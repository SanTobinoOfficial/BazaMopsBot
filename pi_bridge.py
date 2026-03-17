"""
pi_bridge.py v2 – Raspberry Pi 4 Multi-Channel Discord ↔ RF Bridge
=====================================================================

Architektura:
┌──────────────────────────────────────────────────────────────────┐
│                       Raspberry Pi 4                             │
│                                                                  │
│  RF Radio (USB audio wejście)                                    │
│      ↓ squelch (RMS > SQUELCH_RMS)                              │
│      ↓ resample 16kHz mono → 48kHz stereo                       │
│      → StreamingRFSource.feed() na KAŻDYM bocie jednocześnie    │
│        Bot1 → głosowy Discord #radio-1                          │
│        Bot2 → głosowy Discord #radio-2    (broadcast)           │
│        Bot3 → głosowy Discord #alpha-1    ...                   │
│                                                                  │
│  Discord Voice (dowolny kanał)                                   │
│      ↓ DiscordRxSink.write() odbiera 48kHz stereo PCM           │
│      ↓ VAD (RMS > SQUELCH_RMS)                                  │
│      ↓ resample 48kHz stereo → 16kHz mono                       │
│      → asyncio.PriorityQueue (PTT kolejka)                       │
│          is_radio_bridge=True → priorytet 0 (pierwsze)          │
│          pozostałe kanały  → priorytet 1 (FIFO)                 │
│                                                                  │
│  PTT worker (asyncio)                                            │
│      → GPIO HIGH → USB audio out → GPIO LOW → 200ms przerwa    │
│      (jedno nadawanie na raz — jedna fizyczna krótkofalówka)     │
└──────────────────────────────────────────────────────────────────┘

Wymagania (pip):
  discord.py>=2.3.0
  PyAudio>=0.2.11
  python-dotenv>=1.0.0
  RPi.GPIO           ← tylko na Raspberry Pi
  # audioop jest w stdlib Python 3.x (do 3.12), nie wymaga instalacji

Zmienne środowiskowe (.env):
  GUILD_ID           ID serwera Discord (integer)
  SERVER_URL         http://localhost:5000 (do pobrania konfiguracji kanałów)
  AUDIO_INPUT_IDX    indeks urządzenia wejściowego PyAudio (USB audio z radia)
  AUDIO_OUTPUT_IDX   indeks urządzenia wyjściowego PyAudio (USB audio do radia)
  GPIO_PTT_PIN       pin BCM GPIO tranzystora PTT (domyślnie 17)
  SQUELCH_RMS        próg RMS detekcji sygnału (domyślnie 300)
  SILENCE_FRAMES     liczba cichych klatek przed końcem nadawania (domyślnie 12)
  PTT_GAP_MS         przerwa ms między transmisjami PTT (domyślnie 200)
  LOG_LEVEL          DEBUG/INFO/WARNING (domyślnie INFO)
"""

import asyncio
import audioop
import logging
import os
import queue
import signal
import sys
import threading
import time
from typing import Dict, List, Optional

from dotenv import load_dotenv

load_dotenv()

# ─── Logging ──────────────────────────────────────────────────────────────────

_log_level = getattr(logging, os.environ.get('LOG_LEVEL', 'INFO').upper(), logging.INFO)
logging.basicConfig(
    level=_log_level,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%H:%M:%S',
)
log = logging.getLogger('pi_bridge')

# ─── Configuration ────────────────────────────────────────────────────────────

GUILD_ID         = int(os.environ.get('GUILD_ID',         '0'))
SERVER_URL       = os.environ.get('SERVER_URL',           'http://127.0.0.1:5000')
AUDIO_INPUT_IDX  = int(os.environ.get('AUDIO_INPUT_IDX',  '0'))
AUDIO_OUTPUT_IDX = int(os.environ.get('AUDIO_OUTPUT_IDX', '0'))
GPIO_PTT_PIN     = int(os.environ.get('GPIO_PTT_PIN',      '17'))
SQUELCH_RMS      = int(os.environ.get('SQUELCH_RMS',       '300'))
SILENCE_FRAMES   = int(os.environ.get('SILENCE_FRAMES',    '12'))
PTT_GAP_MS       = int(os.environ.get('PTT_GAP_MS',        '200'))

# Audio constants
RADIO_RATE    = 16000  # USB audio (krótkofalówka)
DISCORD_RATE  = 48000  # Discord zawsze 48 kHz
RADIO_CH      = 1      # mono
DISCORD_CH    = 2      # stereo

# Jeden frame Discord = 20ms = 960 próbek stereo = 3840 bajtów
DISCORD_FRAME = 960 * DISCORD_CH * 2   # 3840 bytes
# Jeden frame radio = 20ms = 320 próbek mono = 640 bajtów
RADIO_FRAME   = 320 * RADIO_CH * 2     # 640 bytes

# ─── GPIO ─────────────────────────────────────────────────────────────────────

_gpio_ok = False
try:
    import RPi.GPIO as GPIO  # type: ignore
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(GPIO_PTT_PIN, GPIO.OUT, initial=GPIO.LOW)
    _gpio_ok = True
    log.info(f'GPIO ready – PTT na pinie BCM {GPIO_PTT_PIN}')
except ImportError:
    log.warning('RPi.GPIO niedostępne – PTT nie będzie sterowane (tryb PC)')
except Exception as e:
    log.warning(f'Błąd GPIO: {e}')


def ptt_set(active: bool) -> None:
    """Steruje tranzystorem NPN na linii PTT krótkofalówki."""
    if not _gpio_ok:
        return
    try:
        GPIO.output(GPIO_PTT_PIN, GPIO.HIGH if active else GPIO.LOW)
    except Exception as e:
        log.warning(f'GPIO write error: {e}')


# ─── PyAudio ──────────────────────────────────────────────────────────────────

try:
    import pyaudio
except ImportError:
    log.error('pyaudio nie zainstalowane. Uruchom: pip install PyAudio')
    sys.exit(1)

_pa: pyaudio.PyAudio = None  # tworzony w głównym wątku asyncio przez run_in_executor


# ─── Streaming audio source (RF → Discord) ────────────────────────────────────

import discord  # noqa: E402 (import after env setup)


class StreamingRFSource(discord.AudioSource):
    """
    Kontinuuje streaming audio RF (po próbkowaniu na 48kHz stereo) do kanału
    głosowego Discord. Bufor thread-safe — feed() wywoływane z wątku przechwytywania.
    Zwraca ciszę gdy brak danych, nigdy nie kończy odtwarzania.
    """

    def __init__(self):
        # threading.Queue jest thread-safe bez żadnych locków
        self._q: queue.Queue[bytes] = queue.Queue(maxsize=300)  # ~6s bufor

    def feed(self, pcm48k_stereo: bytes) -> None:
        """Podaj ramkę 48kHz stereo PCM16LE. Wywołaj z dowolnego wątku."""
        # Podziel na ramki o rozmiarze DISCORD_FRAME
        for off in range(0, len(pcm48k_stereo), DISCORD_FRAME):
            chunk = pcm48k_stereo[off:off + DISCORD_FRAME]
            if len(chunk) < DISCORD_FRAME:
                chunk = chunk.ljust(DISCORD_FRAME, b'\x00')
            try:
                self._q.put_nowait(chunk)
            except queue.Full:
                try:
                    self._q.get_nowait()  # wyrzuć najstarszą ramkę
                    self._q.put_nowait(chunk)
                except queue.Empty:
                    pass

    def read(self) -> bytes:
        """Wywoływane przez discord.py co 20ms z wątku kodera."""
        try:
            return self._q.get_nowait()
        except queue.Empty:
            return b'\x00' * DISCORD_FRAME  # cisza

    def is_opus(self) -> bool:
        return False

    def cleanup(self) -> None:
        while not self._q.empty():
            try:
                self._q.get_nowait()
            except queue.Empty:
                break


# ─── Discord audio sink (Discord → PTT queue) ─────────────────────────────────

class DiscordRxSink(discord.AudioSink):
    """
    Odbiera audio z kanału głosowego Discord.
    Wykrywa mowę przez RMS VAD, resampleuje do 16kHz mono,
    a gotowy segment wrzuca do kolejki PTT.
    """

    def __init__(self,
                 channel_name: str,
                 is_priority: bool,
                 ptt_queue: asyncio.PriorityQueue,
                 ptt_counter: 'list[int]',
                 loop: asyncio.AbstractEventLoop):
        self.channel_name = channel_name
        self.is_priority  = is_priority
        self.ptt_queue    = ptt_queue
        self.ptt_counter  = ptt_counter   # [0] – wspólny licznik FIFO
        self.loop         = loop

        self._buf         = bytearray()
        self._silence_cnt = 0
        self._active      = False
        self._state       = None          # stan audioop.ratecv

    def wants_opus(self) -> bool:
        return False

    def write(self, user: Optional[discord.Member], data: discord.VoiceData) -> None:
        """Wywoływane przez discord.py co 20ms dla każdej ramki audio."""
        pcm = data.data
        if not pcm or len(pcm) < DISCORD_FRAME:
            return

        # Resample: 48kHz stereo → 16kHz mono
        try:
            mono = audioop.tomono(pcm, 2, 0.5, 0.5)
            radio_pcm, self._state = audioop.ratecv(
                mono, 2, 1, DISCORD_RATE, RADIO_RATE, self._state
            )
        except Exception:
            return

        rms = audioop.rms(radio_pcm, 2)

        if rms >= SQUELCH_RMS:
            self._silence_cnt = 0
            if not self._active:
                self._active = True
                log.debug(f'[{self.channel_name}] mowa wykryta (RMS={rms:.0f})')
            self._buf.extend(radio_pcm)

            # Wrzucaj do kolejki co ~300ms żeby nie czekać na koniec wypowiedzi
            if len(self._buf) >= RADIO_FRAME * 15:
                self._flush(final=False)
        else:
            if self._active:
                self._buf.extend(radio_pcm)  # dodaj ogon ciszy
                self._silence_cnt += 1
                if self._silence_cnt >= SILENCE_FRAMES:
                    self._active      = False
                    self._silence_cnt = 0
                    self._flush(final=True)

    def _flush(self, final: bool) -> None:
        if not self._buf:
            return
        pcm = bytes(self._buf)
        self._buf.clear()
        priority  = 0 if self.is_priority else 1
        counter   = self.ptt_counter[0]
        self.ptt_counter[0] += 1
        item = (priority, counter, pcm, self.channel_name)
        asyncio.run_coroutine_threadsafe(
            self.ptt_queue.put(item), self.loop
        )
        if final:
            log.debug(f'[{self.channel_name}] segment {len(pcm)}B → kolejka PTT '
                      f'(priorytet={priority})')

    def cleanup(self) -> None:
        if self._buf:
            self._flush(final=True)


# ─── Per-channel Discord bot ───────────────────────────────────────────────────

class ChannelBot:
    """
    Jeden discord.Client na jeden kanał głosowy.
    Siedzi na kanale cały czas:
      - StreamingRFSource odtwarza audio z radia (broadcast)
      - DiscordRxSink zbiera audio Discorda → kolejka PTT
    """

    def __init__(self,
                 ch_cfg: dict,
                 token: str,
                 ptt_queue: asyncio.PriorityQueue,
                 ptt_counter: 'list[int]',
                 loop: asyncio.AbstractEventLoop):
        self.cfg         = ch_cfg
        self.token       = token
        self.name        = ch_cfg['name']
        self.is_priority = bool(ch_cfg.get('is_radio_bridge'))
        self.ptt_queue   = ptt_queue
        self.ptt_counter = ptt_counter
        self.loop        = loop

        self.rf_source: StreamingRFSource = StreamingRFSource()
        self.voice_client: Optional[discord.VoiceClient] = None
        self._sink: Optional[DiscordRxSink] = None

        intents = discord.Intents.default()
        intents.voice_states = True
        self.client = discord.Client(intents=intents)

        @self.client.event
        async def on_ready():
            flag = '🔴 priorytet' if self.is_priority else '🔵 normalny'
            log.info(f'[{self.name}] bot online: {self.client.user}  ({flag})')
            await self._join_voice()

        @self.client.event
        async def on_voice_state_update(member, before, after):
            # Zreconnectuj jeśli wyrzucono naszego bota z kanału
            if member == self.client.user and after.channel is None:
                log.warning(f'[{self.name}] wyrzucony z voice, rekonektuję za 5s…')
                await asyncio.sleep(5)
                await self._join_voice()

    async def _join_voice(self) -> None:
        """Dołącz do skonfigurowanego kanału głosowego i zacznij słuchać + grać."""
        ch_id = self.cfg.get('discord_channel_id')
        if not ch_id:
            log.warning(f'[{self.name}] brak discord_channel_id – pomijam')
            return

        guild = self.client.get_guild(GUILD_ID)
        if not guild:
            log.warning(f'[{self.name}] guild {GUILD_ID} nie znaleziony')
            return

        voice_ch = guild.get_channel(ch_id)
        if not voice_ch:
            log.warning(f'[{self.name}] kanał głosowy {ch_id} nie znaleziony')
            return

        try:
            if self.voice_client and self.voice_client.is_connected():
                await self.voice_client.disconnect(force=True)

            self.voice_client = await voice_ch.connect(self_deaf=False, self_mute=False)

            # Słuchaj Discord → PTT queue
            self._sink = DiscordRxSink(
                channel_name  = self.name,
                is_priority   = self.is_priority,
                ptt_queue     = self.ptt_queue,
                ptt_counter   = self.ptt_counter,
                loop          = self.loop,
            )
            self.voice_client.listen(self._sink)

            # Odtwarzaj RF → Discord (nowe źródło, stare mogło być zatrzymane)
            self.rf_source = StreamingRFSource()
            self.voice_client.play(self.rf_source, after=self._on_play_end)

            log.info(f'[{self.name}] połączony z kanałem głosowym: {voice_ch.name}')

        except Exception as e:
            log.error(f'[{self.name}] błąd łączenia z voice: {e}')

    def _on_play_end(self, error: Optional[Exception]) -> None:
        """Odtwarzanie zatrzymane (błąd lub stop) — uruchom ponownie."""
        if error:
            log.warning(f'[{self.name}] play zakończony z błędem: {error}')
        if self.voice_client and self.voice_client.is_connected():
            asyncio.run_coroutine_threadsafe(self._restart_play(), self.loop)

    async def _restart_play(self) -> None:
        if self.voice_client and self.voice_client.is_connected() \
                and not self.voice_client.is_playing():
            self.rf_source = StreamingRFSource()
            self.voice_client.play(self.rf_source, after=self._on_play_end)

    async def start(self) -> None:
        try:
            await self.client.start(self.token)
        except discord.LoginFailure:
            log.error(f'[{self.name}] nieprawidłowy token Discord')
        except asyncio.CancelledError:
            pass
        except Exception as e:
            log.error(f'[{self.name}] błąd bota: {e}')

    async def stop(self) -> None:
        if self.voice_client:
            try:
                await self.voice_client.disconnect(force=True)
            except Exception:
                pass
        try:
            await self.client.close()
        except Exception:
            pass


# ─── Main bridge ──────────────────────────────────────────────────────────────

class PiBridge:
    """
    Zarządza wszystkimi botami kanałowymi oraz wątkiem przechwytywania radia.
    """

    def __init__(self):
        self.bots:        List[ChannelBot]        = []
        self.ptt_queue:   asyncio.PriorityQueue   = None
        self.ptt_counter: list                    = [0]  # FIFO counter wewnątrz priorytetu
        self.loop:        asyncio.AbstractEventLoop = None
        self._stop        = asyncio.Event()
        self._rf_stop     = threading.Event()

    # ── Ładowanie konfiguracji ───────────────────────────────────────────────

    def _load_channels(self) -> List[dict]:
        """Pobierz kanały z API serwera lub bezpośrednio z bazy danych."""
        # Próba 1: API REST
        try:
            import requests as req
            r = req.get(
                f'{SERVER_URL}/api/guild/{GUILD_ID}/channels',
                timeout=5
            )
            if r.status_code == 200:
                chs = r.json()
                log.info(f'Załadowano {len(chs)} kanałów z API')
                return chs
        except Exception as e:
            log.debug(f'API channels: {e}')

        # Próba 2: bezpośredni import bazy danych (ta sama maszyna)
        try:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            import database as db
            chs = db.get_channels(GUILD_ID)
            log.info(f'Załadowano {len(chs)} kanałów z bazy danych')
            return chs
        except Exception as e:
            log.warning(f'DB channels: {e}')

        return []

    def _get_token(self, ch: dict) -> Optional[str]:
        """Pobierz token Discord bota przypisanego do kanału (przez bot_id = device_id)."""
        bot_id = ch.get('bot_id')
        if not bot_id:
            return None
        try:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            import database as db
            dev = db.get_device(bot_id)
            token = dev.get('bot_token', '').strip() if dev else ''
            return token or None
        except Exception:
            return None

    # ── PTT worker ───────────────────────────────────────────────────────────

    async def _ptt_worker(self) -> None:
        """
        Przetwarza kolejkę PTT – jedno nadawanie na raz.
        Kolejka: (priority, counter, pcm_bytes, source_name)
        """
        log.info('PTT worker uruchomiony')

        # Otwórz wyjście audio w executorze (blokujące)
        try:
            out: pyaudio.Stream = await self.loop.run_in_executor(
                None,
                lambda: _pa.open(
                    format=pyaudio.paInt16,
                    channels=RADIO_CH,
                    rate=RADIO_RATE,
                    output=True,
                    output_device_index=AUDIO_OUTPUT_IDX,
                    frames_per_buffer=RADIO_FRAME // 2,
                )
            )
        except Exception as e:
            log.error(f'PTT wyjście audio: {e}')
            return

        try:
            while True:
                priority, counter, pcm, source = await self.ptt_queue.get()
                log.info(f'[PTT] TX: {source}  priorytet={priority}  '
                         f'{len(pcm) // 2 / RADIO_RATE * 1000:.0f}ms')

                ptt_set(True)
                await asyncio.sleep(0.05)  # 50ms key-up

                # Odtwarzaj w kawałkach – nie blokuj event loop
                for off in range(0, len(pcm), RADIO_FRAME):
                    chunk = pcm[off:off + RADIO_FRAME]
                    await self.loop.run_in_executor(None, out.write, chunk)

                ptt_set(False)
                await asyncio.sleep(PTT_GAP_MS / 1000.0)

        except asyncio.CancelledError:
            pass
        finally:
            ptt_set(False)
            await self.loop.run_in_executor(None, out.close)
            log.info('PTT worker zatrzymany')

    # ── RF capture thread ────────────────────────────────────────────────────

    def _rf_capture_thread(self) -> None:
        """
        Przechwytuje audio z fizycznej krótkofalówki (USB audio wejście).
        Squelch → upsample 16kHz mono → 48kHz stereo → feed() do wszystkich botów.
        Działa w osobnym wątku daemon (PyAudio jest blokujące).
        """
        log.info(f'RF przechwytywanie uruchomione  '
                 f'(squelch={SQUELCH_RMS}, silence_frames={SILENCE_FRAMES})')

        try:
            inp: pyaudio.Stream = _pa.open(
                format=pyaudio.paInt16,
                channels=RADIO_CH,
                rate=RADIO_RATE,
                input=True,
                input_device_index=AUDIO_INPUT_IDX,
                frames_per_buffer=RADIO_FRAME // 2,
            )
        except Exception as e:
            log.error(f'RF wejście audio: {e}')
            return

        silence_cnt   = 0
        transmitting  = False
        up_state      = None  # stan audioop.ratecv

        try:
            while not self._rf_stop.is_set():
                try:
                    raw = inp.read(RADIO_FRAME // 2, exception_on_overflow=False)
                except Exception as e:
                    log.warning(f'RF read: {e}')
                    time.sleep(0.02)
                    continue

                rms = audioop.rms(raw, 2)

                if rms >= SQUELCH_RMS:
                    silence_cnt = 0
                    if not transmitting:
                        transmitting = True
                        log.debug(f'[RF] sygnał wykryty RMS={rms:.0f}')

                    # 16kHz mono → 48kHz mono → 48kHz stereo
                    up, up_state = audioop.ratecv(
                        raw, 2, 1, RADIO_RATE, DISCORD_RATE, up_state
                    )
                    pcm48k = audioop.tostereo(up, 2, 1, 1)
                    self._rf_broadcast(pcm48k)

                else:
                    if transmitting:
                        silence_cnt += 1
                        if silence_cnt <= SILENCE_FRAMES:
                            # Chwilowe przerwy w mowie – nadal nadawaj (ogon)
                            up, up_state = audioop.ratecv(
                                raw, 2, 1, RADIO_RATE, DISCORD_RATE, up_state
                            )
                            pcm48k = audioop.tostereo(up, 2, 1, 1)
                            self._rf_broadcast(pcm48k)
                        else:
                            transmitting = False
                            silence_cnt  = 0
                            up_state     = None
                            log.debug('[RF] sygnał zakończony')
                    else:
                        up_state = None

        finally:
            inp.close()
            log.info('RF przechwytywanie zatrzymane')

    def _rf_broadcast(self, pcm48k: bytes) -> None:
        """
        Wyślij ramkę PCM48kHz stereo do WSZYSTKICH botów Discord jednocześnie.
        Wywoływane z wątku przechwytywania RF — StreamingRFSource.feed() jest thread-safe.
        """
        for bot in self.bots:
            bot.rf_source.feed(pcm48k)

    # ── Main entry point ─────────────────────────────────────────────────────

    async def run(self) -> None:
        global _pa
        self.loop = asyncio.get_running_loop()
        _pa = pyaudio.PyAudio()

        self.ptt_queue = asyncio.PriorityQueue()

        # Załaduj konfigurację kanałów
        channels = self._load_channels()
        if not channels:
            log.error('Brak kanałów. Dodaj kanały w Dashboard → Kanały PTT.')
            return

        # Utwórz bota dla każdego kanału który ma token
        for ch in sorted(channels, key=lambda c: c.get('order_index', 0)):
            token = self._get_token(ch)
            if not token:
                log.warning(f"Kanał '{ch['name']}': brak tokenu bota (bot_id={ch.get('bot_id')}) – pomijam")
                continue

            bot = ChannelBot(ch, token, self.ptt_queue, self.ptt_counter, self.loop)
            self.bots.append(bot)
            flag = ' [PRIORYTET]' if ch.get('is_radio_bridge') else ''
            log.info(f"Kanał zarejestrowany: {ch['name']}{flag}")

        if not self.bots:
            log.error('Żaden kanał nie ma tokenu bota. '
                      'Przypisz bot_id do kanałów w Dashboard → Kanały PTT.')
            return

        log.info(f'Uruchamianie {len(self.bots)} botów kanałowych…')

        # Uruchom wątek przechwytywania RF
        rf_t = threading.Thread(
            target=self._rf_capture_thread, daemon=True, name='rf_capture'
        )
        rf_t.start()

        # Uruchom asyncio taski
        ptt_task = asyncio.create_task(self._ptt_worker(), name='ptt_worker')
        bot_tasks = [
            asyncio.create_task(bot.start(), name=f'bot_{bot.name}')
            for bot in self.bots
        ]

        log.info('pi_bridge uruchomiony. Ctrl+C aby zatrzymać.')
        await self._stop.wait()

        # Shutdown
        log.info('Zatrzymywanie…')
        ptt_task.cancel()
        for t in bot_tasks:
            t.cancel()
        for bot in self.bots:
            await bot.stop()

        ptt_set(False)
        self._rf_stop.set()
        _pa.terminate()
        if _gpio_ok:
            GPIO.cleanup()  # type: ignore
        log.info('pi_bridge zatrzymany.')

    def request_stop(self) -> None:
        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(self._stop.set)
        else:
            self._stop.set()


# ─── Entry point ──────────────────────────────────────────────────────────────

_bridge = PiBridge()


def _on_signal(sig, frame):
    log.info(f'Sygnał {sig} – zatrzymywanie…')
    _bridge.request_stop()


signal.signal(signal.SIGINT,  _on_signal)
signal.signal(signal.SIGTERM, _on_signal)


if __name__ == '__main__':
    if GUILD_ID == 0:
        log.error('Ustaw GUILD_ID w pliku .env (ID serwera Discord)!')
        sys.exit(1)

    log.info(
        f'pi_bridge v2  guild={GUILD_ID}  server={SERVER_URL}\n'
        f'  audio in={AUDIO_INPUT_IDX}  out={AUDIO_OUTPUT_IDX}\n'
        f'  squelch={SQUELCH_RMS}  silence={SILENCE_FRAMES} frames\n'
        f'  PTT gap={PTT_GAP_MS}ms  GPIO pin={GPIO_PTT_PIN}'
    )
    asyncio.run(_bridge.run())

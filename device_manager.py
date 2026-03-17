"""
Device Manager – zarządza botami Discord reprezentującymi fizyczne urządzenia ESP32.

Każde urządzenie (row w tabeli `devices`) to osobny discord.Client uruchomiony
jako asyncio task w tym samym event loopie co główny bot.

Heartbeat: ESP32 wysyła POST /api/device/heartbeat co 30s.
  - Watcher co 30s sprawdza: jeśli ostatni heartbeat >60s temu → bot → Invisible.
  - Gdy heartbeat nadejdzie dla offline bota → bot → Online.

Użycie z Flask (wątek): run_coroutine_threadsafe(coro, _loop)
"""
import asyncio
import discord
from datetime import datetime, timedelta
import database as db

# Event loop ustawiany przez main.py po starcie asyncio
_loop: asyncio.AbstractEventLoop = None


def set_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _loop
    _loop = loop


# ─── Single device bot ────────────────────────────────────────────────────────

class DeviceBot:
    """Jeden discord.Client na jedno urządzenie fizyczne."""

    def __init__(self, device_id: str, token: str, name: str):
        self.device_id = device_id
        self.token = token
        self.name = name
        intents = discord.Intents.default()
        self.client = discord.Client(intents=intents)
        self._task: asyncio.Task = None
        self.is_online = False

        @self.client.event
        async def on_ready():
            self.is_online = True
            await self._set_presence_online()
            print(f'[Device] {self.name} ({self.device_id}) połączony jako {self.client.user}')

        @self.client.event
        async def on_disconnect():
            self.is_online = False

    async def _set_presence_online(self):
        try:
            await self.client.change_presence(
                status=discord.Status.online,
                activity=discord.Game(name=f'{self.name} – aktywne')
            )
            db.set_device_status(self.device_id, 'online')
        except Exception:
            pass

    async def set_offline(self):
        self.is_online = False
        try:
            if self.client.is_ready():
                await self.client.change_presence(status=discord.Status.invisible)
        except Exception:
            pass
        db.set_device_status(self.device_id, 'offline')

    async def start(self):
        self._task = asyncio.create_task(self._run())

    async def _run(self):
        try:
            await self.client.start(self.token)
        except discord.LoginFailure:
            print(f'[Device] {self.device_id}: nieprawidłowy token – pomijam')
            db.set_device_status(self.device_id, 'offline')
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f'[Device] {self.device_id}: błąd {e}')
            db.set_device_status(self.device_id, 'offline')

    async def stop(self):
        if self._task:
            try:
                await self.client.close()
            except Exception:
                pass
            self._task.cancel()
            self._task = None
        self.is_online = False


# ─── Manager ──────────────────────────────────────────────────────────────────

class DeviceBotManager:
    def __init__(self):
        self.bots: dict[str, DeviceBot] = {}
        self._watcher_task: asyncio.Task = None

    async def start_all(self):
        """Ładuje wszystkie urządzenia z DB i startuje ich boty."""
        for d in db.get_all_devices():
            token = d.get('bot_token', '').strip()
            if token:
                await self._start_bot(d['device_id'], token, d['name'])
        self._watcher_task = asyncio.create_task(self._heartbeat_watcher())

    async def _start_bot(self, device_id: str, token: str, name: str):
        if device_id in self.bots:
            await self.bots[device_id].stop()
        bot = DeviceBot(device_id, token, name)
        self.bots[device_id] = bot
        await bot.start()

    async def restart_bot(self, device_id: str):
        """Zatrzymaj i uruchom ponownie bota dla danego urządzenia."""
        d = db.get_device(device_id)
        if not d:
            return
        token = d.get('bot_token', '').strip()
        if token:
            await self._start_bot(device_id, token, d['name'])
        else:
            await self.remove_bot(device_id)

    async def remove_bot(self, device_id: str):
        if device_id in self.bots:
            await self.bots[device_id].stop()
            del self.bots[device_id]

    async def _heartbeat_watcher(self):
        """Co 30s sprawdza czy urządzenia nie straciły heartbeatu (>60s = offline)."""
        while True:
            await asyncio.sleep(30)
            cutoff = (datetime.now() - timedelta(seconds=60)).isoformat()
            for device_id, bot in list(self.bots.items()):
                d = db.get_device(device_id)
                if not d:
                    continue
                lhb = d.get('last_heartbeat') or ''
                if d.get('status') == 'online' and lhb < cutoff:
                    await bot.set_offline()

    # ── Metody wywoływane z wątku Flask (thread-safe) ─────────────────────────

    def on_heartbeat(self, device_id: str):
        """Wywołaj gdy API otrzyma heartbeat. Aktualizuje DB + ewentualnie status bota."""
        db.update_device_heartbeat(device_id)
        d = db.get_device(device_id)
        if not d:
            return
        bot = self.bots.get(device_id)
        if bot and not bot.is_online and _loop and _loop.is_running():
            asyncio.run_coroutine_threadsafe(bot._set_presence_online(), _loop)

    def schedule_restart(self, device_id: str):
        """Restartuje bota z wątku Flask."""
        if _loop and _loop.is_running():
            asyncio.run_coroutine_threadsafe(self.restart_bot(device_id), _loop)

    def schedule_remove(self, device_id: str):
        """Usuwa bota z wątku Flask."""
        if _loop and _loop.is_running():
            asyncio.run_coroutine_threadsafe(self.remove_bot(device_id), _loop)


# Global singleton – importowany przez main.py i dashboard/app.py
device_manager = DeviceBotManager()

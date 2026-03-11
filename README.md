# 🛡️ SerwerDiscordBazaMops – System Rang Discord

> **Dla AI (Replit Agent / Ghostwriter):** Ten plik opisuje pełną architekturę projektu.
> Czytaj go przed wprowadzaniem jakichkolwiek zmian w kodzie.

---

## Czym jest ten projekt?

Discord bot napisany w Pythonie z:
- **Systemem aktywności** opartym na Clock In / Clock Out (przyciski w embedzie)
- **Systemem rang** – automatyczne (za punkty) i specjalne (nadawane przez admina)
- **Panelem webowym (dashboard)** – Flask, Bootstrap 5, dark theme
- **Hostingiem na Replit** – jeden proces uruchamia bota i dashboard jednocześnie

---

## Struktura plików

```
main.py                     ← ENTRY POINT. Startuje wątek Flask + asyncio bot
database.py                 ← WSZYSTKIE operacje SQLite. Importowany wszędzie.
discord_bot.py              ← Klasa BotMops (commands.Bot). Ładuje 3 cogi.

cogs/
  clockin.py                ← ClockView (persistent buttons), daily embed task, .apel
  admin.py                  ← AdminCog – komendy admina z prefix "."
  user.py                   ← UserCog – komendy użytkownika z prefix "."

dashboard/
  app.py                    ← Flask app. Wszystkie routes. Auth przez session.
  templates/
    base.html               ← Layout sidebar + Bootstrap 5 dark theme
    login.html              ← Strona logowania (hasło z env DASHBOARD_PASSWORD)
    index.html              ← Wybór serwera (gdy bot jest na wielu serwerach)
    guild.html              ← Przegląd serwera: stats, top5, aktywni, transakcje
    users.html              ← Lista wszystkich użytkowników z wyszukiwarką
    user_detail.html        ← Profil: punkty, rangi, historia, akcje admina
    ranks.html              ← CRUD rang z modalami Bootstrap
    config.html             ← Konfiguracja: kanały, pkt/h, role adminów

data/
  bot.db                    ← SQLite (tworzony automatycznie przy pierwszym uruchomieniu)

requirements.txt            ← discord.py==2.3.2, Flask==3.0.3, requests, python-dotenv
.replit                     ← run = python main.py, port 5000→80
.env.example                ← Wzór zmiennych środowiskowych
replit.md                   ← Instrukcja konfiguracji dla człowieka
```

---

## Zmienne środowiskowe (Replit Secrets)

| Zmienna | Wymagana | Opis |
|---------|----------|------|
| `DISCORD_TOKEN` | ✅ | Token bota z Discord Developer Portal |
| `DASHBOARD_SECRET` | ✅ | Losowy string – klucz sesji Flask |
| `DASHBOARD_PASSWORD` | ✅ | Hasło logowania do dashboardu |
| `PORT` | ❌ | Port Flask, domyślnie `5000` |

---

## Architektura – jak to działa

### Uruchomienie (`main.py`)
```
main()
 ├── db.init_db()                   ← tworzy tabele SQLite jeśli nie istnieją
 ├── threading.Thread(run_dashboard) ← Flask w osobnym wątku (daemon)
 └── asyncio.run(run_bot())         ← discord.py w głównej pętli asyncio
```

Flask i bot dzielą tę samą bazę SQLite. Flask używa sync `sqlite3`, bot wrapuje
operacje przez `asyncio` (database.py jest synchroniczny – thread-safe z `threading.Lock`).

### Bot (`discord_bot.py` + `cogs/`)

Bot NIE używa discord.py's built-in command system (`@bot.command`).
Zamiast tego każdy cog nasłuchuje `on_message` i ręcznie parsuje prefix `.`:

```python
@commands.Cog.listener()
async def on_message(self, message):
    if not message.content.startswith('.'): return
    cmd = message.content[1:].split()[0].lower()
    if cmd in self._handlers:
        await self._handlers[cmd](message, args)
```

**Sprawdzanie uprawnień admina** (w `admin.py`):
1. `message.author.guild_permissions.administrator` → zawsze ma dostęp
2. Dowolna rola z listy `guilds.admin_role_ids` (JSON array) → ma dostęp

### Clock In/Out (`cogs/clockin.py`)

```
@tasks.loop(time=00:00:00 UTC)          ← odpala się codziennie o północy
  → _post_daily_embeds()
      → dla każdego serwera z ustawionym clock_channel_id
          → wysyła Embed z ClockView
          → zapisuje message_id do daily_embeds

ClockView(ui.View, timeout=None)        ← PERSISTENT (przeżywa restart bota)
  custom_id='clock_in_btn'
  custom_id='clock_out_btn'
  → db.clock_in() / db.clock_out()
  → ephemeral response dla użytkownika
  → _check_rank_up() → awans + rola Discord
```

Po restarcie bota `setup_hook()` wywołuje `bot.add_view(ClockView())` –
dzięki temu przyciski na starych wiadomościach nadal działają.

### Dashboard (`dashboard/app.py`)

Flask z session-based auth. Wszystkie route'y poza `/login` i `/ping`
są chronione dekoratorem `@login_required`.

Discord API jest odpytywane przez `requests` (sync) z bot tokenem –
do pobierania nazw serwerów, kanałów, ról i avatarów.

```
GET  /                                  ← lista serwerów / redirect
GET  /guild/<id>                        ← przegląd serwera
GET  /guild/<id>/users                  ← lista użytkowników
GET  /guild/<id>/users/<uid>            ← profil użytkownika
POST /guild/<id>/users/<uid>/addpoints  ← dodaj/odejmij punkty
POST /guild/<id>/users/<uid>/setpoints  ← ustaw punkty
POST /guild/<id>/users/<uid>/ban        ← zablokuj na lb
POST /guild/<id>/users/<uid>/unban      ← odblokuj
POST /guild/<id>/users/<uid>/reset      ← resetuj dane
POST /guild/<id>/users/<uid>/giverank   ← nadaj rangę specjalną
POST /guild/<id>/users/<uid>/takerank/<rid> ← odbierz rangę
GET  /guild/<id>/ranks                  ← lista rang
POST /guild/<id>/ranks/create           ← utwórz rangę
POST /guild/<id>/ranks/<rid>/edit       ← edytuj rangę
POST /guild/<id>/ranks/<rid>/delete     ← usuń rangę
GET  /guild/<id>/config                 ← konfiguracja
POST /guild/<id>/config                 ← zapisz konfigurację
GET  /ping                              ← keep-alive (bez auth)
```

---

## Baza danych (`database.py`)

Plik: `data/bot.db` (SQLite, WAL mode, threading.Lock na zapisy)

### Tabele

#### `guilds`
| Kolumna | Typ | Opis |
|---------|-----|------|
| `guild_id` | INTEGER PK | ID serwera Discord |
| `clock_channel_id` | INTEGER | ID kanału na daily embed |
| `log_channel_id` | INTEGER | ID kanału logów |
| `admin_role_ids` | TEXT | JSON array ID ról adminów, np. `[123, 456]` |
| `points_per_hour` | REAL | Punkty za godzinę, domyślnie `10.0` |
| `min_clock_minutes` | INTEGER | Min. czas sesji dla punktów, domyślnie `5` |

#### `users`
| Kolumna | Typ | Opis |
|---------|-----|------|
| `user_id, guild_id` | PK | Klucz złożony |
| `points` | REAL | Aktualne punkty |
| `total_hours` | REAL | Suma godzin wszystkich sesji |
| `sessions_count` | INTEGER | Liczba ukończonych sesji |
| `is_banned` | INTEGER | 0/1 – zablokowany na lb |
| `is_clocked_in` | INTEGER | 0/1 – czy aktualnie zalogowany |
| `clock_in_time` | TEXT | ISO timestamp ostatniego clock in |

#### `ranks`
| Kolumna | Typ | Opis |
|---------|-----|------|
| `id` | INTEGER PK | |
| `guild_id` | INTEGER | |
| `name` | TEXT | Unikalna w obrębie serwera (UNIQUE guild_id+name) |
| `required_points` | REAL | Próg punktów (0 dla rang specjalnych) |
| `role_id` | INTEGER | ID roli Discord (opcjonalnie) |
| `color` | TEXT | Hex kolor, np. `#7289da` |
| `icon` | TEXT | Emoji, np. `⭐` |
| `is_special` | INTEGER | 0=automatyczna, 1=specjalna (tylko admin) |

#### `user_special_ranks`
Łączy użytkownika z rangą specjalną. Zawiera `assigned_by` i `note`.
Usuwana kaskadowo gdy ranga jest usuwana.

#### `clock_sessions`
Każda sesja (jeden clock in → clock out). Zawiera `hours_worked` i `points_earned`.
Niezakończone sesje mają `clock_out_time = NULL`.

#### `point_transactions`
Historia każdej zmiany punktów. Zawiera `points_before`, `points_after`,
`transaction_type` (`clock`/`manual`/`set`) i `note`.

#### `daily_embeds`
Zapisuje `message_id` dziennego embeda per serwer per data.
Zapobiega wysyłaniu duplikatów.

---

## System rang

### Automatyczne rangi
- Przypisywane na podstawie progu punktów (`required_points`)
- `db.get_user_auto_rank()` → zwraca najwyższą rangę, na którą stać użytkownika
- Po każdym clock out sprawdzany jest awans: `_check_rank_up()` w `clockin.py`
- Przy awansie: stara rola Discord usuwana, nowa dodawana, embed na kanale clock

### Specjalne rangi
- `is_special=1` w tabeli `ranks`
- Tylko admini mogą nadawać przez `.giverank` lub dashboard
- Wyświetlane osobno w `.rank`, `.profile`, `user_detail.html`

---

## Komendy bota

### Użytkownik (każdy może używać)
```
.help                    lista komend
.points [@user]          punkty i postęp do następnej rangi
.rank [@user]            ranga automatyczna + specjalne
.lb / .leaderboard       top 10 (wyklucza zablokowanych)
.history                 ostatnie 10 sesji clock
.profile [@user]         pełny profil (rangi + sesje + stats)
.clock                   czy jesteś zalogowany + szacowane punkty
```

### Admin (wymaga admin_role lub Discord administrator)
```
.ban @user               zablokuj z rankingu (is_banned=1)
.unban @user             odblokuj z rankingu
.addpoints @user <n> [nota]
.removepoints @user <n> [nota]
.setpoints @user <n> [nota]
.giverank @user <nazwa rangi> [nota]     tylko rangi is_special=1
.takerank @user <nazwa rangi>
.createrank <nazwa> <punkty|SPECIAL> [ikona] [#kolor] [opis]
.deleterank <nazwa>
.editrank <nazwa> <pole> <wartość>       pola: name/points/icon/color/description
.ranks                   lista wszystkich rang (auto + specjalne)
.userinfo [@user]        szczegółowy profil (z historią transakcji)
.forceclockout @user     wymuś clock out (bez punktów)
.resetuser @user         zeruje punkty, godziny, sesje, rangi specjalne
.serverstats             statystyki całego serwera
.setchannel <clock|log> #kanał
.setpoints_h <n>         punkty za godzinę
.adminrole @rola         dodaj rolę admina bota
.removeadminrole @rola
.config                  pokaż aktualną konfigurację
.apel                    wymuś wysłanie daily embeda na bieżący kanał
```

---

## Ważne zasady przy modyfikacji kodu

1. **Operacje zapisu do DB** muszą używać `with _lock:` w `database.py`
2. **Nie używaj** `bot.loop.run_until_complete()` z Flask – Flask jest w osobnym wątku
3. **Persistent views** – po każdej zmianie `ClockView` upewnij się, że `custom_id` buttonów nie zmienił się (inaczej stare przyciski przestaną działać)
4. **Discord API w Flask** – używaj `requests` (sync), nie discord.py (async)
5. **Rangi specjalne** – tylko `is_special=1` można nadać przez `.giverank`; automatycznych (`is_special=0`) nie można
6. **SQLite** – nie używaj `aiosqlite` – cała baza jest synchroniczna z lockami

---

## Uruchomienie lokalne

```bash
cp .env.example .env
# uzupełnij .env

pip install -r requirements.txt
python main.py
```

Dashboard: http://localhost:5000

---

## Keep-alive na Replit

Endpoint `/ping` zwraca `"OK"` bez autoryzacji.
Ustaw UptimeRobot na `https://twoja-nazwa.replit.app/ping` co 5 minut.

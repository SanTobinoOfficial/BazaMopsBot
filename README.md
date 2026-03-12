# 🛡️ SerwerDiscordBazaMops – System Rang Discord

> **Dla AI (Replit Agent / Ghostwriter):** Ten plik opisuje **pełną architekturę projektu**.
> Czytaj go przed wprowadzaniem jakichkolwiek zmian w kodzie.
> Wersja 2.0 – zawiera wszystkie funkcje z drugiej iteracji.

---

## Czym jest ten projekt?

Discord bot napisany w Pythonie z:
- **Systemem aktywności** opartym na Clock In / Clock Out (przyciski w embedzie)
- **Systemem rang** – automatyczne (za punkty), specjalne (admin), UNIT (tylko właściciel)
- **Anty-cheat** – wykrywa wielogodzinne sesje, daje warna, bany po 3 warnach
- **Zaawansowanymi logami** – embed w kanale logów + tabela `action_logs`
- **Panelem komend** – trwały embed z przyciskami i modalami w dedykowanym kanale
- **Panelem webowym (dashboard)** – Flask, Bootstrap 5, dark theme
- **Ogłoszeniami** – compose i wysyłka embed/text z dashboardu
- **Uprawnieniami per-komenda** – każda komenda może mieć przypisane role
- **Harmonogramem 7-dniowym** – godzina apelu konfigurowana osobno na każdy dzień
- **Hostingiem na Replit** – jeden proces uruchamia bota i dashboard jednocześnie

---

## Struktura plików

```
main.py                     ← ENTRY POINT. Startuje wątek Flask + asyncio bot
database.py                 ← WSZYSTKIE operacje SQLite. Importowany wszędzie.
discord_bot.py              ← Klasa BotMops (commands.Bot). Ładuje 4 cogi.

cogs/
  clockin.py                ← ClockView (persistent), schedule_task (minutowy), anti_cheat_task
  admin.py                  ← AdminCog – komendy admina z prefix "."
  user.py                   ← UserCog – komendy użytkownika z prefix "."
  panel.py                  ← PanelCog – UserPanelView, AdminPanelView + Modale

dashboard/
  app.py                    ← Flask app. Wszystkie routes. Auth przez session.
  templates/
    base.html               ← Layout sidebar + Bootstrap 5 dark theme + nowe linki nav
    login.html              ← Strona logowania
    index.html              ← Wybór serwera
    guild.html              ← Przegląd + ostatnie warny + transakcje
    users.html              ← Lista użytkowników z wyszukiwarką
    user_detail.html        ← Profil: punkty, rangi, historia, akcje
    ranks.html              ← CRUD rang (AUTO/SPECIAL/UNIT)
    config.html             ← Konfiguracja: kanały, pkt/h, harmonogram, anty-cheat, panel
    permissions.html        ← Uprawnienia per-komenda (role checkboxy)
    logs.html               ← Logi akcji / warny / transakcje (3 zakładki)
    announcements.html      ← Compose ogłoszenia + historia

data/
  bot.db                    ← SQLite (tworzony automatycznie)

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
 ├── db.init_db()                   ← tworzy tabele + _run_migrations()
 ├── threading.Thread(run_dashboard) ← Flask w osobnym wątku (daemon)
 └── asyncio.run(run_bot())         ← discord.py w głównej pętli asyncio
```

Flask i bot dzielą tę samą bazę SQLite. Flask używa sync `sqlite3`,
bot wrapuje operacje przez `asyncio`. Baza jest synchroniczna z `threading.Lock`.

### Migracje bazy danych (`database.py` → `_run_migrations()`)

Przy każdym starcie `_run_migrations()` sprawdza czy nowe kolumny istnieją
i dodaje je jeśli nie. Dzięki temu stara baza `bot.db` działa z nowym kodem:

```python
def _run_migrations():
    # każdy ALTER TABLE owinięty w try/except OperationalError
    # – bezpieczne dla istniejących baz danych
```

### Bot (`discord_bot.py` + `cogs/`)

Bot NIE używa discord.py's built-in command system (`@bot.command`).
Każdy cog nasłuchuje `on_message` i ręcznie parsuje prefix `.`.

W `setup_hook()` rejestrowane są 3 persistent views:
```python
bot.add_view(ClockView())       # custom_id: 'mops_clock_in', 'mops_clock_out'
bot.add_view(UserPanelView())   # custom_id: 'panel_user_*'
bot.add_view(AdminPanelView())  # custom_id: 'panel_admin_*'
```

**KRYTYCZNE:** `custom_id` przycisków NIGDY nie może się zmienić – inaczej stare
wiadomości na Discordzie przestaną działać.

### Sprawdzanie uprawnień

**Komendy admina** (`admin.py` → `_can_use_cmd()`):
1. `command_permissions` tabela → jeśli jest wpis, sprawdza role użytkownika
2. Fallback: `guild.administrator` lub `admin_role_ids`

**Rangi UNIT** (`admin.py` → `_can_grant_rank()`):
1. `rank.is_owner_only = 1` → tylko właściciel serwera lub skonfigurowany `owner_id`
2. `rank.grant_role_ids` → jeśli ustawione, tylko te role mogą nadawać
3. Fallback: admin

### Clock In/Out (`cogs/clockin.py`)

```
schedule_task (tasks.loop minutowy)
 → dla każdego serwera sprawdza JSON embed_schedule[weekday].{hour, minute, enabled}
 → wysyła Embed z ClockView gdy czas się zgadza (deduplication przez _last_embed_check)

anti_cheat_task (tasks.loop co 30 min)
 → db.get_suspicious_users(guild_id, max_hours=auto_clockout_hours)
 → force clock out + ostrzeżenie w kanale
 → db.add_warning() → jeśli >= warn_limit: db.ban_user()
 → log_action() + send_log() embed
```

### Panel komend (`cogs/panel.py`)

```
UserPanelView (persistent, timeout=None)
  custom_id='panel_user_points'    → ephemeralne info o punktach
  custom_id='panel_user_rank'      → ephemeralna ranga
  custom_id='panel_user_lb'        → ephemeralne top 10
  custom_id='panel_user_history'   → ephemeralna historia sesji
  custom_id='panel_user_profile'   → ephemeralne pełne info
  custom_id='panel_user_status'    → czy zalogowany

AdminPanelView (persistent, timeout=None)
  custom_id='panel_admin_points'   → otwiera AddPointsModal
  custom_id='panel_admin_rank'     → otwiera GiveRankModal
  custom_id='panel_admin_warn'     → otwiera WarnModal
  custom_id='panel_admin_info'     → otwiera UserInfoModal
  custom_id='panel_admin_stats'    → ephemeralne statystyki serwera
```

Aby wysłać/odświeżyć panel: `.panel` w wybranym kanale.
Możliwe też przez konfigurację `command_panel_channel_id` w dashboardzie.

### Dashboard (`dashboard/app.py`)

Flask z session-based auth. Wszystkie route'y poza `/login` i `/ping`
chronione dekoratorem `@login_required`.

Discord API przez `requests` (sync) z bot tokenem.

```
GET  /                                  ← lista serwerów / redirect
GET  /guild/<id>                        ← przegląd + ostanie warny
GET  /guild/<id>/users                  ← lista użytkowników
GET  /guild/<id>/users/<uid>            ← profil użytkownika
POST /guild/<id>/users/<uid>/addpoints
POST /guild/<id>/users/<uid>/setpoints
POST /guild/<id>/users/<uid>/ban
POST /guild/<id>/users/<uid>/unban
POST /guild/<id>/users/<uid>/reset
POST /guild/<id>/users/<uid>/giverank
POST /guild/<id>/users/<uid>/takerank/<rid>
POST /guild/<id>/users/<uid>/warn       ← nowe
POST /guild/<id>/users/<uid>/clearwarn  ← nowe
GET  /guild/<id>/ranks
POST /guild/<id>/ranks/create           ← obsługuje type=AUTO/SPECIAL/UNIT
POST /guild/<id>/ranks/<rid>/edit
POST /guild/<id>/ranks/<rid>/delete
GET  /guild/<id>/config
POST /guild/<id>/config                 ← zapisuje 7-dniowy harmonogram
GET  /guild/<id>/permissions            ← nowe
POST /guild/<id>/permissions            ← nowe
GET  /guild/<id>/announcements          ← nowe
POST /guild/<id>/announcements/send     ← nowe (wysyła przez Discord API)
GET  /guild/<id>/logs                   ← nowe (tab: actions/warnings/transactions)
GET  /ping                              ← keep-alive (bez auth)
```

---

## Baza danych (`database.py`)

Plik: `data/bot.db` (SQLite, WAL mode, `threading.Lock` na zapisy)

### Wszystkie tabele

#### `guilds`
| Kolumna | Typ | Opis |
|---------|-----|------|
| `guild_id` | INTEGER PK | |
| `clock_channel_id` | INTEGER | Kanał daily embed |
| `log_channel_id` | INTEGER | Kanał logów |
| `command_panel_channel_id` | INTEGER | Kanał panelu przycisków |
| `admin_role_ids` | TEXT | JSON `[id, ...]` |
| `points_per_hour` | REAL | default 10.0 |
| `min_clock_minutes` | INTEGER | default 5 |
| `embed_schedule` | TEXT | JSON 7 elementów `[{hour, minute, enabled}, ...]` |
| `auto_clockout_hours` | INTEGER | Max godzin sesji (anty-cheat), default 12 |
| `warn_limit` | INTEGER | Warny przed banem, default 3 |
| `owner_id` | INTEGER | Dodatkowy właściciel dla rang UNIT |

#### `users`
| Kolumna | Typ | Opis |
|---------|-----|------|
| `user_id, guild_id` | PK | |
| `points` | REAL | |
| `total_hours` | REAL | |
| `sessions_count` | INTEGER | |
| `is_banned` | INTEGER | 0/1 |
| `is_clocked_in` | INTEGER | 0/1 |
| `clock_in_time` | TEXT | ISO timestamp |
| `username` | TEXT | Nazwa Discord |
| `display_name` | TEXT | Wyświetlana nazwa |

#### `ranks`
| Kolumna | Typ | Opis |
|---------|-----|------|
| `id` | INTEGER PK | |
| `guild_id` | INTEGER | |
| `name` | TEXT | UNIQUE per guild |
| `required_points` | REAL | 0 dla SPECIAL/UNIT |
| `role_id` | INTEGER | ID roli Discord |
| `color` | TEXT | Hex `#rrggbb` |
| `icon` | TEXT | Emoji |
| `description` | TEXT | |
| `is_special` | INTEGER | 0=AUTO, 1=SPECIAL/UNIT |
| `is_owner_only` | INTEGER | 1 = tylko właściciel może nadać (UNIT) |
| `grant_role_ids` | TEXT | JSON `[id, ...]` – role mogące nadawać |

#### `user_special_ranks`
Łączy użytkownika z rangą specjalną (assigned_by, note, assigned_at).

#### `clock_sessions`
Sesje clock in/out. Kolumna `flagged` = 1 gdy oznaczona przez anty-cheat.

#### `point_transactions`
Historia zmian punktów (clock/manual/set).

#### `daily_embeds`
Deduplication dziennych embedów (guild_id + date → message_id).

#### `warnings` ← NOWE
| Kolumna | Opis |
|---------|------|
| `user_id, guild_id` | Kto dostał warna |
| `reason` | Powód |
| `warned_by` | ID kto dał warna |
| `created_at` | Timestamp |

#### `command_permissions` ← NOWE
| Kolumna | Opis |
|---------|------|
| `guild_id, command_name` | PK złożony |
| `role_ids` | JSON `[id, ...]` |

#### `announcements` ← NOWE
Archiwum wysłanych ogłoszeń (channel_id, content, embed_title, embed_color, announce_type).

#### `action_logs` ← NOWE
| Kolumna | Opis |
|---------|------|
| `guild_id` | |
| `action_type` | clock_in/clock_out/points/rank/warn/ban/anti_cheat/... |
| `actor_id` | Kto wykonał akcję |
| `details` | JSON z dodatkowymi danymi |
| `created_at` | Timestamp |

#### `panel_embeds` ← NOWE
Przechowuje message_id panelu na każdym serwerze.

---

## Typy rang

| Typ | `is_special` | `is_owner_only` | Kto nadaje | Jak |
|-----|-------------|-----------------|------------|-----|
| **AUTO** | 0 | 0 | System automatycznie | Próg punktów |
| **SPECIAL** | 1 | 0 | Admin bota | `.giverank`, dashboard |
| **UNIT** | 1 | 1 | Właściciel serwera / owner_id | `.giverank`, dashboard |

---

## Komendy bota

### Użytkownik (`.help` pokazuje listę)
```
.help                    lista komend
.points [@user]          punkty i postęp
.rank [@user]            ranga + specjalne (🎖) + jednostki (👑)
.lb / .leaderboard       top 10 (bez zablokowanych)
.history                 ostatnie sesje clock
.profile [@user]         pełny profil
.clock                   aktualny status
```

### Admin (wymaga roli admina lub Discord administrator)
```
.ban / .unban @user
.addpoints @user <n> [nota]
.removepoints @user <n> [nota]
.setpoints @user <n> [nota]
.giverank @user <ranga> [nota]
.takerank @user <ranga>
.createrank <nazwa> <punkty|SPECIAL|UNIT> [ikona] [#kolor]
.deleterank / .editrank / .ranks
.warn @user [powód]              ← nowe
.warnings @user                  ← nowe
.clearwarn @user [nr]            ← nowe
.setowner @user                  ← nowe (owner_id)
.setwarnlimit <n>                ← nowe
.setmaxhours <n>                 ← nowe
.userinfo @user
.forceclockout @user
.resetuser @user
.serverstats
.setchannel <clock|log|panel> #kanał
.setpoints_h <n>
.adminrole / .removeadminrole @rola
.config
.apel
.panel                           ← wysyła/odświeża embed panelu komend
```

---

## Ważne zasady przy modyfikacji kodu

1. **Operacje zapisu do DB** muszą używać `with _lock:` w `database.py`
2. **Nie używaj** `bot.loop.run_until_complete()` z Flask – Flask jest w osobnym wątku
3. **Persistent views** – `custom_id` buttonów NIE może się zmienić między restartami
4. **Discord API w Flask** – używaj `requests` (sync), nie discord.py (async)
5. **Rangi UNIT** – `is_owner_only=1` sprawdzany przez `_is_server_owner()`, nie przez role admina
6. **SQLite** – nie używaj `aiosqlite` – cała baza jest synchroniczna z lockami
7. **Migracje** – nowe kolumny dodawaj w `_run_migrations()` z try/except, nie w `CREATE TABLE`
8. **Logi** – każda akcja admina powinna wywoływać `send_log()` + `db.log_action()`
9. **Anty-cheat** – `anti_cheat_task` działa co 30 minut; `auto_clockout_hours` per guild

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

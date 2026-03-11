# 🛡️ Baza Mops – Discord Bot z Systemem Rang

Discord bot z systemem aktywności (clock in/out), rangami, leaderboardem i dashboardem webowym.

## ⚙️ Konfiguracja na Replit

### 1. Zmienne środowiskowe (Secrets)

Wejdź w **Tools → Secrets** i dodaj:

| Zmienna              | Wartość                        | Opis                              |
|----------------------|--------------------------------|-----------------------------------|
| `DISCORD_TOKEN`      | `Bot token z Discord Dev Portal` | Token bota Discord              |
| `DASHBOARD_SECRET`   | `losowy_ciag_32+_znakow`       | Klucz sesji Flask                 |
| `DASHBOARD_PASSWORD` | `twoje_haslo`                  | Hasło logowania do dashboardu     |

### 2. Utwórz bota Discord

1. Wejdź na https://discord.com/developers/applications
2. **New Application** → nadaj nazwę
3. **Bot** → **Add Bot** → skopiuj token
4. **Bot** → włącz: `Message Content Intent`, `Server Members Intent`, `Presence Intent`
5. **OAuth2 → URL Generator**: zaznacz `bot` i `applications.commands`
   - Uprawnienia: `Send Messages`, `Embed Links`, `Read Message History`, `Manage Roles`, `View Channels`
6. Skopiuj wygenerowany link i zaproś bota na serwer

### 3. Uruchomienie

Kliknij **Run** w Replit. Bot i dashboard startują jednocześnie.

## 🤖 Komendy Bota (prefix `.`)

### Użytkownik
| Komenda | Opis |
|---------|------|
| `.help` | Lista wszystkich komend |
| `.points [@user]` | Sprawdź punkty |
| `.rank [@user]` | Sprawdź rangę |
| `.lb` / `.leaderboard` | Top 10 ranking |
| `.history` | Historia sesji clock |
| `.profile [@user]` | Pełny profil |
| `.clock` | Status clock in/out |

### Admin (wymaga roli admina lub uprawnień serwera)
| Komenda | Opis |
|---------|------|
| `.ban @user` | Zablokuj z listy rankingowej |
| `.unban @user` | Odblokuj z listy rankingowej |
| `.addpoints @user <n> [nota]` | Dodaj punkty |
| `.removepoints @user <n> [nota]` | Odejmij punkty |
| `.setpoints @user <n> [nota]` | Ustaw punkty |
| `.giverank @user <nazwa> [nota]` | Nadaj rangę specjalną |
| `.takerank @user <nazwa>` | Odbierz rangę specjalną |
| `.createrank <nazwa> <pkt\|SPECIAL> [ikona] [#kolor] [opis]` | Utwórz rangę |
| `.deleterank <nazwa>` | Usuń rangę |
| `.editrank <nazwa> <pole> <wartość>` | Edytuj rangę |
| `.ranks` | Lista wszystkich rang |
| `.userinfo @user` | Szczegóły użytkownika |
| `.forceclockout @user` | Wymuś wylogowanie |
| `.resetuser @user` | Resetuj dane użytkownika |
| `.serverstats` | Statystyki serwera |
| `.setchannel <clock\|log> #kanał` | Ustaw kanały |
| `.setpoints_h <n>` | Punkty za godzinę |
| `.adminrole @rola` | Dodaj rolę admina |
| `.removeadminrole @rola` | Usuń rolę admina |
| `.config` | Pokaż konfigurację |
| `.apel` | Wyślij apel ręcznie |

## 🌐 Dashboard

Dashboard jest dostępny pod adresem Replit (`https://nazwa.replit.app`).

**Funkcje dashboardu:**
- Przegląd serwera: statystyki, top 5, aktywni użytkownicy
- Zarządzanie użytkownikami: punkty, rangi specjalne, historia
- Zarządzanie rangami: tworzenie, edycja, usuwanie
- Konfiguracja: kanały, punkty/h, role adminów

## 📋 System Clock In/Out

- Codziennie o **północy UTC** bot wysyła embed z przyciskami **Clock In** i **Clock Out**
- Po kliknięciu **Clock In** zapisywana jest godzina wejścia
- Po kliknięciu **Clock Out** obliczany jest czas i nadawane są punkty
- **Domyślnie: 10 punktów za godzinę aktywności**
- Minimum 5 minut sesji aby zdobyć punkty

## 🗃️ Baza Danych

SQLite (`data/bot.db`) – wszystkie dane są lokalne na Replit.

## 🔄 Keep Alive (UptimeRobot)

Aby bot działał 24/7 na bezpłatnym Replit:
1. Wejdź na https://uptimerobot.com
2. **New Monitor** → HTTP(s)
3. URL: `https://twoja-nazwa.replit.app/ping`
4. Interwał: 5 minut

---
*System Rang v1.0 | discord.py + Flask + SQLite*

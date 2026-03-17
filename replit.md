# 🛡️ Baza Mops – Discord Bot z Systemem Rang

Discord bot z systemem aktywności (clock in/out), rangami, leaderboardem i dashboardem webowym.

## ⚙️ Setup na Replit

### 1. Zmienne środowiskowe (Secrets)

Wejdź w **Tools → Secrets** i dodaj 3 sekrety:

| Zmienna              | Przykładowa wartość              | Opis                              |
|----------------------|----------------------------------|-----------------------------------|
| `DISCORD_TOKEN`      | `MzA3...` (bot token)            | Skopiuj z Discord Dev Portal      |
| `DASHBOARD_SECRET`   | `random-long-string-32+ chars`   | Klucz sesji Flask (losowy)        |
| `DASHBOARD_PASSWORD` | `admin123`                       | Hasło do dashboardu web           |

### 2. Discord Bot Setup

1. Wejdź na https://discord.com/developers/applications
2. **New Application** → nadaj nazwę
3. **Bot** sekcja → **Add Bot** → skopiuj `TOKEN`
4. **Privileged Gateway Intents** → włącz:
   - ✅ Message Content Intent
   - ✅ Server Members Intent
   - ✅ Presence Intent
5. **OAuth2 → URL Generator** → zaznacz: `bot` + `applications.commands`
   - Uprawnienia: `Send Messages`, `Embed Links`, `Read Message History`, `Manage Roles`, `View Channels`
6. Skopiuj wygenerowany URL i zaproś bota na serwer

### 3. Uruchomienie

Aplikacja już biegnie! Odwiedź **Preview** aby zobaczyć dashboard (port 5000).

- **Dashboard**: `https://localhost:5000` (lub proxy Replit)
- **Login**: Hasło z `DASHBOARD_PASSWORD`
- **Discord Bot**: Będzie aktywny gdy ustawisz token

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

### Admin (wymaga uprawnień)
| Komenda | Opis |
|---------|------|
| `.ban @user` | Zablokuj z rankingu |
| `.unban @user` | Odblokuj |
| `.addpoints @user <n>` | Dodaj punkty |
| `.removepoints @user <n>` | Odejmij punkty |
| `.setpoints @user <n>` | Ustaw punkty |
| `.giverank @user <nazwa>` | Nadaj rangę |
| `.takerank @user <nazwa>` | Odbierz rangę |
| `.createrank <nazwa>` | Utwórz rangę |
| `.deleterank <nazwa>` | Usuń rangę |
| `.editrank <nazwa> <pole>` | Edytuj rangę |
| `.ranks` | Lista rang |
| `.userinfo @user` | Szczegóły użytkownika |
| `.forceclockout @user` | Wymuś wylogowanie |
| `.resetuser @user` | Resetuj dane |
| `.serverstats` | Statystyki serwera |
| `.config` | Pokaż konfigurację |

## 🌐 Dashboard Web

**Funkcje:**
- Przegląd serwera (statystyki, top 5, aktywni teraz)
- Zarządzanie użytkownikami (punkty, rangi, historia)
- Zarządzanie rangami (tworzenie, edycja, usuwanie)
- Konfiguracja (kanały, punkty/h, role adminów)
- Uprawnienia (dostęp do komend)
- Ogłoszenia (wysyłanie embed/text)
- Logi akcji (audyt i historia zmian)

## 📋 Clock In/Out System

- Codziennie o **północy UTC** bot wysyła embed z przyciskami
- **Clock In** = zapisanie godziny wejścia
- **Clock Out** = obliczenie czasu, przyznanie punktów
- **Domyślnie: 10 pkt/godzina**
- Minimum 5 minut sesji = punkty

## 🗃️ Baza Danych

SQLite (`data/bot.db`) – dane przechowywane lokalnie na Replit.

## 🚀 Deployment

Już skonfigurowany jako **VM** (always-running):
1. Kliknij **Publish** w Replit
2. Bot będzie działał 24/7
3. Dashboard dostępny na `yourusername.replit.app`

Aby bot żył bez przerw na bezpłatnym Replit (opcjonalnie):
1. Setup **UptimeRobot** → https://uptimerobot.com
2. **New Monitor** → HTTP(s) → URL: `https://yourapp.replit.app/ping`
3. Interwał: 5 minut

## 📁 Struktura Plików

```
├── main.py                 # Entry point (Dashboard + Bot)
├── discord_bot.py          # Bot handler
├── database.py             # SQLite DB
├── dashboard/
│   ├── app.py              # Flask app
│   ├── templates/          # HTML templates
│   └── __init__.py
├── cogs/
│   ├── clockin.py          # Clock in/out
│   ├── admin.py            # Admin commands
│   ├── user.py             # User commands
│   └── panel.py            # Button handlers
├── data/
│   └── bot.db              # SQLite database
└── requirements.txt        # Dependencies
```

## 🔧 Technologia

- **Python 3.12** – discord.py + Flask
- **SQLite** – Baza danych
- **Bootstrap 5** – Dashboard UI
- **Discord.py 2.3.2** – Bot framework

---

**Status:** ✅ Setup Complete  
*System Rang v1.0 | discord.py + Flask + SQLite*

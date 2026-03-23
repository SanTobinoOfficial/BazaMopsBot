import os
import io
import csv
import json
import secrets as _secrets
import threading
import requests
from datetime import datetime, timezone
from functools import wraps
from flask import (Flask, render_template, request, redirect,
                   url_for, session, flash, jsonify, Response)
from flask_sock import Sock
import database as db

app = Flask(__name__, template_folder='templates')

# Ensure DB tables exist (dashboard may start before or without the bot)
try:
    import database as _db_init
    _db_init.init_db()
except Exception:
    pass

def _get_secret_key():
    if s := os.environ.get('DASHBOARD_SECRET'):
        return s
    key_file = os.path.join(os.path.dirname(__file__), '..', 'data', '.secret_key')
    os.makedirs(os.path.dirname(key_file), exist_ok=True)
    try:
        with open(key_file) as f:
            key = f.read().strip()
            if key:
                return key
    except FileNotFoundError:
        pass
    key = _secrets.token_hex(32)
    with open(key_file, 'w') as f:
        f.write(key)
    return key

app.secret_key = _get_secret_key()
DISCORD_API = 'https://discord.com/api/v10'
sock = Sock(app)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _tok():
    return os.environ.get('DISCORD_TOKEN', '')

def _dget(path):
    try:
        r = requests.get(f'{DISCORD_API}{path}',
                         headers={'Authorization': f'Bot {_tok()}'}, timeout=5)
        return r.json() if r.ok else None
    except Exception:
        return None

def _dpost(path, payload):
    """POST to Discord API. Returns (response_dict, error_str) tuple."""
    try:
        r = requests.post(f'{DISCORD_API}{path}',
                          headers={'Authorization': f'Bot {_tok()}'},
                          json=payload, timeout=5)
        data = r.json() if r.content else {}
        if r.ok:
            return data, None
        # Build a human-readable error
        msg = data.get('message', f'HTTP {r.status_code}')
        errors = data.get('errors', {})
        if errors:
            def _flatten(d, prefix=''):
                parts = []
                for k, v in d.items():
                    if isinstance(v, dict):
                        if '_errors' in v:
                            for e in v['_errors']:
                                parts.append(f"{prefix}{k}: {e.get('message','')}")
                        else:
                            parts.extend(_flatten(v, f'{prefix}{k}.'))
                    elif isinstance(v, list):
                        for item in v:
                            if isinstance(item, dict):
                                parts.extend(_flatten(item, f'{prefix}{k}.'))
                return parts
            detail = ' | '.join(_flatten(errors))
            msg = f'{msg} – {detail}' if detail else msg
        return None, msg
    except Exception as exc:
        return None, str(exc)

def _dpatch(path, payload):
    """PATCH to Discord API. Returns (response_dict, error_str) tuple."""
    try:
        r = requests.patch(f'{DISCORD_API}{path}',
                           headers={'Authorization': f'Bot {_tok()}'},
                           json=payload, timeout=5)
        data = r.json() if r.content else {}
        if r.ok:
            return data, None
        return None, data.get('message', f'HTTP {r.status_code}')
    except Exception as exc:
        return None, str(exc)

def _dput(path):
    """PUT to Discord API without body (role assignment)."""
    try:
        r = requests.put(f'{DISCORD_API}{path}',
                         headers={'Authorization': f'Bot {_tok()}'},
                         timeout=5)
        return r.ok
    except Exception:
        return False

def _ddel(path):
    """DELETE to Discord API (role removal)."""
    try:
        r = requests.delete(f'{DISCORD_API}{path}',
                            headers={'Authorization': f'Bot {_tok()}'},
                            timeout=5)
        return r.ok
    except Exception:
        return False

def _sync_faction_discord_roles(guild_id: int, user_id: int, faction: dict, add: bool):
    """Add or remove all Discord marker roles for a faction.
    Also handles the base rank (Rekrut) role for the faction.
    """
    try:
        role_ids = json.loads(faction.get('role_ids') or '[]')
        for rid in role_ids:
            if add:
                _dput(f'/guilds/{guild_id}/members/{user_id}/roles/{rid}')
            else:
                _ddel(f'/guilds/{guild_id}/members/{user_id}/roles/{rid}')
    except Exception:
        pass

    # Also add/remove the base Rekrut rank Discord role for the faction
    try:
        all_ranks = db.get_ranks(guild_id)
        faction_ranks = [
            r for r in all_ranks
            if r.get('faction_id') == faction['id']
            and not r.get('is_special') and not r.get('is_owner_only')
        ]
        if faction_ranks:
            faction_ranks.sort(key=lambda r: r.get('required_points', 0))
            base_rank = faction_ranks[0]
            if base_rank.get('role_id'):
                if add:
                    _dput(f'/guilds/{guild_id}/members/{user_id}/roles/{base_rank["role_id"]}')
                else:
                    # Remove ALL faction rank roles on faction removal
                    for r in faction_ranks:
                        if r.get('role_id'):
                            _ddel(f'/guilds/{guild_id}/members/{user_id}/roles/{r["role_id"]}')
    except Exception:
        pass


def _sync_auto_rank_role(guild_id: int, user_id: int, old_role_id):
    """After a points change, remove old auto-rank Discord role and assign the new one.

    Call this AFTER the DB points have already been updated so that
    get_user_auto_rank() returns the rank matching the new points value.
    """
    try:
        new_rank    = db.get_user_auto_rank(user_id, guild_id)
        new_role_id = new_rank.get('role_id') if new_rank else None

        # Nothing changed – skip all API calls
        if old_role_id == new_role_id:
            return

        # Remove previous auto-rank role (if any)
        if old_role_id:
            _ddel(f'/guilds/{guild_id}/members/{user_id}/roles/{old_role_id}')

        # Assign new auto-rank role (if any)
        if new_role_id:
            _dput(f'/guilds/{guild_id}/members/{user_id}/roles/{new_role_id}')
    except Exception:
        pass   # sync is best-effort; never crash the dashboard action

def _split_regulamin(content, max_len=1900):
    """Split regulamin into chunks ≤ max_len chars, breaking at blank lines."""
    lines = content.split('\n')
    chunks, current, current_len = [], [], 0
    for line in lines:
        line_len = len(line) + 1
        if current_len + line_len > max_len and current:
            chunks.append('\n'.join(current))
            current, current_len = [line], line_len
        else:
            current.append(line)
            current_len += line_len
    if current:
        chunks.append('\n'.join(current))
    return [c for c in chunks if c.strip()]


def _calculate_balanced_bonuses(jobs, base_pph):
    """Calculate balanced points_bonus_per_hour for each job.

    Formula: bonus = sqrt(required_points / max_required_points) * base_pph
    Rounded to nearest 0.5. Jobs with 0 required_points get a minimum 0.5 bonus.
    """
    import math
    if not jobs:
        return {}
    max_pts = max((j.get('required_points') or 0) for j in jobs)
    result = {}
    for j in jobs:
        req = j.get('required_points') or 0
        if max_pts > 0:
            ratio = math.sqrt(req / max_pts) if req > 0 else 0.0
        else:
            ratio = 0.0
        raw = ratio * base_pph
        bonus = round(raw * 2) / 2   # round to nearest 0.5
        bonus = max(bonus, 0.5 if req > 0 else 0.0)
        result[j['id']] = bonus
    return result


def _guild_info(guild_id):
    info = _dget(f'/guilds/{guild_id}')
    return info or {}

def _guild_icon(guild_id, icon_hash):
    return f'https://cdn.discordapp.com/icons/{guild_id}/{icon_hash}.png' if icon_hash else None

def _is_ajax():
    """True if request was made with fetch/XHR (expects JSON back)."""
    return (request.content_type or '').startswith('application/json') or \
           request.headers.get('X-Requested-With') == 'XMLHttpRequest'


def login_required(f):
    """Admin-only routes (password login or Discord admin)."""
    @wraps(f)
    def dec(*a, **kw):
        if not session.get('logged_in'):
            if _is_ajax():
                return jsonify({'ok': False, 'message': 'Sesja wygasła. Odśwież stronę i zaloguj się ponownie.'}), 401
            return redirect(url_for('login'))
        return f(*a, **kw)
    return dec


def any_login_required(f):
    """Any authenticated user – admin password OR Discord OAuth."""
    @wraps(f)
    def dec(*a, **kw):
        if not (session.get('logged_in') or session.get('discord_user_id')):
            if _is_ajax():
                return jsonify({'ok': False, 'message': 'Sesja wygasła. Odśwież stronę i zaloguj się ponownie przez Discord.'}), 401
            return redirect(url_for('login'))
        return f(*a, **kw)
    return dec


def _session_is_admin():
    return bool(session.get('logged_in'))


def _session_discord_id():
    return session.get('discord_user_id')

def _fmt(dt_str):
    if not dt_str:
        return '—'
    try:
        return datetime.fromisoformat(dt_str).strftime('%d.%m.%Y %H:%M')
    except Exception:
        return dt_str

app.jinja_env.filters['fmtdt']     = _fmt
app.jinja_env.filters['r2']        = lambda x: round(float(x or 0), 2)
app.jinja_env.filters['from_json'] = lambda s: json.loads(s) if s else []
app.jinja_env.filters['hex_color'] = lambda x: f'#{int(x):06X}'
app.jinja_env.filters['bitand']    = lambda x, mask: int(x or 0) & int(mask)


# ─── Auth ─────────────────────────────────────────────────────────────────────

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        provided = request.form.get('password', '')
        expected = os.environ.get('DASHBOARD_PASSWORD', 'admin')
        if _secrets.compare_digest(provided, expected):
            session['logged_in'] = True
            return redirect(url_for('index'))
        flash('Nieprawidłowe hasło.', 'danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


# ─── Debug (tymczasowy) ───────────────────────────────────────────────────────

@app.route('/auth/debug')
def auth_debug():
    env_ok = {
        'DISCORD_CLIENT_ID':     bool(os.environ.get('DISCORD_CLIENT_ID')),
        'DISCORD_CLIENT_SECRET': bool(os.environ.get('DISCORD_CLIENT_SECRET')),
        'DISCORD_REDIRECT_URI':  os.environ.get('DISCORD_REDIRECT_URI', '(brak)'),
        'DISCORD_GUILD_ID':      os.environ.get('DISCORD_GUILD_ID', '(brak)'),
        'DASHBOARD_SECRET':      bool(os.environ.get('DASHBOARD_SECRET')),
    }
    session_data = dict(session)
    # Remove sensitive data
    session_data.pop('discord_roles', None)
    guilds = db.get_all_guilds()
    return f'<pre style="font-family:monospace;padding:2rem;background:#1e2124;color:#fff">' \
           f'ENV:\n{json.dumps(env_ok, indent=2)}\n\n' \
           f'SESSION:\n{json.dumps(session_data, indent=2, default=str)}\n\n' \
           f'DB guilds: {[g["guild_id"] for g in guilds]}\n' \
           f'</pre>'


# ─── Discord OAuth2 ───────────────────────────────────────────────────────────

@app.route('/auth/discord')
def auth_discord():
    client_id = os.environ.get('DISCORD_CLIENT_ID', '')
    redirect_uri = os.environ.get('DISCORD_REDIRECT_URI', '')
    if not client_id:
        flash('Logowanie przez Discord nie jest skonfigurowane.', 'danger')
        return redirect(url_for('login'))
    from urllib.parse import quote
    url = (f'https://discord.com/api/oauth2/authorize'
           f'?client_id={client_id}'
           f'&redirect_uri={quote(redirect_uri, safe="")}'
           f'&response_type=code&scope=identify')
    return redirect(url)


@app.route('/auth/callback')
def auth_callback():
    code = request.args.get('code')
    error = request.args.get('error')
    if error or not code:
        flash(f'Logowanie anulowane przez Discord: {error or "brak kodu"}.', 'warning')
        return redirect(url_for('login'))

    client_id     = os.environ.get('DISCORD_CLIENT_ID', '')
    client_secret = os.environ.get('DISCORD_CLIENT_SECRET', '')
    redirect_uri  = os.environ.get('DISCORD_REDIRECT_URI', '')

    if not client_id or not client_secret:
        flash('Brak konfiguracji Discord OAuth (DISCORD_CLIENT_ID / DISCORD_CLIENT_SECRET).', 'danger')
        return redirect(url_for('login'))

    # Exchange code for access token
    try:
        token_resp = requests.post(
            f'{DISCORD_API}/oauth2/token',
            data={'client_id': client_id, 'client_secret': client_secret,
                  'grant_type': 'authorization_code', 'code': code,
                  'redirect_uri': redirect_uri},
            headers={'Content-Type': 'application/x-www-form-urlencoded'},
            timeout=10)
    except Exception as exc:
        flash(f'Błąd sieci przy pobieraniu tokena: {exc}', 'danger')
        return redirect(url_for('login'))

    if not token_resp.ok:
        try:
            detail = token_resp.json().get('error_description') or token_resp.json().get('error') or ''
        except Exception:
            detail = token_resp.text[:120]
        flash(f'Discord odrzucił token ({token_resp.status_code}): {detail}. '
              f'Sprawdź czy DISCORD_REDIRECT_URI w Secrets zgadza się z wartością w Developer Portal.', 'danger')
        return redirect(url_for('login'))

    access_token = token_resp.json().get('access_token')
    if not access_token:
        flash('Discord nie zwrócił access_token. Spróbuj ponownie.', 'danger')
        return redirect(url_for('login'))

    # Get user info
    try:
        user_resp = requests.get(f'{DISCORD_API}/users/@me',
                                 headers={'Authorization': f'Bearer {access_token}'},
                                 timeout=5)
    except Exception as exc:
        flash(f'Błąd sieci przy pobieraniu profilu: {exc}', 'danger')
        return redirect(url_for('login'))

    if not user_resp.ok:
        flash(f'Nie można pobrać danych konta Discord ({user_resp.status_code}).', 'danger')
        return redirect(url_for('login'))

    u = user_resp.json()
    uid       = int(u['id'])
    username  = u.get('global_name') or u.get('username', '')
    avatar_h  = u.get('avatar')
    avatar_url = (f'https://cdn.discordapp.com/avatars/{uid}/{avatar_h}.png'
                  if avatar_h else
                  f'https://cdn.discordapp.com/embed/avatars/{uid % 5}.png')

    # Determine guild (use configured ID or first in DB)
    guild_id_str = os.environ.get('DISCORD_GUILD_ID', '').strip()
    if guild_id_str.isdigit():
        guild_id = int(guild_id_str)
    else:
        guilds = db.get_all_guilds()
        if not guilds:
            flash('Brak skonfigurowanego serwera (DISCORD_GUILD_ID nie ustawione i brak guilds w bazie).', 'danger')
            return redirect(url_for('login'))
        guild_id = guilds[0]['guild_id']

    db.ensure_guild(guild_id)
    db.ensure_user(uid, guild_id, username, username)

    # Get member info using bot token (optional – if bot not in guild, still log in)
    member = _dget(f'/guilds/{guild_id}/members/{uid}')
    if member and isinstance(member, dict) and not member.get('code'):
        member_roles = [str(r) for r in member.get('roles', [])]
        nick = member.get('nick') or username
    else:
        member_roles = []
        nick = username

    db.ensure_user(uid, guild_id, username, nick)

    # Check if admin
    guild_cfg = db.get_guild(guild_id) or {}
    try:
        admin_role_ids = [str(r) for r in json.loads(guild_cfg.get('admin_role_ids') or '[]')]
    except Exception:
        admin_role_ids = []
    is_admin = any(r in admin_role_ids for r in member_roles)

    # Store in session
    session['discord_user_id']   = uid
    session['discord_username']  = nick
    session['discord_avatar']    = avatar_url
    session['discord_guild_id']  = guild_id
    session['discord_is_admin']  = is_admin
    session['discord_roles']     = member_roles

    if is_admin:
        session['logged_in'] = True  # grant full admin access

    if is_admin:
        flash(f'Zalogowano jako admin: {nick}', 'success')
        return redirect(url_for('guild_overview', guild_id=guild_id))
    flash(f'Zalogowano jako: {nick}', 'success')
    return redirect(url_for('user_dashboard', guild_id=guild_id))


# ─── Command permission groups ────────────────────────────────────────────────
COMMAND_GROUPS = {
    'Profil':      ['points', 'rank', 'history', 'profile', 'level'],
    'Zegar':       ['clock'],
    'Ranking':     ['lb', 'warnpoints'],
    'Ekonomia':    ['balance', 'deposit', 'withdraw', 'transfer', 'shop', 'buy', 'daily', 'work'],
    'Gry':         ['blackjack', 'highlow', 'scratch', 'rps', 'slots'],
    'Aktywności':  ['fish', 'mine', 'hunt'],
    'Społeczne':   ['hug', 'pat', 'slap', 'gg', 'ship', 'rate'],
    'Rozrywka':    ['fact', 'joke', 'quote', 'owo', 'reverse', 'upper', 'lower'],
    'Narzędzia':   ['ping', 'uptime', 'remindme', 'tag', 'taglist', 'roleinfo'],
}

# Structured tabs for user dashboard (tab → subtab → commands with meta)
CMD_TABS = {
    'Profil': {
        '_flat': [
            {'cmd': 'points',  'icon': 'bi-star',          'label': 'Punkty',       'desc': 'Sprawdź swoje punkty'},
            {'cmd': 'rank',    'icon': 'bi-award',          'label': 'Ranga',        'desc': 'Twoja aktualna ranga'},
            {'cmd': 'level',   'icon': 'bi-bar-chart',      'label': 'Level',        'desc': 'Postęp do następnej rangi'},
            {'cmd': 'profile', 'icon': 'bi-person-badge',   'label': 'Profil',       'desc': 'Pełny profil'},
            {'cmd': 'history', 'icon': 'bi-clock-history',  'label': 'Historia',     'desc': 'Historia punktów'},
            {'cmd': 'lb',      'icon': 'bi-trophy',         'label': 'Ranking',      'desc': 'Top graczy na serwerze'},
            {'cmd': 'warnpoints', 'icon': 'bi-exclamation-triangle', 'label': 'Warn LB', 'desc': 'Ranking warnów'},
            {'cmd': 'avatar',     'icon': 'bi-person-circle',        'label': 'Avatar',   'desc': 'Twój avatar'},
            {'cmd': 'job',        'icon': 'bi-briefcase',            'label': 'Prace',    'desc': 'Lista prac i twoje stanowisko'},
        ]
    },
    'Ekonomia': {
        'Portfel': [
            {'cmd': 'balance',  'icon': 'bi-wallet2',        'label': 'Portfel',      'desc': 'Gotówka i bank'},
            {'cmd': 'deposit',  'icon': 'bi-bank',           'label': 'Wpłać',        'desc': 'Wpłać mopsy do banku', 'arg': True, 'placeholder': 'Kwota lub "all"'},
            {'cmd': 'withdraw', 'icon': 'bi-cash-stack',     'label': 'Wypłać',       'desc': 'Wypłać mopsy z banku', 'arg': True, 'placeholder': 'Kwota lub "all"'},
            {'cmd': 'transfer', 'icon': 'bi-arrow-left-right','label': 'Przelew',     'desc': 'Wyślij mopsy innemu', 'arg': True, 'placeholder': '@nick kwota'},
        ],
        'Sklep': [
            {'cmd': 'shop',  'icon': 'bi-shop',           'label': 'Sklep',    'desc': 'Lista dostępnych przedmiotów'},
            {'cmd': 'buy',   'icon': 'bi-bag-check',      'label': 'Kup',      'desc': 'Kup przedmiot ze sklepu', 'arg': True, 'placeholder': 'Nazwa przedmiotu'},
            {'cmd': 'daily', 'icon': 'bi-gift',           'label': 'Daily',    'desc': 'Dzienna nagroda (co 24h)'},
            {'cmd': 'beg',  'icon': 'bi-hand-thumbs-up', 'label': 'Żebranie',  'desc': 'Żebraj o mopsy (cooldown 30min)'},
            {'cmd': 'eco',  'icon': 'bi-bar-chart',      'label': 'Mopsy LB',  'desc': 'Ranking mopsów'},
            {'cmd': 'rep',  'icon': 'bi-star',           'label': 'Rep',       'desc': 'Daj komuś reputację', 'arg': True, 'placeholder': '@nick'},
            {'cmd': 'work',  'icon': 'bi-briefcase',      'label': 'Praca',    'desc': 'Zarabiaj mopsy (cooldown 1h)'},
        ],
        'Aktywności': [
            {'cmd': 'fish',  'icon': 'bi-water',          'label': 'Wędkowanie', 'desc': 'Łów ryby (cooldown 45min)'},
            {'cmd': 'mine',  'icon': 'bi-hammer',         'label': 'Kopanie',    'desc': 'Wydobywaj surowce (cooldown 1h)'},
            {'cmd': 'hunt',  'icon': 'bi-crosshair',      'label': 'Polowanie',  'desc': 'Poluj na zwierzynę (cooldown 1h)'},
        ],
        'Kasyno': [
            {'cmd': 'slots',      'icon': 'bi-grid-3x3-gap', 'label': 'Jednoręki bandyta', 'desc': 'Spróbuj szczęścia! (cooldown 2min)'},
            {'cmd': 'blackjack',  'icon': 'bi-suit-spade',   'label': 'Blackjack',  'desc': 'Gram o mopsy z dealerem', 'arg': True, 'placeholder': 'Stawka (min 10)'},
            {'cmd': 'highlow',    'icon': 'bi-arrow-up-down','label': 'Wyżej/Niżej','desc': 'Zgadnij czy karta jest wyższa'},
            {'cmd': 'scratch',    'icon': 'bi-ticket-perforated','label': 'Zdrapka', 'desc': 'Kup zdrapkę za 30 🐾'},
            {'cmd': 'rps',        'icon': 'bi-hand-index',   'label': 'Kamień Papier Nożyce', 'desc': 'Zagraj z botem'},
        ],
    },
    'Społeczne': {
        '_flat': [
            {'cmd': 'hug',  'icon': 'bi-emoji-heart-eyes', 'label': 'Przytul',  'desc': 'Przytuл kogoś', 'arg': True, 'placeholder': '@nick'},
            {'cmd': 'pat',  'icon': 'bi-hand-thumbs-up',   'label': 'Pogłaskaj','desc': 'Pogłaskaj kogoś', 'arg': True, 'placeholder': '@nick'},
            {'cmd': 'slap', 'icon': 'bi-hand-index-thumb', 'label': 'Uderz',    'desc': 'Uderz kogoś', 'arg': True, 'placeholder': '@nick'},
            {'cmd': 'gg',   'icon': 'bi-trophy-fill',      'label': 'GG',       'desc': 'Pogratuluj komuś', 'arg': True, 'placeholder': '@nick'},
            {'cmd': 'ship', 'icon': 'bi-heart',            'label': 'Ship',     'desc': 'Sprawdź miłosną kompatybilność', 'arg': True, 'placeholder': 'imię1 imię2'},
            {'cmd': 'rate', 'icon': 'bi-star-half',        'label': 'Oceń',     'desc': 'Oceń cokolwiek', 'arg': True, 'placeholder': 'cokolwiek'},
        ]
    },
    'Rozrywka': {
        '_flat': [
            {'cmd': '8ball',    'icon': 'bi-magic',           'label': '8ball',    'desc': 'Magiczna kula odpowie', 'arg': True, 'placeholder': 'zadaj pytanie'},
            {'cmd': 'coinflip', 'icon': 'bi-coin',            'label': 'Coinflip', 'desc': 'Rzuć monetą'},
            {'cmd': 'roll',     'icon': 'bi-dice-6',          'label': 'Kości',    'desc': 'Rzuć kością', 'arg': True, 'placeholder': 'liczba ścian (np 20)'},
            {'cmd': 'choose',   'icon': 'bi-shuffle',         'label': 'Wybierz',  'desc': 'Wybierz spośród opcji', 'arg': True, 'placeholder': 'opcja1 opcja2 opcja3'},
            {'cmd': 'trivia',   'icon': 'bi-question-circle', 'label': 'Trivia',   'desc': 'Quiz z nagrodą w mopsach'},
            {'cmd': 'fact',    'icon': 'bi-lightbulb',      'label': 'Ciekawostka','desc': 'Losowa ciekawostka'},
            {'cmd': 'joke',    'icon': 'bi-emoji-laughing',  'label': 'Żart',      'desc': 'Losowy żart'},
            {'cmd': 'quote',   'icon': 'bi-chat-quote',      'label': 'Cytat',     'desc': 'Losowy cytat'},
            {'cmd': 'owo',     'icon': 'bi-chat-heart',      'label': 'OwO',       'desc': 'Przetłumacz na OwO', 'arg': True, 'placeholder': 'tekst'},
            {'cmd': 'reverse', 'icon': 'bi-arrow-repeat',    'label': 'Odwróć',    'desc': 'Odwróć tekst', 'arg': True, 'placeholder': 'tekst'},
            {'cmd': 'upper',   'icon': 'bi-type-bold',       'label': 'CAPS',      'desc': 'Tekst wielkimi literami', 'arg': True, 'placeholder': 'tekst'},
            {'cmd': 'lower',   'icon': 'bi-type',            'label': 'małe',      'desc': 'Tekst małymi literami', 'arg': True, 'placeholder': 'tekst'},
        ]
    },
    'Narzędzia': {
        '_flat': [
            {'cmd': 'ping',       'icon': 'bi-reception-4',   'label': 'Ping',        'desc': 'Sprawdź opóźnienie bota'},
            {'cmd': 'uptime',     'icon': 'bi-clock',          'label': 'Uptime',      'desc': 'Jak długo bot działa'},
            {'cmd': 'remindme',   'icon': 'bi-bell',           'label': 'Przypomnienie','desc': 'Ustaw przypomnienie', 'arg': True, 'placeholder': '1h tekst przypomnienia'},
            {'cmd': 'tag',        'icon': 'bi-bookmark',       'label': 'Tag',         'desc': 'Wyświetl tag', 'arg': True, 'placeholder': 'nazwa tagu'},
            {'cmd': 'taglist',    'icon': 'bi-bookmarks',      'label': 'Lista tagów', 'desc': 'Wszystkie dostępne tagi'},
            {'cmd': 'roleinfo',   'icon': 'bi-shield-check',   'label': 'Info o roli', 'desc': 'Info o roli Discord', 'arg': True, 'placeholder': 'nazwa roli'},
            {'cmd': 'warnpoints', 'icon': 'bi-exclamation-triangle','label': 'Warn punkty','desc': 'Ranking warnów punktowych'},
            {'cmd': 'serverinfo', 'icon': 'bi-info-circle',    'label': 'Serwer Info', 'desc': 'Statystyki serwera'},
        ]
    },
}

# ─── Index ────────────────────────────────────────────────────────────────────

@app.route('/')
@any_login_required
def index():
    # Discord user without admin → redirect to their personal dashboard
    if not session.get('logged_in') and session.get('discord_guild_id'):
        return redirect(url_for('user_dashboard', guild_id=session['discord_guild_id']))

    guilds_cfg = db.get_all_guilds()
    guilds = []
    for cfg in guilds_cfg:
        info = _dget(f'/guilds/{cfg["guild_id"]}') or {}
        guilds.append({**cfg, 'name': info.get('name', str(cfg['guild_id'])),
                       'icon': info.get('icon')})
    if len(guilds) == 1:
        return redirect(url_for('guild_overview', guild_id=guilds[0]['guild_id']))
    return render_template('index.html', guilds=guilds)


# ─── User dashboard (Discord-logged-in non-admin) ─────────────────────────────

@app.route('/guild/<int:guild_id>/me')
@any_login_required
def user_dashboard(guild_id):
    try:
        db.ensure_guild(guild_id)
        info = _guild_info(guild_id)
        uid = _session_discord_id()
        # Admin password users without discord id can still visit; show empty profile note
        user = db.get_user(uid, guild_id) if uid else None
        if uid:
            db.ensure_user(uid, guild_id)
            user = db.get_user(uid, guild_id)
        auto_rank   = db.get_user_auto_rank(uid, guild_id) if uid else None
        next_rank   = db.get_user_next_rank(uid, guild_id) if uid else None
        specials    = db.get_user_special_ranks(uid, guild_id) if uid else []
        sessions    = db.get_user_sessions(uid, guild_id, limit=10) if uid else []
        wallet      = db.get_wallet(uid, guild_id) if uid else {'cash': 0, 'bank': 0}
        try:
            user_faction = db.get_user_faction_membership(uid, guild_id) if uid else None
        except Exception:
            user_faction = None
        try:
            user_jobs = db.get_user_jobs(uid, guild_id) if uid else []
        except Exception:
            user_jobs = []
        # Rank progress
        progress = 0
        if auto_rank and next_rank and uid and user:
            cur      = user.get('points', 0) or 0
            req_cur  = auto_rank.get('required_points', 0) or 0
            req_next = next_rank.get('required_points', 1) or 1
            span = req_next - req_cur
            if span > 0:
                progress = min(100, int((cur - req_cur) / span * 100))
        # Leaderboard position
        lb = db.get_leaderboard(guild_id, limit=9999)
        lb_position = next((i+1 for i, u in enumerate(lb) if u['user_id'] == uid), None) if uid else None
        return render_template('user_dashboard.html',
            guild_id=guild_id,
            guild_name=info.get('name', str(guild_id)),
            icon_url=_guild_icon(guild_id, info.get('icon')),
            user=user, uid=uid,
            auto_rank=auto_rank, next_rank=next_rank, specials=specials,
            sessions=sessions, wallet=wallet,
            user_faction=user_faction, user_jobs=user_jobs,
            progress=progress, lb_position=lb_position,
            discord_username=session.get('discord_username', ''),
            discord_avatar=session.get('discord_avatar', ''),
            command_groups=COMMAND_GROUPS,
            cmd_tabs=CMD_TABS,
            user_perms=(db.get_rank_permissions(guild_id, auto_rank['id']) if auto_rank else {}),
            active_events=db.get_active_events(guild_id),
        )
    except Exception as exc:
        import traceback
        tb = traceback.format_exc()
        return f'<pre style="background:#1e2124;color:#f04747;padding:2rem;font-family:monospace">' \
               f'BŁĄD w user_dashboard:\n\n{tb}\n\nUID: {_session_discord_id()}\nGuild: {guild_id}' \
               f'</pre>', 500


# ─── User command runner (browser-side execution) ─────────────────────────────

@app.route('/guild/<int:guild_id>/me/run', methods=['POST'])
@any_login_required
def user_run_command(guild_id):
    import random as _rnd
    data = request.get_json() or {}
    cmd  = data.get('action', '').strip()
    arg  = (data.get('args') or '').strip()
    uid  = _session_discord_id()

    if not uid:
        return jsonify({'ok': False, 'message': 'Zaloguj się przez Discord żeby używać komend.'})

    db.ensure_guild(guild_id)
    db.ensure_user(uid, guild_id)

    if not db.check_user_command_permission(uid, guild_id, cmd):
        return jsonify({'ok': False, 'message': f'Twoja ranga nie ma dostępu do komendy .{cmd}.'})

    user    = db.get_user(uid, guild_id) or {}
    wallet  = db.get_wallet(uid, guild_id)

    def _cooldown(col, minutes):
        last = user.get(col)
        if not last:
            return True, 0
        try:
            from datetime import datetime as _dt
            elapsed = (_dt.now() - _dt.fromisoformat(last)).total_seconds()
            left = minutes * 60 - elapsed
            return left <= 0, max(0, int(left))
        except Exception:
            return True, 0

    def _fmt(s):
        if s < 60: return f'{s}s'
        if s < 3600: return f'{s//60}m {s%60}s'
        return f'{s//3600}h {(s%3600)//60}m'

    # ── Profil ────────────────────────────────────────────────────────────────
    if cmd == 'points':
        pts = user.get('points', 0) or 0
        return jsonify({'ok': True, 'type': 'embed', 'color': '#7289da',
            'title': '⭐ Twoje punkty',
            'fields': [{'name': 'Punkty', 'value': f'**{pts:.1f}**'}]})

    if cmd in ('rank', 'level'):
        auto = db.get_user_auto_rank(uid, guild_id)
        nxt  = db.get_user_next_rank(uid, guild_id)
        pts  = user.get('points', 0) or 0
        progress = 0
        if auto and nxt:
            span = (nxt.get('required_points', 1) - auto.get('required_points', 0)) or 1
            progress = min(100, int((pts - auto.get('required_points', 0)) / span * 100))
        return jsonify({'ok': True, 'type': 'rank',
            'rank': auto.get('name', '—') if auto else '—',
            'rank_icon': auto.get('icon', '') if auto else '',
            'next': nxt.get('name', '') if nxt else '',
            'next_pts': nxt.get('required_points', 0) if nxt else 0,
            'pts': pts, 'progress': progress})

    if cmd == 'profile':
        auto = db.get_user_auto_rank(uid, guild_id)
        return jsonify({'ok': True, 'type': 'embed', 'color': '#7289da',
            'title': '👤 Profil',
            'fields': [
                {'name': 'Ranga',   'value': f'{auto.get("icon","")} {auto.get("name","—")}' if auto else '—'},
                {'name': 'Punkty',  'value': f'{user.get("points",0):.1f}'},
                {'name': 'Sesje',   'value': str(user.get('sessions_count', 0))},
                {'name': 'Łącznie', 'value': f'{user.get("total_hours",0):.1f} h'},
                {'name': 'Streak',  'value': f'{user.get("streak_days",0)} dni'},
            ]})

    if cmd == 'history':
        txs = db.get_user_transactions(uid, guild_id, limit=10)
        if not txs:
            return jsonify({'ok': True, 'type': 'embed', 'color': '#99aab5',
                'title': '📋 Historia', 'description': 'Brak transakcji.'})
        rows = [f'`{t.get("created_at","")[:10]}` '
                f'{"+" if (t.get("amount") or 0) > 0 else ""}{t.get("amount",0):.1f} — {t.get("note","?")}' for t in txs]
        return jsonify({'ok': True, 'type': 'embed', 'color': '#7289da',
            'title': '📋 Historia punktów', 'description': '\n'.join(rows)})

    if cmd == 'lb':
        lb = db.get_leaderboard(guild_id, limit=10)
        rows = [f'**{i+1}.** {r.get("display_name") or r.get("username","?")} — {r.get("points",0):.1f} pkt'
                for i, r in enumerate(lb)]
        return jsonify({'ok': True, 'type': 'embed', 'color': '#faa61a',
            'title': '🏆 Top 10 — Punkty', 'description': '\n'.join(rows) or 'Brak danych'})

    # ── Ekonomia ─────────────────────────────────────────────────────────────
    if cmd == 'balance':
        total = (wallet.get('cash') or 0) + (wallet.get('bank') or 0)
        return jsonify({'ok': True, 'type': 'embed', 'color': '#faa61a',
            'title': '💰 Portfel',
            'fields': [
                {'name': '💵 Gotówka', 'value': f'{int(wallet.get("cash",0))} 🐾'},
                {'name': '🏦 Bank',    'value': f'{int(wallet.get("bank",0))} 🐾'},
                {'name': '📊 Łącznie', 'value': f'{int(total)} 🐾'},
            ]})

    if cmd == 'deposit':
        cash = int(wallet.get('cash') or 0)
        amt  = cash if arg.lower() == 'all' else (int(arg) if arg.isdigit() else None)
        if amt is None or amt <= 0:
            return jsonify({'ok': False, 'message': 'Podaj kwotę lub "all".'})
        if not db.deposit_cash(uid, guild_id, amt):
            return jsonify({'ok': False, 'message': f'Nie masz tyle gotówki! Masz {cash} 🐾.'})
        return jsonify({'ok': True, 'type': 'embed', 'color': '#43b581',
            'title': '🏦 Wpłata', 'description': f'Wpłacono **{amt} 🐾** do banku.'})

    if cmd == 'withdraw':
        bank = int(wallet.get('bank') or 0)
        amt  = bank if arg.lower() == 'all' else (int(arg) if arg.isdigit() else None)
        if amt is None or amt <= 0:
            return jsonify({'ok': False, 'message': 'Podaj kwotę lub "all".'})
        if not db.withdraw_cash(uid, guild_id, amt):
            return jsonify({'ok': False, 'message': f'Nie masz tyle w banku! Masz {bank} 🐾.'})
        return jsonify({'ok': True, 'type': 'embed', 'color': '#43b581',
            'title': '💵 Wypłata', 'description': f'Wypłacono **{amt} 🐾** z banku.'})

    if cmd == 'transfer':
        parts = arg.split()
        if len(parts) < 2:
            return jsonify({'ok': False, 'message': 'Użycie: nick kwota (np. Jan 100)'})
        amt_str = parts[-1]
        if not amt_str.isdigit():
            return jsonify({'ok': False, 'message': 'Podaj prawidłową kwotę.'})
        amt = int(amt_str)
        target_name = ' '.join(parts[:-1]).lstrip('@')
        all_users = db.get_all_users(guild_id)
        target = next((u for u in all_users if (u.get('display_name') or u.get('username','')) == target_name), None)
        if not target:
            return jsonify({'ok': False, 'message': f'Nie znaleziono użytkownika "{target_name}".'})
        if not db.transfer_cash(uid, int(target['user_id']), guild_id, amt):
            return jsonify({'ok': False, 'message': f'Niewystarczające środki! Masz {int(wallet.get("cash",0))} 🐾.'})
        return jsonify({'ok': True, 'type': 'embed', 'color': '#43b581',
            'title': '💸 Przelew', 'description': f'Wysłano **{amt} 🐾** do **{target_name}**.'})

    if cmd == 'daily':
        ok_cd, left = _cooldown('daily_last', 1440)
        if not ok_cd:
            return jsonify({'ok': False, 'message': f'Już odebrałeś dzienną nagrodę! Następna za {_fmt(left)}.'})
        streak = (user.get('streak_days') or 0) + 1
        base = _rnd.randint(50, 150)
        bonus = min(streak * 5, 100)
        earn = int((base + bonus) * db.get_event_multiplier(guild_id, 'mopsy'))
        db.add_cash(uid, guild_id, earn)
        db.set_cooldown(uid, guild_id, 'daily_last')
        db.update_user(uid, guild_id, streak_days=streak)
        return jsonify({'ok': True, 'type': 'embed', 'color': '#43b581',
            'title': '🎁 Dzienna nagroda!',
            'description': f'Otrzymujesz **{earn} 🐾**\nStreak: **{streak}** dni 🔥'})

    if cmd == 'work':
        ok_cd, left = _cooldown('work_last', 60)
        if not ok_cd:
            return jsonify({'ok': False, 'message': f'Jesteś zmęczony! Odpocznij {_fmt(left)}.'})
        jobs = ['Dostarczyłeś pizzę','Naprawiłeś komputer','Posprzątałeś biuro','Pisałeś kod','Prowadziłeś samochód']
        earn = int(_rnd.randint(30, 80) * db.get_event_multiplier(guild_id, 'mopsy'))
        db.add_cash(uid, guild_id, earn)
        db.set_cooldown(uid, guild_id, 'work_last')
        return jsonify({'ok': True, 'type': 'embed', 'color': '#43b581',
            'title': '💼 Praca!', 'description': f'{_rnd.choice(jobs)} i zarobiłeś **{earn} 🐾**'})

    if cmd == 'fish':
        ok_cd, left = _cooldown('fish_last', 45)
        if not ok_cd:
            return jsonify({'ok': False, 'message': f'Wędka musi odpocząć! {_fmt(left)}.'})
        catches = [('🐟 Karasia',20,60),('🐠 Rybkę tropikalną',40,90),('🦈 Rekina',100,200),
                   ('🥾 But',0,0),('🐙 Ośmiornicę',60,120)]
        name, lo, hi = _rnd.choice(catches)
        earn = int(_rnd.randint(lo, hi) * db.get_event_multiplier(guild_id, 'mopsy')) if hi > 0 else 0
        if earn > 0:
            db.add_cash(uid, guild_id, earn)
        db.set_cooldown(uid, guild_id, 'fish_last')
        msg = f'Złowiłeś **{name}** i sprzedałeś za **{earn} 🐾**!' if earn > 0 else f'Złowiłeś **{name}**... nic nie warte 😂'
        return jsonify({'ok': True, 'type': 'embed', 'color': '#7289da',
            'title': '🎣 Wędkowanie', 'description': msg})

    if cmd == 'mine':
        ok_cd, left = _cooldown('mine_last', 60)
        if not ok_cd:
            return jsonify({'ok': False, 'message': f'Kilofy odpoczywają! {_fmt(left)}.'})
        ores = [('⬛ Węgiel',15,40),('🔩 Żelazo',30,70),('💎 Diament',100,250),('🥇 Złoto',60,130),('🪨 Skała',0,0)]
        name, lo, hi = _rnd.choice(ores)
        earn = int(_rnd.randint(lo, hi) * db.get_event_multiplier(guild_id, 'mopsy')) if hi > 0 else 0
        if earn > 0:
            db.add_cash(uid, guild_id, earn)
        db.set_cooldown(uid, guild_id, 'mine_last')
        msg = f'Wydobyłeś **{name}** za **{earn} 🐾**!' if earn > 0 else f'Trafiłeś na **{name}**... bezużyteczny 😅'
        return jsonify({'ok': True, 'type': 'embed', 'color': '#99aab5',
            'title': '⛏️ Kopanie', 'description': msg})

    if cmd == 'hunt':
        ok_cd, left = _cooldown('hunt_last', 60)
        if not ok_cd:
            return jsonify({'ok': False, 'message': f'Broń musi odpocząć! {_fmt(left)}.'})
        prey = [('🦊 Lisa',25,60),('🐗 Dzika',40,90),('🐻 Niedźwiedzia',80,180),('🐇 Zająca',10,30),('❌ Nic',0,0)]
        name, lo, hi = _rnd.choice(prey)
        earn = int(_rnd.randint(lo, hi) * db.get_event_multiplier(guild_id, 'mopsy')) if hi > 0 else 0
        if earn > 0:
            db.add_cash(uid, guild_id, earn)
        db.set_cooldown(uid, guild_id, 'hunt_last')
        msg = f'Upolowałeś **{name}** za **{earn} 🐾**!' if earn > 0 else 'Nic nie upolowałeś tym razem 😞'
        return jsonify({'ok': True, 'type': 'embed', 'color': '#f04747',
            'title': '🏹 Polowanie', 'description': msg})

    if cmd == 'shop':
        return jsonify({'ok': True, 'type': 'embed', 'color': '#faa61a',
            'title': '🛒 Sklep',
            'description': 'Sklep konfiguruje admin. Użyj `.shop` na Discordzie.'})

    # ── Gry / Kasyno ─────────────────────────────────────────────────────────
    if cmd == 'slots':
        ok_cd, left = _cooldown('slots_last', 2)
        if not ok_cd:
            return jsonify({'ok': False, 'message': f'Chwila przerwy! {_fmt(left)}.'})
        syms = ['🍒','🍋','🍊','⭐','💎','🔔','🍀','🎰']
        weights = [25,20,18,15,10,7,4,1]
        reels = [_rnd.choices(syms, weights=weights)[0] for _ in range(3)]
        if reels[0] == reels[1] == reels[2]:
            mult_map = {'💎':50,'🎰':30,'🍀':20,'🔔':15,'⭐':10,'🍊':7,'🍋':5,'🍒':3}
            earn = 50 * mult_map.get(reels[0], 3)
            result = 'jackpot'
        elif len(set(reels)) < 3:
            earn = 30
            result = 'win'
        else:
            earn = 0
            result = 'lose'
        if earn > 0:
            db.add_cash(uid, guild_id, earn)
        db.set_cooldown(uid, guild_id, 'slots_last')
        return jsonify({'ok': True, 'type': 'slots', 'reels': reels, 'result': result, 'earn': earn})

    if cmd in ('blackjack', 'bj'):
        bet = int(arg) if arg.isdigit() else 50
        if bet < 10: bet = 10
        cash = int(wallet.get('cash') or 0)
        if bet > cash:
            return jsonify({'ok': False, 'message': f'Nie masz {bet} 🐾! Masz {cash} 🐾.'})
        vals = {'2':2,'3':3,'4':4,'5':5,'6':6,'7':7,'8':8,'9':9,'10':10,'J':10,'Q':10,'K':10,'A':11}
        suits = ['♠','♥','♦','♣']
        deck = [f'{r}{s}' for s in suits for r in vals.keys()]
        _rnd.shuffle(deck)
        def _hv(h):
            s = sum(vals[c[:-1]] for c in h)
            a = sum(1 for c in h if c[:-1] == 'A')
            while s > 21 and a: s -= 10; a -= 1
            return s
        ph = [deck.pop(), deck.pop()]
        dh = [deck.pop(), deck.pop()]
        db.add_cash(uid, guild_id, -bet)
        session['bj'] = {'ph': ph, 'dh': dh, 'deck': deck, 'bet': bet, 'guild': guild_id, 'uid': uid}
        pv = _hv(ph)
        if pv == 21:
            earn = int(bet * 2.5)
            db.add_cash(uid, guild_id, earn)
            session.pop('bj', None)
            return jsonify({'ok': True, 'type': 'blackjack', 'player_hand': ph, 'dealer_hand': dh,
                'player_val': pv, 'dealer_val': _hv(dh), 'status': 'blackjack', 'earn': earn, 'bet': bet,
                'message': f'BLACKJACK! Wygrywasz {earn} 🐾!'})
        return jsonify({'ok': True, 'type': 'blackjack',
            'player_hand': ph, 'dealer_hand': [dh[0], '??'],
            'player_val': pv, 'dealer_val': None, 'status': 'playing', 'bet': bet})

    if cmd == 'bj_hit':
        bj = session.get('bj')
        if not bj:
            return jsonify({'ok': False, 'message': 'Brak aktywnej gry. Zacznij nową: .bj [stawka]'})
        vals = {'2':2,'3':3,'4':4,'5':5,'6':6,'7':7,'8':8,'9':9,'10':10,'J':10,'Q':10,'K':10,'A':11}
        def _hv(h):
            s = sum(vals[c[:-1]] for c in h)
            a = sum(1 for c in h if c[:-1] == 'A')
            while s > 21 and a: s -= 10; a -= 1
            return s
        bj['ph'].append(bj['deck'].pop())
        session['bj'] = bj
        pv = _hv(bj['ph'])
        if pv > 21:
            session.pop('bj', None)
            return jsonify({'ok': True, 'type': 'blackjack',
                'player_hand': bj['ph'], 'dealer_hand': bj['dh'],
                'player_val': pv, 'dealer_val': _hv(bj['dh']),
                'status': 'bust', 'earn': 0, 'bet': bj['bet'],
                'message': f'Bust! Przekroczyłeś 21. Tracisz {bj["bet"]} 🐾.'})
        return jsonify({'ok': True, 'type': 'blackjack',
            'player_hand': bj['ph'], 'dealer_hand': [bj['dh'][0], '??'],
            'player_val': pv, 'dealer_val': None, 'status': 'playing', 'bet': bj['bet']})

    if cmd == 'bj_stand':
        bj = session.get('bj')
        if not bj:
            return jsonify({'ok': False, 'message': 'Brak aktywnej gry.'})
        vals = {'2':2,'3':3,'4':4,'5':5,'6':6,'7':7,'8':8,'9':9,'10':10,'J':10,'Q':10,'K':10,'A':11}
        def _hv(h):
            s = sum(vals[c[:-1]] for c in h)
            a = sum(1 for c in h if c[:-1] == 'A')
            while s > 21 and a: s -= 10; a -= 1
            return s
        while _hv(bj['dh']) < 17:
            bj['dh'].append(bj['deck'].pop())
        pv = _hv(bj['ph']); dv = _hv(bj['dh'])
        session.pop('bj', None)
        if dv > 21 or pv > dv:
            earn = bj['bet'] * 2; db.add_cash(uid, guild_id, earn)
            status = 'win'; msg = f'Wygrywasz! +{earn} 🐾'
        elif pv == dv:
            db.add_cash(uid, guild_id, bj['bet'])
            status = 'push'; earn = bj['bet']; msg = f'Remis! Zwrot {bj["bet"]} 🐾'
        else:
            status = 'lose'; earn = 0; msg = f'Dealer wygrywa. Tracisz {bj["bet"]} 🐾'
        return jsonify({'ok': True, 'type': 'blackjack',
            'player_hand': bj['ph'], 'dealer_hand': bj['dh'],
            'player_val': pv, 'dealer_val': dv,
            'status': status, 'earn': earn, 'bet': bj['bet'], 'message': msg})

    if cmd in ('highlow', 'hl'):
        vals = {'2':2,'3':3,'4':4,'5':5,'6':6,'7':7,'8':8,'9':9,'10':10,'J':11,'Q':12,'K':13,'A':14}
        suits = ['♠','♥','♦','♣']
        card = _rnd.choice([f'{r}{s}' for s in suits for r in vals.keys()])
        session['hl'] = {'card': card, 'vals': vals}
        return jsonify({'ok': True, 'type': 'highlow', 'card': card})

    if cmd in ('hl_higher', 'hl_lower'):
        hl = session.get('hl')
        if not hl:
            return jsonify({'ok': False, 'message': 'Brak aktywnej gry. Zacznij: .hl'})
        vals = {'2':2,'3':3,'4':4,'5':5,'6':6,'7':7,'8':8,'9':9,'10':10,'J':11,'Q':12,'K':13,'A':14}
        suits = ['♠','♥','♦','♣']
        old_card = hl['card']
        new_card = _rnd.choice([f'{r}{s}' for s in suits for r in vals.keys()])
        session.pop('hl', None)
        ov = vals[old_card[:-1]]; nv = vals[new_card[:-1]]
        if ov == nv:
            return jsonify({'ok': True, 'type': 'highlow_result', 'old_card': old_card, 'new_card': new_card,
                'status': 'tie', 'earn': 0, 'message': 'Taka sama wartość! Remis 😅'})
        correct = (cmd == 'hl_higher' and nv > ov) or (cmd == 'hl_lower' and nv < ov)
        earn = _rnd.randint(20, 60) if correct else 0
        if correct:
            db.add_cash(uid, guild_id, earn)
        return jsonify({'ok': True, 'type': 'highlow_result', 'old_card': old_card, 'new_card': new_card,
            'status': 'win' if correct else 'lose', 'earn': earn,
            'message': f'{"Dobrze!" if correct else "Źle!"} Karta to {new_card}. '
                       f'{"Wygrywasz " + str(earn) + " 🐾!" if correct else "Nie wygrywasz nic."}'})

    if cmd == 'scratch':
        cost = 30
        if int(wallet.get('cash') or 0) < cost:
            return jsonify({'ok': False, 'message': f'Potrzebujesz {cost} 🐾. Masz {int(wallet.get("cash",0))} 🐾.'})
        db.add_cash(uid, guild_id, -cost)
        syms = ['💎','🌟','🍒','❌','🔔','🍀']
        weights = [2,5,20,50,15,8]
        grid = [_rnd.choices(syms, weights=weights)[0] for _ in range(9)]
        prize_map = {'💎':1000,'🌟':300,'🍒':100,'🔔':50,'🍀':200}
        counts = {}
        for s in grid:
            if s != '❌':
                counts[s] = counts.get(s, 0) + 1
        earn = sum(prize_map.get(s, 0) * (n - 2) for s, n in counts.items() if n >= 3)
        if earn > 0:
            db.add_cash(uid, guild_id, earn)
        return jsonify({'ok': True, 'type': 'scratch', 'grid': grid, 'earn': earn, 'cost': cost})

    if cmd == 'rps':
        choices_map = {'kamien':'🪨','papier':'📄','nozyce':'✂️','k':'🪨','p':'📄','n':'✂️'}
        if not arg or arg.lower() not in choices_map:
            return jsonify({'ok': True, 'type': 'rps_choose'})
        uc = choices_map[arg.lower()]
        bc = _rnd.choice(['🪨','📄','✂️'])
        wins_against = {'🪨':'✂️','📄':'🪨','✂️':'📄'}
        if uc == bc:       status = 'tie'; msg = 'Remis!'
        elif wins_against[uc] == bc: status = 'win'; msg = 'Wygrywasz! 🎉'
        else:              status = 'lose'; msg = 'Przegrywasz! 😢'
        return jsonify({'ok': True, 'type': 'rps_result', 'user': uc, 'bot': bc, 'status': status, 'message': msg})

    # ── Społeczne / Rozrywka ──────────────────────────────────────────────────
    if cmd in ('hug','pat','slap','gg'):
        actions = {'hug':'przytula','pat':'głaszcze','slap':'uderza','gg':'gratuluje'}
        emojis  = {'hug':'🤗','pat':'✋','slap':'👋','gg':'🎉'}
        target = arg or 'kogoś'
        return jsonify({'ok': True, 'type': 'embed', 'color': '#faa61a',
            'title': f'{emojis[cmd]} Akcja',
            'description': f'**{session.get("discord_username","Ty")}** {actions[cmd]} **{target}**!'})

    if cmd == 'ship':
        names = arg.split()
        if len(names) < 2:
            return jsonify({'ok': False, 'message': 'Użycie: .ship imię1 imię2'})
        score = abs(hash(names[0].lower() + names[1].lower())) % 101
        bar = '💗' * (score // 10) + '🖤' * (10 - score // 10)
        return jsonify({'ok': True, 'type': 'embed', 'color': '#f04747',
            'title': '❤️ Ship',
            'description': f'**{names[0]}** + **{names[1]}**\n{bar}\n**{score}%** kompatybilności!'})

    if cmd == 'rate':
        if not arg:
            return jsonify({'ok': False, 'message': 'Podaj coś do ocenienia.'})
        score = abs(hash(arg.lower())) % 11
        return jsonify({'ok': True, 'type': 'embed', 'color': '#7289da',
            'title': '⭐ Ocena', 'description': f'**{arg}** → **{score}/10** ⭐'})

    if cmd == 'fact':
        facts = ['Mrówki nigdy nie śpią.','Miód nigdy się nie psuje.','Ośmiornice mają 3 serca.',
                 'Flamingom kolor dają krewetki.','Koty nie czują słodkiego smaku.',
                 'Delfiny śpią z jednym otwartym okiem.']
        return jsonify({'ok': True, 'type': 'embed', 'color': '#43b581',
            'title': '💡 Ciekawostka', 'description': _rnd.choice(facts)})

    if cmd == 'joke':
        jokes = ['Dlaczego programista wychodzi przez okno? Bo ma za dużo bugów w drzwiach.',
                 'Co mówi null do undefined? Ciebie też nie ma!',
                 'Ile programistów potrzeba żeby wkręcić żarówkę? Zero — to problem sprzętowy.']
        return jsonify({'ok': True, 'type': 'embed', 'color': '#faa61a',
            'title': '😂 Żart', 'description': _rnd.choice(jokes)})

    if cmd == 'quote':
        quotes = ['"Kod zawsze robi to co piszesz, nie to co masz na myśli."',
                  '"Najlepsza dokumentacja to czytelny kod."',
                  '"Najpierw rozwiąż problem, potem napisz kod."']
        return jsonify({'ok': True, 'type': 'embed', 'color': '#99aab5',
            'title': '💬 Cytat', 'description': _rnd.choice(quotes)})

    if cmd == 'reverse':
        return jsonify({'ok': True, 'type': 'embed', 'color': '#7289da',
            'title': '🔄 Odwrócony', 'description': f'`{arg[::-1]}`'}) if arg else \
               jsonify({'ok': False, 'message': 'Podaj tekst.'})

    if cmd == 'upper':
        return jsonify({'ok': True, 'type': 'embed', 'color': '#7289da',
            'title': '🔠 CAPS', 'description': f'`{arg.upper()}`'}) if arg else \
               jsonify({'ok': False, 'message': 'Podaj tekst.'})

    if cmd == 'lower':
        return jsonify({'ok': True, 'type': 'embed', 'color': '#7289da',
            'title': '🔡 małe', 'description': f'`{arg.lower()}`'}) if arg else \
               jsonify({'ok': False, 'message': 'Podaj tekst.'})

    if cmd == 'ping':
        return jsonify({'ok': True, 'type': 'embed', 'color': '#43b581',
            'title': '🏓 Pong!', 'description': 'Dashboard odpowiada ⚡'})

    if cmd == 'beg':
        ok_cd, left = _cooldown('beg_last', 30)
        if not ok_cd:
            return jsonify({'ok': False, 'message': f'Poczekaj {_fmt(left)} przed następnym żebraniem.'})
        if _rnd.random() < 0.3:
            db.set_cooldown(uid, guild_id, 'beg_last')
            fails = ['Nikt ci nie dał.', 'Przechodnie cię zignorowali.', 'Zły dzień na żebranie.']
            return jsonify({'ok': True, 'type': 'embed', 'color': '#e67e22',
                'title': '🙏 Żebranie', 'description': _rnd.choice(fails)})
        earn = _rnd.randint(1, 30)
        db.add_cash(uid, guild_id, earn)
        db.set_cooldown(uid, guild_id, 'beg_last')
        givers = ['staruszek', 'biznesmen', 'student', 'turysta', 'dziecko']
        return jsonify({'ok': True, 'type': 'embed', 'color': '#e67e22',
            'title': '🙏 Żebranie',
            'description': f'Litościwy {_rnd.choice(givers)} dał ci **{earn} 🐾**.'})

    if cmd in ('eco', 'ecolb'):
        lb = db.get_eco_leaderboard(guild_id, limit=10)
        rows = [f'**{i+1}.** {r.get("display_name") or r.get("username","?")} — {int((r.get("cash") or 0) + (r.get("bank") or 0))} 🐾'
                for i, r in enumerate(lb)]
        return jsonify({'ok': True, 'type': 'embed', 'color': '#faa61a',
            'title': '🐾 Top 10 — Mopsy', 'description': '\n'.join(rows) or 'Brak danych'})

    if cmd == '8ball':
        if not arg:
            return jsonify({'ok': False, 'message': 'Zadaj pytanie: `.8ball czy dziś padnie?`'})
        answers = [
            ('Tak!', '#43b581'), ('Zdecydowanie tak.', '#43b581'), ('Na pewno.', '#43b581'),
            ('Bez wątpienia.', '#43b581'), ('Raczej tak.', '#faa61a'),
            ('Znaki wskazują na tak.', '#faa61a'), ('Zapytaj ponownie.', '#faa61a'),
            ('Nie można przewidzieć.', '#faa61a'), ('Nie licz na to.', '#f04747'),
            ('Moja odpowiedź brzmi nie.', '#f04747'), ('Bardzo wątpliwe.', '#f04747'),
            ('Zdecydowanie nie.', '#f04747'),
        ]
        ans, color = _rnd.choice(answers)
        return jsonify({'ok': True, 'type': '8ball', 'question': arg, 'answer': ans, 'color': color})

    if cmd in ('coinflip', 'flip'):
        result = _rnd.choice(['ORZEŁ', 'RESZKA'])
        return jsonify({'ok': True, 'type': 'coinflip', 'result': result})

    if cmd in ('roll', 'dice'):
        try:
            sides = int(arg) if arg and arg.isdigit() else 6
            sides = max(2, min(sides, 1000))
        except Exception:
            sides = 6
        result = _rnd.randint(1, sides)
        return jsonify({'ok': True, 'type': 'dice', 'result': result, 'sides': sides})

    if cmd in ('choose', 'wybierz'):
        if not arg:
            return jsonify({'ok': False, 'message': 'Użycie: `.choose opcja1 opcja2 opcja3`'})
        opts = [o.strip() for o in arg.replace(',', ' ').split() if o.strip()]
        if len(opts) < 2:
            return jsonify({'ok': False, 'message': 'Podaj co najmniej 2 opcje.'})
        chosen = _rnd.choice(opts)
        return jsonify({'ok': True, 'type': 'embed', 'color': '#9b59b6',
            'title': '🎯 Wybór', 'description': f'Wybieram: **{chosen}**'})

    if cmd == 'owo':
        if not arg:
            return jsonify({'ok': False, 'message': 'Podaj tekst.'})
        t = arg.replace('r','w').replace('l','w').replace('R','W').replace('L','W')
        faces = ['OwO', 'UwU', '>w<', '^w^']
        return jsonify({'ok': True, 'type': 'embed', 'color': '#ff69b4',
            'title': 'OwO', 'description': f'{t} {_rnd.choice(faces)}'})

    if cmd == 'uptime':
        import time as _time
        up = int(_time.time())
        return jsonify({'ok': True, 'type': 'embed', 'color': '#43b581',
            'title': '⏱️ Uptime', 'description': 'Dashboard działa ✅'})

    if cmd in ('remindme', 'remind'):
        if not arg:
            return jsonify({'ok': False, 'message': 'Użycie: `.remindme 10m Zadzwoń do mamy`'})
        parts = arg.split(None, 1)
        if len(parts) < 2:
            return jsonify({'ok': False, 'message': 'Użycie: `.remindme 10m treść`'})
        dur_str, text = parts
        import re as _re
        m2 = _re.fullmatch(r'(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?', dur_str.lower())
        if not m2 or not any(m2.groups()):
            return jsonify({'ok': False, 'message': 'Nieprawidłowy czas. Przykład: 10m, 1h30m, 2d'})
        d,h,mi,s = (int(x) if x else 0 for x in m2.groups())
        secs = d*86400+h*3600+mi*60+s
        if secs <= 0:
            return jsonify({'ok': False, 'message': 'Czas musi być większy niż 0.'})
        from datetime import datetime as _dt
        remind_at = (_dt.utcnow() + __import__('datetime').timedelta(seconds=secs)).isoformat()
        db.add_reminder(uid, guild_id, 0, text, remind_at)
        return jsonify({'ok': True, 'type': 'embed', 'color': '#43b581',
            'title': '⏰ Przypomnienie ustawione',
            'description': f'Przypomnę ci o: **{text}**\nZa: **{dur_str}**'})

    if cmd == 'warnpoints':
        lb = db.get_warn_points_leaderboard(guild_id, limit=10)
        if not lb:
            return jsonify({'ok': True, 'type': 'embed', 'color': '#f04747',
                'title': '⚠️ Warn Leaderboard', 'description': 'Nikt nie ma warnpointów.'})
        rows = [f'**{i+1}.** {r.get("display_name") or r.get("username","?")} — {r.get("warn_points",0):.1f} wp'
                for i, r in enumerate(lb)]
        return jsonify({'ok': True, 'type': 'embed', 'color': '#f04747',
            'title': '⚠️ Warn Leaderboard', 'description': '\n'.join(rows)})

    if cmd in ('tag', 'taglist'):
        if cmd == 'taglist' or not arg:
            tags = db.list_tags(guild_id)
            if not tags:
                return jsonify({'ok': True, 'type': 'embed', 'color': '#99aab5',
                    'title': '🏷️ Tagi', 'description': 'Brak tagów. Admin tworzy tagi komendą `.tagcreate`'})
            rows = [f'**{t["name"]}** (użycia: {t["uses"]})' for t in tags[:20]]
            return jsonify({'ok': True, 'type': 'embed', 'color': '#7289da',
                'title': f'🏷️ Tagi ({len(tags)})', 'description': '\n'.join(rows)})
        tag = db.get_tag(guild_id, arg.lower())
        if not tag:
            return jsonify({'ok': False, 'message': f'Tag `{arg}` nie istnieje.'})
        db.increment_tag_uses(guild_id, arg.lower())
        return jsonify({'ok': True, 'type': 'embed', 'color': '#7289da',
            'title': f'🏷️ {tag["name"]}', 'description': tag['content']})

    if cmd in ('roleinfo', 'ri'):
        if not arg:
            return jsonify({'ok': False, 'message': 'Podaj nazwę rangi: `.roleinfo Sierżant`'})
        ranks = db.get_ranks(guild_id)
        rank = next((r for r in ranks if arg.lower() in r['name'].lower()), None)
        if not rank:
            return jsonify({'ok': False, 'message': f'Nie znaleziono rangi: `{arg}`'})
        return jsonify({'ok': True, 'type': 'embed', 'color': '#7289da',
            'title': f'{rank["icon"]} {rank["name"]}',
            'fields': [
                {'name': 'Wymagane pkt', 'value': str(rank.get('required_points', 0))},
                {'name': 'Typ', 'value': 'Specjalna' if rank.get('is_special') else 'Auto (punkty)'},
            ]})

    if cmd in ('job', 'praca', 'jobs'):
        all_jobs = db.get_jobs(guild_id)
        my_jobs  = db.get_user_jobs(uid, guild_id)
        my_ids   = {j['job_id'] for j in my_jobs}
        user_pts = (db.get_user(uid, guild_id) or {}).get('points', 0) or 0
        if not all_jobs:
            return jsonify({'ok': True, 'type': 'embed', 'color': '#99aab5',
                'title': '💼 Prace', 'description': 'Brak prac. Admin tworzy prace komendą `.createjob`'})
        fields = []
        for j in all_jobs:
            status = '✅' if j['id'] in my_ids else ('🔒' if user_pts < j.get('required_points', 0) else '🔓')
            cph = j.get('cash_per_hour', 0) or 0
            fields.append({'name': f'{status} {j["icon"]} {j["name"]}',
                'value': f'Req: {j["required_points"]:.0f}pkt | +{j.get("points_bonus_per_hour",0):.1f}pph | {cph:.0f}🐾/h'})
        desc = f'**Twoje prace:** {", ".join(j["name"] for j in my_jobs) or "Brak"}'
        return jsonify({'ok': True, 'type': 'embed', 'color': '#7289da',
            'title': '💼 Prace na serwerze', 'description': desc, 'fields': fields[:10]})

    if cmd == 'avatar':
        avatar_url = session.get('discord_avatar', '')
        username = session.get('discord_username', '')
        return jsonify({'ok': True, 'type': 'avatar', 'url': avatar_url, 'name': username})

    if cmd in ('serverinfo', 'si'):
        info2 = _guild_info(guild_id)
        guild_cfg = db.get_guild(guild_id) or {}
        stats = db.get_guild_stats(guild_id)
        return jsonify({'ok': True, 'type': 'embed', 'color': '#7289da',
            'title': f'ℹ️ {info2.get("name", str(guild_id))}',
            'fields': [
                {'name': 'Użytkownicy w DB', 'value': str(stats.get('total_users', 0))},
                {'name': 'Sesje', 'value': str(stats.get('total_sessions', 0))},
                {'name': 'Rangi', 'value': str(stats.get('total_ranks', 0))},
                {'name': 'Pkt/h', 'value': str(guild_cfg.get('points_per_hour', 10))},
            ]})

    if cmd == 'trivia':
        questions = [
            {'q':'Stolica Polski?','a':'Warszawa','opts':['Kraków','Gdańsk','Warszawa','Poznań']},
            {'q':'Ile metrów ma km?','a':'1000','opts':['100','500','1000','10000']},
            {'q':'Największy ocean?','a':'Spokojny','opts':['Atlantycki','Spokojny','Indyjski','Arktyczny']},
            {'q':'Rok końca II WŚ?','a':'1945','opts':['1939','1943','1945','1950']},
            {'q':'√144 = ?','a':'12','opts':['10','11','12','14']},
            {'q':'Symbol Au to?','a':'Złoto','opts':['Srebro','Złoto','Miedź','Platyna']},
            {'q':'Ile kontynentów?','a':'7','opts':['5','6','7','8']},
        ]
        q = _rnd.choice(questions)
        opts = q['opts'][:]
        _rnd.shuffle(opts)
        session['trivia'] = {'answer': q['a'], 'reward': _rnd.randint(20, 60)}
        return jsonify({'ok': True, 'type': 'trivia', 'question': q['q'], 'options': opts})

    if cmd == 'trivia_answer':
        t = session.get('trivia')
        if not t:
            return jsonify({'ok': False, 'message': 'Brak aktywnego quizu. Użyj `.trivia`'})
        session.pop('trivia', None)
        correct = arg.strip() == t['answer']
        if correct:
            db.add_cash(uid, guild_id, t['reward'])
        return jsonify({'ok': True, 'type': 'trivia_result',
            'correct': correct, 'answer': t['answer'],
            'reward': t['reward'] if correct else 0,
            'message': f'{"✅ Dobrze!" if correct else "❌ Źle!"} Odpowiedź: **{t["answer"]}**' +
                       (f' +{t["reward"]} 🐾' if correct else '')})

    if cmd == 'rep':
        if not arg:
            u2 = db.get_user(uid, guild_id) or {}
            return jsonify({'ok': True, 'type': 'embed', 'color': '#9b59b6',
                'title': '⭐ Reputacja', 'description': f'Twoje rep: **{u2.get("rep_points",0)}**'})
        ok_cd, left = _cooldown('rep_last', 1440)
        if not ok_cd:
            return jsonify({'ok': False, 'message': f'Możesz dać rep raz na 24h. Poczekaj {_fmt(left)}.'})
        all_u = db.get_all_users(guild_id)
        target = next((u3 for u3 in all_u if arg.lstrip('@').lower() in
                       (u3.get('display_name','') or u3.get('username','')).lower()), None)
        if not target:
            return jsonify({'ok': False, 'message': f'Nie znaleziono użytkownika `{arg}`.'})
        if target['user_id'] == uid:
            return jsonify({'ok': False, 'message': 'Nie możesz dać rep sobie.'})
        db.update_user(int(target['user_id']), guild_id,
                       rep_points=(target.get('rep_points') or 0) + 1)
        db.set_cooldown(uid, guild_id, 'rep_last')
        name = target.get('display_name') or target.get('username') or str(target['user_id'])
        return jsonify({'ok': True, 'type': 'embed', 'color': '#9b59b6',
            'title': '⭐ Rep dany!', 'description': f'Dałeś +1 rep dla **{name}**!'})

    return jsonify({'ok': False, 'message': f'Komenda `.{cmd}` niedostępna w przeglądarce.'})


# ─── Clock in/out from browser ───────────────────────────────────────────────

@app.route('/guild/<int:guild_id>/me/clock', methods=['POST'])
@any_login_required
def user_clock(guild_id):
    uid = _session_discord_id()
    if not uid:
        return jsonify({'ok': False, 'message': 'Zaloguj się przez Discord.'})
    db.ensure_guild(guild_id)
    db.ensure_user(uid, guild_id)
    user = db.get_user(uid, guild_id) or {}
    if user.get('is_banned'):
        return jsonify({'ok': False, 'message': 'Jesteś zbanowany.'})
    if user.get('is_clocked_in'):
        result = db.clock_out(uid, guild_id) or {}
        hrs = round(result.get('hours', 0), 2)
        pts = round(result.get('points_earned', 0), 1)
        return jsonify({'ok': True, 'action': 'out',
            'message': f'Clock out! Sesja: {hrs}h, +{pts} pkt',
            'points_earned': pts, 'duration': hrs})
    else:
        db.clock_in(uid, guild_id)
        return jsonify({'ok': True, 'action': 'in', 'message': 'Clock in! Sesja rozpoczęta ✅'})


@app.route('/guild/<int:guild_id>/leaderboard')
@any_login_required
def leaderboard_page(guild_id):
    db.ensure_guild(guild_id)
    info = _guild_info(guild_id)
    top_points = db.get_leaderboard(guild_id, limit=25)
    # Enrich with rank name
    for u in top_points:
        r = db.get_user_auto_rank(u['user_id'], guild_id)
        u['rank_name'] = r['name'] if r else ''
        u['rank_icon'] = r['icon'] if r else ''
    # Mopsy leaderboard – sort by cash descending
    with db._get_conn() as conn:
        top_cash = [dict(r) for r in conn.execute(
            'SELECT * FROM users WHERE guild_id=? AND is_banned=0 ORDER BY cash DESC LIMIT 25',
            (guild_id,)).fetchall()]
    uid = _session_discord_id()
    # Current user's position in each board
    all_users_pts = db.get_leaderboard(guild_id, limit=9999)
    pos_pts  = next((i+1 for i, u in enumerate(all_users_pts) if u['user_id'] == uid), None) if uid else None
    with db._get_conn() as conn:
        all_cash = [dict(r) for r in conn.execute(
            'SELECT * FROM users WHERE guild_id=? AND is_banned=0 ORDER BY cash DESC',
            (guild_id,)).fetchall()]
    pos_cash = next((i+1 for i, u in enumerate(all_cash) if u['user_id'] == uid), None) if uid else None
    return render_template('leaderboard.html',
        guild_id=guild_id,
        guild_name=info.get('name', str(guild_id)),
        icon_url=_guild_icon(guild_id, info.get('icon')),
        top_points=top_points, top_cash=top_cash,
        uid=uid, pos_pts=pos_pts, pos_cash=pos_cash,
    )


# ─── Commands reference page ──────────────────────────────────────────────────

@app.route('/guild/<int:guild_id>/commands')
@login_required
def commands_page(guild_id):
    db.ensure_guild(guild_id)
    info = _guild_info(guild_id)
    return render_template('commands.html',
                           guild_id=guild_id,
                           guild_name=info.get('name', str(guild_id)),
                           icon_url=info.get('icon_url'))


# ─── Command Panel (execute commands from GUI) ────────────────────────────────

@app.route('/guild/<int:guild_id>/command-panel')
@login_required
def command_panel_page(guild_id):
    db.ensure_guild(guild_id)
    info         = _guild_info(guild_id)
    users        = db.get_all_users(guild_id)
    ranks        = db.get_ranks(guild_id)
    factions     = db.get_factions(guild_id)
    channels_raw = _dget(f'/guilds/{guild_id}/channels') or []
    text_channels = sorted(
        [type('C', (), {'id': str(c['id']), 'name': c['name']})()
         for c in channels_raw if c.get('type') == 0],
        key=lambda c: c.name)
    import json as _json
    users_json = _json.dumps([
        {'id': str(u['user_id']),
         'name': u.get('display_name') or u.get('username') or str(u['user_id'])}
        for u in users
    ])
    return render_template('command_panel.html',
                           guild_id=guild_id,
                           guild_name=info.get('name', str(guild_id)),
                           icon_url=info.get('icon_url'),
                           users_json=users_json,
                           ranks=ranks,
                           factions=factions,
                           text_channels=text_channels)


def _parse_dur_seconds(s: str):
    """Parse '1h30m' style string to seconds. Returns None on failure."""
    import re
    m = re.fullmatch(r'(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?', s.strip().lower())
    if not m or not any(m.groups()):
        return None
    d, h, mi, sec = (int(x) if x else 0 for x in m.groups())
    total = d*86400 + h*3600 + mi*60 + sec
    return total if total > 0 else None


@app.route('/guild/<int:guild_id>/execute-command', methods=['POST'])
@login_required
def execute_command(guild_id):
    from flask import jsonify as _json
    from datetime import datetime, timezone, timedelta

    cmd        = request.form.get('cmd', '').strip()
    user_id    = request.form.get('user_id', '').strip()
    amount_str = request.form.get('amount', '').strip()
    reason     = request.form.get('reason', 'Dashboard').strip() or 'Dashboard'
    note       = request.form.get('note', '').strip()
    duration   = request.form.get('duration', '').strip()
    channel_id = request.form.get('channel_id', '').strip()
    rank_id    = request.form.get('rank_id', '').strip()
    faction_id = request.form.get('faction_id', '').strip()
    nick       = request.form.get('nick', '').strip()
    tag_name   = request.form.get('tag_name', '').strip().lower()
    tag_content= request.form.get('tag_content', '').strip()
    announce   = request.form.get('announce_text', '').strip()
    purge_n    = request.form.get('purge_count', '10').strip()
    uid_direct = request.form.get('user_id_direct', '').strip()

    def ok(msg):   return _json({'ok': True,  'message': msg})
    def err(msg):  return _json({'ok': False, 'error':   msg})

    db.ensure_guild(guild_id)

    # ── helpers ────────────────────────────────────────────────────────────────
    def _uid():
        try: return int(user_id)
        except: return None

    def _amt():
        try: return float(amount_str)
        except: return None

    # ── POINTS ────────────────────────────────────────────────────────────────
    if cmd == 'addpoints':
        uid = _uid(); amt = _amt()
        if not uid: return err('Wybierz użytkownika.')
        if amt is None or amt <= 0: return err('Podaj poprawną liczbę punktów.')
        db.ensure_user(uid, guild_id)
        new = db.add_points(uid, guild_id, amt,
                            note=note or f'Dashboard +{amt}', transaction_type='manual', assigned_by=0)
        return ok(f'+{amt:.1f} pkt → nowy stan: {new:.1f} pkt')

    if cmd == 'removepoints':
        uid = _uid(); amt = _amt()
        if not uid: return err('Wybierz użytkownika.')
        if amt is None or amt <= 0: return err('Podaj poprawną liczbę punktów.')
        db.ensure_user(uid, guild_id)
        new = db.add_points(uid, guild_id, -amt,
                            note=note or f'Dashboard -{amt}', transaction_type='manual', assigned_by=0)
        return ok(f'-{amt:.1f} pkt → nowy stan: {new:.1f} pkt')

    if cmd == 'setpoints':
        uid = _uid(); amt = _amt()
        if not uid: return err('Wybierz użytkownika.')
        if amt is None or amt < 0: return err('Podaj poprawną liczbę punktów.')
        db.ensure_user(uid, guild_id)
        new = db.set_points(uid, guild_id, amt, note='Ustawione z Dashboardu', assigned_by=0)
        return ok(f'Punkty ustawione na {new:.1f} pkt')

    # ── ECONOMY ───────────────────────────────────────────────────────────────
    if cmd == 'addmoney':
        uid = _uid(); amt = _amt()
        if not uid: return err('Wybierz użytkownika.')
        if amt is None or amt <= 0: return err('Podaj poprawną kwotę.')
        db.ensure_user(uid, guild_id)
        db.add_cash(uid, guild_id, amt)
        w = db.get_wallet(uid, guild_id)
        return ok(f'+{amt:.0f} 🐾 → gotówka: {int(w["cash"])} 🐾')

    if cmd == 'removemoney':
        uid = _uid(); amt = _amt()
        if not uid: return err('Wybierz użytkownika.')
        if amt is None or amt <= 0: return err('Podaj poprawną kwotę.')
        db.ensure_user(uid, guild_id)
        db.add_cash(uid, guild_id, -amt)
        w = db.get_wallet(uid, guild_id)
        return ok(f'-{amt:.0f} 🐾 → gotówka: {int(w["cash"])} 🐾')

    if cmd == 'setmoney':
        uid = _uid(); amt = _amt()
        if not uid: return err('Wybierz użytkownika.')
        if amt is None or amt < 0: return err('Podaj poprawną kwotę.')
        db.ensure_user(uid, guild_id)
        with db._lock:
            with db._get_conn() as conn:
                conn.execute('UPDATE users SET cash=? WHERE user_id=? AND guild_id=?',
                             (amt, uid, guild_id))
                conn.commit()
        return ok(f'Gotówka ustawiona na {amt:.0f} 🐾')

    # ── MODERATION ────────────────────────────────────────────────────────────
    if cmd == 'warn':
        uid = _uid()
        if not uid: return err('Wybierz użytkownika.')
        db.ensure_user(uid, guild_id)
        db.add_warning(uid, guild_id, reason=reason, warned_by=0, is_auto=False)
        db.add_warn_points(uid, guild_id, 0.5, reason=reason, given_by=0)
        count = db.get_warning_count(uid, guild_id)
        cfg   = db.get_guild(guild_id) or {}
        limit = cfg.get('warn_limit', 3)
        action = ''
        if count >= limit:
            db.update_user(uid, guild_id, is_banned=1)
            _dpost(f'/guilds/{guild_id}/bans/{uid}', {'delete_message_days': 0, 'reason': reason})
            action = ' | AUTO-BAN wykonany!'
        elif count == 2:
            _ddel(f'/guilds/{guild_id}/members/{uid}')
            action = ' | AUTO-KICK wykonany!'
        elif count == 1:
            until = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
            _dpatch(f'/guilds/{guild_id}/members/{uid}',
                    {'communication_disabled_until': until})
            action = ' | AUTO-TIMEOUT 1h wykonany!'
        return ok(f'Ostrzeżono ({count}/{limit}){action}')

    if cmd == 'warnpoints':
        uid = _uid()
        if not uid: return err('Wybierz użytkownika.')
        db.ensure_user(uid, guild_id)
        db.add_warn_points(uid, guild_id, 1.0, reason=reason, given_by=0)
        u = db.get_user(uid, guild_id)
        return ok(f'+1 warn point → łącznie: {u.get("warn_points", 0):.1f}')

    if cmd == 'clearwarn':
        uid = _uid()
        if not uid: return err('Wybierz użytkownika.')
        n = db.clear_warnings(uid, guild_id)
        return ok(f'Usunięto {n} ostrzeżeń.')

    if cmd == 'mute':
        uid = _uid()
        if not uid: return err('Wybierz użytkownika.')
        if not duration: return err('Podaj czas trwania (np. 1h, 30m).')
        secs = _parse_dur_seconds(duration)
        if not secs: return err('Nieprawidłowy czas. Użyj: 10m, 1h, 2d.')
        if secs > 2419200: return err('Max timeout Discord to 28 dni.')
        until = (datetime.now(timezone.utc) + timedelta(seconds=secs)).isoformat()
        data, e2 = _dpatch(f'/guilds/{guild_id}/members/{uid}',
                           {'communication_disabled_until': until})
        if e2: return err(f'Discord API: {e2}')
        return ok(f'Timeout {duration} ustawiony.')

    if cmd == 'unmute':
        uid = _uid()
        if not uid: return err('Wybierz użytkownika.')
        data, e2 = _dpatch(f'/guilds/{guild_id}/members/{uid}',
                           {'communication_disabled_until': None})
        if e2: return err(f'Discord API: {e2}')
        return ok('Timeout cofnięty.')

    if cmd == 'kick':
        uid = _uid()
        if not uid: return err('Wybierz użytkownika.')
        ok2 = _ddel(f'/guilds/{guild_id}/members/{uid}')
        if not ok2: return err('Brak uprawnień lub użytkownik nie jest na serwerze.')
        return ok('Użytkownik wyrzucony z serwera.')

    if cmd == 'discordban':
        uid = _uid()
        if not uid: return err('Wybierz użytkownika.')
        data, e2 = _dpost(f'/guilds/{guild_id}/bans/{uid}',
                          {'delete_message_days': 0, 'reason': reason})
        # PUT also works for ban
        if e2:
            ok3 = _dput(f'/guilds/{guild_id}/bans/{uid}')
            if not ok3: return err(f'Discord API: {e2}')
        db.ensure_user(uid, guild_id)
        db.update_user(uid, guild_id, is_banned=1)
        return ok('Użytkownik zbanowany na serwerze Discord.')

    if cmd == 'discordunban':
        try: uid = int(uid_direct)
        except: return err('Podaj prawidłowe ID użytkownika.')
        ok3 = _ddel(f'/guilds/{guild_id}/bans/{uid}')
        if not ok3: return err('Nie można odbanować (brak uprawnień lub użytkownik nie był zbanowany).')
        return ok(f'Użytkownik {uid} odbanowany.')

    if cmd == 'softban':
        uid = _uid()
        if not uid: return err('Wybierz użytkownika.')
        _dpost(f'/guilds/{guild_id}/bans/{uid}',
               {'delete_message_days': 1, 'reason': f'Softban: {reason}'})
        import time; time.sleep(0.5)
        _ddel(f'/guilds/{guild_id}/bans/{uid}')
        return ok('Soft ban wykonany (wiadomości usunięte, użytkownik może dołączyć ponownie).')

    if cmd == 'purge':
        if not channel_id: return err('Wybierz kanał.')
        try: n = max(1, min(100, int(purge_n)))
        except: n = 10
        msgs = _dget(f'/channels/{channel_id}/messages?limit={n}') or []
        if not msgs: return ok('Brak wiadomości do usunięcia.')
        ids = [m['id'] for m in msgs]
        if len(ids) == 1:
            _ddel(f'/channels/{channel_id}/messages/{ids[0]}')
        else:
            _dpost(f'/channels/{channel_id}/messages/bulk-delete', {'messages': ids})
        return ok(f'Usunięto {len(ids)} wiadomości.')

    # ── CHANNELS ──────────────────────────────────────────────────────────────
    if cmd in ('lock', 'unlock', 'hide', 'unhide'):
        if not channel_id: return err('Wybierz kanał.')
        ch_data = _dget(f'/channels/{channel_id}')
        if not ch_data: return err('Nie można pobrać danych kanału.')
        overwrites = ch_data.get('permission_overwrites', [])
        everyone_id = str(guild_id)  # @everyone role has same ID as guild
        ov = next((o for o in overwrites if o['id'] == everyone_id), None)
        allow = int(ov['allow']) if ov else 0
        deny  = int(ov['deny'])  if ov else 0
        SEND = 1 << 11   # SEND_MESSAGES
        VIEW = 1 << 10   # VIEW_CHANNEL
        if cmd == 'lock':
            deny |= SEND; allow &= ~SEND
        elif cmd == 'unlock':
            deny &= ~SEND; allow &= ~SEND
        elif cmd == 'hide':
            deny |= VIEW; allow &= ~VIEW
        elif cmd == 'unhide':
            deny &= ~VIEW; allow &= ~VIEW
        new_ov = [o for o in overwrites if o['id'] != everyone_id]
        new_ov.append({'id': everyone_id, 'type': 0, 'allow': str(allow), 'deny': str(deny)})
        data2, e2 = _dpatch(f'/channels/{channel_id}', {'permission_overwrites': new_ov})
        if e2: return err(f'Discord API: {e2}')
        labels = {'lock': '🔒 zablokowany', 'unlock': '🔓 odblokowany',
                  'hide': '🙈 ukryty', 'unhide': '👁️ odkryty'}
        return ok(f'Kanał {labels[cmd]}.')

    if cmd == 'nick':
        uid = _uid()
        if not uid: return err('Wybierz użytkownika.')
        new_nick = nick if nick else None
        data2, e2 = _dpatch(f'/guilds/{guild_id}/members/{uid}', {'nick': new_nick})
        if e2: return err(f'Discord API: {e2}')
        return ok(f'Nick {"zresetowany" if not new_nick else f"zmieniony na {new_nick}"}.')

    # ── RANKS ─────────────────────────────────────────────────────────────────
    if cmd == 'giverank':
        uid = _uid()
        if not uid: return err('Wybierz użytkownika.')
        if not rank_id: return err('Wybierz rangę.')
        rank = db.get_rank_by_id(int(rank_id))
        if not rank: return err('Ranga nie istnieje.')
        db.ensure_user(uid, guild_id)
        if rank.get('is_special') or rank.get('is_owner_only'):
            ok2 = db.give_special_rank(uid, guild_id, int(rank_id), assigned_by=0, note='Dashboard')
            if not ok2: return err('Użytkownik już posiada tę rangę.')
            if rank.get('role_id'):
                _dput(f'/guilds/{guild_id}/members/{uid}/roles/{rank["role_id"]}')
        else:
            req = rank.get('required_points', 0)
            u = db.get_user(uid, guild_id)
            old_rank = db.get_user_auto_rank(uid, guild_id)
            if (u.get('points') or 0) < req:
                db.set_points(uid, guild_id, req, note=f'Nadanie rangi: {rank["name"]}', assigned_by=0)
            _sync_auto_rank_role(guild_id, uid, old_rank.get('role_id') if old_rank else None)
        return ok(f'Ranga {rank["icon"]} {rank["name"]} nadana.')

    if cmd == 'takerank':
        uid = _uid()
        if not uid: return err('Wybierz użytkownika.')
        if not rank_id: return err('Wybierz rangę.')
        rank = db.get_rank_by_id(int(rank_id))
        if not rank: return err('Ranga nie istnieje.')
        db.remove_special_rank(uid, guild_id, int(rank_id))
        if rank.get('role_id'):
            _ddel(f'/guilds/{guild_id}/members/{uid}/roles/{rank["role_id"]}')
        return ok(f'Ranga {rank["icon"]} {rank["name"]} odebrana.')

    # ── USER MANAGEMENT ───────────────────────────────────────────────────────
    if cmd == 'forceclockout':
        uid = _uid()
        if not uid: return err('Wybierz użytkownika.')
        db.ensure_user(uid, guild_id)
        db.clockout_user(uid, guild_id)
        return ok('Clock-out wymuszony.')

    if cmd == 'resetuser':
        uid = _uid()
        if not uid: return err('Wybierz użytkownika.')
        db.reset_user(uid, guild_id)
        return ok('Dane użytkownika zresetowane.')

    if cmd == 'assignfaction':
        uid = _uid()
        if not uid: return err('Wybierz użytkownika.')
        if not faction_id: return err('Wybierz frakcję.')
        faction = db.get_faction(int(faction_id))
        if not faction: return err('Frakcja nie istnieje.')
        db.ensure_user(uid, guild_id)
        db.assign_faction(uid, guild_id, int(faction_id), assigned_by=0)
        _sync_faction_discord_roles(guild_id, uid, faction, add=True)
        return ok(f'Przypisano do frakcji {faction["icon"]} {faction["name"]}.')

    # ── TAGS ──────────────────────────────────────────────────────────────────
    if cmd == 'tagcreate':
        if not tag_name: return err('Podaj nazwę tagu.')
        if not tag_content: return err('Podaj treść tagu.')
        ok2 = db.create_tag(guild_id, tag_name, tag_content, author_id=0)
        if not ok2: return err(f'Tag "{tag_name}" już istnieje. Usuń go najpierw.')
        return ok(f'Tag "{tag_name}" utworzony.')

    if cmd == 'tagdelete':
        if not tag_name: return err('Podaj nazwę tagu.')
        ok2 = db.delete_tag(guild_id, tag_name)
        if not ok2: return err(f'Tag "{tag_name}" nie istnieje.')
        return ok(f'Tag "{tag_name}" usunięty.')

    # ── ANNOUNCE ──────────────────────────────────────────────────────────────
    if cmd == 'announce':
        if not channel_id: return err('Wybierz kanał.')
        if not announce: return err('Wpisz treść ogłoszenia.')
        data2, e2 = _dpost(f'/channels/{channel_id}/messages',
                           {'embeds': [{'description': announce, 'color': 0x7289DA}]})
        if e2: return err(f'Discord API: {e2}')
        return ok('Ogłoszenie wysłane.')

    # ── DEAFEN / UNDEAFEN ─────────────────────────────────────────────────────
    if cmd == 'deafen':
        uid = _uid()
        if not uid: return err('Wybierz użytkownika.')
        data2, e2 = _dpatch(f'/guilds/{guild_id}/members/{uid}', {'deaf': True})
        if e2: return err(f'Discord API: {e2}')
        return ok('Użytkownik ogłuszony (server deafen).')

    if cmd == 'undeafen':
        uid = _uid()
        if not uid: return err('Wybierz użytkownika.')
        data2, e2 = _dpatch(f'/guilds/{guild_id}/members/{uid}', {'deaf': False})
        if e2: return err(f'Discord API: {e2}')
        return ok('Użytkownik odogłuszony.')

    # ── TEMPBAN ───────────────────────────────────────────────────────────────
    if cmd == 'tempban':
        uid = _uid()
        if not uid: return err('Wybierz użytkownika.')
        if not duration: return err('Podaj czas bana (np. 1d, 7d).')
        secs = _parse_dur_seconds(duration)
        if not secs: return err('Nieprawidłowy czas.')
        data2, e2 = _dpost(f'/guilds/{guild_id}/bans/{uid}',
                           {'delete_message_days': 0, 'reason': f'Tempban {duration}: {reason}'})
        if e2:
            _dput(f'/guilds/{guild_id}/bans/{uid}')
        db.ensure_user(uid, guild_id)
        db.update_user(uid, guild_id, is_banned=1)
        # Schedule unban via reminder-style DB entry (bot will process)
        from datetime import datetime, timedelta
        unban_at = (datetime.now() + timedelta(seconds=secs)).isoformat()
        db.add_reminder(0, guild_id, 0, f'__UNBAN__{uid}', unban_at)
        return ok(f'Tempban {duration} ustawiony. Automatyczny unban o {unban_at[:16]}.')

    # ── NOTE (add admin note) ─────────────────────────────────────────────────
    if cmd == 'addnote':
        uid = _uid()
        if not uid: return err('Wybierz użytkownika.')
        if not note: return err('Wpisz treść notatki.')
        db.ensure_user(uid, guild_id)
        with db._lock:
            with db._get_conn() as conn:
                conn.execute('INSERT INTO notes (user_id, guild_id, content, author_id) VALUES (?,?,?,?)',
                             (uid, guild_id, note, 0))
                conn.commit()
        return ok(f'Notatka dodana do użytkownika.')

    # ── LEADERBOARD BAN/UNBAN (not Discord ban) ───────────────────────────────
    if cmd == 'lbban':
        uid = _uid()
        if not uid: return err('Wybierz użytkownika.')
        db.ensure_user(uid, guild_id)
        db.update_user(uid, guild_id, is_banned=1)
        return ok('Użytkownik zablokowany na liście rankingowej.')

    if cmd == 'lbunban':
        uid = _uid()
        if not uid: return err('Wybierz użytkownika.')
        db.update_user(uid, guild_id, is_banned=0)
        return ok('Użytkownik odblokowany z listy rankingowej.')

    # ── CLEAR WARN POINTS ─────────────────────────────────────────────────────
    if cmd == 'clearwarnpoints':
        uid = _uid()
        if not uid: return err('Wybierz użytkownika.')
        db.ensure_user(uid, guild_id)
        db.update_user(uid, guild_id, warn_points=0)
        return ok('Warn points wyzerowane.')

    return err(f'Nieznana komenda: {cmd}')


# ─── Guild overview ───────────────────────────────────────────────────────────

@app.route('/guild/<int:guild_id>')
@login_required
def guild_overview(guild_id):
    db.ensure_guild(guild_id)
    info = _guild_info(guild_id)
    guild_cfg = db.get_guild(guild_id) or {}
    stats = db.get_guild_stats(guild_id)
    top = db.get_leaderboard(guild_id, limit=5)
    recent_tx = db.get_all_transactions(guild_id, limit=10)
    active = [u for u in db.get_all_users(guild_id) if u['is_clocked_in']]
    recent_warns = db.get_all_warnings(guild_id, limit=5)
    channels = _dget(f'/guilds/{guild_id}/channels') or []
    text_channels = [c for c in channels if c.get('type') == 0]
    # Resolve clock channel name for the quick-action card
    clock_ch_id = guild_cfg.get('clock_channel_id')
    clock_channel_name = None
    if clock_ch_id:
        ch = next((c for c in text_channels if c['id'] == str(clock_ch_id)), None)
        clock_channel_name = ch['name'] if ch else f'ID:{clock_ch_id}'
    return render_template('guild.html',
        guild_id=guild_id, guild_name=info.get('name', str(guild_id)),
        icon_url=_guild_icon(guild_id, info.get('icon')),
        stats=stats, top=top, recent_tx=recent_tx,
        active_now=active, recent_warns=recent_warns,
        text_channels=text_channels,
        clock_channel_name=clock_channel_name,
        clock_channel_id=clock_ch_id)


# ─── Send clock embed ─────────────────────────────────────────────────────────

@app.route('/guild/<int:guild_id>/send-clock-embed', methods=['POST'])
@login_required
def send_clock_embed(guild_id):
    from datetime import date as _date
    cfg = db.get_guild(guild_id) or {}

    # Allow overriding the channel via form (optional)
    channel_id = request.form.get('channel_id', '').strip()
    if channel_id and channel_id.isdigit():
        channel_id = int(channel_id)
    else:
        channel_id = cfg.get('clock_channel_id')

    if not channel_id:
        flash('Nie ustawiono kanału clock. Skonfiguruj go w Konfiguracji.', 'danger')
        return redirect(url_for('guild_overview', guild_id=guild_id))

    now = datetime.now()
    stats = db.get_guild_stats(guild_id)
    day_name = db.DAYS_PL[now.weekday()]

    embed_obj = {
        'title': '📋 Codzienny Apel – Baza MOPS',
        'description': (
            f'**{day_name}, {now.strftime("%d.%m.%Y")}**\n\n'
            '━━━━━━━━━━━━━━━━━━━━━━━━━━\n'
            '🟢 **Clock In** — Zacznij sesję aktywności\n'
            '🔴 **Clock Out** — Zakończ sesję aktywności\n'
            '━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n'
            '> Punkty przyznawane za każdą godzinę aktywności.\n'
            '> Pamiętaj żeby się wylogować po zakończeniu!\n\n'
            f'👥 Aktywnych teraz: **{stats["active_now"]}**\n'
            f'⚠️ Ostrzeżenia (serwer): **{stats["warning_count"]}**'
        ),
        'color': 0x2ECC71,
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'footer': {'text': 'System Rang MOPS • Punkty za aktywność'},
    }
    components = [{
        'type': 1,
        'components': [
            {'type': 2, 'style': 3, 'label': '🟢 Clock In',  'custom_id': 'mops_clock_in'},
            {'type': 2, 'style': 4, 'label': '🔴 Clock Out', 'custom_id': 'mops_clock_out'},
        ],
    }]
    payload = {'embeds': [embed_obj], 'components': components}

    result, err = _dpost(f'/channels/{channel_id}/messages', payload)
    if result and result.get('id'):
        db.save_daily_embed(guild_id, int(channel_id), int(result['id']),
                            _date.today().isoformat())
        flash('✅ Embed Clock In/Out wysłany pomyślnie!', 'success')
    else:
        flash(f'Błąd wysyłania embeda: {err or "Brak odpowiedzi od Discord"}', 'danger')
    return redirect(url_for('guild_overview', guild_id=guild_id))


# ─── Users ────────────────────────────────────────────────────────────────────

@app.route('/guild/<int:guild_id>/users')
@login_required
def users_list(guild_id):
    db.ensure_guild(guild_id)
    info = _guild_info(guild_id)
    users = db.get_all_users(guild_id)
    return render_template('users.html', guild_id=guild_id,
                           guild_name=info.get('name', str(guild_id)), users=users)

@app.route('/guild/<int:guild_id>/users/<int:user_id>')
@login_required
def user_detail(guild_id, user_id):
    db.ensure_guild(guild_id)
    db.ensure_user(user_id, guild_id)
    info = _guild_info(guild_id)
    user = db.get_user(user_id, guild_id)
    auto_rank    = db.get_user_auto_rank(user_id, guild_id)
    next_rank    = db.get_user_next_rank(user_id, guild_id)
    specials     = db.get_user_special_ranks(user_id, guild_id)
    sessions     = db.get_user_sessions(user_id, guild_id, limit=20)
    txs          = db.get_user_transactions(user_id, guild_id, limit=20)
    warns        = db.get_warnings(user_id, guild_id)
    all_special_ranks = db.get_ranks(guild_id, special_only=True)
    all_ranks         = db.get_ranks(guild_id)
    rank_history = db.get_rank_history(user_id, guild_id, limit=20)
    user_faction = db.get_user_faction_membership(user_id, guild_id)
    factions     = db.get_factions(guild_id)
    user_jobs    = db.get_user_jobs(user_id, guild_id)
    all_jobs     = db.get_jobs(guild_id)
    cfg = db.get_guild(guild_id) or {}
    member_info = _dget(f'/guilds/{guild_id}/members/{user_id}')
    avatar_url = None
    if member_info and member_info.get('user', {}).get('avatar'):
        avatar_url = f'https://cdn.discordapp.com/avatars/{user_id}/{member_info["user"]["avatar"]}.png'
    return render_template('user_detail.html',
        guild_id=guild_id, guild_name=info.get('name', str(guild_id)),
        user=user, user_id=user_id, auto_rank=auto_rank, next_rank=next_rank,
        specials=specials, sessions=sessions, txs=txs, warns=warns,
        all_special_ranks=all_special_ranks, all_ranks=all_ranks, avatar_url=avatar_url,
        rank_history=rank_history, warn_limit=cfg.get('warn_limit', 3),
        user_faction=user_faction, factions=factions,
        user_jobs=user_jobs, all_jobs=all_jobs)

@app.route('/guild/<int:guild_id>/users/<int:user_id>/addpoints', methods=['POST'])
@login_required
def add_points_action(guild_id, user_id):
    pts  = float(request.form.get('points', 0))
    note = request.form.get('note', 'Dashboard')
    if request.form.get('operation') == 'subtract':
        pts = -pts
    db.ensure_user(user_id, guild_id)
    # Capture current auto-rank role before the change
    _old_rank    = db.get_user_auto_rank(user_id, guild_id)
    _old_role_id = _old_rank.get('role_id') if _old_rank else None
    db.add_points(user_id, guild_id, pts, note=note, transaction_type='manual', assigned_by=0)
    # Sync Discord role to reflect new auto-rank
    _sync_auto_rank_role(guild_id, user_id, _old_role_id)
    db.log_action(guild_id, 'points_add', user_id=user_id,
                  details={'delta': pts, 'note': note, 'by': 'dashboard'})
    flash(f'Punkty zaktualizowane ({pts:+.1f}).', 'success')
    return redirect(url_for('user_detail', guild_id=guild_id, user_id=user_id))

@app.route('/guild/<int:guild_id>/users/<int:user_id>/setpoints', methods=['POST'])
@login_required
def set_points_action(guild_id, user_id):
    pts  = float(request.form.get('points', 0))
    note = request.form.get('note', 'Dashboard – ręczne ustawienie')
    db.ensure_user(user_id, guild_id)
    # Capture current auto-rank role before the change
    _old_rank    = db.get_user_auto_rank(user_id, guild_id)
    _old_role_id = _old_rank.get('role_id') if _old_rank else None
    db.set_points(user_id, guild_id, pts, note=note, assigned_by=0)
    # Sync Discord role to reflect new auto-rank
    _sync_auto_rank_role(guild_id, user_id, _old_role_id)
    flash(f'Ustawiono {pts:.1f} pkt.', 'success')
    return redirect(url_for('user_detail', guild_id=guild_id, user_id=user_id))

@app.route('/guild/<int:guild_id>/users/<int:user_id>/ban', methods=['POST'])
@login_required
def ban_user(guild_id, user_id):
    db.update_user(user_id, guild_id, is_banned=1)
    db.log_action(guild_id, 'ban', user_id=user_id, details={'by': 'dashboard'})
    flash('Użytkownik zablokowany na liście rankingowej.', 'warning')
    return redirect(url_for('user_detail', guild_id=guild_id, user_id=user_id))

@app.route('/guild/<int:guild_id>/users/<int:user_id>/unban', methods=['POST'])
@login_required
def unban_user(guild_id, user_id):
    db.update_user(user_id, guild_id, is_banned=0)
    flash('Odblokowano.', 'success')
    return redirect(url_for('user_detail', guild_id=guild_id, user_id=user_id))

@app.route('/guild/<int:guild_id>/users/<int:user_id>/warn', methods=['POST'])
@login_required
def warn_user_action(guild_id, user_id):
    reason = request.form.get('reason', 'Dashboard')
    db.ensure_user(user_id, guild_id)
    db.add_warning(user_id, guild_id, reason=reason, warned_by=0, is_auto=False)
    count = db.get_warning_count(user_id, guild_id)
    cfg = db.get_guild(guild_id) or {}
    if count >= cfg.get('warn_limit', 3):
        db.update_user(user_id, guild_id, is_banned=1)
        flash(f'Ostrzeżono ({count}/{cfg.get("warn_limit", 3)}). Auto-ban!', 'danger')
    else:
        flash(f'Dodano ostrzeżenie ({count}/{cfg.get("warn_limit", 3)}).', 'warning')
    return redirect(url_for('user_detail', guild_id=guild_id, user_id=user_id))

@app.route('/guild/<int:guild_id>/users/<int:user_id>/clearwarn', methods=['POST'])
@login_required
def clear_warn_action(guild_id, user_id):
    warn_id = request.form.get('warn_id', '')
    n = db.clear_warnings(user_id, guild_id, int(warn_id) if warn_id.isdigit() else None)
    flash(f'Usunięto {n} ostrzeżenie(ń).', 'success')
    return redirect(url_for('user_detail', guild_id=guild_id, user_id=user_id))

@app.route('/guild/<int:guild_id>/users/<int:user_id>/reset', methods=['POST'])
@login_required
def reset_user_action(guild_id, user_id):
    db.reset_user(user_id, guild_id)
    db.log_action(guild_id, 'reset', user_id=user_id, details={'by': 'dashboard'})
    flash('Dane zresetowane.', 'warning')
    return redirect(url_for('user_detail', guild_id=guild_id, user_id=user_id))

@app.route('/guild/<int:guild_id>/users/<int:user_id>/giverank', methods=['POST'])
@login_required
def give_rank_action(guild_id, user_id):
    rank_id = int(request.form.get('rank_id', 0))
    note    = request.form.get('note', '')
    db.ensure_user(user_id, guild_id)
    rank = db.get_rank_by_id(rank_id)
    if not rank:
        flash('Ranga nie istnieje.', 'danger')
        return redirect(url_for('user_detail', guild_id=guild_id, user_id=user_id))

    if rank.get('is_special') or rank.get('is_owner_only'):
        # Give special/owner rank directly
        ok = db.give_special_rank(user_id, guild_id, rank_id, assigned_by=0, note=note)
        if ok:
            if rank.get('role_id'):
                _dput(f'/guilds/{guild_id}/members/{user_id}/roles/{rank["role_id"]}')
            flash(f'Ranga specjalna {rank["icon"]} {rank["name"]} nadana.', 'success')
        else:
            flash('Użytkownik już posiada tę rangę.', 'warning')
    else:
        # Auto-rank: raise points to the required threshold and sync Discord role
        req_pts = rank.get('required_points', 0)
        _old_rank    = db.get_user_auto_rank(user_id, guild_id)
        _old_role_id = _old_rank.get('role_id') if _old_rank else None
        user = db.get_user(user_id, guild_id)
        cur_pts = user.get('points', 0) if user else 0
        if cur_pts < req_pts:
            full_note = f'Admin nadał rangę: {rank["name"]}' + (f' – {note}' if note else '')
            db.set_points(user_id, guild_id, req_pts, note=full_note, assigned_by=0)
        _sync_auto_rank_role(guild_id, user_id, _old_role_id)
        flash(f'Ranga {rank["icon"]} {rank["name"]} ustawiona (punkty: {max(cur_pts, req_pts):.0f}).', 'success')
    return redirect(url_for('user_detail', guild_id=guild_id, user_id=user_id))

@app.route('/guild/<int:guild_id>/users/<int:user_id>/notes', methods=['POST'])
@login_required
def save_user_notes(guild_id, user_id):
    notes = request.form.get('notes', '').strip()
    db.update_user_notes(user_id, guild_id, notes)
    flash('Notatki zapisane.', 'success')
    return redirect(url_for('user_detail', guild_id=guild_id, user_id=user_id))

@app.route('/guild/<int:guild_id>/users/<int:user_id>/takerank/<int:rank_id>', methods=['POST'])
@login_required
def take_rank_action(guild_id, user_id, rank_id):
    # Sync: remove Discord role BEFORE removing from DB
    rank = db.get_rank_by_id(rank_id)
    if rank and rank.get('role_id'):
        _ddel(f'/guilds/{guild_id}/members/{user_id}/roles/{rank["role_id"]}')
    db.remove_special_rank(user_id, guild_id, rank_id)
    flash('Ranga odebrana i rola Discord usunięta.', 'warning')
    return redirect(url_for('user_detail', guild_id=guild_id, user_id=user_id))

@app.route('/guild/<int:guild_id>/users/<int:user_id>/assignfaction', methods=['POST'])
@login_required
def assign_faction_action(guild_id, user_id):
    faction_id = request.form.get('faction_id', '').strip()
    if not faction_id or not faction_id.isdigit():
        flash('Wybierz frakcję.', 'danger')
        return redirect(url_for('user_detail', guild_id=guild_id, user_id=user_id))
    f = db.get_faction_by_id(int(faction_id))
    if not f or f['guild_id'] != guild_id:
        flash('Frakcja nie istnieje.', 'danger')
        return redirect(url_for('user_detail', guild_id=guild_id, user_id=user_id))
    db.ensure_user(user_id, guild_id)
    ok = db.assign_faction_member(user_id, guild_id, int(faction_id), assigned_by=0)
    if ok:
        # Sync Discord roles: add faction marker roles + base Rekrut role
        _sync_faction_discord_roles(guild_id, user_id, f, add=True)
        flash(f'Przypisano do frakcji {f["icon"]} {f["name"]} i dodano role Discord.', 'success')
    else:
        flash('Błąd przypisania do frakcji.', 'danger')
    return redirect(url_for('user_detail', guild_id=guild_id, user_id=user_id))

@app.route('/guild/<int:guild_id>/users/<int:user_id>/removefaction', methods=['POST'])
@login_required
def remove_faction_action(guild_id, user_id):
    # Capture faction before removing from DB
    fm = db.get_user_faction_membership(user_id, guild_id)
    ok = db.remove_faction_member(user_id, guild_id)
    if ok and fm:
        # Remove faction marker roles + all faction rank Discord roles
        faction = db.get_faction_by_id(fm['faction_id'])
        if faction:
            _sync_faction_discord_roles(guild_id, user_id, faction, add=False)
        # Sync auto-rank: user is now civilian, remove old faction rank role
        _old_rank_role = None
        try:
            all_ranks = db.get_ranks(guild_id)
            for r in all_ranks:
                if r.get('faction_id') == fm['faction_id'] and r.get('role_id'):
                    _ddel(f'/guilds/{guild_id}/members/{user_id}/roles/{r["role_id"]}')
        except Exception:
            pass
    flash('Usunięto z frakcji i usunięto role Discord.' if ok else 'Użytkownik nie jest w żadnej frakcji.',
          'success' if ok else 'warning')
    return redirect(url_for('user_detail', guild_id=guild_id, user_id=user_id))

@app.route('/guild/<int:guild_id>/users/<int:user_id>/givejob', methods=['POST'])
@login_required
def give_job_action(guild_id, user_id):
    job_id_raw = request.form.get('job_id', '').strip()
    if not job_id_raw or not job_id_raw.isdigit():
        flash('Wybierz pracę.', 'danger')
        return redirect(url_for('user_detail', guild_id=guild_id, user_id=user_id))
    j = db.get_job_by_id(int(job_id_raw))
    if not j or j['guild_id'] != guild_id:
        flash('Praca nie istnieje.', 'danger')
        return redirect(url_for('user_detail', guild_id=guild_id, user_id=user_id))
    db.ensure_user(user_id, guild_id)
    ok = db.select_job(user_id, guild_id, j['id'], admin_granted=True, granted_by=0)
    flash(f'Przydzielono pracę {j["icon"]} {j["name"]}.' if ok else 'Użytkownik już ma tę pracę.', 'success' if ok else 'warning')
    return redirect(url_for('user_detail', guild_id=guild_id, user_id=user_id))

@app.route('/guild/<int:guild_id>/users/<int:user_id>/takejob', methods=['POST'])
@login_required
def take_job_action(guild_id, user_id):
    job_id_raw = request.form.get('job_id', '').strip()
    if not job_id_raw or not job_id_raw.isdigit():
        flash('Wybierz pracę.', 'danger')
        return redirect(url_for('user_detail', guild_id=guild_id, user_id=user_id))
    ok = db.deselect_job(user_id, guild_id, int(job_id_raw))
    flash('Praca odebrana.' if ok else 'Użytkownik nie ma tej pracy.', 'success' if ok else 'warning')
    return redirect(url_for('user_detail', guild_id=guild_id, user_id=user_id))


# ─── Ranks ────────────────────────────────────────────────────────────────────

@app.route('/guild/<int:guild_id>/ranks')
@login_required
def ranks_page(guild_id):
    db.ensure_guild(guild_id)
    info        = _guild_info(guild_id)
    ranks       = db.get_ranks(guild_id)
    guild_roles = _dget(f'/guilds/{guild_id}/roles') or []
    factions    = db.get_factions(guild_id)
    role_map    = {str(r['id']): r['name'] for r in guild_roles}
    fac_map     = {f['id']: f for f in factions}

    # Group by custom category → faction → type default
    grouped = {}
    for r in ranks:
        cat = (r.get('category') or '').strip()
        if cat:
            grouped.setdefault(cat, []).append(r)
        else:
            fid = r.get('faction_id')
            if fid and fid in fac_map:
                f = fac_map[fid]
                cat = f'{f["icon"]} {f["name"]}'
            elif r.get('is_owner_only'):
                cat = '👑 Jednostki'
            elif r.get('is_special'):
                cat = '🎖️ Specjalne'
            else:
                cat = '🤖 Cywile'
            grouped.setdefault(cat, []).append(r)

    return render_template('ranks.html', guild_id=guild_id,
                           guild_name=info.get('name', str(guild_id)),
                           ranks=ranks, guild_roles=guild_roles,
                           grouped_ranks=grouped, factions=factions,
                           role_map=role_map)

@app.route('/guild/<int:guild_id>/ranks/create', methods=['POST'])
@login_required
def create_rank_action(guild_id):
    name       = request.form.get('name', '').strip()
    is_special = request.form.get('is_special') == '1'
    is_owner   = request.form.get('is_owner_only') == '1'
    req_pts    = float(request.form.get('required_points', 0)) if not is_special else 0
    icon       = request.form.get('icon', '⭐').strip() or '⭐'
    color      = request.form.get('color', '#7289da').strip() or '#7289da'
    desc       = request.form.get('description', '').strip()
    category   = request.form.get('category', '').strip()
    role_id    = request.form.get('role_id', '').strip()
    role_id    = int(role_id) if role_id.isdigit() else None
    grant_raw  = request.form.getlist('grant_role_ids')
    grant_ids  = [int(r) for r in grant_raw if r.isdigit()]
    faction_id_raw = request.form.get('faction_id', '').strip()
    faction_id = int(faction_id_raw) if faction_id_raw.isdigit() else None
    if not name:
        flash('Nazwa jest wymagana.', 'danger')
        return redirect(url_for('ranks_page', guild_id=guild_id))
    if db.get_rank_by_name(guild_id, name):
        flash(f'Ranga "{name}" już istnieje.', 'danger')
        return redirect(url_for('ranks_page', guild_id=guild_id))
    db.create_rank(guild_id, name, req_pts, role_id=role_id, color=color,
                   description=desc, icon=icon, is_special=is_special or is_owner,
                   is_owner_only=is_owner, grant_role_ids=grant_ids,
                   category=category, faction_id=faction_id)
    flash(f'Ranga "{name}" utworzona.', 'success')
    return redirect(url_for('ranks_page', guild_id=guild_id))

@app.route('/guild/<int:guild_id>/ranks/<int:rank_id>/edit', methods=['POST'])
@login_required
def edit_rank_action(guild_id, rank_id):
    name     = request.form.get('name', '').strip()
    req_pts  = float(request.form.get('required_points', 0))
    icon     = request.form.get('icon', '⭐').strip() or '⭐'
    color    = request.form.get('color', '#7289da').strip()
    desc     = request.form.get('description', '').strip()
    category = request.form.get('category', '').strip()
    role_id  = request.form.get('role_id', '').strip()
    role_id  = int(role_id) if role_id.isdigit() else None
    grant_raw = request.form.getlist('grant_role_ids')
    grant_ids = [int(r) for r in grant_raw if r.isdigit()]
    faction_id_raw = request.form.get('faction_id', '').strip()
    faction_id = int(faction_id_raw) if faction_id_raw.isdigit() else None
    db.update_rank(rank_id, name=name, required_points=req_pts, icon=icon,
                   color=color, description=desc, role_id=role_id,
                   grant_role_ids=json.dumps(grant_ids), category=category,
                   faction_id=faction_id)
    flash('Ranga zaktualizowana.', 'success')
    return redirect(url_for('ranks_page', guild_id=guild_id))

@app.route('/guild/<int:guild_id>/ranks/<int:rank_id>/delete', methods=['POST'])
@login_required
def delete_rank_action(guild_id, rank_id):
    db.delete_rank(rank_id)
    flash('Ranga usunięta.', 'warning')
    return redirect(url_for('ranks_page', guild_id=guild_id))


# ─── Events (admin) ───────────────────────────────────────────────────────────

EVENT_PRESETS = [
    {'name': 'Happy Day',      'emoji': '🎉', 'color': '#faa61a', 'type': 'points', 'value': 2.0,  'desc': 'Podwójne punkty za aktywność!'},
    {'name': 'Double Mopsy',   'emoji': '🐾', 'color': '#43b581', 'type': 'mopsy',  'value': 2.0,  'desc': 'Podwójne mopsy ze wszystkich źródeł!'},
    {'name': 'Weekend Bonus',  'emoji': '⭐', 'color': '#7289da', 'type': 'points', 'value': 1.5,  'desc': '+50% punktów przez cały weekend!'},
    {'name': 'Wyprzedaż 50%',  'emoji': '🏷️', 'color': '#f04747', 'type': 'shop',   'value': 50.0, 'desc': '50% zniżki na wszystko w sklepie!'},
    {'name': 'Mega Event',     'emoji': '🚀', 'color': '#faa61a', 'type': 'points', 'value': 3.0,  'desc': 'Potrójne punkty – raz na jakiś czas!'},
    {'name': 'Ogłoszenie',     'emoji': '📢', 'color': '#99aab5', 'type': 'custom', 'value': 1.0,  'desc': 'Event ogłoszeniowy bez bonusów'},
]

@app.route('/guild/<int:guild_id>/events', methods=['GET'])
@login_required
def events_page(guild_id):
    db.ensure_guild(guild_id)
    info = _guild_info(guild_id)
    events = db.get_all_events(guild_id)
    active = db.get_active_events(guild_id)
    return render_template('events.html',
        guild_id=guild_id,
        guild_name=info.get('name', str(guild_id)),
        icon_url=_guild_icon(guild_id, info.get('icon')),
        events=events,
        active=active,
        presets=EVENT_PRESETS,
    )

@app.route('/guild/<int:guild_id>/events/create', methods=['POST'])
@login_required
def event_create(guild_id):
    d = request.get_json() or {}
    try:
        eid = db.create_event(
            guild_id=guild_id,
            name=d.get('name', 'Event'),
            description=d.get('description', ''),
            etype=d.get('type', 'custom'),
            value=float(d.get('value', 1.0)),
            emoji=d.get('emoji', '🎉'),
            color=d.get('color', '#7289da'),
            start_at=d.get('start_at', datetime.utcnow().isoformat()),
            end_at=d.get('end_at', (datetime.utcnow() + __import__('datetime').timedelta(hours=24)).isoformat()),
            created_by=_session_discord_id(),
        )
        return jsonify({'ok': True, 'id': eid})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 400

@app.route('/guild/<int:guild_id>/events/<int:event_id>/deactivate', methods=['POST'])
@login_required
def event_deactivate(guild_id, event_id):
    db.deactivate_event(event_id)
    return jsonify({'ok': True})

@app.route('/guild/<int:guild_id>/events/<int:event_id>/delete', methods=['POST'])
@login_required
def event_delete(guild_id, event_id):
    db.delete_event(event_id)
    return jsonify({'ok': True})


# ─── Rank permissions (admin) ─────────────────────────────────────────────────

@app.route('/guild/<int:guild_id>/rank-permissions', methods=['GET', 'POST'])
@login_required
def rank_permissions_page(guild_id):
    db.ensure_guild(guild_id)
    info = _guild_info(guild_id)
    ranks = db.get_ranks(guild_id)

    if request.method == 'POST':
        data = request.get_json() or {}
        for rank in ranks:
            for cmds in COMMAND_GROUPS.values():
                for cmd in cmds:
                    key = f'{rank["id"]}_{cmd}'
                    db.set_rank_permission(guild_id, rank['id'], cmd, bool(data.get(key, True)))
        return jsonify({'ok': True})

    all_perms = db.get_all_rank_permissions(guild_id)
    # Build flat lookup: perms[rank_id][cmd] = True/False
    return render_template('rank_permissions.html',
        guild_id=guild_id,
        guild_name=info.get('name', str(guild_id)),
        icon_url=_guild_icon(guild_id, info.get('icon')),
        ranks=ranks,
        command_groups=COMMAND_GROUPS,
        all_perms=all_perms,
    )


# ─── Config ───────────────────────────────────────────────────────────────────

@app.route('/guild/<int:guild_id>/config')
@login_required
def config_page(guild_id):
    cfg = db.ensure_guild(guild_id)
    info = _guild_info(guild_id)
    channels = _dget(f'/guilds/{guild_id}/channels') or []
    text_channels = [c for c in channels if c.get('type') == 0]
    guild_roles = _dget(f'/guilds/{guild_id}/roles') or []
    try:
        admin_role_ids = json.loads(cfg.get('admin_role_ids') or '[]')
    except Exception:
        admin_role_ids = []
    schedule = db.get_embed_schedule(guild_id)
    try:
        regulamin_msg_count = len(json.loads(cfg.get('regulamin_message_ids') or '[]'))
    except Exception:
        regulamin_msg_count = 0
    return render_template('config.html',
        guild_id=guild_id, guild_name=info.get('name', str(guild_id)),
        cfg=cfg, text_channels=text_channels, guild_roles=guild_roles,
        admin_role_ids=admin_role_ids, schedule=schedule,
        days_pl=db.DAYS_PL, regulamin_msg_count=regulamin_msg_count)

@app.route('/guild/<int:guild_id>/config', methods=['POST'])
@login_required
def config_save(guild_id):
    updates = {}
    for field in ('clock_channel_id', 'log_channel_id', 'command_panel_channel_id',
                  'regulamin_channel_id'):
        v = request.form.get(field, '').strip()
        updates[field] = int(v) if v.isdigit() else None
    for field, default in (('points_per_hour', 10.0), ('min_clock_minutes', 5),
                            ('auto_clockout_hours', 12), ('warn_limit', 3),
                            ('clock_cooldown_min', 0)):
        v = request.form.get(field, '').strip()
        try:
            updates[field] = type(default)(v)
        except Exception:
            pass
    for field, default in (('streak_bonus_pct', 5.0),):
        v = request.form.get(field, '').strip()
        try:
            updates[field] = float(v)
        except Exception:
            pass
    updates['dm_notifications'] = 1 if request.form.get('dm_notifications') == '1' else 0
    owner_id_raw = request.form.get('owner_id', '').strip()
    updates['owner_id'] = int(owner_id_raw) if owner_id_raw.isdigit() else None
    admin_roles = [int(r) for r in request.form.getlist('admin_role_ids') if r.isdigit()]
    updates['admin_role_ids'] = json.dumps(admin_roles)
    # Schedule
    schedule = {}
    for i in range(7):
        h = request.form.get(f'sched_hour_{i}', '0').strip()
        m = request.form.get(f'sched_min_{i}', '0').strip()
        enabled = request.form.get(f'sched_enabled_{i}') == '1'
        try:
            schedule[str(i)] = {'hour': int(h), 'minute': int(m), 'enabled': enabled}
        except Exception:
            schedule[str(i)] = {'hour': 0, 'minute': 0, 'enabled': enabled}
    updates['embed_schedule'] = json.dumps(schedule)
    updates['auto_balance_jobs'] = 1 if request.form.get('auto_balance_jobs') == '1' else 0
    if updates:
        db.update_guild(guild_id, **updates)
        # Auto-rebalance job bonuses when base pph changes and toggle is on
        if updates.get('auto_balance_jobs') and 'points_per_hour' in updates:
            jobs = db.get_jobs(guild_id)
            for job_id, bonus in _calculate_balanced_bonuses(jobs, updates['points_per_hour']).items():
                db.update_job(job_id, points_bonus_per_hour=bonus)
        flash('Konfiguracja zapisana.', 'success')
    return redirect(url_for('config_page', guild_id=guild_id))


@app.route('/guild/<int:guild_id>/publish-regulamin', methods=['POST'])
@login_required
def publish_regulamin(guild_id):
    import hashlib
    cfg = db.get_guild(guild_id) or {}
    ch_id = cfg.get('regulamin_channel_id')
    if not ch_id:
        flash('Najpierw ustaw kanał regulaminu w konfiguracji.', 'danger')
        return redirect(url_for('config_page', guild_id=guild_id))

    reg_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'REGULAMIN.md')
    try:
        with open(reg_path, encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        flash(f'Nie można odczytać REGULAMIN.md: {e}', 'danger')
        return redirect(url_for('config_page', guild_id=guild_id))

    # Delete old messages
    try:
        old_ids = json.loads(cfg.get('regulamin_message_ids') or '[]')
    except Exception:
        old_ids = []
    for msg_id in old_ids:
        _ddel(f'/channels/{ch_id}/messages/{msg_id}')

    # Send new messages
    chunks = _split_regulamin(content)
    new_ids = []
    for chunk in chunks:
        data, _ = _dpost(f'/channels/{ch_id}/messages', {'content': chunk})
        if data:
            new_ids.append(data['id'])

    file_hash = hashlib.md5(content.encode()).hexdigest()
    db.update_guild(guild_id,
                    regulamin_message_ids=json.dumps(new_ids),
                    regulamin_file_hash=file_hash)
    flash(f'Regulamin opublikowany ({len(new_ids)} wiadomości) w <#{ch_id}>.', 'success')
    return redirect(url_for('config_page', guild_id=guild_id))


@app.route('/guild/<int:guild_id>/jobs/balance', methods=['POST'])
@login_required
def balance_jobs(guild_id):
    cfg = db.get_guild(guild_id) or {}
    base_pph = float(cfg.get('points_per_hour') or 10.0)
    jobs = db.get_jobs(guild_id)
    if not jobs:
        flash('Brak prac do zbalansowania.', 'warning')
        return redirect(url_for('jobs_page', guild_id=guild_id))
    bonuses = _calculate_balanced_bonuses(jobs, base_pph)
    for job_id, bonus in bonuses.items():
        db.update_job(job_id, points_bonus_per_hour=bonus)
    flash(f'Zbalansowano bonusy pkt/h dla {len(bonuses)} prac (stawka bazowa: {base_pph} pkt/h).', 'success')
    return redirect(url_for('jobs_page', guild_id=guild_id))


# ─── Permissions ──────────────────────────────────────────────────────────────

COMMAND_LIST = {
    'Użytkownik': ['points', 'rank', 'lb', 'leaderboard', 'history', 'profile', 'clock'],
    'Admin – Punkty': ['addpoints', 'removepoints', 'setpoints'],
    'Admin – Rangi': ['giverank', 'takerank', 'createrank', 'deleterank', 'editrank', 'ranks'],
    'Admin – Ostrzeżenia': ['warn', 'warnings', 'clearwarn'],
    'Admin – Zarządzanie': ['ban', 'unban', 'forceclockout', 'resetuser', 'userinfo',
                            'serverstats', 'config', 'setchannel', 'setpoints_h',
                            'adminrole', 'removeadminrole', 'setowner',
                            'setwarnlimit', 'setmaxhours', 'apel'],
    'Panel': ['panel'],
}

@app.route('/guild/<int:guild_id>/permissions')
@login_required
def permissions_page(guild_id):
    db.ensure_guild(guild_id)
    info = _guild_info(guild_id)
    guild_roles = _dget(f'/guilds/{guild_id}/roles') or []
    current_perms = db.get_all_command_permissions(guild_id)
    return render_template('permissions.html',
        guild_id=guild_id, guild_name=info.get('name', str(guild_id)),
        guild_roles=guild_roles, command_list=COMMAND_LIST,
        current_perms=current_perms)

@app.route('/guild/<int:guild_id>/permissions', methods=['POST'])
@login_required
def permissions_save(guild_id):
    if request.args.get('reset') == '1':
        all_commands = [c for cmds in COMMAND_LIST.values() for c in cmds]
        for cmd in all_commands:
            db.set_command_permission(guild_id, cmd, [])
        flash('Uprawnienia zresetowane do domyślnych.', 'success')
        return redirect(url_for('permissions_page', guild_id=guild_id))
    all_commands = [c for cmds in COMMAND_LIST.values() for c in cmds]
    for cmd in all_commands:
        role_ids = [int(r) for r in request.form.getlist(f'perm_{cmd}') if r.isdigit()]
        db.set_command_permission(guild_id, cmd, role_ids)
    flash('Uprawnienia zapisane.', 'success')
    return redirect(url_for('permissions_page', guild_id=guild_id))


# ─── Announcements ────────────────────────────────────────────────────────────

@app.route('/guild/<int:guild_id>/announcements')
@login_required
def announcements_page(guild_id):
    db.ensure_guild(guild_id)
    info = _guild_info(guild_id)
    channels = _dget(f'/guilds/{guild_id}/channels') or []
    text_channels = [c for c in channels if c.get('type') == 0]
    guild_roles = _dget(f'/guilds/{guild_id}/roles') or []
    # Enrich announcements with channel names
    raw = db.get_announcements(guild_id, limit=30)
    ch_map = {str(c['id']): c['name'] for c in text_channels}
    for ann in raw:
        ann['channel_name'] = ch_map.get(str(ann.get('channel_id', '')), None)
    return render_template('announcements.html',
        guild_id=guild_id, guild_name=info.get('name', str(guild_id)),
        text_channels=text_channels, guild_roles=guild_roles,
        announcements=raw)

@app.route('/guild/<int:guild_id>/announcements/send', methods=['POST'])
@login_required
def send_announcement(guild_id):
    channel_id   = request.form.get('channel_id', '').strip()
    announce_type = request.form.get('announce_type', 'embed')
    title        = request.form.get('embed_title', '').strip()
    content      = request.form.get('content', '').strip()
    color_hex    = request.form.get('embed_color', '#7289da').strip() or '#7289da'
    footer_text  = request.form.get('embed_footer', '').strip()
    mention_role = request.form.get('mention_role_id', '').strip()
    scheduled_at = request.form.get('scheduled_at', '').strip()

    if not content or not channel_id or not channel_id.isdigit():
        flash('Treść i kanał są wymagane.', 'danger')
        return redirect(url_for('announcements_page', guild_id=guild_id))

    channel_id = int(channel_id)
    is_embed = announce_type == 'embed'

    # Handle mention prefix
    if mention_role in ('@everyone', '@here'):
        prefix = f'{mention_role}\n'
    elif mention_role and mention_role.isdigit():
        prefix = f'<@&{mention_role}>\n'
    else:
        prefix = ''

    # Handle scheduled announcements
    if scheduled_at:
        # Parse and normalize to ISO format
        try:
            # Input format from datetime-local: "YYYY-MM-DDTHH:MM"
            dt = datetime.fromisoformat(scheduled_at)
            scheduled_iso = dt.isoformat()
        except Exception:
            scheduled_iso = scheduled_at
        db.save_announcement(guild_id, channel_id, title, content,
                             is_embed, color_hex, 'Dashboard',
                             scheduled_at=scheduled_iso)
        flash(f'Ogłoszenie zaplanowane na {scheduled_at.replace("T", " ")}.', 'success')
        return redirect(url_for('announcements_page', guild_id=guild_id))

    # Send immediately via Discord API
    if is_embed:
        try:
            color_int = int(color_hex.lstrip('#'), 16)
        except Exception:
            color_int = 0x7289DA
        # Build embed - omit optional fields when empty (Discord rejects null values)
        embed_obj = {
            'description': content,
            'color': color_int,
            'timestamp': datetime.now(timezone.utc).isoformat(),
        }
        if title:
            embed_obj['title'] = title
        if footer_text:
            embed_obj['footer'] = {'text': footer_text}
        payload = {'embeds': [embed_obj]}
        if prefix:
            payload['content'] = prefix.rstrip()
    else:
        payload = {'content': prefix + content}

    result, err = _dpost(f'/channels/{channel_id}/messages', payload)
    if result and result.get('id'):
        msg_id = int(result['id'])
        db.save_announcement(guild_id, channel_id, title, content,
                             is_embed, color_hex, 'Dashboard', msg_id)
        flash('Ogłoszenie wysłane!', 'success')
    else:
        flash(f'Błąd wysyłania ogłoszenia: {err or "Brak odpowiedzi od Discord"}', 'danger')
    return redirect(url_for('announcements_page', guild_id=guild_id))


# ─── Factions ─────────────────────────────────────────────────────────────────

@app.route('/guild/<int:guild_id>/factions')
@login_required
def factions_page(guild_id):
    db.ensure_guild(guild_id)
    info     = _guild_info(guild_id)
    factions = db.get_factions(guild_id)
    roles    = _dget(f'/guilds/{guild_id}/roles') or []
    # Build dict faction_id → members list
    faction_members = {f['id']: db.get_faction_members(guild_id, f['id'])
                       for f in factions}
    all_users = db.get_all_users(guild_id)
    return render_template('factions.html',
        guild_id=guild_id, guild_name=info.get('name', str(guild_id)),
        factions=factions, guild_roles=roles,
        faction_members=faction_members, all_users=all_users)


@app.route('/guild/<int:guild_id>/factions/create', methods=['POST'])
@login_required
def faction_create(guild_id):
    name  = request.form.get('name', '').strip()
    icon  = request.form.get('icon', '⚔️').strip() or '⚔️'
    color = request.form.get('color', '#7289da').strip() or '#7289da'
    desc  = request.form.get('description', '').strip()
    if not name:
        flash('Nazwa frakcji jest wymagana.', 'danger')
        return redirect(url_for('factions_page', guild_id=guild_id))
    if db.get_faction_by_name(guild_id, name):
        flash(f'Frakcja "{name}" już istnieje.', 'danger')
        return redirect(url_for('factions_page', guild_id=guild_id))
    db.create_faction(guild_id, name, icon=icon, color=color, description=desc)
    flash(f'Frakcja {icon} {name} utworzona.', 'success')
    return redirect(url_for('factions_page', guild_id=guild_id))


@app.route('/guild/<int:guild_id>/factions/<int:faction_id>/edit', methods=['POST'])
@login_required
def faction_edit(guild_id, faction_id):
    import json as _json
    f = db.get_faction_by_id(faction_id)
    if not f or f['guild_id'] != guild_id:
        flash('Nie znaleziono frakcji.', 'danger')
        return redirect(url_for('factions_page', guild_id=guild_id))
    name  = request.form.get('name', '').strip() or f['name']
    icon  = request.form.get('icon', '').strip()  or f['icon']
    color = request.form.get('color', '').strip() or f['color']
    desc  = request.form.get('description', '').strip()
    # Role IDs come as list from multi-select
    role_ids = [int(r) for r in request.form.getlist('role_ids') if r.isdigit()]
    db.update_faction(faction_id, name=name, icon=icon, color=color,
                      description=desc, role_ids=role_ids)
    flash(f'Frakcja {icon} {name} zaktualizowana.', 'success')
    return redirect(url_for('factions_page', guild_id=guild_id))


@app.route('/guild/<int:guild_id>/factions/<int:faction_id>/delete', methods=['POST'])
@login_required
def faction_delete(guild_id, faction_id):
    f = db.get_faction_by_id(faction_id)
    if not f or f['guild_id'] != guild_id:
        flash('Nie znaleziono frakcji.', 'danger')
        return redirect(url_for('factions_page', guild_id=guild_id))
    db.delete_faction(faction_id)
    flash(f'Frakcja {f["icon"]} {f["name"]} usunięta.', 'success')
    return redirect(url_for('factions_page', guild_id=guild_id))


# ─── Jobs ─────────────────────────────────────────────────────────────────────

@app.route('/guild/<int:guild_id>/jobs')
@login_required
def jobs_page(guild_id):
    db.ensure_guild(guild_id)
    info     = _guild_info(guild_id)
    jobs     = db.get_jobs(guild_id)
    roles    = _dget(f'/guilds/{guild_id}/roles') or []
    job_members = {j['id']: db.get_job_members(guild_id, j['id']) for j in jobs}
    return render_template('jobs.html',
        guild_id=guild_id, guild_name=info.get('name', str(guild_id)),
        jobs=jobs, guild_roles=roles, job_members=job_members)


@app.route('/guild/<int:guild_id>/jobs/create', methods=['POST'])
@login_required
def job_create(guild_id):
    name     = request.form.get('name', '').strip()
    icon     = request.form.get('icon', '💼').strip() or '💼'
    color    = request.form.get('color', '#7289da').strip() or '#7289da'
    desc     = request.form.get('description', '').strip()
    req_pts_raw = request.form.get('required_points', '0').strip()
    role_id_raw = request.form.get('role_id', '').strip()
    try:
        req_pts = float(req_pts_raw)
    except ValueError:
        req_pts = 0.0
    role_id = int(role_id_raw) if role_id_raw.isdigit() else None
    try:
        bonus_pph = float(request.form.get('points_bonus_per_hour', '0').strip())
    except ValueError:
        bonus_pph = 0.0
    if not name:
        flash('Nazwa pracy jest wymagana.', 'danger')
        return redirect(url_for('jobs_page', guild_id=guild_id))
    if db.get_job_by_name(guild_id, name):
        flash(f'Praca "{name}" już istnieje.', 'danger')
        return redirect(url_for('jobs_page', guild_id=guild_id))
    db.create_job(guild_id, name, req_pts, icon=icon, color=color,
                  description=desc, role_id=role_id, points_bonus_per_hour=bonus_pph)
    flash(f'Praca {icon} {name} utworzona.', 'success')
    return redirect(url_for('jobs_page', guild_id=guild_id))


@app.route('/guild/<int:guild_id>/jobs/<int:job_id>/edit', methods=['POST'])
@login_required
def job_edit(guild_id, job_id):
    j = db.get_job_by_id(job_id)
    if not j or j['guild_id'] != guild_id:
        flash('Nie znaleziono pracy.', 'danger')
        return redirect(url_for('jobs_page', guild_id=guild_id))
    name     = request.form.get('name', '').strip() or j['name']
    icon     = request.form.get('icon', '').strip()  or j['icon']
    color    = request.form.get('color', '').strip() or j['color']
    desc     = request.form.get('description', '').strip()
    req_pts_raw = request.form.get('required_points', '').strip()
    role_id_raw = request.form.get('role_id', '').strip()
    try:
        req_pts = float(req_pts_raw)
    except ValueError:
        req_pts = j['required_points']
    try:
        bonus_pph = float(request.form.get('points_bonus_per_hour', '0').strip())
    except ValueError:
        bonus_pph = j.get('points_bonus_per_hour', 0.0)
    role_id = int(role_id_raw) if role_id_raw.isdigit() else None
    db.update_job(job_id, name=name, icon=icon, color=color,
                  description=desc, required_points=req_pts,
                  role_id=role_id, points_bonus_per_hour=bonus_pph)
    flash(f'Praca {icon} {name} zaktualizowana.', 'success')
    return redirect(url_for('jobs_page', guild_id=guild_id))


@app.route('/guild/<int:guild_id>/jobs/<int:job_id>/delete', methods=['POST'])
@login_required
def job_delete(guild_id, job_id):
    j = db.get_job_by_id(job_id)
    if not j or j['guild_id'] != guild_id:
        flash('Nie znaleziono pracy.', 'danger')
        return redirect(url_for('jobs_page', guild_id=guild_id))
    db.delete_job(job_id)
    flash(f'Praca {j["icon"]} {j["name"]} usunięta.', 'success')
    return redirect(url_for('jobs_page', guild_id=guild_id))


# ─── MOPS Auto-Setup – data ───────────────────────────────────────────────────

# ─── Discord role-level permission presets ────────────────────────────────────
# These are set on the ROLE itself (not channel overwrites) when the role is created.
# Reference: https://discord.com/developers/docs/topics/permissions
_RP_ADMIN    = 8                      # Administrator (bypasses ALL channel overwrites)
_RP_KICK     = 2                      # Kick Members
_RP_BAN      = 4                      # Ban Members
_RP_MANAGE_G = 32                     # Manage Server
_RP_MANAGE_C = 16                     # Manage Channels
_RP_MANAGE_R = 268435456              # Manage Roles
_RP_MANAGE_M = 8192                   # Manage Messages (delete/pin others' messages)
_RP_MUTE     = 4194304                # Mute Members (voice)
_RP_DEAFEN   = 8388608                # Deafen Members (voice)
_RP_MOVE     = 16777216               # Move Members (voice channels)
_RP_PRIORITY = 256                    # Priority Speaker (voice)

MOPS_ROLES = [
    # ── Władza ──────────────────────────────────────────────────────────────────
    # 'perms' = Discord role-level permission bits (int, will be str in API call)
    {'name': 'Król',            'color': 0xFFD700, 'hoist': True,
     'perms': _RP_ADMIN},
    {'name': 'Książę',          'color': 0xFFA500, 'hoist': True,
     'perms': _RP_ADMIN},
    {'name': 'Generał',         'color': 0xB20000, 'hoist': True,
     'perms': _RP_KICK|_RP_BAN|_RP_MANAGE_G|_RP_MANAGE_C|_RP_MANAGE_R
              |_RP_MANAGE_M|_RP_MUTE|_RP_DEAFEN|_RP_MOVE},
    # ── Alpha-1 Gwardia Królewska ────────────────────────────────────────────────
    {'name': 'Military Police', 'color': 0xFF0000, 'hoist': True,
     'perms': _RP_KICK|_RP_BAN|_RP_MANAGE_M|_RP_MUTE|_RP_DEAFEN|_RP_MOVE},
    {'name': 'Alpha-1',         'color': 0xCC0000, 'hoist': True,
     'perms': _RP_MANAGE_M|_RP_MUTE|_RP_MOVE},
    # ── Nu-7 Jednostka wojskowa ──────────────────────────────────────────────────
    {'name': 'Generał Nu-7',    'color': 0x003399, 'hoist': True,
     'perms': _RP_KICK|_RP_BAN|_RP_MANAGE_M|_RP_MUTE|_RP_DEAFEN|_RP_MOVE},
    {'name': 'Nu-7',            'color': 0x0055FF, 'hoist': True,
     'perms': _RP_MANAGE_M|_RP_MUTE|_RP_MOVE},
    # ── Wspólne rangi wojskowe (obie frakcje) ────────────────────────────────────
    {'name': 'Kapitan',         'color': 0x8B0000, 'hoist': True,
     'perms': _RP_MUTE|_RP_DEAFEN|_RP_MOVE|_RP_PRIORITY},
    {'name': 'Sierżant',        'color': 0x7B7B00, 'hoist': False,
     'perms': _RP_MOVE|_RP_PRIORITY},
    {'name': 'Squad Leader',    'color': 0x556B2F, 'hoist': False,
     'perms': _RP_PRIORITY},
    {'name': 'Porucznik',       'color': 0x708090, 'hoist': False, 'perms': 0},
    {'name': 'Szeregowy',       'color': 0x4682B4, 'hoist': False, 'perms': 0},
    {'name': 'Rekrut',          'color': 0x2F4F4F, 'hoist': False, 'perms': 0},
    # ── Epsilon-11 Policja ───────────────────────────────────────────────────────
    {'name': 'Generał Epsilon-11', 'color': 0x4169E1, 'hoist': True,
     'perms': _RP_KICK|_RP_BAN|_RP_MANAGE_M|_RP_MUTE|_RP_MOVE},
    {'name': 'Epsilon-11',         'color': 0x6495ED, 'hoist': True,
     'perms': _RP_MANAGE_M|_RP_MUTE|_RP_MOVE},
    # ── Prace cywilne ────────────────────────────────────────────────────────────
    {'name': 'Kowal',           'color': 0x888888, 'hoist': False, 'perms': 0},
    {'name': 'Farmer',          'color': 0x55AA55, 'hoist': False, 'perms': 0},
    {'name': 'Cywil',           'color': 0x99AAB5, 'hoist': False, 'perms': 0},
]

# (category_name, [(channel_name, channel_type), ...])  type: 0=text, 2=voice, 4=category
MOPS_CHANNELS = [
    ('📢-informacje', [
        ('ogłoszenia', 0), ('aktualności', 0), ('regulamin', 0), ('witaj', 0),
    ]),
    ('💬-ogólne', [
        ('ogólny', 0), ('cywile', 0), ('market', 0),
        ('off-topic', 0), ('komendy-bota', 0),
    ]),
    ('📊-bot-mops', [
        ('apel', 0), ('panel', 0), ('prace', 0),
    ]),
    ('⚔️-wojsko', [
        ('wojsko-ogólne', 0), ('rozkazy', 0), ('raporty', 0),
        ('alpha-1-czat', 0), ('nu-7-czat', 0), ('epsilon-11-czat', 0), ('planowanie', 0),
    ]),
    ('🔊-radio', [
        ('Radio Ogólne', 2), ('Radio Alpha-1', 2),
        ('Radio Nu-7', 2), ('Radio Epsilon-11', 2), ('Gabinet Króla', 2),
    ]),
    # Kategoria administracji – niewidoczna dla zwykłych użytkowników
    ('🔒-administracja', [
        ('admin-panel', 0),   # prywatny kanał komend adminowych bota
        ('logi', 0),          # logi bota (clock, rangi, ostrzeżenia)
        ('ostrzeżenia', 0),   # historia warnów i moderacji
    ]),
]

MOPS_FACTIONS = [
    {'name': 'Alpha-1',    'icon': '🔴', 'color': '#CC0000',
     'description': 'Gwardia Królewska – osobista ochrona Króla i Księcia'},
    {'name': 'Nu-7',       'icon': '🔵', 'color': '#0055FF',
     'description': 'Podstawowa jednostka wojskowa'},
    {'name': 'Epsilon-11', 'icon': '🟦', 'color': '#4169E1',
     'description': 'Policja Bazy MOPS – porządek publiczny i ochrona cywilów'},
]

MOPS_SPECIAL_RANKS = [
    {'name': 'Król',    'icon': '👑',  'color': '#FFD700',
     'description': 'Władca Bazy MOPS'},
    {'name': 'Książę',  'icon': '👑',  'color': '#FFA500',
     'description': 'Następca tronu'},
    {'name': 'Generał', 'icon': '🎖️', 'color': '#B20000',
     'description': 'Naczelny dowódca wszystkich wojsk Bazy MOPS – nadawany przez Króla'},
]

MOPS_FACTION_RANKS = [
    # ── Alpha-1 Gwardia Królewska (dół → góra) ─────────────────────────────────
    # 'role' = Discord role name; 'name' = DB rank display name
    {'name': 'Rekrut Alpha-1',       'faction': 'Alpha-1', 'role': 'Rekrut',
     'icon': '🔴', 'pts': 10,  'color': '#2F4F4F', 'special': False, 'owner_only': False,
     'description': 'Nowy rekrut Gwardii Królewskiej'},
    {'name': 'Szeregowy Alpha-1',    'faction': 'Alpha-1', 'role': 'Szeregowy',
     'icon': '🔴', 'pts': 35,  'color': '#4682B4', 'special': False, 'owner_only': False,
     'description': 'Żołnierz Gwardii Królewskiej'},
    {'name': 'Porucznik Alpha-1',    'faction': 'Alpha-1', 'role': 'Porucznik',
     'icon': '🔴', 'pts': 75,  'color': '#708090', 'special': False, 'owner_only': False,
     'description': 'Oficer Gwardii Królewskiej'},
    {'name': 'Squad Leader Alpha-1', 'faction': 'Alpha-1', 'role': 'Squad Leader',
     'icon': '🔴', 'pts': 130, 'color': '#556B2F', 'special': False, 'owner_only': False,
     'description': 'Dowódca drużyny Gwardii Królewskiej'},
    {'name': 'Sierżant Alpha-1',     'faction': 'Alpha-1', 'role': 'Sierżant',
     'icon': '🔴', 'pts': 200, 'color': '#7B7B00', 'special': False, 'owner_only': False,
     'description': 'Starszy sierżant Gwardii Królewskiej'},
    {'name': 'Kapitan Alpha-1',      'faction': 'Alpha-1', 'role': 'Kapitan',
     'icon': '🔴', 'pts': 0,   'color': '#8B0000', 'special': True,  'owner_only': True,
     'description': 'Kapitan Gwardii Królewskiej – nadawany przez admina'},
    {'name': 'Military Police',      'faction': 'Alpha-1', 'role': 'Military Police',
     'icon': '🎖️', 'pts': 0,  'color': '#FF0000', 'special': True,  'owner_only': True,
     'description': 'Generał Alpha-1 – personalny bodyguard Króla, oficer wszystkich wojsk'},

    # ── Nu-7 Jednostka wojskowa (dół → góra) ───────────────────────────────────
    {'name': 'Rekrut Nu-7',          'faction': 'Nu-7',    'role': 'Rekrut',
     'icon': '🔵', 'pts': 10,  'color': '#2F4F4F', 'special': False, 'owner_only': False,
     'description': 'Nowy rekrut Nu-7'},
    {'name': 'Szeregowy Nu-7',       'faction': 'Nu-7',    'role': 'Szeregowy',
     'icon': '🔵', 'pts': 35,  'color': '#4682B4', 'special': False, 'owner_only': False,
     'description': 'Żołnierz Nu-7'},
    {'name': 'Porucznik Nu-7',       'faction': 'Nu-7',    'role': 'Porucznik',
     'icon': '🔵', 'pts': 75,  'color': '#708090', 'special': False, 'owner_only': False,
     'description': 'Oficer Nu-7'},
    {'name': 'Squad Leader Nu-7',    'faction': 'Nu-7',    'role': 'Squad Leader',
     'icon': '🔵', 'pts': 130, 'color': '#556B2F', 'special': False, 'owner_only': False,
     'description': 'Dowódca drużyny Nu-7'},
    {'name': 'Sierżant Nu-7',        'faction': 'Nu-7',    'role': 'Sierżant',
     'icon': '🔵', 'pts': 200, 'color': '#7B7B00', 'special': False, 'owner_only': False,
     'description': 'Starszy sierżant Nu-7'},
    {'name': 'Kapitan Nu-7',         'faction': 'Nu-7',    'role': 'Kapitan',
     'icon': '🔵', 'pts': 0,   'color': '#8B0000', 'special': True,  'owner_only': True,
     'description': 'Kapitan Nu-7 – nadawany przez admina'},
    {'name': 'Generał Nu-7',         'faction': 'Nu-7',    'role': 'Generał Nu-7',
     'icon': '🎖️', 'pts': 0,  'color': '#003399', 'special': True,  'owner_only': True,
     'description': 'Generał Nu-7 – dowódca jednostki, nadawany przez admina'},

    # ── Epsilon-11 Policja (dół → góra) ────────────────────────────────────────
    {'name': 'Rekrut E-11',          'faction': 'Epsilon-11', 'role': 'Rekrut',
     'icon': '🟦', 'pts': 10,  'color': '#2F4F4F', 'special': False, 'owner_only': False,
     'description': 'Nowy funkcjonariusz Epsilon-11'},
    {'name': 'Szeregowy E-11',       'faction': 'Epsilon-11', 'role': 'Szeregowy',
     'icon': '🟦', 'pts': 35,  'color': '#4682B4', 'special': False, 'owner_only': False,
     'description': 'Funkcjonariusz Epsilon-11'},
    {'name': 'Porucznik E-11',       'faction': 'Epsilon-11', 'role': 'Porucznik',
     'icon': '🟦', 'pts': 75,  'color': '#708090', 'special': False, 'owner_only': False,
     'description': 'Oficer Epsilon-11'},
    {'name': 'Squad Leader E-11',    'faction': 'Epsilon-11', 'role': 'Squad Leader',
     'icon': '🟦', 'pts': 130, 'color': '#556B2F', 'special': False, 'owner_only': False,
     'description': 'Dowódca drużyny Epsilon-11'},
    {'name': 'Sierżant E-11',        'faction': 'Epsilon-11', 'role': 'Sierżant',
     'icon': '🟦', 'pts': 200, 'color': '#7B7B00', 'special': False, 'owner_only': False,
     'description': 'Starszy sierżant Epsilon-11'},
    {'name': 'Kapitan E-11',         'faction': 'Epsilon-11', 'role': 'Kapitan',
     'icon': '🟦', 'pts': 0,   'color': '#8B0000', 'special': True,  'owner_only': True,
     'description': 'Kapitan Epsilon-11 – nadawany przez admina'},
    {'name': 'Generał Epsilon-11',   'faction': 'Epsilon-11', 'role': 'Generał Epsilon-11',
     'icon': '🎖️', 'pts': 0,  'color': '#4169E1', 'special': True,  'owner_only': True,
     'description': 'Komendant Epsilon-11 – dowódca policji, nadzoruje cywilów'},
]

MOPS_JOBS = [
    {'name': 'Farmer', 'icon': '🌾', 'pts': 5,  'color': '#55AA55',
     'description': 'Uprawiasz ziemię i karmisz Bazę MOPS'},
    {'name': 'Kowal',  'icon': '⚒️', 'pts': 10, 'color': '#888888',
     'description': 'Kujęsz żelazo dla wojska i cywilów'},
    {'name': 'Kupiec', 'icon': '🛒', 'pts': 25, 'color': '#AA8855',
     'description': 'Handlujesz na miejskim rynku'},
    {'name': 'Rajca',  'icon': '🏛️', 'pts': 50, 'color': '#AAAAAA',
     'description': 'Zasiadasz w radzie miejskiej Bazy MOPS'},
]

# ─── Channel permission constants ─────────────────────────────────────────────
# Discord permission bit flags (as Python ints, passed as strings to API)
_PV   = 1024              # VIEW_CHANNEL
_PS   = 2048              # SEND_MESSAGES
_PM   = 8192              # MANAGE_MESSAGES (delete/pin others' messages)
_PC   = 1048576           # CONNECT (voice)
_PVS  = _PV | _PS         # view + send (text)
_PVC  = _PV | _PC         # view + connect (voice)
_PVMS = _PV | _PS | _PM   # view + send + manage (admin text – for bot channels)

# Per-channel permission rules: {ch_name: [(role_name_or_@everyone, allow, deny), ...]}
# @everyone uses guild_id as the role ID (Discord convention)
MOPS_PERMS = {
    # ── 📢 INFORMACJE ──────────────────────────────────────────────────────────
    'ogłoszenia': [                       # read-only; commanders can send + manage
        ('@everyone',       _PV,    _PS | _PM),
        ('Król',            _PVMS,  0),
        ('Książę',          _PVMS,  0),
        ('Generał',         _PVMS,  0),
        ('Military Police', _PVMS,  0),
    ],
    'aktualności': [                      # read-only; commanders can send + manage
        ('@everyone',       _PV,    _PS | _PM),
        ('Król',            _PVMS,  0),
        ('Książę',          _PVMS,  0),
        ('Generał',         _PVMS,  0),
        ('Military Police', _PVMS,  0),
    ],
    'regulamin': [('@everyone', _PV, _PS | _PM)],    # read-only, no manage
    'witaj':     [('@everyone', _PV, _PS | _PM)],    # read-only, no manage

    # ── 💬 OGÓLNE ──────────────────────────────────────────────────────────────
    'ogólny':       [('@everyone', _PVS, 0)],  # main open chat
    'cywile':       [('@everyone', _PVS, 0)],  # civilian / casual chat
    'market':       [('@everyone', _PVS, 0)],  # trading & economy chat
    'off-topic':    [('@everyone', _PVS, 0)],  # off-topic banter
    'komendy-bota': [('@everyone', _PVS, 0)],  # bot commands

    # ── 📊 BOT MOPS ────────────────────────────────────────────────────────────
    # Bot channels: @everyone can VIEW but NOT send or manage messages.
    # Admin roles get MANAGE_MESSAGES so they can pin/delete if needed.
    'apel':  [
        ('@everyone',       _PV,   _PS | _PM),  # deny send + manage (protect embed!)
        ('Król',            _PVMS, 0),
        ('Książę',          _PVMS, 0),
        ('Generał',         _PVMS, 0),
        ('Military Police', _PVMS, 0),
    ],
    'panel': [
        ('@everyone',       _PV,   _PS | _PM),
        ('Król',            _PVMS, 0),
        ('Książę',          _PVMS, 0),
        ('Generał',         _PVMS, 0),
        ('Military Police', _PVMS, 0),
    ],
    'prace': [
        ('@everyone',       _PV,   _PS | _PM),
        ('Król',            _PVMS, 0),
        ('Książę',          _PVMS, 0),
        ('Generał',         _PVMS, 0),
        ('Military Police', _PVMS, 0),
    ],
    'logi':  [                             # admin-only; inherits from category
        ('@everyone',          0,     _PV),
        ('Król',               _PVMS, 0),
        ('Książę',             _PVMS, 0),
        ('Generał',            _PVMS, 0),
        ('Military Police',    _PVMS, 0),
        ('Generał Nu-7',       _PVMS, 0),
        ('Alpha-1',            _PVMS, 0),
        ('Generał Epsilon-11', _PVMS, 0),
    ],

    # ── 🔒 ADMINISTRACJA ───────────────────────────────────────────────────────
    'admin-panel': [                       # admin bot commands (addpoints, giverank…)
        ('@everyone',          0,     _PV),
        ('Król',               _PVMS, 0),
        ('Książę',             _PVMS, 0),
        ('Generał',            _PVMS, 0),
        ('Military Police',    _PVMS, 0),
        ('Generał Nu-7',       _PVMS, 0),
        ('Alpha-1',            _PVMS, 0),
        ('Generał Epsilon-11', _PVMS, 0),
    ],
    'ostrzeżenia': [                       # moderation history log
        ('@everyone',          0,     _PV),
        ('Król',               _PVMS, 0),
        ('Książę',             _PVMS, 0),
        ('Generał',            _PVMS, 0),
        ('Military Police',    _PVMS, 0),
        ('Generał Nu-7',       _PVMS, 0),
        ('Alpha-1',            _PVMS, 0),
        ('Generał Epsilon-11', _PVMS, 0),
    ],

    # ── ⚔️ WOJSKO ──────────────────────────────────────────────────────────────
    'wojsko-ogólne': [                     # all military (Rekrut+), hidden from civilians
        ('@everyone',          0,     _PV),
        ('Król',               _PVS,  0),
        ('Książę',             _PVS,  0),
        ('Generał',            _PVS,  0),
        ('Military Police',    _PVS,  0),
        ('Generał Nu-7',       _PVS,  0),
        ('Alpha-1',            _PVS,  0),
        ('Nu-7',               _PVS,  0),
        ('Generał Epsilon-11', _PVS,  0),
        ('Epsilon-11',         _PVS,  0),
        ('Kapitan',            _PVS,  0),
        ('Sierżant',           _PVS,  0),
        ('Squad Leader',       _PVS,  0),
        ('Porucznik',          _PVS,  0),
        ('Szeregowy',          _PVS,  0),
        ('Rekrut',             _PVS,  0),
    ],
    'rozkazy': [                           # orders: officers write, enlisted read-only
        ('@everyone',          0,     _PV),
        ('Król',               _PVS,  0),
        ('Książę',             _PVS,  0),
        ('Generał',            _PVS,  0),
        ('Military Police',    _PVS,  0),
        ('Generał Nu-7',       _PVS,  0),
        ('Alpha-1',            _PVS,  0),
        ('Nu-7',               _PVS,  0),
        ('Generał Epsilon-11', _PVS,  0),
        ('Epsilon-11',         _PVS,  0),
        ('Kapitan',            _PVS,  0),
        ('Sierżant',           _PVS,  0),
        ('Squad Leader',       _PVS,  0),
        ('Porucznik',          _PV,   0),  # read-only from Porucznik down
        ('Szeregowy',          _PV,   0),
        ('Rekrut',             _PV,   0),
    ],
    'raporty': [                           # reports: all military can write
        ('@everyone',          0,     _PV),
        ('Król',               _PVS,  0),
        ('Książę',             _PVS,  0),
        ('Generał',            _PVS,  0),
        ('Military Police',    _PVS,  0),
        ('Generał Nu-7',       _PVS,  0),
        ('Alpha-1',            _PVS,  0),
        ('Nu-7',               _PVS,  0),
        ('Generał Epsilon-11', _PVS,  0),
        ('Epsilon-11',         _PVS,  0),
        ('Kapitan',            _PVS,  0),
        ('Sierżant',           _PVS,  0),
        ('Squad Leader',       _PVS,  0),
        ('Porucznik',          _PVS,  0),
        ('Szeregowy',          _PVS,  0),
        ('Rekrut',             _PVS,  0),
    ],
    'alpha-1-czat': [                      # Alpha-1 faction + commanders only
        ('@everyone',       0,     _PV),
        ('Król',            _PVS,  0),
        ('Książę',          _PVS,  0),
        ('Generał',         _PVS,  0),
        ('Military Police', _PVS,  0),
        ('Alpha-1',         _PVS,  0),
        ('Kapitan',         _PVS,  0),
        ('Sierżant',        _PVS,  0),
        ('Squad Leader',    _PVS,  0),
        ('Porucznik',       _PVS,  0),
        ('Szeregowy',       _PVS,  0),
        ('Rekrut',          _PVS,  0),
    ],
    'nu-7-czat': [                         # Nu-7 faction + commanders only
        ('@everyone',       0,     _PV),
        ('Król',            _PVS,  0),
        ('Książę',          _PVS,  0),
        ('Generał',         _PVS,  0),
        ('Military Police', _PVS,  0),
        ('Generał Nu-7',    _PVS,  0),
        ('Nu-7',            _PVS,  0),
        ('Kapitan',         _PVS,  0),
        ('Sierżant',        _PVS,  0),
        ('Squad Leader',    _PVS,  0),
        ('Porucznik',       _PVS,  0),
        ('Szeregowy',       _PVS,  0),
        ('Rekrut',          _PVS,  0),
    ],
    'epsilon-11-czat': [                   # Epsilon-11 faction + commanders only
        ('@everyone',          0,     _PV),
        ('Król',               _PVS,  0),
        ('Książę',             _PVS,  0),
        ('Generał',            _PVS,  0),
        ('Military Police',    _PVS,  0),
        ('Generał Epsilon-11', _PVS,  0),
        ('Epsilon-11',         _PVS,  0),
        ('Kapitan',            _PVS,  0),
        ('Sierżant',           _PVS,  0),
        ('Squad Leader',       _PVS,  0),
        ('Porucznik',          _PVS,  0),
        ('Szeregowy',          _PVS,  0),
        ('Rekrut',             _PVS,  0),
    ],
    'planowanie': [                        # officers (Porucznik+) and commanders
        ('@everyone',          0,     _PV),
        ('Król',               _PVS,  0),
        ('Książę',             _PVS,  0),
        ('Generał',            _PVS,  0),
        ('Military Police',    _PVS,  0),
        ('Generał Nu-7',       _PVS,  0),
        ('Alpha-1',            _PVS,  0),
        ('Nu-7',               _PVS,  0),
        ('Generał Epsilon-11', _PVS,  0),
        ('Epsilon-11',         _PVS,  0),
        ('Kapitan',            _PVS,  0),
        ('Sierżant',           _PVS,  0),
        ('Squad Leader',       _PVS,  0),
        ('Porucznik',          _PVS,  0),
    ],

    # ── 🔊 RADIO (voice) ───────────────────────────────────────────────────────
    'Radio Ogólne': [('@everyone', _PVC, 0)],   # everyone can join
    'Radio Alpha-1': [                      # Alpha-1 + commanders
        ('@everyone',       0,     _PVC),
        ('Król',            _PVC,  0),
        ('Książę',          _PVC,  0),
        ('Generał',         _PVC,  0),
        ('Military Police', _PVC,  0),
        ('Alpha-1',         _PVC,  0),
        ('Kapitan',         _PVC,  0),
        ('Sierżant',        _PVC,  0),
        ('Squad Leader',    _PVC,  0),
        ('Porucznik',       _PVC,  0),
        ('Szeregowy',       _PVC,  0),
        ('Rekrut',          _PVC,  0),
    ],
    'Radio Nu-7': [                         # Nu-7 + commanders
        ('@everyone',    0,     _PVC),
        ('Król',         _PVC,  0),
        ('Książę',       _PVC,  0),
        ('Generał',      _PVC,  0),
        ('Military Police', _PVC, 0),
        ('Generał Nu-7', _PVC,  0),
        ('Nu-7',         _PVC,  0),
        ('Kapitan',      _PVC,  0),
        ('Sierżant',     _PVC,  0),
        ('Squad Leader', _PVC,  0),
        ('Porucznik',    _PVC,  0),
        ('Szeregowy',    _PVC,  0),
        ('Rekrut',       _PVC,  0),
    ],
    'Radio Epsilon-11': [                   # Epsilon-11 + commanders
        ('@everyone',          0,     _PVC),
        ('Król',               _PVC,  0),
        ('Książę',             _PVC,  0),
        ('Generał',            _PVC,  0),
        ('Military Police',    _PVC,  0),
        ('Generał Epsilon-11', _PVC,  0),
        ('Epsilon-11',         _PVC,  0),
        ('Kapitan',            _PVC,  0),
        ('Sierżant',           _PVC,  0),
        ('Squad Leader',       _PVC,  0),
        ('Porucznik',          _PVC,  0),
        ('Szeregowy',          _PVC,  0),
        ('Rekrut',             _PVC,  0),
    ],
    'Gabinet Króla': [                      # royal council only
        ('@everyone',       0,     _PVC),
        ('Król',            _PVC,  0),
        ('Książę',          _PVC,  0),
        ('Generał',         _PVC,  0),
        ('Military Police', _PVC,  0),
    ],
}

# Per-category permission defaults (applied on creation; channels may override)
MOPS_CAT_PERMS = {
    '📢-informacje':    [],                           # everyone sees, read-only per channel
    '💬-ogólne':        [],                           # everyone sees
    '📊-bot-mops':      [],                           # everyone sees (embeds managed by bot)
    '⚔️-wojsko':        [('@everyone', 0, _PV)],      # military only by default
    '🔊-radio':         [('@everyone', 0, _PVC)],     # per-channel controlled
    '🔒-administracja': [                             # fully hidden from non-admins
        ('@everyone',          0,     _PV),
        ('Król',               _PVMS, 0),
        ('Książę',             _PVMS, 0),
        ('Generał',            _PVMS, 0),
        ('Military Police',    _PVMS, 0),
        ('Generał Nu-7',       _PVMS, 0),
        ('Alpha-1',            _PVMS, 0),
        ('Generał Epsilon-11', _PVMS, 0),
    ],
}


def _build_overwrites(role_map: dict, guild_id: int, rules: list) -> list:
    """Build Discord permission_overwrites list from (role_name, allow, deny) rules."""
    out = []
    for role_name, allow, deny in rules:
        if role_name == '@everyone':
            rid = str(guild_id)
        else:
            rid = str(role_map.get(role_name, 0))
            if rid == '0':
                continue
        if allow or deny:
            out.append({'id': rid, 'type': 0,
                        'allow': str(allow), 'deny': str(deny)})
    return out


# ─── MOPS Auto-Setup – routes ─────────────────────────────────────────────────

@app.route('/guild/<int:guild_id>/setup-mops')
@login_required
def setup_mops_page(guild_id):
    db.ensure_guild(guild_id)
    info              = _guild_info(guild_id)
    existing_roles    = _dget(f'/guilds/{guild_id}/roles') or []
    existing_channels = _dget(f'/guilds/{guild_id}/channels') or []
    existing_factions = db.get_factions(guild_id)
    existing_jobs     = db.get_jobs(guild_id)
    existing_role_names = {r['name'] for r in existing_roles}
    existing_ch_names   = {c['name'] for c in existing_channels}
    existing_fac_names  = {f['name'] for f in existing_factions}
    existing_job_names  = {j['name'] for j in existing_jobs}
    return render_template('setup_mops.html',
        guild_id=guild_id, guild_name=info.get('name', str(guild_id)),
        mops_roles=MOPS_ROLES, mops_channels=MOPS_CHANNELS,
        mops_factions=MOPS_FACTIONS, mops_special_ranks=MOPS_SPECIAL_RANKS,
        mops_faction_ranks=MOPS_FACTION_RANKS, mops_jobs=MOPS_JOBS,
        existing_role_names=existing_role_names,
        existing_ch_names=existing_ch_names,
        existing_fac_names=existing_fac_names,
        existing_job_names=existing_job_names)


@app.route('/guild/<int:guild_id>/setup-mops', methods=['POST'])
@login_required
def setup_mops_run(guild_id):
    db.ensure_guild(guild_id)
    results  = []
    role_map = {}   # {role_name: discord_role_id}
    ch_map   = {}   # {channel_name: channel_id}

    # ── 1. Discord roles ──────────────────────────────────────────────────────
    existing_roles    = _dget(f'/guilds/{guild_id}/roles') or []
    existing_role_map = {r['name']: int(r['id']) for r in existing_roles}

    for role_def in MOPS_ROLES:
        rname = role_def['name']
        role_payload = {
            'color': role_def['color'],
            'hoist': role_def['hoist'],
            'mentionable': True,
            'permissions': str(role_def.get('perms', 0)),
        }
        if rname in existing_role_map:
            # Role already exists → PATCH to update color, permissions, hoist
            rid = existing_role_map[rname]
            role_map[rname] = rid
            _dpatch(f'/guilds/{guild_id}/roles/{rid}', role_payload)
            results.append(f'🔄 Rola "{rname}" zaktualizowana')
        else:
            # Create new role
            data, err = _dpost(f'/guilds/{guild_id}/roles',
                               {**role_payload, 'name': rname})
            if data and data.get('id'):
                role_map[rname] = int(data['id'])
                results.append(f'✅ Rola: {rname}')
            else:
                results.append(f'❌ Błąd roli "{rname}": {err}')

    # ── 2. Categories + channels (with permission overwrites) ─────────────────
    existing_channels = _dget(f'/guilds/{guild_id}/channels') or []
    existing_ch_map   = {c['name']: int(c['id']) for c in existing_channels}

    for cat_name, channels_list in MOPS_CHANNELS:
        cat_ow = _build_overwrites(role_map, guild_id, MOPS_CAT_PERMS.get(cat_name, []))
        if cat_name in existing_ch_map:
            # Category exists → PATCH its permission overwrites
            cat_id = existing_ch_map[cat_name]
            if cat_ow:
                _dpatch(f'/channels/{cat_id}', {'permission_overwrites': cat_ow})
            results.append(f'🔄 Kategoria "{cat_name}" zaktualizowana')
        else:
            # Create new category
            cat_payload = {'name': cat_name, 'type': 4}
            if cat_ow:
                cat_payload['permission_overwrites'] = cat_ow
            data, err = _dpost(f'/guilds/{guild_id}/channels', cat_payload)
            if data and data.get('id'):
                cat_id = int(data['id'])
                results.append(f'✅ Kategoria: {cat_name}')
            else:
                results.append(f'❌ Błąd kategorii "{cat_name}": {err}')
                continue

        for ch_name, ch_type in channels_list:
            ch_ow = _build_overwrites(role_map, guild_id, MOPS_PERMS.get(ch_name, []))
            if ch_name in existing_ch_map:
                # Channel exists → PATCH permission overwrites and parent
                cid = existing_ch_map[ch_name]
                ch_map[ch_name] = cid
                patch_payload = {'parent_id': str(cat_id)}
                if ch_ow:
                    patch_payload['permission_overwrites'] = ch_ow
                _dpatch(f'/channels/{cid}', patch_payload)
                icon = '#' if ch_type == 0 else '🔊'
                results.append(f'  🔄 {icon} {ch_name} zaktualizowany')
            else:
                # Create new channel
                ch_payload = {'name': ch_name, 'type': ch_type,
                              'parent_id': str(cat_id)}
                if ch_ow:
                    ch_payload['permission_overwrites'] = ch_ow
                data, err = _dpost(f'/guilds/{guild_id}/channels', ch_payload)
                if data and data.get('id'):
                    ch_map[ch_name] = int(data['id'])
                    icon = '#' if ch_type == 0 else '🔊'
                    results.append(f'  ✅ {icon} {ch_name}')
                else:
                    results.append(f'  ❌ Błąd kanału "{ch_name}": {err}')

    # ── 3. Factions in DB ─────────────────────────────────────────────────────
    for fac_def in MOPS_FACTIONS:
        existing_fac = db.get_faction_by_name(guild_id, fac_def['name'])
        if not existing_fac:
            fac_role_id  = role_map.get(fac_def['name'])
            role_ids_arg = [fac_role_id] if fac_role_id else []
            existing_fac = db.create_faction(
                guild_id, fac_def['name'],
                icon=fac_def['icon'], color=fac_def['color'],
                description=fac_def['description'],
                role_ids=role_ids_arg,
            )
            results.append(f'✅ Frakcja: {fac_def["icon"]} {fac_def["name"]}')
        else:
            results.append(f'⏭️ Frakcja "{fac_def["name"]}" już istnieje')

    # ── 4. Special ranks (Król, Książę) ───────────────────────────────────────
    for rank_def in MOPS_SPECIAL_RANKS:
        if not db.get_rank_by_name(guild_id, rank_def['name']):
            db.create_rank(
                guild_id, rank_def['name'], 0,
                role_id=role_map.get(rank_def['name']),
                color=rank_def['color'], icon=rank_def['icon'],
                description=rank_def['description'],
                is_special=True, is_owner_only=True,
            )
            results.append(f'✅ Ranga: {rank_def["icon"]} {rank_def["name"]}')
        else:
            results.append(f'⏭️ Ranga "{rank_def["name"]}" już istnieje')

    # ── 5. Faction ranks ──────────────────────────────────────────────────────
    alpha1_fac = db.get_faction_by_name(guild_id, 'Alpha-1')
    nu7_fac    = db.get_faction_by_name(guild_id, 'Nu-7')
    for rank_def in MOPS_FACTION_RANKS:
        if db.get_rank_by_name(guild_id, rank_def['name']):
            results.append(f'⏭️ Ranga "{rank_def["name"]}" już istnieje')
            continue
        fac    = alpha1_fac if rank_def['faction'] == 'Alpha-1' else nu7_fac
        fac_id = fac['id'] if fac else None
        # 'role' field holds the Discord role name (shared across factions)
        discord_role_name = rank_def.get('role', rank_def['name'])
        db.create_rank(
            guild_id, rank_def['name'], rank_def['pts'],
            role_id=role_map.get(discord_role_name),
            color=rank_def['color'], icon=rank_def['icon'],
            description=rank_def['description'],
            is_special=rank_def['special'],
            is_owner_only=rank_def['owner_only'],
            faction_id=fac_id,
        )
        results.append(f'✅ Ranga frakcyjna: {rank_def["icon"]} {rank_def["name"]}')

    # ── 6. Jobs ───────────────────────────────────────────────────────────────
    for job_def in MOPS_JOBS:
        if not db.get_job_by_name(guild_id, job_def['name']):
            db.create_job(
                guild_id, job_def['name'], job_def['pts'],
                icon=job_def['icon'], color=job_def['color'],
                description=job_def['description'],
                role_id=role_map.get(job_def['name']),
            )
            results.append(f'✅ Praca: {job_def["icon"]} {job_def["name"]}')
        else:
            results.append(f'⏭️ Praca "{job_def["name"]}" już istnieje')

    # ── 7. Guild config ───────────────────────────────────────────────────────
    admin_ids = [rid for rid in [
        role_map.get('Military Police'),
        role_map.get('Alpha-1'),
    ] if rid]
    updates = {'admin_role_ids': json.dumps(admin_ids)}
    for cfg_key, ch_name in [
        ('clock_channel_id',          'apel'),
        ('log_channel_id',            'logi'),
        ('command_panel_channel_id',  'panel'),
        ('job_channel_id',            'prace'),
    ]:
        if ch_name in ch_map:
            updates[cfg_key] = ch_map[ch_name]
    db.update_guild(guild_id, **updates)
    results.append('✅ Konfiguracja bota zaktualizowana')

    # ── 8. Clock panel → #apel ────────────────────────────────────────────────
    apel_ch_id = ch_map.get('apel')
    if apel_ch_id:
        from datetime import date as _date
        stats    = db.get_guild_stats(guild_id)
        now      = datetime.now()
        day_name = db.DAYS_PL[now.weekday()]
        clock_embed = {
            'title': '📋 Codzienny Apel – Baza MOPS',
            'description': (
                f'**{day_name}, {now.strftime("%d.%m.%Y")}**\n\n'
                '━━━━━━━━━━━━━━━━━━━━━━━━━━\n'
                '🟢 **Clock In** — Zacznij sesję aktywności\n'
                '🔴 **Clock Out** — Zakończ sesję aktywności\n'
                '━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n'
                '> Punkty przyznawane za każdą godzinę aktywności.\n'
                '> Pamiętaj żeby się wylogować po zakończeniu!\n\n'
                f'👥 Aktywnych teraz: **{stats.get("active_now", 0)}**\n'
                f'⚠️ Ostrzeżenia (serwer): **{stats.get("warning_count", 0)}**'
            ),
            'color': 0x2ECC71,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'footer': {'text': 'System Rang MOPS • Punkty za aktywność'},
        }
        clock_components = [{'type': 1, 'components': [
            {'type': 2, 'style': 3, 'label': '🟢 Clock In',  'custom_id': 'mops_clock_in'},
            {'type': 2, 'style': 4, 'label': '🔴 Clock Out', 'custom_id': 'mops_clock_out'},
        ]}]
        data, err = _dpost(f'/channels/{apel_ch_id}/messages',
                           {'embeds': [clock_embed], 'components': clock_components})
        if data and data.get('id'):
            db.save_daily_embed(guild_id, apel_ch_id, int(data['id']),
                                _date.today().isoformat())
            results.append('✅ Panel apelu wysłany do #apel')
        else:
            results.append(f'❌ Błąd wysyłania panelu apelu: {err}')

    # ── 9. Job panel → #prace ─────────────────────────────────────────────────
    prace_ch_id = ch_map.get('prace')
    if prace_ch_id:
        jobs_list = db.get_jobs(guild_id)
        if jobs_list:
            lines = [
                f'**{j["icon"]} {j["name"]}** – `{j["required_points"]:.0f} pkt`'
                + (f' – *{j["description"]}*' if j.get('description') else '')
                for j in jobs_list
            ]
            job_desc = ('Zdobądź wymaganą liczbę punktów i kliknij **Wybierz pracę**!\n\n'
                        + '\n'.join(lines))
        else:
            job_desc = 'Zdobądź wymaganą liczbę punktów i kliknij **Wybierz pracę**!'
        job_embed = {
            'title': '💼 Lista Prac – MOPS',
            'description': job_desc,
            'color': 0x7289DA,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'footer': {'text': 'Możesz posiadać kilka prac jednocześnie • Cywile only'},
        }
        job_components = [{'type': 1, 'components': [
            {'type': 2, 'style': 3, 'label': '💼 Wybierz pracę',
             'custom_id': 'mops_job_select'},
            {'type': 2, 'style': 4, 'label': '🚪 Zrezygnuj z pracy',
             'custom_id': 'mops_job_deselect'},
            {'type': 2, 'style': 2, 'label': '📋 Moje prace',
             'custom_id': 'mops_job_list'},
        ]}]
        data, err = _dpost(f'/channels/{prace_ch_id}/messages',
                           {'embeds': [job_embed], 'components': job_components})
        if data and data.get('id'):
            db.save_panel_embed(guild_id, prace_ch_id, int(data['id']), 'jobs')
            results.append('✅ Panel prac wysłany do #prace')
        else:
            results.append(f'❌ Błąd wysyłania panelu prac: {err}')

    # ── 10. Auto-connect ALL existing DB ranks to Discord roles ──────────────
    # Build a complete DB-rank-name → Discord-role-id mapping
    rank_to_discord = {}
    for sr in MOPS_SPECIAL_RANKS:
        if sr['name'] in role_map:
            rank_to_discord[sr['name']] = role_map[sr['name']]
    for fr in MOPS_FACTION_RANKS:
        discord_role_name = fr.get('role', fr['name'])
        if discord_role_name in role_map:
            rank_to_discord[fr['name']] = role_map[discord_role_name]

    all_db_ranks = db.get_ranks(guild_id)
    connected = 0
    for rank in all_db_ranks:
        # First check explicit mapping, then fall back to direct name match
        new_role_id = rank_to_discord.get(rank['name']) or role_map.get(rank['name'])
        if new_role_id and rank.get('role_id') != new_role_id:
            db.update_rank(rank['id'], role_id=new_role_id)
            connected += 1
    results.append(f'✅ Auto-połączono {connected} rang z rolami Discord')

    # ── Summary ───────────────────────────────────────────────────────────────
    errors  = sum(1 for r in results if r.startswith('❌'))
    skipped = sum(1 for r in results if r.startswith('⏭️'))
    created = sum(1 for r in results if r.startswith('✅'))
    if errors == 0:
        flash(f'✅ Auto-Setup zakończony! Stworzono: {created}, pominięto: {skipped}.', 'success')
    else:
        flash(
            f'⚠️ Setup zakończony z błędami. Stworzono: {created}, '
            f'błędów: {errors}, pominięto: {skipped}. '
            f'Sprawdź czy bot ma uprawnienia Zarządzaj Rolami i Kanałami.',
            'warning')
    return redirect(url_for('guild_overview', guild_id=guild_id))


# ─── Logs ─────────────────────────────────────────────────────────────────────

@app.route('/guild/<int:guild_id>/logs')
@login_required
def logs_page(guild_id):
    db.ensure_guild(guild_id)
    info = _guild_info(guild_id)
    tab = request.args.get('tab', '')
    action_type = request.args.get('type', '')
    action_logs  = db.get_action_logs(guild_id, limit=100, action_type=action_type or None)
    all_warnings = db.get_all_warnings(guild_id, limit=50)
    transactions = db.get_all_transactions(guild_id, limit=50)
    return render_template('logs.html',
        guild_id=guild_id, guild_name=info.get('name', str(guild_id)),
        action_logs=action_logs, all_warnings=all_warnings, transactions=transactions,
        tab=tab, filter_type=action_type)


# ─── Export / Backup ──────────────────────────────────────────────────────────

@app.route('/guild/<int:guild_id>/export/users')
@login_required
def export_users(guild_id):
    users = db.get_all_users(guild_id)
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(['user_id', 'username', 'display_name', 'points', 'total_hours',
                'sessions_count', 'streak_days', 'is_banned', 'created_at'])
    for u in users:
        w.writerow([u['user_id'], u.get('username', ''), u.get('display_name', ''),
                    f'{u["points"]:.2f}', f'{u["total_hours"]:.4f}',
                    u['sessions_count'], u.get('streak_days', 0),
                    u['is_banned'], u.get('created_at', '')])
    out.seek(0)
    return Response(out.getvalue(), mimetype='text/csv',
                    headers={'Content-Disposition':
                             f'attachment; filename=users_{guild_id}.csv'})

@app.route('/guild/<int:guild_id>/export/transactions')
@login_required
def export_transactions(guild_id):
    txs = db.get_all_transactions(guild_id, limit=5000)
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(['id', 'user_id', 'points_change', 'points_before', 'points_after',
                'transaction_type', 'note', 'assigned_by', 'created_at'])
    for t in txs:
        w.writerow([t['id'], t['user_id'], f'{t["points_change"]:.2f}',
                    f'{t["points_before"]:.2f}', f'{t["points_after"]:.2f}',
                    t['transaction_type'], t.get('note', ''),
                    t.get('assigned_by', ''), t.get('created_at', '')])
    out.seek(0)
    return Response(out.getvalue(), mimetype='text/csv',
                    headers={'Content-Disposition':
                             f'attachment; filename=transactions_{guild_id}.csv'})

@app.route('/guild/<int:guild_id>/backup')
@login_required
def backup_guild(guild_id):
    data = db.get_full_backup(guild_id)
    out  = json.dumps(data, ensure_ascii=False, indent=2, default=str)
    fname = f'backup_{guild_id}_{datetime.now().strftime("%Y%m%d_%H%M")}.json'
    return Response(out, mimetype='application/json',
                    headers={'Content-Disposition': f'attachment; filename={fname}'})


# ─── Import ────────────────────────────────────────────────────────────────────

@app.route('/guild/<int:guild_id>/import', methods=['GET', 'POST'])
@login_required
def import_page(guild_id):
    info           = _guild_info(guild_id)
    guild_name     = info.get('name', str(guild_id)) if info else str(guild_id)
    preview        = None
    import_results = session.pop('import_results', None)  # one-shot display

    if request.method == 'POST':
        f = request.files.get('backup_file')
        if not f or not f.filename.endswith('.json'):
            flash('Wybierz plik .json', 'danger')
            return redirect(url_for('import_page', guild_id=guild_id))
        try:
            raw  = f.read().decode('utf-8')
            data = json.loads(raw)
        except Exception as exc:
            flash(f'Błąd parsowania JSON: {exc}', 'danger')
            return redirect(url_for('import_page', guild_id=guild_id))

        if not any(k in data for k in ('users', 'ranks', 'factions', 'jobs')):
            flash('Nieprawidłowy format backupu – brak kluczy users/ranks/factions/jobs.', 'danger')
            return redirect(url_for('import_page', guild_id=guild_id))

        session['import_data']     = raw
        session['import_guild_id'] = guild_id
        preview = {
            'version':            data.get('version', '1.0'),
            'exported_at':        data.get('exported_at', '—'),
            'source_guild':       data.get('guild_id', '—'),
            'users':              len(data.get('users', [])),
            'ranks':              len(data.get('ranks', [])),
            'factions':           len(data.get('factions', [])),
            'jobs':               len(data.get('jobs', [])),
            'warnings':           len(data.get('warnings', [])),
            'user_special_ranks': len(data.get('user_special_ranks', [])),
            'faction_members':    len(data.get('faction_members', [])),
            'user_jobs':          len(data.get('user_jobs', [])),
            'clock_sessions':     len(data.get('clock_sessions', [])),
            'point_transactions': len(data.get('point_transactions', [])),
            'has_config':         'guild_config' in data,
        }

    return render_template('import.html',
                           guild_id=guild_id, guild_name=guild_name,
                           preview=preview,
                           import_results=import_results)


@app.route('/guild/<int:guild_id>/import/run', methods=['POST'])
@login_required
def import_run(guild_id):
    raw  = session.get('import_data')
    sgid = session.get('import_guild_id')
    if not raw or sgid != guild_id:
        flash('Brak danych importu – prześlij plik ponownie.', 'danger')
        return redirect(url_for('import_page', guild_id=guild_id))

    data = json.loads(raw)
    mode = request.form.get('mode', 'merge')   # 'merge' | 'overwrite'

    do_config    = 'do_config'    in request.form
    do_factions  = 'do_factions'  in request.form
    do_ranks     = 'do_ranks'     in request.form
    do_jobs      = 'do_jobs'      in request.form
    do_users     = 'do_users'     in request.form
    do_assign    = 'do_assign'    in request.form
    do_sessions  = 'do_sessions'  in request.form
    do_warnings  = 'do_warnings'  in request.form

    results = []
    ok_n = err_n = skip_n = 0

    def _ok(msg):
        nonlocal ok_n;   ok_n   += 1; results.append(f'✅ {msg}')
    def _skip(msg):
        nonlocal skip_n; skip_n += 1; results.append(f'⏭️ {msg}')
    def _err(msg):
        nonlocal err_n;  err_n  += 1; results.append(f'❌ {msg}')

    # ID translation tables (backup old_id → current DB id)
    faction_id_map = {}
    rank_id_map    = {}
    job_id_map     = {}

    # ── 1. Guild config ────────────────────────────────────────────────────────
    if do_config and 'guild_config' in data:
        try:
            allowed = {'clock_channel_id', 'log_channel_id', 'command_panel_channel_id',
                       'job_channel_id', 'points_per_hour', 'min_clock_minutes',
                       'auto_clockout_hours', 'warn_limit', 'clock_cooldown_min',
                       'admin_role_ids', 'embed_schedule'}
            upd = {k: v for k, v in data['guild_config'].items()
                   if k in allowed and v is not None}
            if upd:
                db.update_guild(guild_id, **upd)
            _ok('Konfiguracja gilda zaktualizowana')
        except Exception as exc:
            _err(f'Konfiguracja: {exc}')

    # ── 2. Factions ────────────────────────────────────────────────────────────
    for fac in data.get('factions', []):
        existing = db.get_faction_by_name(guild_id, fac['name'])
        if existing:
            faction_id_map[fac['id']] = existing['id']
        if do_factions:
            if existing:
                if mode == 'overwrite':
                    db.update_faction(existing['id'],
                                      icon=fac.get('icon', '⚔️'),
                                      color=fac.get('color', '#7289da'),
                                      description=fac.get('description', ''))
                    _ok(f'Frakcja {fac["name"]} zaktualizowana')
                else:
                    _skip(f'Frakcja {fac["name"]} już istnieje')
            else:
                try:
                    role_ids = json.loads(fac.get('role_ids') or '[]')
                except Exception:
                    role_ids = []
                new = db.create_faction(guild_id, fac['name'],
                                        icon=fac.get('icon', '⚔️'),
                                        color=fac.get('color', '#7289da'),
                                        role_ids=role_ids,
                                        description=fac.get('description', ''))
                if new:
                    faction_id_map[fac['id']] = new['id']
                    _ok(f'Frakcja {fac["name"]} utworzona')
                else:
                    _err(f'Frakcja {fac["name"]} – błąd tworzenia')

    # ── 3. Ranks ───────────────────────────────────────────────────────────────
    for r in data.get('ranks', []):
        existing = db.get_rank_by_name(guild_id, r['name'])
        if existing:
            rank_id_map[r['id']] = existing['id']
        if do_ranks:
            if existing:
                if mode == 'overwrite':
                    db.update_rank(existing['id'],
                                   required_points=float(r.get('required_points', 0)),
                                   icon=r.get('icon', '⭐'),
                                   color=r.get('color', '#99aab5'),
                                   is_special=int(bool(r.get('is_special', 0))),
                                   is_owner_only=int(bool(r.get('is_owner_only', 0))))
                    _ok(f'Ranga {r["name"]} zaktualizowana')
                else:
                    _skip(f'Ranga {r["name"]} już istnieje')
            else:
                old_fid = r.get('faction_id')
                new = db.create_rank(guild_id, r['name'],
                                     required_points=float(r.get('required_points', 0)),
                                     icon=r.get('icon', '⭐'),
                                     color=r.get('color', '#99aab5'),
                                     is_special=bool(r.get('is_special', 0)),
                                     is_owner_only=bool(r.get('is_owner_only', 0)),
                                     faction_id=faction_id_map.get(old_fid) if old_fid else None)
                if new:
                    rank_id_map[r['id']] = new['id']
                    _ok(f'Ranga {r["name"]} utworzona')
                else:
                    _err(f'Ranga {r["name"]} – błąd tworzenia')

    # ── 4. Jobs ────────────────────────────────────────────────────────────────
    for j in data.get('jobs', []):
        existing = db.get_job_by_name(guild_id, j['name'])
        if existing:
            job_id_map[j['id']] = existing['id']
        if do_jobs:
            if existing:
                if mode == 'overwrite':
                    db.update_job(existing['id'],
                                  required_points=float(j.get('required_points', 0)),
                                  icon=j.get('icon', '💼'),
                                  color=j.get('color', '#7289da'))
                    _ok(f'Praca {j["name"]} zaktualizowana')
                else:
                    _skip(f'Praca {j["name"]} już istnieje')
            else:
                new = db.create_job(guild_id, j['name'],
                                    required_points=float(j.get('required_points', 0)),
                                    icon=j.get('icon', '💼'),
                                    color=j.get('color', '#7289da'),
                                    description=j.get('description', ''))
                if new:
                    job_id_map[j['id']] = new['id']
                    _ok(f'Praca {j["name"]} utworzona')
                else:
                    _err(f'Praca {j["name"]} – błąd tworzenia')

    # ── 5. Users ───────────────────────────────────────────────────────────────
    if do_users:
        for u in data.get('users', []):
            try:
                uid = int(u['user_id'])
                db.ensure_user(uid, guild_id,
                               username=u.get('username', ''),
                               display_name=u.get('display_name', ''))
                existing = db.get_user(uid, guild_id)
                cur_pts  = float(existing.get('points', 0)) if existing else 0.0
                new_pts  = float(u.get('points', 0))
                if mode == 'overwrite' or new_pts > cur_pts:
                    if new_pts != cur_pts:
                        db.set_points(uid, guild_id, new_pts,
                                      note='Import z backupu', assigned_by=0)
                    db.update_user(uid, guild_id,
                                   total_hours=float(u.get('total_hours', 0)),
                                   sessions_count=int(u.get('sessions_count', 0)),
                                   streak_days=int(u.get('streak_days', 0)))
                    if u.get('is_banned'):
                        db.update_user(uid, guild_id, is_banned=1)
                    if u.get('admin_notes'):
                        db.update_user_notes(uid, guild_id, u['admin_notes'])
                    _ok(f'Użytkownik {u.get("username") or uid} ({new_pts:.0f} pkt)')
                else:
                    _skip(f'Użytkownik {u.get("username") or uid} (aktualne {cur_pts:.0f} ≥ {new_pts:.0f} pkt)')
            except Exception as exc:
                _err(f'Użytkownik {u.get("user_id", "?")}: {exc}')

    # ── 6. Assignments (special ranks / factions / jobs) ──────────────────────
    if do_assign:
        for sr in data.get('user_special_ranks', []):
            try:
                uid    = int(sr['user_id'])
                new_rid = rank_id_map.get(sr['rank_id'])
                if not new_rid:
                    _skip(f'Ranga specjalna uid={uid}: ranga #{sr["rank_id"]} nieznana')
                    continue
                if db.give_special_rank(uid, guild_id, new_rid,
                                        assigned_by=0, note=sr.get('note', '')):
                    _ok(f'Ranga specjalna → uid={uid}')
                else:
                    _skip(f'Ranga specjalna uid={uid} już przypisana')
            except Exception as exc:
                _err(f'Ranga specjalna: {exc}')

        for fm in data.get('faction_members', []):
            try:
                uid    = int(fm['user_id'])
                new_fid = faction_id_map.get(fm['faction_id'])
                if not new_fid:
                    _skip(f'Frakcja uid={uid}: frakcja #{fm["faction_id"]} nieznana')
                    continue
                db.assign_faction_member(uid, guild_id, new_fid, assigned_by=0)
                _ok(f'Frakcja → uid={uid}')
            except Exception as exc:
                _err(f'Frakcja member: {exc}')

        for uj in data.get('user_jobs', []):
            try:
                uid    = int(uj['user_id'])
                new_jid = job_id_map.get(uj['job_id'])
                if not new_jid:
                    _skip(f'Praca uid={uid}: praca #{uj["job_id"]} nieznana')
                    continue
                if db.select_job(uid, guild_id, new_jid, admin_granted=True, granted_by=0):
                    _ok(f'Praca → uid={uid}')
                else:
                    _skip(f'Praca uid={uid} już przypisana')
            except Exception as exc:
                _err(f'Praca przypisanie: {exc}')

    # ── 7. Clock sessions ─────────────────────────────────────────────────────
    if do_sessions:
        try:
            n = db.bulk_import_sessions(guild_id, data.get('clock_sessions', []))
            _ok(f'Sesje clock-in: {n} nowych')
            n = db.bulk_import_transactions(guild_id, data.get('point_transactions', []))
            _ok(f'Transakcje punktów: {n} nowych')
        except Exception as exc:
            _err(f'Sesje/transakcje: {exc}')

    # ── 8. Warnings ───────────────────────────────────────────────────────────
    if do_warnings:
        for w in data.get('warnings', []):
            try:
                db.add_warning(int(w['user_id']), guild_id,
                               reason=w.get('reason', ''),
                               warned_by=w.get('warned_by'),
                               is_auto=bool(w.get('is_auto', 0)))
                _ok(f'Ostrzeżenie uid={w["user_id"]}')
            except Exception as exc:
                _err(f'Ostrzeżenie: {exc}')

    session.pop('import_data', None)
    session.pop('import_guild_id', None)
    session['import_results'] = results[-200:]

    status = 'success' if err_n == 0 else 'warning'
    flash(f'Import zakończony — ✅ {ok_n} sukces · ⏭️ {skip_n} pominięto · ❌ {err_n} błędów.', status)
    return redirect(url_for('import_page', guild_id=guild_id))


# ─── API ──────────────────────────────────────────────────────────────────────

@app.route('/api/guild/<int:guild_id>/stats')
@login_required
def api_stats(guild_id):
    return jsonify(db.get_guild_stats(guild_id))

@app.route('/api/guild/<int:guild_id>/chart-data')
@login_required
def api_chart_data(guild_id):
    days = int(request.args.get('days', 14))
    days = min(max(days, 7), 30)
    data = db.get_daily_activity(guild_id, days=days)
    return jsonify(data)

@app.route('/ping')
def ping():
    return 'OK', 200


# ─── Devices (ESP32) ──────────────────────────────────────────────────────────

@app.route('/guild/<int:guild_id>/devices')
@login_required
def devices_page(guild_id):
    cfg = db.get_guild(guild_id) or {}
    guild_info = _guild_info(guild_id)
    devices = db.get_devices(guild_id)
    # Enrich with runtime online status from device_manager
    try:
        from device_manager import device_manager
        for d in devices:
            bot = device_manager.bots.get(d['device_id'])
            d['bot_running'] = bool(bot and bot.is_online)
    except Exception:
        for d in devices:
            d['bot_running'] = False
    channels = db.get_channels(guild_id)
    channels_map = {c['id']: c for c in channels}
    return render_template('devices.html',
                           guild_id=guild_id,
                           guild_name=guild_info.get('name', str(guild_id)),
                           devices=devices,
                           channels=channels,
                           channels_map=channels_map,
                           cfg=cfg)


@app.route('/guild/<int:guild_id>/devices/add', methods=['POST'])
@login_required
def device_add(guild_id):
    device_id = request.form.get('device_id', '').strip().replace(' ', '_').lower()
    name = request.form.get('name', '').strip()
    bot_token = request.form.get('bot_token', '').strip()
    user_id_raw = request.form.get('user_id', '').strip()
    if not device_id or not name:
        flash('Wypełnij ID urządzenia i nazwę.', 'danger')
        return redirect(url_for('devices_page', guild_id=guild_id))
    user_id = int(user_id_raw) if user_id_raw.isdigit() else None
    ok = db.add_device(device_id, guild_id, name, bot_token=bot_token, user_id=user_id)
    if not ok:
        flash(f'Urządzenie o ID "{device_id}" już istnieje.', 'danger')
        return redirect(url_for('devices_page', guild_id=guild_id))
    # Start bot if token provided
    if bot_token:
        try:
            from device_manager import device_manager
            device_manager.schedule_restart(device_id)
        except Exception:
            pass
    flash(f'Urządzenie "{name}" dodane.', 'success')
    return redirect(url_for('devices_page', guild_id=guild_id))


@app.route('/guild/<int:guild_id>/devices/<device_id>/edit', methods=['POST'])
@login_required
def device_edit(guild_id, device_id):
    d = db.get_device(device_id)
    if not d or d['guild_id'] != guild_id:
        flash('Urządzenie nie znalezione.', 'danger')
        return redirect(url_for('devices_page', guild_id=guild_id))
    name = request.form.get('name', '').strip()
    bot_token = request.form.get('bot_token', '').strip()
    user_id_raw = request.form.get('user_id', '').strip()
    user_id = int(user_id_raw) if user_id_raw.isdigit() else None
    db.update_device(device_id, name=name, bot_token=bot_token, user_id=user_id)
    # Restart bot if token changed
    if bot_token != d.get('bot_token', ''):
        try:
            from device_manager import device_manager
            device_manager.schedule_restart(device_id)
        except Exception:
            pass
    flash(f'Urządzenie "{name}" zaktualizowane.', 'success')
    return redirect(url_for('devices_page', guild_id=guild_id))


@app.route('/guild/<int:guild_id>/devices/<device_id>/delete', methods=['POST'])
@login_required
def device_delete(guild_id, device_id):
    d = db.get_device(device_id)
    if not d or d['guild_id'] != guild_id:
        flash('Urządzenie nie znalezione.', 'danger')
        return redirect(url_for('devices_page', guild_id=guild_id))
    try:
        from device_manager import device_manager
        device_manager.schedule_remove(device_id)
    except Exception:
        pass
    db.delete_device(device_id)
    flash('Urządzenie usunięte.', 'success')
    return redirect(url_for('devices_page', guild_id=guild_id))


@app.route('/guild/<int:guild_id>/devices/<device_id>/restart', methods=['POST'])
@login_required
def device_restart(guild_id, device_id):
    d = db.get_device(device_id)
    if not d or d['guild_id'] != guild_id:
        flash('Urządzenie nie znalezione.', 'danger')
        return redirect(url_for('devices_page', guild_id=guild_id))
    try:
        from device_manager import device_manager
        device_manager.schedule_restart(device_id)
        flash(f'Bot "{d["name"]}" restartuje...', 'info')
    except Exception as e:
        flash(f'Błąd restartu: {e}', 'danger')
    return redirect(url_for('devices_page', guild_id=guild_id))


@app.route('/api/guild/<int:guild_id>/channels')
def api_guild_channels(guild_id):
    """Pobierz konfigurację kanałów PTT — używane przez pi_bridge.
    Uwierzytelnienie: nagłówek X-API-Secret (dowolne urządzenie gildii) lub sesja dashboardu."""
    secret = request.headers.get('X-API-Secret', '').strip()
    if secret:
        devices = db.get_devices(guild_id)
        if not any(d.get('api_secret') == secret for d in devices):
            return jsonify({'error': 'invalid secret'}), 401
    elif not session.get('logged_in'):
        return jsonify({'error': 'unauthorized'}), 401
    return jsonify(db.get_channels(guild_id))


@app.route('/api/guild/<int:guild_id>/devices/status')
@login_required
def api_devices_status(guild_id):
    """Real-time device status for JS polling."""
    devices = db.get_devices(guild_id)
    try:
        from device_manager import device_manager
        result = []
        for d in devices:
            bot = device_manager.bots.get(d['device_id'])
            result.append({
                'device_id': d['device_id'],
                'status': d['status'],
                'bot_running': bool(bot and bot.is_online),
                'last_heartbeat': d.get('last_heartbeat'),
            })
    except Exception:
        result = [{'device_id': d['device_id'], 'status': d['status'],
                   'bot_running': False, 'last_heartbeat': d.get('last_heartbeat')}
                  for d in devices]
    return jsonify(result)


# ─── Device API (called by ESP32, no login required) ─────────────────────────

def _device_auth(req) -> tuple:
    """Returns (device, error_response) from request JSON."""
    data = req.get_json(silent=True) or {}
    device_id = data.get('device_id', '').strip()
    secret = data.get('secret', '').strip()
    if not device_id or not secret:
        return None, (jsonify({'ok': False, 'error': 'missing device_id or secret'}), 400)
    d = db.get_device(device_id)
    if not d:
        return None, (jsonify({'ok': False, 'error': 'unknown device'}), 404)
    if d.get('api_secret') != secret:
        return None, (jsonify({'ok': False, 'error': 'invalid secret'}), 401)
    return d, None


@app.route('/api/device/heartbeat', methods=['POST'])
def api_device_heartbeat():
    d, err = _device_auth(request)
    if err:
        return err
    try:
        from device_manager import device_manager
        device_manager.on_heartbeat(d['device_id'])
    except Exception:
        db.update_device_heartbeat(d['device_id'])
    return jsonify({'ok': True})


@app.route('/api/clock', methods=['POST'])
def api_device_clock():
    d, err = _device_auth(request)
    if err:
        return err

    data = request.get_json(silent=True) or {}
    action = data.get('action', '').strip()
    if action not in ('clock_in', 'clock_out'):
        return jsonify({'ok': False, 'error': 'action must be clock_in or clock_out'}), 400

    user_id = d.get('user_id')
    guild_id = d.get('guild_id')
    if not user_id:
        return jsonify({'ok': False, 'error': 'no user assigned to device'}), 400

    db.ensure_user(user_id, guild_id, '', '')

    if action == 'clock_in':
        result = db.clock_in(user_id, guild_id)
        if not result:
            return jsonify({'ok': False, 'error': 'already clocked in or user not found'}), 409
        # Send Discord notification via main bot REST API
        cfg = db.get_guild(guild_id) or {}
        ch_id = cfg.get('clock_channel_id')
        if ch_id:
            _dpost(f'/channels/{ch_id}/messages', {
                'embeds': [{
                    'title': '📻 Clock In – Urządzenie',
                    'description': f'<@{user_id}> zalogował się przez **{d["name"]}**.',
                    'color': 0x43B581,
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                }]
            })
        return jsonify({'ok': True, 'action': 'clock_in',
                        'clock_in_time': result.get('clock_in_time')})

    else:  # clock_out
        result = db.clock_out(user_id, guild_id)
        if not result:
            return jsonify({'ok': False, 'error': 'not clocked in or user not found'}), 409
        pts = result.get('points_earned', 0)
        hours = result.get('hours', 0)
        cfg = db.get_guild(guild_id) or {}
        ch_id = cfg.get('clock_channel_id')
        if ch_id:
            _dpost(f'/channels/{ch_id}/messages', {
                'embeds': [{
                    'title': '📻 Clock Out – Urządzenie',
                    'description': (
                        f'<@{user_id}> wylogował się przez **{d["name"]}**.\n'
                        f'Czas: **{round(hours * 60):.0f} min** | '
                        f'Punkty: **+{pts:.1f} pkt**'
                    ),
                    'color': 0xFAA61A,
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                }]
            })
        return jsonify({'ok': True, 'action': 'clock_out',
                        'points_earned': pts, 'hours': round(hours, 2)})


@app.route('/api/channel/next', methods=['POST'])
def api_channel_next():
    """Cycle device to next audio channel. Returns new channel name and order index."""
    d, err = _device_auth(request)
    if err:
        return err
    device_id = d['device_id']
    guild_id  = d['guild_id']
    current   = d.get('current_channel_id')
    nxt = db.get_next_channel(guild_id, current)
    if not nxt:
        return jsonify({'ok': False, 'error': 'no channels configured'}), 404
    db.update_device(device_id, current_channel_id=nxt['id'])
    return jsonify({
        'ok': True,
        'channel_id':    nxt['id'],
        'channel_name':  nxt['name'],
        'channel_order': nxt['order_index'],
    })


# ─── Channels management (dashboard) ─────────────────────────────────────────

@app.route('/guild/<int:guild_id>/channels')
@login_required
def channels_page(guild_id):
    cfg = db.get_guild(guild_id) or {}
    guild_info = _guild_info(guild_id)
    channels = db.get_channels(guild_id)
    devices  = db.get_devices(guild_id)
    guild_roles = _dget(f'/guilds/{guild_id}/roles') or []
    discord_channels = _dget(f'/guilds/{guild_id}/channels') or []
    voice_channels = [c for c in discord_channels if c.get('type') == 2]
    return render_template('channels.html',
                           guild_id=guild_id,
                           guild_name=guild_info.get('name', str(guild_id)),
                           channels=channels,
                           devices=devices,
                           voice_channels=voice_channels,
                           cfg=cfg)


@app.route('/guild/<int:guild_id>/channels/add', methods=['POST'])
@login_required
def channel_add(guild_id):
    name = request.form.get('name', '').strip()
    if not name:
        flash('Podaj nazwę kanału.', 'danger')
        return redirect(url_for('channels_page', guild_id=guild_id))
    discord_ch_raw = request.form.get('discord_channel_id', '').strip()
    bot_id         = request.form.get('bot_id', '').strip() or None
    order_raw      = request.form.get('order_index', '0').strip()
    is_radio       = 'is_radio_bridge' in request.form
    discord_ch_id  = int(discord_ch_raw) if discord_ch_raw.isdigit() else None
    order_index    = int(order_raw) if order_raw.isdigit() else 0
    ch = db.create_channel(guild_id, name, discord_ch_id, bot_id, order_index, is_radio)
    if ch:
        flash(f'Kanał "{name}" dodany.', 'success')
    else:
        flash('Błąd podczas dodawania kanału.', 'danger')
    return redirect(url_for('channels_page', guild_id=guild_id))


@app.route('/guild/<int:guild_id>/channels/<int:channel_id>/edit', methods=['POST'])
@login_required
def channel_edit(guild_id, channel_id):
    ch = db.get_channel(channel_id)
    if not ch or ch['guild_id'] != guild_id:
        flash('Kanał nie znaleziony.', 'danger')
        return redirect(url_for('channels_page', guild_id=guild_id))
    name = request.form.get('name', '').strip()
    discord_ch_raw = request.form.get('discord_channel_id', '').strip()
    bot_id         = request.form.get('bot_id', '').strip() or None
    order_raw      = request.form.get('order_index', '0').strip()
    is_radio       = 'is_radio_bridge' in request.form
    discord_ch_id  = int(discord_ch_raw) if discord_ch_raw.isdigit() else None
    order_index    = int(order_raw) if order_raw.isdigit() else 0
    db.update_channel(channel_id, name=name, discord_channel_id=discord_ch_id,
                      bot_id=bot_id, order_index=order_index,
                      is_radio_bridge=1 if is_radio else 0)
    flash(f'Kanał "{name}" zaktualizowany.', 'success')
    return redirect(url_for('channels_page', guild_id=guild_id))


@app.route('/guild/<int:guild_id>/channels/<int:channel_id>/delete', methods=['POST'])
@login_required
def channel_delete(guild_id, channel_id):
    ch = db.get_channel(channel_id)
    if not ch or ch['guild_id'] != guild_id:
        flash('Kanał nie znaleziony.', 'danger')
        return redirect(url_for('channels_page', guild_id=guild_id))
    db.delete_channel(channel_id)
    flash('Kanał usunięty.', 'success')
    return redirect(url_for('channels_page', guild_id=guild_id))


# ─── WebSocket – PTT audio bridge ─────────────────────────────────────────────
#
# Protocol (binary PCM16, mono 16 kHz, little-endian):
#   Client → Server:  TEXT "START"       device starts transmitting
#                     BIN  <pcm16 chunk>  audio data
#                     TEXT "END"         device finished
#   Server → Client:  TEXT "AUDIO_START" incoming audio from another device
#                     BIN  <pcm16 chunk>  same format
#                     TEXT "AUDIO_END"   end of incoming audio
#
# Authentication via JSON on first TEXT message:
#   {"type": "auth", "device_id": "...", "secret": "..."}
# OR via HTTP headers: X-Device-ID + X-API-Secret (for ESP32 arduinoWebSockets)
# ─────────────────────────────────────────────────────────────────────────────

# channel_id (int) → set of active WebSocket connections
_ws_channels: dict[int, set] = {}
_ws_lock = threading.Lock()


def _ws_register(channel_id: int, ws) -> None:
    with _ws_lock:
        _ws_channels.setdefault(channel_id, set()).add(ws)


def _ws_unregister(channel_id: int, ws) -> None:
    with _ws_lock:
        s = _ws_channels.get(channel_id)
        if s:
            s.discard(ws)
            if not s:
                del _ws_channels[channel_id]


def _ws_broadcast_bin(channel_id: int, data: bytes, sender_ws) -> None:
    """Send binary audio frame to all other connections on same channel."""
    with _ws_lock:
        peers = set(_ws_channels.get(channel_id, set()))
    for peer in peers:
        if peer is sender_ws:
            continue
        try:
            peer.send(data)
        except Exception:
            pass


def _ws_broadcast_txt(channel_id: int, msg: str, sender_ws) -> None:
    with _ws_lock:
        peers = set(_ws_channels.get(channel_id, set()))
    for peer in peers:
        if peer is sender_ws:
            continue
        try:
            peer.send(msg)
        except Exception:
            pass


@sock.route('/ws/audio')
def ws_audio(ws):
    """WebSocket endpoint for PTT audio streaming between ESP32 devices."""
    # Authenticate via HTTP headers (ESP32 arduinoWebSockets sends these)
    device_id = request.headers.get('X-Device-ID', '').strip()
    secret    = request.headers.get('X-API-Secret', '').strip()

    # Fall back to JSON auth message if headers not present
    device = None
    channel_id = None

    if device_id and secret:
        d = db.get_device(device_id)
        if d and d.get('api_secret') == secret:
            device = d

    if device is None:
        # Wait for auth message {"type":"auth","device_id":"...","secret":"..."}
        try:
            msg = ws.receive(timeout=10)
            if isinstance(msg, str):
                auth = json.loads(msg)
                if auth.get('type') == 'auth':
                    device_id = auth.get('device_id', '')
                    secret    = auth.get('secret', '')
                    d = db.get_device(device_id)
                    if d and d.get('api_secret') == secret:
                        device = d
        except Exception:
            pass

    if device is None:
        ws.send('{"error":"unauthorized"}')
        ws.close(message=b'Unauthorized')
        return

    # Resolve current channel
    channel_id = device.get('current_channel_id')
    if channel_id is None:
        # Auto-assign to first channel
        chs = db.get_channels(device['guild_id'])
        if chs:
            channel_id = chs[0]['id']
            db.update_device(device['device_id'], current_channel_id=channel_id)

    if channel_id is None:
        ws.send('{"error":"no channels configured"}')
        ws.close()
        return

    _ws_register(channel_id, ws)
    ws.send(json.dumps({'type': 'connected', 'channel_id': channel_id,
                        'device_id': device['device_id']}))

    try:
        while True:
            msg = ws.receive(timeout=60)
            if msg is None:
                break

            # Re-check channel in case device switched while connected
            current = db.get_device(device['device_id'])
            new_ch = current.get('current_channel_id') if current else channel_id
            if new_ch and new_ch != channel_id:
                _ws_unregister(channel_id, ws)
                channel_id = new_ch
                _ws_register(channel_id, ws)
                ws.send(json.dumps({'type': 'channel_changed', 'channel_id': channel_id}))
                continue

            if isinstance(msg, bytes):
                # Binary audio frame – broadcast to all peers on same channel
                _ws_broadcast_bin(channel_id, msg, ws)
            elif isinstance(msg, str):
                msg_stripped = msg.strip()
                if msg_stripped == 'START':
                    _ws_broadcast_txt(channel_id,
                                      json.dumps({'type': 'AUDIO_START',
                                                  'from': device['device_id']}),
                                      ws)
                elif msg_stripped == 'END':
                    _ws_broadcast_txt(channel_id,
                                      json.dumps({'type': 'AUDIO_END',
                                                  'from': device['device_id']}),
                                      ws)
    except Exception:
        pass
    finally:
        _ws_unregister(channel_id, ws)

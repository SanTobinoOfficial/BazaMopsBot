import os
import json
import requests
from datetime import datetime
from functools import wraps

from flask import (Flask, render_template, request, redirect,
                   url_for, session, flash, jsonify)
import database as db

app = Flask(__name__, template_folder='templates')
app.secret_key = os.environ.get('DASHBOARD_SECRET', 'change-me-in-production')

DISCORD_API = 'https://discord.com/api/v10'


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _bot_token() -> str:
    return os.environ.get('DISCORD_TOKEN', '')


def _discord_get(path: str):
    """GET from Discord REST API using bot token."""
    try:
        r = requests.get(f'{DISCORD_API}{path}',
                         headers={'Authorization': f'Bot {_bot_token()}'},
                         timeout=5)
        return r.json() if r.ok else None
    except Exception:
        return None


def _get_guilds():
    """Return list of guilds the bot is in, enriched with DB config."""
    all_guild_cfgs = db.get_all_guilds()
    guilds = []
    for cfg in all_guild_cfgs:
        info = _discord_get(f'/guilds/{cfg["guild_id"]}')
        guilds.append({
            **cfg,
            'name': info.get('name', f'Guild {cfg["guild_id"]}') if info else f'Guild {cfg["guild_id"]}',
            'icon': info.get('icon') if info else None,
        })
    return guilds


def _guild_icon_url(guild_id, icon_hash):
    if icon_hash:
        return f'https://cdn.discordapp.com/icons/{guild_id}/{icon_hash}.png'
    return None


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


def _fmt_dt(dt_str):
    if not dt_str:
        return '—'
    try:
        dt = datetime.fromisoformat(dt_str)
        return dt.strftime('%d.%m.%Y %H:%M')
    except Exception:
        return dt_str


app.jinja_env.filters['fmtdt'] = _fmt_dt
app.jinja_env.filters['round2'] = lambda x: round(float(x or 0), 2)


# ─── Auth ─────────────────────────────────────────────────────────────────────

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        pwd = request.form.get('password', '')
        correct = os.environ.get('DASHBOARD_PASSWORD', 'admin')
        if pwd == correct:
            session['logged_in'] = True
            return redirect(url_for('index'))
        flash('Nieprawidłowe hasło.', 'danger')
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


# ─── Index ────────────────────────────────────────────────────────────────────

@app.route('/')
@login_required
def index():
    guilds = _get_guilds()
    if len(guilds) == 1:
        return redirect(url_for('guild_overview', guild_id=guilds[0]['guild_id']))
    return render_template('index.html', guilds=guilds)


@app.route('/guild/<int:guild_id>')
@login_required
def guild_overview(guild_id: int):
    cfg = db.ensure_guild(guild_id)
    info = _discord_get(f'/guilds/{guild_id}')
    guild_name = info.get('name', str(guild_id)) if info else str(guild_id)
    icon = info.get('icon') if info else None

    stats = db.get_guild_stats(guild_id)
    top = db.get_leaderboard(guild_id, limit=5)
    recent_tx = db.get_all_transactions(guild_id, limit=10)
    active = db.get_all_users(guild_id)
    active = [u for u in active if u['is_clocked_in']]

    return render_template('guild.html',
                           guild_id=guild_id,
                           guild_name=guild_name,
                           icon_url=_guild_icon_url(guild_id, icon),
                           stats=stats,
                           top=top,
                           recent_tx=recent_tx,
                           active_now=active)


# ─── Users ────────────────────────────────────────────────────────────────────

@app.route('/guild/<int:guild_id>/users')
@login_required
def users_list(guild_id: int):
    db.ensure_guild(guild_id)
    info = _discord_get(f'/guilds/{guild_id}')
    guild_name = info.get('name', str(guild_id)) if info else str(guild_id)
    users = db.get_all_users(guild_id)
    return render_template('users.html',
                           guild_id=guild_id,
                           guild_name=guild_name,
                           users=users)


@app.route('/guild/<int:guild_id>/users/<int:user_id>')
@login_required
def user_detail(guild_id: int, user_id: int):
    db.ensure_guild(guild_id)
    db.ensure_user(user_id, guild_id)
    info = _discord_get(f'/guilds/{guild_id}')
    guild_name = info.get('name', str(guild_id)) if info else str(guild_id)

    user = db.get_user(user_id, guild_id)
    auto_rank = db.get_user_auto_rank(user_id, guild_id)
    specials  = db.get_user_special_ranks(user_id, guild_id)
    sessions  = db.get_user_sessions(user_id, guild_id, limit=20)
    txs       = db.get_user_transactions(user_id, guild_id, limit=20)
    all_special_ranks = db.get_ranks(guild_id, special_only=True)

    # Try to get Discord member info
    member_info = _discord_get(f'/guilds/{guild_id}/members/{user_id}')
    avatar_url = None
    if member_info and member_info.get('user'):
        u = member_info['user']
        avatar_url = f'https://cdn.discordapp.com/avatars/{user_id}/{u["avatar"]}.png' if u.get('avatar') else None

    return render_template('user_detail.html',
                           guild_id=guild_id,
                           guild_name=guild_name,
                           user=user,
                           user_id=user_id,
                           auto_rank=auto_rank,
                           specials=specials,
                           sessions=sessions,
                           txs=txs,
                           all_special_ranks=all_special_ranks,
                           avatar_url=avatar_url)


@app.route('/guild/<int:guild_id>/users/<int:user_id>/addpoints', methods=['POST'])
@login_required
def add_points_action(guild_id: int, user_id: int):
    pts  = float(request.form.get('points', 0))
    note = request.form.get('note', 'Dashboard')
    op   = request.form.get('operation', 'add')
    if op == 'subtract':
        pts = -pts
    db.ensure_user(user_id, guild_id)
    db.add_points(user_id, guild_id, pts, note=note,
                  transaction_type='manual', assigned_by=0)
    flash(f'Punkty zaktualizowane! Zmiana: {pts:+.1f}', 'success')
    return redirect(url_for('user_detail', guild_id=guild_id, user_id=user_id))


@app.route('/guild/<int:guild_id>/users/<int:user_id>/setpoints', methods=['POST'])
@login_required
def set_points_action(guild_id: int, user_id: int):
    pts  = float(request.form.get('points', 0))
    note = request.form.get('note', 'Dashboard – ręczne ustawienie')
    db.ensure_user(user_id, guild_id)
    db.set_points(user_id, guild_id, pts, note=note, assigned_by=0)
    flash(f'Ustawiono {pts:.1f} punktów.', 'success')
    return redirect(url_for('user_detail', guild_id=guild_id, user_id=user_id))


@app.route('/guild/<int:guild_id>/users/<int:user_id>/ban', methods=['POST'])
@login_required
def ban_user(guild_id: int, user_id: int):
    db.update_user(user_id, guild_id, is_banned=1)
    flash('Użytkownik zablokowany na liście rankingowej.', 'warning')
    return redirect(url_for('user_detail', guild_id=guild_id, user_id=user_id))


@app.route('/guild/<int:guild_id>/users/<int:user_id>/unban', methods=['POST'])
@login_required
def unban_user(guild_id: int, user_id: int):
    db.update_user(user_id, guild_id, is_banned=0)
    flash('Użytkownik odblokowany na liście rankingowej.', 'success')
    return redirect(url_for('user_detail', guild_id=guild_id, user_id=user_id))


@app.route('/guild/<int:guild_id>/users/<int:user_id>/reset', methods=['POST'])
@login_required
def reset_user_action(guild_id: int, user_id: int):
    db.reset_user(user_id, guild_id)
    flash('Dane użytkownika zostały zresetowane.', 'warning')
    return redirect(url_for('user_detail', guild_id=guild_id, user_id=user_id))


@app.route('/guild/<int:guild_id>/users/<int:user_id>/giverank', methods=['POST'])
@login_required
def give_rank_action(guild_id: int, user_id: int):
    rank_id = int(request.form.get('rank_id', 0))
    note    = request.form.get('note', '')
    db.ensure_user(user_id, guild_id)
    ok = db.give_special_rank(user_id, guild_id, rank_id, assigned_by=0, note=note)
    if ok:
        flash('Ranga specjalna nadana.', 'success')
    else:
        flash('Użytkownik już posiada tę rangę.', 'warning')
    return redirect(url_for('user_detail', guild_id=guild_id, user_id=user_id))


@app.route('/guild/<int:guild_id>/users/<int:user_id>/takerank/<int:rank_id>', methods=['POST'])
@login_required
def take_rank_action(guild_id: int, user_id: int, rank_id: int):
    db.remove_special_rank(user_id, guild_id, rank_id)
    flash('Ranga specjalna odebrana.', 'warning')
    return redirect(url_for('user_detail', guild_id=guild_id, user_id=user_id))


# ─── Ranks ────────────────────────────────────────────────────────────────────

@app.route('/guild/<int:guild_id>/ranks')
@login_required
def ranks_page(guild_id: int):
    db.ensure_guild(guild_id)
    info = _discord_get(f'/guilds/{guild_id}')
    guild_name = info.get('name', str(guild_id)) if info else str(guild_id)
    ranks = db.get_ranks(guild_id)
    # Fetch guild roles for linking
    guild_roles = _discord_get(f'/guilds/{guild_id}/roles') or []
    return render_template('ranks.html',
                           guild_id=guild_id,
                           guild_name=guild_name,
                           ranks=ranks,
                           guild_roles=guild_roles)


@app.route('/guild/<int:guild_id>/ranks/create', methods=['POST'])
@login_required
def create_rank_action(guild_id: int):
    name      = request.form.get('name', '').strip()
    is_special = request.form.get('is_special') == '1'
    req_pts   = float(request.form.get('required_points', 0)) if not is_special else 0
    icon      = request.form.get('icon', '⭐').strip() or '⭐'
    color     = request.form.get('color', '#7289da').strip() or '#7289da'
    desc      = request.form.get('description', '').strip()
    role_id   = request.form.get('role_id', '').strip()
    role_id   = int(role_id) if role_id.isdigit() else None

    if not name:
        flash('Nazwa rangi jest wymagana.', 'danger')
        return redirect(url_for('ranks_page', guild_id=guild_id))

    if db.get_rank_by_name(guild_id, name):
        flash(f'Ranga "{name}" już istnieje.', 'danger')
        return redirect(url_for('ranks_page', guild_id=guild_id))

    db.create_rank(guild_id, name, req_pts, role_id=role_id,
                   color=color, description=desc, icon=icon, is_special=is_special)
    flash(f'Ranga "{name}" została utworzona.', 'success')
    return redirect(url_for('ranks_page', guild_id=guild_id))


@app.route('/guild/<int:guild_id>/ranks/<int:rank_id>/edit', methods=['POST'])
@login_required
def edit_rank_action(guild_id: int, rank_id: int):
    name      = request.form.get('name', '').strip()
    req_pts   = float(request.form.get('required_points', 0))
    icon      = request.form.get('icon', '⭐').strip() or '⭐'
    color     = request.form.get('color', '#7289da').strip()
    desc      = request.form.get('description', '').strip()
    role_id   = request.form.get('role_id', '').strip()
    role_id   = int(role_id) if role_id.isdigit() else None

    db.update_rank(rank_id,
                   name=name, required_points=req_pts,
                   icon=icon, color=color, description=desc, role_id=role_id)
    flash('Ranga zaktualizowana.', 'success')
    return redirect(url_for('ranks_page', guild_id=guild_id))


@app.route('/guild/<int:guild_id>/ranks/<int:rank_id>/delete', methods=['POST'])
@login_required
def delete_rank_action(guild_id: int, rank_id: int):
    db.delete_rank(rank_id)
    flash('Ranga usunięta.', 'warning')
    return redirect(url_for('ranks_page', guild_id=guild_id))


# ─── Config ───────────────────────────────────────────────────────────────────

@app.route('/guild/<int:guild_id>/config')
@login_required
def config_page(guild_id: int):
    cfg = db.ensure_guild(guild_id)
    info = _discord_get(f'/guilds/{guild_id}')
    guild_name = info.get('name', str(guild_id)) if info else str(guild_id)
    guild_channels = _discord_get(f'/guilds/{guild_id}/channels') or []
    guild_roles    = _discord_get(f'/guilds/{guild_id}/roles') or []
    # Only text channels
    text_channels = [c for c in guild_channels if c.get('type') == 0]

    try:
        admin_role_ids = json.loads(cfg.get('admin_role_ids', '[]'))
    except Exception:
        admin_role_ids = []

    return render_template('config.html',
                           guild_id=guild_id,
                           guild_name=guild_name,
                           cfg=cfg,
                           text_channels=text_channels,
                           guild_roles=guild_roles,
                           admin_role_ids=admin_role_ids)


@app.route('/guild/<int:guild_id>/config', methods=['POST'])
@login_required
def config_save(guild_id: int):
    clock_ch  = request.form.get('clock_channel_id', '').strip()
    log_ch    = request.form.get('log_channel_id', '').strip()
    pph       = request.form.get('points_per_hour', '10').strip()
    min_mins  = request.form.get('min_clock_minutes', '5').strip()
    admin_roles_raw = request.form.getlist('admin_role_ids')

    updates = {}
    if clock_ch.isdigit():
        updates['clock_channel_id'] = int(clock_ch)
    if log_ch.isdigit():
        updates['log_channel_id'] = int(log_ch)
    try:
        updates['points_per_hour'] = float(pph)
    except ValueError:
        pass
    try:
        updates['min_clock_minutes'] = int(min_mins)
    except ValueError:
        pass

    role_ids = [int(r) for r in admin_roles_raw if r.isdigit()]
    updates['admin_role_ids'] = json.dumps(role_ids)

    if updates:
        db.update_guild(guild_id, **updates)
        flash('Konfiguracja zapisana.', 'success')
    return redirect(url_for('config_page', guild_id=guild_id))


# ─── API (JSON) ───────────────────────────────────────────────────────────────

@app.route('/api/guild/<int:guild_id>/stats')
@login_required
def api_stats(guild_id: int):
    return jsonify(db.get_guild_stats(guild_id))


@app.route('/api/guild/<int:guild_id>/leaderboard')
@login_required
def api_leaderboard(guild_id: int):
    top = db.get_leaderboard(guild_id, limit=20, include_banned=True)
    return jsonify(top)


# ─── Ping (keep-alive) ────────────────────────────────────────────────────────

@app.route('/ping')
def ping():
    return 'OK', 200

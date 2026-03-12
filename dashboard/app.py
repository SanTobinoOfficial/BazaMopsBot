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
    try:
        r = requests.post(f'{DISCORD_API}{path}',
                          headers={'Authorization': f'Bot {_tok()}',
                                   'Content-Type': 'application/json'},
                          json=payload, timeout=5)
        return r.json() if r.ok else None
    except Exception:
        return None

def _guild_info(guild_id):
    info = _dget(f'/guilds/{guild_id}')
    return info or {}

def _guild_icon(guild_id, icon_hash):
    return f'https://cdn.discordapp.com/icons/{guild_id}/{icon_hash}.png' if icon_hash else None

def login_required(f):
    @wraps(f)
    def dec(*a, **kw):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        return f(*a, **kw)
    return dec

def _fmt(dt_str):
    if not dt_str:
        return '—'
    try:
        return datetime.fromisoformat(dt_str).strftime('%d.%m.%Y %H:%M')
    except Exception:
        return dt_str

app.jinja_env.filters['fmtdt'] = _fmt
app.jinja_env.filters['r2'] = lambda x: round(float(x or 0), 2)


# ─── Auth ─────────────────────────────────────────────────────────────────────

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form.get('password') == os.environ.get('DASHBOARD_PASSWORD', 'admin'):
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
    guilds_cfg = db.get_all_guilds()
    guilds = []
    for cfg in guilds_cfg:
        info = _dget(f'/guilds/{cfg["guild_id"]}') or {}
        guilds.append({**cfg, 'name': info.get('name', str(cfg['guild_id'])),
                       'icon': info.get('icon')})
    if len(guilds) == 1:
        return redirect(url_for('guild_overview', guild_id=guilds[0]['guild_id']))
    return render_template('index.html', guilds=guilds)


# ─── Guild overview ───────────────────────────────────────────────────────────

@app.route('/guild/<int:guild_id>')
@login_required
def guild_overview(guild_id):
    db.ensure_guild(guild_id)
    info = _guild_info(guild_id)
    stats = db.get_guild_stats(guild_id)
    top = db.get_leaderboard(guild_id, limit=5)
    recent_tx = db.get_all_transactions(guild_id, limit=10)
    active = [u for u in db.get_all_users(guild_id) if u['is_clocked_in']]
    recent_warns = db.get_all_warnings(guild_id, limit=5)
    channels = _dget(f'/guilds/{guild_id}/channels') or []
    text_channels = [c for c in channels if c.get('type') == 0]
    return render_template('guild.html',
        guild_id=guild_id, guild_name=info.get('name', str(guild_id)),
        icon_url=_guild_icon(guild_id, info.get('icon')),
        stats=stats, top=top, recent_tx=recent_tx,
        active_now=active, recent_warns=recent_warns,
        text_channels=text_channels)


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
    auto_rank = db.get_user_auto_rank(user_id, guild_id)
    specials  = db.get_user_special_ranks(user_id, guild_id)
    sessions  = db.get_user_sessions(user_id, guild_id, limit=20)
    txs       = db.get_user_transactions(user_id, guild_id, limit=20)
    warns     = db.get_warnings(user_id, guild_id)
    all_special_ranks = db.get_ranks(guild_id, special_only=True)
    cfg = db.get_guild(guild_id) or {}
    member_info = _dget(f'/guilds/{guild_id}/members/{user_id}')
    avatar_url = None
    if member_info and member_info.get('user', {}).get('avatar'):
        avatar_url = f'https://cdn.discordapp.com/avatars/{user_id}/{member_info["user"]["avatar"]}.png'
    return render_template('user_detail.html',
        guild_id=guild_id, guild_name=info.get('name', str(guild_id)),
        user=user, user_id=user_id, auto_rank=auto_rank,
        specials=specials, sessions=sessions, txs=txs, warns=warns,
        all_special_ranks=all_special_ranks, avatar_url=avatar_url,
        warn_limit=cfg.get('warn_limit', 3))

@app.route('/guild/<int:guild_id>/users/<int:user_id>/addpoints', methods=['POST'])
@login_required
def add_points_action(guild_id, user_id):
    pts  = float(request.form.get('points', 0))
    note = request.form.get('note', 'Dashboard')
    if request.form.get('operation') == 'subtract':
        pts = -pts
    db.ensure_user(user_id, guild_id)
    db.add_points(user_id, guild_id, pts, note=note, transaction_type='manual', assigned_by=0)
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
    db.set_points(user_id, guild_id, pts, note=note, assigned_by=0)
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
    ok = db.give_special_rank(user_id, guild_id, rank_id, assigned_by=0, note=note)
    flash('Ranga nadana.' if ok else 'Użytkownik już posiada rangę.', 'success' if ok else 'warning')
    return redirect(url_for('user_detail', guild_id=guild_id, user_id=user_id))

@app.route('/guild/<int:guild_id>/users/<int:user_id>/takerank/<int:rank_id>', methods=['POST'])
@login_required
def take_rank_action(guild_id, user_id, rank_id):
    db.remove_special_rank(user_id, guild_id, rank_id)
    flash('Ranga odebrana.', 'warning')
    return redirect(url_for('user_detail', guild_id=guild_id, user_id=user_id))


# ─── Ranks ────────────────────────────────────────────────────────────────────

@app.route('/guild/<int:guild_id>/ranks')
@login_required
def ranks_page(guild_id):
    db.ensure_guild(guild_id)
    info = _guild_info(guild_id)
    ranks = db.get_ranks(guild_id)
    guild_roles = _dget(f'/guilds/{guild_id}/roles') or []
    return render_template('ranks.html', guild_id=guild_id,
                           guild_name=info.get('name', str(guild_id)),
                           ranks=ranks, guild_roles=guild_roles)

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
    role_id    = request.form.get('role_id', '').strip()
    role_id    = int(role_id) if role_id.isdigit() else None
    grant_raw  = request.form.getlist('grant_role_ids')
    grant_ids  = [int(r) for r in grant_raw if r.isdigit()]
    if not name:
        flash('Nazwa jest wymagana.', 'danger')
        return redirect(url_for('ranks_page', guild_id=guild_id))
    if db.get_rank_by_name(guild_id, name):
        flash(f'Ranga "{name}" już istnieje.', 'danger')
        return redirect(url_for('ranks_page', guild_id=guild_id))
    db.create_rank(guild_id, name, req_pts, role_id=role_id, color=color,
                   description=desc, icon=icon, is_special=is_special or is_owner,
                   is_owner_only=is_owner, grant_role_ids=grant_ids)
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
    role_id  = request.form.get('role_id', '').strip()
    role_id  = int(role_id) if role_id.isdigit() else None
    grant_raw = request.form.getlist('grant_role_ids')
    grant_ids = [int(r) for r in grant_raw if r.isdigit()]
    db.update_rank(rank_id, name=name, required_points=req_pts, icon=icon,
                   color=color, description=desc, role_id=role_id,
                   grant_role_ids=json.dumps(grant_ids))
    flash('Ranga zaktualizowana.', 'success')
    return redirect(url_for('ranks_page', guild_id=guild_id))

@app.route('/guild/<int:guild_id>/ranks/<int:rank_id>/delete', methods=['POST'])
@login_required
def delete_rank_action(guild_id, rank_id):
    db.delete_rank(rank_id)
    flash('Ranga usunięta.', 'warning')
    return redirect(url_for('ranks_page', guild_id=guild_id))


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
    return render_template('config.html',
        guild_id=guild_id, guild_name=info.get('name', str(guild_id)),
        cfg=cfg, text_channels=text_channels, guild_roles=guild_roles,
        admin_role_ids=admin_role_ids, schedule=schedule,
        days_pl=db.DAYS_PL)

@app.route('/guild/<int:guild_id>/config', methods=['POST'])
@login_required
def config_save(guild_id):
    updates = {}
    for field in ('clock_channel_id', 'log_channel_id', 'command_panel_channel_id'):
        v = request.form.get(field, '').strip()
        if v.isdigit():
            updates[field] = int(v)
    for field, default in (('points_per_hour', 10.0), ('min_clock_minutes', 5),
                            ('auto_clockout_hours', 12), ('warn_limit', 3)):
        v = request.form.get(field, '').strip()
        try:
            updates[field] = type(default)(v)
        except Exception:
            pass
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
    if updates:
        db.update_guild(guild_id, **updates)
        flash('Konfiguracja zapisana.', 'success')
    return redirect(url_for('config_page', guild_id=guild_id))


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
    history = db.get_announcements(guild_id, limit=20)
    return render_template('announcements.html',
        guild_id=guild_id, guild_name=info.get('name', str(guild_id)),
        text_channels=text_channels, guild_roles=guild_roles,
        history=history)

@app.route('/guild/<int:guild_id>/announcements/send', methods=['POST'])
@login_required
def send_announcement(guild_id):
    channel_id = int(request.form.get('channel_id', 0))
    title      = request.form.get('title', '').strip()
    content    = request.form.get('content', '').strip()
    is_embed   = request.form.get('is_embed') == '1'
    color_hex  = request.form.get('color', '#7289da').strip()
    ping_role  = request.form.get('ping_role', '').strip()

    if not content or not channel_id:
        flash('Treść i kanał są wymagane.', 'danger')
        return redirect(url_for('announcements_page', guild_id=guild_id))

    payload = {}
    prefix = f'<@&{ping_role}>\n' if ping_role and ping_role.isdigit() else ''

    if is_embed:
        try:
            color_int = int(color_hex.lstrip('#'), 16)
        except Exception:
            color_int = 0x7289DA
        payload = {
            'content': prefix or None,
            'embeds': [{
                'title': title or None,
                'description': content,
                'color': color_int,
                'timestamp': datetime.now().isoformat(),
                'footer': {'text': 'Ogłoszenie | System Rang'}
            }]
        }
    else:
        body = f'**{title}**\n{content}' if title else content
        payload = {'content': prefix + body}

    result = _dpost(f'/channels/{channel_id}/messages', payload)
    if result and result.get('id'):
        msg_id = int(result['id'])
        db.save_announcement(guild_id, channel_id, title, content,
                             is_embed, color_hex, 'Dashboard', msg_id)
        flash('Ogłoszenie wysłane!', 'success')
    else:
        flash('Błąd wysyłania ogłoszenia. Sprawdź uprawnienia bota.', 'danger')
    return redirect(url_for('announcements_page', guild_id=guild_id))


# ─── Logs ─────────────────────────────────────────────────────────────────────

@app.route('/guild/<int:guild_id>/logs')
@login_required
def logs_page(guild_id):
    db.ensure_guild(guild_id)
    info = _guild_info(guild_id)
    action_type = request.args.get('type', '')
    logs = db.get_action_logs(guild_id, limit=100, action_type=action_type or None)
    warns = db.get_all_warnings(guild_id, limit=50)
    txs   = db.get_all_transactions(guild_id, limit=50)
    return render_template('logs.html',
        guild_id=guild_id, guild_name=info.get('name', str(guild_id)),
        logs=logs, warns=warns, txs=txs,
        filter_type=action_type)


# ─── API ──────────────────────────────────────────────────────────────────────

@app.route('/api/guild/<int:guild_id>/stats')
@login_required
def api_stats(guild_id):
    return jsonify(db.get_guild_stats(guild_id))

@app.route('/ping')
def ping():
    return 'OK', 200

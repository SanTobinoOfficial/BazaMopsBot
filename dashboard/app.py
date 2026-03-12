import os
import io
import csv
import json
import requests
from datetime import datetime, timezone
from functools import wraps
from flask import (Flask, render_template, request, redirect,
                   url_for, session, flash, jsonify, Response)
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

app.jinja_env.filters['fmtdt']     = _fmt
app.jinja_env.filters['r2']        = lambda x: round(float(x or 0), 2)
app.jinja_env.filters['from_json'] = lambda s: json.loads(s) if s else []


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
        'title': '📋 Codzienny Apel',
        'description': (
            f'**{day_name}, {now.strftime("%d.%m.%Y")}**\n\n'
            '📌 Oznacz swoją aktywność przyciskami poniżej.\n'
            '• **Clock In** – gdy zaczynasz\n'
            '• **Clock Out** – gdy kończysz\n\n'
            f'👥 Aktywnych teraz: **{stats["active_now"]}**\n'
            f'⚠️ Ostrzeżenia (serwer): **{stats["warning_count"]}**'
        ),
        'color': 0x7289DA,
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'footer': {'text': 'System Rang • Punkty za aktywność'},
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
    auto_rank = db.get_user_auto_rank(user_id, guild_id)
    specials  = db.get_user_special_ranks(user_id, guild_id)
    sessions  = db.get_user_sessions(user_id, guild_id, limit=20)
    txs       = db.get_user_transactions(user_id, guild_id, limit=20)
    warns     = db.get_warnings(user_id, guild_id)
    all_special_ranks = db.get_ranks(guild_id, special_only=True)
    rank_history = db.get_rank_history(user_id, guild_id, limit=20)
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
        rank_history=rank_history, warn_limit=cfg.get('warn_limit', 3))

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
    return render_template('factions.html',
        guild_id=guild_id, guild_name=info.get('name', str(guild_id)),
        factions=factions, guild_roles=roles)


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
    data = {
        'guild_id': guild_id,
        'exported_at': datetime.now().isoformat(),
        'users': db.get_all_users(guild_id),
        'ranks': db.get_ranks(guild_id),
        'warnings': db.get_all_warnings(guild_id, limit=9999),
        'stats': db.get_guild_stats(guild_id),
    }
    out = json.dumps(data, ensure_ascii=False, indent=2, default=str)
    return Response(out, mimetype='application/json',
                    headers={'Content-Disposition':
                             f'attachment; filename=backup_{guild_id}_{datetime.now().strftime("%Y%m%d")}.json'})


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

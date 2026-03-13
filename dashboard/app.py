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
app.jinja_env.filters['hex_color'] = lambda x: f'#{int(x):06X}'
app.jinja_env.filters['bitand']    = lambda x, mask: int(x or 0) & int(mask)


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
        all_special_ranks=all_special_ranks, avatar_url=avatar_url,
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
    flash(f'Przypisano do frakcji {f["icon"]} {f["name"]}.' if ok else 'Błąd przypisania.', 'success' if ok else 'danger')
    return redirect(url_for('user_detail', guild_id=guild_id, user_id=user_id))

@app.route('/guild/<int:guild_id>/users/<int:user_id>/removefaction', methods=['POST'])
@login_required
def remove_faction_action(guild_id, user_id):
    ok = db.remove_faction_member(user_id, guild_id)
    flash('Usunięto z frakcji.' if ok else 'Użytkownik nie jest w żadnej frakcji.', 'success' if ok else 'warning')
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
    if not name:
        flash('Nazwa pracy jest wymagana.', 'danger')
        return redirect(url_for('jobs_page', guild_id=guild_id))
    if db.get_job_by_name(guild_id, name):
        flash(f'Praca "{name}" już istnieje.', 'danger')
        return redirect(url_for('jobs_page', guild_id=guild_id))
    db.create_job(guild_id, name, req_pts, icon=icon, color=color,
                  description=desc, role_id=role_id)
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
    role_id = int(role_id_raw) if role_id_raw.isdigit() else None
    db.update_job(job_id, name=name, icon=icon, color=color,
                  description=desc, required_points=req_pts, role_id=role_id)
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
        ('alpha-1-czat', 0), ('nu-7-czat', 0), ('planowanie', 0),
    ]),
    ('🔊-radio', [
        ('Radio Ogólne', 2), ('Radio Alpha-1', 2),
        ('Radio Nu-7', 2), ('Gabinet Króla', 2),
    ]),
    # Kategoria administracji – niewidoczna dla zwykłych użytkowników
    ('🔒-administracja', [
        ('admin-panel', 0),   # prywatny kanał komend adminowych bota
        ('logi', 0),          # logi bota (clock, rangi, ostrzeżenia)
        ('ostrzeżenia', 0),   # historia warnów i moderacji
    ]),
]

MOPS_FACTIONS = [
    {'name': 'Alpha-1', 'icon': '🔴', 'color': '#CC0000',
     'description': 'Gwardia Królewska – osobista ochrona Króla i Księcia'},
    {'name': 'Nu-7',    'icon': '🔵', 'color': '#0055FF',
     'description': 'Podstawowa jednostka wojskowa'},
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
        ('@everyone',       0,     _PV),
        ('Król',            _PVMS, 0),
        ('Książę',          _PVMS, 0),
        ('Generał',         _PVMS, 0),
        ('Military Police', _PVMS, 0),
        ('Generał Nu-7',    _PVMS, 0),
        ('Alpha-1',         _PVMS, 0),
    ],

    # ── 🔒 ADMINISTRACJA ───────────────────────────────────────────────────────
    'admin-panel': [                       # admin bot commands (addpoints, giverank…)
        ('@everyone',       0,     _PV),
        ('Król',            _PVMS, 0),
        ('Książę',          _PVMS, 0),
        ('Generał',         _PVMS, 0),
        ('Military Police', _PVMS, 0),
        ('Generał Nu-7',    _PVMS, 0),
        ('Alpha-1',         _PVMS, 0),
    ],
    'ostrzeżenia': [                       # moderation history log
        ('@everyone',       0,     _PV),
        ('Król',            _PVMS, 0),
        ('Książę',          _PVMS, 0),
        ('Generał',         _PVMS, 0),
        ('Military Police', _PVMS, 0),
        ('Generał Nu-7',    _PVMS, 0),
        ('Alpha-1',         _PVMS, 0),
    ],

    # ── ⚔️ WOJSKO ──────────────────────────────────────────────────────────────
    'wojsko-ogólne': [                     # all military (Rekrut+), hidden from civilians
        ('@everyone',    0,     _PV),
        ('Król',         _PVS,  0),
        ('Książę',       _PVS,  0),
        ('Generał',      _PVS,  0),
        ('Military Police', _PVS, 0),
        ('Generał Nu-7', _PVS,  0),
        ('Alpha-1',      _PVS,  0),
        ('Nu-7',         _PVS,  0),
        ('Kapitan',      _PVS,  0),
        ('Sierżant',     _PVS,  0),
        ('Squad Leader', _PVS,  0),
        ('Porucznik',    _PVS,  0),
        ('Szeregowy',    _PVS,  0),
        ('Rekrut',       _PVS,  0),
    ],
    'rozkazy': [                           # orders: officers write, enlisted read-only
        ('@everyone',       0,     _PV),
        ('Król',            _PVS,  0),
        ('Książę',          _PVS,  0),
        ('Generał',         _PVS,  0),
        ('Military Police', _PVS,  0),
        ('Generał Nu-7',    _PVS,  0),
        ('Alpha-1',         _PVS,  0),
        ('Nu-7',            _PVS,  0),
        ('Kapitan',         _PVS,  0),
        ('Sierżant',        _PVS,  0),
        ('Squad Leader',    _PVS,  0),
        ('Porucznik',       _PV,   0),  # read-only from Porucznik down
        ('Szeregowy',       _PV,   0),
        ('Rekrut',          _PV,   0),
    ],
    'raporty': [                           # reports: all military can write
        ('@everyone',       0,     _PV),
        ('Król',            _PVS,  0),
        ('Książę',          _PVS,  0),
        ('Generał',         _PVS,  0),
        ('Military Police', _PVS,  0),
        ('Generał Nu-7',    _PVS,  0),
        ('Alpha-1',         _PVS,  0),
        ('Nu-7',            _PVS,  0),
        ('Kapitan',         _PVS,  0),
        ('Sierżant',        _PVS,  0),
        ('Squad Leader',    _PVS,  0),
        ('Porucznik',       _PVS,  0),
        ('Szeregowy',       _PVS,  0),
        ('Rekrut',          _PVS,  0),
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
    'planowanie': [                        # officers (Porucznik+) and commanders
        ('@everyone',       0,     _PV),
        ('Król',            _PVS,  0),
        ('Książę',          _PVS,  0),
        ('Generał',         _PVS,  0),
        ('Military Police', _PVS,  0),
        ('Generał Nu-7',    _PVS,  0),
        ('Alpha-1',         _PVS,  0),
        ('Nu-7',            _PVS,  0),
        ('Kapitan',         _PVS,  0),
        ('Sierżant',        _PVS,  0),
        ('Squad Leader',    _PVS,  0),
        ('Porucznik',       _PVS,  0),
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
        ('@everyone',       0,     _PV),
        ('Król',            _PVMS, 0),
        ('Książę',          _PVMS, 0),
        ('Generał',         _PVMS, 0),
        ('Military Police', _PVMS, 0),
        ('Generał Nu-7',    _PVMS, 0),
        ('Alpha-1',         _PVMS, 0),
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

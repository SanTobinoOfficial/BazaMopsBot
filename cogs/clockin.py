import discord
from discord.ext import commands, tasks
from discord import ui
from datetime import datetime, date
import json
import asyncio
import database as db

# ─── Session embed helpers ────────────────────────────────────────────────────

def _faction_icon(guild: discord.Guild, member: discord.Member, guild_id: int) -> str:
    """Return '<icon> ' for the user's faction (explicit membership) or empty string."""
    if not member:
        return ''
    f = db.get_user_faction_membership(member.id, guild_id)
    return f'{f["faction_icon"]} ' if f else ''


def _prog_bar(current: float, next_pts: float, from_pts: float = 0,
              width: int = 10) -> str:
    """ASCII progress bar: '████░░░░░░ 30/50 pkt'"""
    span = next_pts - from_pts
    if span <= 0:
        filled = width
    else:
        filled = int(min(width, max(0, round((current - from_pts) / span * width))))
    bar = '█' * filled + '░' * (width - filled)
    return f'`{bar}` {current:.0f}/{next_pts:.0f} pkt'


async def _build_session_embed(guild: discord.Guild, cfg: dict,
                               embed_data: dict) -> discord.Embed:
    """Build the live session embed with current attendees."""
    pts_h     = cfg.get('points_per_hour', 10)
    host_id   = embed_data.get('host_id')
    co_id     = embed_data.get('co_host_id')
    ev_type   = embed_data.get('event_type') or 'Zmiana'

    host_str  = f'<@{host_id}>' if host_id else 'Automatyczny'
    co_str    = f'<@{co_id}>'   if co_id   else None

    e = discord.Embed(
        title='📋 Clock-In Session',
        description='Kliknij przycisk **✅** poniżej, aby się zalogować lub wylogować!',
        color=BLURPLE, timestamp=datetime.now())

    e.add_field(name='Default Points', value=f'**{pts_h:.0f}**', inline=True)
    e.add_field(name='Host',           value=host_str,            inline=True)
    if co_str:
        e.add_field(name='Co-host',    value=co_str,              inline=True)
    e.add_field(name='Type of event',  value=ev_type,             inline=False)

    active = [u for u in db.get_all_users(guild.id) if u['is_clocked_in']]
    if active:
        lines = []
        for i, u in enumerate(active[:20]):
            m   = guild.get_member(u['user_id'])
            fi  = _faction_icon(guild, m, guild.id)
            nm  = m.display_name if m else (u.get('display_name') or str(u['user_id']))
            lines.append(f'{i+1}. {fi}{nm}')
        if len(active) > 20:
            lines.append(f'*… i {len(active)-20} więcej*')
        e.add_field(name=f'Attendees ({len(active)})',
                    value='\n'.join(lines), inline=False)
    else:
        e.add_field(name='Attendees (0)',
                    value='No one has clocked in yet.', inline=False)

    e.set_footer(text='System Rang • Punkty za aktywność')
    return e


async def _build_finished_embed(guild: discord.Guild, cfg: dict,
                                embed_data: dict,
                                attendees: list) -> discord.Embed:
    """Build the FINISHED session embed with final attendee list."""
    pts_h   = cfg.get('points_per_hour', 10)
    host_id = embed_data.get('host_id')
    ev_type = embed_data.get('event_type') or 'Zmiana'

    e = discord.Embed(
        title='📋 Clock-In Session - FINISHED',
        description='This session has been completed and can no longer be edited.',
        color=RED, timestamp=datetime.now())

    e.add_field(name='Default Points', value=f'**{pts_h:.0f}**', inline=True)
    e.add_field(name='Host',
                value=f'<@{host_id}>' if host_id else 'Automatyczny', inline=True)
    e.add_field(name='Type of event',  value=ev_type, inline=True)

    n = len(attendees)
    if n == 0:
        e.add_field(name='Final Attendees (0)',
                    value='No one clocked in.', inline=False)
    else:
        chunk = 10
        for start in range(0, n, chunk):
            end   = min(start + chunk, n)
            label = (f'Final Attendees ({n})'
                     if n <= chunk else f'Final Attendees ({start+1}-{end})')
            lines = [f'{start+i+1}. {a["display"]} – {a["pts"]:.0f} points'
                     for i, a in enumerate(attendees[start:end])]
            e.add_field(name=label, value='\n'.join(lines), inline=False)

    e.set_footer(text='System Rang • Sesja zakończona')
    return e


async def _refresh_session_embed(guild: discord.Guild) -> None:
    """Fetch and edit today's session message with updated attendees."""
    cfg = db.get_guild(guild.id)
    if not cfg:
        return
    today      = date.today().isoformat()
    embed_data = db.get_daily_embed(guild.id, today)
    if not embed_data or embed_data.get('is_finished'):
        return
    ch = guild.get_channel(embed_data['channel_id'])
    if not ch:
        return
    try:
        msg = await ch.fetch_message(embed_data['message_id'])
        new_e = await _build_session_embed(guild, cfg, embed_data)
        await msg.edit(embed=new_e)
    except Exception:
        pass

BLURPLE = 0x7289DA
GREEN   = 0x43B581
RED     = 0xF04747
YELLOW  = 0xFAA61A
ORANGE  = 0xE67E22


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _rank_line(user_id: int, guild_id: int) -> str:
    rank = db.get_user_auto_rank(user_id, guild_id)
    special = db.get_user_special_ranks(user_id, guild_id)
    parts = []
    if rank:
        parts.append(f"{rank['icon']} {rank['name']}")
    for sr in special:
        parts.append(f"{sr['icon']} {sr['name']}")
    return ' | '.join(parts) if parts else 'Brak rangi'


async def send_log(guild: discord.Guild, embed: discord.Embed) -> None:
    cfg = db.get_guild(guild.id)
    if not cfg or not cfg.get('log_channel_id'):
        return
    ch = guild.get_channel(cfg['log_channel_id'])
    if ch:
        try:
            await ch.send(embed=embed)
        except discord.Forbidden:
            pass


def log_embed(title: str, color: int, **fields) -> discord.Embed:
    e = discord.Embed(title=title, color=color, timestamp=datetime.now())
    for name, value in fields.items():
        e.add_field(name=name, value=str(value) or '—', inline=True)
    e.set_footer(text='System Rang – Logi')
    return e


# ─── SessionClockView (new-style persistent view) ─────────────────────────────

class EditSessionModal(ui.Modal, title='✏️ Edytuj Sesję'):
    host = ui.TextInput(
        label='Host (ID użytkownika, puste = Automatyczny)',
        required=False, placeholder='np. 123456789')
    co_host = ui.TextInput(
        label='Co-host (ID użytkownika, puste = brak)',
        required=False, placeholder='np. 123456789')
    event_type = ui.TextInput(
        label='Typ wydarzenia',
        required=False, default='Zmiana',
        placeholder='np. Zmiana, Trening, Event…', max_length=80)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        today = date.today().isoformat()

        def _parse_id(val):
            v = val.strip().strip('<@!>').strip() if val else ''
            try:
                return int(v) if v else None
            except ValueError:
                return None

        host_id    = _parse_id(self.host.value)
        co_host_id = _parse_id(self.co_host.value)
        ev_type    = self.event_type.value.strip() or 'Zmiana'

        db.update_daily_embed_meta(
            interaction.guild_id, today,
            host_id=host_id, co_host_id=co_host_id, event_type=ev_type)
        await _refresh_session_embed(interaction.guild)
        await interaction.followup.send('✅ Sesja zaktualizowana!', ephemeral=True)


class SessionClockView(ui.View):
    """New-style session embed with admin controls (row 0) + toggle button (row 1)."""
    def __init__(self):
        super().__init__(timeout=None)

    async def _is_admin(self, interaction: discord.Interaction) -> bool:
        if interaction.user.guild_permissions.administrator:
            return True
        cfg = db.get_guild(interaction.guild_id) or {}
        try:
            aids = json.loads(cfg.get('admin_role_ids') or '[]')
        except Exception:
            aids = []
        return any(r.id in aids for r in interaction.user.roles)

    # ── Row 0: Admin controls ────────────────────────────────────────────────

    @ui.button(label='🗑️ Usuń', style=discord.ButtonStyle.danger,
               custom_id='mops_sess_del', row=0)
    async def btn_delete(self, interaction: discord.Interaction, _: ui.Button):
        if not await self._is_admin(interaction):
            await interaction.response.send_message('❌ Brak uprawnień.', ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            await interaction.message.delete()
        except Exception:
            pass
        await interaction.followup.send('🗑️ Embed sesji usunięty.', ephemeral=True)

    @ui.button(label='✏️ Edytuj', style=discord.ButtonStyle.secondary,
               custom_id='mops_sess_edit', row=0)
    async def btn_edit(self, interaction: discord.Interaction, _: ui.Button):
        if not await self._is_admin(interaction):
            await interaction.response.send_message('❌ Brak uprawnień.', ephemeral=True)
            return
        today = date.today().isoformat()
        ed = db.get_daily_embed(interaction.guild_id, today)
        modal = EditSessionModal()
        if ed:
            if ed.get('host_id'):
                modal.host.default = str(ed['host_id'])
            if ed.get('co_host_id'):
                modal.co_host.default = str(ed['co_host_id'])
            if ed.get('event_type'):
                modal.event_type.default = ed['event_type']
        await interaction.response.send_modal(modal)

    @ui.button(label='🏁 Zakończ', style=discord.ButtonStyle.success,
               custom_id='mops_sess_finish', row=0)
    async def btn_finish(self, interaction: discord.Interaction, _: ui.Button):
        if not await self._is_admin(interaction):
            await interaction.response.send_message('❌ Brak uprawnień.', ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        gid   = interaction.guild_id
        today = date.today().isoformat()
        cfg   = db.get_guild(gid) or {}

        # Force clock-out all active users and collect attendee data
        active = [u for u in db.get_all_users(gid) if u['is_clocked_in']]
        attendees = []
        for u in active:
            uid    = u['user_id']
            result = db.clock_out(uid, gid)
            m      = interaction.guild.get_member(uid)
            fi     = _faction_icon(interaction.guild, m, gid)
            nm     = m.display_name if m else (u.get('display_name') or str(uid))
            pts    = result['points_earned'] if result else 0
            # streak bonus
            if result and pts > 0:
                bonus_pct = cfg.get('streak_bonus_pct', 5.0) or 0.0
                streak    = db.update_streak(uid, gid, today)
                if streak > 1 and bonus_pct > 0:
                    bonus = round(pts * (bonus_pct / 100) * streak, 2)
                    db.add_points(uid, gid, bonus,
                                  note=f'Bonus serii {streak} dni',
                                  transaction_type='streak_bonus')
                    pts += bonus
            attendees.append({'display': f'{fi}{nm}', 'pts': pts})

        embed_data = db.get_daily_embed(gid, today) or {}
        finished_e = await _build_finished_embed(
            interaction.guild, cfg, embed_data, attendees)

        try:
            await interaction.message.edit(embed=finished_e, view=None)
        except Exception:
            pass

        db.update_daily_embed_meta(gid, today,
                                   is_finished=1,
                                   finished_at=datetime.now().isoformat())
        db.log_action(gid, 'session_finish', actor_id=interaction.user.id,
                      details={'attendees': len(attendees)})
        await send_log(interaction.guild, log_embed(
            '🏁 Sesja Zakończona', GREEN,
            Uczestnicy=str(len(attendees)),
            Przez=interaction.user.mention))
        await interaction.followup.send(
            f'✅ Sesja zakończona! Wylogowano **{len(attendees)}** uczestników.',
            ephemeral=True)

    # ── Row 1: Clock In/Out toggle ────────────────────────────────────────────

    @ui.button(label='✅ Clock In / Clock Out', style=discord.ButtonStyle.success,
               custom_id='mops_clock_toggle', row=1)
    async def btn_toggle(self, interaction: discord.Interaction, _: ui.Button):
        await interaction.response.defer(ephemeral=True)
        gid, uid = interaction.guild_id, interaction.user.id
        db.ensure_guild(gid)
        db.ensure_user(uid, gid, str(interaction.user), interaction.user.display_name)

        user = db.get_user(uid, gid)
        cfg  = db.get_guild(gid) or {}

        if not user or not user['is_clocked_in']:
            # ── CLOCK IN ──────────────────────────────────────────────────────
            cooldown_min = cfg.get('clock_cooldown_min', 0) or 0
            if cooldown_min > 0:
                last_end = db.get_last_session_end(uid, gid)
                if last_end:
                    mins_since = (datetime.now() - last_end).total_seconds() / 60
                    if mins_since < cooldown_min:
                        remaining = int(cooldown_min - mins_since) + 1
                        e = discord.Embed(
                            description=(f'⏳ Musisz odczekać **{remaining} min** '
                                         f'przed kolejnym Clock In.'),
                            color=YELLOW)
                        await interaction.followup.send(embed=e, ephemeral=True)
                        return

            sess = db.clock_in(uid, gid)
            if not sess:
                await interaction.followup.send('❌ Błąd przy logowaniu.', ephemeral=True)
                return

            now = datetime.now()
            fi  = _faction_icon(interaction.guild, interaction.user, gid)
            e   = discord.Embed(title='✅ Zalogowano!', color=GREEN, timestamp=now)
            e.set_thumbnail(url=interaction.user.display_avatar.url)
            e.add_field(name='👤 Użytkownik',
                        value=f'{fi}{interaction.user.display_name}', inline=True)
            e.add_field(name='🕐 Godzina', value=now.strftime('%H:%M:%S'), inline=True)
            e.add_field(name='⭐ Ranga', value=_rank_line(uid, gid), inline=False)
            e.set_footer(text='Pamiętaj o Clock Out na koniec aktywności!')
            await interaction.followup.send(embed=e, ephemeral=True)

            db.log_action(gid, 'clock_in', user_id=uid,
                          details={'time': now.isoformat(),
                                   'display_name': interaction.user.display_name})
            await send_log(interaction.guild, log_embed(
                '🟢 Clock In', GREEN,
                Użytkownik=f'{interaction.user.mention} ({interaction.user.display_name})',
                Godzina=now.strftime('%H:%M:%S'), Data=now.strftime('%d.%m.%Y')))

        else:
            # ── CLOCK OUT ─────────────────────────────────────────────────────
            result = db.clock_out(uid, gid)
            if not result:
                await interaction.followup.send('❌ Błąd przy wylogowaniu.', ephemeral=True)
                return

            h, m     = result['hours'], result['minutes']
            pts      = result['points_earned']
            ci, co   = result['clock_in_time'], result['clock_out_time']
            time_str = f'{int(h)}h {int(m % 60)}min' if h >= 1 else f'{int(m)}min'

            today_str    = date.today().isoformat()
            streak       = db.update_streak(uid, gid, today_str)
            bonus_pct    = cfg.get('streak_bonus_pct', 5.0) or 0.0
            streak_bonus = 0.0
            streak_msg   = ''
            if pts > 0 and streak > 1 and bonus_pct > 0:
                streak_bonus = round(pts * (bonus_pct / 100) * streak, 2)
                db.add_points(uid, gid, streak_bonus,
                              note=f'Bonus serii {streak} dni (+{bonus_pct}%/dzień)',
                              transaction_type='streak_bonus')
                streak_msg = f'\n🔥 Bonus serii ×{streak} (+{streak_bonus:.1f} pkt)'

            fresh = db.get_user(uid, gid)
            fi    = _faction_icon(interaction.guild, interaction.user, gid)

            e = discord.Embed(title='👋 Wylogowano!', color=BLURPLE, timestamp=co)
            e.set_thumbnail(url=interaction.user.display_avatar.url)
            e.add_field(name='👤 Użytkownik',
                        value=f'{fi}{interaction.user.display_name}', inline=True)
            e.add_field(name='⏱️ Czas',   value=time_str, inline=True)
            pts_text = (f'+**{pts:.1f}** pkt{streak_msg}'
                        if pts > 0 else '*(zbyt krótka sesja)*')
            e.add_field(name='💰 Punkty', value=pts_text, inline=True)
            e.add_field(name='🕐 Clock In',  value=ci.strftime('%H:%M'), inline=True)
            e.add_field(name='🕑 Clock Out', value=co.strftime('%H:%M'), inline=True)
            e.add_field(name='⭐ Ranga',     value=_rank_line(uid, gid), inline=True)
            if streak > 1:
                e.add_field(name='🔥 Seria', value=f'{streak} dni z rzędu!', inline=True)
            # Progress bar to next rank
            if fresh:
                next_r = db.get_user_next_rank(uid, gid)
                if next_r:
                    cur_rank = db.get_user_auto_rank(uid, gid)
                    from_pts = cur_rank['required_points'] if cur_rank else 0
                    bar = _prog_bar(fresh['points'], next_r['required_points'], from_pts)
                    e.add_field(name=f'Postęp → {next_r["icon"]} {next_r["name"]}',
                                value=bar, inline=False)
                e.set_footer(text=f'Łączne punkty: {fresh["points"]:.1f} pkt')
            await interaction.followup.send(embed=e, ephemeral=True)

            db.log_action(gid, 'clock_out', user_id=uid,
                          details={'hours': round(h, 2), 'points': pts,
                                   'streak_bonus': streak_bonus,
                                   'display_name': interaction.user.display_name})
            await send_log(interaction.guild, log_embed(
                '🔴 Clock Out', RED,
                Użytkownik=f'{interaction.user.mention} ({interaction.user.display_name})',
                Czas=time_str,
                Punkty=f'+{pts:.1f}' + (f' +{streak_bonus:.1f}(seria)' if streak_bonus else ''),
                **{'Łącznie pkt': f'{fresh["points"]:.1f}' if fresh else '?'}))

            pts_before = (fresh['points'] - pts - streak_bonus) if fresh else 0
            await _check_rank_up(interaction, uid, gid, pts_before,
                                 fresh['points'] if fresh else 0)
            if cfg.get('dm_notifications', 1):
                await _check_near_rank_dm(interaction, uid, gid,
                                          fresh['points'] if fresh else 0)

        # Refresh the session embed attendee list
        await _refresh_session_embed(interaction.guild)


# ─── Persistent ClockView (backward compat) ────────────────────────────────────

class ClockView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label='🟢 Clock In', style=discord.ButtonStyle.success,
               custom_id='mops_clock_in')
    async def clock_in(self, interaction: discord.Interaction, _: ui.Button):
        await interaction.response.defer(ephemeral=True)
        gid, uid = interaction.guild_id, interaction.user.id
        db.ensure_guild(gid)
        db.ensure_user(uid, gid, str(interaction.user), interaction.user.display_name)

        user = db.get_user(uid, gid)
        if user and user['is_clocked_in']:
            since = datetime.fromisoformat(user['clock_in_time'])
            e = discord.Embed(
                description=(f'⚠️ Już jesteś zalogowany od **{since.strftime("%H:%M")}**.\n'
                             f'Użyj **Clock Out** aby się wylogować.'),
                color=YELLOW)
            await interaction.followup.send(embed=e, ephemeral=True)
            return

        # ── Cooldown check ─────────────────────────────────────────────────
        cfg = db.get_guild(gid) or {}
        cooldown_min = cfg.get('clock_cooldown_min', 0) or 0
        if cooldown_min > 0:
            last_end = db.get_last_session_end(uid, gid)
            if last_end:
                mins_since = (datetime.now() - last_end).total_seconds() / 60
                if mins_since < cooldown_min:
                    remaining = int(cooldown_min - mins_since) + 1
                    e = discord.Embed(
                        description=(f'⏳ Musisz odczekać **{remaining} min** '
                                     f'przed kolejnym Clock In.\n'
                                     f'(Cooldown: {cooldown_min} min)'),
                        color=YELLOW)
                    await interaction.followup.send(embed=e, ephemeral=True)
                    return

        sess = db.clock_in(uid, gid)
        if not sess:
            await interaction.followup.send('❌ Błąd przy logowaniu.', ephemeral=True)
            return

        now = datetime.now()
        e = discord.Embed(title='✅ Zalogowano!', color=GREEN, timestamp=now)
        e.set_thumbnail(url=interaction.user.display_avatar.url)
        e.add_field(name='👤 Użytkownik', value=interaction.user.display_name, inline=True)
        e.add_field(name='🕐 Godzina', value=now.strftime('%H:%M:%S'), inline=True)
        e.add_field(name='⭐ Ranga', value=_rank_line(uid, gid), inline=False)
        e.set_footer(text='Pamiętaj o Clock Out na koniec aktywności!')
        await interaction.followup.send(embed=e, ephemeral=True)

        db.log_action(gid, 'clock_in', user_id=uid,
                      details={'time': now.isoformat(),
                               'display_name': interaction.user.display_name})
        await send_log(interaction.guild, log_embed(
            '🟢 Clock In', GREEN,
            Użytkownik=f'{interaction.user.mention} ({interaction.user.display_name})',
            Godzina=now.strftime('%H:%M:%S'),
            Data=now.strftime('%d.%m.%Y')))

    @ui.button(label='🔴 Clock Out', style=discord.ButtonStyle.danger,
               custom_id='mops_clock_out')
    async def clock_out(self, interaction: discord.Interaction, _: ui.Button):
        await interaction.response.defer(ephemeral=True)
        gid, uid = interaction.guild_id, interaction.user.id
        db.ensure_guild(gid)
        db.ensure_user(uid, gid, str(interaction.user), interaction.user.display_name)

        user = db.get_user(uid, gid)
        if not user or not user['is_clocked_in']:
            e = discord.Embed(
                description='⚠️ Nie jesteś zalogowany. Kliknij **Clock In** aby rozpocząć.',
                color=YELLOW)
            await interaction.followup.send(embed=e, ephemeral=True)
            return

        result = db.clock_out(uid, gid)
        if not result:
            await interaction.followup.send('❌ Błąd przy wylogowaniu.', ephemeral=True)
            return

        h    = result['hours']
        m    = result['minutes']
        pts  = result['points_earned']
        ci   = result['clock_in_time']
        co   = result['clock_out_time']
        time_str = f'{int(h)}h {int(m % 60)}min' if h >= 1 else f'{int(m)}min'

        # ── Streak update + bonus ──────────────────────────────────────────
        cfg = db.get_guild(gid) or {}
        today_str = date.today().isoformat()
        streak = db.update_streak(uid, gid, today_str)
        bonus_pct = cfg.get('streak_bonus_pct', 5.0) or 0.0
        streak_bonus = 0.0
        streak_bonus_msg = ''
        if pts > 0 and streak > 1 and bonus_pct > 0:
            streak_bonus = round(pts * (bonus_pct / 100) * streak, 2)
            new_pts = db.add_points(uid, gid, streak_bonus,
                                    note=f'Bonus serii {streak} dni (+{bonus_pct}%/dzień)',
                                    transaction_type='streak_bonus')
            streak_bonus_msg = f'\n🔥 Bonus serii ×{streak} (+{streak_bonus:.1f} pkt)'
        else:
            new_pts = db.get_user(uid, gid)['points'] if db.get_user(uid, gid) else 0

        fresh_user = db.get_user(uid, gid)

        e = discord.Embed(title='👋 Wylogowano!', color=BLURPLE, timestamp=co)
        e.set_thumbnail(url=interaction.user.display_avatar.url)
        e.add_field(name='👤 Użytkownik', value=interaction.user.display_name, inline=True)
        e.add_field(name='⏱️ Czas', value=time_str, inline=True)
        pts_text = (f'+**{pts:.1f}** pkt{streak_bonus_msg}'
                    if pts > 0 else '*(zbyt krótka sesja)*')
        e.add_field(name='💰 Punkty', value=pts_text, inline=True)
        e.add_field(name='🕐 Clock In', value=ci.strftime('%H:%M'), inline=True)
        e.add_field(name='🕑 Clock Out', value=co.strftime('%H:%M'), inline=True)
        e.add_field(name='⭐ Ranga', value=_rank_line(uid, gid), inline=True)
        if streak > 1:
            e.add_field(name='🔥 Seria', value=f'{streak} dni z rzędu!', inline=True)
        if fresh_user:
            next_r = db.get_user_next_rank(uid, gid)
            if next_r:
                cur_rank = db.get_user_auto_rank(uid, gid)
                from_pts = cur_rank['required_points'] if cur_rank else 0
                bar = _prog_bar(fresh_user['points'], next_r['required_points'], from_pts)
                e.add_field(name=f'Postęp → {next_r["icon"]} {next_r["name"]}',
                            value=bar, inline=False)
            e.set_footer(text=f'Łączne punkty: {fresh_user["points"]:.1f} pkt')
        await interaction.followup.send(embed=e, ephemeral=True)

        db.log_action(gid, 'clock_out', user_id=uid,
                      details={'hours': round(h, 2), 'points': pts,
                               'streak_bonus': streak_bonus,
                               'display_name': interaction.user.display_name})
        await send_log(interaction.guild, log_embed(
            '🔴 Clock Out', RED,
            Użytkownik=f'{interaction.user.mention} ({interaction.user.display_name})',
            Czas=time_str,
            Punkty=f'+{pts:.1f}' + (f' +{streak_bonus:.1f} (seria)' if streak_bonus else ''),
            **{'Łącznie pkt': f'{fresh_user["points"]:.1f}' if fresh_user else '?'}))

        pts_before = (fresh_user['points'] - pts - streak_bonus) if fresh_user else 0
        await _check_rank_up(interaction, uid, gid, pts_before,
                             fresh_user['points'] if fresh_user else 0)

        # ── Near-rank DM notification ──────────────────────────────────────
        if cfg.get('dm_notifications', 1):
            await _check_near_rank_dm(interaction, uid, gid,
                                      fresh_user['points'] if fresh_user else 0)


async def _check_rank_up(interaction: discord.Interaction,
                          uid: int, gid: int,
                          pts_before: float, pts_after: float):
    # Use faction-aware rank lookup with points_override
    rank_before = db.get_user_auto_rank(uid, gid, points_override=pts_before)
    rank_after  = db.get_user_auto_rank(uid, gid, points_override=pts_after)

    if rank_after and (not rank_before or rank_after['id'] != rank_before['id']):
        try:
            color = int(rank_after['color'].lstrip('#'), 16)
        except Exception:
            color = GREEN

        # Save rank history
        db.add_rank_history(uid, gid, rank_after['name'], 'gained',
                            pts_after, rank_id=rank_after['id'])

        e = discord.Embed(
            title='🎉 Awans na nową rangę!',
            description=(f'{interaction.user.mention} awansował(a) na\n'
                         f'**{rank_after["icon"]} {rank_after["name"]}**!'),
            color=color)
        e.set_thumbnail(url=interaction.user.display_avatar.url)
        # Add progress bar to next rank if available
        next_r = db.get_user_next_rank(uid, gid)
        if next_r:
            bar = _prog_bar(pts_after, next_r['required_points'],
                            rank_after['required_points'])
            e.add_field(name=f'Do {next_r["icon"]} {next_r["name"]}',
                        value=bar, inline=False)
        e.set_footer(text=f'Punkty: {pts_after:.1f}')

        cfg = db.get_guild(gid)
        ch_id = cfg.get('clock_channel_id') if cfg else None
        ch = interaction.guild.get_channel(ch_id) if ch_id else None
        if ch:
            try:
                await ch.send(content=interaction.user.mention, embed=e)
            except discord.Forbidden:
                pass

        # Role swap
        if rank_after.get('role_id'):
            role = interaction.guild.get_role(rank_after['role_id'])
            member = interaction.guild.get_member(uid)
            if role and member:
                try:
                    if rank_before and rank_before.get('role_id'):
                        old = interaction.guild.get_role(rank_before['role_id'])
                        if old and old in member.roles:
                            await member.remove_roles(old, reason='Awans rangi')
                    await member.add_roles(role, reason=f'Awans: {rank_after["name"]}')
                except discord.Forbidden:
                    pass

        db.log_action(gid, 'rank_up', user_id=uid,
                      details={'rank': rank_after['name'], 'points': pts_after})
        await send_log(interaction.guild, log_embed(
            '🎉 Awans Rangi', color,
            Użytkownik=interaction.user.mention,
            **{'Nowa ranga': f'{rank_after["icon"]} {rank_after["name"]}'},
            Punkty=f'{pts_after:.1f}'))

        # DM on rank-up
        cfg2 = db.get_guild(gid) or {}
        if cfg2.get('dm_notifications', 1):
            member = interaction.guild.get_member(uid)
            if member:
                try:
                    dm_e = discord.Embed(
                        title='🎉 Awans na nową rangę!',
                        description=(f'Gratulacje! Awansowałeś na serwerze '
                                     f'**{interaction.guild.name}**!\n\n'
                                     f'**Nowa ranga:** {rank_after["icon"]} {rank_after["name"]}\n'
                                     f'**Punkty:** {pts_after:.1f}'),
                        color=color)
                    await member.send(embed=dm_e)
                except Exception:
                    pass


async def _check_near_rank_dm(interaction: discord.Interaction,
                               uid: int, gid: int, pts: float):
    """Send DM when user is within 10% of the next rank (faction-aware)."""
    next_rank = db.get_user_next_rank(uid, gid)
    if not next_rank:
        return
    needed = next_rank['required_points'] - pts
    threshold = next_rank['required_points'] * 0.10   # within 10%
    if needed <= threshold:
        member = interaction.guild.get_member(uid)
        if member:
            try:
                cur_rank = db.get_user_auto_rank(uid, gid)
                from_pts = cur_rank['required_points'] if cur_rank else 0
                bar = _prog_bar(pts, next_rank['required_points'], from_pts)
                await member.send(embed=discord.Embed(
                    title='⭐ Blisko nowej rangi!',
                    description=(f'Brakuje Ci tylko **{needed:.1f} pkt** do rangi\n'
                                 f'**{next_rank["icon"]} {next_rank["name"]}**!\n\n'
                                 f'{bar}\n\n'
                                 f'*Kontynuuj aktywność na **{interaction.guild.name}**!*'),
                    color=YELLOW))
            except Exception:
                pass


# ─── Main Cog ─────────────────────────────────────────────────────────────────

class ClockInCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._last_embed_check: dict = {}   # guild_id → "date:HH:MM" key
        self._ann_last_check: str = ''      # last minute checked for announcements
        self.schedule_task.start()
        self.anti_cheat_task.start()
        self.scheduled_announcements_task.start()

    def cog_unload(self):
        self.schedule_task.cancel()
        self.anti_cheat_task.cancel()
        self.scheduled_announcements_task.cancel()

    # ── Per-day embed schedule (runs every minute) ─────────────────────────

    @tasks.loop(minutes=1)
    async def schedule_task(self):
        now = datetime.now()
        current_day = str(now.weekday())          # "0"=Mon … "6"=Sun
        current_hm  = f'{now.hour:02d}:{now.minute:02d}'
        today       = date.today().isoformat()

        for guild in self.bot.guilds:
            cfg = db.get_guild(guild.id)
            if not cfg or not cfg.get('clock_channel_id'):
                continue
            schedule = db.get_embed_schedule(guild.id)
            day_cfg  = schedule.get(current_day, {})
            if not day_cfg.get('enabled', True):
                continue
            sched_hm = f'{day_cfg.get("hour", 0):02d}:{day_cfg.get("minute", 0):02d}'
            if current_hm != sched_hm:
                continue
            key = f'{guild.id}:{today}:{sched_hm}'
            if self._last_embed_check.get(guild.id) == key:
                continue
            self._last_embed_check[guild.id] = key
            if db.get_daily_embed(guild.id, today):
                continue
            ch = guild.get_channel(cfg['clock_channel_id'])
            if ch:
                await self._send_daily_embed(ch, guild.id, today)

    @schedule_task.before_loop
    async def before_schedule(self):
        await self.bot.wait_until_ready()

    async def _send_daily_embed(self, channel: discord.TextChannel,
                                 guild_id: int, today: str):
        cfg        = db.get_guild(guild_id) or {}
        embed_data = db.get_daily_embed(guild_id, today) or {}
        # If no metadata saved yet, defaults are used (Automatyczny / Zmiana)
        embed_obj  = await _build_session_embed(channel.guild, cfg, embed_data)
        try:
            msg = await channel.send(embed=embed_obj, view=SessionClockView())
            db.save_daily_embed(guild_id, channel.id, msg.id, today)
        except discord.Forbidden:
            pass

    # ── Scheduled announcements (runs every minute) ────────────────────────

    @tasks.loop(minutes=1)
    async def scheduled_announcements_task(self):
        now_min = datetime.now().strftime('%Y-%m-%d %H:%M')
        if self._ann_last_check == now_min:
            return   # Already checked this minute
        self._ann_last_check = now_min

        due = db.get_due_announcements()
        for ann in due:
            guild = self.bot.get_guild(ann['guild_id'])
            if not guild:
                db.mark_announcement_sent(ann['id'])
                continue
            channel = guild.get_channel(ann['channel_id'])
            if not channel:
                db.mark_announcement_sent(ann['id'])
                continue
            try:
                if ann.get('is_embed'):
                    color_int = BLURPLE
                    try:
                        color_int = int((ann.get('color') or '#7289da').lstrip('#'), 16)
                    except Exception:
                        pass
                    embed = discord.Embed(
                        title=ann.get('title') or '',
                        description=ann.get('content') or '',
                        color=color_int,
                        timestamp=datetime.now())
                    embed.set_footer(text=f'Zaplanowane ogłoszenie • {ann.get("sent_by", "Dashboard")}')
                    msg = await channel.send(embed=embed)
                else:
                    msg = await channel.send(content=ann.get('content') or '')
                db.mark_announcement_sent(ann['id'], message_id=msg.id)
            except Exception:
                db.mark_announcement_sent(ann['id'])

    @scheduled_announcements_task.before_loop
    async def before_announcements(self):
        await self.bot.wait_until_ready()

    # ── Anti-cheat (runs every 30 min) ────────────────────────────────────

    @tasks.loop(minutes=30)
    async def anti_cheat_task(self):
        for guild in self.bot.guilds:
            cfg = db.get_guild(guild.id)
            if not cfg:
                continue
            max_hours  = cfg.get('auto_clockout_hours', 12)
            warn_limit = cfg.get('warn_limit', 3)
            suspicious = db.get_suspicious_users(guild.id, max_hours)

            for u in suspicious:
                uid = u['user_id']
                db.force_clock_out(uid, guild.id)
                ci_str = u.get('clock_in_time', '')
                try:
                    ci_dt   = datetime.fromisoformat(ci_str)
                    elapsed = round((datetime.now() - ci_dt).total_seconds() / 3600, 1)
                except Exception:
                    elapsed = max_hours

                db.add_warning(
                    uid, guild.id,
                    reason=f'Auto-cheat: zalogowany {elapsed}h bez Clock Out (limit {max_hours}h)',
                    warned_by=None, is_auto=True)
                warn_count = db.get_warning_count(uid, guild.id)
                db.log_action(guild.id, 'anticheat', user_id=uid,
                              details={'hours': elapsed, 'warn_count': warn_count,
                                       'warn_limit': warn_limit})

                if warn_count >= warn_limit:
                    db.update_user(uid, guild.id, is_banned=1)
                    db.log_action(guild.id, 'auto_ban', user_id=uid,
                                  details={'reason': 'Przekroczono limit ostrzeżeń (anti-cheat)'})

                member = guild.get_member(uid)
                name    = member.display_name if member else u.get('display_name', str(uid))
                mention = member.mention if member else f'ID:{uid}'
                status_txt = (f'🔨 **Auto-ban** po {warn_limit} ostrzeżeniach'
                              if warn_count >= warn_limit
                              else f'Ostrzeżenie **#{warn_count}/{warn_limit}**')

                e = discord.Embed(title='🤖 Anti-Cheat – Wykrycie',
                                  color=ORANGE, timestamp=datetime.now())
                e.add_field(name='👤 Użytkownik', value=f'{mention} ({name})', inline=True)
                e.add_field(name='⏱️ Czas zalogowania', value=f'{elapsed}h', inline=True)
                e.add_field(name='⚡ Akcja',
                            value=f'Wymuszono Clock Out\n{status_txt}', inline=False)
                e.set_footer(text='Wykryto podejrzaną aktywność')
                await send_log(guild, e)

                # DM notification
                if cfg.get('dm_notifications', 1) and member:
                    try:
                        await member.send(embed=discord.Embed(
                            title='⚠️ Automatyczne wylogowanie',
                            description=(f'Zostałeś automatycznie wylogowany na serwerze '
                                         f'**{guild.name}** po {elapsed}h aktywności.\n\n'
                                         f'{status_txt}'),
                            color=ORANGE))
                    except Exception:
                        pass

                # Notify in clock channel
                ch_id = cfg.get('clock_channel_id')
                ch = guild.get_channel(ch_id) if ch_id else None
                if ch:
                    try:
                        await ch.send(
                            content=mention if member else '',
                            embed=discord.Embed(
                                description=(f'⚠️ {mention} – wykryto zalogowanie przez '
                                             f'**{elapsed}h** bez wylogowania.\n'
                                             f'Sesja zakończona automatycznie. {status_txt}'),
                                color=ORANGE))
                    except discord.Forbidden:
                        pass

    @anti_cheat_task.before_loop
    async def before_anticheat(self):
        await self.bot.wait_until_ready()
        await asyncio.sleep(60)   # Give bot 60s to fully start

    # ── .apel command ─────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        if not message.content.startswith('.'):
            return
        parts = message.content[1:].strip().split()
        if not parts or parts[0].lower() != 'apel':
            return
        cfg = db.ensure_guild(message.guild.id)
        admin_ids = json.loads(cfg.get('admin_role_ids', '[]') or '[]')
        is_admin = (
            message.author.guild_permissions.administrator or
            any(r.id in admin_ids for r in message.author.roles))
        if not is_admin:
            return
        today = date.today().isoformat()
        await self._send_daily_embed(message.channel, message.guild.id, today)
        try:
            await message.add_reaction('✅')
        except Exception:
            pass


async def setup(bot: commands.Bot):
    await bot.add_cog(ClockInCog(bot))

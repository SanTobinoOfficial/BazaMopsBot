"""
Panel komend – 4 persistent embedy z przyciskami podzielonymi na kategorie.

Kategorie:
  'stats'    – 📊 Statystyki  (Punkty, Ranga, Profil, Seria)      – wszyscy
  'activity' – ⏱️ Aktywność   (Status, Historia sesji)             – wszyscy
  'server'   – 🏆 Serwer       (Ranking, Statystyki serwera)        – wszyscy
  'admin'    – ⚙️ Admin        (Punkty±, Nadaj rangę, Ostrzeż, Info, Stats) – admini

Każda odpowiedź jest EPHEMERAL (widoczna tylko dla klikającego).
"""
import discord
from discord.ext import commands
from discord import ui
from datetime import datetime
import json
import database as db
from cogs.clockin import send_log, log_embed

BLURPLE = 0x7289DA
GREEN   = 0x43B581
RED     = 0xF04747
YELLOW  = 0xFAA61A
ORANGE  = 0xE67E22


# ─── Helpers ──────────────────────────────────────────────────────────────────

async def _send_or_edit(channel: discord.TextChannel, guild_id: int,
                        panel_type: str, embed: discord.Embed,
                        view: ui.View) -> discord.Message:
    """Try to edit an existing panel message; send a new one if not found."""
    existing = db.get_panel_embed(guild_id, panel_type)
    if existing:
        try:
            old_ch = channel.guild.get_channel(existing['channel_id'])
            if old_ch:
                old_msg = await old_ch.fetch_message(existing['message_id'])
                await old_msg.edit(embed=embed, view=view)
                return old_msg
        except Exception:
            pass
    msg = await channel.send(embed=embed, view=view)
    db.save_panel_embed(guild_id, channel.id, msg.id, panel_type)
    return msg


# ─── Modals ───────────────────────────────────────────────────────────────────

class AddPointsModal(ui.Modal, title='➕ Dodaj / Odejmij Punkty'):
    user_input = ui.TextInput(label='Użytkownik (ID lub @mention)', required=True,
                              placeholder='np. 123456789 lub @Nick')
    amount     = ui.TextInput(label='Punkty (ujemne = odejmij)', required=True,
                              placeholder='np. 50 lub -20')
    note       = ui.TextInput(label='Nota', required=False,
                              default='Panel komend',
                              placeholder='Powód zmiany punktów')

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        uid_raw = self.user_input.value.strip('<@!>').strip()
        try:
            uid = int(uid_raw)
        except ValueError:
            await interaction.followup.send('❌ Nieprawidłowy użytkownik.', ephemeral=True)
            return
        try:
            pts = float(self.amount.value)
        except ValueError:
            await interaction.followup.send('❌ Nieprawidłowa liczba punktów.', ephemeral=True)
            return
        member = interaction.guild.get_member(uid)
        if not member:
            await interaction.followup.send('❌ Użytkownik nie jest na serwerze.', ephemeral=True)
            return
        db.ensure_user(uid, interaction.guild_id, str(member), member.display_name)
        new = db.add_points(uid, interaction.guild_id, pts,
                            note=self.note.value or 'Panel komend',
                            transaction_type='manual', assigned_by=interaction.user.id)
        sign = '+' if pts >= 0 else ''
        e = discord.Embed(
            description=f'✅ **{sign}{pts:.1f} pkt** → **{member.display_name}** | Stan: **{new:.1f} pkt**',
            color=GREEN if pts >= 0 else YELLOW)
        await interaction.followup.send(embed=e, ephemeral=True)
        await send_log(interaction.guild, log_embed(
            '💰 Punkty (Panel)', GREEN if pts >= 0 else YELLOW,
            Użytkownik=member.mention, Zmiana=f'{sign}{pts:.1f}',
            **{'Nowy stan': f'{new:.1f}'}, Nota=self.note.value or '—',
            Przez=interaction.user.mention))


class GiveRankModal(ui.Modal, title='🎖️ Nadaj Rangę Specjalną'):
    user_input = ui.TextInput(label='Użytkownik (ID)', required=True)
    rank_name  = ui.TextInput(label='Nazwa rangi (SPECIAL lub UNIT)', required=True)
    note       = ui.TextInput(label='Nota / powód', required=False)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        uid_raw = self.user_input.value.strip('<@!>').strip()
        try:
            uid = int(uid_raw)
        except ValueError:
            await interaction.followup.send('❌ Nieprawidłowy użytkownik.', ephemeral=True)
            return
        member = interaction.guild.get_member(uid)
        if not member:
            await interaction.followup.send('❌ Użytkownik nie jest na serwerze.', ephemeral=True)
            return
        rank = db.get_rank_by_name(interaction.guild_id, self.rank_name.value.strip())
        if not rank or not rank['is_special']:
            await interaction.followup.send('❌ Nie znaleziono rangi specjalnej o tej nazwie.',
                                            ephemeral=True)
            return
        if rank.get('is_owner_only'):
            cfg = db.get_guild(interaction.guild_id) or {}
            owner_id = cfg.get('owner_id')
            if (interaction.user.id != interaction.guild.owner_id and
                    interaction.user.id != owner_id):
                await interaction.followup.send(
                    '❌ Ta ranga (UNIT) może być nadana tylko przez właściciela/dowódcę.',
                    ephemeral=True)
                return
        db.ensure_user(uid, interaction.guild_id, str(member), member.display_name)
        ok = db.give_special_rank(uid, interaction.guild_id, rank['id'],
                                  assigned_by=interaction.user.id,
                                  note=self.note.value or '')
        if ok:
            db.add_rank_history(uid, interaction.guild_id, rank['name'], 'gained',
                                db.get_user(uid, interaction.guild_id)['points'],
                                rank_id=rank['id'])
            await interaction.followup.send(
                embed=discord.Embed(
                    description=f'✅ Nadano **{rank["icon"]} {rank["name"]}** → **{member.display_name}**',
                    color=GREEN),
                ephemeral=True)
            if rank.get('role_id'):
                role = interaction.guild.get_role(rank['role_id'])
                if role:
                    try:
                        await member.add_roles(role)
                    except discord.Forbidden:
                        pass
        else:
            await interaction.followup.send('⚠️ Użytkownik już posiada tę rangę.', ephemeral=True)


class WarnModal(ui.Modal, title='⚠️ Ostrzeż Użytkownika'):
    user_input = ui.TextInput(label='Użytkownik (ID)', required=True)
    reason     = ui.TextInput(label='Powód ostrzeżenia', required=True)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        uid_raw = self.user_input.value.strip('<@!>').strip()
        try:
            uid = int(uid_raw)
        except ValueError:
            await interaction.followup.send('❌ Nieprawidłowy użytkownik.', ephemeral=True)
            return
        member = interaction.guild.get_member(uid)
        if not member:
            await interaction.followup.send('❌ Użytkownik nie jest na serwerze.', ephemeral=True)
            return
        db.ensure_user(uid, interaction.guild_id, str(member), member.display_name)
        db.add_warning(uid, interaction.guild_id, reason=self.reason.value,
                       warned_by=interaction.user.id, is_auto=False)
        count = db.get_warning_count(uid, interaction.guild_id)
        cfg = db.get_guild(interaction.guild_id) or {}
        limit = cfg.get('warn_limit', 3)
        extra = ''
        if count >= limit:
            db.update_user(uid, interaction.guild_id, is_banned=1)
            extra = '\n🔨 Auto-ban z rankingu (osiągnięto limit)!'
        await interaction.followup.send(
            embed=discord.Embed(
                description=f'⚠️ Ostrzeżono **{member.display_name}** ({count}/{limit}){extra}',
                color=YELLOW),
            ephemeral=True)
        await send_log(interaction.guild, log_embed(
            '⚠️ Ostrzeżenie (Panel)', YELLOW,
            Użytkownik=member.mention, Powód=self.reason.value,
            **{'Ostrzeżenia': f'{count}/{limit}'}, Przez=interaction.user.mention))
        # DM notification
        cfg2 = db.get_guild(interaction.guild_id) or {}
        if cfg2.get('dm_notifications', 1):
            try:
                await member.send(embed=discord.Embed(
                    title='⚠️ Ostrzeżenie',
                    description=f'Otrzymałeś ostrzeżenie na **{interaction.guild.name}**.\n'
                                f'**Powód:** {self.reason.value}\n'
                                f'Ostrzeżenia: {count}/{limit}',
                    color=YELLOW))
            except Exception:
                pass


class UserInfoModal(ui.Modal, title='📋 Info Użytkownika'):
    user_input = ui.TextInput(label='Użytkownik (ID)', required=True)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        uid_raw = self.user_input.value.strip('<@!>').strip()
        try:
            uid = int(uid_raw)
        except ValueError:
            await interaction.followup.send('❌ Nieprawidłowy ID.', ephemeral=True)
            return
        member = interaction.guild.get_member(uid)
        db.ensure_user(uid, interaction.guild_id,
                       str(member) if member else '',
                       member.display_name if member else '')
        u = db.get_user(uid, interaction.guild_id)
        if not u:
            await interaction.followup.send('❌ Użytkownik nie znaleziony w bazie.', ephemeral=True)
            return
        rank = db.get_user_auto_rank(uid, interaction.guild_id)
        specials = db.get_user_special_ranks(uid, interaction.guild_id)
        warns = db.get_warning_count(uid, interaction.guild_id)
        cfg = db.get_guild(interaction.guild_id) or {}
        name = member.display_name if member else u.get('display_name') or str(uid)
        e = discord.Embed(title=f'📋 {name}', color=BLURPLE, timestamp=datetime.now())
        if member:
            e.set_thumbnail(url=member.display_avatar.url)
        e.add_field(name='💰 Punkty', value=f'{u["points"]:.1f}', inline=True)
        e.add_field(name='⏱️ Godziny', value=f'{u["total_hours"]:.2f}h', inline=True)
        e.add_field(name='🔥 Seria', value=f'{u.get("streak_days", 0)} dni', inline=True)
        e.add_field(name='⚠️ Warny', value=f'{warns}/{cfg.get("warn_limit", 3)}', inline=True)
        e.add_field(name='⭐ Ranga', value=f'{rank["icon"]} {rank["name"]}' if rank else 'Brak', inline=True)
        e.add_field(name='🎖️ Specjalne',
                    value=', '.join(f'{r["icon"]} {r["name"]}' for r in specials) or 'Brak',
                    inline=True)
        e.add_field(name='🟢 Aktywny', value='Tak' if u['is_clocked_in'] else 'Nie', inline=True)
        await interaction.followup.send(embed=e, ephemeral=True)


# ─── User Panel Views ──────────────────────────────────────────────────────────

class StatsPanelView(ui.View):
    """📊 Statystyki: Punkty, Ranga, Profil, Seria – ephemeral"""
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label='💰 Punkty', style=discord.ButtonStyle.primary,
               custom_id='panel_s_pts', row=0)
    async def btn_points(self, interaction: discord.Interaction, _: ui.Button):
        await interaction.response.defer(ephemeral=True)
        uid, gid = interaction.user.id, interaction.guild_id
        db.ensure_user(uid, gid, str(interaction.user), interaction.user.display_name)
        u = db.get_user(uid, gid)
        rank = db.get_user_auto_rank(uid, gid)
        ranks = db.get_ranks(gid, auto_only=True)
        next_r = next((r for r in ranks if r['required_points'] > u['points']), None)
        e = discord.Embed(title=f'💰 Punkty – {interaction.user.display_name}', color=BLURPLE)
        e.set_thumbnail(url=interaction.user.display_avatar.url)
        e.add_field(name='Punkty', value=f'**{u["points"]:.1f}** pkt', inline=True)
        e.add_field(name='Godziny', value=f'**{u["total_hours"]:.1f}h**', inline=True)
        e.add_field(name='Sesje', value=f'**{u["sessions_count"]}**', inline=True)
        if rank:
            e.add_field(name='Obecna ranga',
                        value=f'{rank["icon"]} **{rank["name"]}** ({rank["required_points"]:.0f} pkt)',
                        inline=False)
        if next_r:
            left = next_r['required_points'] - u['points']
            e.add_field(name='Następna ranga',
                        value=f'{next_r["icon"]} {next_r["name"]} – brakuje **{left:.1f} pkt**',
                        inline=False)
        else:
            e.add_field(name='✨ Status', value='Osiągnąłeś maksymalną rangę!', inline=False)
        await interaction.followup.send(embed=e, ephemeral=True)

    @ui.button(label='⭐ Ranga', style=discord.ButtonStyle.primary,
               custom_id='panel_s_rank', row=0)
    async def btn_rank(self, interaction: discord.Interaction, _: ui.Button):
        await interaction.response.defer(ephemeral=True)
        uid, gid = interaction.user.id, interaction.guild_id
        db.ensure_user(uid, gid, str(interaction.user), interaction.user.display_name)
        u = db.get_user(uid, gid)
        auto = db.get_user_auto_rank(uid, gid)
        specials = db.get_user_special_ranks(uid, gid)
        units = [r for r in specials if r.get('is_owner_only')]
        normals = [r for r in specials if not r.get('is_owner_only')]
        color = BLURPLE
        if auto and auto.get('color'):
            try:
                color = int(auto['color'].lstrip('#'), 16)
            except Exception:
                pass
        e = discord.Embed(title=f'⭐ Ranga – {interaction.user.display_name}',
                          color=color, timestamp=datetime.now())
        e.set_thumbnail(url=interaction.user.display_avatar.url)
        e.add_field(name='💰 Punkty', value=f'{u["points"]:.1f}', inline=True)
        e.add_field(name='🤖 Ranga automatyczna',
                    value=f'{auto["icon"]} **{auto["name"]}**' if auto else '*Brak*',
                    inline=False)
        if units:
            e.add_field(name='👑 Jednostki',
                        value='\n'.join(
                            f'{r["icon"]} **{r["name"]}**' +
                            (f' – {r["note"]}' if r.get('note') else '')
                            for r in units),
                        inline=False)
        if normals:
            e.add_field(name='🎖️ Rangi specjalne',
                        value='\n'.join(
                            f'{r["icon"]} **{r["name"]}**' +
                            (f' – {r["note"]}' if r.get('note') else '')
                            for r in normals),
                        inline=False)
        await interaction.followup.send(embed=e, ephemeral=True)

    @ui.button(label='👤 Profil', style=discord.ButtonStyle.secondary,
               custom_id='panel_s_profile', row=0)
    async def btn_profile(self, interaction: discord.Interaction, _: ui.Button):
        await interaction.response.defer(ephemeral=True)
        uid, gid = interaction.user.id, interaction.guild_id
        db.ensure_user(uid, gid, str(interaction.user), interaction.user.display_name)
        u = db.get_user(uid, gid)
        auto = db.get_user_auto_rank(uid, gid)
        specials = db.get_user_special_ranks(uid, gid)
        warns = db.get_warning_count(uid, gid)
        cfg = db.get_guild(gid) or {}
        streak = u.get('streak_days', 0)
        color = BLURPLE
        if auto and auto.get('color'):
            try:
                color = int(auto['color'].lstrip('#'), 16)
            except Exception:
                pass
        e = discord.Embed(title=f'👤 {interaction.user.display_name}',
                          color=color, timestamp=datetime.now())
        e.set_thumbnail(url=interaction.user.display_avatar.url)
        e.add_field(name='💰 Punkty', value=f'{u["points"]:.1f}', inline=True)
        e.add_field(name='⏱️ Godziny', value=f'{u["total_hours"]:.1f}h', inline=True)
        e.add_field(name='📅 Sesje', value=str(u['sessions_count']), inline=True)
        e.add_field(name='🔥 Seria', value=f'{streak} {"dzień" if streak == 1 else "dni"}', inline=True)
        rank_lines = []
        if auto:
            rank_lines.append(f'🤖 {auto["icon"]} {auto["name"]}')
        for sr in specials:
            badge = '👑' if sr.get('is_owner_only') else '🎖️'
            rank_lines.append(f'{badge} {sr["icon"]} {sr["name"]}')
        e.add_field(name='⭐ Rangi', value='\n'.join(rank_lines) or '*Brak*', inline=False)
        status = '🟢 Zalogowany' if u['is_clocked_in'] else '⚫ Niezalogowany'
        if u.get('is_banned'):
            status += ' | 🔨 Zablokowany z rankingu'
        e.set_footer(text=f'⚠️ Warny: {warns}/{cfg.get("warn_limit", 3)} | {status}')
        await interaction.followup.send(embed=e, ephemeral=True)

    @ui.button(label='🔥 Seria', style=discord.ButtonStyle.secondary,
               custom_id='panel_s_streak', row=0)
    async def btn_streak(self, interaction: discord.Interaction, _: ui.Button):
        await interaction.response.defer(ephemeral=True)
        uid, gid = interaction.user.id, interaction.guild_id
        db.ensure_user(uid, gid, str(interaction.user), interaction.user.display_name)
        u = db.get_user(uid, gid)
        cfg = db.get_guild(gid) or {}
        streak = u.get('streak_days', 0) or 0
        bonus_pct = cfg.get('streak_bonus_pct', 5.0)
        # Current bonus multiplier
        bonus = round(streak * bonus_pct, 1)
        e = discord.Embed(title=f'🔥 Seria – {interaction.user.display_name}', color=ORANGE)
        if streak == 0:
            e.description = (
                '**Brak aktywnej serii.** 😴\n\n'
                'Zaloguj się przez Clock In i zakończ sesję, aby rozpocząć serię!\n'
                'Za każdy kolejny dzień aktywności otrzymujesz bonus punktów.'
            )
        else:
            fire = '🔥' * min(streak, 10)
            e.description = (
                f'{fire}\n\n'
                f'**Twoja obecna seria:** {streak} {"dzień" if streak == 1 else "dni" if 2 <= streak <= 4 else "dni"} z rzędu!\n'
                f'**Bonus do punktów:** +{bonus}%\n\n'
                f'*Kontynuuj aktywność jutro, aby zwiększyć serię!*'
            )
        e.add_field(name='💡 Jak działa seria?',
                    value=(f'Zakończenie sesji każdego dnia zwiększa serię o 1.\n'
                           f'Przerwa jednego dnia resetuje serię do 0.\n'
                           f'Bonus za serię: **{bonus_pct:.1f}% za każdy dzień**.'),
                    inline=False)
        await interaction.followup.send(embed=e, ephemeral=True)


class ActivityPanelView(ui.View):
    """⏱️ Aktywność: Status clock, Historia sesji – ephemeral"""
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label='🟢 Status clock', style=discord.ButtonStyle.success,
               custom_id='panel_a_status', row=0)
    async def btn_status(self, interaction: discord.Interaction, _: ui.Button):
        await interaction.response.defer(ephemeral=True)
        uid, gid = interaction.user.id, interaction.guild_id
        db.ensure_user(uid, gid, str(interaction.user), interaction.user.display_name)
        u = db.get_user(uid, gid)
        if not u:
            await interaction.followup.send('Brak danych.', ephemeral=True)
            return
        if u['is_clocked_in']:
            since = datetime.fromisoformat(u['clock_in_time'])
            elapsed = datetime.now() - since
            mins = int(elapsed.total_seconds() / 60)
            h, m = divmod(mins, 60)
            cfg = db.get_guild(gid) or {}
            est = round(elapsed.total_seconds() / 3600 * cfg.get('points_per_hour', 10), 1)
            e = discord.Embed(title='🟢 Zalogowany', color=GREEN)
            e.add_field(name='Od godziny', value=since.strftime('%H:%M'), inline=True)
            e.add_field(name='Czas sesji', value=f'{h}h {m}min' if h else f'{m} min', inline=True)
            e.add_field(name='~Szacowane pkt', value=f'+{est:.1f} pkt', inline=True)
        else:
            last_end = db.get_last_session_end(uid, gid)
            e = discord.Embed(title='⚫ Niezalogowany', color=YELLOW)
            if last_end:
                e.add_field(name='Ostatnia sesja zakończona',
                            value=last_end.strftime('%d.%m.%Y %H:%M'),
                            inline=False)
        await interaction.followup.send(embed=e, ephemeral=True)

    @ui.button(label='📅 Historia sesji', style=discord.ButtonStyle.secondary,
               custom_id='panel_a_history', row=0)
    async def btn_history(self, interaction: discord.Interaction, _: ui.Button):
        await interaction.response.defer(ephemeral=True)
        sessions = db.get_user_sessions(interaction.user.id, interaction.guild_id, limit=10)
        if not sessions:
            await interaction.followup.send(
                embed=discord.Embed(description='📭 Brak historii sesji.', color=YELLOW),
                ephemeral=True)
            return
        lines = []
        for s in sessions:
            ci = datetime.fromisoformat(s['clock_in_time']).strftime('%d.%m %H:%M')
            flag = ' ⚠️' if s.get('flagged') else ''
            if s['clock_out_time']:
                co = datetime.fromisoformat(s['clock_out_time']).strftime('%H:%M')
                lines.append(
                    f'`{ci}→{co}` **{s["hours_worked"]:.2f}h** +{s["points_earned"]:.1f}pkt{flag}')
            else:
                lines.append(f'`{ci}` 🟢 *aktywna*')
        u = db.get_user(interaction.user.id, interaction.guild_id)
        e = discord.Embed(title='📅 Historia Sesji', description='\n'.join(lines), color=BLURPLE)
        if u:
            e.set_footer(text=f'Łącznie: {u["total_hours"]:.1f}h | {u["points"]:.1f} pkt')
        await interaction.followup.send(embed=e, ephemeral=True)


class ServerPanelView(ui.View):
    """🏆 Serwer: Ranking, Statystyki serwera – ephemeral"""
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label='🏆 Ranking', style=discord.ButtonStyle.primary,
               custom_id='panel_c_lb', row=0)
    async def btn_lb(self, interaction: discord.Interaction, _: ui.Button):
        await interaction.response.defer(ephemeral=True)
        gid = interaction.guild_id
        top = db.get_leaderboard(gid, limit=10)
        medals = ['🥇', '🥈', '🥉']
        lines = []
        user_pos = None
        all_users = db.get_leaderboard(gid, limit=9999)
        for i, u in enumerate(all_users):
            if u['user_id'] == interaction.user.id:
                user_pos = i + 1
                break
        for i, u in enumerate(top):
            medal = medals[i] if i < 3 else f'`{i+1}.`'
            m = interaction.guild.get_member(u['user_id'])
            name = m.display_name if m else u.get('display_name') or str(u['user_id'])
            rank = db.get_user_auto_rank(u['user_id'], gid)
            rs = f' • {rank["icon"]}' if rank else ''
            me_mark = ' ← Ty' if u['user_id'] == interaction.user.id else ''
            lines.append(f'{medal} **{name}**{rs} – {u["points"]:.1f} pkt{me_mark}')
        e = discord.Embed(title='🏆 Ranking Aktywności',
                          description='\n'.join(lines) or '*Brak danych.*',
                          color=BLURPLE, timestamp=datetime.now())
        if user_pos and user_pos > 10:
            me = db.get_user(interaction.user.id, gid)
            if me:
                e.set_footer(text=f'Twoja pozycja: #{user_pos} | {me["points"]:.1f} pkt')
        elif user_pos:
            e.set_footer(text=f'Twoja pozycja w top 10: #{user_pos}')
        await interaction.followup.send(embed=e, ephemeral=True)

    @ui.button(label='📊 Statystyki serwera', style=discord.ButtonStyle.secondary,
               custom_id='panel_c_stats', row=0)
    async def btn_server_stats(self, interaction: discord.Interaction, _: ui.Button):
        await interaction.response.defer(ephemeral=True)
        s = db.get_guild_stats(interaction.guild_id)
        e = discord.Embed(title=f'📊 Statystyki – {interaction.guild.name}',
                          color=BLURPLE, timestamp=datetime.now())
        e.set_thumbnail(url=interaction.guild.icon.url if interaction.guild.icon else None)
        e.add_field(name='👥 Użytkownicy', value=str(s['total_users']), inline=True)
        e.add_field(name='💰 Łączne pkt', value=f'{s["total_points"]:.0f}', inline=True)
        e.add_field(name='⏱️ Godziny aktywności', value=f'{s["total_hours"]}h', inline=True)
        e.add_field(name='🟢 Aktywni teraz', value=str(s['active_now']), inline=True)
        e.add_field(name='📋 Sesje', value=str(s['total_sessions']), inline=True)
        e.add_field(name='⭐ Rangi', value=str(s['rank_count']), inline=True)
        e.add_field(name='⚠️ Warny', value=str(s['warning_count']), inline=True)
        e.add_field(name='🔨 Zablokowanych', value=str(s['banned_count']), inline=True)
        await interaction.followup.send(embed=e, ephemeral=True)


# ─── Admin Panel View ──────────────────────────────────────────────────────────

class AdminPanelView(ui.View):
    """⚙️ Admin: Punkty, Rangi, Ostrzeżenia, Info, Statystyki"""
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

    @ui.button(label='➕ Punkty', style=discord.ButtonStyle.success,
               custom_id='apanel_pts', row=0)
    async def btn_add_pts(self, interaction: discord.Interaction, _: ui.Button):
        if not await self._is_admin(interaction):
            await interaction.response.send_message('❌ Brak uprawnień.', ephemeral=True)
            return
        await interaction.response.send_modal(AddPointsModal())

    @ui.button(label='🎖️ Nadaj Rangę', style=discord.ButtonStyle.primary,
               custom_id='apanel_rank', row=0)
    async def btn_give_rank(self, interaction: discord.Interaction, _: ui.Button):
        if not await self._is_admin(interaction):
            await interaction.response.send_message('❌ Brak uprawnień.', ephemeral=True)
            return
        await interaction.response.send_modal(GiveRankModal())

    @ui.button(label='⚠️ Ostrzeż', style=discord.ButtonStyle.danger,
               custom_id='apanel_warn', row=0)
    async def btn_warn(self, interaction: discord.Interaction, _: ui.Button):
        if not await self._is_admin(interaction):
            await interaction.response.send_message('❌ Brak uprawnień.', ephemeral=True)
            return
        await interaction.response.send_modal(WarnModal())

    @ui.button(label='📋 Info Użytkownika', style=discord.ButtonStyle.secondary,
               custom_id='apanel_info', row=1)
    async def btn_info(self, interaction: discord.Interaction, _: ui.Button):
        if not await self._is_admin(interaction):
            await interaction.response.send_message('❌ Brak uprawnień.', ephemeral=True)
            return
        await interaction.response.send_modal(UserInfoModal())

    @ui.button(label='📊 Statystyki (Admin)', style=discord.ButtonStyle.secondary,
               custom_id='apanel_stats', row=1)
    async def btn_stats(self, interaction: discord.Interaction, _: ui.Button):
        await interaction.response.defer(ephemeral=True)
        if not await self._is_admin(interaction):
            await interaction.followup.send('❌ Brak uprawnień.', ephemeral=True)
            return
        s = db.get_guild_stats(interaction.guild_id)
        e = discord.Embed(title='📊 Statystyki (Admin)', color=ORANGE, timestamp=datetime.now())
        e.add_field(name='👥 Użytkownicy', value=str(s['total_users']), inline=True)
        e.add_field(name='💰 Łączne pkt', value=f'{s["total_points"]:.0f}', inline=True)
        e.add_field(name='⏱️ Godziny', value=f'{s["total_hours"]}h', inline=True)
        e.add_field(name='🟢 Aktywni', value=str(s['active_now']), inline=True)
        e.add_field(name='⚠️ Warny', value=str(s['warning_count']), inline=True)
        e.add_field(name='🔨 Zablokowanych', value=str(s['banned_count']), inline=True)
        await interaction.followup.send(embed=e, ephemeral=True)


# ─── Cog ──────────────────────────────────────────────────────────────────────

class PanelCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        if not message.content.startswith('.'):
            return
        parts = message.content[1:].strip().split()
        if not parts or parts[0].lower() != 'panel':
            return
        cfg = db.get_guild(message.guild.id)
        if not cfg:
            return
        try:
            aids = json.loads(cfg.get('admin_role_ids') or '[]')
        except Exception:
            aids = []
        is_admin = (message.author.guild_permissions.administrator or
                    any(r.id in aids for r in message.author.roles))
        if not is_admin:
            await message.reply(
                embed=discord.Embed(description='❌ Brak uprawnień.', color=RED),
                mention_author=False)
            return
        ch_id = cfg.get('command_panel_channel_id')
        channel = message.guild.get_channel(ch_id) if ch_id else message.channel
        if not channel:
            await message.reply(
                embed=discord.Embed(
                    description='❌ Kanał panelu nie ustawiony.\n'
                                'Użyj Dashboardu → Konfiguracja, aby ustawić kanał panelu.',
                    color=RED),
                mention_author=False)
            return
        await self._refresh_panel(channel, message.guild.id)
        try:
            await message.add_reaction('✅')
        except Exception:
            pass

    async def _refresh_panel(self, channel: discord.TextChannel, guild_id: int):
        """Send (or edit) all 4 panel embeds in the configured channel."""

        # ── 1. 📊 Statystyki ──────────────────────────────────────────────────
        stats_e = discord.Embed(
            title='📊 Statystyki',
            description=(
                'Sprawdź swoje punkty, rangę, profil i serię aktywności.\n'
                '🔒 *Odpowiedzi widoczne tylko dla Ciebie.*'
            ),
            color=BLURPLE
        )
        stats_e.add_field(name='💰 Punkty',
                          value='Twoje punkty, ranga i postęp do następnej', inline=True)
        stats_e.add_field(name='⭐ Ranga',
                          value='Aktualna ranga automatyczna i specjalne', inline=True)
        stats_e.add_field(name='👤 Profil',
                          value='Pełny profil z podsumowaniem', inline=True)
        stats_e.add_field(name='🔥 Seria',
                          value='Twoja seria dni aktywności i bonus punktów', inline=True)
        stats_e.set_footer(text='System Rang • Kliknij przycisk poniżej')
        await _send_or_edit(channel, guild_id, 'stats', stats_e, StatsPanelView())

        # ── 2. ⏱️ Aktywność ───────────────────────────────────────────────────
        activity_e = discord.Embed(
            title='⏱️ Aktywność',
            description=(
                'Sprawdź swój aktualny status clock in/out i historię sesji.\n'
                '🔒 *Odpowiedzi widoczne tylko dla Ciebie.*'
            ),
            color=GREEN
        )
        activity_e.add_field(name='🟢 Status clock',
                              value='Czy jesteś aktualnie zalogowany? Ile czasu minęło?',
                              inline=True)
        activity_e.add_field(name='📅 Historia sesji',
                              value='Ostatnie 10 sesji z godzinami i punktami',
                              inline=True)
        activity_e.set_footer(text='System Rang • Kliknij przycisk poniżej')
        await _send_or_edit(channel, guild_id, 'activity', activity_e, ActivityPanelView())

        # ── 3. 🏆 Serwer ──────────────────────────────────────────────────────
        server_e = discord.Embed(
            title='🏆 Serwer',
            description=(
                'Ranking aktywności i globalne statystyki serwera.\n'
                '🔒 *Odpowiedzi widoczne tylko dla Ciebie.*'
            ),
            color=YELLOW
        )
        server_e.add_field(name='🏆 Ranking',
                           value='Top 10 najbardziej aktywnych graczy', inline=True)
        server_e.add_field(name='📊 Statystyki serwera',
                           value='Łączna aktywność, godziny, warny i więcej', inline=True)
        server_e.set_footer(text='System Rang • Kliknij przycisk poniżej')
        await _send_or_edit(channel, guild_id, 'server', server_e, ServerPanelView())

        # ── 4. ⚙️ Admin ───────────────────────────────────────────────────────
        admin_e = discord.Embed(
            title='⚙️ Panel Admina',
            description=(
                'Komendy administracyjne – **uprawnienia sprawdzane przy każdym kliknięciu**.\n'
                '🔒 *Tylko dla uprawnionych ról.*'
            ),
            color=ORANGE
        )
        admin_e.add_field(name='➕ Punkty', value='Dodaj lub odejmij punkty dowolnemu użytkownikowi', inline=True)
        admin_e.add_field(name='🎖️ Nadaj Rangę', value='Nadaj rangę specjalną (SPECIAL) lub jednostkową (UNIT)', inline=True)
        admin_e.add_field(name='⚠️ Ostrzeż', value='Wyślij ostrzeżenie z powodem (liczy do auto-banu)', inline=True)
        admin_e.add_field(name='📋 Info', value='Pełne info o dowolnym użytkowniku', inline=True)
        admin_e.add_field(name='📊 Statystyki', value='Globalne statystyki serwera (wersja admin)', inline=True)
        admin_e.set_footer(text='System Rang • Tylko dla adminów')
        await _send_or_edit(channel, guild_id, 'admin', admin_e, AdminPanelView())


async def setup(bot: commands.Bot):
    await bot.add_cog(PanelCog(bot))

"""
Panel komend – persistent embed z przyciskami dla wszystkich komend.
Dwa typy paneli:
  'user'  – komendy użytkownika (widoczny dla wszystkich)
  'admin' – komendy admina (przyciski widoczne, ale sprawdzanie uprawnień)
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
            await interaction.followup.send('❌ Nieprawidłowy użytkownik.', ephemeral=True); return
        try:
            pts = float(self.amount.value)
        except ValueError:
            await interaction.followup.send('❌ Nieprawidłowa liczba punktów.', ephemeral=True); return

        member = interaction.guild.get_member(uid)
        if not member:
            await interaction.followup.send('❌ Użytkownik nie jest na serwerze.', ephemeral=True); return

        db.ensure_user(uid, interaction.guild_id, str(member), member.display_name)
        new = db.add_points(uid, interaction.guild_id, pts,
                            note=self.note.value or 'Panel komend',
                            transaction_type='manual', assigned_by=interaction.user.id)
        sign = '+' if pts >= 0 else ''
        e = discord.Embed(
            description=f'✅ **{sign}{pts:.1f} pkt** → **{member.display_name}** | Stan: **{new:.1f} pkt**',
            color=GREEN if pts >= 0 else YELLOW
        )
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
            await interaction.followup.send('❌ Nieprawidłowy użytkownik.', ephemeral=True); return

        member = interaction.guild.get_member(uid)
        if not member:
            await interaction.followup.send('❌ Użytkownik nie jest na serwerze.', ephemeral=True); return

        rank = db.get_rank_by_name(interaction.guild_id, self.rank_name.value.strip())
        if not rank or not rank['is_special']:
            await interaction.followup.send('❌ Nie znaleziono rangi specjalnej o tej nazwie.', ephemeral=True); return

        if rank.get('is_owner_only'):
            cfg = db.get_guild(interaction.guild_id) or {}
            owner_id = cfg.get('owner_id')
            if (interaction.user.id != interaction.guild.owner_id and
                    interaction.user.id != owner_id):
                await interaction.followup.send('❌ Ta ranga (UNIT) może być nadana tylko przez właściciela/dowódcę.', ephemeral=True); return

        db.ensure_user(uid, interaction.guild_id, str(member), member.display_name)
        ok = db.give_special_rank(uid, interaction.guild_id, rank['id'],
                                  assigned_by=interaction.user.id,
                                  note=self.note.value or '')
        if ok:
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
            await interaction.followup.send('❌ Nieprawidłowy użytkownik.', ephemeral=True); return

        member = interaction.guild.get_member(uid)
        if not member:
            await interaction.followup.send('❌ Użytkownik nie jest na serwerze.', ephemeral=True); return

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
        await send_log(interaction.guild, log_embed('⚠️ Ostrzeżenie (Panel)', YELLOW,
            Użytkownik=member.mention, Powód=self.reason.value,
            **{'Ostrzeżenia': f'{count}/{limit}'}, Przez=interaction.user.mention))


class UserInfoModal(ui.Modal, title='📋 Info Użytkownika'):
    user_input = ui.TextInput(label='Użytkownik (ID)', required=True)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        uid_raw = self.user_input.value.strip('<@!>').strip()
        try:
            uid = int(uid_raw)
        except ValueError:
            await interaction.followup.send('❌ Nieprawidłowy ID.', ephemeral=True); return

        member = interaction.guild.get_member(uid)
        db.ensure_user(uid, interaction.guild_id,
                       str(member) if member else '',
                       member.display_name if member else '')
        u = db.get_user(uid, interaction.guild_id)
        if not u:
            await interaction.followup.send('❌ Użytkownik nie znaleziony w bazie.', ephemeral=True); return

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
        e.add_field(name='⚠️ Warny', value=f'{warns}/{cfg.get("warn_limit", 3)}', inline=True)
        e.add_field(name='⭐ Ranga', value=f'{rank["icon"]} {rank["name"]}' if rank else 'Brak', inline=True)
        e.add_field(name='🎖️ Specjalne', value=', '.join(f'{r["icon"]} {r["name"]}' for r in specials) or 'Brak', inline=True)
        e.add_field(name='🟢 Aktywny', value='Tak' if u['is_clocked_in'] else 'Nie', inline=True)
        await interaction.followup.send(embed=e, ephemeral=True)


# ─── Panel Views ──────────────────────────────────────────────────────────────

class UserPanelView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def _check_perm(self, interaction, command_name) -> bool:
        perm = db.get_command_permission(interaction.guild_id, command_name)
        if perm:
            try:
                allowed = json.loads(perm['allowed_role_ids'])
            except Exception:
                allowed = []
            if allowed:
                return (interaction.user.guild_permissions.administrator or
                        any(r.id in allowed for r in interaction.user.roles))
        return True

    @ui.button(label='💰 Punkty', style=discord.ButtonStyle.secondary, custom_id='panel_points', row=0)
    async def btn_points(self, interaction: discord.Interaction, _: ui.Button):
        await interaction.response.defer(ephemeral=True)
        uid, gid = interaction.user.id, interaction.guild_id
        db.ensure_user(uid, gid, str(interaction.user), interaction.user.display_name)
        u = db.get_user(uid, gid)
        rank = db.get_user_auto_rank(uid, gid)
        ranks = db.get_ranks(gid, auto_only=True)
        next_r = next((r for r in ranks if r['required_points'] > u['points']), None)
        e = discord.Embed(title=f'💰 Punkty – {interaction.user.display_name}', color=BLURPLE)
        e.add_field(name='Punkty', value=f'**{u["points"]:.1f}** pkt', inline=True)
        e.add_field(name='Godziny', value=f'**{u["total_hours"]:.1f}h**', inline=True)
        if rank:
            e.add_field(name='Ranga', value=f'{rank["icon"]} {rank["name"]}', inline=True)
        if next_r:
            e.add_field(name='Następna ranga',
                        value=f'{next_r["icon"]} {next_r["name"]} (brakuje {next_r["required_points"]-u["points"]:.1f} pkt)',
                        inline=False)
        await interaction.followup.send(embed=e, ephemeral=True)

    @ui.button(label='⭐ Ranga', style=discord.ButtonStyle.secondary, custom_id='panel_rank', row=0)
    async def btn_rank(self, interaction: discord.Interaction, _: ui.Button):
        await interaction.response.defer(ephemeral=True)
        uid, gid = interaction.user.id, interaction.guild_id
        db.ensure_user(uid, gid, str(interaction.user), interaction.user.display_name)
        u = db.get_user(uid, gid)
        auto = db.get_user_auto_rank(uid, gid)
        specials = db.get_user_special_ranks(uid, gid)
        e = discord.Embed(title=f'⭐ Ranga – {interaction.user.display_name}', color=BLURPLE)
        e.add_field(name='💰 Punkty', value=f'{u["points"]:.1f}', inline=True)
        e.add_field(name='🤖 Auto', value=f'{auto["icon"]} {auto["name"]}' if auto else 'Brak', inline=True)
        if specials:
            e.add_field(name='🎖️ Specjalne/Jednostki',
                        value='\n'.join(f'{"👑" if r.get("is_owner_only") else "🎖️"} {r["icon"]} {r["name"]}' for r in specials),
                        inline=False)
        await interaction.followup.send(embed=e, ephemeral=True)

    @ui.button(label='🏆 Ranking', style=discord.ButtonStyle.secondary, custom_id='panel_lb', row=0)
    async def btn_lb(self, interaction: discord.Interaction, _: ui.Button):
        await interaction.response.defer(ephemeral=True)
        top = db.get_leaderboard(interaction.guild_id, limit=10)
        medals = ['🥇', '🥈', '🥉']
        lines = []
        for i, u in enumerate(top):
            medal = medals[i] if i < 3 else f'`{i+1}.`'
            m = interaction.guild.get_member(u['user_id'])
            name = m.display_name if m else u.get('display_name') or str(u['user_id'])
            lines.append(f'{medal} **{name}** – {u["points"]:.1f} pkt')
        e = discord.Embed(title='🏆 Ranking', description='\n'.join(lines) or 'Brak danych.', color=BLURPLE)
        await interaction.followup.send(embed=e, ephemeral=True)

    @ui.button(label='📅 Historia', style=discord.ButtonStyle.secondary, custom_id='panel_history', row=1)
    async def btn_history(self, interaction: discord.Interaction, _: ui.Button):
        await interaction.response.defer(ephemeral=True)
        sessions = db.get_user_sessions(interaction.user.id, interaction.guild_id, limit=5)
        if not sessions:
            await interaction.followup.send('📭 Brak historii sesji.', ephemeral=True); return
        lines = []
        for s in sessions:
            ci = datetime.fromisoformat(s['clock_in_time']).strftime('%d.%m %H:%M')
            flag = ' ⚠️' if s.get('flagged') else ''
            if s['clock_out_time']:
                co = datetime.fromisoformat(s['clock_out_time']).strftime('%H:%M')
                lines.append(f'`{ci}→{co}` {s["hours_worked"]:.2f}h +{s["points_earned"]:.1f}pkt{flag}')
            else:
                lines.append(f'`{ci}` 🟢 aktywna')
        e = discord.Embed(title='📅 Ostatnie sesje', description='\n'.join(lines), color=BLURPLE)
        await interaction.followup.send(embed=e, ephemeral=True)

    @ui.button(label='👤 Profil', style=discord.ButtonStyle.secondary, custom_id='panel_profile', row=1)
    async def btn_profile(self, interaction: discord.Interaction, _: ui.Button):
        await interaction.response.defer(ephemeral=True)
        uid, gid = interaction.user.id, interaction.guild_id
        db.ensure_user(uid, gid, str(interaction.user), interaction.user.display_name)
        u = db.get_user(uid, gid)
        auto = db.get_user_auto_rank(uid, gid)
        specials = db.get_user_special_ranks(uid, gid)
        warns = db.get_warning_count(uid, gid)
        cfg = db.get_guild(gid) or {}
        e = discord.Embed(title=f'👤 {interaction.user.display_name}', color=BLURPLE, timestamp=datetime.now())
        e.set_thumbnail(url=interaction.user.display_avatar.url)
        e.add_field(name='💰 Punkty', value=f'{u["points"]:.1f}', inline=True)
        e.add_field(name='⏱️ Godziny', value=f'{u["total_hours"]:.1f}h', inline=True)
        e.add_field(name='📅 Sesje', value=str(u['sessions_count']), inline=True)
        rank_lines = []
        if auto:
            rank_lines.append(f'🤖 {auto["icon"]} {auto["name"]}')
        for sr in specials:
            badge = '👑' if sr.get('is_owner_only') else '🎖️'
            rank_lines.append(f'{badge} {sr["icon"]} {sr["name"]}')
        e.add_field(name='⭐ Rangi', value='\n'.join(rank_lines) or 'Brak', inline=False)
        e.set_footer(text=f'Warny: {warns}/{cfg.get("warn_limit", 3)} | {"🟢 Aktywny" if u["is_clocked_in"] else "⚫ Nieaktywny"}')
        await interaction.followup.send(embed=e, ephemeral=True)

    @ui.button(label='⏱️ Status', style=discord.ButtonStyle.secondary, custom_id='panel_clock', row=1)
    async def btn_clock(self, interaction: discord.Interaction, _: ui.Button):
        await interaction.response.defer(ephemeral=True)
        u = db.get_user(interaction.user.id, interaction.guild_id)
        if not u:
            await interaction.followup.send('Brak danych.', ephemeral=True); return
        if u['is_clocked_in']:
            since = datetime.fromisoformat(u['clock_in_time'])
            mins = int((datetime.now() - since).total_seconds() / 60)
            cfg = db.get_guild(interaction.guild_id) or {}
            est = round((mins / 60) * cfg.get('points_per_hour', 10), 1)
            e = discord.Embed(description=f'🟢 Zalogowany od **{since.strftime("%H:%M")}** ({mins} min)\n~{est} pkt', color=GREEN)
        else:
            e = discord.Embed(description='⚫ Niezalogowany.', color=YELLOW)
        await interaction.followup.send(embed=e, ephemeral=True)


class AdminPanelView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def _is_admin(self, interaction) -> bool:
        if interaction.user.guild_permissions.administrator:
            return True
        cfg = db.get_guild(interaction.guild_id) or {}
        try:
            aids = json.loads(cfg.get('admin_role_ids') or '[]')
        except Exception:
            aids = []
        return any(r.id in aids for r in interaction.user.roles)

    @ui.button(label='➕ Dodaj/Odejmij Punkty', style=discord.ButtonStyle.success, custom_id='apanel_pts', row=0)
    async def btn_add_pts(self, interaction: discord.Interaction, _: ui.Button):
        if not await self._is_admin(interaction):
            await interaction.response.send_message('❌ Brak uprawnień.', ephemeral=True); return
        await interaction.response.send_modal(AddPointsModal())

    @ui.button(label='🎖️ Nadaj Rangę', style=discord.ButtonStyle.primary, custom_id='apanel_rank', row=0)
    async def btn_give_rank(self, interaction: discord.Interaction, _: ui.Button):
        if not await self._is_admin(interaction):
            await interaction.response.send_message('❌ Brak uprawnień.', ephemeral=True); return
        await interaction.response.send_modal(GiveRankModal())

    @ui.button(label='⚠️ Ostrzeż', style=discord.ButtonStyle.danger, custom_id='apanel_warn', row=0)
    async def btn_warn(self, interaction: discord.Interaction, _: ui.Button):
        if not await self._is_admin(interaction):
            await interaction.response.send_message('❌ Brak uprawnień.', ephemeral=True); return
        await interaction.response.send_modal(WarnModal())

    @ui.button(label='📋 Info Użytkownika', style=discord.ButtonStyle.secondary, custom_id='apanel_info', row=1)
    async def btn_info(self, interaction: discord.Interaction, _: ui.Button):
        if not await self._is_admin(interaction):
            await interaction.response.send_message('❌ Brak uprawnień.', ephemeral=True); return
        await interaction.response.send_modal(UserInfoModal())

    @ui.button(label='📊 Statystyki', style=discord.ButtonStyle.secondary, custom_id='apanel_stats', row=1)
    async def btn_stats(self, interaction: discord.Interaction, _: ui.Button):
        await interaction.response.defer(ephemeral=True)
        if not await self._is_admin(interaction):
            await interaction.followup.send('❌ Brak uprawnień.', ephemeral=True); return
        s = db.get_guild_stats(interaction.guild_id)
        e = discord.Embed(title='📊 Statystyki', color=BLURPLE, timestamp=datetime.now())
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
                    description='❌ Kanał panelu nie ustawiony.\nUżyj `.setchannel panel #kanał`',
                    color=RED),
                mention_author=False)
            return
        await self._refresh_panel(channel, message.guild.id)
        await message.add_reaction('✅')

    async def _refresh_panel(self, channel: discord.TextChannel, guild_id: int):
        # ── User panel ──
        user_e = discord.Embed(
            title='🎛️ Panel Komend – Użytkownik',
            description=(
                'Użyj przycisków poniżej aby sprawdzić swoje statystyki.\n'
                'Odpowiedzi są widoczne **tylko dla Ciebie**.'
            ),
            color=BLURPLE,
            timestamp=datetime.now()
        )
        user_e.add_field(name='💰 Punkty', value='Sprawdź swoje punkty i postęp', inline=True)
        user_e.add_field(name='⭐ Ranga', value='Twoja aktualna ranga', inline=True)
        user_e.add_field(name='🏆 Ranking', value='Top 10 serwera', inline=True)
        user_e.add_field(name='📅 Historia', value='Ostatnie sesje clock', inline=True)
        user_e.add_field(name='👤 Profil', value='Pełny profil', inline=True)
        user_e.add_field(name='⏱️ Status', value='Czy jesteś zalogowany?', inline=True)
        user_e.set_footer(text='System Rang • Wszystkie odpowiedzi są prywatne')

        existing_user = db.get_panel_embed(guild_id, 'user')
        if existing_user:
            try:
                old_ch = channel.guild.get_channel(existing_user['channel_id'])
                if old_ch:
                    old_msg = await old_ch.fetch_message(existing_user['message_id'])
                    await old_msg.edit(embed=user_e, view=UserPanelView())
                    user_msg = old_msg
                else:
                    raise Exception('Channel not found')
            except Exception:
                user_msg = await channel.send(embed=user_e, view=UserPanelView())
        else:
            user_msg = await channel.send(embed=user_e, view=UserPanelView())
        db.save_panel_embed(guild_id, channel.id, user_msg.id, 'user')

        # ── Admin panel ──
        admin_e = discord.Embed(
            title='⚙️ Panel Komend – Admin',
            description=(
                'Komendy administracyjne.\n'
                '**Uprawnienia są sprawdzane przy każdym kliknięciu.**'
            ),
            color=0xE67E22,
            timestamp=datetime.now()
        )
        admin_e.add_field(name='➕ Dodaj/Odejmij Punkty', value='Zmień punkty dowolnego użytkownika', inline=True)
        admin_e.add_field(name='🎖️ Nadaj Rangę', value='Nadaj rangę SPECIAL lub UNIT', inline=True)
        admin_e.add_field(name='⚠️ Ostrzeż', value='Wyślij ostrzeżenie użytkownikowi', inline=True)
        admin_e.add_field(name='📋 Info Użytkownika', value='Szczegóły dowolnego użytkownika', inline=True)
        admin_e.add_field(name='📊 Statystyki', value='Statystyki całego serwera', inline=True)
        admin_e.set_footer(text='System Rang • Tylko dla uprawnionych')

        existing_admin = db.get_panel_embed(guild_id, 'admin')
        if existing_admin:
            try:
                old_ch = channel.guild.get_channel(existing_admin['channel_id'])
                if old_ch:
                    old_msg = await old_ch.fetch_message(existing_admin['message_id'])
                    await old_msg.edit(embed=admin_e, view=AdminPanelView())
                else:
                    raise Exception('Channel not found')
            except Exception:
                await channel.send(embed=admin_e, view=AdminPanelView())
                new_msg = await channel.send(embed=admin_e, view=AdminPanelView())
                db.save_panel_embed(guild_id, channel.id, new_msg.id, 'admin')
                return
        else:
            new_msg = await channel.send(embed=admin_e, view=AdminPanelView())
            db.save_panel_embed(guild_id, channel.id, new_msg.id, 'admin')


async def setup(bot: commands.Bot):
    await bot.add_cog(PanelCog(bot))

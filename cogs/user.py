import discord
from discord.ext import commands
from datetime import datetime
import json
import database as db

BLURPLE = 0x7289DA
GREEN   = 0x43B581
RED     = 0xF04747
YELLOW  = 0xFAA61A
MEDALS  = ['🥇', '🥈', '🥉']


class UserCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._handlers = {
            'points':      self._cmd_points,
            'rank':        self._cmd_rank,
            'lb':          self._cmd_leaderboard,
            'leaderboard': self._cmd_leaderboard,
            'history':     self._cmd_history,
            'profile':     self._cmd_profile,
            'clock':       self._cmd_clock,
            'help':        self._cmd_help,
        }

    def _resolve_member(self, msg, arg):
        uid = arg.strip('<@!>').strip()
        try:
            return msg.guild.get_member(int(uid))
        except ValueError:
            return None

    async def _can_use(self, member: discord.Member, guild_id: int,
                       command_name: str) -> bool:
        """Check command-level permissions for user commands."""
        perm = db.get_command_permission(guild_id, command_name)
        if perm:
            try:
                allowed = json.loads(perm['allowed_role_ids'])
            except Exception:
                allowed = []
            if allowed:
                return (member.guild_permissions.administrator or
                        any(r.id in allowed for r in member.roles))
        return True   # User commands open by default

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        if not message.content.startswith('.'):
            return
        parts = message.content[1:].strip().split()
        if not parts:
            return
        cmd = parts[0].lower()
        if cmd not in self._handlers:
            return
        db.ensure_guild(message.guild.id)
        db.ensure_user(message.author.id, message.guild.id,
                       str(message.author), message.author.display_name)
        if not await self._can_use(message.author, message.guild.id, cmd):
            await message.reply(
                embed=discord.Embed(
                    description='❌ Twoja rola nie ma dostępu do tej komendy.',
                    color=RED),
                mention_author=False)
            return
        await self._handlers[cmd](message, parts[1:])

    async def _cmd_points(self, msg, args):
        m = self._resolve_member(msg, args[0]) if args else msg.author
        if not m:
            await msg.reply(embed=discord.Embed(description='❌ Nie znaleziono.', color=RED),
                            mention_author=False); return
        db.ensure_user(m.id, msg.guild.id, str(m), m.display_name)
        u = db.get_user(m.id, msg.guild.id)
        rank = db.get_user_auto_rank(m.id, msg.guild.id)
        ranks = db.get_ranks(msg.guild.id, auto_only=True)
        next_r = next((r for r in ranks if r['required_points'] > u['points']), None)
        e = discord.Embed(title=f'💰 Punkty – {m.display_name}', color=BLURPLE)
        e.set_thumbnail(url=m.display_avatar.url)
        e.add_field(name='Punkty', value=f'**{u["points"]:.1f}** pkt', inline=True)
        e.add_field(name='Godziny', value=f'**{u["total_hours"]:.1f}h**', inline=True)
        e.add_field(name='Sesje', value=f'**{u["sessions_count"]}**', inline=True)
        if rank:
            e.add_field(name='Obecna ranga', value=f'{rank["icon"]} {rank["name"]}', inline=False)
        if next_r:
            e.add_field(name='Następna ranga',
                        value=f'{next_r["icon"]} {next_r["name"]} – brakuje **{next_r["required_points"]-u["points"]:.1f} pkt**',
                        inline=False)
        warns = db.get_warning_count(m.id, msg.guild.id)
        cfg = db.get_guild(msg.guild.id) or {}
        if warns > 0:
            e.set_footer(text=f'⚠️ Ostrzeżenia: {warns}/{cfg.get("warn_limit", 3)}')
        await msg.reply(embed=e, mention_author=False)

    async def _cmd_rank(self, msg, args):
        m = self._resolve_member(msg, args[0]) if args else msg.author
        if not m:
            await msg.reply(embed=discord.Embed(description='❌ Nie znaleziono.', color=RED),
                            mention_author=False); return
        db.ensure_user(m.id, msg.guild.id, str(m), m.display_name)
        u = db.get_user(m.id, msg.guild.id)
        auto = db.get_user_auto_rank(m.id, msg.guild.id)
        specials = db.get_user_special_ranks(m.id, msg.guild.id)
        units = [r for r in specials if r.get('is_owner_only')]
        normals = [r for r in specials if not r.get('is_owner_only')]
        color = BLURPLE
        if auto and auto.get('color'):
            try:
                color = int(auto['color'].lstrip('#'), 16)
            except Exception:
                pass
        e = discord.Embed(title=f'⭐ Ranga – {m.display_name}', color=color)
        e.set_thumbnail(url=m.display_avatar.url)
        e.add_field(name='💰 Punkty', value=f'{u["points"]:.1f}', inline=True)
        e.add_field(name='🤖 Ranga automatyczna',
                    value=f'{auto["icon"]} **{auto["name"]}** ({auto["required_points"]:.0f} pkt)' if auto else 'Brak',
                    inline=False)
        if units:
            e.add_field(name='👑 Jednostki',
                        value='\n'.join(f'{r["icon"]} **{r["name"]}**' + (f' – {r["note"]}' if r.get("note") else '') for r in units),
                        inline=False)
        if normals:
            e.add_field(name='🎖️ Rangi specjalne',
                        value='\n'.join(f'{r["icon"]} **{r["name"]}**' + (f' – {r["note"]}' if r.get("note") else '') for r in normals),
                        inline=False)
        await msg.reply(embed=e, mention_author=False)

    async def _cmd_leaderboard(self, msg, args):
        top = db.get_leaderboard(msg.guild.id, limit=10)
        if not top:
            await msg.reply(embed=discord.Embed(description='📭 Brak danych.', color=YELLOW),
                            mention_author=False); return
        e = discord.Embed(title='🏆 Ranking Aktywności', color=BLURPLE, timestamp=datetime.now())
        lines = []
        for i, u in enumerate(top):
            medal = MEDALS[i] if i < 3 else f'`{i+1}.`'
            member = msg.guild.get_member(u['user_id'])
            name = member.display_name if member else u.get('display_name') or str(u['user_id'])
            rank = db.get_user_auto_rank(u['user_id'], msg.guild.id)
            rs = f' • {rank["icon"]} {rank["name"]}' if rank else ''
            lines.append(f'{medal} **{name}** – {u["points"]:.1f} pkt{rs}')
        e.description = '\n'.join(lines)
        all_u = db.get_leaderboard(msg.guild.id, limit=9999)
        me = db.get_user(msg.author.id, msg.guild.id)
        if me and not me['is_banned']:
            pos = next((i+1 for i, u in enumerate(all_u) if u['user_id'] == msg.author.id), None)
            if pos and pos > 10:
                e.set_footer(text=f'Twoja pozycja: #{pos} | {me["points"]:.1f} pkt')
        await msg.reply(embed=e, mention_author=False)

    async def _cmd_history(self, msg, args):
        sessions = db.get_user_sessions(msg.author.id, msg.guild.id, limit=10)
        if not sessions:
            await msg.reply(embed=discord.Embed(description='📭 Brak historii.', color=YELLOW),
                            mention_author=False); return
        e = discord.Embed(title='📅 Historia Sesji', color=BLURPLE)
        lines = []
        for s in sessions:
            ci = datetime.fromisoformat(s['clock_in_time']).strftime('%d.%m %H:%M')
            flag = ' ⚠️' if s.get('flagged') else ''
            if s['clock_out_time']:
                co = datetime.fromisoformat(s['clock_out_time']).strftime('%H:%M')
                lines.append(f'`{ci}` → `{co}` | {s["hours_worked"]:.2f}h | +{s["points_earned"]:.1f} pkt{flag}')
            else:
                lines.append(f'`{ci}` → 🟢 *aktywna*')
        e.description = '\n'.join(lines)
        u = db.get_user(msg.author.id, msg.guild.id)
        if u:
            e.set_footer(text=f'Łącznie: {u["total_hours"]:.1f}h | {u["points"]:.1f} pkt')
        await msg.reply(embed=e, mention_author=False)

    async def _cmd_profile(self, msg, args):
        m = self._resolve_member(msg, args[0]) if args else msg.author
        if not m:
            await msg.reply(embed=discord.Embed(description='❌ Nie znaleziono.', color=RED),
                            mention_author=False); return
        db.ensure_user(m.id, msg.guild.id, str(m), m.display_name)
        u = db.get_user(m.id, msg.guild.id)
        auto = db.get_user_auto_rank(m.id, msg.guild.id)
        specials = db.get_user_special_ranks(m.id, msg.guild.id)
        sessions = db.get_user_sessions(m.id, msg.guild.id, limit=3)
        warns = db.get_warnings(m.id, msg.guild.id)
        cfg = db.get_guild(msg.guild.id) or {}
        color = BLURPLE
        if auto and auto.get('color'):
            try:
                color = int(auto['color'].lstrip('#'), 16)
            except Exception:
                pass
        e = discord.Embed(title=f'👤 Profil – {m.display_name}', color=color, timestamp=datetime.now())
        e.set_thumbnail(url=m.display_avatar.url)
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
        status = '🟢 Zalogowany' if u['is_clocked_in'] else '⚫ Niezalogowany'
        if u['is_banned']:
            status += ' | 🔨 Zablokowany na lb'
        if warns:
            status += f' | ⚠️ {len(warns)}/{cfg.get("warn_limit", 3)} warnów'
        e.add_field(name='Status', value=status, inline=False)
        if sessions:
            lines = []
            for s in sessions:
                ci = datetime.fromisoformat(s['clock_in_time']).strftime('%d.%m %H:%M')
                if s['clock_out_time']:
                    co = datetime.fromisoformat(s['clock_out_time']).strftime('%H:%M')
                    lines.append(f'`{ci}→{co}` {s["hours_worked"]:.1f}h +{s["points_earned"]:.1f}pkt')
                else:
                    lines.append(f'`{ci}` 🟢 aktywna')
            e.add_field(name='📅 Ostatnie sesje', value='\n'.join(lines), inline=False)
        ranks = db.get_ranks(msg.guild.id, auto_only=True)
        for r in ranks:
            if r['required_points'] > u['points']:
                e.set_footer(text=f'Do rangi {r["name"]}: {r["required_points"]-u["points"]:.1f} pkt')
                break
        await msg.reply(embed=e, mention_author=False)

    async def _cmd_clock(self, msg, args):
        u = db.get_user(msg.author.id, msg.guild.id)
        if not u:
            await msg.reply(embed=discord.Embed(description='Brak danych.', color=YELLOW),
                            mention_author=False); return
        if u['is_clocked_in']:
            since = datetime.fromisoformat(u['clock_in_time'])
            elapsed = datetime.now() - since
            mins = int(elapsed.total_seconds() / 60)
            cfg = db.get_guild(msg.guild.id) or {}
            est = round((elapsed.total_seconds() / 3600) * cfg.get('points_per_hour', 10), 1)
            e = discord.Embed(
                description=f'🟢 Zalogowany od **{since.strftime("%H:%M")}**\n'
                            f'Czas: **{mins} min** | Szacowane: **~{est} pkt**',
                color=GREEN)
        else:
            e = discord.Embed(description='⚫ Nie jesteś zalogowany.', color=YELLOW)
        await msg.reply(embed=e, mention_author=False)

    async def _cmd_help(self, msg, args):
        gid = msg.guild.id
        cfg = db.get_guild(gid) or {}
        try:
            admin_ids = json.loads(cfg.get('admin_role_ids') or '[]')
        except Exception:
            admin_ids = []
        is_admin = (msg.author.guild_permissions.administrator or
                    any(r.id in admin_ids for r in msg.author.roles))

        # ── Permission helpers (sync – db calls are synchronous) ──────────────
        def _user_perm(cmd):
            """Return True if member can use this user command."""
            perm = db.get_command_permission(gid, cmd)
            if perm:
                try:
                    allowed = json.loads(perm['allowed_role_ids'])
                except Exception:
                    allowed = []
                if allowed:
                    return (msg.author.guild_permissions.administrator or
                            any(r.id in allowed for r in msg.author.roles))
            return True   # user commands open by default

        def _admin_perm(cmd):
            """Return True if member can use this admin command."""
            perm = db.get_command_permission(gid, cmd)
            if perm:
                try:
                    allowed = json.loads(perm['allowed_role_ids'])
                except Exception:
                    allowed = []
                if allowed:
                    return (msg.author.guild_permissions.administrator or
                            any(r.id in allowed for r in msg.author.roles))
            return is_admin   # fall back to generic admin check

        e = discord.Embed(title='📖 Pomoc – System Rang',
                          description='Prefix: **`.`** | Panel komend: kanał z przyciskami',
                          color=BLURPLE)

        # ── User commands (filtered) ──────────────────────────────────────────
        user_defs = [
            ('points',   '`.points [@user]`',   'punkty, ranga, postęp do następnej'),
            ('rank',     '`.rank [@user]`',     'ranga auto + specjalne + jednostki'),
            ('lb',       '`.lb`',               'ranking top 10'),
            ('history',  '`.history`',          'historia sesji clock in/out'),
            ('profile',  '`.profile [@user]`',  'pełny profil z ostatnimi sesjami'),
            ('clock',    '`.clock`',            'aktualny status zalogowania'),
            ('help',     '`.help`',             'ta wiadomość'),
        ]
        user_lines = [f'{s} – {d}' for cmd, s, d in user_defs if _user_perm(cmd)]
        e.add_field(name='👤 Użytkownik', inline=False,
                    value='\n'.join(user_lines) if user_lines else '*Brak dostępnych komend.*')

        if not is_admin:
            await msg.reply(embed=e, mention_author=False)
            return

        # ── Admin commands (filtered per-command) ─────────────────────────────
        pts_defs = [
            ('addpoints',    '`.addpoints @u <n> [nota]`'),
            ('removepoints', '`.removepoints @u <n> [nota]`'),
            ('setpoints',    '`.setpoints @u <n> [nota]`'),
        ]
        pts_lines = [s for cmd, s in pts_defs if _admin_perm(cmd)]
        if pts_lines:
            e.add_field(name='🔨 Admin – Punkty', inline=False,
                        value='  '.join(pts_lines))

        rank_defs = [
            ('giverank',   '`.giverank @u <ranga> [nota]` – nadaj SPECIAL/UNIT'),
            ('takerank',   '`.takerank @u <ranga>` – odbierz rangę'),
            ('createrank', '`.createrank <n> <pkt|SPECIAL|UNIT> [ikona] [#kolor] [opis]`'),
            ('deleterank', '`.deleterank <nazwa>`'),
            ('editrank',   '`.editrank <nazwa> <pole> <wartość>`'),
            ('ranks',      '`.ranks` – lista rang'),
        ]
        rank_lines = [s for cmd, s in rank_defs if _admin_perm(cmd)]
        if rank_lines:
            e.add_field(name='🔨 Admin – Rangi', inline=False,
                        value='\n'.join(rank_lines))

        warn_defs = [
            ('warn',      '`.warn @u [powód]`'),
            ('warnings',  '`.warnings [@u]`'),
            ('clearwarn', '`.clearwarn @u [id]`'),
        ]
        warn_lines = [s for cmd, s in warn_defs if _admin_perm(cmd)]
        if warn_lines:
            e.add_field(name='🔨 Admin – Ostrzeżenia', inline=False,
                        value='  '.join(warn_lines))

        mgmt_defs = [
            ('userinfo',        '`.userinfo @u`'),
            ('forceclockout',   '`.forceclockout @u`'),
            ('resetuser',       '`.resetuser @u`'),
            ('ban',             '`.ban @u`'),
            ('unban',           '`.unban @u`'),
            ('serverstats',     '`.serverstats`'),
            ('setchannel',      '`.setchannel <clock|log|panel> #ch`'),
            ('setpoints_h',     '`.setpoints_h <n>`'),
            ('adminrole',       '`.adminrole @r`'),
            ('removeadminrole', '`.removeadminrole @r`'),
            ('setowner',        '`.setowner @u`'),
            ('setwarnlimit',    '`.setwarnlimit <n>`'),
            ('setmaxhours',     '`.setmaxhours <h>`'),
            ('config',          '`.config`'),
            ('apel',            '`.apel` – wyślij embed Clock In/Out na bieżący kanał'),
        ]
        mgmt_lines = [s for cmd, s in mgmt_defs if _admin_perm(cmd)]
        if mgmt_lines:
            e.add_field(name='🔨 Admin – Zarządzanie', inline=False,
                        value='\n'.join(mgmt_lines))

        # panel is handled by PanelCog (no per-command DB entry by default)
        e.add_field(name='🔨 Admin – Panel', inline=False,
                    value='`.panel` – utwórz/odśwież panel komend w skonfigurowanym kanale')
        await msg.reply(embed=e, mention_author=False)


async def setup(bot: commands.Bot):
    await bot.add_cog(UserCog(bot))

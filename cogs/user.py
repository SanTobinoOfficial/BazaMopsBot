import discord
from discord.ext import commands
from datetime import datetime
import database as db

BLURPLE = 0x7289DA
GREEN   = 0x43B581
RED     = 0xF04747
YELLOW  = 0xFAA61A

MEDALS = ['🥇', '🥈', '🥉']


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

    def _resolve_member(self, msg: discord.Message, arg: str) -> discord.Member | None:
        uid = arg.strip('<@!>').strip()
        try:
            return msg.guild.get_member(int(uid))
        except ValueError:
            return None

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
        await self._handlers[cmd](message, parts[1:])

    # ── .points [@user] ───────────────────────────────────────────────────────
    async def _cmd_points(self, msg: discord.Message, args: list):
        if args:
            member = self._resolve_member(msg, args[0])
        else:
            member = msg.author
        if not member:
            await msg.reply(embed=discord.Embed(description='❌ Nie znaleziono użytkownika.', color=RED),
                            mention_author=False)
            return

        db.ensure_user(member.id, msg.guild.id, str(member), member.display_name)
        user = db.get_user(member.id, msg.guild.id)
        rank = db.get_user_auto_rank(member.id, msg.guild.id)

        # Find next rank
        ranks = db.get_ranks(msg.guild.id, auto_only=True)
        next_rank = None
        for r in ranks:
            if r['required_points'] > user['points']:
                next_rank = r
                break

        embed = discord.Embed(
            title=f'💰 Punkty – {member.display_name}',
            color=BLURPLE
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name='Punkty', value=f'**{user["points"]:.1f}** pkt', inline=True)
        embed.add_field(name='Godziny', value=f'**{user["total_hours"]:.1f}h**', inline=True)
        embed.add_field(name='Sesje', value=f'**{user["sessions_count"]}**', inline=True)

        if rank:
            embed.add_field(name='Obecna ranga', value=f'{rank["icon"]} {rank["name"]}', inline=False)
        if next_rank:
            needed = next_rank['required_points'] - user['points']
            embed.add_field(name='Następna ranga',
                            value=f'{next_rank["icon"]} {next_rank["name"]} – brakuje **{needed:.1f} pkt**',
                            inline=False)
        await msg.reply(embed=embed, mention_author=False)

    # ── .rank [@user] ─────────────────────────────────────────────────────────
    async def _cmd_rank(self, msg: discord.Message, args: list):
        if args:
            member = self._resolve_member(msg, args[0])
        else:
            member = msg.author
        if not member:
            await msg.reply(embed=discord.Embed(description='❌ Nie znaleziono użytkownika.', color=RED),
                            mention_author=False)
            return

        db.ensure_user(member.id, msg.guild.id, str(member), member.display_name)
        user = db.get_user(member.id, msg.guild.id)
        auto_rank = db.get_user_auto_rank(member.id, msg.guild.id)
        specials  = db.get_user_special_ranks(member.id, msg.guild.id)

        embed = discord.Embed(title=f'⭐ Ranga – {member.display_name}', color=BLURPLE)
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name='💰 Punkty', value=f'{user["points"]:.1f}', inline=True)

        if auto_rank:
            try:
                color = int(auto_rank['color'].lstrip('#'), 16)
                embed.color = color
            except Exception:
                pass
            embed.add_field(
                name='🤖 Ranga automatyczna',
                value=f'{auto_rank["icon"]} **{auto_rank["name"]}**\n'
                      f'Wymagane: {auto_rank["required_points"]:.0f} pkt',
                inline=False
            )
        else:
            embed.add_field(name='🤖 Ranga automatyczna', value='Brak (brak rang lub za mało pkt)', inline=False)

        if specials:
            embed.add_field(
                name='🎖️ Rangi specjalne',
                value='\n'.join(
                    f'{r["icon"]} **{r["name"]}**' + (f' – {r["note"]}' if r.get("note") else '')
                    for r in specials
                ),
                inline=False
            )
        await msg.reply(embed=embed, mention_author=False)

    # ── .lb / .leaderboard ────────────────────────────────────────────────────
    async def _cmd_leaderboard(self, msg: discord.Message, args: list):
        top = db.get_leaderboard(msg.guild.id, limit=10)
        if not top:
            await msg.reply(embed=discord.Embed(description='📭 Brak danych rankingowych.', color=YELLOW),
                            mention_author=False)
            return

        embed = discord.Embed(title='🏆 Ranking Aktywności', color=BLURPLE, timestamp=datetime.now())
        lines = []
        for i, u in enumerate(top):
            medal = MEDALS[i] if i < 3 else f'`{i+1}.`'
            member = msg.guild.get_member(u['user_id'])
            name = member.display_name if member else u.get('display_name') or u.get('username') or f'ID:{u["user_id"]}'
            rank = db.get_user_auto_rank(u['user_id'], msg.guild.id)
            rank_str = f' • {rank["icon"]} {rank["name"]}' if rank else ''
            lines.append(f'{medal} **{name}** – {u["points"]:.1f} pkt{rank_str}')

        embed.description = '\n'.join(lines)

        # Show calling user's position
        user = db.get_user(msg.author.id, msg.guild.id)
        if user and not user['is_banned']:
            all_users = db.get_leaderboard(msg.guild.id, limit=9999)
            pos = next((i+1 for i, u in enumerate(all_users) if u['user_id'] == msg.author.id), None)
            if pos and pos > 10:
                embed.set_footer(text=f'Twoja pozycja: #{pos} | {user["points"]:.1f} pkt')

        await msg.reply(embed=embed, mention_author=False)

    # ── .history ──────────────────────────────────────────────────────────────
    async def _cmd_history(self, msg: discord.Message, args: list):
        sessions = db.get_user_sessions(msg.author.id, msg.guild.id, limit=10)
        if not sessions:
            await msg.reply(embed=discord.Embed(description='📭 Brak historii sesji.', color=YELLOW),
                            mention_author=False)
            return

        embed = discord.Embed(title='📅 Historia Sesji', color=BLURPLE)
        lines = []
        for s in sessions:
            ci = datetime.fromisoformat(s['clock_in_time']).strftime('%d.%m %H:%M')
            if s['clock_out_time']:
                co = datetime.fromisoformat(s['clock_out_time']).strftime('%H:%M')
                lines.append(f'`{ci}` → `{co}` | {s["hours_worked"]:.2f}h | +{s["points_earned"]:.1f} pkt')
            else:
                lines.append(f'`{ci}` → 🟢 *aktywna*')

        embed.description = '\n'.join(lines)
        user = db.get_user(msg.author.id, msg.guild.id)
        if user:
            embed.set_footer(text=f'Łącznie: {user["total_hours"]:.1f}h | {user["points"]:.1f} pkt')
        await msg.reply(embed=embed, mention_author=False)

    # ── .profile [@user] ──────────────────────────────────────────────────────
    async def _cmd_profile(self, msg: discord.Message, args: list):
        if args:
            member = self._resolve_member(msg, args[0])
        else:
            member = msg.author
        if not member:
            await msg.reply(embed=discord.Embed(description='❌ Nie znaleziono użytkownika.', color=RED),
                            mention_author=False)
            return

        db.ensure_user(member.id, msg.guild.id, str(member), member.display_name)
        user = db.get_user(member.id, msg.guild.id)
        auto_rank = db.get_user_auto_rank(member.id, msg.guild.id)
        specials  = db.get_user_special_ranks(member.id, msg.guild.id)
        sessions  = db.get_user_sessions(member.id, msg.guild.id, limit=3)
        txs       = db.get_user_transactions(member.id, msg.guild.id, limit=3)

        # Rank color
        color = BLURPLE
        if auto_rank and auto_rank.get('color'):
            try:
                color = int(auto_rank['color'].lstrip('#'), 16)
            except Exception:
                pass

        embed = discord.Embed(
            title=f'👤 Profil – {member.display_name}',
            color=color,
            timestamp=datetime.now()
        )
        embed.set_thumbnail(url=member.display_avatar.url)

        # Stats
        embed.add_field(name='💰 Punkty', value=f'{user["points"]:.1f}', inline=True)
        embed.add_field(name='⏱️ Łączny czas', value=f'{user["total_hours"]:.1f}h', inline=True)
        embed.add_field(name='📅 Sesje', value=str(user['sessions_count']), inline=True)

        # Ranks
        rank_lines = []
        if auto_rank:
            rank_lines.append(f'🤖 {auto_rank["icon"]} {auto_rank["name"]}')
        for sr in specials:
            rank_lines.append(f'🎖️ {sr["icon"]} {sr["name"]}')
        embed.add_field(name='⭐ Rangi', value='\n'.join(rank_lines) or 'Brak', inline=False)

        # Status
        status = '🟢 Zalogowany' if user['is_clocked_in'] else '⚫ Niezalogowany'
        if user['is_banned']:
            status += ' | ⚠️ Zablokowany na lb'
        embed.add_field(name='Status', value=status, inline=False)

        # Recent sessions
        if sessions:
            sess_lines = []
            for s in sessions:
                ci = datetime.fromisoformat(s['clock_in_time']).strftime('%d.%m %H:%M')
                if s['clock_out_time']:
                    co = datetime.fromisoformat(s['clock_out_time']).strftime('%H:%M')
                    sess_lines.append(f'`{ci}→{co}` {s["hours_worked"]:.1f}h +{s["points_earned"]:.1f}pkt')
                else:
                    sess_lines.append(f'`{ci}` 🟢 aktywna')
            embed.add_field(name='📅 Ostatnie sesje', value='\n'.join(sess_lines), inline=False)

        # Next rank
        ranks = db.get_ranks(msg.guild.id, auto_only=True)
        for r in ranks:
            if r['required_points'] > user['points']:
                needed = r['required_points'] - user['points']
                embed.set_footer(text=f'Do rangi {r["name"]}: {needed:.1f} pkt')
                break

        await msg.reply(embed=embed, mention_author=False)

    # ── .clock ────────────────────────────────────────────────────────────────
    async def _cmd_clock(self, msg: discord.Message, args: list):
        user = db.get_user(msg.author.id, msg.guild.id)
        if not user:
            await msg.reply(embed=discord.Embed(description='Brak danych. Najpierw użyj Clock In.',
                                                color=YELLOW), mention_author=False)
            return
        if user['is_clocked_in']:
            since = datetime.fromisoformat(user['clock_in_time'])
            elapsed = datetime.now() - since
            mins = int(elapsed.total_seconds() / 60)
            cfg = db.get_guild(msg.guild.id) or {}
            pph = cfg.get('points_per_hour', 10.0)
            est_pts = round((elapsed.total_seconds() / 3600) * pph, 1)
            embed = discord.Embed(
                description=f'🟢 Jesteś zalogowany od **{since.strftime("%H:%M")}**\n'
                            f'Czas aktywności: **{mins} min**\n'
                            f'Szacowane punkty: **~{est_pts} pkt**',
                color=GREEN
            )
        else:
            embed = discord.Embed(description='⚫ Nie jesteś zalogowany.', color=YELLOW)
        await msg.reply(embed=embed, mention_author=False)

    # ── .help ─────────────────────────────────────────────────────────────────
    async def _cmd_help(self, msg: discord.Message, args: list):
        from cogs.admin import AdminCog
        is_admin = False
        cfg = db.get_guild(msg.guild.id) or {}
        import json
        try:
            role_ids = json.loads(cfg.get('admin_role_ids', '[]'))
        except Exception:
            role_ids = []
        if (msg.author.guild_permissions.administrator or
                any(r.id in role_ids for r in msg.author.roles)):
            is_admin = True

        embed = discord.Embed(
            title='📖 Pomoc – System Rang',
            description='Prefix komend: **`.`**',
            color=BLURPLE
        )
        embed.add_field(
            name='👤 Komendy użytkownika',
            value=(
                '`.points [@użytkownik]` – sprawdź punkty\n'
                '`.rank [@użytkownik]` – sprawdź rangę\n'
                '`.lb` / `.leaderboard` – ranking top 10\n'
                '`.history` – historia sesji\n'
                '`.profile [@użytkownik]` – pełny profil\n'
                '`.clock` – status clock in/out\n'
                '`.help` – ta wiadomość'
            ),
            inline=False
        )
        if is_admin:
            embed.add_field(
                name='🔨 Komendy Admina',
                value=(
                    '`.ban @user` – zablokuj z rankingu\n'
                    '`.unban @user` – odblokuj z rankingu\n'
                    '`.addpoints @user <n> [nota]` – dodaj punkty\n'
                    '`.removepoints @user <n> [nota]` – odejmij punkty\n'
                    '`.setpoints @user <n> [nota]` – ustaw punkty\n'
                    '`.giverank @user <nazwa> [nota]` – nadaj rangę spec.\n'
                    '`.takerank @user <nazwa>` – odbierz rangę spec.\n'
                    '`.createrank <nazwa> <pkt|SPECIAL> [ikona] [#kolor] [opis]`\n'
                    '`.deleterank <nazwa>` – usuń rangę\n'
                    '`.editrank <nazwa> <pole> <wartość>` – edytuj rangę\n'
                    '`.ranks` – lista wszystkich rang\n'
                    '`.forceclockout @user` – wymuś wylogowanie\n'
                    '`.resetuser @user` – resetuj dane użytkownika\n'
                    '`.userinfo @user` – szczegóły użytkownika\n'
                    '`.serverstats` – statystyki serwera\n'
                    '`.setchannel <clock|log> #kanał`\n'
                    '`.setpoints_h <n>` – punkty za godzinę\n'
                    '`.adminrole @rola` – dodaj rolę admina\n'
                    '`.removeadminrole @rola` – usuń rolę admina\n'
                    '`.config` – pokaż konfigurację\n'
                    '`.apel` – wyślij codzienny apel ręcznie'
                ),
                inline=False
            )
        embed.set_footer(text='Dashboard: dostępny pod adresem bota na Replit')
        await msg.reply(embed=embed, mention_author=False)


async def setup(bot: commands.Bot):
    await bot.add_cog(UserCog(bot))

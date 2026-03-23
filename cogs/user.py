import discord
from discord.ext import commands
from datetime import datetime, timedelta
import json
import random
import asyncio
import database as db

BLURPLE = 0x7289DA
GREEN   = 0x43B581
RED     = 0xF04747
YELLOW  = 0xFAA61A
GOLD    = 0xF1C40F
ORANGE  = 0xE67E22
PURPLE  = 0x9B59B6

MEDALS  = ['🥇', '🥈', '🥉']
COIN    = '🪙'

# ── Shop items: (name, cost_mopsy, points_reward) ────────────────────────────
SHOP_ITEMS = [
    (1, 'Paczka S',  100,  5),
    (2, 'Paczka M',  450,  25),
    (3, 'Paczka L',  800,  50),
    (4, 'Paczka XL', 1500, 100),
]

# ── 8ball answers ─────────────────────────────────────────────────────────────
BALL_ANSWERS = [
    ('Tak!', GREEN), ('Zdecydowanie tak.', GREEN), ('Na pewno.', GREEN),
    ('Bez wątpienia.', GREEN), ('Możesz na to liczyć.', GREEN),
    ('Wygląda dobrze.', GREEN), ('Tak, zdecydowanie.', GREEN),
    ('Raczej tak.', YELLOW), ('Znaki wskazują na tak.', YELLOW),
    ('Zapytaj ponownie później.', YELLOW), ('Lepiej nie mówić ci teraz.', YELLOW),
    ('Nie można przewidzieć teraz.', YELLOW), ('Skoncentruj się i zapytaj ponownie.', YELLOW),
    ('Nie licz na to.', RED), ('Moja odpowiedź brzmi nie.', RED),
    ('Moje źródła mówią nie.', RED), ('Perspektywy nie wyglądają dobrze.', RED),
    ('Bardzo wątpliwe.', RED),
]

# ── Trivia questions ──────────────────────────────────────────────────────────
TRIVIA = [
    ('Jaka jest stolica Polski?', 'Warszawa', ['Kraków', 'Gdańsk', 'Poznań']),
    ('Ile metrów ma jeden kilometr?', '1000', ['100', '500', '10000']),
    ('Jak nazywa się największy ocean na Ziemi?', 'Spokojny', ['Atlantycki', 'Indyjski', 'Arktyczny']),
    ('W którym roku zakończyła się II Wojna Światowa?', '1945', ['1939', '1942', '1950']),
    ('Ile wynosi pierwiastek kwadratowy z 144?', '12', ['10', '14', '16']),
    ('Kto napisał "Pan Tadeusz"?', 'Adam Mickiewicz', ['Juliusz Słowacki', 'Henryk Sienkiewicz', 'Bolesław Prus']),
    ('Ile kości ma ludzki szkielet dorosłego człowieka?', '206', ['150', '250', '300']),
    ('Jak nazywa się planeta najdalej od Słońca?', 'Neptun', ['Saturn', 'Uran', 'Jowisz']),
    ('Ile wynosi 15% z 200?', '30', ['25', '35', '40']),
    ('Jaki element chemiczny ma symbol Au?', 'Złoto', ['Srebro', 'Miedź', 'Aluminium']),
    ('W którym roku Polska wstąpiła do Unii Europejskiej?', '2004', ['1999', '2007', '2001']),
    ('Jak długo trwa doba?', '24 godziny', ['20 godzin', '22 godziny', '26 godzin']),
    ('Ile kontynentów ma Ziemia?', '7', ['5', '6', '8']),
    ('Kto jest autorem teorii względności?', 'Albert Einstein', ['Isaac Newton', 'Nikola Tesla', 'Stephen Hawking']),
    ('Jak nazywa się najwyższa góra świata?', 'Mount Everest', ['K2', 'Mont Blanc', 'Kilimandżaro']),
    ('Ile dni ma rok przestępny?', '366', ['365', '367', '364']),
    ('Jaki kolor mają liście chlorofilu?', 'Zielony', ['Żółty', 'Niebieski', 'Czerwony']),
    ('Ile godzin ma tydzień?', '168', ['144', '196', '120']),
    ('Kto napisał "Quo Vadis"?', 'Henryk Sienkiewicz', ['Adam Mickiewicz', 'Bolesław Prus', 'Stefan Żeromski']),
    ('Jaką prędkość ma światło (km/s)?', '300 000', ['150 000', '1 000 000', '30 000']),
    ('Ile strun ma gitara klasyczna?', '6', ['4', '7', '8']),
    ('Jak nazywa się symbol matematyczny nieskończoności?', 'Lemniskata', ['Sigma', 'Delta', 'Omega']),
    ('Ile wynosi suma kątów trójkąta?', '180 stopni', ['90 stopni', '270 stopni', '360 stopni']),
    ('W jakim kraju znajduje się Wieża Eiffla?', 'Francja', ['Włochy', 'Niemcy', 'Belgia']),
    ('Ile nóg ma pająk?', '8', ['6', '10', '4']),
]


def _prog_bar(current: float, next_pts: float, from_pts: float = 0, width: int = 10) -> str:
    span = next_pts - from_pts
    if span <= 0:
        filled = width
    else:
        filled = int(min(width, max(0, round((current - from_pts) / span * width))))
    bar = '█' * filled + '░' * (width - filled)
    return f'`{bar}` {current:.0f}/{next_pts:.0f} pkt'


def _fmt_money(n: float) -> str:
    return f'**{int(n):,}** {COIN}'.replace(',', ' ')


def _check_cooldown(last_str: str | None, minutes: int) -> timedelta | None:
    """Returns remaining timedelta if still on cooldown, else None."""
    if not last_str:
        return None
    try:
        last = datetime.fromisoformat(last_str)
    except Exception:
        return None
    diff = timedelta(minutes=minutes) - (datetime.now() - last)
    return diff if diff.total_seconds() > 0 else None


def _fmt_cd(td: timedelta) -> str:
    total = int(td.total_seconds())
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f'{h}h {m}m'
    if m:
        return f'{m}m {s}s'
    return f'{s}s'


class UserCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._handlers = {
            # Rangi / punkty
            'points':      self._cmd_points,
            'rank':        self._cmd_rank,
            'lb':          self._cmd_leaderboard,
            'leaderboard': self._cmd_leaderboard,
            'history':     self._cmd_history,
            'profile':     self._cmd_profile,
            'clock':       self._cmd_clock,
            'help':        self._cmd_help,
            # Ekonomia
            'balance':     self._cmd_balance,
            'bal':         self._cmd_balance,
            'portfel':     self._cmd_balance,
            'daily':       self._cmd_daily,
            'work':        self._cmd_work,
            'pracuj':      self._cmd_work,
            'beg':         self._cmd_beg,
            'zebrz':       self._cmd_beg,
            'pay':         self._cmd_pay,
            'przelej':     self._cmd_pay,
            'deposit':     self._cmd_deposit,
            'withdraw':    self._cmd_withdraw,
            'shop':        self._cmd_shop,
            'sklep':       self._cmd_shop,
            'buy':         self._cmd_buy,
            'kup':         self._cmd_buy,
            'eco':         self._cmd_ecolb,
            'ecolb':       self._cmd_ecolb,
            # Fun
            '8ball':       self._cmd_8ball,
            'coinflip':    self._cmd_coinflip,
            'flip':        self._cmd_coinflip,
            'roll':        self._cmd_roll,
            'dice':        self._cmd_roll,
            'choose':      self._cmd_choose,
            'wybierz':     self._cmd_choose,
            'avatar':      self._cmd_avatar,
            'av':          self._cmd_avatar,
            'serverinfo':  self._cmd_serverinfo,
            'si':          self._cmd_serverinfo,
            'rep':         self._cmd_rep,
            'poll':        self._cmd_poll,
            'ankieta':     self._cmd_poll,
            'trivia':      self._cmd_trivia,
            'quiz':        self._cmd_trivia,
            # Ekonomia – minigry (Dank Memer / Tatsu)
            'blackjack':   self._cmd_blackjack,
            'bj':          self._cmd_blackjack,
            'highlow':     self._cmd_highlow,
            'hl':          self._cmd_highlow,
            'scratch':     self._cmd_scratch,
            'rps':         self._cmd_rps,
            'slots':       self._cmd_slots,
            'fish':        self._cmd_fish,
            'mine':        self._cmd_mine,
            'hunt':        self._cmd_hunt,
            # Fun – social (Tatsu)
            'hug':         self._cmd_hug,
            'pat':         self._cmd_pat,
            'slap':        self._cmd_slap,
            'gg':          self._cmd_gg,
            # Fun – misc
            'joke':        self._cmd_joke,
            'quote':       self._cmd_quote,
            'owo':         self._cmd_owo,
            'uwu':         self._cmd_owo,
            'ship':        self._cmd_ship,
            'rate':        self._cmd_rate,
            'fact':        self._cmd_fact,
            'reverse':     self._cmd_reverse,
            'upper':       self._cmd_upper,
            'lower':       self._cmd_lower,
            # Utility (MEE6/Carl-bot)
            'ping':        self._cmd_ping,
            'uptime':      self._cmd_uptime,
            'remindme':    self._cmd_remindme,
            'remind':      self._cmd_remindme,
            # Tags (Carl-bot) – read-only for users
            'tag':         self._cmd_tag,
            'taglist':     self._cmd_taglist,
            # Info
            'roleinfo':    self._cmd_roleinfo,
            'ri':          self._cmd_roleinfo,
            # Level alias (MEE6)
            'level':       self._cmd_rank,
            # Jobs
            'job':         self._cmd_job,
            'praca':       self._cmd_job,
            'jobs':        self._cmd_job,
        }

    def _resolve_member(self, msg, arg):
        uid = arg.strip('<@!>').strip()
        try:
            return msg.guild.get_member(int(uid))
        except ValueError:
            return None

    async def _check_perm(self, msg, cmd_name: str) -> bool:
        """Returns False and sends error if user's rank doesn't allow the command."""
        if not msg.guild:
            return True
        if not db.check_user_command_permission(msg.author.id, msg.guild.id, cmd_name):
            em = discord.Embed(
                description=f'❌ Twoja ranga nie ma dostępu do komendy `.{cmd_name}`.',
                color=0xf04747)
            await msg.channel.send(embed=em)
            return False
        return True

    async def _can_use(self, member: discord.Member, guild_id: int, command_name: str) -> bool:
        perm = db.get_command_permission(guild_id, command_name)
        if perm:
            try:
                allowed = json.loads(perm['allowed_role_ids'])
            except Exception:
                allowed = []
            if allowed:
                return (member.guild_permissions.administrator or
                        any(r.id in allowed for r in member.roles))
        return True

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
                embed=discord.Embed(description='❌ Twoja rola nie ma dostępu do tej komendy.', color=RED),
                mention_author=False)
            return
        await self._handlers[cmd](message, parts[1:])

    # ══════════════════════════════════════════════════════════════════════════
    # RANGI / PUNKTY
    # ══════════════════════════════════════════════════════════════════════════

    async def _cmd_points(self, msg, args):
        m = self._resolve_member(msg, args[0]) if args else msg.author
        if not m:
            await msg.reply(embed=discord.Embed(description='❌ Nie znaleziono.', color=RED),
                            mention_author=False); return
        db.ensure_user(m.id, msg.guild.id, str(m), m.display_name)
        u = db.get_user(m.id, msg.guild.id)
        rank   = db.get_user_auto_rank(m.id, msg.guild.id)
        next_r = db.get_user_next_rank(m.id, msg.guild.id)
        e = discord.Embed(title=f'💰 Punkty – {m.display_name}', color=BLURPLE)
        e.set_thumbnail(url=m.display_avatar.url)
        e.add_field(name='Punkty', value=f'**{u["points"]:.1f}** pkt', inline=True)
        e.add_field(name='Godziny', value=f'**{u["total_hours"]:.1f}h**', inline=True)
        e.add_field(name='Sesje', value=f'**{u["sessions_count"]}**', inline=True)
        if rank:
            e.add_field(name='Obecna ranga', value=f'{rank["icon"]} {rank["name"]}', inline=False)
        if next_r:
            from_pts = rank['required_points'] if rank else 0
            bar = _prog_bar(u['points'], next_r['required_points'], from_pts)
            e.add_field(name=f'Postęp → {next_r["icon"]} {next_r["name"]}', value=bar, inline=False)
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
        u        = db.get_user(m.id, msg.guild.id)
        auto     = db.get_user_auto_rank(m.id, msg.guild.id)
        next_r   = db.get_user_next_rank(m.id, msg.guild.id)
        specials = db.get_user_special_ranks(m.id, msg.guild.id)
        units    = [r for r in specials if r.get('is_owner_only')]
        normals  = [r for r in specials if not r.get('is_owner_only')]
        faction  = db.get_user_faction_membership(m.id, msg.guild.id)
        color = BLURPLE
        if auto and auto.get('color'):
            try: color = int(auto['color'].lstrip('#'), 16)
            except Exception: pass
        elif faction and faction.get('faction_color'):
            try: color = int(faction['faction_color'].lstrip('#'), 16)
            except Exception: pass
        e = discord.Embed(title=f'⭐ Ranga – {m.display_name}', color=color)
        e.set_thumbnail(url=m.display_avatar.url)
        e.add_field(name='💰 Punkty', value=f'{u["points"]:.1f}', inline=True)
        if faction:
            e.add_field(name='⚔️ Frakcja',
                        value=f'{faction["faction_icon"]} **{faction["faction_name"]}**', inline=True)
        e.add_field(name='🤖 Ranga automatyczna',
                    value=f'{auto["icon"]} **{auto["name"]}** ({auto["required_points"]:.0f} pkt)' if auto else 'Brak (cywil)',
                    inline=False)
        if next_r:
            from_pts = auto['required_points'] if auto else 0
            bar = _prog_bar(u['points'], next_r['required_points'], from_pts)
            e.add_field(name=f'Postęp → {next_r["icon"]} {next_r["name"]}', value=bar, inline=False)
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
        u        = db.get_user(m.id, msg.guild.id)
        auto     = db.get_user_auto_rank(m.id, msg.guild.id)
        next_r   = db.get_user_next_rank(m.id, msg.guild.id)
        specials = db.get_user_special_ranks(m.id, msg.guild.id)
        sessions = db.get_user_sessions(m.id, msg.guild.id, limit=3)
        warns    = db.get_warnings(m.id, msg.guild.id)
        faction  = db.get_user_faction_membership(m.id, msg.guild.id)
        jobs     = db.get_user_jobs(m.id, msg.guild.id)
        cfg      = db.get_guild(msg.guild.id) or {}
        wallet   = db.get_wallet(m.id, msg.guild.id)
        color = BLURPLE
        if auto and auto.get('color'):
            try: color = int(auto['color'].lstrip('#'), 16)
            except Exception: pass
        elif faction and faction.get('faction_color'):
            try: color = int(faction['faction_color'].lstrip('#'), 16)
            except Exception: pass
        e = discord.Embed(title=f'👤 Profil – {m.display_name}', color=color, timestamp=datetime.now())
        e.set_thumbnail(url=m.display_avatar.url)
        e.add_field(name='💰 Punkty', value=f'{u["points"]:.1f}', inline=True)
        e.add_field(name='⏱️ Godziny', value=f'{u["total_hours"]:.1f}h', inline=True)
        e.add_field(name='📅 Sesje', value=str(u['sessions_count']), inline=True)
        e.add_field(name=f'{COIN} Portfel', value=f'Gotówka: {int(wallet["cash"])} | Bank: {int(wallet["bank"])}', inline=True)
        rep = u.get('rep_points') or 0
        e.add_field(name='⭐ Reputacja', value=str(rep), inline=True)
        e.add_field(name='⚠️ Warn pts', value=f'{u.get("warn_points", 0):.1f}', inline=True)
        if faction:
            e.add_field(name='⚔️ Frakcja',
                        value=f'{faction["faction_icon"]} **{faction["faction_name"]}**', inline=True)
        if jobs:
            job_str = ' | '.join(f'{j["icon"]} {j["name"]}' for j in jobs)
            e.add_field(name='💼 Prace', value=job_str, inline=True)
        rank_lines = []
        if auto:
            rank_lines.append(f'🤖 {auto["icon"]} {auto["name"]}')
        else:
            rank_lines.append('🤖 Brak rangi (cywil)')
        for sr in specials:
            badge = '👑' if sr.get('is_owner_only') else '🎖️'
            rank_lines.append(f'{badge} {sr["icon"]} {sr["name"]}')
        e.add_field(name='⭐ Rangi', value='\n'.join(rank_lines), inline=False)
        if next_r:
            from_pts = auto['required_points'] if auto else 0
            bar = _prog_bar(u['points'], next_r['required_points'], from_pts)
            e.add_field(name=f'Postęp → {next_r["icon"]} {next_r["name"]}', value=bar, inline=False)
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
        if next_r:
            e.set_footer(text=f'Do rangi {next_r["name"]}: {next_r["required_points"]-u["points"]:.1f} pkt')
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

    # ══════════════════════════════════════════════════════════════════════════
    # EKONOMIA
    # ══════════════════════════════════════════════════════════════════════════

    async def _cmd_balance(self, msg, args):
        if not await self._check_perm(msg, 'balance'): return
        m = self._resolve_member(msg, args[0]) if args else msg.author
        if not m:
            await msg.reply(embed=discord.Embed(description='❌ Nie znaleziono.', color=RED),
                            mention_author=False); return
        db.ensure_user(m.id, msg.guild.id, str(m), m.display_name)
        w = db.get_wallet(m.id, msg.guild.id)
        total = w['cash'] + w['bank']
        e = discord.Embed(title=f'{COIN} Portfel – {m.display_name}', color=GOLD)
        e.set_thumbnail(url=m.display_avatar.url)
        e.add_field(name='💵 Gotówka', value=_fmt_money(w['cash']), inline=True)
        e.add_field(name='🏦 Bank',    value=_fmt_money(w['bank']), inline=True)
        e.add_field(name='💰 Łącznie', value=_fmt_money(total), inline=True)
        await msg.reply(embed=e, mention_author=False)

    async def _cmd_daily(self, msg, args):
        if not await self._check_perm(msg, 'daily'): return
        u = db.get_user(msg.author.id, msg.guild.id)
        cd = _check_cooldown(u.get('daily_last'), 60 * 24)  # 24h
        if cd:
            e = discord.Embed(description=f'⏳ Daily już odebrane! Wróć za **{_fmt_cd(cd)}**.', color=RED)
            await msg.reply(embed=e, mention_author=False); return
        reward = random.randint(100, 200)
        mopsy_mult = db.get_event_multiplier(msg.guild.id, 'mopsy')
        reward = int(reward * mopsy_mult)
        db.add_cash(msg.author.id, msg.guild.id, reward)
        db.set_cooldown(msg.author.id, msg.guild.id, 'daily_last')
        w = db.get_wallet(msg.author.id, msg.guild.id)
        e = discord.Embed(title=f'{COIN} Daily Reward!', color=GOLD)
        e.description = f'Otrzymałeś {_fmt_money(reward)}!\nStań się bogatszy jutro o kolejną nagrodę.'
        e.add_field(name='💵 Gotówka teraz', value=_fmt_money(w['cash']), inline=True)
        e.set_footer(text='Wróć za 24h po kolejną nagrodę!')
        await msg.reply(embed=e, mention_author=False)

    # ── Job flavour per job name (fallback → generic) ──────────────────────────
    _JOB_WORK = {
        'farmer':    [('zebrałeś plony','na polu'),('nakarmiłeś zwierzęta','w zagrodzie'),
                      ('zasadziłeś nowe nasiona','w ogrodzie'),('sprzedałeś warzywa','na targu')],
        'kowal':     [('wykułeś podkowy','przy kuźni'),('naprawiłeś zbroję','w warsztacie'),
                      ('ostrzyłeś miecze','dla gwardii'),('odlałeś nowe okucia','przy piecu')],
        'kupiec':    [('sprzedałeś towary','na placu'),('wynegocjowałeś kontrakt','z kupcem'),
                      ('przewiozłeś ładunek','przez miasto'),('otworzyłeś nowy stoisko','na targu')],
        'rajca':     [('przemawiałeś w radzie','na sesji'),('podpisałeś edykt','w ratuszu'),
                      ('zebrałeś podatki','od kupców'),('reprezentowałeś gildię','przed szlachtą')],
        'kierowca':  [('rozwiozłeś paczki','po całym mieście'),('dotarłeś na czas','mimo korków'),
                      ('załadowałeś ciężarówkę','w magazynie'),('zrobiłeś nocną trasę','przez autostradę')],
    }
    _JOB_BASE = [
        ('zbierałeś ziemniaki','na polu'),('rozwoziłeś pizzę','po mieście'),
        ('sprzątałeś biuro','na noc'),('pilnowałeś magazynu','przez całą zmianę'),
        ('naprawiałeś komputer','u sąsiada'),('sortowałeś paczki','w magazynie'),
    ]
    # cash bonus per work command per job name key (partial match)
    _JOB_WORK_BONUS = {
        'farmer': 20, 'kowal': 30, 'kupiec': 60, 'rajca': 100, 'kierowca': 150,
    }

    async def _cmd_work(self, msg, args):
        if not await self._check_perm(msg, 'work'): return
        u = db.get_user(msg.author.id, msg.guild.id)
        cd = _check_cooldown(u.get('work_last'), 60)  # 1h
        if cd:
            e = discord.Embed(description=f'⏳ Jesteś zmęczony! Odpocznij jeszcze **{_fmt_cd(cd)}**.', color=RED)
            await msg.reply(embed=e, mention_author=False); return

        # Check user's jobs for bonus and flavour text
        user_jobs = db.get_user_jobs(msg.author.id, msg.guild.id)
        bonus = 0
        flavour_pool = self._JOB_BASE
        job_names = []
        for j in user_jobs:
            jname = j.get('name', '').lower()
            job_names.append(jname)
            for key, b in self._JOB_WORK_BONUS.items():
                if key in jname:
                    bonus = max(bonus, b)
                    pool = self._JOB_WORK.get(key)
                    if pool:
                        flavour_pool = pool
                    break

        job_txt, place_txt = random.choice(flavour_pool)
        base = random.randint(30, 80)
        reward = base + random.randint(0, bonus)
        mopsy_mult = db.get_event_multiplier(msg.guild.id, 'mopsy')
        reward = int(reward * mopsy_mult)
        db.add_cash(msg.author.id, msg.guild.id, reward)
        db.set_cooldown(msg.author.id, msg.guild.id, 'work_last')
        w = db.get_wallet(msg.author.id, msg.guild.id)
        e = discord.Embed(title='💼 Praca', color=GREEN)
        e.description = f'Przez ostatnią godzinę **{job_txt}** {place_txt}.\nZarobiłeś {_fmt_money(reward)}!'
        if bonus > 0 and job_names:
            e.set_footer(text=f'Bonus z pracy: +{bonus} 🐾 | Możesz pracować znowu za 1h')
        else:
            e.set_footer(text='Możesz pracować znowu za 1h')
        e.add_field(name='💵 Gotówka teraz', value=_fmt_money(w['cash']), inline=True)
        await msg.reply(embed=e, mention_author=False)

    async def _cmd_job(self, msg, args):
        """Show / select / leave a job."""
        if not await self._check_perm(msg, 'job'): return
        gid = msg.guild.id
        uid = msg.author.id
        db.ensure_user(uid, gid, str(msg.author), msg.author.display_name)

        # .job leave [name]
        if args and args[0].lower() in ('leave', 'odejdź', 'rzuc', 'rzuć', 'quit'):
            leave_name = ' '.join(args[1:]).strip().lower()
            my_jobs = db.get_user_jobs(uid, gid)
            if not my_jobs:
                await msg.reply(embed=discord.Embed(description='❌ Nie masz żadnej pracy.', color=RED),
                                mention_author=False); return
            if not leave_name:
                if len(my_jobs) == 1:
                    target = my_jobs[0]
                else:
                    names = ', '.join(f'**{j["name"]}**' for j in my_jobs)
                    await msg.reply(embed=discord.Embed(description=f'❓ Podaj nazwę pracy: `.job leave <nazwa>`\nTwoje prace: {names}', color=YELLOW),
                                    mention_author=False); return
            else:
                target = next((j for j in my_jobs if leave_name in j['name'].lower()), None)
                if not target:
                    await msg.reply(embed=discord.Embed(description='❌ Nie znaleziono takiej pracy w Twoich stanowiskach.', color=RED),
                                    mention_author=False); return
            db.deselect_job(uid, gid, target['job_id'])
            await msg.reply(embed=discord.Embed(
                description=f'✅ Rzuciłeś pracę: **{target["icon"]} {target["name"]}**', color=ORANGE),
                mention_author=False)
            return

        # .job [name] — select a job
        if args:
            query = ' '.join(args).lower()
            all_jobs = db.get_jobs(gid)
            target = next((j for j in all_jobs if query in j['name'].lower()), None)
            if not target:
                await msg.reply(embed=discord.Embed(description=f'❌ Nie znaleziono pracy: `{query}`', color=RED),
                                mention_author=False); return
            user = db.get_user(uid, gid) or {}
            pts = user.get('points', 0) or 0
            if pts < target.get('required_points', 0):
                await msg.reply(embed=discord.Embed(
                    description=f'❌ Potrzebujesz **{target["required_points"]} pkt** żeby podjąć tę pracę. Masz **{pts:.1f} pkt**.', color=RED),
                    mention_author=False); return
            my_jobs = db.get_user_jobs(uid, gid)
            if any(j['job_id'] == target['id'] for j in my_jobs):
                await msg.reply(embed=discord.Embed(description=f'ℹ️ Już pracujesz jako **{target["name"]}**.', color=YELLOW),
                                mention_author=False); return
            db.select_job(uid, gid, target['id'])
            cph = target.get('cash_per_hour', 0) or 0
            e = discord.Embed(title=f'{target["icon"]} Podjąłeś pracę!', color=GREEN)
            e.description = (
                f'Teraz pracujesz jako **{target["name"]}**.\n'
                f'**Bonus pkt/h:** +{target.get("points_bonus_per_hour",0):.1f}\n'
                f'**Mopsy/h (clock-in):** +{cph:.0f} 🐾\n'
                f'**Bonus .work:** +{self._JOB_WORK_BONUS.get(next((k for k in self._JOB_WORK_BONUS if k in target["name"].lower()), ""), 0)} 🐾'
            )
            await msg.reply(embed=e, mention_author=False)
            return

        # .job — list
        all_jobs = db.get_jobs(gid)
        my_jobs  = db.get_user_jobs(uid, gid)
        my_ids   = {j['job_id'] for j in my_jobs}
        user     = db.get_user(uid, gid) or {}
        pts      = user.get('points', 0) or 0

        e = discord.Embed(title='💼 Prace na serwerze', color=BLURPLE)
        e.set_footer(text='.job <nazwa>  →  podjąć pracę  |  .job leave <nazwa>  →  rzucić')

        for j in all_jobs:
            cph = j.get('cash_per_hour', 0) or 0
            bpph = j.get('points_bonus_per_hour', 0) or 0
            work_bonus = self._JOB_WORK_BONUS.get(
                next((k for k in self._JOB_WORK_BONUS if k in j['name'].lower()), ''), 0)
            status = '✅' if j['id'] in my_ids else ('🔒' if pts < j.get('required_points', 0) else '🔓')
            val = (
                f'Wymagane pkt: **{j["required_points"]:.0f}**\n'
                f'Bonus pkt/h: **+{bpph:.1f}**\n'
                f'Mopsy/h: **+{cph:.0f} 🐾**\n'
                f'Bonus .work: **+{work_bonus} 🐾**'
            )
            e.add_field(name=f'{status} {j["icon"]} {j["name"]}', value=val, inline=True)

        if my_jobs:
            names = ', '.join(f'{j["icon"]} {j["name"]}' for j in my_jobs)
            e.description = f'**Twoje prace:** {names}'
        else:
            e.description = '**Twoje prace:** Brak — użyj `.job <nazwa>` żeby podjąć pracę'

        await msg.reply(embed=e, mention_author=False)

    async def _cmd_beg(self, msg, args):
        u = db.get_user(msg.author.id, msg.guild.id)
        cd = _check_cooldown(u.get('beg_last'), 30)  # 30min
        if cd:
            e = discord.Embed(description=f'⏳ Nie żebraj tak często! Poczekaj **{_fmt_cd(cd)}**.', color=RED)
            await msg.reply(embed=e, mention_author=False); return
        # 30% szans na niepowodzenie
        if random.random() < 0.30:
            db.set_cooldown(msg.author.id, msg.guild.id, 'beg_last')
            answers = ['Nikt ci nie dał.', 'Przechodnie cię zignorowali.', 'Zły dzień na żebranie.']
            e = discord.Embed(description=f'🚶 {random.choice(answers)}', color=ORANGE)
            await msg.reply(embed=e, mention_author=False); return
        reward = random.randint(1, 30)
        db.add_cash(msg.author.id, msg.guild.id, reward)
        db.set_cooldown(msg.author.id, msg.guild.id, 'beg_last')
        givers = ['staruszek', 'biznesmen', 'student', 'turysta', 'dziecko z rodziną']
        giver = random.choice(givers)
        e = discord.Embed(title='🙏 Żebranie', color=ORANGE)
        e.description = f'Litościwy {giver} dał ci {_fmt_money(reward)}.'
        e.set_footer(text='Możesz żebrać znowu za 30 min')
        await msg.reply(embed=e, mention_author=False)

    async def _cmd_pay(self, msg, args):
        if len(args) < 2:
            await msg.reply(embed=discord.Embed(description='❌ `.pay @user <kwota>`', color=RED),
                            mention_author=False); return
        target = self._resolve_member(msg, args[0])
        if not target or target.id == msg.author.id:
            await msg.reply(embed=discord.Embed(description='❌ Nieprawidłowy odbiorca.', color=RED),
                            mention_author=False); return
        try:
            amount = float(args[1])
            if amount <= 0: raise ValueError
        except ValueError:
            await msg.reply(embed=discord.Embed(description='❌ Nieprawidłowa kwota.', color=RED),
                            mention_author=False); return
        db.ensure_user(target.id, msg.guild.id, str(target), target.display_name)
        ok = db.transfer_cash(msg.author.id, target.id, msg.guild.id, amount)
        if not ok:
            await msg.reply(embed=discord.Embed(description='❌ Nie masz tyle gotówki!', color=RED),
                            mention_author=False); return
        e = discord.Embed(title=f'{COIN} Przelew', color=GREEN)
        e.description = f'**{msg.author.display_name}** przelał {_fmt_money(amount)} → **{target.display_name}**'
        await msg.reply(embed=e, mention_author=False)

    async def _cmd_deposit(self, msg, args):
        if not await self._check_perm(msg, 'deposit'): return
        if not args:
            await msg.reply(embed=discord.Embed(description='❌ `.deposit <kwota|all>`', color=RED),
                            mention_author=False); return
        w = db.get_wallet(msg.author.id, msg.guild.id)
        if args[0].lower() == 'all':
            amount = w['cash']
        else:
            try:
                amount = float(args[0])
                if amount <= 0: raise ValueError
            except ValueError:
                await msg.reply(embed=discord.Embed(description='❌ Nieprawidłowa kwota.', color=RED),
                                mention_author=False); return
        ok = db.deposit_cash(msg.author.id, msg.guild.id, amount)
        if not ok:
            await msg.reply(embed=discord.Embed(description='❌ Nie masz tyle gotówki!', color=RED),
                            mention_author=False); return
        w = db.get_wallet(msg.author.id, msg.guild.id)
        e = discord.Embed(title='🏦 Depozyt', color=BLURPLE)
        e.description = f'Wpłacono {_fmt_money(amount)} do banku.'
        e.add_field(name='💵 Gotówka', value=_fmt_money(w['cash']), inline=True)
        e.add_field(name='🏦 Bank',    value=_fmt_money(w['bank']), inline=True)
        await msg.reply(embed=e, mention_author=False)

    async def _cmd_withdraw(self, msg, args):
        if not await self._check_perm(msg, 'withdraw'): return
        if not args:
            await msg.reply(embed=discord.Embed(description='❌ `.withdraw <kwota|all>`', color=RED),
                            mention_author=False); return
        w = db.get_wallet(msg.author.id, msg.guild.id)
        if args[0].lower() == 'all':
            amount = w['bank']
        else:
            try:
                amount = float(args[0])
                if amount <= 0: raise ValueError
            except ValueError:
                await msg.reply(embed=discord.Embed(description='❌ Nieprawidłowa kwota.', color=RED),
                                mention_author=False); return
        ok = db.withdraw_cash(msg.author.id, msg.guild.id, amount)
        if not ok:
            await msg.reply(embed=discord.Embed(description='❌ Nie masz tyle w banku!', color=RED),
                            mention_author=False); return
        w = db.get_wallet(msg.author.id, msg.guild.id)
        e = discord.Embed(title='🏦 Wypłata', color=BLURPLE)
        e.description = f'Wypłacono {_fmt_money(amount)} z banku.'
        e.add_field(name='💵 Gotówka', value=_fmt_money(w['cash']), inline=True)
        e.add_field(name='🏦 Bank',    value=_fmt_money(w['bank']), inline=True)
        await msg.reply(embed=e, mention_author=False)

    async def _cmd_shop(self, msg, args):
        if not await self._check_perm(msg, 'shop'): return
        e = discord.Embed(title=f'{COIN} Sklep – Zamiana Mopsów na Punkty', color=PURPLE)
        e.description = (
            f'Użyj `.buy <nr>` żeby kupić przedmiot.\n'
            f'Punkty są **4× cenniejsze** od mopsów — dlatego przelicznik jest korzystny dla aktywnych!\n\n'
        )
        lines = []
        for nr, name, cost, pts in SHOP_ITEMS:
            lines.append(f'`{nr}.` **{name}** – {cost} {COIN} → **+{pts} pkt**')
        e.add_field(name='Dostępne pakiety', value='\n'.join(lines), inline=False)
        e.set_footer(text='Mopsy zdobywasz przez .daily .work .beg')
        await msg.reply(embed=e, mention_author=False)

    async def _cmd_buy(self, msg, args):
        if not await self._check_perm(msg, 'buy'): return
        if not args or not args[0].isdigit():
            await msg.reply(embed=discord.Embed(description='❌ `.buy <nr_przedmiotu>` – użyj `.shop` żeby zobaczyć listę.', color=RED),
                            mention_author=False); return
        nr = int(args[0])
        item = next((i for i in SHOP_ITEMS if i[0] == nr), None)
        if not item:
            await msg.reply(embed=discord.Embed(description='❌ Nie ma takiego przedmiotu.', color=RED),
                            mention_author=False); return
        _, name, cost, pts = item
        discount = db.get_event_multiplier(msg.guild.id, 'shop')
        cost = int(cost * (1.0 - discount))
        w = db.get_wallet(msg.author.id, msg.guild.id)
        if w['cash'] < cost:
            brakuje = cost - w['cash']
            await msg.reply(embed=discord.Embed(
                description=f'❌ Brakuje ci {_fmt_money(brakuje)}!\nMasz tylko {_fmt_money(w["cash"])}.',
                color=RED), mention_author=False); return
        db.add_cash(msg.author.id, msg.guild.id, -cost)
        _old_rank = db.get_user_auto_rank(msg.author.id, msg.guild.id)
        new_pts = db.add_points(msg.author.id, msg.guild.id, pts,
                                note=f'Zakup w sklepie: {name}', transaction_type='shop')
        w2 = db.get_wallet(msg.author.id, msg.guild.id)
        e = discord.Embed(title=f'{COIN} Zakup udany!', color=GREEN)
        e.description = (
            f'Kupiłeś **{name}**!\n'
            f'Zapłacono: {_fmt_money(cost)}\n'
            f'Otrzymano: **+{pts} pkt**'
        )
        e.add_field(name='💵 Gotówka teraz', value=_fmt_money(w2['cash']), inline=True)
        e.add_field(name='💰 Punkty teraz', value=f'**{new_pts:.1f} pkt**', inline=True)
        # Sprawdź awans na rangę
        new_rank = db.get_user_auto_rank(msg.author.id, msg.guild.id)
        if new_rank and (not _old_rank or new_rank['id'] != _old_rank['id']):
            e.add_field(name='🎉 Awans!', value=f'Osiągnąłeś rangę **{new_rank["icon"]} {new_rank["name"]}**!', inline=False)
        await msg.reply(embed=e, mention_author=False)

    async def _cmd_ecolb(self, msg, args):
        top = db.get_eco_leaderboard(msg.guild.id, limit=10)
        if not top:
            await msg.reply(embed=discord.Embed(description='📭 Brak danych.', color=YELLOW),
                            mention_author=False); return
        e = discord.Embed(title=f'{COIN} Ranking Ekonomii', color=GOLD, timestamp=datetime.now())
        lines = []
        for i, u in enumerate(top):
            medal = MEDALS[i] if i < 3 else f'`{i+1}.`'
            member = msg.guild.get_member(u['user_id'])
            name = member.display_name if member else u.get('display_name') or str(u['user_id'])
            total = (u.get('cash') or 0) + (u.get('bank') or 0)
            lines.append(f'{medal} **{name}** – {int(total):,} {COIN}'.replace(',', ' '))
        e.description = '\n'.join(lines)
        await msg.reply(embed=e, mention_author=False)

    # ══════════════════════════════════════════════════════════════════════════
    # FUN / UTILITY
    # ══════════════════════════════════════════════════════════════════════════

    async def _cmd_8ball(self, msg, args):
        if not args:
            await msg.reply(embed=discord.Embed(description='❌ `.8ball <pytanie>`', color=RED),
                            mention_author=False); return
        question = ' '.join(args)
        answer, color = random.choice(BALL_ANSWERS)
        e = discord.Embed(title='🎱 Magic 8-Ball', color=color)
        e.add_field(name='❓ Pytanie', value=question, inline=False)
        e.add_field(name='🎱 Odpowiedź', value=f'**{answer}**', inline=False)
        await msg.reply(embed=e, mention_author=False)

    async def _cmd_coinflip(self, msg, args):
        result = random.choice([('🪙 Orzeł', GREEN), ('🪙 Reszka', BLURPLE)])
        e = discord.Embed(title='🪙 Rzut monetą', description=f'Wypadło: **{result[0]}**', color=result[1])
        await msg.reply(embed=e, mention_author=False)

    async def _cmd_roll(self, msg, args):
        # Formaty: .roll | .roll 20 | .roll 2d6 | .roll d100
        raw = args[0].lower() if args else '6'
        try:
            if 'd' in raw:
                parts = raw.split('d')
                count = int(parts[0]) if parts[0] else 1
                sides = int(parts[1])
                count = min(count, 20)
                sides = min(sides, 1000000)
                if count < 1 or sides < 2: raise ValueError
                rolls = [random.randint(1, sides) for _ in range(count)]
                desc = f'`{count}d{sides}` → {" + ".join(str(r) for r in rolls)}'
                if count > 1:
                    desc += f' = **{sum(rolls)}**'
                else:
                    desc = f'`d{sides}` → **{rolls[0]}**'
            else:
                sides = min(int(raw), 1000000)
                if sides < 2: raise ValueError
                result = random.randint(1, sides)
                desc = f'`d{sides}` → **{result}**'
        except Exception:
            await msg.reply(embed=discord.Embed(description='❌ `.roll [K]` lub `.roll [N]d[K]`', color=RED),
                            mention_author=False); return
        e = discord.Embed(title='🎲 Kość', description=desc, color=BLURPLE)
        await msg.reply(embed=e, mention_author=False)

    async def _cmd_choose(self, msg, args):
        if len(args) < 2:
            await msg.reply(embed=discord.Embed(description='❌ `.choose opcja1 opcja2 opcja3...`', color=RED),
                            mention_author=False); return
        choice = random.choice(args)
        e = discord.Embed(title='🤔 Wybór', color=PURPLE)
        e.add_field(name='Opcje', value=' | '.join(f'`{a}`' for a in args), inline=False)
        e.add_field(name='✅ Wybieram', value=f'**{choice}**', inline=False)
        await msg.reply(embed=e, mention_author=False)

    async def _cmd_avatar(self, msg, args):
        m = self._resolve_member(msg, args[0]) if args else msg.author
        if not m:
            await msg.reply(embed=discord.Embed(description='❌ Nie znaleziono.', color=RED),
                            mention_author=False); return
        e = discord.Embed(title=f'🖼️ Avatar – {m.display_name}', color=BLURPLE)
        e.set_image(url=m.display_avatar.url)
        e.description = f'[Link do avatara]({m.display_avatar.url})'
        await msg.reply(embed=e, mention_author=False)

    async def _cmd_serverinfo(self, msg, args):
        g = msg.guild
        bots   = sum(1 for m in g.members if m.bot)
        humans = g.member_count - bots
        e = discord.Embed(title=f'🌐 {g.name}', color=BLURPLE, timestamp=datetime.now())
        if g.icon:
            e.set_thumbnail(url=g.icon.url)
        e.add_field(name='👥 Członkowie', value=f'{humans} ludzi, {bots} botów', inline=True)
        e.add_field(name='📅 Serwer założony', value=g.created_at.strftime('%d.%m.%Y'), inline=True)
        e.add_field(name='👑 Właściciel', value=g.owner.mention if g.owner else '—', inline=True)
        e.add_field(name='💬 Kanały tekstowe', value=str(len(g.text_channels)), inline=True)
        e.add_field(name='🔊 Kanały głosowe', value=str(len(g.voice_channels)), inline=True)
        e.add_field(name='🎭 Role', value=str(len(g.roles)), inline=True)
        boost = g.premium_subscription_count or 0
        e.add_field(name='🚀 Boosty', value=f'{boost} (Tier {g.premium_tier})', inline=True)
        e.set_footer(text=f'ID: {g.id}')
        await msg.reply(embed=e, mention_author=False)

    async def _cmd_rep(self, msg, args):
        if not args:
            await msg.reply(embed=discord.Embed(description='❌ `.rep @user`', color=RED),
                            mention_author=False); return
        target = self._resolve_member(msg, args[0])
        if not target or target.id == msg.author.id or target.bot:
            await msg.reply(embed=discord.Embed(description='❌ Nie możesz dać repa sobie ani botowi.', color=RED),
                            mention_author=False); return
        u = db.get_user(msg.author.id, msg.guild.id)
        cd = _check_cooldown(u.get('rep_last'), 60 * 24)  # 24h
        if cd:
            e = discord.Embed(description=f'⏳ Możesz dać repa ponownie za **{_fmt_cd(cd)}**.', color=RED)
            await msg.reply(embed=e, mention_author=False); return
        db.ensure_user(target.id, msg.guild.id, str(target), target.display_name)
        db.update_user(target.id, msg.guild.id,
                       rep_points=(db.get_user(target.id, msg.guild.id).get('rep_points') or 0) + 1)
        db.set_cooldown(msg.author.id, msg.guild.id, 'rep_last')
        target_u = db.get_user(target.id, msg.guild.id)
        e = discord.Embed(title='⭐ Reputacja', color=GOLD)
        e.description = f'**{msg.author.display_name}** dał repa **{target.display_name}**!'
        e.add_field(name='⭐ Reputacja łącznie', value=str(target_u.get('rep_points') or 0), inline=True)
        e.set_footer(text='Możesz dać repa ponownie za 24h')
        await msg.reply(embed=e, mention_author=False)

    async def _cmd_poll(self, msg, args):
        if not args:
            await msg.reply(embed=discord.Embed(description='❌ `.poll <pytanie>`', color=RED),
                            mention_author=False); return
        question = ' '.join(args)
        e = discord.Embed(title='📊 Ankieta', description=f'**{question}**', color=BLURPLE,
                          timestamp=datetime.now())
        e.set_footer(text=f'Ankieta od {msg.author.display_name} | Zagłosuj reakcjami!')
        sent = await msg.channel.send(embed=e)
        await sent.add_reaction('✅')
        await sent.add_reaction('❌')
        try:
            await msg.delete()
        except Exception:
            pass

    async def _cmd_trivia(self, msg, args):
        q, correct, wrong = random.choice(TRIVIA)
        all_answers = wrong + [correct]
        random.shuffle(all_answers)
        labels = ['🇦', '🇧', '🇨', '🇩']
        correct_label = labels[all_answers.index(correct)]
        e = discord.Embed(title='🧠 Trivia!', description=f'**{q}**', color=PURPLE, timestamp=datetime.now())
        for i, ans in enumerate(all_answers):
            e.add_field(name=labels[i], value=ans, inline=True)
        e.set_footer(text='Masz 15 sekund! Zagłosuj flagą odpowiedzi.')
        sent = await msg.reply(embed=e, mention_author=False)
        for label in labels[:len(all_answers)]:
            await sent.add_reaction(label)
        await asyncio.sleep(15)
        e2 = discord.Embed(title='🧠 Trivia – Odpowiedź!', color=GREEN)
        e2.description = f'**Pytanie:** {q}\n✅ **Poprawna odpowiedź:** {correct_label} **{correct}**'
        await msg.channel.send(embed=e2)

    # ══════════════════════════════════════════════════════════════════════════
    # POMOC
    # ══════════════════════════════════════════════════════════════════════════

    async def _cmd_help(self, msg, args):
        gid = msg.guild.id
        cfg = db.get_guild(gid) or {}
        try:
            admin_ids = json.loads(cfg.get('admin_role_ids') or '[]')
        except Exception:
            admin_ids = []
        is_admin = (msg.author.guild_permissions.administrator or
                    any(r.id in admin_ids for r in msg.author.roles))

        def _user_perm(cmd):
            perm = db.get_command_permission(gid, cmd)
            if perm:
                try:
                    allowed = json.loads(perm['allowed_role_ids'])
                except Exception:
                    allowed = []
                if allowed:
                    return (msg.author.guild_permissions.administrator or
                            any(r.id in allowed for r in msg.author.roles))
            return True

        def _admin_perm(cmd):
            perm = db.get_command_permission(gid, cmd)
            if perm:
                try:
                    allowed = json.loads(perm['allowed_role_ids'])
                except Exception:
                    allowed = []
                if allowed:
                    return (msg.author.guild_permissions.administrator or
                            any(r.id in allowed for r in msg.author.roles))
            return is_admin

        e = discord.Embed(title='📖 Pomoc – BazaMops Bot',
                          description='Prefix: **`.`**',
                          color=BLURPLE)

        # Rangi
        rank_user = [
            ('points',  '`.points [@user]`',  'punkty, ranga, postęp'),
            ('rank',    '`.rank [@user]`',    'ranga auto + specjalne'),
            ('lb',      '`.lb`',              'ranking top 10'),
            ('history', '`.history`',         'historia sesji'),
            ('profile', '`.profile [@user]`', 'pełny profil'),
            ('clock',   '`.clock`',           'status zalogowania'),
        ]
        rank_lines = [f'{s} – {d}' for cmd, s, d in rank_user if _user_perm(cmd)]
        e.add_field(name='⭐ Rangi i Punkty', inline=False,
                    value='\n'.join(rank_lines) or '*Brak*')

        # Ekonomia
        eco_user = [
            ('balance',  '`.balance [@user]`',       'portfel: gotówka + bank'),
            ('daily',    '`.daily`',                  f'dzienna nagroda {COIN} (24h)'),
            ('work',     '`.work`',                   f'zarabiaj {COIN} (1h cooldown)'),
            ('beg',      '`.beg`',                    f'żebraj o {COIN} (30min cooldown)'),
            ('pay',      '`.pay @user <kwota>`',      f'przelej {COIN} innemu'),
            ('deposit',  '`.deposit <kwota|all>`',    f'wpłać do banku'),
            ('withdraw', '`.withdraw <kwota|all>`',   f'wypłać z banku'),
            ('shop',     '`.shop`',                   f'sklep – zamień {COIN} na punkty'),
            ('buy',      '`.buy <nr>`',               f'kup przedmiot ze sklepu'),
            ('eco',      '`.eco`',                    f'ranking bogaczy'),
        ]
        eco_lines = [f'{s} – {d}' for cmd, s, d in eco_user if _user_perm(cmd)]
        e.add_field(name=f'{COIN} Ekonomia', inline=False,
                    value='\n'.join(eco_lines) or '*Brak*')

        # Minigry
        mini_user = [
            ('slots', f'`.slots [stawka]`',  f'automat {COIN} (cooldown 2min)'),
            ('fish',  f'`.fish`',            f'wędkowanie {COIN} (45min)'),
            ('mine',  f'`.mine`',            f'kopalnia {COIN} (1h)'),
            ('hunt',  f'`.hunt`',            f'polowanie {COIN} (1h)'),
        ]
        mini_lines = [f'{s} – {d}' for cmd, s, d in mini_user if _user_perm(cmd)]
        e.add_field(name='🎰 Minigry', inline=False,
                    value='\n'.join(mini_lines) or '*Brak*')

        # Fun
        fun_user = [
            ('8ball',      '`.8ball <pytanie>`',          'wróżba'),
            ('coinflip',   '`.coinflip`',                 'orzeł czy reszka'),
            ('roll',       '`.roll [Nd][K]`',             'rzuć kością (np. 2d6)'),
            ('choose',     '`.choose op1 op2 op3`',       'wybierz losowo'),
            ('joke',       '`.joke`',                     'losowy dowcip'),
            ('quote',      '`.quote`',                    'losowy cytat'),
            ('owo',        '`.owo <tekst>`',              'owifikacja tekstu'),
            ('hug',        '`.hug [@user]`',              'przytul kogoś'),
            ('pat',        '`.pat [@user]`',              'pogłaszcz kogoś'),
            ('slap',       '`.slap [@user]`',             'daj liścia'),
            ('gg',         '`.gg [@user]`',               'pogratuluj'),
            ('avatar',     '`.avatar [@user]`',           'pokaż avatar'),
            ('serverinfo', '`.serverinfo`',               'info o serwerze'),
            ('roleinfo',   '`.roleinfo @rola`',           'info o roli'),
            ('rep',        '`.rep @user`',                'daj punkt reputacji (24h)'),
            ('poll',       '`.poll <pytanie>`',           'utwórz ankietę'),
            ('trivia',     '`.trivia`',                   'losowe pytanie quizowe'),
        ]
        fun_lines = [f'{s} – {d}' for cmd, s, d in fun_user if _user_perm(cmd)]
        e.add_field(name='🎮 Fun', inline=False,
                    value='\n'.join(fun_lines) or '*Brak*')

        # Utility
        util_user = [
            ('ping',      '`.ping`',                   'latencja bota'),
            ('uptime',    '`.uptime`',                 'czas działania bota'),
            ('remindme',  '`.remindme <czas> <tekst>`','ustaw przypomnienie'),
            ('tag',       '`.tag <nazwa>`',            'wyświetl tag serwera'),
            ('taglist',   '`.taglist`',                'lista tagów serwera'),
        ]
        util_lines = [f'{s} – {d}' for cmd, s, d in util_user if _user_perm(cmd)]
        e.add_field(name='🔧 Narzędzia', inline=False,
                    value='\n'.join(util_lines) or '*Brak*')

        e.add_field(name='ℹ️ Inne', value='`.help` – ta wiadomość', inline=False)

        if not is_admin:
            await msg.reply(embed=e, mention_author=False)
            return

        # Admin sekcje
        pts_defs = [
            ('addpoints',    '`.addpoints @u <n>`'),
            ('removepoints', '`.removepoints @u <n>`'),
            ('setpoints',    '`.setpoints @u <n>`'),
        ]
        pts_lines = [s for cmd, s in pts_defs if _admin_perm(cmd)]
        if pts_lines:
            e.add_field(name='🔨 Admin – Punkty', inline=False, value='  '.join(pts_lines))

        mod_defs = [
            ('warn',      '`.warn @u [powód]`'),
            ('warnpoints','`.warnpoints @u [powód]`'),
            ('warnlb',    '`.warnlb`'),
            ('warnings',  '`.warnings [@u]`'),
            ('clearwarn', '`.clearwarn @u [id]`'),
            ('mute',      '`.mute @u [czas] [powód]`'),
            ('unmute',    '`.unmute @u`'),
            ('kick',      '`.kick @u [powód]`'),
            ('tempban',   '`.tempban @u <czas> [powód]`'),
            ('softban',   '`.softban @u [powód]`'),
            ('purge',     '`.purge <n>`'),
            ('slowmode',  '`.slowmode <s>`'),
            ('note',      '`.note @u <treść>`'),
            ('notes',     '`.notes @u`'),
        ]
        mod_lines = [s for cmd, s in mod_defs if _admin_perm(cmd)]
        if mod_lines:
            e.add_field(name='🔨 Admin – Moderacja', inline=False, value='\n'.join(mod_lines))

        eco_admin = [
            ('addmoney',    '`.addmoney @u <n>`'),
            ('removemoney', '`.removemoney @u <n>`'),
            ('setmoney',    '`.setmoney @u <n>`'),
        ]
        eco_lines2 = [s for cmd, s in eco_admin if _admin_perm(cmd)]
        if eco_lines2:
            e.add_field(name='🔨 Admin – Ekonomia', inline=False, value='  '.join(eco_lines2))

        rank_defs = [
            ('giverank',   '`.giverank @u <ranga>`'),
            ('takerank',   '`.takerank @u <ranga>`'),
            ('createrank', '`.createrank <n> <pkt|SPECIAL|UNIT>`'),
            ('deleterank', '`.deleterank <n>`'),
            ('editrank',   '`.editrank <n> <pole> <wartość>`'),
            ('ranks',      '`.ranks`'),
        ]
        rank_lines2 = [s for cmd, s in rank_defs if _admin_perm(cmd)]
        if rank_lines2:
            e.add_field(name='🔨 Admin – Rangi', inline=False, value='  '.join(rank_lines2))

        mgmt_defs = [
            ('userinfo',      '`.userinfo @u`'),
            ('ban',           '`.ban @u`'),
            ('unban',         '`.unban @u`'),
            ('forceclockout', '`.forceclockout @u`'),
            ('resetuser',     '`.resetuser @u`'),
            ('serverstats',   '`.serverstats`'),
            ('config',        '`.config`'),
        ]
        mgmt_lines = [s for cmd, s in mgmt_defs if _admin_perm(cmd)]
        if mgmt_lines:
            e.add_field(name='🔨 Admin – Zarządzanie', inline=False, value='  '.join(mgmt_lines))

        e.add_field(name='🔨 Admin – Setup',
                    value='`.setchannel` `.setpoints_h` `.adminrole` `.setwarnlimit` `.setmaxhours`',
                    inline=False)

        chan_defs = [
            ('lock',     '`.lock [#ch]`'),
            ('unlock',   '`.unlock [#ch]`'),
            ('hide',     '`.hide [#ch]`'),
            ('unhide',   '`.unhide [#ch]`'),
            ('announce', '`.announce #ch <tekst>`'),
            ('nick',     '`.nick @u <nick|reset>`'),
            ('move',     '`.move @u #voice`'),
            ('deafen',   '`.deafen @u`'),
            ('undeafen', '`.undeafen @u`'),
        ]
        chan_lines = [s for cmd, s in chan_defs if _admin_perm(cmd)]
        if chan_lines:
            e.add_field(name='🔨 Admin – Kanały i głos', inline=False,
                        value='  '.join(chan_lines))

        tag_defs = [('tag', '`.tag create/edit/delete/list <nazwa> [treść]`')]
        tag_lines = [s for cmd, s in tag_defs if _admin_perm(cmd)]
        if tag_lines:
            e.add_field(name='🏷️ Admin – Tagi', inline=False, value='  '.join(tag_lines))

        await msg.reply(embed=e, mention_author=False)


    # ══════════════════════════════════════════════════════════════════════════
    # BLACKJACK / HIGHLOW / SCRATCH / RPS (Dank Memer style)
    # ══════════════════════════════════════════════════════════════════════════

    @staticmethod
    def _bj_deck():
        suits = ['♠', '♥', '♦', '♣']
        ranks = ['A','2','3','4','5','6','7','8','9','10','J','Q','K']
        deck = [(r, s) for s in suits for r in ranks]
        random.shuffle(deck)
        return deck

    @staticmethod
    def _bj_val(hand):
        total, aces = 0, 0
        for r, _ in hand:
            if r in ('J','Q','K'): total += 10
            elif r == 'A': total += 11; aces += 1
            else: total += int(r)
        while total > 21 and aces:
            total -= 10; aces -= 1
        return total

    @staticmethod
    def _bj_str(hand, hide=False):
        if hide: return f'{hand[0][0]}{hand[0][1]} 🂠'
        return ' '.join(f'{r}{s}' for r, s in hand)

    async def _cmd_blackjack(self, msg, args):
        """Blackjack z opcjonalną stawką mopsów."""
        if not await self._check_perm(msg, 'blackjack'): return
        bet = 0
        if args and args[0].isdigit():
            bet = int(args[0])
            if bet < 10:
                await msg.reply(embed=discord.Embed(description='❌ Min. stawka to **10** 🐾.', color=RED),
                                mention_author=False); return
            w = db.get_wallet(msg.author.id, msg.guild.id)
            if w['cash'] < bet:
                await msg.reply(embed=discord.Embed(
                    description=f'❌ Masz tylko **{int(w["cash"])}** 🐾!', color=RED),
                    mention_author=False); return
            db.add_cash(msg.author.id, msg.guild.id, -bet)

        deck = self._bj_deck()
        ph = [deck.pop(), deck.pop()]
        dh = [deck.pop(), deck.pop()]

        def make_embed(hide=True, result=None):
            pv = self._bj_val(ph)
            e = discord.Embed(title='🃏 Blackjack', color=GOLD)
            dv_show = '??' if hide else str(self._bj_val(dh))
            e.add_field(name=f'🤖 Krupier ({dv_show})', value=self._bj_str(dh, hide), inline=False)
            e.add_field(name=f'👤 Ty ({pv})', value=self._bj_str(ph), inline=False)
            if bet: e.add_field(name='Stawka', value=f'{bet} 🐾', inline=True)
            if result: e.add_field(name='📊 Wynik', value=result, inline=False)
            return e

        # Check natural blackjack
        if self._bj_val(ph) == 21:
            win = int(bet * 2.5) if bet else 0
            if bet: db.add_cash(msg.author.id, msg.guild.id, win)
            await msg.reply(embed=make_embed(False, f'🎉 BLACKJACK!{f" +{win} 🐾" if bet else ""}'),
                            mention_author=False); return

        finished = [False]

        class BJView(discord.ui.View):
            def __init__(vself):
                super().__init__(timeout=60)

            async def _end(vself, interaction, result_text):
                finished[0] = True
                for item in vself.children: item.disabled = True
                await interaction.response.edit_message(embed=make_embed(False, result_text), view=vself)

            @discord.ui.button(label='Hit 🃏', style=discord.ButtonStyle.green)
            async def hit(vself, interaction, button):
                if interaction.user.id != msg.author.id:
                    await interaction.response.send_message('To nie twoja gra!', ephemeral=True); return
                ph.append(deck.pop())
                pv = self._bj_val(ph)
                if pv > 21:
                    if bet: db.add_cash(msg.author.id, msg.guild.id, 0)  # already deducted
                    await vself._end(interaction, f'💥 Bust! ({pv}). Przegrałeś{f" {bet} 🐾" if bet else ""}.')
                elif pv == 21:
                    await vself.stand.callback(vself, interaction, button)
                else:
                    await interaction.response.edit_message(embed=make_embed(), view=vself)

            @discord.ui.button(label='Stand ✋', style=discord.ButtonStyle.red)
            async def stand(vself, interaction, button):
                if interaction.user.id != msg.author.id:
                    await interaction.response.send_message('To nie twoja gra!', ephemeral=True); return
                while self._bj_val(dh) < 17: dh.append(deck.pop())
                pv, dv = self._bj_val(ph), self._bj_val(dh)
                if dv > 21 or pv > dv:
                    mult = 2.5 if pv == 21 and len(ph) == 2 else 2
                    win = int(bet * mult) if bet else 0
                    if bet: db.add_cash(msg.author.id, msg.guild.id, win)
                    res = f'🎉 Wygrałeś{f" +{win} 🐾" if bet else ""}!{"(BJ ×2.5)" if mult==2.5 else ""}'
                elif pv == dv:
                    if bet: db.add_cash(msg.author.id, msg.guild.id, bet)
                    res = '🤝 Remis! Stawka zwrócona.'
                else:
                    res = f'😔 Przegrałeś{f" {bet} 🐾" if bet else ""}. (krupier: {dv})'
                await vself._end(interaction, res)

            async def on_timeout(vself):
                if not finished[0]:
                    for item in vself.children: item.disabled = True

        await msg.reply(embed=make_embed(), view=BJView(), mention_author=False)

    async def _cmd_highlow(self, msg, args):
        """Zgadnij czy następna liczba będzie wyższa czy niższa."""
        if not await self._check_perm(msg, 'highlow'): return
        current = random.randint(1, 100)
        e = discord.Embed(title='🔢 High or Low?', color=BLURPLE)
        e.description = f'Liczba to: **{current}**\nCzy następna będzie **wyższa** czy **niższa**?'
        e.set_footer(text='Masz 30 sekund!')

        finished = [False]

        class HLView(discord.ui.View):
            def __init__(vself): super().__init__(timeout=30)

            async def _resolve(vself, interaction, guess):
                if interaction.user.id != msg.author.id:
                    await interaction.response.send_message('To nie twoja gra!', ephemeral=True); return
                if finished[0]: return
                finished[0] = True
                nxt = random.randint(1, 100)
                correct = (guess == 'high' and nxt > current) or (guess == 'low' and nxt < current)
                reward = random.randint(20, 60) if correct else 0
                if correct: db.add_cash(msg.author.id, msg.guild.id, reward)
                for item in vself.children: item.disabled = True
                color = GREEN if correct else RED
                res = discord.Embed(title='🔢 High or Low?', color=color)
                res.description = (
                    f'Poprzednia: **{current}** → Następna: **{nxt}**\n'
                    f'{"✅ Zgadłeś!" if correct else "❌ Nie zgadłeś."}'
                    f'{f" +{reward} 🐾" if correct else ""}'
                )
                await interaction.response.edit_message(embed=res, view=vself)

            @discord.ui.button(label='⬆️ Wyżej', style=discord.ButtonStyle.green)
            async def high(vself, interaction, button): await vself._resolve(interaction, 'high')

            @discord.ui.button(label='⬇️ Niżej', style=discord.ButtonStyle.red)
            async def low(vself, interaction, button):  await vself._resolve(interaction, 'low')

        await msg.reply(embed=e, view=HLView(), mention_author=False)

    async def _cmd_scratch(self, msg, args):
        """Zdrap los – postaw 30 🐾 żeby wygrać więcej."""
        if not await self._check_perm(msg, 'scratch'): return
        COST = 30
        w = db.get_wallet(msg.author.id, msg.guild.id)
        if w['cash'] < COST:
            await msg.reply(embed=discord.Embed(
                description=f'❌ Los kosztuje **{COST}** 🐾. Masz tylko **{int(w["cash"])}** 🐾.',
                color=RED), mention_author=False); return
        db.add_cash(msg.author.id, msg.guild.id, -COST)

        SYM = ['🍒','🍒','🍒','🍋','🍋','⭐','⭐','💎','🍀','💰']
        grid = [random.choice(SYM) for _ in range(9)]
        # Check wins (3 in a row: rows + cols + diags)
        lines = [
            grid[0:3], grid[3:6], grid[6:9],
            grid[0::3], grid[1::3], grid[2::3],
            [grid[0],grid[4],grid[8]], [grid[2],grid[4],grid[6]]
        ]
        prizes = {'🍒':30,'🍋':50,'⭐':100,'🍀':200,'💎':500,'💰':1000}
        won = 0
        winning_sym = None
        for line in lines:
            if line[0] == line[1] == line[2]:
                p = prizes.get(line[0], 0)
                if p > won: won = p; winning_sym = line[0]

        if won: db.add_cash(msg.author.id, msg.guild.id, won)
        w2 = db.get_wallet(msg.author.id, msg.guild.id)
        g = '\n'.join(' '.join(grid[i*3:(i+1)*3]) for i in range(3))
        e = discord.Embed(title='🎟️ Los na Szczęście', color=GOLD if won else ORANGE)
        e.description = f'```\n{g}\n```'
        if won:
            e.add_field(name='🎉 Wygrana!', value=f'{winning_sym} × 3 → **+{won} 🐾**', inline=True)
        else:
            e.add_field(name='😔 Brak wygranej', value=f'Straciłeś {COST} 🐾', inline=True)
        e.add_field(name='💵 Gotówka', value=f'{int(w2["cash"])} 🐾', inline=True)
        await msg.reply(embed=e, mention_author=False)

    async def _cmd_rps(self, msg, args):
        """Kamień, papier, nożyce vs bot."""
        if not await self._check_perm(msg, 'rps'): return
        if not args:
            await msg.reply(embed=discord.Embed(
                description='❌ `.rps <kamien|papier|nozyce>` lub `rock|paper|scissors`', color=RED),
                mention_author=False); return
        choices_map = {
            'kamien':'rock','rock':'rock','k':'rock','r':'rock',
            'papier':'paper','paper':'paper','p':'paper',
            'nozyce':'scissors','scissors':'scissors','n':'scissors','s':'scissors',
        }
        user_choice = choices_map.get(args[0].lower())
        if not user_choice:
            await msg.reply(embed=discord.Embed(
                description='❌ Użyj: `kamien`, `papier` lub `nozyce`', color=RED),
                mention_author=False); return
        bot_choice = random.choice(['rock','paper','scissors'])
        emoji = {'rock':'🪨','paper':'📄','scissors':'✂️'}
        names = {'rock':'Kamień','paper':'Papier','scissors':'Nożyce'}
        wins = {('rock','scissors'),('paper','rock'),('scissors','paper')}
        if user_choice == bot_choice:
            color, result = YELLOW, '🤝 Remis!'
        elif (user_choice, bot_choice) in wins:
            color, result = GREEN, '🎉 Wygrałeś!'
        else:
            color, result = RED, '😔 Przegrałeś!'
        e = discord.Embed(title='✊ Kamień Papier Nożyce', color=color)
        e.add_field(name='👤 Ty', value=f'{emoji[user_choice]} {names[user_choice]}', inline=True)
        e.add_field(name='🤖 Bot', value=f'{emoji[bot_choice]} {names[bot_choice]}', inline=True)
        e.add_field(name='Wynik', value=f'**{result}**', inline=False)
        await msg.reply(embed=e, mention_author=False)

    # ══════════════════════════════════════════════════════════════════════════
    # MINIGRY EKONOMICZNE (Tatsu / Dank Memer style)
    # ══════════════════════════════════════════════════════════════════════════

    async def _cmd_slots(self, msg, args):
        """Slot machine – opcjonalnie postaw mopsy."""
        if not await self._check_perm(msg, 'slots'): return
        u = db.get_user(msg.author.id, msg.guild.id)
        cd = _check_cooldown(u.get('slots_last'), 2)  # 2min
        if cd:
            await msg.reply(embed=discord.Embed(
                description=f'⏳ Automat w serwisie! Wróć za **{_fmt_cd(cd)}**.', color=RED),
                mention_author=False); return

        bet = 0
        if args and args[0].isdigit():
            bet = int(args[0])
            w = db.get_wallet(msg.author.id, msg.guild.id)
            if bet < 10:
                await msg.reply(embed=discord.Embed(description='❌ Minimalna stawka to **10** 🐾.', color=RED),
                                mention_author=False); return
            if w['cash'] < bet:
                await msg.reply(embed=discord.Embed(
                    description=f'❌ Nie masz tyle! Masz **{int(w["cash"])}** 🐾.', color=RED),
                    mention_author=False); return
            db.add_cash(msg.author.id, msg.guild.id, -bet)

        SYMBOLS = ['🍒', '🍋', '🍊', '🍇', '⭐', '💎']
        WEIGHTS  = [30,   25,   20,   15,   7,    3  ]
        reels = random.choices(SYMBOLS, weights=WEIGHTS, k=3)

        if reels[0] == reels[1] == reels[2]:
            symbol = reels[0]
            mults = {'💎': 20, '⭐': 10, '🍇': 6, '🍊': 4, '🍋': 3, '🍒': 2}
            mult = mults.get(symbol, 2)
            if bet:
                win = bet * mult
                db.add_cash(msg.author.id, msg.guild.id, win)
                result_text = f'🎉 **JACKPOT!** {symbol}{symbol}{symbol} × {mult}\n+{_fmt_money(win)}'
                color = GOLD
            else:
                result_text = f'🎉 **JACKPOT!** {symbol}{symbol}{symbol}'
                color = GOLD
        elif reels[0] == reels[1] or reels[1] == reels[2]:
            if bet:
                win = bet
                db.add_cash(msg.author.id, msg.guild.id, win)
                result_text = f'✅ Dwa takie same! {" ".join(reels)}\nOdzyskujesz {_fmt_money(win)}'
                color = GREEN
            else:
                result_text = f'✅ Dwa takie same! {" ".join(reels)}'
                color = GREEN
        else:
            result_text = f'💸 Nic. {" ".join(reels)}'
            color = RED
            if bet:
                result_text += f'\nStrata: {_fmt_money(bet)}'

        db.set_cooldown(msg.author.id, msg.guild.id, 'slots_last')
        e = discord.Embed(title='🎰 Automat', description=result_text, color=color)
        if bet:
            w2 = db.get_wallet(msg.author.id, msg.guild.id)
            e.set_footer(text=f'Gotówka: {int(w2["cash"])} 🐾 | Cooldown: 2 min')
        await msg.reply(embed=e, mention_author=False)

    async def _cmd_fish(self, msg, args):
        if not await self._check_perm(msg, 'fish'): return
        u = db.get_user(msg.author.id, msg.guild.id)
        cd = _check_cooldown(u.get('fish_last'), 45)  # 45min
        if cd:
            await msg.reply(embed=discord.Embed(
                description=f'⏳ Ryby jeszcze nie wróciły! Wróć za **{_fmt_cd(cd)}**.', color=RED),
                mention_author=False); return
        catches = [
            ('🐟 Śledź', 5, 20), ('🐠 Rybka tropikalna', 15, 40),
            ('🐡 Ryba rozdymka', 20, 50), ('🦈 Rekin', 80, 150),
            ('🐙 Ośmiornica', 50, 100), ('🦞 Homar', 60, 120),
            ('🐚 Muszla', 2, 10), ('👢 Stary but', 0, 0),
            ('💎 Skarb zatopiony', 200, 350),
        ]
        weights = [25, 20, 15, 5, 10, 8, 10, 5, 2]
        name, mn, mx = random.choices(catches, weights=weights, k=1)[0]
        reward = random.randint(mn, mx) if mx > 0 else 0
        mopsy_mult = db.get_event_multiplier(msg.guild.id, 'mopsy')
        reward = int(reward * mopsy_mult)
        db.add_cash(msg.author.id, msg.guild.id, reward)
        db.set_cooldown(msg.author.id, msg.guild.id, 'fish_last')
        w = db.get_wallet(msg.author.id, msg.guild.id)
        if reward > 0:
            e = discord.Embed(title='🎣 Wędkowanie', color=BLURPLE)
            e.description = f'Złowiłeś **{name}**!\nZarobiłeś {_fmt_money(reward)}.'
        else:
            e = discord.Embed(title='🎣 Wędkowanie', color=ORANGE)
            e.description = f'Wyciągnąłeś **{name}**... Nic nie zarobisz tym razem.'
        e.set_footer(text=f'Gotówka: {int(w["cash"])} 🐾 | Cooldown: 45 min')
        await msg.reply(embed=e, mention_author=False)

    async def _cmd_mine(self, msg, args):
        if not await self._check_perm(msg, 'mine'): return
        u = db.get_user(msg.author.id, msg.guild.id)
        cd = _check_cooldown(u.get('mine_last'), 60)  # 1h
        if cd:
            await msg.reply(embed=discord.Embed(
                description=f'⏳ Jesteś zmęczony kopaniem! Wróć za **{_fmt_cd(cd)}**.', color=RED),
                mention_author=False); return
        finds = [
            ('⛏️ Kamień', 1, 5), ('🪨 Skała', 2, 8),
            ('🪵 Drewno (znalazłeś w kopalni?)', 5, 15),
            ('🔩 Żelazo', 15, 35), ('🥈 Srebro', 30, 60),
            ('🥇 Złoto', 60, 100), ('💎 Diament', 150, 300),
            ('💣 Dynamit (eksplodował)', 0, 0),
        ]
        weights = [20, 18, 10, 20, 15, 10, 5, 2]
        name, mn, mx = random.choices(finds, weights=weights, k=1)[0]
        reward = random.randint(mn, mx) if mx > 0 else 0
        mopsy_mult = db.get_event_multiplier(msg.guild.id, 'mopsy')
        reward = int(reward * mopsy_mult)
        db.add_cash(msg.author.id, msg.guild.id, reward)
        db.set_cooldown(msg.author.id, msg.guild.id, 'mine_last')
        w = db.get_wallet(msg.author.id, msg.guild.id)
        if reward > 0:
            e = discord.Embed(title='⛏️ Kopalnia', color=ORANGE)
            e.description = f'Wykopałeś **{name}**!\nZarobiłeś {_fmt_money(reward)}.'
        else:
            e = discord.Embed(title='⛏️ Kopalnia', color=RED)
            e.description = f'Trafiłeś na **{name}**... Nic nie zarobiłeś.'
        e.set_footer(text=f'Gotówka: {int(w["cash"])} 🐾 | Cooldown: 1h')
        await msg.reply(embed=e, mention_author=False)

    async def _cmd_hunt(self, msg, args):
        if not await self._check_perm(msg, 'hunt'): return
        u = db.get_user(msg.author.id, msg.guild.id)
        cd = _check_cooldown(u.get('hunt_last'), 60)  # 1h
        if cd:
            await msg.reply(embed=discord.Embed(
                description=f'⏳ Zwierzęta się schowały! Wróć za **{_fmt_cd(cd)}**.', color=RED),
                mention_author=False); return
        prey = [
            ('🐇 Królik', 10, 25), ('🦆 Kaczka', 15, 35),
            ('🦊 Lis', 30, 55), ('🐗 Dzik', 40, 70),
            ('🦌 Jeleń', 60, 100), ('🐻 Niedźwiedź', 100, 180),
            ('🦁 Lew (jak to możliwe?)', 200, 350),
            ('💨 Nic nie trafiłeś', 0, 0),
        ]
        weights = [20, 18, 15, 15, 12, 8, 2, 10]
        name, mn, mx = random.choices(prey, weights=weights, k=1)[0]
        reward = random.randint(mn, mx) if mx > 0 else 0
        mopsy_mult = db.get_event_multiplier(msg.guild.id, 'mopsy')
        reward = int(reward * mopsy_mult)
        db.add_cash(msg.author.id, msg.guild.id, reward)
        db.set_cooldown(msg.author.id, msg.guild.id, 'hunt_last')
        w = db.get_wallet(msg.author.id, msg.guild.id)
        if reward > 0:
            e = discord.Embed(title='🏹 Polowanie', color=GREEN)
            e.description = f'Upolowałeś **{name}**!\nZarobiłeś {_fmt_money(reward)}.'
        else:
            e = discord.Embed(title='🏹 Polowanie', color=ORANGE)
            e.description = '💨 Chybiłeś. Wszystkie zwierzęta uciekły.'
        e.set_footer(text=f'Gotówka: {int(w["cash"])} 🐾 | Cooldown: 1h')
        await msg.reply(embed=e, mention_author=False)

    # ══════════════════════════════════════════════════════════════════════════
    # SOCIAL / FUN (Tatsu style)
    # ══════════════════════════════════════════════════════════════════════════

    async def _cmd_hug(self, msg, args):
        if not await self._check_perm(msg, 'hug'): return
        target = self._resolve_member(msg, args[0]) if args else None
        GIFS = [
            'https://media.giphy.com/media/od5H3PmEG5EVq/giphy.gif',
            'https://media.giphy.com/media/lrr9rHuoJOE0w/giphy.gif',
            'https://media.giphy.com/media/3bqtLDeiDtwhq/giphy.gif',
        ]
        e = discord.Embed(color=PURPLE)
        if target:
            e.description = f'**{msg.author.display_name}** przytula **{target.display_name}**! 🤗'
        else:
            e.description = f'**{msg.author.display_name}** daje wszystkim buziaka! 🤗'
        e.set_image(url=random.choice(GIFS))
        await msg.reply(embed=e, mention_author=False)

    async def _cmd_pat(self, msg, args):
        if not await self._check_perm(msg, 'pat'): return
        target = self._resolve_member(msg, args[0]) if args else None
        GIFS = [
            'https://media.giphy.com/media/L2z7dnOduqEow/giphy.gif',
            'https://media.giphy.com/media/109ltuoSQT212w/giphy.gif',
        ]
        e = discord.Embed(color=PURPLE)
        if target:
            e.description = f'**{msg.author.display_name}** głaszcze **{target.display_name}**! 👋'
        else:
            e.description = f'**{msg.author.display_name}** głaszcze powietrze... 👋'
        e.set_image(url=random.choice(GIFS))
        await msg.reply(embed=e, mention_author=False)

    async def _cmd_slap(self, msg, args):
        if not await self._check_perm(msg, 'slap'): return
        target = self._resolve_member(msg, args[0]) if args else None
        e = discord.Embed(color=RED)
        if target:
            e.description = f'**{msg.author.display_name}** daje liścia **{target.display_name}**! 👋😤'
        else:
            e.description = f'**{msg.author.display_name}** macha ręką w powietrzu... 👋'
        await msg.reply(embed=e, mention_author=False)

    async def _cmd_gg(self, msg, args):
        target = self._resolve_member(msg, args[0]) if args else None
        e = discord.Embed(color=GOLD)
        if target:
            e.description = f'🎉 **GG!** Gratulacje dla **{target.display_name}**! Tak trzymaj! 🏆'
        else:
            e.description = f'🎉 **GG!** Dobra robota, **{msg.author.display_name}**!'
        await msg.reply(embed=e, mention_author=False)

    # ══════════════════════════════════════════════════════════════════════════
    # MISC FUN
    # ══════════════════════════════════════════════════════════════════════════

    FACTS = [
        'Mrówki nigdy nie śpią.', 'Ośmiornice mają trzy serca.',
        'Miód nie psuje się — archeolodzy znajdowali 3000-letni jadalny miód.',
        'Wzrok pszczoły sięga do ultrafioletu.', 'Banany są technicznie jagodami.',
        'Krokodyle nie mogą wysunąć języka.', 'Serce krewetki mieści się w głowie.',
        'Niedźwiedzie polarne mają przezroczystą sierść.', 'Słonie boją się pszczół.',
        'Pingwiny proponują ukochanym kamień jako pierścionek zaręczynowy.',
        'Kozy mają prostokątne źrenice.', 'Truskawki nie są jagodami botanicznie.',
        'Delfiny nadają sobie imiona.', 'Kozy potrafią rozpoznawać ludzkie twarze.',
        'Mrówkowiec nie ma zębów, je ok. 35 000 mrówek dziennie.',
    ]

    async def _cmd_fact(self, msg, args):
        if not await self._check_perm(msg, 'fact'): return
        e = discord.Embed(title='💡 Ciekawostka', description=random.choice(self.FACTS), color=BLURPLE)
        await msg.reply(embed=e, mention_author=False)

    async def _cmd_ship(self, msg, args):
        if not await self._check_perm(msg, 'ship'): return
        if len(args) >= 2:
            m1 = self._resolve_member(msg, args[0])
            m2 = self._resolve_member(msg, args[1])
            n1 = m1.display_name if m1 else args[0]
            n2 = m2.display_name if m2 else args[1]
        elif len(args) == 1:
            m1 = self._resolve_member(msg, args[0])
            n1 = m1.display_name if m1 else args[0]
            n2 = msg.author.display_name
        else:
            await msg.reply(embed=discord.Embed(description='❌ `.ship @user1 [@user2]`', color=RED),
                            mention_author=False); return
        seed = abs(hash(n1.lower() + n2.lower())) % 101
        bar_filled = round(seed / 10)
        bar = '💗' * bar_filled + '🖤' * (10 - bar_filled)
        if seed >= 85: label = '💘 Idealna para!'
        elif seed >= 60: label = '💕 Bardzo dobrana!'
        elif seed >= 40: label = '💛 Może być...'
        elif seed >= 20: label = '🤍 Słaby sygnał...'
        else: label = '💔 Chyba nie...'
        name = n1[:len(n1)//2] + n2[len(n2)//2:]
        e = discord.Embed(title=f'💘 Shipowanie: {n1} & {n2}', color=PURPLE)
        e.add_field(name='Imię shipowe', value=f'**{name}**', inline=True)
        e.add_field(name='Wynik', value=f'**{seed}%** {label}', inline=True)
        e.add_field(name='Pasek miłości', value=bar, inline=False)
        await msg.reply(embed=e, mention_author=False)

    async def _cmd_rate(self, msg, args):
        if not await self._check_perm(msg, 'rate'): return
        if not args:
            await msg.reply(embed=discord.Embed(description='❌ `.rate <cokolwiek>`', color=RED),
                            mention_author=False); return
        thing = ' '.join(args)
        score = abs(hash(thing.lower())) % 101
        bar_filled = round(score / 10)
        bar = '🟩' * bar_filled + '⬛' * (10 - bar_filled)
        if score >= 90: verdict = 'Absolutnie niesamowite!'
        elif score >= 70: verdict = 'Całkiem dobre!'
        elif score >= 50: verdict = 'Może być...'
        elif score >= 30: verdict = 'Słabe to.'
        else: verdict = 'Tragedia.'
        e = discord.Embed(title=f'⭐ Ocena: {thing}', color=GOLD)
        e.add_field(name='Wynik', value=f'**{score}/100** — {verdict}', inline=False)
        e.add_field(name='Pasek', value=bar, inline=False)
        await msg.reply(embed=e, mention_author=False)

    async def _cmd_reverse(self, msg, args):
        if not args:
            await msg.reply(embed=discord.Embed(description='❌ `.reverse <tekst>`', color=RED),
                            mention_author=False); return
        text = ' '.join(args)
        e = discord.Embed(title='🔄 Odwrócony tekst', color=BLURPLE)
        e.add_field(name='Oryginał', value=text, inline=False)
        e.add_field(name='Odwrócony', value=text[::-1], inline=False)
        await msg.reply(embed=e, mention_author=False)

    async def _cmd_upper(self, msg, args):
        if not args:
            await msg.reply(embed=discord.Embed(description='❌ `.upper <tekst>`', color=RED),
                            mention_author=False); return
        await msg.reply(embed=discord.Embed(description=f'🔠 **{" ".join(args).upper()}**', color=BLURPLE),
                        mention_author=False)

    async def _cmd_lower(self, msg, args):
        if not args:
            await msg.reply(embed=discord.Embed(description='❌ `.lower <tekst>`', color=RED),
                            mention_author=False); return
        await msg.reply(embed=discord.Embed(description=f'🔡 {" ".join(args).lower()}', color=BLURPLE),
                        mention_author=False)

    JOKES = [
        ('Dlaczego programista nie wyszedł z domu?', 'Bo nie miał okna (Windows).'),
        ('Co mówi NULL do wartości?', '"Mam cię za nic."'),
        ('Ile programistów potrzeba żeby zmienić żarówkę?', 'Żadnego – to problem sprzętowy.'),
        ('Dlaczego kot siedzi na klawiaturze?', 'Bo chce być close to the mouse.'),
        ('Dlaczego ryba nie ma laptopa?', 'Bo boi się sieci.'),
        ('Co powiedział ocean do plaży?', 'Nic, tylko pomachał.'),
        ('Dlaczego krowa nosi dzwonek?', 'Bo rogi nie grają.'),
        ('Ile kosztuje brak zainteresowania?', 'Nie wiem, mnie to nie interesuje.'),
        ('Co jest szybsze: ciepło czy zimno?', 'Ciepło. Zimno można złapać.'),
        ('Dlaczego ludzie piją kawę?', 'Bo herbata nie budzi tyle kontrowersji.'),
    ]

    QUOTES = [
        ('Nie ważne jak wolno idziesz, ważne że się nie zatrzymujesz.', 'Konfucjusz'),
        ('Sukces to suma małych wysiłków powtarzanych dzień po dniu.', 'Robert Collier'),
        ('Jedyna droga do dobrej roboty to kochać to co się robi.', 'Steve Jobs'),
        ('Wszystko wydaje się niemożliwe dopóki nie zostanie zrobione.', 'Nelson Mandela'),
        ('Każdy ekspert był kiedyś nowicjuszem.', 'Helen Hayes'),
        ('Mów mało, rób dużo.', 'Benjamin Franklin'),
        ('Życie jest zbyt krótkie żeby nie próbować.', 'Nieznany'),
        ('Wiedza mówi, mądrość słucha.', 'Jimi Hendrix'),
        ('Nie odkładaj na jutro tego co możesz zrobić pojutrze.', 'Mark Twain'),
        ('Im ciężej pracujesz, tym więcej szczęścia masz.', 'Thomas Jefferson'),
    ]

    async def _cmd_joke(self, msg, args):
        if not await self._check_perm(msg, 'joke'): return
        setup_line, punchline = random.choice(self.JOKES)
        e = discord.Embed(title='😂 Dowcip', color=GOLD)
        e.add_field(name='❓', value=setup_line, inline=False)
        e.add_field(name='💬', value=f'||{punchline}||', inline=False)
        e.set_footer(text='Kliknij aby zobaczyć odpowiedź!')
        await msg.reply(embed=e, mention_author=False)

    async def _cmd_quote(self, msg, args):
        if not await self._check_perm(msg, 'quote'): return
        text, author = random.choice(self.QUOTES)
        e = discord.Embed(
            description=f'*„{text}"*\n\n— **{author}**',
            color=PURPLE)
        e.set_footer(text='💭 Cytat dnia')
        await msg.reply(embed=e, mention_author=False)

    async def _cmd_owo(self, msg, args):
        if not args:
            await msg.reply(embed=discord.Embed(description='❌ `.owo <tekst>`', color=RED),
                            mention_author=False); return
        text = ' '.join(args)
        def owify(t):
            t = t.replace('r', 'w').replace('l', 'w')
            t = t.replace('R', 'W').replace('L', 'W')
            faces = [' owo', ' uwu', ' >w<', ' ^-^', ' nya~']
            return t + random.choice(faces)
        e = discord.Embed(description=owify(text), color=PURPLE)
        await msg.reply(embed=e, mention_author=False)

    # ══════════════════════════════════════════════════════════════════════════
    # UTILITY (MEE6 / Carl-bot)
    # ══════════════════════════════════════════════════════════════════════════

    _start_time = datetime.now()

    async def _cmd_ping(self, msg, args):
        latency = round(self.bot.latency * 1000)
        color = GREEN if latency < 100 else (YELLOW if latency < 200 else RED)
        e = discord.Embed(title='🏓 Pong!', color=color)
        e.add_field(name='Latencja', value=f'**{latency}ms**', inline=True)
        await msg.reply(embed=e, mention_author=False)

    async def _cmd_uptime(self, msg, args):
        delta = datetime.now() - UserCog._start_time
        h, rem = divmod(int(delta.total_seconds()), 3600)
        m, s = divmod(rem, 60)
        d, h = divmod(h, 24)
        parts = []
        if d: parts.append(f'{d}d')
        if h: parts.append(f'{h}h')
        if m: parts.append(f'{m}m')
        parts.append(f'{s}s')
        e = discord.Embed(title='⏱️ Uptime', color=GREEN)
        e.description = f'Bot działa od: **{" ".join(parts)}**'
        await msg.reply(embed=e, mention_author=False)

    async def _cmd_remindme(self, msg, args):
        """.remindme <czas> <wiadomość>  np. .remindme 1h30m sprawdź piekarnik"""
        if not await self._check_perm(msg, 'remindme'): return
        if len(args) < 2:
            await msg.reply(embed=discord.Embed(
                description='❌ `.remindme <czas> <wiadomość>`\nPrzykład: `.remindme 1h30m sprawdź piekarnik`',
                color=RED), mention_author=False); return

        from cogs.admin import _parse_duration
        td = _parse_duration(args[0])
        if not td or td.total_seconds() < 10:
            await msg.reply(embed=discord.Embed(
                description='❌ Nieprawidłowy czas. Użyj formatu `1h`, `30m`, `1h30m`, `2d`.', color=RED),
                mention_author=False); return
        if td.total_seconds() > 60 * 60 * 24 * 30:
            await msg.reply(embed=discord.Embed(
                description='❌ Maksymalny czas przypomnienia to 30 dni.', color=RED),
                mention_author=False); return

        reminder_text = ' '.join(args[1:])
        remind_at = (datetime.now() + td).isoformat()
        rid = db.add_reminder(msg.author.id, msg.guild.id, msg.channel.id, reminder_text, remind_at)
        human_time = (datetime.now() + td).strftime('%d.%m.%Y o %H:%M')
        e = discord.Embed(title='⏰ Przypomnienie ustawione!', color=GREEN)
        e.description = f'Przypomnę ci: **{reminder_text}**'
        e.add_field(name='🕐 Kiedy', value=human_time)
        e.set_footer(text=f'ID: {rid}')
        await msg.reply(embed=e, mention_author=False)

    # ══════════════════════════════════════════════════════════════════════════
    # TAGS (Carl-bot style) – read for all users
    # ══════════════════════════════════════════════════════════════════════════

    async def _cmd_tag(self, msg, args):
        if not args:
            await msg.reply(embed=discord.Embed(
                description='❌ `.tag <nazwa>` – użyj `.taglist` żeby zobaczyć dostępne tagi.',
                color=RED), mention_author=False); return
        name = args[0].lower()
        tag = db.get_tag(msg.guild.id, name)
        if not tag:
            await msg.reply(embed=discord.Embed(
                description=f'❌ Tag **{name}** nie istnieje. Użyj `.taglist`.', color=RED),
                mention_author=False); return
        db.increment_tag_uses(msg.guild.id, name)
        await msg.channel.send(tag['content'])

    async def _cmd_taglist(self, msg, args):
        tags = db.list_tags(msg.guild.id)
        if not tags:
            await msg.reply(embed=discord.Embed(description='📭 Brak tagów na tym serwerze.', color=YELLOW),
                            mention_author=False); return
        e = discord.Embed(title='🏷️ Tagi serwera', color=BLURPLE)
        lines = [f'`{t["name"]}`  — użyto {t["uses"]}×' for t in tags]
        e.description = '\n'.join(lines) or '*brak*'
        e.set_footer(text='Użyj .tag <nazwa> żeby wyświetlić tag')
        await msg.reply(embed=e, mention_author=False)

    # ══════════════════════════════════════════════════════════════════════════
    # ROLE INFO
    # ══════════════════════════════════════════════════════════════════════════

    async def _cmd_roleinfo(self, msg, args):
        if not args:
            await msg.reply(embed=discord.Embed(description='❌ `.roleinfo @rola`', color=RED),
                            mention_author=False); return
        rid = args[0].strip('<@&>').strip()
        try:
            role = msg.guild.get_role(int(rid))
        except ValueError:
            role = discord.utils.find(lambda r: r.name.lower() == ' '.join(args).lower(), msg.guild.roles)
        if not role:
            await msg.reply(embed=discord.Embed(description='❌ Nie znaleziono roli.', color=RED),
                            mention_author=False); return
        color_int = role.color.value or BLURPLE
        e = discord.Embed(title=f'🎭 Rola – {role.name}', color=color_int)
        e.add_field(name='ID', value=str(role.id), inline=True)
        e.add_field(name='Kolor', value=str(role.color), inline=True)
        e.add_field(name='Pozycja', value=str(role.position), inline=True)
        e.add_field(name='Członkowie', value=str(len(role.members)), inline=True)
        e.add_field(name='Hoistowana', value='Tak' if role.hoist else 'Nie', inline=True)
        e.add_field(name='Wzmiankowalna', value='Tak' if role.mentionable else 'Nie', inline=True)
        e.add_field(name='Zarządzana', value='Tak (np. bot/integracja)' if role.managed else 'Nie', inline=True)
        e.add_field(name='Utworzona', value=role.created_at.strftime('%d.%m.%Y'), inline=True)
        await msg.reply(embed=e, mention_author=False)


async def setup(bot: commands.Bot):
    await bot.add_cog(UserCog(bot))

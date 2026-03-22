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
        }

    def _resolve_member(self, msg, arg):
        uid = arg.strip('<@!>').strip()
        try:
            return msg.guild.get_member(int(uid))
        except ValueError:
            return None

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
        u = db.get_user(msg.author.id, msg.guild.id)
        cd = _check_cooldown(u.get('daily_last'), 60 * 24)  # 24h
        if cd:
            e = discord.Embed(description=f'⏳ Daily już odebrane! Wróć za **{_fmt_cd(cd)}**.', color=RED)
            await msg.reply(embed=e, mention_author=False); return
        reward = random.randint(100, 200)
        db.add_cash(msg.author.id, msg.guild.id, reward)
        db.set_cooldown(msg.author.id, msg.guild.id, 'daily_last')
        w = db.get_wallet(msg.author.id, msg.guild.id)
        e = discord.Embed(title=f'{COIN} Daily Reward!', color=GOLD)
        e.description = f'Otrzymałeś {_fmt_money(reward)}!\nStań się bogatszy jutro o kolejną nagrodę.'
        e.add_field(name='💵 Gotówka teraz', value=_fmt_money(w['cash']), inline=True)
        e.set_footer(text='Wróć za 24h po kolejną nagrodę!')
        await msg.reply(embed=e, mention_author=False)

    async def _cmd_work(self, msg, args):
        u = db.get_user(msg.author.id, msg.guild.id)
        cd = _check_cooldown(u.get('work_last'), 60)  # 1h
        if cd:
            e = discord.Embed(description=f'⏳ Jesteś zmęczony! Odpocznij jeszcze **{_fmt_cd(cd)}**.', color=RED)
            await msg.reply(embed=e, mention_author=False); return
        jobs_list = [
            ('zbierałeś ziemniaki', 'na polu'), ('rozwoziłeś pizzę', 'po mieście'),
            ('sprzątałeś biuro', 'na noc'), ('pilnowałeś magazynu', 'przez całą zmianę'),
            ('naprawiałeś komputer', 'u sąsiada'), ('strzyżeś trawniki', 'w parku'),
            ('myłeś okna', 'w wieżowcu'), ('sortowałeś paczki', 'w magazynie'),
            ('uczyłeś dzieci', 'grać na gitarze'), ('gotowałeś obiady', 'w stołówce'),
        ]
        job, place = random.choice(jobs_list)
        reward = random.randint(30, 80)
        db.add_cash(msg.author.id, msg.guild.id, reward)
        db.set_cooldown(msg.author.id, msg.guild.id, 'work_last')
        w = db.get_wallet(msg.author.id, msg.guild.id)
        e = discord.Embed(title='💼 Praca', color=GREEN)
        e.description = f'Przez ostatnią godzinę **{job}** {place}.\nZarobiłeś {_fmt_money(reward)}!'
        e.add_field(name='💵 Gotówka teraz', value=_fmt_money(w['cash']), inline=True)
        e.set_footer(text='Możesz pracować znowu za 1h')
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
        if not args or not args[0].isdigit():
            await msg.reply(embed=discord.Embed(description='❌ `.buy <nr_przedmiotu>` – użyj `.shop` żeby zobaczyć listę.', color=RED),
                            mention_author=False); return
        nr = int(args[0])
        item = next((i for i in SHOP_ITEMS if i[0] == nr), None)
        if not item:
            await msg.reply(embed=discord.Embed(description='❌ Nie ma takiego przedmiotu.', color=RED),
                            mention_author=False); return
        _, name, cost, pts = item
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

        # Fun
        fun_user = [
            ('8ball',      '`.8ball <pytanie>`',          'wróżba'),
            ('coinflip',   '`.coinflip`',                 'orzeł czy reszka'),
            ('roll',       '`.roll [Nd][K]`',             'rzuć kością (np. 2d6)'),
            ('choose',     '`.choose op1 op2 op3`',       'wybierz losowo'),
            ('avatar',     '`.avatar [@user]`',           'pokaż avatar'),
            ('serverinfo', '`.serverinfo`',               'info o serwerze'),
            ('rep',        '`.rep @user`',                'daj punkt reputacji (24h)'),
            ('poll',       '`.poll <pytanie>`',           'utwórz ankietę'),
            ('trivia',     '`.trivia`',                   'losowe pytanie quizowe'),
        ]
        fun_lines = [f'{s} – {d}' for cmd, s, d in fun_user if _user_perm(cmd)]
        e.add_field(name='🎮 Fun', inline=False,
                    value='\n'.join(fun_lines) or '*Brak*')

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
        await msg.reply(embed=e, mention_author=False)


async def setup(bot: commands.Bot):
    await bot.add_cog(UserCog(bot))

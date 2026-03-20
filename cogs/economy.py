import discord
from discord.ext import commands
from datetime import datetime, timedelta
import random
import database as db

BLURPLE = 0x7289DA
GREEN   = 0x43B581
RED     = 0xF04747
YELLOW  = 0xFAA61A
GOLD    = 0xF1C40F
TEAL    = 0x1ABC9C

CURRENCY = 'mopsow'
CURRENCY_ICON = '🐾'

DAILY_COOLDOWN_H  = 24
WORK_COOLDOWN_H   = 1
BEG_COOLDOWN_MIN  = 30
REP_COOLDOWN_H    = 24

WORK_RESPONSES = [
    ('ochroniarz na imprezie', 80, 140),
    ('dostawa pizzy', 50, 100),
    ('sprzatanie bazy', 60, 110),
    ('programista na zlecenie', 100, 180),
    ('DJ na weselu', 70, 130),
    ('kierowca taksowki', 55, 105),
    ('barman nocny', 65, 125),
    ('streamer na Twitchu', 30, 90),
    ('handlarz na targu', 45, 95),
    ('mechanik samochodowy', 75, 135),
]

BEG_RESPONSES = [
    'Ktos litosciwie wrzucil ci drobniaki',
    'Znalazles zgubiony portfel... prawie pusty',
    'Sprzedales stare skarpetkowy',
    'Wygrales zaklady o jednego mopsa',
    'Ktos pomylil cie z celebryta i dał napiwek',
]

EIGHTBALL_ANSWERS = [
    ('Tak, zdecydowanie.', GREEN),
    ('Bez watpienia.', GREEN),
    ('Na pewno.', GREEN),
    ('Mozesz na to liczyc.', GREEN),
    ('Wedlug moich informacji — tak.', GREEN),
    ('Raczej tak.', GREEN),
    ('Perspektywy sa dobre.', GREEN),
    ('Tak.', GREEN),
    ('Znaki wskazuja na tak.', GREEN),
    ('Nie jest to pewne, spytaj pozniej.', YELLOW),
    ('Lepiej nie mowic teraz.', YELLOW),
    ('Nie moge tego teraz przewidziec.', YELLOW),
    ('Skoncentruj sie i zapytaj ponownie.', YELLOW),
    ('Nie licz na to.', RED),
    ('Moja odpowiedz brzmi nie.', RED),
    ('Moje zrodla mowia nie.', RED),
    ('Perspektywy nie sa najlepsze.', RED),
    ('Bardzo watpliwe.', RED),
]

# Stały sklep — (id, nazwa, cena_mopsy, nagroda_punkty)
SHOP_ITEMS = [
    (1, 'Pakiet 5 punktow',   100,  5),
    (2, 'Pakiet 25 punktow',  450, 25),
    (3, 'Pakiet 100 punktow', 1600, 100),
]


def _ok(desc):   return discord.Embed(description=f'✅ {desc}', color=GREEN)
def _err(desc):  return discord.Embed(description=f'❌ {desc}', color=RED)
def _info(desc): return discord.Embed(description=f'ℹ️ {desc}', color=BLURPLE)


def _cooldown_left(last_str: str, hours: float = 0, minutes: float = 0) -> timedelta | None:
    if not last_str:
        return None
    last = datetime.fromisoformat(last_str)
    delta = timedelta(hours=hours, minutes=minutes)
    diff = (last + delta) - datetime.now()
    return diff if diff.total_seconds() > 0 else None


def _fmt_td(td: timedelta) -> str:
    total = int(td.total_seconds())
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f'{h}h {m}m'
    if m:
        return f'{m}m {s}s'
    return f'{s}s'


class EconomyCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._handlers = {
            'balance':  self._cmd_balance,
            'bal':      self._cmd_balance,
            'portfel':  self._cmd_balance,
            'daily':    self._cmd_daily,
            'work':     self._cmd_work,
            'pracuj':   self._cmd_work,
            'beg':      self._cmd_beg,
            'zebrz':    self._cmd_beg,
            'pay':      self._cmd_pay,
            'przelej':  self._cmd_pay,
            'deposit':  self._cmd_deposit,
            'wplac':    self._cmd_deposit,
            'withdraw': self._cmd_withdraw,
            'wyplac':   self._cmd_withdraw,
            'shop':     self._cmd_shop,
            'sklep':    self._cmd_shop,
            'buy':      self._cmd_buy,
            'kup':      self._cmd_buy,
            'lbmopsy':  self._cmd_lbmopsy,
            # Fun
            '8ball':    self._cmd_8ball,
            'coinflip': self._cmd_coinflip,
            'orzel':    self._cmd_coinflip,
            'roll':     self._cmd_roll,
            'dice':     self._cmd_roll,
            'choose':   self._cmd_choose,
            'wybierz':  self._cmd_choose,
            'avatar':   self._cmd_avatar,
            'rep':      self._cmd_rep,
            'serverinfo': self._cmd_serverinfo,
            'poll':     self._cmd_poll,
            'ping':     self._cmd_ping,
        }

    def _resolve_member(self, msg, arg):
        uid = arg.strip('<@!>').strip()
        try:
            return msg.guild.get_member(int(uid))
        except (ValueError, AttributeError):
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

    # ── Economy ──────────────────────────────────────────────────────────────

    async def _cmd_balance(self, msg, args):
        m = self._resolve_member(msg, args[0]) if args else msg.author
        if not m:
            await msg.reply(embed=_err('Nie znaleziono uzytkownika.'), mention_author=False); return
        db.ensure_user(m.id, msg.guild.id, str(m), m.display_name)
        w = db.get_wallet(m.id, msg.guild.id)
        e = discord.Embed(title=f'{CURRENCY_ICON} Portfel — {m.display_name}', color=GOLD)
        e.set_thumbnail(url=m.display_avatar.url)
        e.add_field(name='Gotowka', value=f'**{w["cash"]:.0f}** {CURRENCY_ICON}', inline=True)
        e.add_field(name='Bank',    value=f'**{w["bank"]:.0f}** {CURRENCY_ICON}', inline=True)
        e.add_field(name='Razem',   value=f'**{w["cash"]+w["bank"]:.0f}** {CURRENCY_ICON}', inline=True)
        await msg.reply(embed=e, mention_author=False)

    async def _cmd_daily(self, msg, args):
        u = db.get_user(msg.author.id, msg.guild.id)
        left = _cooldown_left(u.get('daily_last'), hours=DAILY_COOLDOWN_H)
        if left:
            await msg.reply(embed=_err(f'Dzienna nagroda dostepna za **{_fmt_td(left)}**.'),
                            mention_author=False); return
        reward = random.randint(150, 250)
        db.add_cash(msg.author.id, msg.guild.id, reward)
        db.set_cooldown(msg.author.id, msg.guild.id, 'daily_last')
        w = db.get_wallet(msg.author.id, msg.guild.id)
        e = discord.Embed(
            title=f'{CURRENCY_ICON} Dzienna nagroda!',
            description=f'Otrzymujesz **{reward}** {CURRENCY_ICON}!\nPortfel: **{w["cash"]:.0f}** {CURRENCY_ICON}',
            color=GOLD)
        await msg.reply(embed=e, mention_author=False)

    async def _cmd_work(self, msg, args):
        u = db.get_user(msg.author.id, msg.guild.id)
        left = _cooldown_left(u.get('work_last'), hours=WORK_COOLDOWN_H)
        if left:
            await msg.reply(embed=_err(f'Mozesz pracowac ponownie za **{_fmt_td(left)}**.'),
                            mention_author=False); return
        job_name, low, high = random.choice(WORK_RESPONSES)
        earned = random.randint(low, high)
        db.add_cash(msg.author.id, msg.guild.id, earned)
        db.set_cooldown(msg.author.id, msg.guild.id, 'work_last')
        w = db.get_wallet(msg.author.id, msg.guild.id)
        e = discord.Embed(
            title='💼 Praca',
            description=f'Pracowales jako **{job_name}** i zarobiles **{earned}** {CURRENCY_ICON}!\n'
                        f'Portfel: **{w["cash"]:.0f}** {CURRENCY_ICON}',
            color=TEAL)
        e.set_footer(text=f'Cooldown: {WORK_COOLDOWN_H}h')
        await msg.reply(embed=e, mention_author=False)

    async def _cmd_beg(self, msg, args):
        u = db.get_user(msg.author.id, msg.guild.id)
        left = _cooldown_left(u.get('beg_last'), minutes=BEG_COOLDOWN_MIN)
        if left:
            await msg.reply(embed=_err(f'Nie zebrz tak czesto! Poczekaj **{_fmt_td(left)}**.'),
                            mention_author=False); return
        earned = random.randint(1, 40)
        desc = random.choice(BEG_RESPONSES)
        db.add_cash(msg.author.id, msg.guild.id, earned)
        db.set_cooldown(msg.author.id, msg.guild.id, 'beg_last')
        e = discord.Embed(
            title='🙏 Zebractwo',
            description=f'{desc}\n+**{earned}** {CURRENCY_ICON}',
            color=YELLOW)
        await msg.reply(embed=e, mention_author=False)

    async def _cmd_pay(self, msg, args):
        if len(args) < 2:
            await msg.reply(embed=_err('`.pay @user <kwota>`'), mention_author=False); return
        target = self._resolve_member(msg, args[0])
        if not target or target.bot:
            await msg.reply(embed=_err('Nie znaleziono uzytkownika.'), mention_author=False); return
        if target.id == msg.author.id:
            await msg.reply(embed=_err('Nie mozesz przelac pieniedzy samemu sobie.'), mention_author=False); return
        try:
            amount = float(args[1])
            if amount <= 0:
                raise ValueError
        except ValueError:
            await msg.reply(embed=_err('Podaj poprawna kwote.'), mention_author=False); return
        db.ensure_user(target.id, msg.guild.id, str(target), target.display_name)
        ok = db.transfer_cash(msg.author.id, target.id, msg.guild.id, amount)
        if not ok:
            await msg.reply(embed=_err('Nie masz wystarczajaco gotowki.'), mention_author=False); return
        e = discord.Embed(
            description=f'💸 {msg.author.mention} przelal **{amount:.0f}** {CURRENCY_ICON} do {target.mention}',
            color=GREEN)
        await msg.reply(embed=e, mention_author=False)

    async def _cmd_deposit(self, msg, args):
        if not args:
            await msg.reply(embed=_err('`.deposit <kwota|all>`'), mention_author=False); return
        w = db.get_wallet(msg.author.id, msg.guild.id)
        amount = w['cash'] if args[0].lower() == 'all' else None
        if amount is None:
            try:
                amount = float(args[0])
                if amount <= 0:
                    raise ValueError
            except ValueError:
                await msg.reply(embed=_err('Podaj poprawna kwote.'), mention_author=False); return
        ok = db.deposit_cash(msg.author.id, msg.guild.id, amount)
        if not ok:
            await msg.reply(embed=_err('Nie masz wystarczajaco gotowki.'), mention_author=False); return
        w2 = db.get_wallet(msg.author.id, msg.guild.id)
        e = discord.Embed(
            description=f'🏦 Wplacono **{amount:.0f}** {CURRENCY_ICON} do banku.\nBank: **{w2["bank"]:.0f}** {CURRENCY_ICON}',
            color=TEAL)
        await msg.reply(embed=e, mention_author=False)

    async def _cmd_withdraw(self, msg, args):
        if not args:
            await msg.reply(embed=_err('`.withdraw <kwota|all>`'), mention_author=False); return
        w = db.get_wallet(msg.author.id, msg.guild.id)
        amount = w['bank'] if args[0].lower() == 'all' else None
        if amount is None:
            try:
                amount = float(args[0])
                if amount <= 0:
                    raise ValueError
            except ValueError:
                await msg.reply(embed=_err('Podaj poprawna kwote.'), mention_author=False); return
        ok = db.withdraw_cash(msg.author.id, msg.guild.id, amount)
        if not ok:
            await msg.reply(embed=_err('Nie masz wystarczajaco srodkow w banku.'), mention_author=False); return
        w2 = db.get_wallet(msg.author.id, msg.guild.id)
        e = discord.Embed(
            description=f'💵 Wyplacono **{amount:.0f}** {CURRENCY_ICON} z banku.\nGotowka: **{w2["cash"]:.0f}** {CURRENCY_ICON}',
            color=TEAL)
        await msg.reply(embed=e, mention_author=False)

    async def _cmd_shop(self, msg, args):
        e = discord.Embed(title=f'{CURRENCY_ICON} Sklep', color=GOLD)
        e.description = 'Kupuj przedmioty za mopsy.\nUzyj `.buy <id>` aby kupic.\n\n'
        lines = []
        for item_id, name, price, pts in SHOP_ITEMS:
            lines.append(f'`[{item_id}]` **{name}** — {price} {CURRENCY_ICON} → +{pts} pkt')
        e.description += '\n'.join(lines)
        w = db.get_wallet(msg.author.id, msg.guild.id)
        e.set_footer(text=f'Twoja gotowka: {w["cash"]:.0f} {CURRENCY_ICON}')
        await msg.reply(embed=e, mention_author=False)

    async def _cmd_buy(self, msg, args):
        if not args:
            await msg.reply(embed=_err('`.buy <id>` — uzyj `.shop` aby zobaczyc liste.'),
                            mention_author=False); return
        try:
            item_id = int(args[0])
        except ValueError:
            await msg.reply(embed=_err('Podaj numer ID przedmiotu.'), mention_author=False); return
        item = next((i for i in SHOP_ITEMS if i[0] == item_id), None)
        if not item:
            await msg.reply(embed=_err('Nie znaleziono przedmiotu. Uzyj `.shop`.'),
                            mention_author=False); return
        _, name, price, pts = item
        w = db.get_wallet(msg.author.id, msg.guild.id)
        if w['cash'] < price:
            brak = price - w['cash']
            await msg.reply(embed=_err(f'Za malo gotowki. Brakuje **{brak:.0f}** {CURRENCY_ICON}.'),
                            mention_author=False); return
        db.add_cash(msg.author.id, msg.guild.id, -price)
        db.add_points(msg.author.id, msg.guild.id, pts,
                      note=f'Zakup w sklepie: {name}', assigned_by=None)
        e = discord.Embed(
            title=f'{CURRENCY_ICON} Zakup udany!',
            description=f'Kupiles **{name}**!\n'
                        f'Zaplacono: **{price}** {CURRENCY_ICON}\n'
                        f'Otrzymano: **+{pts} pkt**',
            color=GREEN)
        await msg.reply(embed=e, mention_author=False)

    async def _cmd_lbmopsy(self, msg, args):
        top = db.get_eco_leaderboard(msg.guild.id, limit=10)
        if not top:
            await msg.reply(embed=discord.Embed(description='📭 Brak danych.', color=YELLOW),
                            mention_author=False); return
        MEDALS = ['🥇', '🥈', '🥉']
        e = discord.Embed(title=f'{CURRENCY_ICON} Ranking Bogaczy', color=GOLD, timestamp=datetime.now())
        lines = []
        for i, u in enumerate(top):
            medal = MEDALS[i] if i < 3 else f'`{i+1}.`'
            member = msg.guild.get_member(u['user_id'])
            name = member.display_name if member else u.get('display_name') or str(u['user_id'])
            total = (u.get('cash') or 0) + (u.get('bank') or 0)
            lines.append(f'{medal} **{name}** — {total:.0f} {CURRENCY_ICON}')
        e.description = '\n'.join(lines)
        await msg.reply(embed=e, mention_author=False)

    # ── Fun ──────────────────────────────────────────────────────────────────

    async def _cmd_8ball(self, msg, args):
        if not args:
            await msg.reply(embed=_err('`.8ball <pytanie>`'), mention_author=False); return
        question = ' '.join(args)
        answer, color = random.choice(EIGHTBALL_ANSWERS)
        e = discord.Embed(color=color)
        e.add_field(name='❓ Pytanie', value=question, inline=False)
        e.add_field(name='🎱 Odpowiedz', value=f'**{answer}**', inline=False)
        await msg.reply(embed=e, mention_author=False)

    async def _cmd_coinflip(self, msg, args):
        result = random.choice(['Orzel', 'Reszka'])
        if args:
            guess = args[0].lower()
            guess_map = {'orzel': 'Orzel', 'reszka': 'Reszka', 'h': 'Orzel',
                         'heads': 'Orzel', 't': 'Reszka', 'tails': 'Reszka'}
            guess_norm = guess_map.get(guess)
            if guess_norm:
                won = guess_norm == result
                e = discord.Embed(
                    description=f'🪙 Wypadlo: **{result}**\n{"✅ Trafiony!" if won else "❌ Pudlo!"}',
                    color=GREEN if won else RED)
                await msg.reply(embed=e, mention_author=False)
                return
        e = discord.Embed(description=f'🪙 **{result}**!', color=GOLD)
        await msg.reply(embed=e, mention_author=False)

    async def _cmd_roll(self, msg, args):
        sides = 6
        if args:
            try:
                sides = int(args[0])
                if sides < 2:
                    sides = 6
            except ValueError:
                pass
        result = random.randint(1, sides)
        e = discord.Embed(description=f'🎲 Wyrzucono **{result}** (k{sides})', color=BLURPLE)
        await msg.reply(embed=e, mention_author=False)

    async def _cmd_choose(self, msg, args):
        if not args:
            await msg.reply(embed=_err('`.choose <opcja1> <opcja2> ...`'), mention_author=False); return
        options = [a.strip(',|') for a in args if a.strip(',|')]
        if len(options) < 2:
            await msg.reply(embed=_err('Podaj co najmniej 2 opcje.'), mention_author=False); return
        picked = random.choice(options)
        e = discord.Embed(description=f'🎯 Wybieram: **{picked}**', color=BLURPLE)
        await msg.reply(embed=e, mention_author=False)

    async def _cmd_avatar(self, msg, args):
        m = self._resolve_member(msg, args[0]) if args else msg.author
        if not m:
            await msg.reply(embed=_err('Nie znaleziono uzytkownika.'), mention_author=False); return
        e = discord.Embed(title=f'🖼️ Avatar — {m.display_name}', color=BLURPLE)
        e.set_image(url=m.display_avatar.url)
        await msg.reply(embed=e, mention_author=False)

    async def _cmd_rep(self, msg, args):
        if not args:
            await msg.reply(embed=_err('`.rep @user`'), mention_author=False); return
        target = self._resolve_member(msg, args[0])
        if not target or target.bot:
            await msg.reply(embed=_err('Nie znaleziono uzytkownika.'), mention_author=False); return
        if target.id == msg.author.id:
            await msg.reply(embed=_err('Nie mozesz dac repki samemu sobie.'), mention_author=False); return
        u = db.get_user(msg.author.id, msg.guild.id)
        left = _cooldown_left(u.get('rep_last'), hours=REP_COOLDOWN_H)
        if left:
            await msg.reply(embed=_err(f'Mozesz dac repke ponownie za **{_fmt_td(left)}**.'),
                            mention_author=False); return
        db.ensure_user(target.id, msg.guild.id, str(target), target.display_name)
        with db._lock:
            with db._get_conn() as conn:
                conn.execute(
                    'UPDATE users SET rep_points = rep_points + 1 WHERE user_id=? AND guild_id=?',
                    (target.id, msg.guild.id))
                conn.commit()
        db.set_cooldown(msg.author.id, msg.guild.id, 'rep_last')
        t_u = db.get_user(target.id, msg.guild.id)
        rep = t_u.get('rep_points', 0) if t_u else 1
        e = discord.Embed(
            description=f'⭐ {msg.author.mention} dal repke uzytkownikowi {target.mention}!\n'
                        f'Laczne repki: **{rep}**',
            color=GOLD)
        await msg.reply(embed=e, mention_author=False)

    async def _cmd_serverinfo(self, msg, args):
        g = msg.guild
        bots   = sum(1 for m in g.members if m.bot)
        humans = g.member_count - bots
        e = discord.Embed(title=f'📊 {g.name}', color=BLURPLE, timestamp=datetime.now())
        if g.icon:
            e.set_thumbnail(url=g.icon.url)
        e.add_field(name='Czlonkowie', value=f'👥 {humans} ludzi\n🤖 {bots} botow', inline=True)
        e.add_field(name='Kanaly',
                    value=f'💬 {len(g.text_channels)} tekstowych\n'
                          f'🔊 {len(g.voice_channels)} głosowych', inline=True)
        e.add_field(name='Role', value=str(len(g.roles)), inline=True)
        e.add_field(name='Serwer utworzony',
                    value=g.created_at.strftime('%d.%m.%Y'), inline=True)
        e.add_field(name='ID', value=str(g.id), inline=True)
        e.add_field(name='Boost', value=f'Tier {g.premium_tier} | {g.premium_subscription_count}x', inline=True)
        await msg.reply(embed=e, mention_author=False)

    async def _cmd_poll(self, msg, args):
        if not args:
            await msg.reply(embed=_err('`.poll <pytanie>`'), mention_author=False); return
        question = ' '.join(args)
        e = discord.Embed(title='📊 Ankieta', description=f'**{question}**', color=BLURPLE)
        e.set_footer(text=f'Ankieta od {msg.author.display_name}')
        sent = await msg.channel.send(embed=e)
        await sent.add_reaction('👍')
        await sent.add_reaction('👎')
        try:
            await msg.delete()
        except Exception:
            pass

    async def _cmd_ping(self, msg, args):
        latency = round(self.bot.latency * 1000)
        e = discord.Embed(description=f'🏓 Pong! Latencja: **{latency}ms**',
                          color=GREEN if latency < 100 else YELLOW)
        await msg.reply(embed=e, mention_author=False)


async def setup(bot: commands.Bot):
    await bot.add_cog(EconomyCog(bot))

import discord
from discord.ext import commands, tasks
from discord import ui
from datetime import datetime, date
import json
import asyncio
import database as db

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


# ─── Persistent ClockView ─────────────────────────────────────────────────────

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
                description=f'⚠️ Już jesteś zalogowany od **{since.strftime("%H:%M")}**.\nUżyj **Clock Out** aby się wylogować.',
                color=YELLOW
            )
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
                      details={'time': now.isoformat(), 'display_name': interaction.user.display_name})
        await send_log(interaction.guild, log_embed(
            '🟢 Clock In', GREEN,
            Użytkownik=f'{interaction.user.mention} ({interaction.user.display_name})',
            Godzina=now.strftime('%H:%M:%S'),
            Data=now.strftime('%d.%m.%Y')
        ))

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
                color=YELLOW
            )
            await interaction.followup.send(embed=e, ephemeral=True)
            return

        result = db.clock_out(uid, gid)
        if not result:
            await interaction.followup.send('❌ Błąd przy wylogowaniu.', ephemeral=True)
            return

        h = result['hours']
        m = result['minutes']
        pts = result['points_earned']
        ci = result['clock_in_time']
        co = result['clock_out_time']
        time_str = f'{int(h)}h {int(m % 60)}min' if h >= 1 else f'{int(m)}min'

        fresh_user = db.get_user(uid, gid)

        e = discord.Embed(title='👋 Wylogowano!', color=BLURPLE, timestamp=co)
        e.set_thumbnail(url=interaction.user.display_avatar.url)
        e.add_field(name='👤 Użytkownik', value=interaction.user.display_name, inline=True)
        e.add_field(name='⏱️ Czas', value=time_str, inline=True)
        e.add_field(name='💰 Punkty',
                    value=f'+**{pts:.1f}** pkt' if pts > 0 else '*(zbyt krótka sesja)*',
                    inline=True)
        e.add_field(name='🕐 Clock In', value=ci.strftime('%H:%M'), inline=True)
        e.add_field(name='🕑 Clock Out', value=co.strftime('%H:%M'), inline=True)
        e.add_field(name='⭐ Ranga', value=_rank_line(uid, gid), inline=True)
        if fresh_user:
            e.set_footer(text=f'Łączne punkty: {fresh_user["points"]:.1f} pkt')
        await interaction.followup.send(embed=e, ephemeral=True)

        db.log_action(gid, 'clock_out', user_id=uid,
                      details={'hours': round(h, 2), 'points': pts,
                               'display_name': interaction.user.display_name})
        await send_log(interaction.guild, log_embed(
            '🔴 Clock Out', RED,
            Użytkownik=f'{interaction.user.mention} ({interaction.user.display_name})',
            Czas=time_str,
            Punkty=f'+{pts:.1f}',
            **{'Łącznie pkt': f'{fresh_user["points"]:.1f}' if fresh_user else '?'}
        ))

        pts_before = (fresh_user['points'] - pts) if fresh_user else 0
        await _check_rank_up(interaction, uid, gid, pts_before,
                             fresh_user['points'] if fresh_user else 0)


async def _check_rank_up(interaction: discord.Interaction,
                          uid: int, gid: int,
                          pts_before: float, pts_after: float):
    ranks_auto = db.get_ranks(gid, auto_only=True)
    rank_before, rank_after = None, None
    for r in ranks_auto:
        if r['required_points'] <= pts_before:
            rank_before = r
    for r in ranks_auto:
        if r['required_points'] <= pts_after:
            rank_after = r

    if rank_after and (not rank_before or rank_after['id'] != rank_before['id']):
        try:
            color = int(rank_after['color'].lstrip('#'), 16)
        except Exception:
            color = GREEN
        e = discord.Embed(
            title='🎉 Awans na nową rangę!',
            description=(f'{interaction.user.mention} awansował(a) na\n'
                         f'**{rank_after["icon"]} {rank_after["name"]}**!'),
            color=color
        )
        e.set_thumbnail(url=interaction.user.display_avatar.url)
        e.set_footer(text=f'Punkty: {pts_after:.1f}')
        cfg = db.get_guild(gid)
        ch_id = cfg.get('clock_channel_id') if cfg else None
        ch = interaction.guild.get_channel(ch_id) if ch_id else None
        if ch:
            try:
                await ch.send(content=interaction.user.mention, embed=e)
            except discord.Forbidden:
                pass
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
            Punkty=f'{pts_after:.1f}'
        ))


# ─── Main Cog ─────────────────────────────────────────────────────────────────

class ClockInCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._last_embed_check: dict = {}   # guild_id → "YYYY-MM-DD HH:MM"
        self.schedule_task.start()
        self.anti_cheat_task.start()

    def cog_unload(self):
        self.schedule_task.cancel()
        self.anti_cheat_task.cancel()

    # ── Per-day schedule (runs every minute) ──────────────────────────────────

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
            day_cfg = schedule.get(current_day, {})

            if not day_cfg.get('enabled', True):
                continue

            sched_hm = f'{day_cfg.get("hour", 0):02d}:{day_cfg.get("minute", 0):02d}'
            if current_hm != sched_hm:
                continue

            # Deduplicate: only once per minute per guild
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
        stats = db.get_guild_stats(guild_id)
        dt = datetime.strptime(today, '%Y-%m-%d')
        day_name = db.DAYS_PL[dt.weekday()]
        e = discord.Embed(
            title='📋 Codzienny Apel',
            description=(
                f'**{day_name}, {dt.strftime("%d.%m.%Y")}**\n\n'
                '📌 Oznacz swoją aktywność przyciskami poniżej.\n'
                '• **Clock In** – gdy zaczynasz\n'
                '• **Clock Out** – gdy kończysz\n\n'
                f'👥 Aktywnych teraz: **{stats["active_now"]}**\n'
                f'⚠️ Ostrzeżenia (serwer): **{stats["warning_count"]}**'
            ),
            color=BLURPLE,
            timestamp=datetime.now()
        )
        e.set_footer(text='System Rang • Punkty za aktywność')
        try:
            msg = await channel.send(embed=e, view=ClockView())
            db.save_daily_embed(guild_id, channel.id, msg.id, today)
        except discord.Forbidden:
            pass

    # ── Anti-cheat (runs every 30 min) ────────────────────────────────────────

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
                    ci_dt  = datetime.fromisoformat(ci_str)
                    elapsed = round((datetime.now() - ci_dt).total_seconds() / 3600, 1)
                except Exception:
                    elapsed = max_hours

                warn_id = db.add_warning(
                    uid, guild.id,
                    reason=f'Auto-cheat: zalogowany {elapsed}h bez Clock Out (limit {max_hours}h)',
                    warned_by=None, is_auto=True
                )
                warn_count = db.get_warning_count(uid, guild.id)
                db.log_action(guild.id, 'anticheat', user_id=uid,
                              details={'hours': elapsed, 'warn_count': warn_count,
                                       'warn_limit': warn_limit})

                # Auto-ban after warn_limit
                if warn_count >= warn_limit:
                    db.update_user(uid, guild.id, is_banned=1)
                    db.log_action(guild.id, 'auto_ban', user_id=uid,
                                  details={'reason': 'Przekroczono limit ostrzeżeń (anti-cheat)'})

                member = guild.get_member(uid)
                name = member.display_name if member else u.get('display_name', str(uid))
                mention = member.mention if member else f'ID:{uid}'

                status_txt = (f'🔨 **Auto-ban** po {warn_limit} ostrzeżeniach'
                              if warn_count >= warn_limit
                              else f'Ostrzeżenie **#{warn_count}/{warn_limit}**')

                e = discord.Embed(
                    title='🤖 Anti-Cheat – Wykrycie',
                    color=ORANGE,
                    timestamp=datetime.now()
                )
                e.add_field(name='👤 Użytkownik', value=f'{mention} ({name})', inline=True)
                e.add_field(name='⏱️ Czas zalogowania', value=f'{elapsed}h', inline=True)
                e.add_field(name='⚡ Akcja', value=f'Wymuszono Clock Out\n{status_txt}', inline=False)
                e.set_footer(text='Wykryto podejrzaną aktywność')
                await send_log(guild, e)

                # Notify in clock channel
                ch_id = cfg.get('clock_channel_id')
                ch = guild.get_channel(ch_id) if ch_id else None
                if ch:
                    try:
                        await ch.send(
                            content=mention if member else '',
                            embed=discord.Embed(
                                description=(
                                    f'⚠️ {mention} – wykryto zalogowanie przez **{elapsed}h** bez wylogowania.\n'
                                    f'Sesja zakończona automatycznie. {status_txt}'
                                ),
                                color=ORANGE
                            )
                        )
                    except discord.Forbidden:
                        pass

    @anti_cheat_task.before_loop
    async def before_anticheat(self):
        await self.bot.wait_until_ready()
        await asyncio.sleep(60)   # Give bot 60s to fully start

    # ── .apel command ─────────────────────────────────────────────────────────

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
            any(r.id in admin_ids for r in message.author.roles)
        )
        if not is_admin:
            return
        today = date.today().isoformat()
        await self._send_daily_embed(message.channel, message.guild.id, today)
        await message.add_reaction('✅')


async def setup(bot: commands.Bot):
    await bot.add_cog(ClockInCog(bot))

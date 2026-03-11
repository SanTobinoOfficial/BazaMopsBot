import discord
from discord.ext import commands, tasks
from discord import ui
from datetime import datetime, date, time as dtime
import asyncio
import database as db

BLURPLE = 0x7289DA
GREEN   = 0x43B581
RED     = 0xF04747
YELLOW  = 0xFAA61A


def _rank_display(user_id: int, guild_id: int) -> str:
    rank = db.get_user_auto_rank(user_id, guild_id)
    special = db.get_user_special_ranks(user_id, guild_id)
    parts = []
    if rank:
        parts.append(f"{rank['icon']} {rank['name']}")
    for sr in special:
        parts.append(f"{sr['icon']} {sr['name']}")
    return ' | '.join(parts) if parts else 'Brak rangi'


class ClockView(ui.View):
    """Persistent view – survives bot restarts thanks to custom_ids."""

    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label='🟢 Clock In', style=discord.ButtonStyle.success,
               custom_id='clock_in_btn')
    async def clock_in(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True)
        guild_id = interaction.guild_id
        user_id  = interaction.user.id

        db.ensure_guild(guild_id)
        db.ensure_user(user_id, guild_id,
                       str(interaction.user), interaction.user.display_name)

        user = db.get_user(user_id, guild_id)
        if user and user['is_clocked_in']:
            since = datetime.fromisoformat(user['clock_in_time'])
            embed = discord.Embed(
                title='⚠️ Już zalogowany',
                description=f'Jesteś już zalogowany od **{since.strftime("%H:%M")}**.\n'
                            f'Użyj przycisku **Clock Out** aby się wylogować.',
                color=YELLOW
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        session = db.clock_in(user_id, guild_id)
        if not session:
            await interaction.followup.send('❌ Błąd przy logowaniu.', ephemeral=True)
            return

        now = datetime.now()
        embed = discord.Embed(
            title='✅ Zalogowano!',
            description=f'Witaj, **{interaction.user.display_name}**!\n'
                        f'Czas logowania: **{now.strftime("%H:%M:%S")}**\n\n'
                        f'Ranga: {_rank_display(user_id, guild_id)}',
            color=GREEN,
            timestamp=now
        )
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        embed.set_footer(text='Pamiętaj o Clock Out na koniec aktywności!')
        await interaction.followup.send(embed=embed, ephemeral=True)

        await _log(interaction.guild, f'🟢 **{interaction.user.display_name}** zalogował(a) się o {now.strftime("%H:%M")}')

    @ui.button(label='🔴 Clock Out', style=discord.ButtonStyle.danger,
               custom_id='clock_out_btn')
    async def clock_out(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True)
        guild_id = interaction.guild_id
        user_id  = interaction.user.id

        db.ensure_guild(guild_id)
        db.ensure_user(user_id, guild_id,
                       str(interaction.user), interaction.user.display_name)

        user = db.get_user(user_id, guild_id)
        if not user or not user['is_clocked_in']:
            embed = discord.Embed(
                title='⚠️ Nie jesteś zalogowany',
                description='Najpierw kliknij **Clock In** aby zaznaczyć swoją aktywność.',
                color=YELLOW
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        result = db.clock_out(user_id, guild_id)
        if not result:
            await interaction.followup.send('❌ Błąd przy wylogowaniu.', ephemeral=True)
            return

        hours   = result['hours']
        minutes = result['minutes']
        pts     = result['points_earned']
        ci      = result['clock_in_time']
        co      = result['clock_out_time']

        time_str = f'{int(hours)}h {int(minutes % 60)}min' if hours >= 1 else f'{int(minutes)}min'

        embed = discord.Embed(
            title='👋 Wylogowano!',
            color=BLURPLE,
            timestamp=co
        )
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        embed.add_field(name='👤 Użytkownik', value=interaction.user.display_name, inline=True)
        embed.add_field(name='⏱️ Czas aktywności', value=time_str, inline=True)
        embed.add_field(name='💰 Zdobyte punkty', value=f'+**{pts:.1f}** pkt' if pts > 0 else '*(za mało czasu)*', inline=True)
        embed.add_field(name='🕐 Zalogowano', value=ci.strftime('%H:%M:%S'), inline=True)
        embed.add_field(name='🕐 Wylogowano', value=co.strftime('%H:%M:%S'), inline=True)
        embed.add_field(name='⭐ Ranga', value=_rank_display(user_id, guild_id), inline=True)

        total_user = db.get_user(user_id, guild_id)
        if total_user:
            embed.set_footer(text=f'Łączne punkty: {total_user["points"]:.1f} pkt')

        await interaction.followup.send(embed=embed, ephemeral=True)

        log_msg = (
            f'🔴 **{interaction.user.display_name}** wylogował(a) się | '
            f'{time_str} | +{pts:.1f} pkt'
        )
        await _log(interaction.guild, log_msg)

        # Check for rank-up
        await _check_rank_up(interaction, user_id, guild_id,
                              total_user['points'] - pts if total_user else 0,
                              total_user['points'] if total_user else 0)


async def _log(guild: discord.Guild, msg: str):
    if not guild:
        return
    cfg = db.get_guild(guild.id)
    if not cfg or not cfg.get('log_channel_id'):
        return
    ch = guild.get_channel(cfg['log_channel_id'])
    if ch:
        try:
            await ch.send(msg)
        except discord.Forbidden:
            pass


async def _check_rank_up(interaction: discord.Interaction,
                          user_id: int, guild_id: int,
                          points_before: float, points_after: float):
    # Get rank before points were added
    ranks_auto = db.get_ranks(guild_id, auto_only=True)
    rank_before = None
    for r in ranks_auto:
        if r['required_points'] <= points_before:
            rank_before = r
        else:
            break

    rank_after = db.get_user_auto_rank(user_id, guild_id)

    if rank_after and (not rank_before or rank_after['id'] != rank_before['id']):
        # User ranked up!
        embed = discord.Embed(
            title='🎉 Awans na nową rangę!',
            description=f'**{interaction.user.display_name}** awansował(a) na rangę\n'
                        f'**{rank_after["icon"]} {rank_after["name"]}**!',
            color=int(rank_after['color'].lstrip('#'), 16) if rank_after.get('color') else GREEN
        )
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        embed.set_footer(text=f'Punkty: {points_after:.1f}')

        # Try to send to clock channel
        cfg = db.get_guild(guild_id)
        channel_id = cfg.get('clock_channel_id') if cfg else None
        ch = interaction.guild.get_channel(channel_id) if channel_id else None
        if ch:
            try:
                await ch.send(content=interaction.user.mention, embed=embed)
            except discord.Forbidden:
                pass

        # Assign Discord role if configured
        if rank_after.get('role_id'):
            role = interaction.guild.get_role(rank_after['role_id'])
            member = interaction.guild.get_member(user_id)
            if role and member:
                try:
                    # Remove old rank role
                    if rank_before and rank_before.get('role_id'):
                        old_role = interaction.guild.get_role(rank_before['role_id'])
                        if old_role and old_role in member.roles:
                            await member.remove_roles(old_role, reason='Awans rangi')
                    await member.add_roles(role, reason=f'Awans: {rank_after["name"]}')
                except discord.Forbidden:
                    pass


class ClockInCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.daily_embed_task.start()

    def cog_unload(self):
        self.daily_embed_task.cancel()

    @tasks.loop(time=dtime(hour=0, minute=0, second=0))
    async def daily_embed_task(self):
        await self._post_daily_embeds()

    @daily_embed_task.before_loop
    async def before_daily(self):
        await self.bot.wait_until_ready()

    async def _post_daily_embeds(self):
        today = date.today().isoformat()
        for guild in self.bot.guilds:
            cfg = db.get_guild(guild.id)
            if not cfg or not cfg.get('clock_channel_id'):
                continue
            # Already posted today?
            if db.get_daily_embed(guild.id, today):
                continue
            channel = guild.get_channel(cfg['clock_channel_id'])
            if not channel:
                continue
            await self._send_daily_embed(channel, guild.id, today)

    async def _send_daily_embed(self, channel: discord.TextChannel,
                                 guild_id: int, today: str):
        stats = db.get_guild_stats(guild_id)
        embed = discord.Embed(
            title='📋 Codzienny Apel',
            description=(
                f'**Data:** {datetime.strptime(today, "%Y-%m-%d").strftime("%d.%m.%Y")}\n\n'
                '📌 Oznacz swoją aktywność przyciskami poniżej.\n'
                '• **Clock In** – gdy zaczynasz aktywność\n'
                '• **Clock Out** – gdy kończysz aktywność\n\n'
                f'👥 Aktywnych teraz: **{stats["active_now"]}**'
            ),
            color=BLURPLE,
            timestamp=datetime.now()
        )
        embed.set_footer(text='System Rang • Punkty za aktywność')
        view = ClockView()
        try:
            msg = await channel.send(embed=embed, view=view)
            db.save_daily_embed(guild_id, channel.id, msg.id, today)
        except discord.Forbidden:
            pass

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

        # .apel – admin command to force-post today's embed
        if cmd == 'apel':
            cfg = db.get_guild(message.guild.id)
            admin_roles = cfg.get('admin_role_ids', '[]') if cfg else '[]'
            import json
            admin_role_ids = json.loads(admin_roles) if isinstance(admin_roles, str) else admin_roles
            is_admin = (
                message.author.guild_permissions.administrator or
                any(r.id in admin_role_ids for r in message.author.roles)
            )
            if not is_admin:
                return
            today = date.today().isoformat()
            channel = message.channel
            await self._send_daily_embed(channel, message.guild.id, today)
            await message.add_reaction('✅')


async def setup(bot: commands.Bot):
    await bot.add_cog(ClockInCog(bot))

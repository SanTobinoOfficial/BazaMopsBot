import discord
from discord.ext import commands, tasks
import database as db
import asyncio


class BotMops(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.guilds = True
        super().__init__(command_prefix='!', intents=intents, help_command=None)

    async def setup_hook(self):
        db.init_db()
        await self.load_extension('cogs.clockin')
        await self.load_extension('cogs.admin')
        await self.load_extension('cogs.user')
        await self.load_extension('cogs.economy')
        await self.load_extension('cogs.panel')
        await self.load_extension('cogs.jobs')
        # Re-register ALL persistent views after restart
        from cogs.clockin import ClockView, SessionClockView
        from cogs.panel import (StatsPanelView, ActivityPanelView,
                                ServerPanelView, AdminPanelView)
        from cogs.jobs import JobPanelView
        self.add_view(ClockView())          # backward compat for old embeds
        self.add_view(SessionClockView())   # new session embeds
        self.add_view(StatsPanelView())
        self.add_view(ActivityPanelView())
        self.add_view(ServerPanelView())
        self.add_view(AdminPanelView())
        self.add_view(JobPanelView())       # job selection panel

    async def on_ready(self):
        print(f'✅ Zalogowano jako {self.user} (ID: {self.user.id})')
        print(f'   Serwery: {[g.name for g in self.guilds]}')
        for guild in self.guilds:
            db.ensure_guild(guild.id)
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name=".help | System Rang"
            )
        )
        if not self._reminder_loop.is_running():
            self._reminder_loop.start()

    @tasks.loop(seconds=30)
    async def _reminder_loop(self):
        """Check and fire due reminders every 30 seconds."""
        try:
            pending = db.get_pending_reminders()
            for r in pending:
                try:
                    ch = self.get_channel(r['channel_id'])
                    if ch:
                        user = self.get_user(r['user_id'])
                        mention = user.mention if user else f'<@{r["user_id"]}>'
                        e = discord.Embed(
                            title='⏰ Przypomnienie!',
                            description=f'{mention}\n\n**{r["message"]}**',
                            color=0x43B581)
                        await ch.send(embed=e)
                except Exception:
                    pass
                db.mark_reminder_done(r['id'])
        except Exception:
            pass

    async def on_guild_join(self, guild: discord.Guild):
        db.ensure_guild(guild.id)
        print(f'➕ Dołączono do: {guild.name}')

    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        db.ensure_user(
            message.author.id, message.guild.id,
            str(message.author), message.author.display_name
        )
        await self.process_commands(message)

    async def on_command_error(self, ctx, error):
        pass


bot = BotMops()

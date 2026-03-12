import discord
from discord.ext import commands
import database as db


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
        await self.load_extension('cogs.panel')
        # Re-register ALL persistent views after restart
        from cogs.clockin import ClockView
        from cogs.panel import UserPanelView, AdminPanelView
        self.add_view(ClockView())
        self.add_view(UserPanelView())
        self.add_view(AdminPanelView())

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

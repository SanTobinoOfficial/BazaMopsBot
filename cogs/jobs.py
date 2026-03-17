import discord
from discord.ext import commands
from discord import ui
from datetime import datetime
import database as db

BLURPLE = 0x7289DA
GREEN   = 0x43B581
RED     = 0xF04747
YELLOW  = 0xFAA61A
ORANGE  = 0xE67E22


# ─── Embed builder ────────────────────────────────────────────────────────────

def _build_job_embed(guild_id: int, guild_name: str) -> discord.Embed:
    """Build the public job-list embed (non-personalised)."""
    jobs = db.get_jobs(guild_id)
    e = discord.Embed(
        title=f'💼 Lista Prac – {guild_name}',
        description='Zdobądź wymaganą liczbę punktów i kliknij **Wybierz pracę**!',
        color=BLURPLE,
        timestamp=datetime.now()
    )
    if not jobs:
        e.description = '❌ Brak skonfigurowanych prac. Admin użyj `.createjob`.'
        e.color = YELLOW
        return e

    lines = []
    for j in jobs:
        desc_part = f' – *{j["description"]}*' if j.get('description') else ''
        role_part = ''
        lines.append(
            f'**{j["icon"]} {j["name"]}** – `{j["required_points"]:.0f} pkt`'
            f'{role_part}{desc_part}'
        )
    e.add_field(name='Dostępne prace', value='\n'.join(lines), inline=False)
    e.set_footer(text='Możesz posiadać kilka prac jednocześnie • Cywile only')
    return e


# ─── Refresh helper ───────────────────────────────────────────────────────────

async def _refresh_job_panel(guild: discord.Guild) -> None:
    """Edit the stored job panel embed, or do nothing if not found."""
    cfg = db.get_guild(guild.id)
    if not cfg or not cfg.get('job_channel_id'):
        return
    panel = db.get_panel_embed(guild.id, 'jobs')
    if not panel:
        return
    ch = guild.get_channel(panel['channel_id'])
    if not ch:
        return
    try:
        msg = await ch.fetch_message(panel['message_id'])
        await msg.edit(embed=_build_job_embed(guild.id, guild.name),
                       view=JobPanelView())
    except Exception:
        pass


# ─── Ephemeral per-job button views ───────────────────────────────────────────

class JobSelectButton(ui.Button):
    """Single button that immediately assigns one job + Discord role."""
    def __init__(self, job: dict):
        label = f'{job["name"]} – {job["required_points"]:.0f} pkt'
        if len(label) > 80:
            label = label[:77] + '...'
        super().__init__(
            label=label,
            style=discord.ButtonStyle.success,
            custom_id=f'job_pick_{job["id"]}',
            emoji=job.get('icon') or '💼',
        )
        self.job_id = job['id']

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        gid, uid = interaction.guild_id, interaction.user.id
        db.ensure_user(uid, gid, str(interaction.user), interaction.user.display_name)
        job = db.get_job_by_id(self.job_id)
        if not job:
            await interaction.followup.send(
                embed=discord.Embed(description='❌ Praca nie istnieje.', color=RED),
                ephemeral=True)
            return
        ok = db.select_job(uid, gid, self.job_id)
        if ok:
            if job.get('role_id'):
                role = interaction.guild.get_role(job['role_id'])
                member = interaction.guild.get_member(uid)
                if role and member:
                    try:
                        await member.add_roles(role, reason=f'Praca: {job["name"]}')
                    except discord.Forbidden:
                        pass
            await interaction.followup.send(
                embed=discord.Embed(
                    description=f'✅ Otrzymałeś pracę **{job["icon"]} {job["name"]}**!',
                    color=GREEN),
                ephemeral=True)
            await _refresh_job_panel(interaction.guild)
        else:
            await interaction.followup.send(
                embed=discord.Embed(
                    description=f'⚠️ Już masz pracę **{job["name"]}**.', color=YELLOW),
                ephemeral=True)


class JobDeselectButton(ui.Button):
    """Single button that immediately removes one job + Discord role."""
    def __init__(self, job: dict):
        label = job['name']
        if j_granted := job.get('admin_granted'):
            label += ' (admin)'
        if len(label) > 80:
            label = label[:77] + '...'
        super().__init__(
            label=label,
            style=discord.ButtonStyle.danger,
            custom_id=f'job_drop_{job["id"]}',
            emoji=job.get('icon') or '💼',
        )
        self.job_id = job['id']

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        gid, uid = interaction.guild_id, interaction.user.id
        job = db.get_job_by_id(self.job_id)
        if not job:
            await interaction.followup.send(
                embed=discord.Embed(description='❌ Praca nie istnieje.', color=RED),
                ephemeral=True)
            return
        ok = db.deselect_job(uid, gid, self.job_id)
        if ok:
            if job.get('role_id'):
                role = interaction.guild.get_role(job['role_id'])
                member = interaction.guild.get_member(uid)
                if role and member:
                    try:
                        await member.remove_roles(role, reason=f'Rezygnacja z pracy: {job["name"]}')
                    except discord.Forbidden:
                        pass
            await interaction.followup.send(
                embed=discord.Embed(
                    description=f'✅ Zrezygnowano z pracy **{job["icon"]} {job["name"]}**.',
                    color=ORANGE),
                ephemeral=True)
            await _refresh_job_panel(interaction.guild)
        else:
            await interaction.followup.send(
                embed=discord.Embed(
                    description=f'⚠️ Nie masz pracy **{job["name"]}**.', color=YELLOW),
                ephemeral=True)


class JobButtonView(ui.View):
    """Ephemeral view: one button per available job (max 25)."""
    def __init__(self, available_jobs: list):
        super().__init__(timeout=60)
        for job in available_jobs[:25]:
            self.add_item(JobSelectButton(job))


class JobDelistView(ui.View):
    """Ephemeral view: one button per current job for deselection (max 25)."""
    def __init__(self, current_jobs: list):
        super().__init__(timeout=60)
        for job in current_jobs[:25]:
            self.add_item(JobDeselectButton(job))


# ─── Persistent panel view ────────────────────────────────────────────────────

class JobPanelView(ui.View):
    """Persistent view for the job selection panel embed."""

    def __init__(self):
        super().__init__(timeout=None)

    def _is_civilian(self, interaction: discord.Interaction) -> bool:
        """Returns True if user has no faction assignment."""
        fm = db.get_user_faction_membership(interaction.user.id, interaction.guild_id)
        return fm is None

    async def _is_admin(self, interaction: discord.Interaction) -> bool:
        import json
        if interaction.user.guild_permissions.administrator:
            return True
        cfg = db.get_guild(interaction.guild_id) or {}
        try:
            aids = json.loads(cfg.get('admin_role_ids') or '[]')
        except Exception:
            aids = []
        return any(r.id in aids for r in interaction.user.roles)

    @ui.button(label='💼 Wybierz pracę', style=discord.ButtonStyle.success,
               custom_id='mops_job_select', row=0)
    async def btn_select(self, interaction: discord.Interaction, _: ui.Button):
        await interaction.response.defer(ephemeral=True)
        gid, uid = interaction.guild_id, interaction.user.id
        db.ensure_guild(gid)
        db.ensure_user(uid, gid, str(interaction.user), interaction.user.display_name)

        # Only civilians can self-select (admins can bypass via .givejob)
        if not self._is_civilian(interaction) and not await self._is_admin(interaction):
            await interaction.followup.send(
                embed=discord.Embed(
                    description='⚔️ Jesteś w frakcji – nie możesz samodzielnie wybrać pracy.\n'
                                'Poproś admina o `.givejob`.',
                    color=YELLOW),
                ephemeral=True)
            return

        available = db.get_available_jobs(uid, gid)
        if not available:
            await interaction.followup.send(
                embed=discord.Embed(
                    description='🔒 Brak dostępnych prac.\n'
                                'Zdobądź więcej punktów lub sprawdź `.jobs`.',
                    color=YELLOW),
                ephemeral=True)
            return

        view = JobButtonView(available)
        await interaction.followup.send(
            embed=discord.Embed(
                title='💼 Wybierz pracę',
                description='Kliknij przycisk, aby od razu otrzymać pracę i rolę:',
                color=BLURPLE),
            view=view,
            ephemeral=True)

    @ui.button(label='🚪 Zrezygnuj z pracy', style=discord.ButtonStyle.danger,
               custom_id='mops_job_deselect', row=0)
    async def btn_deselect(self, interaction: discord.Interaction, _: ui.Button):
        await interaction.response.defer(ephemeral=True)
        gid, uid = interaction.guild_id, interaction.user.id
        db.ensure_user(uid, gid, str(interaction.user), interaction.user.display_name)

        current = db.get_user_jobs(uid, gid)
        if not current:
            await interaction.followup.send(
                embed=discord.Embed(description='📭 Nie masz żadnej pracy.', color=YELLOW),
                ephemeral=True)
            return

        view = JobDelistView(current)
        await interaction.followup.send(
            embed=discord.Embed(
                title='🚪 Zrezygnuj z pracy',
                description='Kliknij przycisk, aby zrezygnować z pracy i stracić rolę:',
                color=ORANGE),
            view=view,
            ephemeral=True)

    @ui.button(label='📋 Moje prace', style=discord.ButtonStyle.secondary,
               custom_id='mops_job_list', row=0)
    async def btn_list(self, interaction: discord.Interaction, _: ui.Button):
        await interaction.response.defer(ephemeral=True)
        gid, uid = interaction.guild_id, interaction.user.id
        db.ensure_user(uid, gid, str(interaction.user), interaction.user.display_name)

        u = db.get_user(uid, gid)
        current = db.get_user_jobs(uid, gid)
        available = db.get_available_jobs(uid, gid)

        e = discord.Embed(
            title=f'📋 Twoje prace – {interaction.user.display_name}',
            color=BLURPLE)
        e.add_field(name='💰 Punkty', value=f'{u["points"]:.1f}' if u else '—', inline=True)

        if current:
            lines = [f'✅ {j["icon"]} **{j["name"]}**'
                     + (' *(admin)*' if j.get('admin_granted') else '')
                     for j in current]
            e.add_field(name='Aktywne prace', value='\n'.join(lines), inline=False)
        else:
            e.add_field(name='Aktywne prace', value='*Brak – wybierz pracę poniżej*', inline=False)

        if available:
            lines = [f'🔓 {j["icon"]} **{j["name"]}** – `{j["required_points"]:.0f} pkt`'
                     for j in available]
            e.add_field(name='Dostępne do wyboru', value='\n'.join(lines), inline=False)

        await interaction.followup.send(embed=e, ephemeral=True)


# ─── Cog ──────────────────────────────────────────────────────────────────────

class JobCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot


async def setup(bot: commands.Bot):
    await bot.add_cog(JobCog(bot))

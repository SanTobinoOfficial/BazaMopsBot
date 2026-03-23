import discord
from discord.ext import commands
from datetime import datetime, timedelta
import json
import re
import database as db
from cogs.clockin import send_log, log_embed


def _parse_duration(s: str) -> timedelta | None:
    """Parse '1h', '30m', '2d', '1h30m' etc. Returns timedelta or None."""
    pattern = r'(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?'
    m = re.fullmatch(pattern, s.strip().lower())
    if not m or not any(m.groups()):
        return None
    d, h, mi, sec = (int(x) if x else 0 for x in m.groups())
    return timedelta(days=d, hours=h, minutes=mi, seconds=sec)

BLURPLE = 0x7289DA
GREEN   = 0x43B581
RED     = 0xF04747
YELLOW  = 0xFAA61A
ORANGE  = 0xE67E22
GOLD    = 0xF1C40F


def _ok(desc):  return discord.Embed(description=f'✅ {desc}', color=GREEN)
def _err(desc): return discord.Embed(description=f'❌ {desc}', color=RED)
def _warn(desc):return discord.Embed(description=f'⚠️ {desc}', color=YELLOW)


class AdminCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._handlers = {
            # Points
            'addpoints':       self._cmd_addpoints,
            'removepoints':    self._cmd_removepoints,
            'setpoints':       self._cmd_setpoints,
            # Leaderboard
            'ban':             self._cmd_ban,
            'unban':           self._cmd_unban,
            # Warnings & moderation
            'warn':            self._cmd_warn,
            'warnings':        self._cmd_warnings,
            'clearwarn':       self._cmd_clearwarn,
            'warnpoints':      self._cmd_warnpoints,
            'clearwarnpoints': self._cmd_clearwarnpoints,
            'warnlb':          self._cmd_warnlb,
            'mute':            self._cmd_mute,
            'unmute':          self._cmd_unmute,
            'kick':            self._cmd_kick,
            'tempban':         self._cmd_tempban,
            'softban':         self._cmd_softban,
            'purge':           self._cmd_purge,
            'note':            self._cmd_note,
            'notes':           self._cmd_notes,
            'deletenote':      self._cmd_deletenote,
            'slowmode':        self._cmd_slowmode,
            # Economy admin
            'addmoney':        self._cmd_addmoney,
            'removemoney':     self._cmd_removemoney,
            'setmoney':        self._cmd_setmoney,
            # Ranks
            'giverank':        self._cmd_giverank,
            'takerank':        self._cmd_takerank,
            'createrank':      self._cmd_createrank,
            'deleterank':      self._cmd_deleterank,
            'editrank':        self._cmd_editrank,
            'ranks':           self._cmd_ranks,
            # User management
            'forceclockout':   self._cmd_forceclockout,
            'resetuser':       self._cmd_resetuser,
            'userinfo':        self._cmd_userinfo,
            # Server
            'serverstats':     self._cmd_serverstats,
            'config':          self._cmd_config,
            'resetperms':      self._cmd_resetperms,
            # Setup
            'setchannel':      self._cmd_setchannel,
            'setpoints_h':     self._cmd_setpointshour,
            'adminrole':       self._cmd_adminrole,
            'removeadminrole': self._cmd_removeadminrole,
            'officerole':      self._cmd_officerole,
            'removeofficerole':self._cmd_removeofficerole,
            'modrole':         self._cmd_modrole,
            'removemodrole':   self._cmd_removemodrole,
            'perminfo':        self._cmd_perminfo,
            'setowner':        self._cmd_setowner,
            'setwarnlimit':    self._cmd_setwarnlimit,
            'setmaxhours':     self._cmd_setmaxhours,
            # Factions
            'createfaction':      self._cmd_createfaction,
            'deletefaction':      self._cmd_deletefaction,
            'editfaction':        self._cmd_editfaction,
            'addfactionrole':     self._cmd_addfactionrole,
            'removefactionrole':  self._cmd_removefactionrole,
            'factions':           self._cmd_factions,
            'assignfaction':      self._cmd_assignfaction,
            'removefaction':      self._cmd_removefaction,
            # Jobs
            'createjob':          self._cmd_createjob,
            'deletejob':          self._cmd_deletejob,
            'editjob':            self._cmd_editjob,
            'jobs':               self._cmd_jobs,
            'givejob':            self._cmd_givejob,
            'takejob':            self._cmd_takejob,
            'setjobchannel':      self._cmd_setjobchannel,
            'jobpanel':           self._cmd_jobpanel,
            # Channel management (Dyno/ProBot/Carl-bot)
            'lock':               self._cmd_lock,
            'unlock':             self._cmd_unlock,
            'hide':               self._cmd_hide,
            'unhide':             self._cmd_unhide,
            'announce':           self._cmd_announce,
            # User management (Dyno)
            'nick':               self._cmd_nick,
            'move':               self._cmd_move,
            'deafen':             self._cmd_deafen,
            'undeafen':           self._cmd_undeafen,
            # Tags (Carl-bot)
            'tag':                self._cmd_tag_admin,
            'tagcreate':          self._cmd_tag_admin,
            'tagdelete':          self._cmd_tag_admin,
            'tagedit':            self._cmd_tag_admin,
        }

    # ── Permission helpers ────────────────────────────────────────────────────

    # ── Admin tier constants ──────────────────────────────────────────────────
    # tier 1 = Moderator (warn, mute, kick, note, nick, slowmode, lock, move...)
    # tier 2 = Oficer    (ban, purge, addpoints, giverank, addmoney, announce...)
    # tier 3 = Admin     (setpoints, resetuser, createrank, createfaction, config...)
    _MOD_CMDS = {
        'warn','warnings','clearwarn','warnpoints','warnlb',
        'mute','unmute','kick','note','notes','deletenote',
        'nick','move','deafen','undeafen','slowmode',
        'lock','unlock','hide','unhide',
        'userinfo','forceclockout',
        'tag','tagcreate','tagdelete','tagedit',
    }
    _OFFICER_CMDS = {
        'ban','unban','tempban','softban','purge',
        'addpoints','removepoints','giverank','takerank',
        'addmoney','removemoney',
        'clearwarnpoints',
        'announce',
        'givejob','takejob',
        'assignfaction','removefaction',
        'serverstats',
    }
    # Everything else requires full admin (tier 3)

    def _get_tier_ids(self, cfg: dict, tier: str) -> set:
        """Return combined role IDs for given tier and above."""
        admin   = set(json.loads(cfg.get('admin_role_ids')   or '[]'))
        officer = set(json.loads(cfg.get('officer_role_ids') or '[]'))
        mod     = set(json.loads(cfg.get('mod_role_ids')     or '[]'))
        if tier == 'mod':
            return admin | officer | mod
        if tier == 'officer':
            return admin | officer
        return admin  # 'admin' tier

    def _is_server_owner(self, member: discord.Member, guild_id: int) -> bool:
        if member.id == member.guild.owner_id:
            return True
        cfg = db.get_guild(guild_id)
        return bool(cfg and cfg.get('owner_id') and member.id == cfg['owner_id'])

    async def _is_admin(self, member: discord.Member, guild_id: int) -> bool:
        if member.guild_permissions.administrator or self._is_server_owner(member, guild_id):
            return True
        cfg = db.get_guild(guild_id) or {}
        return any(r.id in self._get_tier_ids(cfg, 'admin') for r in member.roles)

    async def _check_admin(self, msg: discord.Message) -> bool:
        """Full admin required."""
        if await self._is_admin(msg.author, msg.guild.id):
            return True
        await msg.reply(embed=_err('Brak uprawnień. Wymagana ranga: **Admin/Generał**.'),
                        mention_author=False)
        return False

    async def _can_use_cmd(self, member: discord.Member, guild_id: int,
                           command_name: str) -> bool:
        """Determine required tier from command name and check member roles."""
        if member.guild_permissions.administrator or self._is_server_owner(member, guild_id):
            return True
        cfg = db.get_guild(guild_id) or {}
        if command_name in self._MOD_CMDS:
            tier = 'mod'
        elif command_name in self._OFFICER_CMDS:
            tier = 'officer'
        else:
            tier = 'admin'
        ids = self._get_tier_ids(cfg, tier)
        return any(r.id in ids for r in member.roles)

    async def _can_grant_rank(self, member: discord.Member,
                              guild_id: int, rank: dict) -> bool:
        if rank.get('is_owner_only'):
            return self._is_server_owner(member, guild_id)
        try:
            grant_roles = json.loads(rank.get('grant_role_ids') or '[]')
        except Exception:
            grant_roles = []
        if grant_roles:
            return any(r.id in grant_roles for r in member.roles)
        return await self._is_admin(member, guild_id)

    def _resolve_member(self, msg: discord.Message, arg: str):
        uid = arg.strip('<@!>').strip()
        try:
            return msg.guild.get_member(int(uid))
        except ValueError:
            return None

    # ── Listener ──────────────────────────────────────────────────────────────

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
        args = parts[1:]
        if cmd not in self._handlers:
            return
        db.ensure_guild(message.guild.id)
        if not await self._can_use_cmd(message.author, message.guild.id, cmd):
            await message.reply(embed=_err('Nie masz uprawnień do tej komendy.'),
                                mention_author=False)
            return
        await self._handlers[cmd](message, args)

    # ── Discord role sync helper ───────────────────────────────────────────────

    async def _sync_rank_role(self, member: discord.Member, old_role_id):
        """After a points change, swap old auto-rank role for the new one on Discord."""
        gid = member.guild.id
        new_rank    = db.get_user_auto_rank(member.id, gid)
        new_role_id = new_rank.get('role_id') if new_rank else None
        if old_role_id == new_role_id:
            return
        try:
            if old_role_id:
                old_role = member.guild.get_role(old_role_id)
                if old_role and old_role in member.roles:
                    await member.remove_roles(old_role, reason='Auto-sync rangi po zmianie punktów')
            if new_role_id:
                new_role = member.guild.get_role(new_role_id)
                if new_role and new_role not in member.roles:
                    await member.add_roles(new_role, reason='Auto-sync rangi po zmianie punktów')
        except discord.Forbidden:
            pass

    def _user_status_fields(self, member: discord.Member) -> dict:
        """Build extra embed fields showing faction, current rank, Discord roles."""
        gid  = member.guild.id
        rank = db.get_user_auto_rank(member.id, gid)
        fm   = db.get_user_faction_membership(member.id, gid)
        # top 5 server roles (excluding @everyone, sorted by position desc)
        roles = sorted(
            [r for r in member.roles if r.name != '@everyone'],
            key=lambda r: r.position, reverse=True
        )[:5]
        fields: dict = {}
        fields['⭐ Ranga'] = (f'{rank["icon"]} {rank["name"]}' if rank else 'Cywil (brak rangi)')
        if fm:
            fields['⚔️ Frakcja'] = f'{fm["faction_icon"]} {fm["faction_name"]}'
        fields['🎭 Role DC'] = ' '.join(r.mention for r in roles) if roles else '—'
        return fields

    # ── Points ────────────────────────────────────────────────────────────────

    async def _cmd_addpoints(self, msg, args):
        if len(args) < 2:
            await msg.reply(embed=_err('`.addpoints @user <n> [nota]`'), mention_author=False)
            return
        m = self._resolve_member(msg, args[0])
        if not m:
            await msg.reply(embed=_err('Nie znaleziono użytkownika.'), mention_author=False); return
        try:
            pts = float(args[1])
        except ValueError:
            await msg.reply(embed=_err('Nieprawidłowa liczba.'), mention_author=False); return
        note = ' '.join(args[2:]) if len(args) > 2 else 'Ręczne dodanie przez admina'
        db.ensure_user(m.id, msg.guild.id, str(m), m.display_name)
        # Capture old auto-rank before change for Discord sync
        _old_rank    = db.get_user_auto_rank(m.id, msg.guild.id)
        _old_role_id = _old_rank.get('role_id') if _old_rank else None
        new = db.add_points(m.id, msg.guild.id, pts, note=note,
                            transaction_type='manual', assigned_by=msg.author.id)
        await self._sync_rank_role(m, _old_role_id)
        # Build reply embed with user status
        e = _ok(f'**+{pts:.1f} pkt** → **{m.display_name}** | Stan: **{new:.1f} pkt**')
        e.set_thumbnail(url=m.display_avatar.url)
        e.add_field(name='📝 Nota', value=note, inline=False)
        for name, val in self._user_status_fields(m).items():
            e.add_field(name=name, value=val, inline=True)
        e.set_footer(text=f'Przez: {msg.author.display_name}')
        await msg.reply(embed=e, mention_author=False)
        db.log_action(msg.guild.id, 'points_add', user_id=m.id, actor_id=msg.author.id,
                      details={'delta': pts, 'new_total': new, 'note': note})
        await send_log(msg.guild, log_embed('💰 Punkty dodane', GREEN,
            Użytkownik=m.mention, Zmiana=f'+{pts:.1f}',
            **{'Nowy stan': f'{new:.1f}'}, Nota=note,
            Przez=msg.author.mention))

    async def _cmd_removepoints(self, msg, args):
        if len(args) < 2:
            await msg.reply(embed=_err('`.removepoints @user <n> [nota]`'), mention_author=False); return
        m = self._resolve_member(msg, args[0])
        if not m:
            await msg.reply(embed=_err('Nie znaleziono użytkownika.'), mention_author=False); return
        try:
            pts = float(args[1])
        except ValueError:
            await msg.reply(embed=_err('Nieprawidłowa liczba.'), mention_author=False); return
        note = ' '.join(args[2:]) if len(args) > 2 else 'Ręczne odjęcie przez admina'
        db.ensure_user(m.id, msg.guild.id, str(m), m.display_name)
        _old_rank    = db.get_user_auto_rank(m.id, msg.guild.id)
        _old_role_id = _old_rank.get('role_id') if _old_rank else None
        new = db.add_points(m.id, msg.guild.id, -pts, note=note,
                            transaction_type='manual', assigned_by=msg.author.id)
        await self._sync_rank_role(m, _old_role_id)
        e = _ok(f'**-{pts:.1f} pkt** ← **{m.display_name}** | Stan: **{new:.1f} pkt**')
        e.set_thumbnail(url=m.display_avatar.url)
        e.add_field(name='📝 Nota', value=note, inline=False)
        for name, val in self._user_status_fields(m).items():
            e.add_field(name=name, value=val, inline=True)
        e.set_footer(text=f'Przez: {msg.author.display_name}')
        await msg.reply(embed=e, mention_author=False)
        await send_log(msg.guild, log_embed('💸 Punkty odjęte', ORANGE,
            Użytkownik=m.mention, Zmiana=f'-{pts:.1f}',
            **{'Nowy stan': f'{new:.1f}'}, Nota=note, Przez=msg.author.mention))

    async def _cmd_setpoints(self, msg, args):
        if len(args) < 2:
            await msg.reply(embed=_err('`.setpoints @user <n> [nota]`'), mention_author=False); return
        m = self._resolve_member(msg, args[0])
        if not m:
            await msg.reply(embed=_err('Nie znaleziono użytkownika.'), mention_author=False); return
        try:
            pts = float(args[1])
        except ValueError:
            await msg.reply(embed=_err('Nieprawidłowa liczba.'), mention_author=False); return
        note = ' '.join(args[2:]) if len(args) > 2 else 'Ustawienie przez admina'
        db.ensure_user(m.id, msg.guild.id, str(m), m.display_name)
        _old_rank    = db.get_user_auto_rank(m.id, msg.guild.id)
        _old_role_id = _old_rank.get('role_id') if _old_rank else None
        new = db.set_points(m.id, msg.guild.id, pts, note=note, assigned_by=msg.author.id)
        await self._sync_rank_role(m, _old_role_id)
        e = _ok(f'Ustawiono **{pts:.1f} pkt** dla **{m.display_name}**')
        e.set_thumbnail(url=m.display_avatar.url)
        for name, val in self._user_status_fields(m).items():
            e.add_field(name=name, value=val, inline=True)
        e.set_footer(text=f'Przez: {msg.author.display_name}')
        await msg.reply(embed=e, mention_author=False)
        await send_log(msg.guild, log_embed('📊 Punkty ustawione', BLURPLE,
            Użytkownik=m.mention, **{'Nowy stan': f'{new:.1f}'}, Nota=note,
            Przez=msg.author.mention))

    # ── Ban / Unban ───────────────────────────────────────────────────────────

    async def _cmd_ban(self, msg, args):
        if not args:
            await msg.reply(embed=_err('`.ban @user`'), mention_author=False); return
        m = self._resolve_member(msg, args[0])
        if not m:
            await msg.reply(embed=_err('Nie znaleziono użytkownika.'), mention_author=False); return
        db.ensure_user(m.id, msg.guild.id, str(m), m.display_name)
        db.update_user(m.id, msg.guild.id, is_banned=1)
        db.log_action(msg.guild.id, 'ban', user_id=m.id, actor_id=msg.author.id)
        await msg.reply(embed=_ok(f'**{m.display_name}** zablokowany na liście rankingowej.'),
                        mention_author=False)
        await send_log(msg.guild, log_embed('🔨 Ban z Rankingu', RED,
            Użytkownik=m.mention, Przez=msg.author.mention))

    async def _cmd_unban(self, msg, args):
        if not args:
            await msg.reply(embed=_err('`.unban @user`'), mention_author=False); return
        m = self._resolve_member(msg, args[0])
        if not m:
            await msg.reply(embed=_err('Nie znaleziono użytkownika.'), mention_author=False); return
        db.update_user(m.id, msg.guild.id, is_banned=0)
        db.log_action(msg.guild.id, 'unban', user_id=m.id, actor_id=msg.author.id)
        await msg.reply(embed=_ok(f'**{m.display_name}** odblokowany.'), mention_author=False)
        await send_log(msg.guild, log_embed('✅ Odblokowany', GREEN,
            Użytkownik=m.mention, Przez=msg.author.mention))

    # ── Warnings ──────────────────────────────────────────────────────────────

    async def _cmd_warn(self, msg, args):
        if not args:
            await msg.reply(embed=_err('`.warn @user [powód]`'), mention_author=False); return
        m = self._resolve_member(msg, args[0])
        if not m:
            await msg.reply(embed=_err('Nie znaleziono użytkownika.'), mention_author=False); return
        reason = ' '.join(args[1:]) if len(args) > 1 else 'Brak powodu'
        db.ensure_user(m.id, msg.guild.id, str(m), m.display_name)
        db.add_warning(m.id, msg.guild.id, reason=reason,
                       warned_by=msg.author.id, is_auto=False)
        # Each .warn = +0.5 warnpoints
        db.add_warn_points(m.id, msg.guild.id, 0.5, reason=reason, given_by=msg.author.id)
        count = db.get_warning_count(m.id, msg.guild.id)
        cfg = db.get_guild(msg.guild.id) or {}
        limit = cfg.get('warn_limit', 3)
        e = _ok(f'Ostrzeżono **{m.display_name}** ({count}/{limit} ostrzeżeń)')
        e.add_field(name='📝 Powód', value=reason)
        # Auto-actions
        action_msg = ''
        try:
            if count >= limit:
                db.update_user(m.id, msg.guild.id, is_banned=1)
                await m.ban(reason=f'Auto-ban: {count} ostrzeżeń. {reason}')
                action_msg = '🔨 Auto-ban wykonany!'
            elif count == 2:
                await m.kick(reason=f'Auto-kick: 2 ostrzeżenia. {reason}')
                action_msg = '👢 Auto-kick wykonany!'
            elif count == 1:
                await m.timeout(timedelta(hours=1), reason=f'Auto-timeout: 1 ostrzeżenie. {reason}')
                action_msg = '🔇 Auto-timeout 1h wykonany!'
        except discord.Forbidden:
            action_msg = '⚠️ Brak uprawnień do wykonania auto-akcji.'
        except Exception:
            pass
        if action_msg:
            e.add_field(name='🤖 Auto-akcja', value=action_msg, inline=False)
        await msg.reply(embed=e, mention_author=False)
        db.log_action(msg.guild.id, 'warn', user_id=m.id, actor_id=msg.author.id,
                      details={'reason': reason, 'count': count})
        await send_log(msg.guild, log_embed('⚠️ Ostrzeżenie', YELLOW,
            Użytkownik=m.mention, Powód=reason,
            **{f'Ostrzeżenia': f'{count}/{limit}'}, Przez=msg.author.mention))

    async def _cmd_warnings(self, msg, args):
        m = self._resolve_member(msg, args[0]) if args else msg.author
        if not m:
            await msg.reply(embed=_err('Nie znaleziono użytkownika.'), mention_author=False); return
        warns = db.get_warnings(m.id, msg.guild.id)
        cfg = db.get_guild(msg.guild.id) or {}
        limit = cfg.get('warn_limit', 3)
        e = discord.Embed(title=f'⚠️ Ostrzeżenia – {m.display_name}',
                          color=YELLOW if warns else GREEN)
        if warns:
            lines = []
            for w in warns:
                tag = '🤖' if w['is_auto'] else '👤'
                lines.append(f'`#{w["id"]}` {tag} {w["reason"][:60]} | {w["created_at"][:10]}')
            e.description = '\n'.join(lines)
            e.set_footer(text=f'{len(warns)}/{limit} ostrzeżeń')
        else:
            e.description = '✅ Brak ostrzeżeń.'
        await msg.reply(embed=e, mention_author=False)

    async def _cmd_clearwarn(self, msg, args):
        if not args:
            await msg.reply(embed=_err('`.clearwarn @user [id_ostrzeżenia]`'),
                            mention_author=False); return
        m = self._resolve_member(msg, args[0])
        if not m:
            await msg.reply(embed=_err('Nie znaleziono użytkownika.'), mention_author=False); return
        warn_id = int(args[1]) if len(args) > 1 and args[1].isdigit() else None
        n = db.clear_warnings(m.id, msg.guild.id, warn_id)
        await msg.reply(embed=_ok(f'Usunięto **{n}** ostrzeżenie(ń) dla **{m.display_name}**.'),
                        mention_author=False)
        db.log_action(msg.guild.id, 'warn_clear', user_id=m.id, actor_id=msg.author.id,
                      details={'warn_id': warn_id, 'count_removed': n})
        await send_log(msg.guild, log_embed('🧹 Wyczyszczono ostrzeżenia', GREEN,
            Użytkownik=m.mention, Usunięto=str(n), Przez=msg.author.mention))

    # ── Ranks ─────────────────────────────────────────────────────────────────

    async def _cmd_giverank(self, msg, args):
        """Gives any rank (special or auto) to a member.
        For auto-ranks, points are raised to the required threshold.
        Usage: .giverank @user <nazwa rangi> [nota]
        """
        if len(args) < 2:
            await msg.reply(embed=_err('`.giverank @user <nazwa rangi> [nota]`'),
                            mention_author=False); return
        m = self._resolve_member(msg, args[0])
        if not m:
            await msg.reply(embed=_err('Nie znaleziono użytkownika.'), mention_author=False); return

        rank, note = None, ''
        for i in range(len(args), 1, -1):
            r = db.get_rank_by_name(msg.guild.id, ' '.join(args[1:i]))
            if r:
                rank, note = r, ' '.join(args[i:])
                break
        if not rank:
            await msg.reply(embed=_err('Nie znaleziono rangi. Użyj `.ranks`.'),
                            mention_author=False); return

        db.ensure_user(m.id, msg.guild.id, str(m), m.display_name)

        if rank.get('is_special') or rank.get('is_owner_only'):
            # ── Special / owner rank ──────────────────────────────────────────
            if not await self._can_grant_rank(msg.author, msg.guild.id, rank):
                key = 'Ta ranga jest **tylko dla właściciela/dowódcy**.' if rank.get('is_owner_only') \
                      else 'Twoja rola nie ma uprawnień do nadawania tej rangi.'
                await msg.reply(embed=_err(key), mention_author=False); return
            ok = db.give_special_rank(m.id, msg.guild.id, rank['id'],
                                      assigned_by=msg.author.id, note=note)
            if not ok:
                await msg.reply(embed=_warn(f'**{m.display_name}** już posiada tę rangę.'),
                                mention_author=False); return
            if rank.get('role_id'):
                role = msg.guild.get_role(rank['role_id'])
                if role:
                    try: await m.add_roles(role, reason=f'Ranga spec.: {rank["name"]}')
                    except discord.Forbidden: pass
            badge = '👑' if rank.get('is_owner_only') else '🎖️'
            e = _ok(f'{badge} Nadano rangę **{rank["icon"]} {rank["name"]}** → **{m.display_name}**')
        else:
            # ── Auto-rank: raise points to threshold + sync Discord role ──────
            req_pts = rank.get('required_points', 0)
            _old    = db.get_user_auto_rank(m.id, msg.guild.id)
            _old_id = _old.get('role_id') if _old else None
            user    = db.get_user(m.id, msg.guild.id)
            cur_pts = user.get('points', 0) if user else 0
            if cur_pts < req_pts:
                full_note = f'Admin nadał rangę: {rank["name"]}' + (f' – {note}' if note else '')
                db.set_points(m.id, msg.guild.id, req_pts,
                              note=full_note, assigned_by=msg.author.id)
            await self._sync_rank_role(m, _old_id)
            badge = '🤖'
            e = _ok(f'🤖 Ustawiono rangę **{rank["icon"]} {rank["name"]}** → **{m.display_name}**\n'
                    f'Punkty: **{max(cur_pts, req_pts):.0f}** pkt')

        if note:
            e.add_field(name='📝 Nota', value=note, inline=False)
        e.set_thumbnail(url=m.display_avatar.url)
        for name, val in self._user_status_fields(m).items():
            e.add_field(name=name, value=val, inline=True)
        e.set_footer(text=f'Przez: {msg.author.display_name}')
        await msg.reply(embed=e, mention_author=False)
        db.log_action(msg.guild.id, 'rank_give', user_id=m.id, actor_id=msg.author.id,
                      details={'rank': rank['name'], 'note': note})
        await send_log(msg.guild, log_embed(f'{badge} Ranga Nadana', GOLD,
            Użytkownik=m.mention,
            Ranga=f'{rank["icon"]} {rank["name"]}',
            Nota=note or '—', Przez=msg.author.mention))

    async def _cmd_takerank(self, msg, args):
        if len(args) < 2:
            await msg.reply(embed=_err('`.takerank @user <nazwa rangi>`'),
                            mention_author=False); return
        m = self._resolve_member(msg, args[0])
        if not m:
            await msg.reply(embed=_err('Nie znaleziono użytkownika.'), mention_author=False); return
        rank = db.get_rank_by_name(msg.guild.id, ' '.join(args[1:]))
        if not rank:
            await msg.reply(embed=_err('Nie znaleziono rangi.'), mention_author=False); return
        if rank.get('is_owner_only') and not self._is_server_owner(msg.author, msg.guild.id):
            await msg.reply(embed=_err('Tylko właściciel/dowódca może odebrać tę rangę.'),
                            mention_author=False); return
        ok = db.remove_special_rank(m.id, msg.guild.id, rank['id'])
        if not ok:
            await msg.reply(embed=_warn(f'**{m.display_name}** nie posiada tej rangi.'),
                            mention_author=False); return
        await msg.reply(embed=_ok(f'Odebrano **{rank["icon"]} {rank["name"]}** od **{m.display_name}**.'),
                        mention_author=False)
        if rank.get('role_id'):
            role = msg.guild.get_role(rank['role_id'])
            if role and role in m.roles:
                try:
                    await m.remove_roles(role)
                except discord.Forbidden:
                    pass
        db.log_action(msg.guild.id, 'rank_take', user_id=m.id, actor_id=msg.author.id,
                      details={'rank': rank['name']})
        await send_log(msg.guild, log_embed('🗑️ Ranga Odebrana', ORANGE,
            Użytkownik=m.mention, Ranga=f'{rank["icon"]} {rank["name"]}',
            Przez=msg.author.mention))

    async def _cmd_createrank(self, msg, args):
        """
        .createrank <nazwa> <punkty|SPECIAL|UNIT> [FRAKCJA:<nazwa>] [ikona] [#kolor] [opis]
        SPECIAL = ranga specjalna (admin może nadawać)
        UNIT    = jednostka (tylko właściciel/dowódca może nadawać)
        FRAKCJA:<nazwa> = przypisz rangę do frakcji (tylko dla rang automatycznych)
        """
        if len(args) < 2:
            await msg.reply(embed=_err(
                '`.createrank <nazwa> <punkty|SPECIAL|UNIT> [FRAKCJA:<nazwa>] [ikona] [#kolor] [opis]`\n'
                '`SPECIAL` = ranga specjalna (admin)\n'
                '`UNIT` = jednostka (tylko właściciel/dowódca)\n'
                '`FRAKCJA:Alpha-1` = ranga należy do frakcji'
            ), mention_author=False); return

        name = args[0]
        type_arg = args[1].upper()
        is_special = type_arg in ('SPECIAL', 'UNIT')
        is_owner_only = type_arg == 'UNIT'
        try:
            req_pts = 0.0 if is_special else float(args[1])
        except ValueError:
            await msg.reply(embed=_err('Punkty muszą być liczbą, "SPECIAL" lub "UNIT".'),
                            mention_author=False); return

        # Parse optional FRAKCJA: flag from remaining args
        remaining = args[2:]
        faction_id = None
        faction_name_str = None
        filtered = []
        for a in remaining:
            if a.upper().startswith('FRAKCJA:'):
                faction_name_str = a[8:].strip()
            else:
                filtered.append(a)
        remaining = filtered

        if faction_name_str:
            f = db.get_faction_by_name(msg.guild.id, faction_name_str)
            if not f:
                await msg.reply(embed=_err(f'Frakcja **{faction_name_str}** nie istnieje. Użyj `.createfaction`.'),
                                mention_author=False); return
            faction_id = f['id']

        icon  = remaining[0] if remaining else ('👑' if is_owner_only else ('🎖️' if is_special else '⭐'))
        color = '#7289da'
        desc  = ''
        rest  = remaining[1:] if remaining else []
        if rest:
            if rest[0].startswith('#'):
                color = rest[0]
                desc = ' '.join(rest[1:])
            else:
                desc = ' '.join(rest)

        if db.get_rank_by_name(msg.guild.id, name):
            await msg.reply(embed=_err(f'Ranga **{name}** już istnieje.'), mention_author=False); return

        rank = db.create_rank(msg.guild.id, name, req_pts, color=color,
                              description=desc, icon=icon,
                              is_special=is_special, is_owner_only=is_owner_only,
                              faction_id=faction_id)
        if not rank:
            await msg.reply(embed=_err('Błąd tworzenia rangi.'), mention_author=False); return

        badge = '👑 UNIT' if is_owner_only else ('🎖️ SPECIAL' if is_special else f'🤖 AUTO ({req_pts:.0f} pkt)')
        faction_str = f' | ⚔️ {faction_name_str}' if faction_name_str else ''
        e = _ok(f'Utworzono rangę **{icon} {name}** [{badge}{faction_str}]')
        if desc:
            e.add_field(name='Opis', value=desc)
        await msg.reply(embed=e, mention_author=False)

    async def _cmd_deleterank(self, msg, args):
        if not args:
            await msg.reply(embed=_err('`.deleterank <nazwa>`'), mention_author=False); return
        rank = db.get_rank_by_name(msg.guild.id, ' '.join(args))
        if not rank:
            await msg.reply(embed=_err('Nie znaleziono rangi.'), mention_author=False); return
        if rank.get('is_owner_only') and not self._is_server_owner(msg.author, msg.guild.id):
            await msg.reply(embed=_err('Tylko właściciel/dowódca może usunąć rangę UNIT.'),
                            mention_author=False); return
        db.delete_rank(rank['id'])
        await msg.reply(embed=_ok(f'Usunięto rangę **{rank["icon"]} {rank["name"]}**.'),
                        mention_author=False)

    async def _cmd_editrank(self, msg, args):
        if len(args) < 3:
            await msg.reply(embed=_err(
                '`.editrank <nazwa> <pole> <wartość>`\n'
                'Pola: `name`, `points`, `icon`, `color`, `description`, `category`, `faction`\n'
                '`faction NONE` = usuń z frakcji | `faction Alpha-1` = przypisz do frakcji'
            ), mention_author=False); return
        rank = db.get_rank_by_name(msg.guild.id, args[0])
        if not rank:
            await msg.reply(embed=_err('Nie znaleziono rangi.'), mention_author=False); return
        field = args[1].lower()
        value = ' '.join(args[2:])

        # Special case: faction field
        if field == 'faction':
            if value.upper() == 'NONE':
                db.update_rank(rank['id'], faction_id=None)
                await msg.reply(embed=_ok(f'Usunięto rangę **{rank["name"]}** z frakcji.'),
                                mention_author=False)
            else:
                f = db.get_faction_by_name(msg.guild.id, value)
                if not f:
                    await msg.reply(embed=_err(f'Frakcja **{value}** nie istnieje.'),
                                    mention_author=False); return
                db.update_rank(rank['id'], faction_id=f['id'])
                await msg.reply(embed=_ok(f'Przypisano **{rank["name"]}** do frakcji **{f["icon"]} {f["name"]}**.'),
                                mention_author=False)
            return

        fields_map = {
            'name':        ('name',            lambda v: v),
            'points':      ('required_points', float),
            'icon':        ('icon',            lambda v: v),
            'color':       ('color',           lambda v: v),
            'description': ('description',     lambda v: v),
            'category':    ('category',        lambda v: v),
        }
        if field not in fields_map:
            await msg.reply(embed=_err('Pole: `name`, `points`, `icon`, `color`, `description`, `category`, `faction`'),
                            mention_author=False); return
        col, converter = fields_map[field]
        try:
            db.update_rank(rank['id'], **{col: converter(value)})
        except ValueError:
            await msg.reply(embed=_err('Nieprawidłowa wartość.'), mention_author=False); return
        await msg.reply(embed=_ok(f'Zaktualizowano **{rank["name"]}**: `{field}` = `{value}`'),
                        mention_author=False)

    async def _cmd_ranks(self, msg, args):
        gid      = msg.guild.id
        ranks    = db.get_ranks(gid)
        factions = db.get_factions(gid)
        if not ranks and not factions:
            await msg.reply(embed=_warn('Brak rang. Użyj `.createrank`.'), mention_author=False)
            return

        # Build faction id→name map
        fac_map = {f['id']: f for f in factions}

        # Group ranks by category / faction / type
        cats = {}
        for r in ranks:
            cat = r.get('category') or ''
            if not cat:
                fid = r.get('faction_id')
                if fid and fid in fac_map:
                    f = fac_map[fid]
                    cat = f'{f["icon"]} {f["name"]}'
                elif r.get('is_owner_only'):
                    cat = '👑 Jednostki'
                elif r.get('is_special'):
                    cat = '🎖️ Specjalne'
                else:
                    cat = '🤖 Cywile'
            cats.setdefault(cat, []).append(r)

        e = discord.Embed(title=f'⭐ Lista Rang – {msg.guild.name}', color=BLURPLE)

        for cat_name, cat_ranks in cats.items():
            lines = []
            for r in cat_ranks:
                dot = '●'
                if r.get('is_owner_only'):
                    line = f'{dot} {r["icon"]} **{r["name"]}** 👑'
                elif r.get('is_special'):
                    line = f'{dot} {r["icon"]} **{r["name"]}**'
                    if r.get('description'):
                        line += f' – {r["description"]}'
                else:
                    line = f'{dot} {r["icon"]} **{r["name"]}** – `{r["required_points"]:.0f} pkt`'
                lines.append(line)
            e.add_field(name=f'─── {cat_name} ───', value='\n'.join(lines) or '—', inline=False)

        if factions:
            lines = []
            for f in factions:
                members = db.get_faction_members(gid, f['id'])
                line = f'● {f["icon"]} **{f["name"]}** ({len(members)} czł.)'
                if f.get('description'):
                    line += f' – {f["description"]}'
                lines.append(line)
            e.add_field(name='─── ⚔️ Frakcje ───', value='\n'.join(lines), inline=False)

        await msg.reply(embed=e, mention_author=False)

    # ── User management ───────────────────────────────────────────────────────

    async def _cmd_forceclockout(self, msg, args):
        if not args:
            await msg.reply(embed=_err('`.forceclockout @user`'), mention_author=False); return
        m = self._resolve_member(msg, args[0])
        if not m:
            await msg.reply(embed=_err('Nie znaleziono.'), mention_author=False); return
        ok = db.force_clock_out(m.id, msg.guild.id)
        txt = f'Wymuszono wylogowanie **{m.display_name}**.' if ok else f'**{m.display_name}** nie był zalogowany.'
        await msg.reply(embed=_ok(txt) if ok else _warn(txt), mention_author=False)
        if ok:
            await send_log(msg.guild, log_embed('⚡ Force Clock Out', ORANGE,
                Użytkownik=m.mention, Przez=msg.author.mention))

    async def _cmd_resetuser(self, msg, args):
        if not args:
            await msg.reply(embed=_err('`.resetuser @user`'), mention_author=False); return
        m = self._resolve_member(msg, args[0])
        if not m:
            await msg.reply(embed=_err('Nie znaleziono.'), mention_author=False); return
        db.reset_user(m.id, msg.guild.id)
        db.log_action(msg.guild.id, 'reset', user_id=m.id, actor_id=msg.author.id)
        await msg.reply(embed=_ok(f'Zresetowano dane **{m.display_name}**.'), mention_author=False)
        await send_log(msg.guild, log_embed('🗑️ Reset Użytkownika', RED,
            Użytkownik=m.mention, Przez=msg.author.mention))

    async def _cmd_userinfo(self, msg, args):
        m = self._resolve_member(msg, args[0]) if args else msg.author
        if not m:
            await msg.reply(embed=_err('Nie znaleziono.'), mention_author=False); return
        db.ensure_user(m.id, msg.guild.id, str(m), m.display_name)
        u          = db.get_user(m.id, msg.guild.id)
        rank       = db.get_user_auto_rank(m.id, msg.guild.id)
        specials   = db.get_user_special_ranks(m.id, msg.guild.id)
        warns      = db.get_warnings(m.id, msg.guild.id)
        txs        = db.get_user_transactions(m.id, msg.guild.id, limit=5)
        faction_mem= db.get_user_faction_membership(m.id, msg.guild.id)
        cfg        = db.get_guild(msg.guild.id) or {}
        warn_limit = cfg.get('warn_limit', 3)

        # Collect all Discord roles (sorted by position, skip @everyone)
        dc_roles = sorted(
            [r for r in m.roles if r.name != '@everyone'],
            key=lambda r: r.position, reverse=True
        )

        e = discord.Embed(title=f'📋 Info: {m.display_name}', color=BLURPLE, timestamp=datetime.now())
        e.set_thumbnail(url=m.display_avatar.url)

        # ── Stats row ────────────────────────────────────────────────────────
        e.add_field(name='💰 Punkty',  value=f'{u["points"]:.1f}',        inline=True)
        e.add_field(name='⏱️ Godziny', value=f'{u["total_hours"]:.2f}h',  inline=True)
        e.add_field(name='📅 Sesje',   value=str(u['sessions_count']),    inline=True)

        # ── Faction ──────────────────────────────────────────────────────────
        if faction_mem:
            e.add_field(name='⚔️ Frakcja',
                        value=f'{faction_mem["faction_icon"]} **{faction_mem["faction_name"]}**',
                        inline=True)

        # ── Rank row ─────────────────────────────────────────────────────────
        e.add_field(name='⭐ Ranga auto',
                    value=f'{rank["icon"]} {rank["name"]}' if rank else 'Cywil (brak rangi)',
                    inline=True)
        e.add_field(name='🎖️ Rangi spec.',
                    value=', '.join(f'{r["icon"]} {r["name"]}' for r in specials) or 'Brak',
                    inline=True)

        # ── Status ───────────────────────────────────────────────────────────
        e.add_field(name='🟢 Aktywny',
                    value='Tak' if u['is_clocked_in'] else 'Nie', inline=True)
        e.add_field(name='⚠️ Ostrzeżenia',
                    value=f'{len(warns)}/{warn_limit}', inline=True)
        if u['is_banned']:
            e.add_field(name='🔨 Status', value='ZABLOKOWANY na lb', inline=True)

        # ── Discord roles list ────────────────────────────────────────────────
        if dc_roles:
            roles_line = ' '.join(r.mention for r in dc_roles[:10])
            if len(dc_roles) > 10:
                roles_line += f' *+{len(dc_roles)-10}*'
            e.add_field(name=f'🎭 Role Discord ({len(dc_roles)})', value=roles_line, inline=False)

        # ── Recent transactions ───────────────────────────────────────────────
        if txs:
            lines = []
            for t in txs:
                s = '+' if t['points_change'] > 0 else ''
                lines.append(f'`{s}{t["points_change"]:.1f}` {(t["note"] or "")[:40]}')
            e.add_field(name='💸 Ostatnie transakcje', value='\n'.join(lines), inline=False)

        e.set_footer(text=f'ID: {m.id}')
        await msg.reply(embed=e, mention_author=False)

    # ── Server ────────────────────────────────────────────────────────────────

    async def _cmd_serverstats(self, msg, args):
        s = db.get_guild_stats(msg.guild.id)
        cfg = db.get_guild(msg.guild.id) or {}
        e = discord.Embed(title='📊 Statystyki Serwera', color=BLURPLE, timestamp=datetime.now())
        e.add_field(name='👥 Użytkownicy', value=str(s['total_users']), inline=True)
        e.add_field(name='💰 Łączne pkt', value=f'{s["total_points"]:.0f}', inline=True)
        e.add_field(name='⏱️ Godziny', value=f'{s["total_hours"]}h', inline=True)
        e.add_field(name='📅 Sesje', value=str(s['total_sessions']), inline=True)
        e.add_field(name='🟢 Aktywni', value=str(s['active_now']), inline=True)
        e.add_field(name='⚠️ Ostrzeżenia', value=str(s['warning_count']), inline=True)
        e.add_field(name='🔨 Zablokowanych', value=str(s['banned_count']), inline=True)
        e.add_field(name='⭐ Rang', value=str(s['rank_count']), inline=True)
        e.add_field(name='💡 Pkt/h', value=f'{cfg.get("points_per_hour", 10):.1f}', inline=True)
        await msg.reply(embed=e, mention_author=False)

    # ── Setup ─────────────────────────────────────────────────────────────────

    async def _cmd_resetperms(self, msg, args):
        """Clear all rank command restrictions (everyone gets full user command access)."""
        if not await self._check_admin(msg): return
        db.force_reseed_permissions(msg.guild.id)
        e = discord.Embed(
            title='✅ Uprawnienia użytkowników zresetowane',
            description=(
                'Wszystkie restrykcje komend użytkownika zostały usunięte.\n'
                'Każdy ma teraz dostęp do ekonomii, gier i fun.\n\n'
                'Aby zarządzać uprawnieniami **adminów**:\n'
                '`.perminfo` — pokaż konfigurację\n'
                '`.adminrole @rola` — Generał/Królewscy\n'
                '`.officerole @rola` — Kapitan\n'
                '`.modrole @rola` — Military Police / Squad Leader'
            ), color=0x43B581)
        await msg.reply(embed=e, mention_author=False)

    async def _cmd_config(self, msg, args):
        cfg = db.get_guild(msg.guild.id) or {}
        e = discord.Embed(title='⚙️ Konfiguracja Serwera', color=BLURPLE)
        def ch(cid):
            if not cid: return '❌ Nie ustawiony'
            c = msg.guild.get_channel(cid)
            return c.mention if c else f'ID:{cid}'
        e.add_field(name='📋 Kanał Clock', value=ch(cfg.get('clock_channel_id')), inline=True)
        e.add_field(name='📝 Kanał Logów', value=ch(cfg.get('log_channel_id')), inline=True)
        e.add_field(name='🎛️ Kanał Panelu', value=ch(cfg.get('command_panel_channel_id')), inline=True)
        e.add_field(name='💰 Pkt/h', value=f'{cfg.get("points_per_hour", 10):.1f}', inline=True)
        e.add_field(name='⏱️ Min. czas', value=f'{cfg.get("min_clock_minutes", 5)} min', inline=True)
        e.add_field(name='🤖 Max h (antycheat)', value=f'{cfg.get("auto_clockout_hours", 12)}h', inline=True)
        e.add_field(name='⚠️ Limit warnów', value=str(cfg.get('warn_limit', 3)), inline=True)
        schedule = db.get_embed_schedule(msg.guild.id)
        lines = []
        for i in range(7):
            d = schedule.get(str(i), {})
            status = '✅' if d.get('enabled', True) else '❌'
            h, m2 = d.get('hour', 0), d.get('minute', 0)
            lines.append(f'{status} **{db.DAYS_PL[i][:3]}** {h:02d}:{m2:02d}')
        e.add_field(name='📅 Harmonogram apelów', value='\n'.join(lines), inline=False)
        await msg.reply(embed=e, mention_author=False)

    async def _cmd_setchannel(self, msg, args):
        if len(args) < 2:
            await msg.reply(embed=_err('`.setchannel <clock|log|panel> #kanał`'), mention_author=False); return
        kind = args[0].lower()
        ch_id = args[1].strip('<#>').strip()
        try:
            ch_id = int(ch_id)
        except ValueError:
            await msg.reply(embed=_err('Nieprawidłowy kanał.'), mention_author=False); return
        ch = msg.guild.get_channel(ch_id)
        if not ch:
            await msg.reply(embed=_err('Kanał nie istnieje.'), mention_author=False); return
        mapping = {'clock': 'clock_channel_id', 'log': 'log_channel_id',
                   'panel': 'command_panel_channel_id'}
        if kind not in mapping:
            await msg.reply(embed=_err('Typ: `clock`, `log`, `panel`'), mention_author=False); return
        db.update_guild(msg.guild.id, **{mapping[kind]: ch_id})
        await msg.reply(embed=_ok(f'Ustawiono kanał **{kind}**: {ch.mention}'), mention_author=False)

    async def _cmd_setpointshour(self, msg, args):
        if not args:
            await msg.reply(embed=_err('`.setpoints_h <n>`'), mention_author=False); return
        try:
            db.update_guild(msg.guild.id, points_per_hour=float(args[0]))
            await msg.reply(embed=_ok(f'Ustawiono **{float(args[0]):.1f} pkt/h**.'), mention_author=False)
        except ValueError:
            await msg.reply(embed=_err('Nieprawidłowa wartość.'), mention_author=False)

    async def _cmd_adminrole(self, msg, args):
        if not args:
            await msg.reply(embed=_err('`.adminrole @rola`'), mention_author=False); return
        rid = args[0].strip('<@&>').strip()
        try:
            rid = int(rid)
        except ValueError:
            await msg.reply(embed=_err('Nieprawidłowa rola.'), mention_author=False); return
        role = msg.guild.get_role(rid)
        if not role:
            await msg.reply(embed=_err('Rola nie istnieje.'), mention_author=False); return
        cfg = db.get_guild(msg.guild.id) or {}
        ids = json.loads(cfg.get('admin_role_ids') or '[]')
        if rid not in ids:
            ids.append(rid)
        db.update_guild(msg.guild.id, admin_role_ids=json.dumps(ids))
        await msg.reply(embed=_ok(f'Dodano {role.mention} jako rolę admina bota.'), mention_author=False)

    async def _cmd_removeadminrole(self, msg, args):
        if not args:
            await msg.reply(embed=_err('`.removeadminrole @rola`'), mention_author=False); return
        rid = args[0].strip('<@&>').strip()
        try:
            rid = int(rid)
        except ValueError:
            await msg.reply(embed=_err('Nieprawidłowa rola.'), mention_author=False); return
        cfg = db.get_guild(msg.guild.id) or {}
        ids = [i for i in json.loads(cfg.get('admin_role_ids') or '[]') if i != rid]
        db.update_guild(msg.guild.id, admin_role_ids=json.dumps(ids))
        await msg.reply(embed=_ok('Usunięto rolę z listy adminów.'), mention_author=False)

    def _role_cmd(self, key: str):
        """Helper: return (add_fn, remove_fn) for a given config key."""
        async def _add(msg, args):
            if not await self._check_admin(msg): return
            if not args:
                await msg.reply(embed=_err(f'`.{key}role @rola`'), mention_author=False); return
            rid = args[0].strip('<@&>').strip()
            try: rid = int(rid)
            except ValueError:
                await msg.reply(embed=_err('Nieprawidłowa rola.'), mention_author=False); return
            role = msg.guild.get_role(rid)
            if not role:
                await msg.reply(embed=_err('Rola nie istnieje.'), mention_author=False); return
            cfg = db.get_guild(msg.guild.id) or {}
            ids = json.loads(cfg.get(f'{key}_role_ids') or '[]')
            if rid not in ids: ids.append(rid)
            db.update_guild(msg.guild.id, **{f'{key}_role_ids': json.dumps(ids)})
            tier_names = {'mod': 'Moderator', 'officer': 'Oficer', 'admin': 'Admin'}
            await msg.reply(embed=_ok(f'Dodano {role.mention} do grupy **{tier_names.get(key, key)}**.'),
                            mention_author=False)
        async def _remove(msg, args):
            if not await self._check_admin(msg): return
            if not args:
                await msg.reply(embed=_err(f'`.remove{key}role @rola`'), mention_author=False); return
            rid = args[0].strip('<@&>').strip()
            try: rid = int(rid)
            except ValueError:
                await msg.reply(embed=_err('Nieprawidłowa rola.'), mention_author=False); return
            cfg = db.get_guild(msg.guild.id) or {}
            ids = [i for i in json.loads(cfg.get(f'{key}_role_ids') or '[]') if i != rid]
            db.update_guild(msg.guild.id, **{f'{key}_role_ids': json.dumps(ids)})
            await msg.reply(embed=_ok(f'Usunięto rolę z grupy **{key}**.'), mention_author=False)
        return _add, _remove

    async def _cmd_officerole(self, msg, args):
        fn, _ = self._role_cmd('officer')
        await fn(msg, args)

    async def _cmd_removeofficerole(self, msg, args):
        _, fn = self._role_cmd('officer')
        await fn(msg, args)

    async def _cmd_modrole(self, msg, args):
        fn, _ = self._role_cmd('mod')
        await fn(msg, args)

    async def _cmd_removemodrole(self, msg, args):
        _, fn = self._role_cmd('mod')
        await fn(msg, args)

    async def _cmd_perminfo(self, msg, args):
        """Show current permission tier configuration."""
        if not await self._check_admin(msg): return
        cfg = db.get_guild(msg.guild.id) or {}
        e = discord.Embed(title='🔐 Poziomy uprawnień', color=0x7289DA)
        def fmt_roles(key):
            try:
                ids = json.loads(cfg.get(key) or '[]')
            except Exception:
                ids = []
            if not ids:
                return '*Brak — ustaw komendą*'
            roles = [msg.guild.get_role(rid) for rid in ids]
            return ' '.join(r.mention for r in roles if r) or '*nieznane role*'
        e.add_field(name='👑 Admin (`.adminrole`)',
            value=fmt_roles('admin_role_ids') + '\n*Generał, Książę, Król*\n'
                  '`setpoints` `resetuser` `createrank` `config` `events`...', inline=False)
        e.add_field(name='⚔️ Oficer (`.officerole`)',
            value=fmt_roles('officer_role_ids') + '\n*Kapitan*\n'
                  '`ban` `addpoints` `giverank` `announce` `purge`...', inline=False)
        e.add_field(name='🛡️ Moderator (`.modrole`)',
            value=fmt_roles('mod_role_ids') + '\n*Military Police, Squad Leader+*\n'
                  '`warn` `mute` `kick` `note` `lock` `nick`...', inline=False)
        e.set_footer(text='Każdy wyższy poziom ma też dostęp do komend niższego.')
        await msg.reply(embed=e, mention_author=False)

    async def _cmd_setowner(self, msg, args):
        """Set the guild 'owner/commander' who can grant UNIT ranks."""
        if not msg.author.guild_permissions.administrator:
            await msg.reply(embed=_err('Tylko administrator Discord może ustawić właściciela.'),
                            mention_author=False); return
        if not args:
            await msg.reply(embed=_err('`.setowner @user`'), mention_author=False); return
        m = self._resolve_member(msg, args[0])
        if not m:
            await msg.reply(embed=_err('Nie znaleziono.'), mention_author=False); return
        db.update_guild(msg.guild.id, owner_id=m.id)
        await msg.reply(embed=_ok(f'Ustawiono **{m.display_name}** jako właściciela/dowódcę '
                                   f'(może nadawać rangi UNIT).'), mention_author=False)

    async def _cmd_setwarnlimit(self, msg, args):
        if not args:
            await msg.reply(embed=_err('`.setwarnlimit <n>`'), mention_author=False); return
        try:
            n = int(args[0])
            db.update_guild(msg.guild.id, warn_limit=n)
            await msg.reply(embed=_ok(f'Limit ostrzeżeń: **{n}**. Po tym auto-ban z rankingu.'),
                            mention_author=False)
        except ValueError:
            await msg.reply(embed=_err('Podaj liczbę całkowitą.'), mention_author=False)

    async def _cmd_setmaxhours(self, msg, args):
        if not args:
            await msg.reply(embed=_err('`.setmaxhours <h>`'), mention_author=False); return
        try:
            n = int(args[0])
            db.update_guild(msg.guild.id, auto_clockout_hours=n)
            await msg.reply(embed=_ok(f'Anti-cheat limit: **{n}h** zalogowania bez wylogowania.'),
                            mention_author=False)
        except ValueError:
            await msg.reply(embed=_err('Podaj liczbę godzin.'), mention_author=False)


    # ── Factions ──────────────────────────────────────────────────────────────

    async def _cmd_createfaction(self, msg, args):
        """
        .createfaction <nazwa> [ikona] [#kolor] [opis]
        """
        if not args:
            await msg.reply(embed=_err(
                '`.createfaction <nazwa> [ikona] [#kolor] [opis]`\n'
                'Przykład: `.createfaction MR ⚔️ #ff5555 Frakcja MR`'
            ), mention_author=False); return

        name  = args[0]
        icon  = args[1] if len(args) > 1 else '⚔️'
        color = '#7289da'
        desc  = ''
        rest  = args[2:]
        if rest and rest[0].startswith('#'):
            color = rest[0]
            desc  = ' '.join(rest[1:])
        elif rest:
            desc = ' '.join(rest)

        if db.get_faction_by_name(msg.guild.id, name):
            await msg.reply(embed=_err(f'Frakcja **{name}** już istnieje.'), mention_author=False); return

        f = db.create_faction(msg.guild.id, name, icon=icon, color=color, description=desc)
        if not f:
            await msg.reply(embed=_err('Błąd tworzenia frakcji.'), mention_author=False); return
        e = _ok(f'Utworzono frakcję **{icon} {name}**')
        if desc:
            e.add_field(name='Opis', value=desc)
        e.add_field(name='Kolor', value=color)
        e.set_footer(text='Dodaj role: .addfactionrole <frakcja> @rola')
        await msg.reply(embed=e, mention_author=False)

    async def _cmd_deletefaction(self, msg, args):
        if not args:
            await msg.reply(embed=_err('`.deletefaction <nazwa>`'), mention_author=False); return
        f = db.get_faction_by_name(msg.guild.id, ' '.join(args))
        if not f:
            await msg.reply(embed=_err('Nie znaleziono frakcji.'), mention_author=False); return
        db.delete_faction(f['id'])
        await msg.reply(embed=_ok(f'Usunięto frakcję **{f["icon"]} {f["name"]}**.'),
                        mention_author=False)

    async def _cmd_editfaction(self, msg, args):
        """
        .editfaction <nazwa> <pole> <wartość>
        Pola: name, icon, color, description
        """
        if len(args) < 3:
            await msg.reply(embed=_err(
                '`.editfaction <nazwa> <pole> <wartość>`\n'
                'Pola: `name`, `icon`, `color`, `description`'
            ), mention_author=False); return
        f = db.get_faction_by_name(msg.guild.id, args[0])
        if not f:
            await msg.reply(embed=_err('Nie znaleziono frakcji.'), mention_author=False); return
        field = args[1].lower()
        value = ' '.join(args[2:])
        allowed = {'name', 'icon', 'color', 'description'}
        if field not in allowed:
            await msg.reply(embed=_err(f'Pole: {", ".join(f"`{a}`" for a in allowed)}'),
                            mention_author=False); return
        db.update_faction(f['id'], **{field: value})
        await msg.reply(embed=_ok(f'Zaktualizowano **{f["name"]}**: `{field}` = `{value}`'),
                        mention_author=False)

    async def _cmd_addfactionrole(self, msg, args):
        """
        .addfactionrole <nazwa frakcji> @rola
        """
        if len(args) < 2:
            await msg.reply(embed=_err('`.addfactionrole <frakcja> @rola`'), mention_author=False); return
        f = db.get_faction_by_name(msg.guild.id, args[0])
        if not f:
            await msg.reply(embed=_err('Nie znaleziono frakcji.'), mention_author=False); return
        rid = args[1].strip('<@&>').strip()
        try:
            rid = int(rid)
        except ValueError:
            await msg.reply(embed=_err('Nieprawidłowa rola.'), mention_author=False); return
        role = msg.guild.get_role(rid)
        if not role:
            await msg.reply(embed=_err('Rola nie istnieje.'), mention_author=False); return
        ids = json.loads(f['role_ids'] or '[]')
        if rid not in ids:
            ids.append(rid)
        db.update_faction(f['id'], role_ids=ids)
        await msg.reply(embed=_ok(f'Dodano {role.mention} do frakcji **{f["icon"]} {f["name"]}**.'),
                        mention_author=False)

    async def _cmd_removefactionrole(self, msg, args):
        """
        .removefactionrole <nazwa frakcji> @rola
        """
        if len(args) < 2:
            await msg.reply(embed=_err('`.removefactionrole <frakcja> @rola`'), mention_author=False); return
        f = db.get_faction_by_name(msg.guild.id, args[0])
        if not f:
            await msg.reply(embed=_err('Nie znaleziono frakcji.'), mention_author=False); return
        rid = args[1].strip('<@&>').strip()
        try:
            rid = int(rid)
        except ValueError:
            await msg.reply(embed=_err('Nieprawidłowa rola.'), mention_author=False); return
        ids = [i for i in json.loads(f['role_ids'] or '[]') if i != rid]
        db.update_faction(f['id'], role_ids=ids)
        await msg.reply(embed=_ok(f'Usunięto rolę z frakcji **{f["icon"]} {f["name"]}**.'),
                        mention_author=False)

    async def _cmd_factions(self, msg, args):
        factions = db.get_factions(msg.guild.id)
        if not factions:
            await msg.reply(embed=_warn('Brak frakcji. Użyj `.createfaction`.'),
                            mention_author=False); return
        e = discord.Embed(title='⚔️ Frakcje', color=BLURPLE)
        for f in factions:
            members = db.get_faction_members(msg.guild.id, f['id'])
            val = f'👥 Członków: **{len(members)}**'
            if members:
                top = members[:5]
                names = []
                for mem in top:
                    member = msg.guild.get_member(mem['user_id'])
                    nm = member.display_name if member else mem.get('display_name', str(mem['user_id']))
                    names.append(f'{nm} ({mem["points"]:.0f} pkt)')
                val += '\n' + ', '.join(names)
                if len(members) > 5:
                    val += f' *…+{len(members)-5}*'
            if f.get('description'):
                val += f'\n*{f["description"]}*'
            e.add_field(name=f'{f["icon"]} {f["name"]}', value=val, inline=False)
        e.set_footer(text='Przypisz: .assignfaction @user <frakcja> | Usuń: .removefaction @user')
        await msg.reply(embed=e, mention_author=False)

    async def _cmd_assignfaction(self, msg, args):
        """
        .assignfaction @user <nazwa frakcji>
        Przypisuje użytkownika do frakcji (jeden użytkownik = jedna frakcja).
        """
        if len(args) < 2:
            await msg.reply(embed=_err('`.assignfaction @user <nazwa frakcji>`'),
                            mention_author=False); return
        m = self._resolve_member(msg, args[0])
        if not m:
            await msg.reply(embed=_err('Nie znaleziono użytkownika.'), mention_author=False); return
        faction_name = ' '.join(args[1:])
        f = db.get_faction_by_name(msg.guild.id, faction_name)
        if not f:
            await msg.reply(embed=_err(f'Frakcja **{faction_name}** nie istnieje. Użyj `.factions`.'),
                            mention_author=False); return
        db.ensure_user(m.id, msg.guild.id, str(m), m.display_name)
        ok = db.assign_faction_member(m.id, msg.guild.id, f['id'],
                                      assigned_by=msg.author.id)
        if not ok:
            await msg.reply(embed=_err('Błąd przypisania do frakcji.'), mention_author=False); return

        # Add faction marker roles + base Rekrut role to Discord member
        role_added = []
        try:
            fac_role_ids = json.loads(f.get('role_ids') or '[]')
            for rid in fac_role_ids:
                role = msg.guild.get_role(int(rid))
                if role:
                    await m.add_roles(role, reason=f'Frakcja: {f["name"]}')
                    role_added.append(role.mention)
        except Exception:
            pass
        # Add Rekrut (lowest faction rank) Discord role
        try:
            all_ranks = db.get_ranks(msg.guild.id)
            faction_ranks = sorted(
                [r for r in all_ranks if r.get('faction_id') == f['id']
                 and not r.get('is_special') and not r.get('is_owner_only')],
                key=lambda r: r.get('required_points', 0)
            )
            if faction_ranks and faction_ranks[0].get('role_id'):
                base_role = msg.guild.get_role(faction_ranks[0]['role_id'])
                if base_role and base_role not in m.roles:
                    await m.add_roles(base_role, reason=f'Wstęp do frakcji: {f["name"]}')
                    role_added.append(base_role.mention)
        except Exception:
            pass

        e = _ok(f'Przypisano **{m.display_name}** do frakcji **{f["icon"]} {f["name"]}**.')
        if role_added:
            e.add_field(name='🎭 Role Discord dodane', value=' '.join(role_added) or '—')
        e.set_footer(text=f'Przez: {msg.author.display_name}')
        await msg.reply(embed=e, mention_author=False)
        db.log_action(msg.guild.id, 'faction_assign',
                      user_id=m.id, actor_id=msg.author.id,
                      details={'faction': f['name'], 'faction_id': f['id']})
        await send_log(msg.guild, log_embed('⚔️ Frakcja Przypisana', BLURPLE,
            Użytkownik=m.mention,
            Frakcja=f'{f["icon"]} {f["name"]}',
            Przez=msg.author.mention))

    async def _cmd_removefaction(self, msg, args):
        """
        .removefaction @user
        Usuwa użytkownika z jego frakcji i usuwa powiązane role Discord.
        """
        if not args:
            await msg.reply(embed=_err('`.removefaction @user`'), mention_author=False); return
        m = self._resolve_member(msg, args[0])
        if not m:
            await msg.reply(embed=_err('Nie znaleziono użytkownika.'), mention_author=False); return
        # Get current faction before removing
        fm = db.get_user_faction_membership(m.id, msg.guild.id)
        if not fm:
            await msg.reply(embed=_warn(f'**{m.display_name}** nie jest w żadnej frakcji.'),
                            mention_author=False); return
        ok = db.remove_faction_member(m.id, msg.guild.id)
        if not ok:
            await msg.reply(embed=_err('Błąd usuwania z frakcji.'), mention_author=False); return

        # Remove faction marker roles + all faction rank roles from Discord
        roles_removed = []
        try:
            faction = db.get_faction_by_id(fm['faction_id'])
            if faction:
                fac_role_ids = json.loads(faction.get('role_ids') or '[]')
                for rid in fac_role_ids:
                    role = msg.guild.get_role(int(rid))
                    if role and role in m.roles:
                        await m.remove_roles(role, reason=f'Usunięto z frakcji: {fm["faction_name"]}')
                        roles_removed.append(role.mention)
        except Exception:
            pass
        try:
            all_ranks = db.get_ranks(msg.guild.id)
            for r in all_ranks:
                if r.get('faction_id') == fm['faction_id'] and r.get('role_id'):
                    role = msg.guild.get_role(r['role_id'])
                    if role and role in m.roles:
                        await m.remove_roles(role, reason='Usunięto z frakcji')
                        roles_removed.append(role.mention)
        except Exception:
            pass

        e = _ok(f'Usunięto **{m.display_name}** z frakcji **{fm["faction_icon"]} {fm["faction_name"]}**.')
        if roles_removed:
            e.add_field(name='🗑️ Role Discord usunięte',
                        value=' '.join(dict.fromkeys(roles_removed)) or '—')
        await msg.reply(embed=e, mention_author=False)
        db.log_action(msg.guild.id, 'faction_remove',
                      user_id=m.id, actor_id=msg.author.id,
                      details={'faction': fm['faction_name']})
        await send_log(msg.guild, log_embed('⚔️ Frakcja Usunięta', ORANGE,
            Użytkownik=m.mention,
            **{'Była frakcja': f'{fm["faction_icon"]} {fm["faction_name"]}'},
            Przez=msg.author.mention))


    # ── Jobs ──────────────────────────────────────────────────────────────────

    async def _cmd_createjob(self, msg, args):
        """
        .createjob <nazwa> <punkty> [ikona] [#kolor] [opis]
        Tworzy nową pracę dostępną dla cywilów po osiągnięciu progu punktowego.
        """
        if len(args) < 2:
            await msg.reply(embed=_err(
                '`.createjob <nazwa> <punkty> [ikona] [#kolor] [opis]`\n'
                'Przykład: `.createjob Farmer 5 🌾 #55aa55 Praca na farmie`'
            ), mention_author=False); return

        name = args[0]
        try:
            req_pts = float(args[1])
        except ValueError:
            await msg.reply(embed=_err('Punkty muszą być liczbą.'), mention_author=False); return

        remaining = args[2:]
        icon  = remaining[0] if remaining else '💼'
        color = '#7289da'
        desc  = ''
        rest  = remaining[1:] if remaining else []
        if rest:
            if rest[0].startswith('#'):
                color = rest[0]
                desc = ' '.join(rest[1:])
            else:
                desc = ' '.join(rest)

        if db.get_job_by_name(msg.guild.id, name):
            await msg.reply(embed=_err(f'Praca **{name}** już istnieje.'),
                            mention_author=False); return
        job = db.create_job(msg.guild.id, name, req_pts,
                            icon=icon, color=color, description=desc)
        if not job:
            await msg.reply(embed=_err('Błąd tworzenia pracy.'), mention_author=False); return
        e = _ok(f'Utworzono pracę **{icon} {name}** – `{req_pts:.0f} pkt`')
        if desc:
            e.add_field(name='Opis', value=desc)
        e.set_footer(text='Aby przypiąć rolę Discord: .editjob <nazwa> role <@rola>')
        await msg.reply(embed=e, mention_author=False)

    async def _cmd_deletejob(self, msg, args):
        if not args:
            await msg.reply(embed=_err('`.deletejob <nazwa>`'), mention_author=False); return
        job = db.get_job_by_name(msg.guild.id, ' '.join(args))
        if not job:
            await msg.reply(embed=_err('Nie znaleziono pracy.'), mention_author=False); return
        db.delete_job(job['id'])
        await msg.reply(embed=_ok(f'Usunięto pracę **{job["icon"]} {job["name"]}**.'),
                        mention_author=False)

    async def _cmd_editjob(self, msg, args):
        """
        .editjob <nazwa> <pole> <wartość>
        Pola: name, points, icon, color, description, role
        role = @rola lub NONE
        """
        if len(args) < 3:
            await msg.reply(embed=_err(
                '`.editjob <nazwa> <pole> <wartość>`\n'
                'Pola: `name`, `points`, `icon`, `color`, `description`, `role`\n'
                '`role NONE` = usuń rolę Discord'
            ), mention_author=False); return
        job = db.get_job_by_name(msg.guild.id, args[0])
        if not job:
            await msg.reply(embed=_err('Nie znaleziono pracy.'), mention_author=False); return
        field = args[1].lower()
        value = ' '.join(args[2:])

        if field == 'role':
            if value.upper() == 'NONE':
                db.update_job(job['id'], role_id=None)
                await msg.reply(embed=_ok(f'Usunięto rolę Discord z pracy **{job["name"]}**.'),
                                mention_author=False)
            else:
                rid = value.strip('<@&>').strip()
                try:
                    rid = int(rid)
                except ValueError:
                    await msg.reply(embed=_err('Nieprawidłowa rola.'), mention_author=False); return
                role = msg.guild.get_role(rid)
                if not role:
                    await msg.reply(embed=_err('Rola nie istnieje.'), mention_author=False); return
                db.update_job(job['id'], role_id=rid)
                await msg.reply(embed=_ok(f'Przypisano {role.mention} do pracy **{job["name"]}**.'),
                                mention_author=False)
            return

        fields_map = {
            'name':        ('name',            lambda v: v),
            'points':      ('required_points', float),
            'icon':        ('icon',            lambda v: v),
            'color':       ('color',           lambda v: v),
            'description': ('description',     lambda v: v),
        }
        if field not in fields_map:
            await msg.reply(embed=_err('Pole: `name`, `points`, `icon`, `color`, `description`, `role`'),
                            mention_author=False); return
        col, converter = fields_map[field]
        try:
            db.update_job(job['id'], **{col: converter(value)})
        except ValueError:
            await msg.reply(embed=_err('Nieprawidłowa wartość.'), mention_author=False); return
        await msg.reply(embed=_ok(f'Zaktualizowano **{job["name"]}**: `{field}` = `{value}`'),
                        mention_author=False)

    async def _cmd_jobs(self, msg, args):
        gid   = msg.guild.id
        jobs  = db.get_jobs(gid)
        if not jobs:
            await msg.reply(embed=_warn('Brak prac. Użyj `.createjob`.'),
                            mention_author=False); return
        e = discord.Embed(title='💼 Lista Prac', color=BLURPLE)
        for j in jobs:
            members = db.get_job_members(gid, j['id'])
            role_str = ''
            if j.get('role_id'):
                role = msg.guild.get_role(j['role_id'])
                role_str = f' | {role.mention}' if role else ' | *(rola usunięta)*'
            val = (f'`{j["required_points"]:.0f} pkt` | 👥 {len(members)}{role_str}')
            if j.get('description'):
                val += f'\n*{j["description"]}*'
            e.add_field(name=f'{j["icon"]} {j["name"]}', value=val, inline=True)
        e.set_footer(text='Nadaj ręcznie: .givejob @user <praca> | Odbierz: .takejob @user <praca>')
        await msg.reply(embed=e, mention_author=False)

    async def _cmd_givejob(self, msg, args):
        """
        .givejob @user <nazwa pracy>
        Przydziela pracę (bypass: działa dla wszystkich, nie tylko cywilów).
        """
        if len(args) < 2:
            await msg.reply(embed=_err('`.givejob @user <nazwa pracy>`'),
                            mention_author=False); return
        m = self._resolve_member(msg, args[0])
        if not m:
            await msg.reply(embed=_err('Nie znaleziono użytkownika.'), mention_author=False); return
        job_name = ' '.join(args[1:])
        job = db.get_job_by_name(msg.guild.id, job_name)
        if not job:
            await msg.reply(embed=_err(f'Praca **{job_name}** nie istnieje.'),
                            mention_author=False); return
        db.ensure_user(m.id, msg.guild.id, str(m), m.display_name)
        ok = db.select_job(m.id, msg.guild.id, job['id'],
                           admin_granted=True, granted_by=msg.author.id)
        if not ok:
            await msg.reply(embed=_warn(f'**{m.display_name}** już ma pracę **{job["name"]}**.'),
                            mention_author=False); return
        # Assign role if configured
        if job.get('role_id'):
            role = msg.guild.get_role(job['role_id'])
            if role:
                try:
                    await m.add_roles(role, reason=f'Admin nadał pracę: {job["name"]}')
                except discord.Forbidden:
                    pass
        e = _ok(f'Przydzielono pracę **{job["icon"]} {job["name"]}** → **{m.display_name}**.')
        e.set_footer(text=f'Przez: {msg.author.display_name}')
        await msg.reply(embed=e, mention_author=False)
        db.log_action(msg.guild.id, 'job_give', user_id=m.id, actor_id=msg.author.id,
                      details={'job': job['name'], 'job_id': job['id']})
        await send_log(msg.guild, log_embed('💼 Praca Przydzielona', GREEN,
            Użytkownik=m.mention, Praca=f'{job["icon"]} {job["name"]}',
            Przez=msg.author.mention))

    async def _cmd_takejob(self, msg, args):
        """
        .takejob @user <nazwa pracy>
        Odbiera pracę użytkownikowi.
        """
        if len(args) < 2:
            await msg.reply(embed=_err('`.takejob @user <nazwa pracy>`'),
                            mention_author=False); return
        m = self._resolve_member(msg, args[0])
        if not m:
            await msg.reply(embed=_err('Nie znaleziono użytkownika.'), mention_author=False); return
        job_name = ' '.join(args[1:])
        job = db.get_job_by_name(msg.guild.id, job_name)
        if not job:
            await msg.reply(embed=_err(f'Praca **{job_name}** nie istnieje.'),
                            mention_author=False); return
        ok = db.deselect_job(m.id, msg.guild.id, job['id'])
        if not ok:
            await msg.reply(embed=_warn(f'**{m.display_name}** nie ma pracy **{job["name"]}**.'),
                            mention_author=False); return
        # Remove role if configured
        if job.get('role_id'):
            role = msg.guild.get_role(job['role_id'])
            if role:
                try:
                    await m.remove_roles(role, reason=f'Admin odebrał pracę: {job["name"]}')
                except discord.Forbidden:
                    pass
        e = _ok(f'Odebrano pracę **{job["icon"]} {job["name"]}** od **{m.display_name}**.')
        await msg.reply(embed=e, mention_author=False)
        db.log_action(msg.guild.id, 'job_take', user_id=m.id, actor_id=msg.author.id,
                      details={'job': job['name']})
        await send_log(msg.guild, log_embed('💼 Praca Odebrana', ORANGE,
            Użytkownik=m.mention, Praca=f'{job["icon"]} {job["name"]}',
            Przez=msg.author.mention))

    async def _cmd_setjobchannel(self, msg, args):
        """
        .setjobchannel #kanał
        Ustawia kanał dla panelu wyboru pracy.
        """
        if not args:
            await msg.reply(embed=_err('`.setjobchannel #kanał`'), mention_author=False); return
        cid = args[0].strip('<#>').strip()
        try:
            cid = int(cid)
        except ValueError:
            await msg.reply(embed=_err('Nieprawidłowy kanał.'), mention_author=False); return
        ch = msg.guild.get_channel(cid)
        if not ch:
            await msg.reply(embed=_err('Kanał nie istnieje.'), mention_author=False); return
        db.update_guild(msg.guild.id, job_channel_id=cid)
        await msg.reply(embed=_ok(f'Kanał prac ustawiony na {ch.mention}.\n'
                                  f'Użyj `.jobpanel` aby wysłać/odświeżyć panel.'),
                        mention_author=False)

    async def _cmd_jobpanel(self, msg, args):
        """
        .jobpanel
        Wysyła lub odświeża embed panelu pracy na skonfigurowanym kanale.
        """
        from cogs.jobs import _build_job_embed, JobPanelView
        cfg = db.get_guild(msg.guild.id) or {}
        ch_id = cfg.get('job_channel_id')
        if not ch_id:
            await msg.reply(embed=_err('Kanał prac nie jest ustawiony. Użyj `.setjobchannel #kanał`.'),
                            mention_author=False); return
        ch = msg.guild.get_channel(ch_id)
        if not ch:
            await msg.reply(embed=_err('Skonfigurowany kanał prac nie istnieje.'),
                            mention_author=False); return

        embed = _build_job_embed(msg.guild.id, msg.guild.name)
        view  = JobPanelView()

        # Try to edit existing panel
        panel = db.get_panel_embed(msg.guild.id, 'jobs')
        if panel:
            try:
                old_ch = msg.guild.get_channel(panel['channel_id'])
                if old_ch:
                    old_msg = await old_ch.fetch_message(panel['message_id'])
                    await old_msg.edit(embed=embed, view=view)
                    await msg.reply(embed=_ok(f'Panel pracy zaktualizowany w {ch.mention}.'),
                                    mention_author=False)
                    return
            except Exception:
                pass  # Message gone – send new one

        new_msg = await ch.send(embed=embed, view=view)
        db.save_panel_embed(msg.guild.id, ch.id, new_msg.id, 'jobs')
        await msg.reply(embed=_ok(f'Panel pracy wysłany w {ch.mention}.'),
                        mention_author=False)

    # ── Discord member join: assign Cywil role ────────────────────────────────

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """Automatically assign the 'Cywil' Discord role when a new member joins."""
        gid = member.guild.id
        db.ensure_guild(gid)
        db.ensure_user(member.id, gid, str(member), member.display_name)

        # Find the Cywil rank's Discord role
        all_ranks = db.get_ranks(gid)
        cywil_rank = next(
            (r for r in all_ranks
             if r['name'].lower() == 'cywil' and r.get('role_id')),
            None
        )
        if cywil_rank:
            role = member.guild.get_role(cywil_rank['role_id'])
            if role:
                try:
                    await member.add_roles(role, reason='Nowy członek – automatyczny Cywil')
                except discord.Forbidden:
                    pass
        db.log_action(gid, 'member_join', user_id=member.id,
                      details={'action': 'auto_cywil'})
        await send_log(member.guild, log_embed('👋 Nowy Członek', GREEN,
            Użytkownik=member.mention,
            **{'Rola auto': 'Cywil' if cywil_rank else '—'}))

    # ── Discord → DB role sync ─────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        """Pełna synchronizacja Discord rola → DB (rangi specjalne + drzewko + frakcje)."""
        if before.roles == after.roles:
            return

        gid = after.guild.id
        uid = after.id
        db.ensure_user(uid, gid)

        added   = [r for r in after.roles if r not in before.roles]
        removed = [r for r in before.roles if r not in after.roles]

        # Zbuduj mapę: discord_role_id → [lista rang] (WSZYSTKIE rangi, nie tylko specjalne)
        all_ranks    = db.get_ranks(gid)
        role_to_ranks: dict[int, list] = {}
        for r in all_ranks:
            if r.get('role_id'):
                role_to_ranks.setdefault(r['role_id'], []).append(r)

        # Zbuduj mapę: discord_role_id → faction
        factions        = db.get_factions(gid)
        role_to_faction = {}
        for f in factions:
            try:
                for rid in json.loads(f.get('role_ids') or '[]'):
                    role_to_faction[int(rid)] = f
            except Exception:
                pass

        # ── Rola dodana ───────────────────────────────────────────────────────
        for role in added:
            for rank in role_to_ranks.get(role.id, []):
                if rank.get('is_special') or rank.get('is_owner_only'):
                    # ── Ranga specjalna / admin: nadaj bezpośrednio ──────────
                    db.give_special_rank(uid, gid, rank['id'],
                                         assigned_by=0, note='Auto-sync z Discord')
                    db.log_action(gid, 'role_sync', user_id=uid,
                                  details={'action': 'rank_added',
                                           'rank': rank['name'], 'role': role.name})
                else:
                    # ── Ranga drzewka: ustaw punkty na minimum tej rangi ─────
                    # Uwzględnia frakcję: weź rangę pasującą do frakcji usera
                    user_fac = db.get_user_faction_membership(uid, gid)
                    fac_id   = user_fac.get('id') if user_fac else None
                    if rank.get('faction_id') not in (None, fac_id):
                        continue   # ranga innej frakcji – pomiń
                    req_pts = rank.get('required_points', 0)
                    if req_pts > 0:
                        user = db.get_user(uid, gid)
                        if user and (user.get('points') or 0) < req_pts:
                            db.set_points(uid, gid, req_pts,
                                          note=f'Auto-sync roli Discord: {role.name}',
                                          assigned_by=0)
                        db.log_action(gid, 'role_sync', user_id=uid,
                                      details={'action': 'auto_rank_role_added',
                                               'rank': rank['name'],
                                               'pts_set': req_pts, 'role': role.name})

            # Rola frakcji (Alpha-1, Nu-7) → przypisz do frakcji w DB
            faction = role_to_faction.get(role.id)
            if faction:
                db.assign_faction_member(uid, gid, faction['id'], assigned_by=0)
                db.log_action(gid, 'role_sync', user_id=uid,
                              details={'action': 'faction_added',
                                       'faction': faction['name'], 'role': role.name})

        # ── Rola usunięta ─────────────────────────────────────────────────────
        for role in removed:
            for rank in role_to_ranks.get(role.id, []):
                if rank.get('is_special') or rank.get('is_owner_only'):
                    # ── Ranga specjalna: usuń ────────────────────────────────
                    db.remove_special_rank(uid, gid, rank['id'])
                    db.log_action(gid, 'role_sync', user_id=uid,
                                  details={'action': 'rank_removed',
                                           'rank': rank['name'], 'role': role.name})
                else:
                    # ── Ranga drzewka: obniż punkty do progu poprzedniej rangi
                    user_fac = db.get_user_faction_membership(uid, gid)
                    fac_id   = user_fac.get('id') if user_fac else None
                    if rank.get('faction_id') not in (None, fac_id):
                        continue
                    req_pts = rank.get('required_points', 0)
                    if req_pts > 0:
                        user = db.get_user(uid, gid)
                        cur  = user.get('points', 0) if user else 0
                        # Tylko obniż jeśli aktualny wynik to właśnie ta ranga
                        if cur >= req_pts:
                            new_pts = max(req_pts - 1, 0)
                            db.set_points(uid, gid, new_pts,
                                          note=f'Auto-sync roli Discord (usunięto): {role.name}',
                                          assigned_by=0)
                        db.log_action(gid, 'role_sync', user_id=uid,
                                      details={'action': 'auto_rank_role_removed',
                                               'rank': rank['name'], 'role': role.name})

            # Usunięcie roli frakcji → usuń z frakcji w DB
            faction = role_to_faction.get(role.id)
            if faction:
                current = db.get_user_faction_membership(uid, gid)
                if current and current.get('id') == faction['id']:
                    db.remove_faction_member(uid, gid)
                    db.log_action(gid, 'role_sync', user_id=uid,
                                  details={'action': 'faction_removed',
                                           'faction': faction['name']})


    # ── Warn Points ───────────────────────────────────────────────────────────

    async def _cmd_warnpoints(self, msg, args):
        if not args:
            await msg.reply(embed=_err('`.warnpoints @user [powód]`'), mention_author=False); return
        m = self._resolve_member(msg, args[0])
        if not m:
            await msg.reply(embed=_err('Nie znaleziono użytkownika.'), mention_author=False); return
        reason = ' '.join(args[1:]) if len(args) > 1 else 'Brak powodu'
        db.ensure_user(m.id, msg.guild.id, str(m), m.display_name)
        total = db.add_warn_points(m.id, msg.guild.id, 1.0, reason=reason, given_by=msg.author.id)
        e = _ok(f'Dodano WarnPoint **{m.display_name}** (łącznie: **{total:.1f}** WP)')
        e.add_field(name='📝 Powód', value=reason)
        e.set_footer(text='WarnPoints nie liczą się do limitu warnów — tylko do leaderboarda')
        await msg.reply(embed=e, mention_author=False)
        await send_log(msg.guild, log_embed('📊 WarnPoint', YELLOW,
            Użytkownik=m.mention, Powód=reason,
            **{'Łącznie WP': f'{total:.1f}'}, Przez=msg.author.mention))

    async def _cmd_clearwarnpoints(self, msg, args):
        if not args:
            await msg.reply(embed=_err('`.clearwarnpoints @user`'), mention_author=False); return
        m = self._resolve_member(msg, args[0])
        if not m:
            await msg.reply(embed=_err('Nie znaleziono użytkownika.'), mention_author=False); return
        db.clear_warn_points(m.id, msg.guild.id)
        await msg.reply(embed=_ok(f'Wyczyszczono WarnPoints dla **{m.display_name}**.'),
                        mention_author=False)

    async def _cmd_warnlb(self, msg, args):
        top = db.get_warn_points_leaderboard(msg.guild.id, limit=10)
        if not top:
            await msg.reply(embed=discord.Embed(description='📭 Nikt nie ma WarnPoints.',
                                                color=GREEN), mention_author=False); return
        e = discord.Embed(title='⚠️ Ranking WarnPoints', color=YELLOW, timestamp=datetime.now())
        lines = []
        for i, u in enumerate(top):
            member = msg.guild.get_member(u['user_id'])
            name = member.display_name if member else u.get('display_name') or str(u['user_id'])
            lines.append(f'`{i+1}.` **{name}** — {u["warn_points"]:.1f} WP')
        e.description = '\n'.join(lines)
        e.set_footer(text='Każdy .warn = +0.5 WP | Każdy .warnpoints = +1 WP')
        await msg.reply(embed=e, mention_author=False)

    # ── Moderation ────────────────────────────────────────────────────────────

    async def _cmd_mute(self, msg, args):
        """`.mute @user [czas] [powód]` — np. .mute @user 1h Spam"""
        if not args:
            await msg.reply(embed=_err('`.mute @user [czas] [powód]` — np. `.mute @user 30m spam`'),
                            mention_author=False); return
        m = self._resolve_member(msg, args[0])
        if not m:
            await msg.reply(embed=_err('Nie znaleziono użytkownika.'), mention_author=False); return
        duration = timedelta(minutes=10)  # default 10 min
        reason_start = 1
        if len(args) > 1:
            parsed = _parse_duration(args[1])
            if parsed:
                duration = parsed
                reason_start = 2
        reason = ' '.join(args[reason_start:]) if len(args) > reason_start else 'Brak powodu'
        max_td = timedelta(days=28)
        if duration > max_td:
            duration = max_td
        try:
            await m.timeout(duration, reason=reason)
        except discord.Forbidden:
            await msg.reply(embed=_err('Brak uprawnień do wyciszenia.'), mention_author=False); return
        mins = int(duration.total_seconds() / 60)
        time_str = f'{duration.days}d' if duration.days else (f'{mins//60}h {mins%60}m' if mins >= 60 else f'{mins}m')
        e = _ok(f'Wyciszono **{m.display_name}** na **{time_str}**')
        e.add_field(name='📝 Powód', value=reason)
        await msg.reply(embed=e, mention_author=False)
        await send_log(msg.guild, log_embed('🔇 Mute', YELLOW,
            Użytkownik=m.mention, Czas=time_str, Powód=reason, Przez=msg.author.mention))

    async def _cmd_unmute(self, msg, args):
        if not args:
            await msg.reply(embed=_err('`.unmute @user`'), mention_author=False); return
        m = self._resolve_member(msg, args[0])
        if not m:
            await msg.reply(embed=_err('Nie znaleziono użytkownika.'), mention_author=False); return
        try:
            await m.timeout(None)
        except discord.Forbidden:
            await msg.reply(embed=_err('Brak uprawnień.'), mention_author=False); return
        await msg.reply(embed=_ok(f'Unmute: **{m.display_name}**'), mention_author=False)
        await send_log(msg.guild, log_embed('🔊 Unmute', GREEN,
            Użytkownik=m.mention, Przez=msg.author.mention))

    async def _cmd_kick(self, msg, args):
        if not args:
            await msg.reply(embed=_err('`.kick @user [powód]`'), mention_author=False); return
        m = self._resolve_member(msg, args[0])
        if not m:
            await msg.reply(embed=_err('Nie znaleziono użytkownika.'), mention_author=False); return
        reason = ' '.join(args[1:]) if len(args) > 1 else 'Brak powodu'
        try:
            await m.kick(reason=reason)
        except discord.Forbidden:
            await msg.reply(embed=_err('Brak uprawnień do kicka.'), mention_author=False); return
        await msg.reply(embed=_ok(f'Wyrzucono **{m.display_name}** z serwera.'), mention_author=False)
        db.log_action(msg.guild.id, 'kick', user_id=m.id, actor_id=msg.author.id,
                      details={'reason': reason})
        await send_log(msg.guild, log_embed('👢 Kick', ORANGE,
            Użytkownik=m.mention, Powód=reason, Przez=msg.author.mention))

    async def _cmd_tempban(self, msg, args):
        """`.tempban @user <czas> [powód]`"""
        if len(args) < 2:
            await msg.reply(embed=_err('`.tempban @user <czas> [powód]` — np. `.tempban @user 7d nieodpowiednie zachowanie`'),
                            mention_author=False); return
        m = self._resolve_member(msg, args[0])
        if not m:
            await msg.reply(embed=_err('Nie znaleziono użytkownika.'), mention_author=False); return
        duration = _parse_duration(args[1])
        if not duration:
            await msg.reply(embed=_err('Nieprawidłowy czas. Przykład: `7d`, `24h`, `1d12h`'),
                            mention_author=False); return
        reason = ' '.join(args[2:]) if len(args) > 2 else 'Brak powodu'
        unban_at = (datetime.now() + duration).strftime('%d.%m.%Y %H:%M')
        try:
            await m.ban(reason=f'[TEMPBAN do {unban_at}] {reason}')
        except discord.Forbidden:
            await msg.reply(embed=_err('Brak uprawnień do bana.'), mention_author=False); return
        days = duration.days
        hrs = int(duration.total_seconds() / 3600)
        time_str = f'{days}d' if days else f'{hrs}h'
        e = _ok(f'Tymczasowo zbanowano **{m.display_name}** na **{time_str}**')
        e.add_field(name='📝 Powód', value=reason)
        e.add_field(name='📅 Odban', value=unban_at, inline=True)
        e.set_footer(text='Odban jest manualny — ustaw reminder lub użyj schedulera')
        await msg.reply(embed=e, mention_author=False)
        db.log_action(msg.guild.id, 'tempban', user_id=m.id, actor_id=msg.author.id,
                      details={'reason': reason, 'until': unban_at})
        await send_log(msg.guild, log_embed('⏳ Tempban', RED,
            Użytkownik=m.mention, Czas=time_str, Odban=unban_at,
            Powód=reason, Przez=msg.author.mention))

    async def _cmd_softban(self, msg, args):
        """Ban + natychmiastowy unban (usuwa wiadomości z ostatnich 7 dni)."""
        if not args:
            await msg.reply(embed=_err('`.softban @user [powód]`'), mention_author=False); return
        m = self._resolve_member(msg, args[0])
        if not m:
            await msg.reply(embed=_err('Nie znaleziono użytkownika.'), mention_author=False); return
        reason = ' '.join(args[1:]) if len(args) > 1 else 'Brak powodu'
        try:
            await m.ban(reason=f'[SOFTBAN] {reason}', delete_message_days=7)
            await msg.guild.unban(m, reason='Softban — automatyczny unban')
        except discord.Forbidden:
            await msg.reply(embed=_err('Brak uprawnień.'), mention_author=False); return
        e = _ok(f'Softban **{m.display_name}** — wyrzucono i usunięto wiadomości (7 dni).')
        e.add_field(name='📝 Powód', value=reason)
        await msg.reply(embed=e, mention_author=False)
        await send_log(msg.guild, log_embed('🧹 Softban', ORANGE,
            Użytkownik=m.mention, Powód=reason, Przez=msg.author.mention))

    async def _cmd_purge(self, msg, args):
        if not args or not args[0].isdigit():
            await msg.reply(embed=_err('`.purge <liczba>` — np. `.purge 10`'), mention_author=False); return
        n = min(int(args[0]), 100)
        try:
            deleted = await msg.channel.purge(limit=n + 1)  # +1 for the command msg
        except discord.Forbidden:
            await msg.reply(embed=_err('Brak uprawnień do usuwania wiadomości.'), mention_author=False); return
        e = _ok(f'Usunięto **{len(deleted)-1}** wiadomości.')
        confirm = await msg.channel.send(embed=e)
        import asyncio
        await asyncio.sleep(3)
        try:
            await confirm.delete()
        except Exception:
            pass

    async def _cmd_slowmode(self, msg, args):
        if not args or not args[0].isdigit():
            await msg.reply(embed=_err('`.slowmode <sekundy>` — 0 wyłącza'), mention_author=False); return
        sec = min(int(args[0]), 21600)
        try:
            await msg.channel.edit(slowmode_delay=sec)
        except discord.Forbidden:
            await msg.reply(embed=_err('Brak uprawnień.'), mention_author=False); return
        if sec == 0:
            await msg.reply(embed=_ok('Slowmode wyłączony.'), mention_author=False)
        else:
            await msg.reply(embed=_ok(f'Slowmode ustawiony na **{sec}s**.'), mention_author=False)

    async def _cmd_note(self, msg, args):
        if len(args) < 2:
            await msg.reply(embed=_err('`.note @user <treść>`'), mention_author=False); return
        m = self._resolve_member(msg, args[0])
        if not m:
            await msg.reply(embed=_err('Nie znaleziono użytkownika.'), mention_author=False); return
        content = ' '.join(args[1:])
        db.ensure_user(m.id, msg.guild.id, str(m), m.display_name)
        note_id = db.add_note(m.id, msg.guild.id, content, msg.author.id)
        await msg.reply(embed=_ok(f'Notatka #{note_id} dodana dla **{m.display_name}**.'),
                        mention_author=False)

    async def _cmd_notes(self, msg, args):
        if not args:
            await msg.reply(embed=_err('`.notes @user`'), mention_author=False); return
        m = self._resolve_member(msg, args[0])
        if not m:
            await msg.reply(embed=_err('Nie znaleziono użytkownika.'), mention_author=False); return
        notes = db.get_notes(m.id, msg.guild.id)
        if not notes:
            await msg.reply(embed=discord.Embed(
                description=f'📭 Brak notatek dla **{m.display_name}**.', color=GREEN),
                mention_author=False); return
        e = discord.Embed(title=f'📝 Notatki — {m.display_name}', color=YELLOW)
        for n in notes[:10]:
            ts = n['created_at'][:16] if n.get('created_at') else '?'
            author = msg.guild.get_member(n['author_id'])
            by = author.display_name if author else str(n.get('author_id', '?'))
            e.add_field(name=f'#{n["id"]} • {ts} • {by}', value=n['content'], inline=False)
        await msg.reply(embed=e, mention_author=False)

    async def _cmd_deletenote(self, msg, args):
        if not args or not args[0].isdigit():
            await msg.reply(embed=_err('`.deletenote <id>`'), mention_author=False); return
        ok = db.delete_note(int(args[0]), msg.guild.id)
        if ok:
            await msg.reply(embed=_ok(f'Notatka #{args[0]} usunięta.'), mention_author=False)
        else:
            await msg.reply(embed=_err('Nie znaleziono notatki.'), mention_author=False)

    # ── Economy Admin ─────────────────────────────────────────────────────────

    async def _cmd_addmoney(self, msg, args):
        if len(args) < 2:
            await msg.reply(embed=_err('`.addmoney @user <kwota>`'), mention_author=False); return
        m = self._resolve_member(msg, args[0])
        if not m:
            await msg.reply(embed=_err('Nie znaleziono użytkownika.'), mention_author=False); return
        try:
            amount = float(args[1])
            if amount <= 0:
                raise ValueError
        except ValueError:
            await msg.reply(embed=_err('Podaj poprawną kwotę.'), mention_author=False); return
        db.ensure_user(m.id, msg.guild.id, str(m), m.display_name)
        new = db.add_cash(m.id, msg.guild.id, amount)
        await msg.reply(embed=_ok(f'Dodano **{amount:.0f}** 🐾 użytkownikowi **{m.display_name}**. Portfel: {new:.0f} 🐾'),
                        mention_author=False)

    async def _cmd_removemoney(self, msg, args):
        if len(args) < 2:
            await msg.reply(embed=_err('`.removemoney @user <kwota>`'), mention_author=False); return
        m = self._resolve_member(msg, args[0])
        if not m:
            await msg.reply(embed=_err('Nie znaleziono użytkownika.'), mention_author=False); return
        try:
            amount = float(args[1])
            if amount <= 0:
                raise ValueError
        except ValueError:
            await msg.reply(embed=_err('Podaj poprawną kwotę.'), mention_author=False); return
        db.ensure_user(m.id, msg.guild.id, str(m), m.display_name)
        new = db.add_cash(m.id, msg.guild.id, -amount)
        await msg.reply(embed=_ok(f'Odjęto **{amount:.0f}** 🐾 od **{m.display_name}**. Portfel: {new:.0f} 🐾'),
                        mention_author=False)

    async def _cmd_setmoney(self, msg, args):
        if len(args) < 2:
            await msg.reply(embed=_err('`.setmoney @user <kwota>`'), mention_author=False); return
        m = self._resolve_member(msg, args[0])
        if not m:
            await msg.reply(embed=_err('Nie znaleziono użytkownika.'), mention_author=False); return
        try:
            amount = float(args[1])
            if amount < 0:
                raise ValueError
        except ValueError:
            await msg.reply(embed=_err('Podaj poprawną kwotę (>=0).'), mention_author=False); return
        db.ensure_user(m.id, msg.guild.id, str(m), m.display_name)
        with db._lock:
            with db._get_conn() as conn:
                conn.execute('UPDATE users SET cash=? WHERE user_id=? AND guild_id=?',
                             (amount, m.id, msg.guild.id))
                conn.commit()
        await msg.reply(embed=_ok(f'Ustawiono portfel **{m.display_name}** na **{amount:.0f}** 🐾.'),
                        mention_author=False)


    # ── Channel Management (Dyno / ProBot style) ─────────────────────────────

    async def _cmd_lock(self, msg, args):
        """Lock a channel – remove @everyone's ability to send messages."""
        ch = msg.channel
        if args:
            cid = args[0].strip('<#>').strip()
            try:
                ch = msg.guild.get_channel(int(cid)) or ch
            except ValueError:
                pass
        overwrite = ch.overwrites_for(msg.guild.default_role)
        overwrite.send_messages = False
        try:
            await ch.set_permissions(msg.guild.default_role, overwrite=overwrite,
                                     reason=f'Zablokowany przez {msg.author}')
            await msg.reply(embed=_ok(f'🔒 Kanał {ch.mention} zablokowany.'), mention_author=False)
            await send_log(msg.guild, log_embed('🔒 Kanał zablokowany', RED,
                Kanał=ch.mention, Przez=msg.author.mention))
        except discord.Forbidden:
            await msg.reply(embed=_err('Brak uprawnień.'), mention_author=False)

    async def _cmd_unlock(self, msg, args):
        """Unlock a channel – restore @everyone send messages."""
        ch = msg.channel
        if args:
            cid = args[0].strip('<#>').strip()
            try:
                ch = msg.guild.get_channel(int(cid)) or ch
            except ValueError:
                pass
        overwrite = ch.overwrites_for(msg.guild.default_role)
        overwrite.send_messages = None
        try:
            await ch.set_permissions(msg.guild.default_role, overwrite=overwrite,
                                     reason=f'Odblokowany przez {msg.author}')
            await msg.reply(embed=_ok(f'🔓 Kanał {ch.mention} odblokowany.'), mention_author=False)
            await send_log(msg.guild, log_embed('🔓 Kanał odblokowany', GREEN,
                Kanał=ch.mention, Przez=msg.author.mention))
        except discord.Forbidden:
            await msg.reply(embed=_err('Brak uprawnień.'), mention_author=False)

    async def _cmd_hide(self, msg, args):
        """Hide a channel from @everyone."""
        ch = msg.channel
        if args:
            cid = args[0].strip('<#>').strip()
            try:
                ch = msg.guild.get_channel(int(cid)) or ch
            except ValueError:
                pass
        overwrite = ch.overwrites_for(msg.guild.default_role)
        overwrite.view_channel = False
        try:
            await ch.set_permissions(msg.guild.default_role, overwrite=overwrite,
                                     reason=f'Ukryty przez {msg.author}')
            await msg.reply(embed=_ok(f'🙈 Kanał {ch.mention} ukryty.'), mention_author=False)
        except discord.Forbidden:
            await msg.reply(embed=_err('Brak uprawnień.'), mention_author=False)

    async def _cmd_unhide(self, msg, args):
        """Unhide a channel for @everyone."""
        ch = msg.channel
        if args:
            cid = args[0].strip('<#>').strip()
            try:
                ch = msg.guild.get_channel(int(cid)) or ch
            except ValueError:
                pass
        overwrite = ch.overwrites_for(msg.guild.default_role)
        overwrite.view_channel = None
        try:
            await ch.set_permissions(msg.guild.default_role, overwrite=overwrite,
                                     reason=f'Odkryty przez {msg.author}')
            await msg.reply(embed=_ok(f'👁️ Kanał {ch.mention} odkryty.'), mention_author=False)
        except discord.Forbidden:
            await msg.reply(embed=_err('Brak uprawnień.'), mention_author=False)

    async def _cmd_announce(self, msg, args):
        """.announce #channel <treść>"""
        if len(args) < 2:
            await msg.reply(embed=_err('`.announce #kanał <treść>`'), mention_author=False); return
        cid = args[0].strip('<#>').strip()
        try:
            ch = msg.guild.get_channel(int(cid))
        except ValueError:
            ch = None
        if not ch:
            await msg.reply(embed=_err('Nie znaleziono kanału.'), mention_author=False); return
        content = ' '.join(args[1:])
        e = discord.Embed(description=content, color=BLURPLE, timestamp=datetime.now())
        e.set_author(name=msg.guild.name, icon_url=msg.guild.icon.url if msg.guild.icon else None)
        e.set_footer(text=f'Ogłoszenie przez {msg.author.display_name}')
        try:
            await ch.send(embed=e)
            await msg.reply(embed=_ok(f'Ogłoszenie wysłane do {ch.mention}.'), mention_author=False)
        except discord.Forbidden:
            await msg.reply(embed=_err('Brak uprawnień do wysłania na ten kanał.'), mention_author=False)

    # ── User management extras (Dyno) ─────────────────────────────────────────

    async def _cmd_nick(self, msg, args):
        """.nick @user <nowy nick> | .nick @user reset"""
        if len(args) < 2:
            await msg.reply(embed=_err('`.nick @user <nowy nick>` lub `.nick @user reset`'),
                            mention_author=False); return
        m = self._resolve_member(msg, args[0])
        if not m:
            await msg.reply(embed=_err('Nie znaleziono użytkownika.'), mention_author=False); return
        new_nick = None if args[1].lower() == 'reset' else ' '.join(args[1:])
        try:
            await m.edit(nick=new_nick, reason=f'Nick zmieniony przez {msg.author}')
            if new_nick:
                await msg.reply(embed=_ok(f'Nick **{m.display_name}** zmieniony na **{new_nick}**.'),
                                mention_author=False)
            else:
                await msg.reply(embed=_ok(f'Nick **{m.name}** zresetowany.'), mention_author=False)
        except discord.Forbidden:
            await msg.reply(embed=_err('Brak uprawnień do zmiany nicku.'), mention_author=False)

    async def _cmd_move(self, msg, args):
        """.move @user #voice_channel"""
        if len(args) < 2:
            await msg.reply(embed=_err('`.move @user #kanał_głosowy`'), mention_author=False); return
        m = self._resolve_member(msg, args[0])
        if not m:
            await msg.reply(embed=_err('Nie znaleziono użytkownika.'), mention_author=False); return
        cid = args[1].strip('<#>').strip()
        try:
            ch = msg.guild.get_channel(int(cid))
        except ValueError:
            ch = None
        if not ch or not isinstance(ch, discord.VoiceChannel):
            await msg.reply(embed=_err('Podaj poprawny kanał głosowy.'), mention_author=False); return
        if not m.voice:
            await msg.reply(embed=_err(f'**{m.display_name}** nie jest na żadnym kanale głosowym.'),
                            mention_author=False); return
        try:
            await m.move_to(ch, reason=f'Przeniesiony przez {msg.author}')
            await msg.reply(embed=_ok(f'**{m.display_name}** przeniesiony do **{ch.name}**.'),
                            mention_author=False)
        except discord.Forbidden:
            await msg.reply(embed=_err('Brak uprawnień.'), mention_author=False)

    async def _cmd_deafen(self, msg, args):
        """.deafen @user"""
        if not args:
            await msg.reply(embed=_err('`.deafen @user`'), mention_author=False); return
        m = self._resolve_member(msg, args[0])
        if not m:
            await msg.reply(embed=_err('Nie znaleziono użytkownika.'), mention_author=False); return
        try:
            await m.edit(deafen=True, reason=f'Deafen przez {msg.author}')
            await msg.reply(embed=_ok(f'**{m.display_name}** ogłuszony (server deafen).'),
                            mention_author=False)
        except discord.Forbidden:
            await msg.reply(embed=_err('Brak uprawnień.'), mention_author=False)

    async def _cmd_undeafen(self, msg, args):
        """.undeafen @user"""
        if not args:
            await msg.reply(embed=_err('`.undeafen @user`'), mention_author=False); return
        m = self._resolve_member(msg, args[0])
        if not m:
            await msg.reply(embed=_err('Nie znaleziono użytkownika.'), mention_author=False); return
        try:
            await m.edit(deafen=False, reason=f'Undeafen przez {msg.author}')
            await msg.reply(embed=_ok(f'**{m.display_name}** odogłuszony.'), mention_author=False)
        except discord.Forbidden:
            await msg.reply(embed=_err('Brak uprawnień.'), mention_author=False)

    # ── Tags (Carl-bot style) ─────────────────────────────────────────────────

    async def _cmd_tag_admin(self, msg, args):
        """.tag create <name> <content> | .tag edit <name> <content> | .tag delete <name>"""
        # Route: if cmd is tagcreate/tagdelete/tagedit inject first arg
        cmd = msg.content[1:].strip().split()[0].lower()
        if cmd in ('tagcreate',):
            args = ['create'] + list(args)
        elif cmd in ('tagdelete',):
            args = ['delete'] + list(args)
        elif cmd in ('tagedit',):
            args = ['edit'] + list(args)

        if not args:
            await msg.reply(embed=_err(
                '`.tag create <nazwa> <treść>`\n'
                '`.tag edit <nazwa> <treść>`\n'
                '`.tag delete <nazwa>`\n'
                '`.tag list` – lista tagów'
            ), mention_author=False); return

        sub = args[0].lower()

        if sub == 'create':
            if len(args) < 3:
                await msg.reply(embed=_err('`.tag create <nazwa> <treść>`'), mention_author=False); return
            name = args[1].lower()
            content = ' '.join(args[2:])
            ok = db.create_tag(msg.guild.id, name, content, msg.author.id)
            if not ok:
                await msg.reply(embed=_err(f'Tag **{name}** już istnieje. Użyj `.tag edit`.'),
                                mention_author=False); return
            await msg.reply(embed=_ok(f'Tag **{name}** utworzony.'), mention_author=False)

        elif sub == 'edit':
            if len(args) < 3:
                await msg.reply(embed=_err('`.tag edit <nazwa> <treść>`'), mention_author=False); return
            name = args[1].lower()
            content = ' '.join(args[2:])
            ok = db.update_tag(msg.guild.id, name, content)
            if not ok:
                await msg.reply(embed=_err(f'Tag **{name}** nie istnieje.'), mention_author=False); return
            await msg.reply(embed=_ok(f'Tag **{name}** zaktualizowany.'), mention_author=False)

        elif sub == 'delete':
            if len(args) < 2:
                await msg.reply(embed=_err('`.tag delete <nazwa>`'), mention_author=False); return
            name = args[1].lower()
            ok = db.delete_tag(msg.guild.id, name)
            if not ok:
                await msg.reply(embed=_err(f'Tag **{name}** nie istnieje.'), mention_author=False); return
            await msg.reply(embed=_ok(f'Tag **{name}** usunięty.'), mention_author=False)

        elif sub == 'list':
            tags = db.list_tags(msg.guild.id)
            if not tags:
                await msg.reply(embed=discord.Embed(description='📭 Brak tagów.', color=YELLOW),
                                mention_author=False); return
            e = discord.Embed(title='🏷️ Lista Tagów', color=BLURPLE)
            e.description = ' '.join(f'`{t["name"]}`' for t in tags)
            await msg.reply(embed=e, mention_author=False)

        else:
            await msg.reply(embed=_err(
                '`.tag create <nazwa> <treść>` | `.tag edit <nazwa> <treść>` | `.tag delete <nazwa>` | `.tag list`'
            ), mention_author=False)


async def setup(bot: commands.Bot):
    await bot.add_cog(AdminCog(bot))

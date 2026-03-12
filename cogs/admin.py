import discord
from discord.ext import commands
from datetime import datetime
import json
import database as db
from cogs.clockin import send_log, log_embed

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
            # Warnings
            'warn':            self._cmd_warn,
            'warnings':        self._cmd_warnings,
            'clearwarn':       self._cmd_clearwarn,
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
            # Setup
            'setchannel':      self._cmd_setchannel,
            'setpoints_h':     self._cmd_setpointshour,
            'adminrole':       self._cmd_adminrole,
            'removeadminrole': self._cmd_removeadminrole,
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
        }

    # ── Permission helpers ────────────────────────────────────────────────────

    async def _is_admin(self, member: discord.Member, guild_id: int) -> bool:
        if member.guild_permissions.administrator:
            return True
        cfg = db.get_guild(guild_id)
        if not cfg:
            return False
        try:
            role_ids = json.loads(cfg.get('admin_role_ids') or '[]')
        except Exception:
            role_ids = []
        return any(r.id in role_ids for r in member.roles)

    async def _can_use_cmd(self, member: discord.Member, guild_id: int,
                           command_name: str) -> bool:
        """Check command-level permission, falling back to admin check."""
        perm = db.get_command_permission(guild_id, command_name)
        if perm:
            try:
                allowed = json.loads(perm['allowed_role_ids'])
            except Exception:
                allowed = []
            if allowed:
                if any(r.id in allowed for r in member.roles):
                    return True
                # Command has explicit roles set – don't fall through to admin
                if not member.guild_permissions.administrator:
                    return False
        return await self._is_admin(member, guild_id)

    def _is_server_owner(self, member: discord.Member, guild_id: int) -> bool:
        if member.id == member.guild.owner_id:
            return True
        cfg = db.get_guild(guild_id)
        if cfg and cfg.get('owner_id') and member.id == cfg['owner_id']:
            return True
        return False

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
        new = db.add_points(m.id, msg.guild.id, pts, note=note,
                            transaction_type='manual', assigned_by=msg.author.id)
        e = _ok(f'**+{pts:.1f} pkt** → **{m.display_name}** | Stan: **{new:.1f} pkt**')
        e.add_field(name='📝 Nota', value=note)
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
        new = db.add_points(m.id, msg.guild.id, -pts, note=note,
                            transaction_type='manual', assigned_by=msg.author.id)
        e = _ok(f'**-{pts:.1f} pkt** ← **{m.display_name}** | Stan: **{new:.1f} pkt**')
        e.add_field(name='📝 Nota', value=note)
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
        new = db.set_points(m.id, msg.guild.id, pts, note=note, assigned_by=msg.author.id)
        await msg.reply(embed=_ok(f'Ustawiono **{pts:.1f} pkt** dla **{m.display_name}**'),
                        mention_author=False)
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
        count = db.get_warning_count(m.id, msg.guild.id)
        cfg = db.get_guild(msg.guild.id) or {}
        limit = cfg.get('warn_limit', 3)
        e = _ok(f'Ostrzeżono **{m.display_name}** ({count}/{limit} ostrzeżeń)')
        e.add_field(name='📝 Powód', value=reason)
        if count >= limit:
            db.update_user(m.id, msg.guild.id, is_banned=1)
            e.add_field(name='⚠️', value=f'Osiągnięto limit! Auto-ban z rankingu.')
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
        if not rank['is_special']:
            await msg.reply(embed=_warn('To automatyczna ranga – nie można nadawać ręcznie.'),
                            mention_author=False); return
        if not await self._can_grant_rank(msg.author, msg.guild.id, rank):
            if rank.get('is_owner_only'):
                await msg.reply(embed=_err('Ta ranga jest **tylko dla właściciela serwera/dowódcy**.'),
                                mention_author=False)
            else:
                await msg.reply(embed=_err('Twoja rola nie ma uprawnień do nadawania tej rangi.'),
                                mention_author=False)
            return

        db.ensure_user(m.id, msg.guild.id, str(m), m.display_name)
        ok = db.give_special_rank(m.id, msg.guild.id, rank['id'],
                                  assigned_by=msg.author.id, note=note)
        if not ok:
            await msg.reply(embed=_warn(f'**{m.display_name}** już posiada tę rangę.'),
                            mention_author=False); return

        badge = '👑' if rank.get('is_owner_only') else '🎖️'
        e = _ok(f'{badge} Nadano rangę **{rank["icon"]} {rank["name"]}** → **{m.display_name}**')
        if note:
            e.add_field(name='📝 Nota', value=note)
        await msg.reply(embed=e, mention_author=False)

        if rank.get('role_id'):
            role = msg.guild.get_role(rank['role_id'])
            if role:
                try:
                    await m.add_roles(role, reason=f'Ranga: {rank["name"]}')
                except discord.Forbidden:
                    pass
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
        .createrank <nazwa> <punkty|SPECIAL|UNIT> [ikona] [#kolor] [opis]
        SPECIAL = ranga specjalna (admin może nadawać)
        UNIT    = jednostka (tylko właściciel/dowódca może nadawać)
        """
        if len(args) < 2:
            await msg.reply(embed=_err(
                '`.createrank <nazwa> <punkty|SPECIAL|UNIT> [ikona] [#kolor] [opis]`\n'
                '`SPECIAL` = ranga specjalna (admin)\n'
                '`UNIT` = jednostka (tylko właściciel/dowódca)'
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

        icon  = args[2] if len(args) > 2 else ('👑' if is_owner_only else ('🎖️' if is_special else '⭐'))
        color = '#7289da'
        desc  = ''
        if len(args) > 3:
            if args[3].startswith('#'):
                color = args[3]
                desc = ' '.join(args[4:])
            else:
                desc = ' '.join(args[3:])

        if db.get_rank_by_name(msg.guild.id, name):
            await msg.reply(embed=_err(f'Ranga **{name}** już istnieje.'), mention_author=False); return

        rank = db.create_rank(msg.guild.id, name, req_pts, color=color,
                              description=desc, icon=icon,
                              is_special=is_special, is_owner_only=is_owner_only)
        if not rank:
            await msg.reply(embed=_err('Błąd tworzenia rangi.'), mention_author=False); return

        badge = '👑 UNIT' if is_owner_only else ('🎖️ SPECIAL' if is_special else f'🤖 AUTO ({req_pts:.0f} pkt)')
        e = _ok(f'Utworzono rangę **{icon} {name}** [{badge}]')
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
                'Pola: `name`, `points`, `icon`, `color`, `description`'
            ), mention_author=False); return
        rank = db.get_rank_by_name(msg.guild.id, args[0])
        if not rank:
            await msg.reply(embed=_err('Nie znaleziono rangi.'), mention_author=False); return
        field = args[1].lower()
        value = ' '.join(args[2:])
        fields_map = {
            'name': ('name', lambda v: v),
            'points': ('required_points', float),
            'icon': ('icon', lambda v: v),
            'color': ('color', lambda v: v),
            'description': ('description', lambda v: v),
        }
        if field not in fields_map:
            await msg.reply(embed=_err('Pole: `name`, `points`, `icon`, `color`, `description`'),
                            mention_author=False); return
        col, converter = fields_map[field]
        try:
            db.update_rank(rank['id'], **{col: converter(value)})
        except ValueError:
            await msg.reply(embed=_err('Nieprawidłowa wartość.'), mention_author=False); return
        await msg.reply(embed=_ok(f'Zaktualizowano **{rank["name"]}**: `{field}` = `{value}`'),
                        mention_author=False)

    async def _cmd_ranks(self, msg, args):
        ranks = db.get_ranks(msg.guild.id)
        if not ranks:
            await msg.reply(embed=_warn('Brak rang. Użyj `.createrank`.'), mention_author=False); return
        e = discord.Embed(title='⭐ Lista Rang', color=BLURPLE)
        auto    = [r for r in ranks if not r['is_special']]
        special = [r for r in ranks if r['is_special'] and not r['is_owner_only']]
        units   = [r for r in ranks if r['is_owner_only']]
        if auto:
            e.add_field(name='🤖 Automatyczne', inline=False,
                value='\n'.join(f'{r["icon"]} **{r["name"]}** – {r["required_points"]:.0f} pkt' for r in auto))
        if special:
            e.add_field(name='🎖️ Specjalne (admin)', inline=False,
                value='\n'.join(f'{r["icon"]} **{r["name"]}**' + (f' – {r["description"]}' if r.get("description") else '') for r in special))
        if units:
            e.add_field(name='👑 Jednostki (tylko właściciel/dowódca)', inline=False,
                value='\n'.join(f'{r["icon"]} **{r["name"]}**' + (f' – {r["description"]}' if r.get("description") else '') for r in units))
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
        u = db.get_user(m.id, msg.guild.id)
        rank = db.get_user_auto_rank(m.id, msg.guild.id)
        specials = db.get_user_special_ranks(m.id, msg.guild.id)
        warns = db.get_warnings(m.id, msg.guild.id)
        txs = db.get_user_transactions(m.id, msg.guild.id, limit=5)
        cfg = db.get_guild(msg.guild.id) or {}
        e = discord.Embed(title=f'📋 Info: {m.display_name}', color=BLURPLE, timestamp=datetime.now())
        e.set_thumbnail(url=m.display_avatar.url)
        e.add_field(name='💰 Punkty', value=f'{u["points"]:.1f}', inline=True)
        e.add_field(name='⏱️ Godziny', value=f'{u["total_hours"]:.2f}h', inline=True)
        e.add_field(name='📅 Sesje', value=str(u['sessions_count']), inline=True)
        e.add_field(name='⭐ Ranga auto',
                    value=f'{rank["icon"]} {rank["name"]}' if rank else 'Brak', inline=True)
        e.add_field(name='🎖️ Rangi spec.',
                    value=', '.join(f'{r["icon"]} {r["name"]}' for r in specials) or 'Brak', inline=True)
        e.add_field(name='🟢 Aktywny',
                    value='Tak' if u['is_clocked_in'] else 'Nie', inline=True)
        warn_limit = cfg.get('warn_limit', 3)
        e.add_field(name='⚠️ Ostrzeżenia',
                    value=f'{len(warns)}/{warn_limit}', inline=True)
        if u['is_banned']:
            e.add_field(name='🔨 Status', value='ZABLOKOWANY na lb', inline=True)
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
            ids   = json.loads(f['role_ids'] or '[]')
            roles = [msg.guild.get_role(r) for r in ids if msg.guild.get_role(r)]
            val   = (', '.join(r.mention for r in roles) if roles else '*brak ról*')
            if f.get('description'):
                val += f'\n*{f["description"]}*'
            e.add_field(name=f'{f["icon"]} {f["name"]}', value=val, inline=False)
        await msg.reply(embed=e, mention_author=False)


async def setup(bot: commands.Bot):
    await bot.add_cog(AdminCog(bot))

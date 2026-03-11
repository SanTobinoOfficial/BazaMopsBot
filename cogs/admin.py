import discord
from discord.ext import commands
from datetime import datetime
import json
import database as db

BLURPLE = 0x7289DA
GREEN   = 0x43B581
RED     = 0xF04747
YELLOW  = 0xFAA61A


def _ok(desc: str) -> discord.Embed:
    return discord.Embed(description=f'✅ {desc}', color=GREEN)

def _err(desc: str) -> discord.Embed:
    return discord.Embed(description=f'❌ {desc}', color=RED)

def _warn(desc: str) -> discord.Embed:
    return discord.Embed(description=f'⚠️ {desc}', color=YELLOW)


class AdminCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

        # Map command names → handler methods
        self._handlers = {
            'ban':          self._cmd_ban,
            'unban':        self._cmd_unban,
            'addpoints':    self._cmd_addpoints,
            'removepoints': self._cmd_removepoints,
            'setpoints':    self._cmd_setpoints,
            'resetuser':    self._cmd_resetuser,
            'giverank':     self._cmd_giverank,
            'takerank':     self._cmd_takerank,
            'createrank':   self._cmd_createrank,
            'deleterank':   self._cmd_deleterank,
            'editrank':     self._cmd_editrank,
            'ranks':        self._cmd_ranks,
            'forceclockout':self._cmd_forceclockout,
            'setchannel':   self._cmd_setchannel,
            'setpoints_h':  self._cmd_setpointshour,
            'adminrole':    self._cmd_adminrole,
            'removeadminrole': self._cmd_removeadminrole,
            'userinfo':     self._cmd_userinfo,
            'serverstats':  self._cmd_serverstats,
            'config':       self._cmd_config,
        }

    async def _is_admin(self, member: discord.Member, guild: discord.Guild) -> bool:
        if member.guild_permissions.administrator:
            return True
        cfg = db.get_guild(guild.id)
        if not cfg:
            return False
        try:
            role_ids = json.loads(cfg['admin_role_ids']) if isinstance(cfg['admin_role_ids'], str) else cfg['admin_role_ids']
        except Exception:
            role_ids = []
        return any(r.id in role_ids for r in member.roles)

    def _resolve_member(self, message: discord.Message, arg: str) -> discord.Member | None:
        """Resolve a mention or ID to a Member."""
        # Mention format: <@123> or <@!123>
        uid = arg.strip('<@!>').strip()
        try:
            uid_int = int(uid)
            return message.guild.get_member(uid_int)
        except ValueError:
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
        args = parts[1:]

        if cmd not in self._handlers:
            return

        if not await self._is_admin(message.author, message.guild):
            await message.reply(embed=_err('Nie masz uprawnień administratora.'),
                                mention_author=False)
            return

        db.ensure_guild(message.guild.id)
        await self._handlers[cmd](message, args)

    # ── .ban @user ────────────────────────────────────────────────────────────
    async def _cmd_ban(self, msg: discord.Message, args: list):
        if not args:
            await msg.reply(embed=_err('Użycie: `.ban @użytkownik`'), mention_author=False)
            return
        member = self._resolve_member(msg, args[0])
        if not member:
            await msg.reply(embed=_err('Nie znaleziono użytkownika.'), mention_author=False)
            return
        db.ensure_user(member.id, msg.guild.id, str(member), member.display_name)
        db.update_user(member.id, msg.guild.id, is_banned=1)
        embed = _ok(f'**{member.display_name}** został(a) zablokowany(a) na liście rankingowej.')
        embed.set_footer(text=f'Przez: {msg.author.display_name}')
        await msg.reply(embed=embed, mention_author=False)

    # ── .unban @user ──────────────────────────────────────────────────────────
    async def _cmd_unban(self, msg: discord.Message, args: list):
        if not args:
            await msg.reply(embed=_err('Użycie: `.unban @użytkownik`'), mention_author=False)
            return
        member = self._resolve_member(msg, args[0])
        if not member:
            await msg.reply(embed=_err('Nie znaleziono użytkownika.'), mention_author=False)
            return
        db.update_user(member.id, msg.guild.id, is_banned=0)
        await msg.reply(embed=_ok(f'**{member.display_name}** został(a) odblokowany(a) na liście rankingowej.'),
                        mention_author=False)

    # ── .addpoints @user <n> [nota] ───────────────────────────────────────────
    async def _cmd_addpoints(self, msg: discord.Message, args: list):
        if len(args) < 2:
            await msg.reply(embed=_err('Użycie: `.addpoints @użytkownik <liczba> [nota]`'),
                            mention_author=False)
            return
        member = self._resolve_member(msg, args[0])
        if not member:
            await msg.reply(embed=_err('Nie znaleziono użytkownika.'), mention_author=False)
            return
        try:
            pts = float(args[1])
        except ValueError:
            await msg.reply(embed=_err('Nieprawidłowa liczba punktów.'), mention_author=False)
            return
        note = ' '.join(args[2:]) if len(args) > 2 else 'Ręczne dodanie przez admina'
        db.ensure_user(member.id, msg.guild.id, str(member), member.display_name)
        new_pts = db.add_points(member.id, msg.guild.id, pts, note=note,
                                transaction_type='manual', assigned_by=msg.author.id)
        embed = _ok(f'Dodano **+{pts:.1f} pkt** dla **{member.display_name}**\n'
                    f'Nowy stan: **{new_pts:.1f} pkt**')
        if note:
            embed.add_field(name='📝 Nota', value=note)
        embed.set_footer(text=f'Przez: {msg.author.display_name}')
        await msg.reply(embed=embed, mention_author=False)

    # ── .removepoints @user <n> [nota] ───────────────────────────────────────
    async def _cmd_removepoints(self, msg: discord.Message, args: list):
        if len(args) < 2:
            await msg.reply(embed=_err('Użycie: `.removepoints @użytkownik <liczba> [nota]`'),
                            mention_author=False)
            return
        member = self._resolve_member(msg, args[0])
        if not member:
            await msg.reply(embed=_err('Nie znaleziono użytkownika.'), mention_author=False)
            return
        try:
            pts = float(args[1])
        except ValueError:
            await msg.reply(embed=_err('Nieprawidłowa liczba punktów.'), mention_author=False)
            return
        note = ' '.join(args[2:]) if len(args) > 2 else 'Ręczne odjęcie przez admina'
        db.ensure_user(member.id, msg.guild.id, str(member), member.display_name)
        new_pts = db.add_points(member.id, msg.guild.id, -pts, note=note,
                                transaction_type='manual', assigned_by=msg.author.id)
        embed = _ok(f'Odjęto **-{pts:.1f} pkt** od **{member.display_name}**\n'
                    f'Nowy stan: **{new_pts:.1f} pkt**')
        if note:
            embed.add_field(name='📝 Nota', value=note)
        embed.set_footer(text=f'Przez: {msg.author.display_name}')
        await msg.reply(embed=embed, mention_author=False)

    # ── .setpoints @user <n> [nota] ───────────────────────────────────────────
    async def _cmd_setpoints(self, msg: discord.Message, args: list):
        if len(args) < 2:
            await msg.reply(embed=_err('Użycie: `.setpoints @użytkownik <liczba> [nota]`'),
                            mention_author=False)
            return
        member = self._resolve_member(msg, args[0])
        if not member:
            await msg.reply(embed=_err('Nie znaleziono użytkownika.'), mention_author=False)
            return
        try:
            pts = float(args[1])
        except ValueError:
            await msg.reply(embed=_err('Nieprawidłowa liczba punktów.'), mention_author=False)
            return
        note = ' '.join(args[2:]) if len(args) > 2 else 'Ręczne ustawienie przez admina'
        db.ensure_user(member.id, msg.guild.id, str(member), member.display_name)
        new_pts = db.set_points(member.id, msg.guild.id, pts, note=note, assigned_by=msg.author.id)
        embed = _ok(f'Ustawiono **{pts:.1f} pkt** dla **{member.display_name}**')
        if note:
            embed.add_field(name='📝 Nota', value=note)
        embed.set_footer(text=f'Przez: {msg.author.display_name}')
        await msg.reply(embed=embed, mention_author=False)

    # ── .resetuser @user ──────────────────────────────────────────────────────
    async def _cmd_resetuser(self, msg: discord.Message, args: list):
        if not args:
            await msg.reply(embed=_err('Użycie: `.resetuser @użytkownik`'), mention_author=False)
            return
        member = self._resolve_member(msg, args[0])
        if not member:
            await msg.reply(embed=_err('Nie znaleziono użytkownika.'), mention_author=False)
            return
        db.reset_user(member.id, msg.guild.id)
        await msg.reply(embed=_ok(f'Zresetowano dane **{member.display_name}**.'),
                        mention_author=False)

    # ── .giverank @user <nazwa rangi> [nota] ─────────────────────────────────
    async def _cmd_giverank(self, msg: discord.Message, args: list):
        if len(args) < 2:
            await msg.reply(embed=_err('Użycie: `.giverank @użytkownik <nazwa rangi> [nota]`'),
                            mention_author=False)
            return
        member = self._resolve_member(msg, args[0])
        if not member:
            await msg.reply(embed=_err('Nie znaleziono użytkownika.'), mention_author=False)
            return

        # Rank name can be multi-word; scan until we run out of args
        # Try longest match first
        rank = None
        note = ''
        for i in range(len(args), 1, -1):
            candidate = ' '.join(args[1:i])
            rank = db.get_rank_by_name(msg.guild.id, candidate)
            if rank:
                note = ' '.join(args[i:])
                break

        if not rank:
            await msg.reply(embed=_err(f'Nie znaleziono rangi. Użyj `.ranks` aby zobaczyć listę.'),
                            mention_author=False)
            return
        if not rank['is_special']:
            await msg.reply(embed=_warn('To jest automatyczna ranga – nie można jej nadawać ręcznie.\n'
                                        'Można nadawać tylko **specjalne** rangi.'), mention_author=False)
            return

        db.ensure_user(member.id, msg.guild.id, str(member), member.display_name)
        ok = db.give_special_rank(member.id, msg.guild.id, rank['id'],
                                  assigned_by=msg.author.id, note=note)
        if not ok:
            await msg.reply(embed=_warn(f'**{member.display_name}** już posiada tę rangę.'),
                            mention_author=False)
            return

        embed = _ok(f'Nadano rangę **{rank["icon"]} {rank["name"]}** użytkownikowi **{member.display_name}**')
        if note:
            embed.add_field(name='📝 Nota', value=note)
        embed.set_footer(text=f'Przez: {msg.author.display_name}')
        await msg.reply(embed=embed, mention_author=False)

        # Assign Discord role
        if rank.get('role_id'):
            role = msg.guild.get_role(rank['role_id'])
            if role:
                try:
                    await member.add_roles(role, reason=f'Ranga: {rank["name"]}')
                except discord.Forbidden:
                    pass

    # ── .takerank @user <nazwa rangi> ─────────────────────────────────────────
    async def _cmd_takerank(self, msg: discord.Message, args: list):
        if len(args) < 2:
            await msg.reply(embed=_err('Użycie: `.takerank @użytkownik <nazwa rangi>`'),
                            mention_author=False)
            return
        member = self._resolve_member(msg, args[0])
        if not member:
            await msg.reply(embed=_err('Nie znaleziono użytkownika.'), mention_author=False)
            return
        rank_name = ' '.join(args[1:])
        rank = db.get_rank_by_name(msg.guild.id, rank_name)
        if not rank:
            await msg.reply(embed=_err('Nie znaleziono rangi.'), mention_author=False)
            return
        ok = db.remove_special_rank(member.id, msg.guild.id, rank['id'])
        if not ok:
            await msg.reply(embed=_warn(f'**{member.display_name}** nie posiada tej rangi.'),
                            mention_author=False)
            return
        await msg.reply(embed=_ok(f'Odebrano rangę **{rank["icon"]} {rank["name"]}** od **{member.display_name}**.'),
                        mention_author=False)
        if rank.get('role_id'):
            role = msg.guild.get_role(rank['role_id'])
            if role and role in member.roles:
                try:
                    await member.remove_roles(role, reason=f'Odebrana ranga: {rank["name"]}')
                except discord.Forbidden:
                    pass

    # ── .createrank <nazwa> <punkty> [ikona] [kolor hex] [opis] ──────────────
    async def _cmd_createrank(self, msg: discord.Message, args: list):
        """Usage: .createrank <nazwa> <punkty_lub_SPECIAL> [ikona] [#kolor] [opis...]"""
        if len(args) < 2:
            await msg.reply(embed=_err(
                'Użycie: `.createrank <nazwa> <wymagane_punkty|SPECIAL> [ikona] [#kolor] [opis]`\n'
                'Przykład: `.createrank Weteran SPECIAL 🎖️ #ffd700 Dla weteranów`\n'
                'Przykład: `.createrank Kapral 300 🪖 #99aab5`'
            ), mention_author=False)
            return

        name = args[0]
        is_special = args[1].upper() == 'SPECIAL'
        try:
            req_pts = 0.0 if is_special else float(args[1])
        except ValueError:
            await msg.reply(embed=_err('Punkty muszą być liczbą lub "SPECIAL".'), mention_author=False)
            return

        icon  = args[2] if len(args) > 2 else ('🎖️' if is_special else '⭐')
        color = '#7289da'
        desc  = ''
        if len(args) > 3:
            if args[3].startswith('#'):
                color = args[3]
                desc = ' '.join(args[4:])
            else:
                desc = ' '.join(args[3:])

        if db.get_rank_by_name(msg.guild.id, name):
            await msg.reply(embed=_err(f'Ranga o nazwie **{name}** już istnieje.'), mention_author=False)
            return

        rank = db.create_rank(msg.guild.id, name, req_pts, color=color,
                               description=desc, icon=icon, is_special=is_special)
        if not rank:
            await msg.reply(embed=_err('Błąd przy tworzeniu rangi.'), mention_author=False)
            return

        kind = '🎖️ Specjalna (tylko admin)' if is_special else f'🤖 Automatyczna (przy {req_pts:.0f} pkt)'
        embed = _ok(f'Utworzono rangę **{icon} {name}**')
        embed.add_field(name='Typ', value=kind, inline=True)
        embed.add_field(name='Kolor', value=color, inline=True)
        if desc:
            embed.add_field(name='Opis', value=desc, inline=False)
        await msg.reply(embed=embed, mention_author=False)

    # ── .deleterank <nazwa> ───────────────────────────────────────────────────
    async def _cmd_deleterank(self, msg: discord.Message, args: list):
        if not args:
            await msg.reply(embed=_err('Użycie: `.deleterank <nazwa rangi>`'), mention_author=False)
            return
        name = ' '.join(args)
        rank = db.get_rank_by_name(msg.guild.id, name)
        if not rank:
            await msg.reply(embed=_err(f'Nie znaleziono rangi **{name}**.'), mention_author=False)
            return
        db.delete_rank(rank['id'])
        await msg.reply(embed=_ok(f'Usunięto rangę **{rank["icon"]} {rank["name"]}**.'),
                        mention_author=False)

    # ── .editrank <nazwa> <pole> <wartość> ────────────────────────────────────
    async def _cmd_editrank(self, msg: discord.Message, args: list):
        if len(args) < 3:
            await msg.reply(embed=_err(
                'Użycie: `.editrank <nazwa> <pole> <wartość>`\n'
                'Pola: `name`, `points`, `icon`, `color`, `description`'
            ), mention_author=False)
            return
        rank_name = args[0]
        field = args[1].lower()
        value = ' '.join(args[2:])
        rank = db.get_rank_by_name(msg.guild.id, rank_name)
        if not rank:
            await msg.reply(embed=_err('Nie znaleziono rangi.'), mention_author=False)
            return
        allowed = {'name', 'points', 'icon', 'color', 'description'}
        if field not in allowed:
            await msg.reply(embed=_err(f'Nieprawidłowe pole. Dostępne: {", ".join(allowed)}'),
                            mention_author=False)
            return
        update = {}
        if field == 'points':
            try:
                update['required_points'] = float(value)
            except ValueError:
                await msg.reply(embed=_err('Punkty muszą być liczbą.'), mention_author=False)
                return
        elif field == 'name':
            update['name'] = value
        elif field == 'icon':
            update['icon'] = value
        elif field == 'color':
            update['color'] = value
        elif field == 'description':
            update['description'] = value
        db.update_rank(rank['id'], **update)
        await msg.reply(embed=_ok(f'Zaktualizowano rangę **{rank["name"]}**: `{field}` = `{value}`'),
                        mention_author=False)

    # ── .ranks ────────────────────────────────────────────────────────────────
    async def _cmd_ranks(self, msg: discord.Message, args: list):
        ranks = db.get_ranks(msg.guild.id)
        if not ranks:
            await msg.reply(embed=_warn('Brak skonfigurowanych rang. Użyj `.createrank`.'),
                            mention_author=False)
            return
        auto = [r for r in ranks if not r['is_special']]
        special = [r for r in ranks if r['is_special']]

        embed = discord.Embed(title='⭐ Lista Rang', color=BLURPLE)
        if auto:
            embed.add_field(
                name='🤖 Automatyczne (za punkty)',
                value='\n'.join(
                    f'{r["icon"]} **{r["name"]}** – {r["required_points"]:.0f} pkt'
                    for r in auto
                ),
                inline=False
            )
        if special:
            embed.add_field(
                name='🎖️ Specjalne (tylko admin)',
                value='\n'.join(
                    f'{r["icon"]} **{r["name"]}**'
                    + (f' – {r["description"]}' if r.get("description") else '')
                    for r in special
                ),
                inline=False
            )
        await msg.reply(embed=embed, mention_author=False)

    # ── .forceclockout @user ──────────────────────────────────────────────────
    async def _cmd_forceclockout(self, msg: discord.Message, args: list):
        if not args:
            await msg.reply(embed=_err('Użycie: `.forceclockout @użytkownik`'), mention_author=False)
            return
        member = self._resolve_member(msg, args[0])
        if not member:
            await msg.reply(embed=_err('Nie znaleziono użytkownika.'), mention_author=False)
            return
        ok = db.force_clock_out(member.id, msg.guild.id)
        if ok:
            await msg.reply(embed=_ok(f'Wymuszono wylogowanie **{member.display_name}**.'),
                            mention_author=False)
        else:
            await msg.reply(embed=_warn(f'**{member.display_name}** nie był(a) zalogowany(a).'),
                            mention_author=False)

    # ── .setchannel <clock|log> #channel ──────────────────────────────────────
    async def _cmd_setchannel(self, msg: discord.Message, args: list):
        if len(args) < 2:
            await msg.reply(embed=_err('Użycie: `.setchannel <clock|log> #kanał`'), mention_author=False)
            return
        kind = args[0].lower()
        ch_arg = args[1]
        ch_id_str = ch_arg.strip('<#>').strip()
        try:
            ch_id = int(ch_id_str)
        except ValueError:
            await msg.reply(embed=_err('Nieprawidłowy kanał.'), mention_author=False)
            return
        channel = msg.guild.get_channel(ch_id)
        if not channel:
            await msg.reply(embed=_err('Kanał nie istnieje na serwerze.'), mention_author=False)
            return
        if kind == 'clock':
            db.update_guild(msg.guild.id, clock_channel_id=ch_id)
            await msg.reply(embed=_ok(f'Ustawiono kanał Clock In/Out: {channel.mention}'),
                            mention_author=False)
        elif kind == 'log':
            db.update_guild(msg.guild.id, log_channel_id=ch_id)
            await msg.reply(embed=_ok(f'Ustawiono kanał logów: {channel.mention}'),
                            mention_author=False)
        else:
            await msg.reply(embed=_err('Typ kanału: `clock` lub `log`'), mention_author=False)

    # ── .setpoints_h <liczba> ─────────────────────────────────────────────────
    async def _cmd_setpointshour(self, msg: discord.Message, args: list):
        if not args:
            await msg.reply(embed=_err('Użycie: `.setpoints_h <punkty_na_godzinę>`'),
                            mention_author=False)
            return
        try:
            pph = float(args[0])
        except ValueError:
            await msg.reply(embed=_err('Nieprawidłowa wartość.'), mention_author=False)
            return
        db.update_guild(msg.guild.id, points_per_hour=pph)
        await msg.reply(embed=_ok(f'Ustawiono **{pph:.1f} punktów/h** za aktywność.'),
                        mention_author=False)

    # ── .adminrole @role ──────────────────────────────────────────────────────
    async def _cmd_adminrole(self, msg: discord.Message, args: list):
        if not args:
            await msg.reply(embed=_err('Użycie: `.adminrole @rola`'), mention_author=False)
            return
        role_str = args[0].strip('<@&>').strip()
        try:
            role_id = int(role_str)
        except ValueError:
            await msg.reply(embed=_err('Nieprawidłowa rola.'), mention_author=False)
            return
        role = msg.guild.get_role(role_id)
        if not role:
            await msg.reply(embed=_err('Rola nie istnieje.'), mention_author=False)
            return
        cfg = db.get_guild(msg.guild.id) or {}
        try:
            ids = json.loads(cfg.get('admin_role_ids', '[]'))
        except Exception:
            ids = []
        if role_id not in ids:
            ids.append(role_id)
        db.update_guild(msg.guild.id, admin_role_ids=json.dumps(ids))
        await msg.reply(embed=_ok(f'Dodano {role.mention} jako rolę administratora bota.'),
                        mention_author=False)

    # ── .removeadminrole @role ────────────────────────────────────────────────
    async def _cmd_removeadminrole(self, msg: discord.Message, args: list):
        if not args:
            await msg.reply(embed=_err('Użycie: `.removeadminrole @rola`'), mention_author=False)
            return
        role_str = args[0].strip('<@&>').strip()
        try:
            role_id = int(role_str)
        except ValueError:
            await msg.reply(embed=_err('Nieprawidłowa rola.'), mention_author=False)
            return
        cfg = db.get_guild(msg.guild.id) or {}
        try:
            ids = json.loads(cfg.get('admin_role_ids', '[]'))
        except Exception:
            ids = []
        ids = [i for i in ids if i != role_id]
        db.update_guild(msg.guild.id, admin_role_ids=json.dumps(ids))
        await msg.reply(embed=_ok('Usunięto rolę z listy administratorów bota.'),
                        mention_author=False)

    # ── .userinfo @user ───────────────────────────────────────────────────────
    async def _cmd_userinfo(self, msg: discord.Message, args: list):
        if args:
            member = self._resolve_member(msg, args[0])
        else:
            member = msg.author
        if not member:
            await msg.reply(embed=_err('Nie znaleziono użytkownika.'), mention_author=False)
            return
        db.ensure_user(member.id, msg.guild.id, str(member), member.display_name)
        user = db.get_user(member.id, msg.guild.id)
        rank = db.get_user_auto_rank(member.id, msg.guild.id)
        specials = db.get_user_special_ranks(member.id, msg.guild.id)
        transactions = db.get_user_transactions(member.id, msg.guild.id, limit=5)
        sessions = db.get_user_sessions(member.id, msg.guild.id, limit=5)

        embed = discord.Embed(
            title=f'📋 Info: {member.display_name}',
            color=BLURPLE,
            timestamp=datetime.now()
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name='💰 Punkty', value=f'{user["points"]:.1f}', inline=True)
        embed.add_field(name='⏱️ Godziny', value=f'{user["total_hours"]:.2f}h', inline=True)
        embed.add_field(name='📅 Sesje', value=str(user['sessions_count']), inline=True)
        embed.add_field(name='⭐ Ranga auto', value=f'{rank["icon"]} {rank["name"]}' if rank else 'Brak', inline=True)
        embed.add_field(name='🎖️ Rangi spec.',
                        value=', '.join(f'{r["icon"]} {r["name"]}' for r in specials) or 'Brak',
                        inline=True)
        embed.add_field(name='🔴 Aktywny',
                        value='🟢 Tak' if user['is_clocked_in'] else '🔴 Nie', inline=True)
        if user['is_banned']:
            embed.add_field(name='⚠️ Status', value='ZABLOKOWANY na lb', inline=False)

        if transactions:
            tx_lines = []
            for t in transactions:
                sign = '+' if t['points_change'] > 0 else ''
                tx_lines.append(f'`{sign}{t["points_change"]:.1f}` {t["note"][:40]}')
            embed.add_field(name='💸 Ostatnie transakcje', value='\n'.join(tx_lines), inline=False)

        embed.set_footer(text=f'ID: {member.id}')
        await msg.reply(embed=embed, mention_author=False)

    # ── .serverstats ──────────────────────────────────────────────────────────
    async def _cmd_serverstats(self, msg: discord.Message, args: list):
        stats = db.get_guild_stats(msg.guild.id)
        cfg = db.get_guild(msg.guild.id) or {}
        embed = discord.Embed(title='📊 Statystyki Serwera', color=BLURPLE, timestamp=datetime.now())
        embed.add_field(name='👥 Użytkownicy', value=str(stats['total_users']), inline=True)
        embed.add_field(name='💰 Łączne punkty', value=f'{stats["total_points"]:.0f}', inline=True)
        embed.add_field(name='⏱️ Łączne godziny', value=f'{stats["total_hours"]}h', inline=True)
        embed.add_field(name='📅 Sesje łącznie', value=str(stats['total_sessions']), inline=True)
        embed.add_field(name='🟢 Aktywnych teraz', value=str(stats['active_now']), inline=True)
        embed.add_field(name='🔨 Zablokowanych', value=str(stats['banned_count']), inline=True)
        embed.add_field(name='⭐ Rang', value=str(stats['rank_count']), inline=True)
        embed.add_field(name='💡 Pkt/godz', value=f'{cfg.get("points_per_hour", 10):.1f}', inline=True)
        await msg.reply(embed=embed, mention_author=False)

    # ── .config ───────────────────────────────────────────────────────────────
    async def _cmd_config(self, msg: discord.Message, args: list):
        cfg = db.get_guild(msg.guild.id) or {}
        embed = discord.Embed(title='⚙️ Konfiguracja Serwera', color=BLURPLE)

        def ch_name(ch_id):
            if not ch_id:
                return '❌ Nie ustawiony'
            ch = msg.guild.get_channel(ch_id)
            return ch.mention if ch else f'ID: {ch_id}'

        embed.add_field(name='📋 Kanał Clock', value=ch_name(cfg.get('clock_channel_id')), inline=True)
        embed.add_field(name='📝 Kanał Logów', value=ch_name(cfg.get('log_channel_id')), inline=True)
        embed.add_field(name='💰 Pkt/godz', value=f'{cfg.get("points_per_hour", 10):.1f}', inline=True)
        embed.add_field(name='⏱️ Min. czas (min)', value=str(cfg.get('min_clock_minutes', 5)), inline=True)

        try:
            role_ids = json.loads(cfg.get('admin_role_ids', '[]'))
        except Exception:
            role_ids = []
        role_str = ', '.join(
            (msg.guild.get_role(rid).mention if msg.guild.get_role(rid) else str(rid))
            for rid in role_ids
        ) or 'Tylko Discord Admini'
        embed.add_field(name='🔑 Role admina', value=role_str, inline=False)

        embed.add_field(
            name='📌 Komendy konfiguracyjne',
            value=(
                '`.setchannel clock #kanał` – kanał codziennego apelu\n'
                '`.setchannel log #kanał` – kanał logów\n'
                '`.setpoints_h <n>` – punkty za godzinę\n'
                '`.adminrole @rola` – dodaj rolę admina bota\n'
                '`.removeadminrole @rola` – usuń rolę admina bota\n'
                '`.apel` – wyślij apel ręcznie na bieżący kanał'
            ),
            inline=False
        )
        await msg.reply(embed=embed, mention_author=False)


async def setup(bot: commands.Bot):
    await bot.add_cog(AdminCog(bot))

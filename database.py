import sqlite3
import threading
import json
from datetime import datetime, date, timedelta
from typing import Optional, List, Dict, Any

DATABASE_FILE = 'data/bot.db'
_lock = threading.Lock()

# ─── Default embed schedule (every day at 00:00) ─────────────────────────────
DEFAULT_SCHEDULE = json.dumps({
    str(i): {"hour": 0, "minute": 0, "enabled": True} for i in range(7)
})

DAYS_PL = ["Poniedziałek", "Wtorek", "Środa", "Czwartek", "Piątek", "Sobota", "Niedziela"]


def init_db():
    import os
    os.makedirs('data', exist_ok=True)
    with _get_conn() as conn:
        conn.executescript(f'''
            PRAGMA journal_mode=WAL;
            PRAGMA foreign_keys=ON;

            CREATE TABLE IF NOT EXISTS guilds (
                guild_id                  INTEGER PRIMARY KEY,
                clock_channel_id          INTEGER DEFAULT NULL,
                log_channel_id            INTEGER DEFAULT NULL,
                command_panel_channel_id  INTEGER DEFAULT NULL,
                admin_role_ids            TEXT    DEFAULT '[]',
                owner_id                  INTEGER DEFAULT NULL,
                points_per_hour           REAL    DEFAULT 10.0,
                min_clock_minutes         INTEGER DEFAULT 5,
                auto_clockout_hours       INTEGER DEFAULT 12,
                warn_limit                INTEGER DEFAULT 3,
                streak_bonus_pct          REAL    DEFAULT 5.0,
                dm_notifications          INTEGER DEFAULT 1,
                clock_cooldown_min        INTEGER DEFAULT 0,
                embed_schedule            TEXT    DEFAULT '{DEFAULT_SCHEDULE}',
                created_at                TEXT    DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS users (
                user_id        INTEGER,
                guild_id       INTEGER,
                username       TEXT    DEFAULT '',
                display_name   TEXT    DEFAULT '',
                points         REAL    DEFAULT 0,
                total_hours    REAL    DEFAULT 0,
                sessions_count INTEGER DEFAULT 0,
                is_banned      INTEGER DEFAULT 0,
                is_clocked_in  INTEGER DEFAULT 0,
                clock_in_time  TEXT    DEFAULT NULL,
                streak_days    INTEGER DEFAULT 0,
                last_active_date TEXT  DEFAULT NULL,
                admin_notes    TEXT    DEFAULT '',
                created_at     TEXT    DEFAULT (datetime('now')),
                updated_at     TEXT    DEFAULT (datetime('now')),
                PRIMARY KEY (user_id, guild_id)
            );

            CREATE TABLE IF NOT EXISTS ranks (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id         INTEGER NOT NULL,
                name             TEXT    NOT NULL,
                required_points  REAL    DEFAULT 0,
                role_id          INTEGER DEFAULT NULL,
                color            TEXT    DEFAULT '#7289da',
                description      TEXT    DEFAULT '',
                icon             TEXT    DEFAULT '⭐',
                is_special       INTEGER DEFAULT 0,
                is_owner_only    INTEGER DEFAULT 0,
                grant_role_ids   TEXT    DEFAULT '[]',
                display_order    INTEGER DEFAULT 0,
                created_at       TEXT    DEFAULT (datetime('now')),
                UNIQUE(guild_id, name)
            );

            CREATE TABLE IF NOT EXISTS user_special_ranks (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL,
                guild_id    INTEGER NOT NULL,
                rank_id     INTEGER NOT NULL,
                assigned_by INTEGER NOT NULL,
                note        TEXT    DEFAULT '',
                assigned_at TEXT    DEFAULT (datetime('now')),
                FOREIGN KEY (rank_id) REFERENCES ranks(id) ON DELETE CASCADE,
                UNIQUE(user_id, guild_id, rank_id)
            );

            CREATE TABLE IF NOT EXISTS clock_sessions (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id        INTEGER NOT NULL,
                guild_id       INTEGER NOT NULL,
                clock_in_time  TEXT    NOT NULL,
                clock_out_time TEXT    DEFAULT NULL,
                hours_worked   REAL    DEFAULT 0,
                points_earned  REAL    DEFAULT 0,
                session_date   TEXT    NOT NULL,
                flagged        INTEGER DEFAULT 0,
                created_at     TEXT    DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS point_transactions (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id          INTEGER NOT NULL,
                guild_id         INTEGER NOT NULL,
                points_change    REAL    NOT NULL,
                points_before    REAL    NOT NULL,
                points_after     REAL    NOT NULL,
                transaction_type TEXT    NOT NULL,
                note             TEXT    DEFAULT '',
                assigned_by      INTEGER DEFAULT NULL,
                reference_id     INTEGER DEFAULT NULL,
                created_at       TEXT    DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS daily_embeds (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id   INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                embed_date TEXT    NOT NULL,
                created_at TEXT    DEFAULT (datetime('now')),
                UNIQUE(guild_id, embed_date)
            );

            CREATE TABLE IF NOT EXISTS warnings (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    INTEGER NOT NULL,
                guild_id   INTEGER NOT NULL,
                reason     TEXT    DEFAULT '',
                warned_by  INTEGER DEFAULT NULL,
                is_auto    INTEGER DEFAULT 0,
                created_at TEXT    DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS command_permissions (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id         INTEGER NOT NULL,
                command_name     TEXT    NOT NULL,
                allowed_role_ids TEXT    DEFAULT '[]',
                UNIQUE(guild_id, command_name)
            );

            CREATE TABLE IF NOT EXISTS announcements (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id     INTEGER NOT NULL,
                channel_id   INTEGER NOT NULL,
                title        TEXT    DEFAULT '',
                content      TEXT    NOT NULL,
                is_embed     INTEGER DEFAULT 1,
                color        TEXT    DEFAULT '#7289da',
                sent_by      TEXT    DEFAULT 'Dashboard',
                message_id   INTEGER DEFAULT NULL,
                scheduled_at TEXT    DEFAULT NULL,
                is_sent      INTEGER DEFAULT 1,
                created_at   TEXT    DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS action_logs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id    INTEGER NOT NULL,
                user_id     INTEGER DEFAULT NULL,
                actor_id    INTEGER DEFAULT NULL,
                action_type TEXT    NOT NULL,
                details     TEXT    DEFAULT '{{}}',
                created_at  TEXT    DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS panel_embeds (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id   INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                panel_type TEXT    DEFAULT 'user',
                created_at TEXT    DEFAULT (datetime('now')),
                UNIQUE(guild_id, panel_type)
            );

            CREATE TABLE IF NOT EXISTS rank_history (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    INTEGER NOT NULL,
                guild_id   INTEGER NOT NULL,
                rank_id    INTEGER DEFAULT NULL,
                rank_name  TEXT    NOT NULL,
                action     TEXT    NOT NULL,
                points_at  REAL    DEFAULT 0,
                created_at TEXT    DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS factions (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id    INTEGER NOT NULL,
                name        TEXT    NOT NULL,
                icon        TEXT    DEFAULT '⚔️',
                color       TEXT    DEFAULT '#7289da',
                role_ids    TEXT    DEFAULT '[]',
                description TEXT    DEFAULT '',
                created_at  TEXT    DEFAULT (datetime('now')),
                UNIQUE(guild_id, name)
            );

            CREATE TABLE IF NOT EXISTS faction_members (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL,
                guild_id    INTEGER NOT NULL,
                faction_id  INTEGER NOT NULL,
                assigned_by INTEGER DEFAULT NULL,
                assigned_at TEXT    DEFAULT (datetime('now')),
                UNIQUE(user_id, guild_id)
            );

            CREATE TABLE IF NOT EXISTS jobs (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id         INTEGER NOT NULL,
                name             TEXT    NOT NULL,
                required_points  REAL    DEFAULT 0,
                icon             TEXT    DEFAULT '💼',
                color            TEXT    DEFAULT '#7289da',
                description      TEXT    DEFAULT '',
                role_id          INTEGER DEFAULT NULL,
                display_order    INTEGER DEFAULT 0,
                created_at       TEXT    DEFAULT (datetime('now')),
                UNIQUE(guild_id, name)
            );

            CREATE TABLE IF NOT EXISTS user_jobs (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id       INTEGER NOT NULL,
                guild_id      INTEGER NOT NULL,
                job_id        INTEGER NOT NULL,
                admin_granted INTEGER DEFAULT 0,
                granted_by    INTEGER DEFAULT NULL,
                selected_at   TEXT    DEFAULT (datetime('now')),
                UNIQUE(user_id, guild_id, job_id)
            );
        ''')
        conn.commit()
        _run_migrations(conn)


def _run_migrations(conn):
    """Safely add new columns to existing databases."""
    migrations = [
        "ALTER TABLE guilds ADD COLUMN embed_schedule TEXT DEFAULT '{}'",
        "ALTER TABLE guilds ADD COLUMN command_panel_channel_id INTEGER DEFAULT NULL",
        "ALTER TABLE guilds ADD COLUMN warn_limit INTEGER DEFAULT 3",
        "ALTER TABLE guilds ADD COLUMN auto_clockout_hours INTEGER DEFAULT 12",
        "ALTER TABLE guilds ADD COLUMN owner_id INTEGER DEFAULT NULL",
        "ALTER TABLE guilds ADD COLUMN streak_bonus_pct REAL DEFAULT 5.0",
        "ALTER TABLE guilds ADD COLUMN dm_notifications INTEGER DEFAULT 1",
        "ALTER TABLE guilds ADD COLUMN clock_cooldown_min INTEGER DEFAULT 0",
        "ALTER TABLE ranks ADD COLUMN is_owner_only INTEGER DEFAULT 0",
        "ALTER TABLE ranks ADD COLUMN grant_role_ids TEXT DEFAULT '[]'",
        "ALTER TABLE clock_sessions ADD COLUMN flagged INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN streak_days INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN last_active_date TEXT DEFAULT NULL",
        "ALTER TABLE users ADD COLUMN admin_notes TEXT DEFAULT ''",
        "ALTER TABLE announcements ADD COLUMN scheduled_at TEXT DEFAULT NULL",
        "ALTER TABLE announcements ADD COLUMN is_sent INTEGER DEFAULT 1",
        "ALTER TABLE daily_embeds ADD COLUMN host_id INTEGER DEFAULT NULL",
        "ALTER TABLE daily_embeds ADD COLUMN co_host_id INTEGER DEFAULT NULL",
        "ALTER TABLE daily_embeds ADD COLUMN event_type TEXT DEFAULT 'Zmiana'",
        "ALTER TABLE daily_embeds ADD COLUMN is_finished INTEGER DEFAULT 0",
        "ALTER TABLE daily_embeds ADD COLUMN finished_at TEXT DEFAULT NULL",
        "ALTER TABLE ranks ADD COLUMN category TEXT DEFAULT ''",
        "ALTER TABLE ranks ADD COLUMN faction_id INTEGER DEFAULT NULL",
        """CREATE TABLE IF NOT EXISTS faction_members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL, guild_id INTEGER NOT NULL,
            faction_id INTEGER NOT NULL, assigned_by INTEGER DEFAULT NULL,
            assigned_at TEXT DEFAULT (datetime('now')),
            UNIQUE(user_id, guild_id))""",
        "ALTER TABLE guilds ADD COLUMN job_channel_id INTEGER DEFAULT NULL",
        """CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL, name TEXT NOT NULL,
            required_points REAL DEFAULT 0, icon TEXT DEFAULT '💼',
            color TEXT DEFAULT '#7289da', description TEXT DEFAULT '',
            role_id INTEGER DEFAULT NULL, display_order INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            UNIQUE(guild_id, name))""",
        """CREATE TABLE IF NOT EXISTS user_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL, guild_id INTEGER NOT NULL,
            job_id INTEGER NOT NULL, admin_granted INTEGER DEFAULT 0,
            granted_by INTEGER DEFAULT NULL,
            selected_at TEXT DEFAULT (datetime('now')),
            UNIQUE(user_id, guild_id, job_id))""",
        "ALTER TABLE jobs ADD COLUMN points_bonus_per_hour REAL DEFAULT 0",
        "ALTER TABLE guilds ADD COLUMN regulamin_channel_id INTEGER DEFAULT NULL",
        "ALTER TABLE guilds ADD COLUMN regulamin_message_ids TEXT DEFAULT '[]'",
        "ALTER TABLE guilds ADD COLUMN regulamin_file_hash TEXT DEFAULT NULL",
        "ALTER TABLE guilds ADD COLUMN auto_balance_jobs INTEGER DEFAULT 0",
        """CREATE TABLE IF NOT EXISTS devices (
            device_id      TEXT PRIMARY KEY,
            guild_id       INTEGER NOT NULL,
            user_id        INTEGER DEFAULT NULL,
            name           TEXT    NOT NULL DEFAULT '',
            bot_token      TEXT    DEFAULT '',
            api_secret     TEXT    DEFAULT '',
            status         TEXT    DEFAULT 'offline',
            last_heartbeat TEXT    DEFAULT NULL,
            created_at     TEXT    DEFAULT (datetime('now')))""",
        "ALTER TABLE devices ADD COLUMN current_channel_id INTEGER DEFAULT NULL",
        """CREATE TABLE IF NOT EXISTS channels (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id           INTEGER NOT NULL,
            name               TEXT    NOT NULL,
            discord_channel_id INTEGER DEFAULT NULL,
            bot_id             TEXT    DEFAULT NULL,
            order_index        INTEGER DEFAULT 0,
            is_radio_bridge    INTEGER DEFAULT 0,
            created_at         TEXT    DEFAULT (datetime('now')))""",
        # Economy & warn points
        "ALTER TABLE users ADD COLUMN warn_points REAL DEFAULT 0",
        "ALTER TABLE users ADD COLUMN cash REAL DEFAULT 0",
        "ALTER TABLE users ADD COLUMN bank REAL DEFAULT 0",
        "ALTER TABLE users ADD COLUMN rep_points INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN daily_last TEXT DEFAULT NULL",
        "ALTER TABLE users ADD COLUMN work_last TEXT DEFAULT NULL",
        "ALTER TABLE users ADD COLUMN beg_last TEXT DEFAULT NULL",
        "ALTER TABLE users ADD COLUMN rep_last TEXT DEFAULT NULL",
        """CREATE TABLE IF NOT EXISTS notes (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL,
            guild_id   INTEGER NOT NULL,
            content    TEXT    NOT NULL,
            author_id  INTEGER DEFAULT NULL,
            created_at TEXT    DEFAULT (datetime('now')))""",
    ]
    for m in migrations:
        try:
            conn.execute(m)
        except Exception:
            pass
    conn.commit()


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DATABASE_FILE, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# ─── Guild ────────────────────────────────────────────────────────────────────

def get_guild(guild_id: int) -> Optional[Dict]:
    with _get_conn() as conn:
        row = conn.execute('SELECT * FROM guilds WHERE guild_id=?', (guild_id,)).fetchone()
        return dict(row) if row else None


def ensure_guild(guild_id: int) -> Dict:
    with _lock:
        with _get_conn() as conn:
            conn.execute('INSERT OR IGNORE INTO guilds (guild_id, embed_schedule) VALUES (?,?)',
                         (guild_id, DEFAULT_SCHEDULE))
            conn.commit()
    return get_guild(guild_id)


def update_guild(guild_id: int, **kwargs) -> None:
    if not kwargs:
        return
    set_clause = ', '.join(f'{k}=?' for k in kwargs)
    with _lock:
        with _get_conn() as conn:
            conn.execute(f'UPDATE guilds SET {set_clause} WHERE guild_id=?',
                         list(kwargs.values()) + [guild_id])
            conn.commit()


def get_all_guilds() -> List[Dict]:
    with _get_conn() as conn:
        return [dict(r) for r in conn.execute('SELECT * FROM guilds').fetchall()]


def get_embed_schedule(guild_id: int) -> Dict:
    cfg = get_guild(guild_id)
    if not cfg:
        return {}
    raw = cfg.get('embed_schedule') or DEFAULT_SCHEDULE
    try:
        return json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        return {}


def set_embed_schedule(guild_id: int, schedule: Dict) -> None:
    update_guild(guild_id, embed_schedule=json.dumps(schedule))


# ─── User ─────────────────────────────────────────────────────────────────────

def get_user(user_id: int, guild_id: int) -> Optional[Dict]:
    with _get_conn() as conn:
        row = conn.execute('SELECT * FROM users WHERE user_id=? AND guild_id=?',
                           (user_id, guild_id)).fetchone()
        return dict(row) if row else None


def ensure_user(user_id: int, guild_id: int, username: str = '',
                display_name: str = '') -> Dict:
    with _lock:
        with _get_conn() as conn:
            conn.execute(
                'INSERT OR IGNORE INTO users (user_id,guild_id,username,display_name) VALUES (?,?,?,?)',
                (user_id, guild_id, username, display_name)
            )
            if username or display_name:
                conn.execute(
                    'UPDATE users SET username=?,display_name=?,updated_at=? WHERE user_id=? AND guild_id=?',
                    (username, display_name, datetime.now().isoformat(), user_id, guild_id)
                )
            conn.commit()
    return get_user(user_id, guild_id)


def update_user(user_id: int, guild_id: int, **kwargs) -> None:
    if not kwargs:
        return
    kwargs['updated_at'] = datetime.now().isoformat()
    set_clause = ', '.join(f'{k}=?' for k in kwargs)
    with _lock:
        with _get_conn() as conn:
            conn.execute(
                f'UPDATE users SET {set_clause} WHERE user_id=? AND guild_id=?',
                list(kwargs.values()) + [user_id, guild_id]
            )
            conn.commit()


def add_points(user_id: int, guild_id: int, delta: float, note: str = '',
               transaction_type: str = 'manual', assigned_by: int = None,
               reference_id: int = None) -> float:
    with _lock:
        with _get_conn() as conn:
            row = conn.execute('SELECT points FROM users WHERE user_id=? AND guild_id=?',
                               (user_id, guild_id)).fetchone()
            if not row:
                return 0.0
            before = row['points']
            after = max(0.0, before + delta)
            conn.execute(
                'UPDATE users SET points=?,updated_at=? WHERE user_id=? AND guild_id=?',
                (after, datetime.now().isoformat(), user_id, guild_id)
            )
            conn.execute(
                '''INSERT INTO point_transactions
                   (user_id,guild_id,points_change,points_before,points_after,
                    transaction_type,note,assigned_by,reference_id)
                   VALUES (?,?,?,?,?,?,?,?,?)''',
                (user_id, guild_id, delta, before, after,
                 transaction_type, note, assigned_by, reference_id)
            )
            conn.commit()
    return after


def set_points(user_id: int, guild_id: int, new_pts: float, note: str = '',
               assigned_by: int = None) -> float:
    u = get_user(user_id, guild_id)
    if not u:
        return 0.0
    return add_points(user_id, guild_id, new_pts - u['points'],
                      note=note, transaction_type='set', assigned_by=assigned_by)


def reset_user(user_id: int, guild_id: int) -> None:
    with _lock:
        with _get_conn() as conn:
            conn.execute(
                '''UPDATE users SET points=0,total_hours=0,sessions_count=0,
                   is_banned=0,is_clocked_in=0,clock_in_time=NULL,
                   streak_days=0,last_active_date=NULL,updated_at=?
                   WHERE user_id=? AND guild_id=?''',
                (datetime.now().isoformat(), user_id, guild_id)
            )
            conn.execute('DELETE FROM user_special_ranks WHERE user_id=? AND guild_id=?',
                         (user_id, guild_id))
            conn.execute('DELETE FROM warnings WHERE user_id=? AND guild_id=?',
                         (user_id, guild_id))
            conn.execute('DELETE FROM user_jobs WHERE user_id=? AND guild_id=?',
                         (user_id, guild_id))
            conn.execute('DELETE FROM faction_members WHERE user_id=? AND guild_id=?',
                         (user_id, guild_id))
            conn.commit()


def get_all_users(guild_id: int) -> List[Dict]:
    with _get_conn() as conn:
        return [dict(r) for r in conn.execute(
            'SELECT * FROM users WHERE guild_id=? ORDER BY points DESC', (guild_id,)
        ).fetchall()]


def get_leaderboard(guild_id: int, limit: int = 10,
                    include_banned: bool = False) -> List[Dict]:
    with _get_conn() as conn:
        q = 'SELECT * FROM users WHERE guild_id=?'
        if not include_banned:
            q += ' AND is_banned=0'
        q += ' ORDER BY points DESC LIMIT ?'
        return [dict(r) for r in conn.execute(q, (guild_id, limit)).fetchall()]


def update_user_notes(user_id: int, guild_id: int, notes: str) -> None:
    update_user(user_id, guild_id, admin_notes=notes)


# ─── Streak ───────────────────────────────────────────────────────────────────

def update_streak(user_id: int, guild_id: int, today: str) -> int:
    """Update consecutive-day streak on clock_out. Returns new streak count."""
    u = get_user(user_id, guild_id)
    if not u:
        return 0
    last_date = u.get('last_active_date')
    current_streak = u.get('streak_days', 0) or 0
    try:
        today_d = date.fromisoformat(today)
        if last_date:
            last_d = date.fromisoformat(last_date)
            diff = (today_d - last_d).days
            if diff == 0:
                new_streak = max(current_streak, 1)   # Same day – keep current
            elif diff == 1:
                new_streak = current_streak + 1        # Consecutive day – extend
            else:
                new_streak = 1                         # Gap – reset
        else:
            new_streak = 1
    except Exception:
        new_streak = 1
    update_user(user_id, guild_id, streak_days=new_streak, last_active_date=today)
    return new_streak


# ─── Ranks ────────────────────────────────────────────────────────────────────

def get_ranks(guild_id: int, special_only=False, auto_only=False) -> List[Dict]:
    with _get_conn() as conn:
        q = 'SELECT * FROM ranks WHERE guild_id=?'
        if special_only:
            q += ' AND is_special=1'
        if auto_only:
            q += ' AND is_special=0'
        q += ' ORDER BY is_owner_only DESC, is_special ASC, required_points ASC'
        return [dict(r) for r in conn.execute(q, (guild_id,)).fetchall()]


def get_rank_by_id(rank_id: int) -> Optional[Dict]:
    with _get_conn() as conn:
        row = conn.execute('SELECT * FROM ranks WHERE id=?', (rank_id,)).fetchone()
        return dict(row) if row else None


def get_rank_by_name(guild_id: int, name: str) -> Optional[Dict]:
    with _get_conn() as conn:
        row = conn.execute(
            'SELECT * FROM ranks WHERE guild_id=? AND name=? COLLATE NOCASE',
            (guild_id, name)
        ).fetchone()
        return dict(row) if row else None


def create_rank(guild_id: int, name: str, required_points: float = 0,
                role_id: int = None, color: str = '#7289da',
                description: str = '', icon: str = '⭐',
                is_special: bool = False, is_owner_only: bool = False,
                grant_role_ids: list = None,
                display_order: int = 0,
                category: str = '',
                faction_id: int = None) -> Optional[Dict]:
    with _lock:
        with _get_conn() as conn:
            try:
                cur = conn.execute(
                    '''INSERT INTO ranks
                       (guild_id,name,required_points,role_id,color,description,icon,
                        is_special,is_owner_only,grant_role_ids,display_order,category,faction_id)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                    (guild_id, name, required_points, role_id, color, description, icon,
                     1 if is_special else 0, 1 if is_owner_only else 0,
                     json.dumps(grant_role_ids or []), display_order, category, faction_id)
                )
                conn.commit()
                return get_rank_by_id(cur.lastrowid)
            except sqlite3.IntegrityError:
                return None


def update_rank(rank_id: int, **kwargs) -> None:
    if not kwargs:
        return
    set_clause = ', '.join(f'{k}=?' for k in kwargs)
    with _lock:
        with _get_conn() as conn:
            conn.execute(f'UPDATE ranks SET {set_clause} WHERE id=?',
                         list(kwargs.values()) + [rank_id])
            conn.commit()


def delete_rank(rank_id: int) -> None:
    with _lock:
        with _get_conn() as conn:
            conn.execute('DELETE FROM user_special_ranks WHERE rank_id=?', (rank_id,))
            conn.execute('DELETE FROM ranks WHERE id=?', (rank_id,))
            conn.commit()


def get_user_auto_rank(user_id: int, guild_id: int,
                        points_override: float = None) -> Optional[Dict]:
    """Faction-aware: returns the highest rank the user qualifies for in their faction
    (or civilian ranks if not in any faction)."""
    u = get_user(user_id, guild_id)
    if not u:
        return None
    pts = points_override if points_override is not None else u['points']
    fm  = get_user_faction_membership(user_id, guild_id)
    fid = fm['faction_id'] if fm else None
    with _get_conn() as conn:
        if fid is not None:
            row = conn.execute(
                '''SELECT * FROM ranks WHERE guild_id=? AND faction_id=?
                   AND is_special=0 AND is_owner_only=0 AND required_points<=?
                   ORDER BY required_points DESC LIMIT 1''',
                (guild_id, fid, pts)
            ).fetchone()
        else:
            row = conn.execute(
                '''SELECT * FROM ranks WHERE guild_id=? AND (faction_id IS NULL OR faction_id=0)
                   AND is_special=0 AND is_owner_only=0 AND required_points<=?
                   ORDER BY required_points DESC LIMIT 1''',
                (guild_id, pts)
            ).fetchone()
        return dict(row) if row else None


def get_user_next_rank(user_id: int, guild_id: int) -> Optional[Dict]:
    """Returns the next rank the user can earn (faction-aware)."""
    u = get_user(user_id, guild_id)
    if not u:
        return None
    fm  = get_user_faction_membership(user_id, guild_id)
    fid = fm['faction_id'] if fm else None
    with _get_conn() as conn:
        if fid is not None:
            row = conn.execute(
                '''SELECT * FROM ranks WHERE guild_id=? AND faction_id=?
                   AND is_special=0 AND is_owner_only=0 AND required_points>?
                   ORDER BY required_points ASC LIMIT 1''',
                (guild_id, fid, u['points'])
            ).fetchone()
        else:
            row = conn.execute(
                '''SELECT * FROM ranks WHERE guild_id=? AND (faction_id IS NULL OR faction_id=0)
                   AND is_special=0 AND is_owner_only=0 AND required_points>?
                   ORDER BY required_points ASC LIMIT 1''',
                (guild_id, u['points'])
            ).fetchone()
        return dict(row) if row else None


def get_user_special_ranks(user_id: int, guild_id: int) -> List[Dict]:
    with _get_conn() as conn:
        return [dict(r) for r in conn.execute(
            '''SELECT r.*, usr.assigned_by, usr.note, usr.assigned_at as given_at
               FROM user_special_ranks usr
               JOIN ranks r ON usr.rank_id=r.id
               WHERE usr.user_id=? AND usr.guild_id=?
               ORDER BY usr.assigned_at DESC''',
            (user_id, guild_id)
        ).fetchall()]


def give_special_rank(user_id: int, guild_id: int, rank_id: int,
                      assigned_by: int, note: str = '') -> bool:
    with _lock:
        with _get_conn() as conn:
            try:
                conn.execute(
                    'INSERT OR IGNORE INTO user_special_ranks (user_id,guild_id,rank_id,assigned_by,note) VALUES (?,?,?,?,?)',
                    (user_id, guild_id, rank_id, assigned_by, note)
                )
                conn.commit()
                return conn.execute(
                    'SELECT id FROM user_special_ranks WHERE user_id=? AND guild_id=? AND rank_id=?',
                    (user_id, guild_id, rank_id)
                ).fetchone() is not None
            except Exception:
                return False


def remove_special_rank(user_id: int, guild_id: int, rank_id: int) -> bool:
    with _lock:
        with _get_conn() as conn:
            cur = conn.execute(
                'DELETE FROM user_special_ranks WHERE user_id=? AND guild_id=? AND rank_id=?',
                (user_id, guild_id, rank_id)
            )
            conn.commit()
            return cur.rowcount > 0


# ─── Rank History ─────────────────────────────────────────────────────────────

def add_rank_history(user_id: int, guild_id: int, rank_name: str,
                     action: str, points_at: float, rank_id: int = None) -> None:
    with _lock:
        with _get_conn() as conn:
            conn.execute(
                'INSERT INTO rank_history (user_id,guild_id,rank_id,rank_name,action,points_at) VALUES (?,?,?,?,?,?)',
                (user_id, guild_id, rank_id, rank_name, action, points_at)
            )
            conn.commit()


def get_rank_history(user_id: int, guild_id: int, limit: int = 20) -> List[Dict]:
    with _get_conn() as conn:
        return [dict(r) for r in conn.execute(
            'SELECT * FROM rank_history WHERE user_id=? AND guild_id=? ORDER BY created_at DESC LIMIT ?',
            (user_id, guild_id, limit)
        ).fetchall()]


# ─── Clock ────────────────────────────────────────────────────────────────────

def get_last_session_end(user_id: int, guild_id: int) -> Optional[datetime]:
    """Returns datetime of last clock_out, or None."""
    with _get_conn() as conn:
        row = conn.execute(
            '''SELECT clock_out_time FROM clock_sessions
               WHERE user_id=? AND guild_id=? AND clock_out_time IS NOT NULL
               ORDER BY clock_out_time DESC LIMIT 1''',
            (user_id, guild_id)
        ).fetchone()
        if row and row['clock_out_time']:
            try:
                return datetime.fromisoformat(row['clock_out_time'])
            except Exception:
                pass
    return None


def clock_in(user_id: int, guild_id: int) -> Optional[Dict]:
    u = get_user(user_id, guild_id)
    if not u or u['is_clocked_in']:
        return None
    now = datetime.now().isoformat()
    today = date.today().isoformat()
    with _lock:
        with _get_conn() as conn:
            cur = conn.execute(
                'INSERT INTO clock_sessions (user_id,guild_id,clock_in_time,session_date) VALUES (?,?,?,?)',
                (user_id, guild_id, now, today)
            )
            conn.execute(
                'UPDATE users SET is_clocked_in=1,clock_in_time=?,updated_at=? WHERE user_id=? AND guild_id=?',
                (now, now, user_id, guild_id)
            )
            conn.commit()
            return dict(conn.execute('SELECT * FROM clock_sessions WHERE id=?',
                                     (cur.lastrowid,)).fetchone())


def clock_out(user_id: int, guild_id: int) -> Optional[Dict]:
    u = get_user(user_id, guild_id)
    if not u or not u['is_clocked_in'] or not u['clock_in_time']:
        return None
    cfg = get_guild(guild_id) or {}
    pph = cfg.get('points_per_hour', 10.0)
    min_min = cfg.get('min_clock_minutes', 5)
    ci_dt = datetime.fromisoformat(u['clock_in_time'])
    co_dt = datetime.now()
    secs = (co_dt - ci_dt).total_seconds()
    hours = secs / 3600
    mins = secs / 60

    # Sum job bonuses for this user
    job_bonus_pph = 0.0
    with _get_conn() as _c:
        rows = _c.execute(
            '''SELECT COALESCE(j.points_bonus_per_hour, 0) AS bonus
               FROM user_jobs uj
               JOIN jobs j ON uj.job_id = j.id
               WHERE uj.user_id=? AND uj.guild_id=?''',
            (user_id, guild_id)
        ).fetchall()
        job_bonus_pph = sum(r['bonus'] for r in rows)

    effective_pph = pph + job_bonus_pph
    pts = round(hours * effective_pph, 2) if mins >= min_min else 0.0
    base_pts = round(hours * pph, 2) if mins >= min_min else 0.0
    with _lock:
        with _get_conn() as conn:
            sess = conn.execute(
                '''SELECT id FROM clock_sessions
                   WHERE user_id=? AND guild_id=? AND clock_out_time IS NULL
                   ORDER BY clock_in_time DESC LIMIT 1''',
                (user_id, guild_id)
            ).fetchone()
            sess_id = sess['id'] if sess else None
            if sess_id:
                conn.execute(
                    'UPDATE clock_sessions SET clock_out_time=?,hours_worked=?,points_earned=? WHERE id=?',
                    (co_dt.isoformat(), round(hours, 4), pts, sess_id)
                )
            conn.execute(
                '''UPDATE users SET is_clocked_in=0,clock_in_time=NULL,
                   total_hours=total_hours+?,sessions_count=sessions_count+1,updated_at=?
                   WHERE user_id=? AND guild_id=?''',
                (round(hours, 4), co_dt.isoformat(), user_id, guild_id)
            )
            conn.commit()
    if pts > 0:
        note = f'Sesja {round(hours, 2)}h | {ci_dt.strftime("%H:%M")}→{co_dt.strftime("%H:%M")}'
        if job_bonus_pph > 0:
            note += f' | bonus pracy +{job_bonus_pph:.1f} pkt/h'
        add_points(user_id, guild_id, pts,
                   note=note,
                   transaction_type='clock', reference_id=sess_id)
    return {
        'hours': round(hours, 4), 'minutes': round(mins, 1),
        'points_earned': pts, 'base_pts': base_pts,
        'job_bonus_pph': job_bonus_pph, 'effective_pph': effective_pph,
        'clock_in_time': ci_dt, 'clock_out_time': co_dt,
        'session_id': sess_id, 'enough_time': mins >= min_min,
    }


def force_clock_out(user_id: int, guild_id: int) -> bool:
    u = get_user(user_id, guild_id)
    if not u or not u['is_clocked_in']:
        return False
    now = datetime.now().isoformat()
    with _lock:
        with _get_conn() as conn:
            conn.execute(
                'UPDATE clock_sessions SET clock_out_time=?,flagged=1 WHERE user_id=? AND guild_id=? AND clock_out_time IS NULL',
                (now, user_id, guild_id)
            )
            conn.execute(
                'UPDATE users SET is_clocked_in=0,clock_in_time=NULL,updated_at=? WHERE user_id=? AND guild_id=?',
                (now, user_id, guild_id)
            )
            conn.commit()
    return True


def get_suspicious_users(guild_id: int, max_hours: int) -> List[Dict]:
    """Users who have been clocked in for longer than max_hours."""
    with _get_conn() as conn:
        rows = conn.execute(
            'SELECT * FROM users WHERE guild_id=? AND is_clocked_in=1 AND clock_in_time IS NOT NULL',
            (guild_id,)
        ).fetchall()
    result = []
    now = datetime.now()
    for r in rows:
        try:
            ci = datetime.fromisoformat(r['clock_in_time'])
            if (now - ci).total_seconds() / 3600 >= max_hours:
                result.append(dict(r))
        except Exception:
            pass
    return result


def get_user_sessions(user_id: int, guild_id: int, limit: int = 10) -> List[Dict]:
    with _get_conn() as conn:
        return [dict(r) for r in conn.execute(
            'SELECT * FROM clock_sessions WHERE user_id=? AND guild_id=? ORDER BY clock_in_time DESC LIMIT ?',
            (user_id, guild_id, limit)
        ).fetchall()]


def get_user_transactions(user_id: int, guild_id: int, limit: int = 20) -> List[Dict]:
    with _get_conn() as conn:
        return [dict(r) for r in conn.execute(
            'SELECT * FROM point_transactions WHERE user_id=? AND guild_id=? ORDER BY created_at DESC LIMIT ?',
            (user_id, guild_id, limit)
        ).fetchall()]


def get_all_sessions(guild_id: int, limit: int = 50) -> List[Dict]:
    with _get_conn() as conn:
        return [dict(r) for r in conn.execute(
            'SELECT * FROM clock_sessions WHERE guild_id=? ORDER BY clock_in_time DESC LIMIT ?',
            (guild_id, limit)
        ).fetchall()]


def get_all_transactions(guild_id: int, limit: int = 50) -> List[Dict]:
    with _get_conn() as conn:
        return [dict(r) for r in conn.execute(
            'SELECT * FROM point_transactions WHERE guild_id=? ORDER BY created_at DESC LIMIT ?',
            (guild_id, limit)
        ).fetchall()]


# ─── Warnings ─────────────────────────────────────────────────────────────────

def add_warning(user_id: int, guild_id: int, reason: str = '',
                warned_by: int = None, is_auto: bool = False) -> int:
    with _lock:
        with _get_conn() as conn:
            cur = conn.execute(
                'INSERT INTO warnings (user_id,guild_id,reason,warned_by,is_auto) VALUES (?,?,?,?,?)',
                (user_id, guild_id, reason, warned_by, 1 if is_auto else 0)
            )
            conn.commit()
            return cur.lastrowid


def get_warnings(user_id: int, guild_id: int) -> List[Dict]:
    with _get_conn() as conn:
        return [dict(r) for r in conn.execute(
            'SELECT * FROM warnings WHERE user_id=? AND guild_id=? ORDER BY created_at DESC',
            (user_id, guild_id)
        ).fetchall()]


def get_warning_count(user_id: int, guild_id: int) -> int:
    with _get_conn() as conn:
        r = conn.execute(
            'SELECT COUNT(*) as c FROM warnings WHERE user_id=? AND guild_id=?',
            (user_id, guild_id)
        ).fetchone()
        return r['c'] if r else 0


def clear_warnings(user_id: int, guild_id: int, warn_id: int = None) -> int:
    with _lock:
        with _get_conn() as conn:
            if warn_id:
                cur = conn.execute(
                    'DELETE FROM warnings WHERE id=? AND user_id=? AND guild_id=?',
                    (warn_id, user_id, guild_id)
                )
            else:
                cur = conn.execute(
                    'DELETE FROM warnings WHERE user_id=? AND guild_id=?',
                    (user_id, guild_id)
                )
            conn.commit()
            return cur.rowcount


def get_all_warnings(guild_id: int, limit: int = 50) -> List[Dict]:
    with _get_conn() as conn:
        return [dict(r) for r in conn.execute(
            'SELECT * FROM warnings WHERE guild_id=? ORDER BY created_at DESC LIMIT ?',
            (guild_id, limit)
        ).fetchall()]


# ─── Command permissions ──────────────────────────────────────────────────────

def get_command_permission(guild_id: int, command_name: str) -> Optional[Dict]:
    with _get_conn() as conn:
        row = conn.execute(
            'SELECT * FROM command_permissions WHERE guild_id=? AND command_name=?',
            (guild_id, command_name)
        ).fetchone()
        return dict(row) if row else None


def set_command_permission(guild_id: int, command_name: str,
                           allowed_role_ids: List[int]) -> None:
    with _lock:
        with _get_conn() as conn:
            conn.execute(
                '''INSERT INTO command_permissions (guild_id,command_name,allowed_role_ids)
                   VALUES (?,?,?) ON CONFLICT(guild_id,command_name)
                   DO UPDATE SET allowed_role_ids=excluded.allowed_role_ids''',
                (guild_id, command_name, json.dumps(allowed_role_ids))
            )
            conn.commit()


def get_all_command_permissions(guild_id: int) -> Dict[str, List[int]]:
    with _get_conn() as conn:
        rows = conn.execute(
            'SELECT * FROM command_permissions WHERE guild_id=?', (guild_id,)
        ).fetchall()
    result = {}
    for r in rows:
        try:
            result[r['command_name']] = json.loads(r['allowed_role_ids'])
        except Exception:
            result[r['command_name']] = []
    return result


# ─── Announcements ────────────────────────────────────────────────────────────

def save_announcement(guild_id: int, channel_id: int, title: str,
                      content: str, is_embed: bool, color: str,
                      sent_by: str, message_id: int = None,
                      scheduled_at: str = None) -> int:
    is_sent = 0 if scheduled_at else 1
    with _lock:
        with _get_conn() as conn:
            cur = conn.execute(
                '''INSERT INTO announcements
                   (guild_id,channel_id,title,content,is_embed,color,sent_by,
                    message_id,scheduled_at,is_sent)
                   VALUES (?,?,?,?,?,?,?,?,?,?)''',
                (guild_id, channel_id, title, content,
                 1 if is_embed else 0, color, sent_by,
                 message_id, scheduled_at, is_sent)
            )
            conn.commit()
            return cur.lastrowid


def get_announcements(guild_id: int, limit: int = 20) -> List[Dict]:
    with _get_conn() as conn:
        return [dict(r) for r in conn.execute(
            'SELECT * FROM announcements WHERE guild_id=? ORDER BY created_at DESC LIMIT ?',
            (guild_id, limit)
        ).fetchall()]


def get_due_announcements() -> List[Dict]:
    """Returns scheduled announcements that are due and not yet sent."""
    now = datetime.now().isoformat()
    with _get_conn() as conn:
        return [dict(r) for r in conn.execute(
            'SELECT * FROM announcements WHERE scheduled_at IS NOT NULL AND scheduled_at <= ? AND is_sent=0',
            (now,)
        ).fetchall()]


def mark_announcement_sent(ann_id: int, message_id: int = None) -> None:
    with _lock:
        with _get_conn() as conn:
            if message_id:
                conn.execute(
                    'UPDATE announcements SET is_sent=1, message_id=? WHERE id=?',
                    (message_id, ann_id)
                )
            else:
                conn.execute('UPDATE announcements SET is_sent=1 WHERE id=?', (ann_id,))
            conn.commit()


# ─── Action logs ──────────────────────────────────────────────────────────────

def log_action(guild_id: int, action_type: str,
               user_id: int = None, actor_id: int = None,
               details: dict = None) -> None:
    with _lock:
        with _get_conn() as conn:
            conn.execute(
                'INSERT INTO action_logs (guild_id,user_id,actor_id,action_type,details) VALUES (?,?,?,?,?)',
                (guild_id, user_id, actor_id, action_type,
                 json.dumps(details or {}))
            )
            conn.commit()


def get_action_logs(guild_id: int, limit: int = 100,
                    action_type: str = None) -> List[Dict]:
    with _get_conn() as conn:
        q = 'SELECT * FROM action_logs WHERE guild_id=?'
        params = [guild_id]
        if action_type:
            q += ' AND action_type=?'
            params.append(action_type)
        q += ' ORDER BY created_at DESC LIMIT ?'
        params.append(limit)
        return [dict(r) for r in conn.execute(q, params).fetchall()]


# ─── Panel embeds ─────────────────────────────────────────────────────────────

def save_panel_embed(guild_id: int, channel_id: int,
                     message_id: int, panel_type: str) -> None:
    with _lock:
        with _get_conn() as conn:
            conn.execute(
                '''INSERT INTO panel_embeds (guild_id,channel_id,message_id,panel_type)
                   VALUES (?,?,?,?) ON CONFLICT(guild_id,panel_type)
                   DO UPDATE SET channel_id=excluded.channel_id,
                                 message_id=excluded.message_id''',
                (guild_id, channel_id, message_id, panel_type)
            )
            conn.commit()


def get_panel_embed(guild_id: int, panel_type: str) -> Optional[Dict]:
    with _get_conn() as conn:
        row = conn.execute(
            'SELECT * FROM panel_embeds WHERE guild_id=? AND panel_type=?',
            (guild_id, panel_type)
        ).fetchone()
        return dict(row) if row else None


# ─── Daily embeds ─────────────────────────────────────────────────────────────

def save_daily_embed(guild_id: int, channel_id: int,
                     message_id: int, embed_date: str) -> None:
    with _lock:
        with _get_conn() as conn:
            conn.execute(
                'INSERT OR REPLACE INTO daily_embeds (guild_id,channel_id,message_id,embed_date) VALUES (?,?,?,?)',
                (guild_id, channel_id, message_id, embed_date)
            )
            conn.commit()


def get_daily_embed(guild_id: int, embed_date: str) -> Optional[Dict]:
    with _get_conn() as conn:
        row = conn.execute(
            'SELECT * FROM daily_embeds WHERE guild_id=? AND embed_date=?',
            (guild_id, embed_date)
        ).fetchone()
        return dict(row) if row else None


def update_daily_embed_meta(guild_id: int, embed_date: str, **kwargs) -> None:
    """Update metadata columns (host_id, co_host_id, event_type, is_finished, etc.)"""
    if not kwargs:
        return
    set_clause = ', '.join(f'{k}=?' for k in kwargs)
    with _lock:
        with _get_conn() as conn:
            conn.execute(
                f'UPDATE daily_embeds SET {set_clause} WHERE guild_id=? AND embed_date=?',
                [*kwargs.values(), guild_id, embed_date]
            )
            conn.commit()


# ─── Factions ─────────────────────────────────────────────────────────────────

def get_factions(guild_id: int) -> List[Dict]:
    with _get_conn() as conn:
        rows = conn.execute(
            'SELECT * FROM factions WHERE guild_id=? ORDER BY name', (guild_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_faction_by_id(faction_id: int) -> Optional[Dict]:
    with _get_conn() as conn:
        row = conn.execute('SELECT * FROM factions WHERE id=?', (faction_id,)).fetchone()
        return dict(row) if row else None


def get_faction_by_name(guild_id: int, name: str) -> Optional[Dict]:
    with _get_conn() as conn:
        row = conn.execute(
            'SELECT * FROM factions WHERE guild_id=? AND LOWER(name)=LOWER(?)',
            (guild_id, name)
        ).fetchone()
        return dict(row) if row else None


def create_faction(guild_id: int, name: str, icon: str = '⚔️',
                   color: str = '#7289da', role_ids: list = None,
                   description: str = '') -> Optional[Dict]:
    import json as _json
    with _lock:
        with _get_conn() as conn:
            try:
                conn.execute(
                    'INSERT INTO factions (guild_id,name,icon,color,role_ids,description) VALUES (?,?,?,?,?,?)',
                    (guild_id, name, icon, color, _json.dumps(role_ids or []), description)
                )
                conn.commit()
            except Exception:
                return None
    return get_faction_by_name(guild_id, name)


def update_faction(faction_id: int, **kwargs) -> None:
    if not kwargs:
        return
    import json as _json
    if 'role_ids' in kwargs and isinstance(kwargs['role_ids'], list):
        kwargs['role_ids'] = _json.dumps(kwargs['role_ids'])
    set_clause = ', '.join(f'{k}=?' for k in kwargs)
    with _lock:
        with _get_conn() as conn:
            conn.execute(
                f'UPDATE factions SET {set_clause} WHERE id=?',
                [*kwargs.values(), faction_id]
            )
            conn.commit()


def delete_faction(faction_id: int) -> None:
    with _lock:
        with _get_conn() as conn:
            conn.execute('DELETE FROM factions WHERE id=?', (faction_id,))
            conn.commit()


def get_user_faction(guild_id: int, member_role_ids: List[int]) -> Optional[Dict]:
    """Legacy: return faction by Discord role_ids intersection (kept for compat)."""
    import json as _json
    factions = get_factions(guild_id)
    for f in factions:
        try:
            f_roles = _json.loads(f['role_ids'])
        except Exception:
            f_roles = []
        if any(rid in f_roles for rid in member_role_ids):
            return f
    return None


# ─── Faction membership (explicit, admin-assigned) ────────────────────────────

def get_user_faction_membership(user_id: int, guild_id: int) -> Optional[Dict]:
    """Returns faction membership record with faction details, or None."""
    with _get_conn() as conn:
        row = conn.execute(
            '''SELECT fm.*, f.name AS faction_name, f.icon AS faction_icon,
                      f.color AS faction_color, f.description AS faction_description
               FROM faction_members fm
               JOIN factions f ON fm.faction_id = f.id
               WHERE fm.user_id=? AND fm.guild_id=?''',
            (user_id, guild_id)
        ).fetchone()
        return dict(row) if row else None


def assign_faction_member(user_id: int, guild_id: int, faction_id: int,
                          assigned_by: int = None) -> bool:
    """Assign (or move) a user to a faction. Replaces existing membership."""
    with _lock:
        with _get_conn() as conn:
            try:
                conn.execute(
                    '''INSERT INTO faction_members (user_id, guild_id, faction_id, assigned_by)
                       VALUES (?,?,?,?)
                       ON CONFLICT(user_id, guild_id) DO UPDATE SET
                         faction_id=excluded.faction_id,
                         assigned_by=excluded.assigned_by,
                         assigned_at=datetime('now')''',
                    (user_id, guild_id, faction_id, assigned_by)
                )
                conn.commit()
                return True
            except Exception:
                return False


def remove_faction_member(user_id: int, guild_id: int) -> bool:
    """Remove a user from their faction. Returns True if they were in one."""
    with _lock:
        with _get_conn() as conn:
            cur = conn.execute(
                'DELETE FROM faction_members WHERE user_id=? AND guild_id=?',
                (user_id, guild_id)
            )
            conn.commit()
            return cur.rowcount > 0


def get_faction_members(guild_id: int, faction_id: int) -> List[Dict]:
    """Returns all users in a given faction with basic user data."""
    with _get_conn() as conn:
        return [dict(r) for r in conn.execute(
            '''SELECT fm.user_id, fm.assigned_at,
                      COALESCE(u.display_name, u.username, CAST(fm.user_id AS TEXT)) AS display_name,
                      u.points
               FROM faction_members fm
               LEFT JOIN users u ON fm.user_id=u.user_id AND u.guild_id=fm.guild_id
               WHERE fm.guild_id=? AND fm.faction_id=?
               ORDER BY COALESCE(u.points, 0) DESC''',
            (guild_id, faction_id)
        ).fetchall()]


# ─── Stats ────────────────────────────────────────────────────────────────────

def get_guild_stats(guild_id: int) -> Dict:
    with _get_conn() as conn:
        def sc(q, *a):
            r = conn.execute(q, a).fetchone()
            return list(r)[0] if r else 0
        return {
            'total_users':    sc('SELECT COUNT(*) FROM users WHERE guild_id=?', guild_id),
            'total_points':   sc('SELECT COALESCE(SUM(points),0) FROM users WHERE guild_id=?', guild_id),
            'total_sessions': sc('SELECT COUNT(*) FROM clock_sessions WHERE guild_id=?', guild_id),
            'total_hours':    round(sc('SELECT COALESCE(SUM(hours_worked),0) FROM clock_sessions WHERE guild_id=?', guild_id), 2),
            'active_now':     sc('SELECT COUNT(*) FROM users WHERE guild_id=? AND is_clocked_in=1', guild_id),
            'banned_count':   sc('SELECT COUNT(*) FROM users WHERE guild_id=? AND is_banned=1', guild_id),
            'rank_count':     sc('SELECT COUNT(*) FROM ranks WHERE guild_id=?', guild_id),
            'warning_count':  sc('SELECT COUNT(*) FROM warnings WHERE guild_id=?', guild_id),
        }


def get_daily_activity(guild_id: int, days: int = 14) -> List[Dict]:
    """Returns per-day stats for the last N days: date, total_points, active_users, sessions."""
    result = []
    today = date.today()
    with _get_conn() as conn:
        for i in range(days - 1, -1, -1):
            d = (today - timedelta(days=i)).isoformat()
            pts = conn.execute(
                '''SELECT COALESCE(SUM(points_change), 0) FROM point_transactions
                   WHERE guild_id=? AND transaction_type IN ('clock','streak_bonus')
                   AND date(created_at)=?''',
                (guild_id, d)
            ).fetchone()
            users = conn.execute(
                'SELECT COUNT(DISTINCT user_id) FROM clock_sessions WHERE guild_id=? AND session_date=?',
                (guild_id, d)
            ).fetchone()
            sessions = conn.execute(
                'SELECT COUNT(*) FROM clock_sessions WHERE guild_id=? AND session_date=?',
                (guild_id, d)
            ).fetchone()
            result.append({
                'date': d,
                'points': round(float(list(pts)[0] or 0), 1),
                'active_users': int(list(users)[0] or 0),
                'sessions': int(list(sessions)[0] or 0),
            })
    return result


# ─── Jobs ─────────────────────────────────────────────────────────────────────

def get_jobs(guild_id: int) -> List[Dict]:
    with _get_conn() as conn:
        return [dict(r) for r in conn.execute(
            'SELECT * FROM jobs WHERE guild_id=? ORDER BY required_points ASC, display_order ASC',
            (guild_id,)
        ).fetchall()]


def get_job_by_id(job_id: int) -> Optional[Dict]:
    with _get_conn() as conn:
        row = conn.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
        return dict(row) if row else None


def get_job_by_name(guild_id: int, name: str) -> Optional[Dict]:
    with _get_conn() as conn:
        row = conn.execute(
            'SELECT * FROM jobs WHERE guild_id=? AND LOWER(name)=LOWER(?)',
            (guild_id, name)
        ).fetchone()
        return dict(row) if row else None


def create_job(guild_id: int, name: str, required_points: float = 0,
               icon: str = '💼', color: str = '#7289da',
               description: str = '', role_id: int = None,
               display_order: int = 0,
               points_bonus_per_hour: float = 0) -> Optional[Dict]:
    with _lock:
        with _get_conn() as conn:
            try:
                cur = conn.execute(
                    '''INSERT INTO jobs
                       (guild_id,name,required_points,icon,color,description,
                        role_id,display_order,points_bonus_per_hour)
                       VALUES (?,?,?,?,?,?,?,?,?)''',
                    (guild_id, name, required_points, icon, color, description,
                     role_id, display_order, points_bonus_per_hour)
                )
                conn.commit()
                return get_job_by_id(cur.lastrowid)
            except Exception:
                return None


def update_job(job_id: int, **kwargs) -> None:
    if not kwargs:
        return
    set_clause = ', '.join(f'{k}=?' for k in kwargs)
    with _lock:
        with _get_conn() as conn:
            conn.execute(f'UPDATE jobs SET {set_clause} WHERE id=?',
                         list(kwargs.values()) + [job_id])
            conn.commit()


def delete_job(job_id: int) -> None:
    with _lock:
        with _get_conn() as conn:
            conn.execute('DELETE FROM user_jobs WHERE job_id=?', (job_id,))
            conn.execute('DELETE FROM jobs WHERE id=?', (job_id,))
            conn.commit()


def get_user_jobs(user_id: int, guild_id: int) -> List[Dict]:
    """Returns jobs the user has selected, with full job details."""
    with _get_conn() as conn:
        return [dict(r) for r in conn.execute(
            '''SELECT j.*, uj.admin_granted, uj.granted_by, uj.selected_at AS job_selected_at
               FROM user_jobs uj
               JOIN jobs j ON uj.job_id = j.id
               WHERE uj.user_id=? AND uj.guild_id=?
               ORDER BY j.required_points ASC''',
            (user_id, guild_id)
        ).fetchall()]


def get_available_jobs(user_id: int, guild_id: int) -> List[Dict]:
    """Returns jobs the user can select (points meet threshold, not yet selected)."""
    u = get_user(user_id, guild_id)
    if not u:
        return []
    pts = u['points']
    with _get_conn() as conn:
        return [dict(r) for r in conn.execute(
            '''SELECT j.* FROM jobs j
               WHERE j.guild_id=? AND j.required_points<=?
               AND j.id NOT IN (
                   SELECT job_id FROM user_jobs WHERE user_id=? AND guild_id=?
               )
               ORDER BY j.required_points ASC''',
            (guild_id, pts, user_id, guild_id)
        ).fetchall()]


def select_job(user_id: int, guild_id: int, job_id: int,
               admin_granted: bool = False, granted_by: int = None) -> bool:
    """Add a job to user's selected jobs. Returns True on success."""
    with _lock:
        with _get_conn() as conn:
            try:
                conn.execute(
                    '''INSERT OR IGNORE INTO user_jobs
                       (user_id, guild_id, job_id, admin_granted, granted_by)
                       VALUES (?,?,?,?,?)''',
                    (user_id, guild_id, job_id,
                     1 if admin_granted else 0, granted_by)
                )
                conn.commit()
                return True
            except Exception:
                return False


def deselect_job(user_id: int, guild_id: int, job_id: int) -> bool:
    """Remove a job from user's selected jobs. Returns True if it existed."""
    with _lock:
        with _get_conn() as conn:
            cur = conn.execute(
                'DELETE FROM user_jobs WHERE user_id=? AND guild_id=? AND job_id=?',
                (user_id, guild_id, job_id)
            )
            conn.commit()
            return cur.rowcount > 0


def deselect_all_jobs(user_id: int, guild_id: int) -> None:
    """Remove all jobs from a user (used on reset)."""
    with _lock:
        with _get_conn() as conn:
            conn.execute(
                'DELETE FROM user_jobs WHERE user_id=? AND guild_id=?',
                (user_id, guild_id)
            )
            conn.commit()


def get_job_members(guild_id: int, job_id: int) -> List[Dict]:
    """Returns all users who have selected this job, with basic user data."""
    with _get_conn() as conn:
        return [dict(r) for r in conn.execute(
            '''SELECT uj.user_id, uj.selected_at, uj.admin_granted,
                      COALESCE(u.display_name, u.username, CAST(uj.user_id AS TEXT)) AS display_name,
                      u.points
               FROM user_jobs uj
               LEFT JOIN users u ON uj.user_id=u.user_id AND u.guild_id=uj.guild_id
               WHERE uj.guild_id=? AND uj.job_id=?
               ORDER BY COALESCE(u.points, 0) DESC''',
            (guild_id, job_id)
        ).fetchall()]


# ─── Full Backup / Import ──────────────────────────────────────────────────────

def get_full_backup(guild_id: int) -> dict:
    """Return a complete snapshot of every table for this guild."""
    with _get_conn() as conn:
        def _all(table, where='guild_id=?'):
            return [dict(r) for r in
                    conn.execute(f'SELECT * FROM {table} WHERE {where}', (guild_id,)).fetchall()]

        return {
            'version':            '2.0',
            'guild_id':           guild_id,
            'exported_at':        datetime.now().isoformat(),
            'guild_config':       dict(conn.execute(
                                      'SELECT * FROM guilds WHERE guild_id=?', (guild_id,)
                                  ).fetchone() or {}),
            'users':              _all('users'),
            'ranks':              _all('ranks'),
            'factions':           _all('factions'),
            'jobs':               _all('jobs'),
            'warnings':           _all('warnings'),
            'user_special_ranks': _all('user_special_ranks'),
            'faction_members':    _all('faction_members'),
            'user_jobs':          _all('user_jobs'),
            'clock_sessions':     _all('clock_sessions'),
            'point_transactions': _all('point_transactions'),
        }


def bulk_import_sessions(guild_id: int, sessions: list) -> int:
    """INSERT OR IGNORE clock sessions from a backup. Returns count inserted."""
    inserted = 0
    with _lock:
        with _get_conn() as conn:
            for s in sessions:
                try:
                    conn.execute(
                        '''INSERT OR IGNORE INTO clock_sessions
                           (id, user_id, guild_id, clock_in_time, clock_out_time,
                            hours_worked, points_earned, session_date, flagged, created_at)
                           VALUES (?,?,?,?,?,?,?,?,?,?)''',
                        (s.get('id'), int(s['user_id']), guild_id,
                         s.get('clock_in_time'), s.get('clock_out_time'),
                         float(s.get('hours_worked', 0)), float(s.get('points_earned', 0)),
                         s.get('session_date', ''), int(s.get('flagged', 0)),
                         s.get('created_at'))
                    )
                    if conn.execute('SELECT changes()').fetchone()[0]:
                        inserted += 1
                except Exception:
                    pass
            conn.commit()
    return inserted


def bulk_import_transactions(guild_id: int, transactions: list) -> int:
    """INSERT OR IGNORE point_transactions from a backup. Returns count inserted."""
    inserted = 0
    with _lock:
        with _get_conn() as conn:
            for t in transactions:
                try:
                    conn.execute(
                        '''INSERT OR IGNORE INTO point_transactions
                           (id, user_id, guild_id, points_change, points_before, points_after,
                            transaction_type, note, assigned_by, reference_id, created_at)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
                        (t.get('id'), int(t['user_id']), guild_id,
                         float(t.get('points_change', 0)), float(t.get('points_before', 0)),
                         float(t.get('points_after', 0)), t.get('transaction_type', 'manual'),
                         t.get('note', ''), t.get('assigned_by'), t.get('reference_id'),
                         t.get('created_at'))
                    )
                    if conn.execute('SELECT changes()').fetchone()[0]:
                        inserted += 1
                except Exception:
                    pass
            conn.commit()
    return inserted


# ─── Devices (ESP32 physical devices) ────────────────────────────────────────

def get_devices(guild_id: int) -> List[Dict]:
    with _get_conn() as conn:
        return [dict(r) for r in conn.execute(
            'SELECT * FROM devices WHERE guild_id=? ORDER BY name',
            (guild_id,)
        ).fetchall()]


def get_all_devices() -> List[Dict]:
    with _get_conn() as conn:
        return [dict(r) for r in conn.execute(
            'SELECT * FROM devices ORDER BY guild_id, name'
        ).fetchall()]


def get_device(device_id: str) -> Optional[Dict]:
    with _get_conn() as conn:
        row = conn.execute('SELECT * FROM devices WHERE device_id=?', (device_id,)).fetchone()
        return dict(row) if row else None


def get_device_by_secret(api_secret: str) -> Optional[Dict]:
    with _get_conn() as conn:
        row = conn.execute('SELECT * FROM devices WHERE api_secret=?', (api_secret,)).fetchone()
        return dict(row) if row else None


def add_device(device_id: str, guild_id: int, name: str,
               bot_token: str = '', user_id: int = None) -> bool:
    import uuid
    secret = uuid.uuid4().hex
    with _lock:
        with _get_conn() as conn:
            try:
                conn.execute(
                    '''INSERT INTO devices (device_id, guild_id, user_id, name, bot_token, api_secret)
                       VALUES (?,?,?,?,?,?)''',
                    (device_id, guild_id, user_id, name, bot_token, secret)
                )
                conn.commit()
                return True
            except Exception:
                return False


def update_device(device_id: str, **kwargs) -> None:
    if not kwargs:
        return
    cols = ', '.join(f'{k}=?' for k in kwargs)
    vals = list(kwargs.values()) + [device_id]
    with _lock:
        with _get_conn() as conn:
            conn.execute(f'UPDATE devices SET {cols} WHERE device_id=?', vals)
            conn.commit()


def delete_device(device_id: str) -> None:
    with _lock:
        with _get_conn() as conn:
            conn.execute('DELETE FROM devices WHERE device_id=?', (device_id,))
            conn.commit()


def update_device_heartbeat(device_id: str) -> None:
    now = datetime.now().isoformat()
    with _lock:
        with _get_conn() as conn:
            conn.execute(
                "UPDATE devices SET last_heartbeat=?, status='online' WHERE device_id=?",
                (now, device_id)
            )
            conn.commit()


def set_device_status(device_id: str, status: str) -> None:
    with _lock:
        with _get_conn() as conn:
            conn.execute('UPDATE devices SET status=? WHERE device_id=?', (status, device_id))
            conn.commit()


# ─── Channels (audio channels for ESP32 PTT routing) ──────────────────────────

def get_channels(guild_id: int) -> List[Dict]:
    with _get_conn() as conn:
        return [dict(r) for r in conn.execute(
            'SELECT * FROM channels WHERE guild_id=? ORDER BY order_index, name',
            (guild_id,)
        ).fetchall()]


def get_channel(channel_id: int) -> Optional[Dict]:
    with _get_conn() as conn:
        row = conn.execute('SELECT * FROM channels WHERE id=?', (channel_id,)).fetchone()
        return dict(row) if row else None


def get_radio_bridge_channel(guild_id: int) -> Optional[Dict]:
    """Return the channel marked as radio bridge (physical walkie-talkie)."""
    with _get_conn() as conn:
        row = conn.execute(
            'SELECT * FROM channels WHERE guild_id=? AND is_radio_bridge=1 ORDER BY order_index LIMIT 1',
            (guild_id,)
        ).fetchone()
        return dict(row) if row else None


def create_channel(guild_id: int, name: str, discord_channel_id: int = None,
                   bot_id: str = None, order_index: int = 0,
                   is_radio_bridge: bool = False) -> Optional[Dict]:
    with _lock:
        with _get_conn() as conn:
            try:
                cur = conn.execute(
                    '''INSERT INTO channels (guild_id, name, discord_channel_id, bot_id,
                       order_index, is_radio_bridge)
                       VALUES (?,?,?,?,?,?)''',
                    (guild_id, name, discord_channel_id, bot_id, order_index,
                     1 if is_radio_bridge else 0)
                )
                conn.commit()
                return get_channel(cur.lastrowid)
            except Exception:
                return None


def update_channel(channel_id: int, **kwargs) -> None:
    if not kwargs:
        return
    cols = ', '.join(f'{k}=?' for k in kwargs)
    vals = list(kwargs.values()) + [channel_id]
    with _lock:
        with _get_conn() as conn:
            conn.execute(f'UPDATE channels SET {cols} WHERE id=?', vals)
            conn.commit()


def delete_channel(channel_id: int) -> None:
    with _lock:
        with _get_conn() as conn:
            conn.execute('DELETE FROM channels WHERE id=?', (channel_id,))
            conn.commit()


def get_next_channel(guild_id: int, current_channel_id: int) -> Optional[Dict]:
    """Return the next channel in order_index cycle, wrapping around."""
    channels = get_channels(guild_id)
    if not channels:
        return None
    if current_channel_id is None:
        return channels[0]
    ids = [c['id'] for c in channels]
    try:
        idx = ids.index(current_channel_id)
        next_idx = (idx + 1) % len(ids)
    except ValueError:
        next_idx = 0
    return channels[next_idx]


# ─── Warn Points ──────────────────────────────────────────────────────────────

def add_warn_points(user_id: int, guild_id: int, amount: float,
                    reason: str = '', given_by: int = None) -> float:
    with _lock:
        with _get_conn() as conn:
            conn.execute(
                'UPDATE users SET warn_points = warn_points + ? WHERE user_id=? AND guild_id=?',
                (amount, user_id, guild_id))
            conn.commit()
    u = get_user(user_id, guild_id)
    return u['warn_points'] if u else amount


def get_warn_points_leaderboard(guild_id: int, limit: int = 10) -> List[Dict]:
    with _get_conn() as conn:
        rows = conn.execute(
            'SELECT * FROM users WHERE guild_id=? AND warn_points > 0 AND is_banned=0 '
            'ORDER BY warn_points DESC LIMIT ?', (guild_id, limit)).fetchall()
        return [dict(r) for r in rows]


def clear_warn_points(user_id: int, guild_id: int) -> None:
    with _lock:
        with _get_conn() as conn:
            conn.execute('UPDATE users SET warn_points=0 WHERE user_id=? AND guild_id=?',
                         (user_id, guild_id))
            conn.commit()


# ─── Notes ────────────────────────────────────────────────────────────────────

def add_note(user_id: int, guild_id: int, content: str, author_id: int = None) -> int:
    with _lock:
        with _get_conn() as conn:
            cur = conn.execute(
                'INSERT INTO notes (user_id, guild_id, content, author_id) VALUES (?,?,?,?)',
                (user_id, guild_id, content, author_id))
            conn.commit()
            return cur.lastrowid


def get_notes(user_id: int, guild_id: int) -> List[Dict]:
    with _get_conn() as conn:
        rows = conn.execute(
            'SELECT * FROM notes WHERE user_id=? AND guild_id=? ORDER BY created_at DESC',
            (user_id, guild_id)).fetchall()
        return [dict(r) for r in rows]


def delete_note(note_id: int, guild_id: int) -> bool:
    with _lock:
        with _get_conn() as conn:
            cur = conn.execute('DELETE FROM notes WHERE id=? AND guild_id=?', (note_id, guild_id))
            conn.commit()
            return cur.rowcount > 0


# ─── Economy ──────────────────────────────────────────────────────────────────

def get_wallet(user_id: int, guild_id: int) -> Dict:
    u = get_user(user_id, guild_id)
    if not u:
        return {'cash': 0.0, 'bank': 0.0}
    return {'cash': u.get('cash') or 0.0, 'bank': u.get('bank') or 0.0}


def add_cash(user_id: int, guild_id: int, amount: float) -> float:
    """Add (or subtract) cash from wallet. Returns new cash balance."""
    with _lock:
        with _get_conn() as conn:
            conn.execute(
                'UPDATE users SET cash = MAX(0, cash + ?) WHERE user_id=? AND guild_id=?',
                (amount, user_id, guild_id))
            conn.commit()
    return get_wallet(user_id, guild_id)['cash']


def transfer_cash(from_id: int, to_id: int, guild_id: int, amount: float) -> bool:
    """Move cash between users. Returns False if sender has insufficient funds."""
    with _lock:
        with _get_conn() as conn:
            sender = conn.execute(
                'SELECT cash FROM users WHERE user_id=? AND guild_id=?',
                (from_id, guild_id)).fetchone()
            if not sender or sender['cash'] < amount:
                return False
            conn.execute(
                'UPDATE users SET cash = cash - ? WHERE user_id=? AND guild_id=?',
                (amount, from_id, guild_id))
            conn.execute(
                'UPDATE users SET cash = cash + ? WHERE user_id=? AND guild_id=?',
                (amount, to_id, guild_id))
            conn.commit()
    return True


def deposit_cash(user_id: int, guild_id: int, amount: float) -> bool:
    with _lock:
        with _get_conn() as conn:
            row = conn.execute(
                'SELECT cash FROM users WHERE user_id=? AND guild_id=?',
                (user_id, guild_id)).fetchone()
            if not row or row['cash'] < amount:
                return False
            conn.execute(
                'UPDATE users SET cash = cash - ?, bank = bank + ? WHERE user_id=? AND guild_id=?',
                (amount, amount, user_id, guild_id))
            conn.commit()
    return True


def withdraw_cash(user_id: int, guild_id: int, amount: float) -> bool:
    with _lock:
        with _get_conn() as conn:
            row = conn.execute(
                'SELECT bank FROM users WHERE user_id=? AND guild_id=?',
                (user_id, guild_id)).fetchone()
            if not row or row['bank'] < amount:
                return False
            conn.execute(
                'UPDATE users SET bank = bank - ?, cash = cash + ? WHERE user_id=? AND guild_id=?',
                (amount, amount, user_id, guild_id))
            conn.commit()
    return True


def set_cooldown(user_id: int, guild_id: int, field: str) -> None:
    """Set a cooldown timestamp (daily_last, work_last, beg_last, rep_last)."""
    now = datetime.now().isoformat()
    with _lock:
        with _get_conn() as conn:
            conn.execute(
                f'UPDATE users SET {field}=? WHERE user_id=? AND guild_id=?',
                (now, user_id, guild_id))
            conn.commit()


def get_eco_leaderboard(guild_id: int, limit: int = 10) -> List[Dict]:
    with _get_conn() as conn:
        rows = conn.execute(
            'SELECT *, (cash + bank) as total FROM users WHERE guild_id=? AND is_banned=0 '
            'ORDER BY total DESC LIMIT ?', (guild_id, limit)).fetchall()
        return [dict(r) for r in rows]

import sqlite3
import threading
import json
from datetime import datetime, date
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
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id   INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                title      TEXT    DEFAULT '',
                content    TEXT    NOT NULL,
                is_embed   INTEGER DEFAULT 1,
                color      TEXT    DEFAULT '#7289da',
                sent_by    TEXT    DEFAULT 'Dashboard',
                message_id INTEGER DEFAULT NULL,
                created_at TEXT    DEFAULT (datetime('now'))
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
        "ALTER TABLE ranks ADD COLUMN is_owner_only INTEGER DEFAULT 0",
        "ALTER TABLE ranks ADD COLUMN grant_role_ids TEXT DEFAULT '[]'",
        "ALTER TABLE clock_sessions ADD COLUMN flagged INTEGER DEFAULT 0",
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
                   is_banned=0,is_clocked_in=0,clock_in_time=NULL,updated_at=?
                   WHERE user_id=? AND guild_id=?''',
                (datetime.now().isoformat(), user_id, guild_id)
            )
            conn.execute('DELETE FROM user_special_ranks WHERE user_id=? AND guild_id=?',
                         (user_id, guild_id))
            conn.execute('DELETE FROM warnings WHERE user_id=? AND guild_id=?',
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
                display_order: int = 0) -> Optional[Dict]:
    with _lock:
        with _get_conn() as conn:
            try:
                cur = conn.execute(
                    '''INSERT INTO ranks
                       (guild_id,name,required_points,role_id,color,description,icon,
                        is_special,is_owner_only,grant_role_ids,display_order)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
                    (guild_id, name, required_points, role_id, color, description, icon,
                     1 if is_special else 0, 1 if is_owner_only else 0,
                     json.dumps(grant_role_ids or []), display_order)
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


def get_user_auto_rank(user_id: int, guild_id: int) -> Optional[Dict]:
    u = get_user(user_id, guild_id)
    if not u:
        return None
    with _get_conn() as conn:
        row = conn.execute(
            '''SELECT * FROM ranks WHERE guild_id=? AND is_special=0
               AND required_points<=? ORDER BY required_points DESC LIMIT 1''',
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


# ─── Clock ────────────────────────────────────────────────────────────────────

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
    pts = round(hours * pph, 2) if mins >= min_min else 0.0
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
        add_points(user_id, guild_id, pts,
                   note=f'Sesja {round(hours, 2)}h | {ci_dt.strftime("%H:%M")}→{co_dt.strftime("%H:%M")}',
                   transaction_type='clock', reference_id=sess_id)
    return {
        'hours': round(hours, 4), 'minutes': round(mins, 1),
        'points_earned': pts, 'clock_in_time': ci_dt, 'clock_out_time': co_dt,
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
                      sent_by: str, message_id: int = None) -> int:
    with _lock:
        with _get_conn() as conn:
            cur = conn.execute(
                '''INSERT INTO announcements
                   (guild_id,channel_id,title,content,is_embed,color,sent_by,message_id)
                   VALUES (?,?,?,?,?,?,?,?)''',
                (guild_id, channel_id, title, content,
                 1 if is_embed else 0, color, sent_by, message_id)
            )
            conn.commit()
            return cur.lastrowid


def get_announcements(guild_id: int, limit: int = 20) -> List[Dict]:
    with _get_conn() as conn:
        return [dict(r) for r in conn.execute(
            'SELECT * FROM announcements WHERE guild_id=? ORDER BY created_at DESC LIMIT ?',
            (guild_id, limit)
        ).fetchall()]


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

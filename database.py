import sqlite3
import threading
import json
from datetime import datetime, date
from typing import Optional, List, Dict, Any

DATABASE_FILE = 'data/bot.db'
_lock = threading.Lock()


def init_db():
    import os
    os.makedirs('data', exist_ok=True)
    with _get_conn() as conn:
        conn.executescript('''
            PRAGMA journal_mode=WAL;
            PRAGMA foreign_keys=ON;

            CREATE TABLE IF NOT EXISTS guilds (
                guild_id       INTEGER PRIMARY KEY,
                clock_channel_id INTEGER DEFAULT NULL,
                log_channel_id   INTEGER DEFAULT NULL,
                admin_role_ids   TEXT    DEFAULT '[]',
                points_per_hour  REAL    DEFAULT 10.0,
                min_clock_minutes INTEGER DEFAULT 5,
                embed_hour       INTEGER DEFAULT 0,
                embed_minute     INTEGER DEFAULT 0,
                created_at       TEXT    DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS users (
                user_id          INTEGER,
                guild_id         INTEGER,
                username         TEXT    DEFAULT '',
                display_name     TEXT    DEFAULT '',
                points           REAL    DEFAULT 0,
                total_hours      REAL    DEFAULT 0,
                sessions_count   INTEGER DEFAULT 0,
                is_banned        INTEGER DEFAULT 0,
                is_clocked_in    INTEGER DEFAULT 0,
                clock_in_time    TEXT    DEFAULT NULL,
                created_at       TEXT    DEFAULT (datetime('now')),
                updated_at       TEXT    DEFAULT (datetime('now')),
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
        ''')
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
            conn.execute('INSERT OR IGNORE INTO guilds (guild_id) VALUES (?)', (guild_id,))
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


# ─── User ─────────────────────────────────────────────────────────────────────

def get_user(user_id: int, guild_id: int) -> Optional[Dict]:
    with _get_conn() as conn:
        row = conn.execute('SELECT * FROM users WHERE user_id=? AND guild_id=?',
                           (user_id, guild_id)).fetchone()
        return dict(row) if row else None


def ensure_user(user_id: int, guild_id: int, username: str = '', display_name: str = '') -> Dict:
    with _lock:
        with _get_conn() as conn:
            conn.execute(
                'INSERT OR IGNORE INTO users (user_id, guild_id, username, display_name) VALUES (?,?,?,?)',
                (user_id, guild_id, username, display_name)
            )
            if username or display_name:
                conn.execute(
                    'UPDATE users SET username=?, display_name=?, updated_at=? WHERE user_id=? AND guild_id=?',
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
    """Add (or subtract) points. Returns new total. Thread-safe."""
    with _lock:
        with _get_conn() as conn:
            row = conn.execute(
                'SELECT points FROM users WHERE user_id=? AND guild_id=?',
                (user_id, guild_id)
            ).fetchone()
            if not row:
                return 0.0
            before = row['points']
            after = max(0.0, before + delta)
            conn.execute(
                'UPDATE users SET points=?, updated_at=? WHERE user_id=? AND guild_id=?',
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


def set_points(user_id: int, guild_id: int, new_points: float, note: str = '',
               assigned_by: int = None) -> float:
    user = get_user(user_id, guild_id)
    if not user:
        return 0.0
    delta = new_points - user['points']
    return add_points(user_id, guild_id, delta, note=note,
                      transaction_type='set', assigned_by=assigned_by)


def reset_user(user_id: int, guild_id: int) -> None:
    with _lock:
        with _get_conn() as conn:
            conn.execute(
                '''UPDATE users SET points=0, total_hours=0, sessions_count=0,
                   is_banned=0, is_clocked_in=0, clock_in_time=NULL, updated_at=?
                   WHERE user_id=? AND guild_id=?''',
                (datetime.now().isoformat(), user_id, guild_id)
            )
            conn.execute('DELETE FROM user_special_ranks WHERE user_id=? AND guild_id=?',
                         (user_id, guild_id))
            conn.commit()


def get_all_users(guild_id: int) -> List[Dict]:
    with _get_conn() as conn:
        return [dict(r) for r in conn.execute(
            'SELECT * FROM users WHERE guild_id=? ORDER BY points DESC',
            (guild_id,)
        ).fetchall()]


def get_leaderboard(guild_id: int, limit: int = 10, include_banned: bool = False) -> List[Dict]:
    with _get_conn() as conn:
        q = 'SELECT * FROM users WHERE guild_id=?'
        if not include_banned:
            q += ' AND is_banned=0'
        q += ' ORDER BY points DESC LIMIT ?'
        return [dict(r) for r in conn.execute(q, (guild_id, limit)).fetchall()]


# ─── Ranks ────────────────────────────────────────────────────────────────────

def get_ranks(guild_id: int, special_only: bool = False, auto_only: bool = False) -> List[Dict]:
    with _get_conn() as conn:
        q = 'SELECT * FROM ranks WHERE guild_id=?'
        if special_only:
            q += ' AND is_special=1'
        if auto_only:
            q += ' AND is_special=0'
        q += ' ORDER BY is_special ASC, required_points ASC'
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
                is_special: bool = False, display_order: int = 0) -> Optional[Dict]:
    with _lock:
        with _get_conn() as conn:
            try:
                cur = conn.execute(
                    '''INSERT INTO ranks
                       (guild_id,name,required_points,role_id,color,description,icon,is_special,display_order)
                       VALUES (?,?,?,?,?,?,?,?,?)''',
                    (guild_id, name, required_points, role_id, color,
                     description, icon, 1 if is_special else 0, display_order)
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
    user = get_user(user_id, guild_id)
    if not user:
        return None
    with _get_conn() as conn:
        row = conn.execute(
            '''SELECT * FROM ranks WHERE guild_id=? AND is_special=0 AND required_points<=?
               ORDER BY required_points DESC LIMIT 1''',
            (guild_id, user['points'])
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
                    '''INSERT OR IGNORE INTO user_special_ranks
                       (user_id,guild_id,rank_id,assigned_by,note) VALUES (?,?,?,?,?)''',
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
    user = get_user(user_id, guild_id)
    if not user or user['is_clocked_in']:
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
                'UPDATE users SET is_clocked_in=1, clock_in_time=?, updated_at=? WHERE user_id=? AND guild_id=?',
                (now, now, user_id, guild_id)
            )
            conn.commit()
            return dict(conn.execute('SELECT * FROM clock_sessions WHERE id=?',
                                     (cur.lastrowid,)).fetchone())


def clock_out(user_id: int, guild_id: int) -> Optional[Dict]:
    user = get_user(user_id, guild_id)
    if not user or not user['is_clocked_in'] or not user['clock_in_time']:
        return None

    guild = get_guild(guild_id) or {}
    points_per_hour = guild.get('points_per_hour', 10.0)
    min_minutes = guild.get('min_clock_minutes', 5)

    clock_in_dt = datetime.fromisoformat(user['clock_in_time'])
    clock_out_dt = datetime.now()
    seconds = (clock_out_dt - clock_in_dt).total_seconds()
    hours = seconds / 3600
    minutes = seconds / 60
    points_earned = round(hours * points_per_hour, 2) if minutes >= min_minutes else 0.0

    with _lock:
        with _get_conn() as conn:
            session = conn.execute(
                '''SELECT id FROM clock_sessions
                   WHERE user_id=? AND guild_id=? AND clock_out_time IS NULL
                   ORDER BY clock_in_time DESC LIMIT 1''',
                (user_id, guild_id)
            ).fetchone()
            session_id = session['id'] if session else None

            if session_id:
                conn.execute(
                    'UPDATE clock_sessions SET clock_out_time=?, hours_worked=?, points_earned=? WHERE id=?',
                    (clock_out_dt.isoformat(), round(hours, 4), points_earned, session_id)
                )

            conn.execute(
                '''UPDATE users SET is_clocked_in=0, clock_in_time=NULL,
                   total_hours=total_hours+?, sessions_count=sessions_count+1, updated_at=?
                   WHERE user_id=? AND guild_id=?''',
                (round(hours, 4), clock_out_dt.isoformat(), user_id, guild_id)
            )
            conn.commit()

    if points_earned > 0:
        add_points(user_id, guild_id, points_earned,
                   note=f'Sesja {round(hours, 2)}h | {clock_in_dt.strftime("%H:%M")} - {clock_out_dt.strftime("%H:%M")}',
                   transaction_type='clock', reference_id=session_id)

    return {
        'hours': round(hours, 4),
        'minutes': round(minutes, 1),
        'points_earned': points_earned,
        'clock_in_time': clock_in_dt,
        'clock_out_time': clock_out_dt,
        'session_id': session_id,
        'enough_time': minutes >= min_minutes,
    }


def force_clock_out(user_id: int, guild_id: int) -> bool:
    user = get_user(user_id, guild_id)
    if not user or not user['is_clocked_in']:
        return False
    now = datetime.now().isoformat()
    with _lock:
        with _get_conn() as conn:
            conn.execute(
                '''UPDATE clock_sessions SET clock_out_time=? WHERE
                   user_id=? AND guild_id=? AND clock_out_time IS NULL''',
                (now, user_id, guild_id)
            )
            conn.execute(
                'UPDATE users SET is_clocked_in=0, clock_in_time=NULL, updated_at=? WHERE user_id=? AND guild_id=?',
                (now, user_id, guild_id)
            )
            conn.commit()
    return True


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


# ─── Daily embed ──────────────────────────────────────────────────────────────

def save_daily_embed(guild_id: int, channel_id: int, message_id: int, embed_date: str) -> None:
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
        def scalar(q, *a):
            r = conn.execute(q, a).fetchone()
            return list(r)[0] if r else 0

        return {
            'total_users':    scalar('SELECT COUNT(*) FROM users WHERE guild_id=?', guild_id),
            'total_points':   scalar('SELECT COALESCE(SUM(points),0) FROM users WHERE guild_id=?', guild_id),
            'total_sessions': scalar('SELECT COUNT(*) FROM clock_sessions WHERE guild_id=?', guild_id),
            'total_hours':    round(scalar('SELECT COALESCE(SUM(hours_worked),0) FROM clock_sessions WHERE guild_id=?', guild_id), 2),
            'active_now':     scalar('SELECT COUNT(*) FROM users WHERE guild_id=? AND is_clocked_in=1', guild_id),
            'banned_count':   scalar('SELECT COUNT(*) FROM users WHERE guild_id=? AND is_banned=1', guild_id),
            'rank_count':     scalar('SELECT COUNT(*) FROM ranks WHERE guild_id=?', guild_id),
        }

"""SQLite database: connection and schema."""
import os
import sqlite3
import sys
from contextlib import contextmanager

DATA_DIR = os.environ.get('DOTRACK_DATA', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data'))
DB_PATH = os.path.join(DATA_DIR, 'dotrack.db')

SCHEMA_VERSION = 4

# Values stored in the database. They are stable keys: the UI translates them.
# note = a notice for a day or a period (babysitter away, office closed…); birthday = yearly, due_date is the birth date
KINDS = ['task', 'deadline', 'appointment', 'note', 'birthday']
CATEGORIES = ['home', 'shopping', 'car', 'health', 'kids', 'school', 'documents', 'money', 'work', 'leisure', 'other']
PRIORITIES = [-1, 0, 1]  # low, normal, high
RECUR_UNITS = ['day', 'week', 'month', 'year']
ROLES = ['admin', 'member']
FEED_SCOPES = ['mine', 'all']
# checklist = shopping-style list (undated items stay out of the agenda); project = a group of ordinary items
LIST_KINDS = ['checklist', 'project']
COLORS = ['blue', 'green', 'red', 'orange', 'yellow', 'purple', 'pink', 'teal', 'gray']
RECUR_FROM = ['due', 'done']  # next occurrence counted from the due date or from the day it was done
NOTIFICATION_KINDS = ['reminder', 'assigned', 'comment', 'done']
# Supermarket aisles for shopping lists (the UI translates them)
SECTIONS = ['produce', 'bakery', 'meat_fish', 'dairy', 'frozen', 'pantry', 'drinks', 'snacks', 'household', 'personal_care',
            'baby', 'pets', 'other']
WEBHOOK_EVENTS = ['item.created', 'item.updated', 'item.done', 'item.reopened', 'item.deleted', 'comment.created']
TRASH_DAYS = 30

SCHEMA = '''
CREATE TABLE IF NOT EXISTS families (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
    name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    email_verified INTEGER NOT NULL DEFAULT 0,
    session_version INTEGER NOT NULL DEFAULT 1,
    consent_at TEXT,
    language TEXT NOT NULL DEFAULT 'it',
    reminders_email INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS members (
    family_id INTEGER NOT NULL REFERENCES families(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role TEXT NOT NULL DEFAULT 'member',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (family_id, user_id)
);
CREATE TABLE IF NOT EXISTS identities (
    provider TEXT NOT NULL,
    subject TEXT NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    email TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (provider, subject)
);
CREATE TABLE IF NOT EXISTS tokens (
    hash TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    family_id INTEGER REFERENCES families(id) ON DELETE CASCADE,
    expires_at TEXT NOT NULL,
    used_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
-- People without an account who can be put in charge of things: kids, grandparents, the babysitter…
CREATE TABLE IF NOT EXISTS people (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    family_id INTEGER NOT NULL REFERENCES families(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
-- Everything to remember: to-dos, deadlines (car tax, insurance, licence…) and appointments
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    family_id INTEGER NOT NULL REFERENCES families(id) ON DELETE CASCADE,
    kind TEXT NOT NULL DEFAULT 'task',
    title TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT 'other',
    subject TEXT NOT NULL DEFAULT '',          -- who/what it is about: "Panda", "Giulia", …
    due_date DATE,
    due_time TEXT,                             -- HH:MM
    end_time TEXT,                             -- HH:MM (appointments)
    location TEXT NOT NULL DEFAULT '',
    assignee_id INTEGER REFERENCES users(id) ON DELETE SET NULL,   -- NULL = anyone
    person_id INTEGER REFERENCES people(id) ON DELETE SET NULL,    -- or someone without an account
    priority INTEGER NOT NULL DEFAULT 0,       -- -1 low, 0 normal, 1 high
    end_date DATE,                             -- last day of a note covering a period
    recur_unit TEXT,                           -- day | week | month | year, NULL = once
    recur_every INTEGER,
    remind_days INTEGER,                       -- reminder N days before, NULL = none
    done_at TEXT,
    done_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    spawned_from INTEGER REFERENCES items(id) ON DELETE SET NULL,  -- previous occurrence of a recurring item
    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_items_family_due ON items(family_id, due_date);
-- Questions to ask (with their answers) for appointments, checklist entries for the rest
CREATE TABLE IF NOT EXISTS item_checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    position INTEGER NOT NULL DEFAULT 0,
    text TEXT NOT NULL,
    answer TEXT NOT NULL DEFAULT '',
    done INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_checks_item ON item_checks(item_id);
-- Medical reports and other files; the content lives in DATA_DIR/files/<stored_name>
CREATE TABLE IF NOT EXISTS attachments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    mime TEXT NOT NULL,
    size INTEGER NOT NULL,
    stored_name TEXT NOT NULL UNIQUE,
    uploaded_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_attachments_item ON attachments(item_id);
-- Private iCal address that Google Calendar (or any calendar app) subscribes to
CREATE TABLE IF NOT EXISTS calendar_feeds (
    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    family_id INTEGER NOT NULL REFERENCES families(id) ON DELETE CASCADE,
    token TEXT NOT NULL UNIQUE,
    scope TEXT NOT NULL DEFAULT 'mine',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
-- Days on which the daily reminder email was already sent
-- Lists (shopping list, packing list…) and projects ("Bathroom works"): one level, no nesting
CREATE TABLE IF NOT EXISTS lists (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    family_id INTEGER NOT NULL REFERENCES families(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'checklist',
    color TEXT NOT NULL DEFAULT 'blue',
    position INTEGER NOT NULL DEFAULT 0,
    archived INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
-- Free labels, several per item
CREATE TABLE IF NOT EXISTS labels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    family_id INTEGER NOT NULL REFERENCES families(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    color TEXT NOT NULL DEFAULT 'gray',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS item_labels (
    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    label_id INTEGER NOT NULL REFERENCES labels(id) ON DELETE CASCADE,
    PRIMARY KEY (item_id, label_id)
);
CREATE INDEX IF NOT EXISTS idx_item_labels_label ON item_labels(label_id);
CREATE TABLE IF NOT EXISTS comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    text TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_comments_item ON comments(item_id);
-- Who did what to an item: created, updated, done, reopened
CREATE TABLE IF NOT EXISTS item_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    action TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_events_item ON item_events(item_id);
-- In-app notifications (also sent as push notifications to the user's devices)
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    family_id INTEGER NOT NULL REFERENCES families(id) ON DELETE CASCADE,
    item_id INTEGER REFERENCES items(id) ON DELETE CASCADE,
    actor_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    read_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id, read_at);
-- Reminders already delivered: (item, moment) so a reminder fires once
CREATE TABLE IF NOT EXISTS reminders_sent (
    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    moment TEXT NOT NULL,
    PRIMARY KEY (item_id, moment)
);
-- Web Push subscriptions (one per browser/device)
CREATE TABLE IF NOT EXISTS push_subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    endpoint TEXT NOT NULL UNIQUE,
    p256dh TEXT NOT NULL,
    auth TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
-- Passwords for apps (CalDAV): only the hash is stored
CREATE TABLE IF NOT EXISTS app_passwords (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    hash TEXT NOT NULL UNIQUE,
    last_used_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
-- Shopping history of a list: suggestions while typing and the aisle each thing belongs to
CREATE TABLE IF NOT EXISTS list_history (
    list_id INTEGER NOT NULL REFERENCES lists(id) ON DELETE CASCADE,
    key TEXT NOT NULL,                 -- lower-case name
    name TEXT NOT NULL,
    section TEXT,
    uses INTEGER NOT NULL DEFAULT 1,
    last_used TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (list_id, key)
);
-- Personal API tokens (integrations: Home Assistant, eaTrack, scripts): only the hash is stored
CREATE TABLE IF NOT EXISTS api_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    family_id INTEGER NOT NULL REFERENCES families(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    hash TEXT NOT NULL UNIQUE,
    hint TEXT NOT NULL,
    last_used_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
-- Outgoing webhooks of a family
CREATE TABLE IF NOT EXISTS webhooks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    family_id INTEGER NOT NULL REFERENCES families(id) ON DELETE CASCADE,
    url TEXT NOT NULL,
    secret TEXT NOT NULL,
    events TEXT NOT NULL,              -- comma separated
    last_status TEXT,
    last_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
-- Two-step verification: single-use recovery codes (hashed)
CREATE TABLE IF NOT EXISTS recovery_codes (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    hash TEXT NOT NULL,
    used_at TEXT,
    PRIMARY KEY (user_id, hash)
);
CREATE TABLE IF NOT EXISTS reminder_runs (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    day DATE NOT NULL,
    PRIMARY KEY (user_id, day)
);
'''


def connect():
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    return conn


@contextmanager
def transaction():
    """Connection that commits on success and rolls back on error."""
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def bump(conn, family_id):
    """Something changed in the family: clients polling /api/sync reload."""
    if family_id:
        conn.execute('UPDATE families SET version = version + 1 WHERE id = ?', (family_id,))


def create_family(conn, name, language='it'):
    return conn.execute('INSERT INTO families (name) VALUES (?)', (name,)).lastrowid


# Columns added after version 1: (table, column, definition)
ADDED_COLUMNS = [
    ('items', 'person_id', 'INTEGER REFERENCES people(id) ON DELETE SET NULL'),
    ('items', 'priority', 'INTEGER NOT NULL DEFAULT 0'),
    ('items', 'end_date', 'DATE'),
    ('items', 'list_id', 'INTEGER REFERENCES lists(id) ON DELETE CASCADE'),
    ('items', 'recur_from', "TEXT NOT NULL DEFAULT 'due'"),
    ('items', 'remind_time', 'TEXT'),               # HH:MM of the reminder notification, NULL = default
    ('items', 'caldav_uid', 'TEXT'),                # UID given by a CalDAV client, NULL = item-<id>@host
    ('items', 'caldav_name', 'TEXT'),               # resource name chosen by a CalDAV client
    ('items', 'deleted_at', 'TEXT'),                # in the trash since then (NULL = not deleted)
    ('items', 'position', 'INTEGER NOT NULL DEFAULT 0'),  # manual order inside a list
    ('items', 'quantity', "TEXT NOT NULL DEFAULT ''"),     # shopping: "2", "500 g"
    ('items', 'section', 'TEXT'),                   # shopping: supermarket aisle
    ('items', 'rotation', 'TEXT'),                  # chores in turn: "u1,u2,p3" (members u<id>, people p<id>)
    ('lists', 'sections', 'INTEGER NOT NULL DEFAULT 0'),  # group a checklist by aisle
    ('lists', 'template', 'INTEGER NOT NULL DEFAULT 0'),  # a template to create lists from
    ('families', 'version', 'INTEGER NOT NULL DEFAULT 0'),  # bumped on every change: clients poll it
    ('users', 'totp_secret', 'TEXT'),               # two-step verification (TOTP), NULL = off
    ('users', 'totp_pending', 'TEXT'),              # secret being set up, not confirmed yet
    ('families', 'hub_id', 'INTEGER'),              # the family in weHub (see famkit/hub.py), NULL = not managed there
    ('families', 'hub_version', 'INTEGER'),         # weHub version last copied
    ('users', 'hub_id', 'INTEGER'),
    ('people', 'hub_id', 'INTEGER'),
    ('items', 'ext_ref', 'TEXT'),                   # kept in step by another family app, e.g. "patrack-12" (hub_hooks.py)
    ('items', 'ext_url', 'TEXT'),                   # where that app shows it (the paTrack document)
]


def _migrate(conn):
    """Bring a database created by an older version up to date (new tables come from SCHEMA)."""
    for table, column, definition in ADDED_COLUMNS:
        if column not in {r['name'] for r in conn.execute(f'PRAGMA table_info({table})')}:
            conn.execute(f'ALTER TABLE {table} ADD COLUMN {column} {definition}')


def init_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = connect()
    try:
        conn.executescript(SCHEMA)
        _migrate(conn)
        conn.execute('CREATE INDEX IF NOT EXISTS idx_items_list ON items(list_id)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_items_deleted ON items(family_id, deleted_at)')
        conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_items_caldav_name ON items(family_id, caldav_name)')
        conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_families_hub ON families(hub_id)')
        conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_users_hub ON users(hub_id)')
        conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_items_ext ON items(family_id, ext_ref)')
        conn.execute(f'PRAGMA user_version = {SCHEMA_VERSION}')
        conn.execute('PRAGMA journal_mode = WAL')
        conn.commit()
    finally:
        conn.close()


# The shared code (famkit: mail, backups, weHub link, sign-in) reads DOTRACK_* variables and uses this module
import famkit  # noqa: E402
famkit.configure('DOTRACK', 'doTrack', sys.modules[__name__])

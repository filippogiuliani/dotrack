"""Priority, people without an account, notices over a period, birthdays, and the upgrade of old databases."""
import datetime
import sqlite3

import db
import reminders
from common import next_birthday
from conftest import ok


def test_priority_and_validation(family):
    c = family.c
    assert c.post('/api/items', json={'title': 'x', 'priority': 5}).status_code == 400
    assert c.post('/api/items', json={'title': 'x', 'priority': 'high'}).status_code == 400
    item = family.item(title='Urgente', priority=1, category='shopping')
    assert (item['priority'], item['category']) == (1, 'shopping')
    assert family.item(title='Normale')['priority'] == 0


def test_people_without_account(family):
    c = family.c
    giulia = ok(c.post('/api/family/people', json={'name': 'Giulia'}), 201)
    assert c.post('/api/family/people', json={'name': 'giulia'}).status_code == 409
    assert c.post('/api/family/people', json={'name': ' '}).status_code == 400
    assert [p['name'] for p in ok(c.get('/api/me'))['people']] == ['Giulia']

    item = family.item(title='Compiti', person_id=giulia['id'], assignee_id=family.uid)
    assert (item['person_id'], item['assignee_id']) == (giulia['id'], None)  # a person excludes a member
    ok(c.put(f"/api/family/people/{giulia['id']}", json={'name': 'Giulia R.'}))
    assert ok(c.get('/api/family'))['people'][0]['name'] == 'Giulia R.'

    # Another family can't use or see them
    other = family.client()
    from conftest import sign_up
    sign_up(other, email='altro@example.com')
    assert other.post('/api/items', json={'title': 'x', 'person_id': giulia['id']}).status_code == 400
    assert other.delete(f"/api/family/people/{giulia['id']}").status_code == 404

    ok(c.delete(f"/api/family/people/{giulia['id']}"))
    assert ok(c.get(f"/api/items/{item['id']}"))['person_id'] is None


def test_notice_over_a_period(family):
    c = family.c
    assert c.post('/api/items', json={'title': 'Chiusura', 'kind': 'note'}).status_code == 400  # needs a date
    assert c.post('/api/items', json={'title': 'Chiusura', 'kind': 'note', 'due_date': '2026-12-24',
                                      'end_date': '2026-12-20'}).status_code == 400
    note = family.item(title='Chiusura aziendale', kind='note', due_date='2026-12-24', end_date='2027-01-06',
                       due_time='10:00', recur_unit='year')
    assert (note['end_date'], note['due_time'], note['recur_unit']) == ('2027-01-06', None, None)
    # An end_date is only for notes
    assert family.item(title='x', due_date='2026-12-24', end_date='2027-01-06')['end_date'] is None


def test_next_birthday():
    assert next_birthday('1990-03-15', datetime.date(2026, 11, 9)) == (datetime.date(2027, 3, 15), 37)
    assert next_birthday('1990-11-09', datetime.date(2026, 11, 9)) == (datetime.date(2026, 11, 9), 36)
    assert next_birthday('2024-02-29', datetime.date(2026, 11, 9)) == (datetime.date(2027, 2, 28), 3)
    assert next_birthday('1904-12-01', datetime.date(2026, 11, 9)) == (datetime.date(2026, 12, 1), None)


def test_birthdays_and_notices_in_reminders_and_feed(client, family, outbox):
    f = family
    with db.transaction() as conn:
        conn.execute('UPDATE users SET email_verified = 1')
    f.item(kind='birthday', title='Nonna Lucia', due_date='1950-11-12', remind_days=3)
    f.item(kind='note', title='La babysitter non viene', due_date='2026-11-10')
    f.item(kind='note', title='Chiusura passata', due_date='2026-11-01', end_date='2026-11-05')
    assert reminders.run_once(datetime.date(2026, 11, 9)) == 1
    body = outbox[-1][2]
    assert '🎂 Nonna Lucia – 12/11/2026, compie 76 anni' in body
    assert 'Chiusura passata' not in body  # a notice is never "overdue"

    f.item(kind='note', title='Chiusura aziendale', due_date='2026-12-24', end_date='2027-01-06')
    feed = ok(f.c.get('/api/calendar/feed'))
    ics = client().get('/' + feed['url'].split('://', 1)[1].split('/', 1)[1]).get_data(as_text=True)
    assert 'SUMMARY:🎂 Nonna Lucia' in ics and 'RRULE:FREQ=YEARLY' in ics  # years ago, but repeats
    assert 'DTSTART;VALUE=DATE:20261224' in ics and 'DTEND;VALUE=DATE:20270107' in ics


def test_old_database_is_upgraded(tmp_path, monkeypatch):
    path = tmp_path / 'old.db'
    conn = sqlite3.connect(path)
    conn.executescript('''CREATE TABLE families (id INTEGER PRIMARY KEY, name TEXT NOT NULL, created_at TEXT);
        CREATE TABLE items (id INTEGER PRIMARY KEY AUTOINCREMENT, family_id INTEGER NOT NULL, kind TEXT NOT NULL DEFAULT 'task',
        title TEXT NOT NULL, assignee_id INTEGER, due_date DATE);
        INSERT INTO families VALUES (1, 'F', NULL); INSERT INTO items (family_id, title) VALUES (1, 'Vecchio');''')
    conn.commit()
    conn.close()
    monkeypatch.setattr(db, 'DATA_DIR', str(tmp_path))
    monkeypatch.setattr(db, 'DB_PATH', str(path))
    db.init_db()
    conn = db.connect()
    row = conn.execute('SELECT title, priority, person_id, end_date FROM items').fetchone()
    assert tuple(row) == ('Vecchio', 0, None, None)
    assert conn.execute('PRAGMA user_version').fetchone()[0] == db.SCHEMA_VERSION
    conn.close()

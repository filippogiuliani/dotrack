"""Timed reminders and Web Push subscriptions."""
import datetime

import notify
import reminders
from conftest import ok


def test_reminder_moment():
    row = lambda **k: {'kind': 'task', 'due_date': '2026-12-10', 'due_time': None, 'remind_days': 1, 'remind_time': None, **k}
    hour = reminders.HOUR
    today = datetime.date(2026, 12, 1)
    assert reminders.reminder_moment(row(), today) == datetime.datetime(2026, 12, 9, hour)
    assert reminders.reminder_moment(row(remind_time='18:30'), today) == datetime.datetime(2026, 12, 9, 18, 30)
    # Same day with a time: one hour before
    assert reminders.reminder_moment(row(remind_days=0, due_time='15:00'), today) == datetime.datetime(2026, 12, 10, 14, 0)
    assert reminders.reminder_moment(row(remind_days=0, due_time='00:30'), today) == datetime.datetime(2026, 12, 10, 0, 0)
    assert reminders.reminder_moment(row(remind_days=None), today) is None
    # Birthdays: this year's (or next year's) birthday
    bday = row(kind='birthday', due_date='1980-12-05', remind_days=3)
    assert reminders.reminder_moment(bday, today) == datetime.datetime(2026, 12, 2, hour)
    assert reminders.reminder_moment(bday, datetime.date(2026, 12, 20)) == datetime.datetime(2027, 12, 2, hour)


def test_push_due_fires_once_for_the_right_people(family, pushes):
    f = family
    f.add_partner()
    now = datetime.datetime(2026, 12, 9, 18, 31)
    mine = f.item(title='Pagare bollo', due_date='2026-12-10', remind_days=1, remind_time='18:30', assignee_id=f.uid)
    anyone = f.item(title='Pediatra', kind='appointment', due_date='2026-12-09', due_time='19:30', remind_days=0, location='Studio')
    f.item(title='Più tardi', due_date='2026-12-10', remind_days=1, remind_time='20:00')
    done = f.item(title='Fatto', due_date='2026-12-10', remind_days=1, remind_time='18:00')
    ok(f.c.post(f"/api/items/{done['id']}/done"))
    pushes.clear()

    assert reminders.push_due(now) == 2
    who = sorted((uid, p['title']) for uid, p in pushes)
    assert who == sorted([(f.uid, 'Pagare bollo'), (f.uid, '📅 Pediatra'), (f.puid, '📅 Pediatra')])
    body = next(p['body'] for uid, p in pushes if p['title'] == '📅 Pediatra')
    assert '19:30' in body and 'Studio' in body
    # Kept in the bell too
    assert {n['title'] for n in ok(f.p.get('/api/notifications'))['items']} == {'📅 Pediatra'}

    # Not again
    pushes.clear()
    assert reminders.push_due(now + datetime.timedelta(minutes=5)) == 0 and not pushes
    # Changing the time makes a new reminder
    mine = ok(f.c.get(f"/api/items/{mine['id']}"))
    ok(f.c.put(f"/api/items/{mine['id']}", json={**mine, 'remind_time': '18:40'}))
    assert reminders.push_due(datetime.datetime(2026, 12, 9, 18, 41)) == 1
    # Too old: a reminder more than a day late is skipped
    assert reminders.push_due(datetime.datetime(2026, 12, 11, 21, 0)) == 0


def test_subscriptions(family):
    c = family.c
    assert c.post('/api/push/test').status_code == 400
    key = ok(c.get('/api/push/key'))['key']
    assert len(key) > 80 and key == ok(c.get('/api/push/key'))['key']  # stable
    bad = {'endpoint': 'http://evil.local/x', 'keys': {'p256dh': 'a', 'auth': 'b'}}
    assert c.post('/api/push/subscriptions', json=bad).status_code == 400
    sub = {'endpoint': 'https://fcm.googleapis.com/fcm/send/abc', 'keys': {'p256dh': 'BPk', 'auth': 'xyz'}}
    assert ok(c.post('/api/push/subscriptions', json=sub), 201)['devices'] == 1
    assert ok(c.post('/api/push/subscriptions', json=sub), 201)['devices'] == 1  # same device
    ok(c.post('/api/push/test'))
    ok(c.delete('/api/push/subscriptions', json={'endpoint': sub['endpoint']}))
    assert c.post('/api/push/test').status_code == 400


def test_gone_subscriptions_are_removed(family, monkeypatch):
    import db
    import pywebpush

    class Gone:
        status_code = 410

    def fake(*a, **k):
        raise pywebpush.WebPushException('gone', response=Gone())
    monkeypatch.setattr(pywebpush, 'webpush', fake)
    sub = {'endpoint': 'https://fcm.googleapis.com/fcm/send/abc', 'keys': {'p256dh': 'BPk', 'auth': 'xyz'}}
    ok(family.c.post('/api/push/subscriptions', json=sub), 201)
    with db.transaction() as conn:
        assert notify.send_push(conn, family.uid, {'title': 'x'}) == 0
        assert conn.execute('SELECT COUNT(*) FROM push_subscriptions').fetchone()[0] == 0

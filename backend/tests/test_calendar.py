"""iCal feed for Google Calendar, and daily reminder emails."""
import datetime

import reminders
from conftest import ok


def feed_text(c, url):
    path = url.split('://', 1)[1].split('/', 1)[1]
    r = c.get('/' + path)
    assert r.status_code == 200 and r.mimetype == 'text/calendar'
    return r.get_data(as_text=True)


def test_ical_feed(client, family):
    f = family
    f.add_partner()
    f.item(kind='appointment', title='Pediatra', due_date='2026-11-20', due_time='10:30', location='Via Roma 1, Milano',
           remind_days=1, checks=[{'text': 'Chiedere del vaccino'}])
    f.item(kind='deadline', title='Bollo auto', due_date='2026-12-01', assignee_id=f.puid)
    f.item(title='Senza data')
    feed = ok(f.c.get('/api/calendar/feed'))
    assert feed['scope'] == 'mine' and feed['webcal'].startswith('webcal://')
    anon = client()
    ics = feed_text(anon, feed['url'])
    assert ics.startswith('BEGIN:VCALENDAR\r\n') and ics.endswith('END:VCALENDAR\r\n')
    assert 'SUMMARY:Pediatra' in ics and 'DTSTART:20261120T093000Z' in ics  # 10:30 in Rome = 09:30 UTC
    assert 'LOCATION:Via Roma 1\\, Milano' in ics and 'TRIGGER:-P1D' in ics
    assert 'Chiedere del vaccino' in ics.replace('\r\n ', '')
    assert 'Bollo auto' not in ics  # assigned to Sara: not in Fil's "mine" feed
    assert 'Senza data' not in ics
    assert all(len(line.encode()) <= 75 for line in ics.split('\r\n'))

    feed = ok(f.c.put('/api/calendar/feed', json={'scope': 'all'}))
    ics = feed_text(anon, feed['url'])
    assert 'SUMMARY:⏰ Bollo auto (Sara)' in ics and 'DTSTART;VALUE=DATE:20261201' in ics

    old = feed['url']
    feed = ok(f.c.put('/api/calendar/feed', json={'regenerate': True}))
    assert feed['url'] != old
    assert anon.get('/' + old.split('://', 1)[1].split('/', 1)[1]).status_code == 404
    assert f.c.put('/api/calendar/feed', json={'scope': 'nope'}).status_code == 400
    assert anon.get('/api/ical/not-a-token.ics').status_code == 404


def test_feed_stops_when_member_leaves(client, family):
    f = family
    f.add_partner()
    feed = ok(f.p.get('/api/calendar/feed'))
    ok(f.c.delete(f'/api/family/members/{f.puid}'))
    assert client().get('/' + feed['url'].split('://', 1)[1].split('/', 1)[1]).status_code == 404


def verify(f, outbox):
    """Mark every user verified (reminders only go to confirmed addresses)."""
    import db
    with db.transaction() as conn:
        conn.execute('UPDATE users SET email_verified = 1')
    outbox.clear()


def test_daily_reminders(family, outbox):
    f = family
    f.add_partner()
    verify(f, outbox)
    today = datetime.date(2026, 11, 10)  # a Tuesday
    f.item(kind='deadline', title='Assicurazione', subject='Panda', due_date='2026-12-10', remind_days=30)
    f.item(kind='appointment', title='Pediatra', due_date='2026-11-10', due_time='10:30', assignee_id=f.uid)
    f.item(title='Lontano', due_date='2027-05-01', remind_days=7)
    f.item(title='Di Sara', due_date='2026-11-10', assignee_id=f.puid)

    assert reminders.run_once(today) == 2
    mails = {to: (subject, body) for to, subject, body in outbox}
    subject, body = mails['fil@example.com']
    assert subject == 'doTrack: 2 cose da ricordare'
    assert 'Pediatra' in body and '10/11/2026 10:30' in body and 'Assicurazione (Panda)' in body
    assert 'Lontano' not in body and 'Di Sara' not in body
    sara = mails['sara@example.com'][1]
    assert 'Di Sara' in sara and 'Assicurazione' in sara and 'Pediatra' not in sara

    # Only once a day
    assert reminders.run_once(today) == 0
    # Overdue items alone: only on Mondays
    outbox.clear()
    assert reminders.run_once(datetime.date(2026, 11, 13)) == 0
    # Monday: Sara's overdue to-do is reported; Fil's past appointment is not "overdue"
    assert reminders.run_once(datetime.date(2026, 11, 16)) == 1
    assert outbox[0][0] == 'sara@example.com' and 'SCADUTI' in outbox[0][2] and 'Di Sara' in outbox[0][2]


def test_reminders_can_be_turned_off(family, outbox):
    f = family
    verify(f, outbox)
    f.item(title='Oggi', due_date='2026-11-10')
    ok(f.c.put('/api/account', json={'reminders_email': False}))
    assert reminders.run_once(datetime.date(2026, 11, 10)) == 0

"""Daily reminder email: every morning each user gets a summary of what needs attention
(items assigned to them or to anyone). Nothing is sent on days with nothing new."""
import datetime
import os
import threading
import time

import db
import i18n
from famkit import mail
import notify
from common import next_birthday

HOUR = int(os.environ.get('DOTRACK_REMINDER_HOUR', '8'))


def _line(it, lang, names, people, due, age=None):
    fmt = lambda d: d.strftime('%d/%m/%Y')
    parts = [('🎂 ' if it['kind'] == 'birthday' else '') + ('❗ ' if it['priority'] > 0 else '') + it['title']]
    if it['subject']:
        parts.append(f"({it['subject']})")
    when = fmt(due)
    if it['end_date']:
        when += ' – ' + fmt(datetime.date.fromisoformat(it['end_date']))
    if it['due_time']:
        when += ' ' + it['due_time']
    extra = [when]
    if age:
        extra.append(i18n.tr('turns {n}', lang, n=age))
    if it['location']:
        extra.append(it['location'])
    if it['person_id'] in people:
        extra.append(people[it['person_id']])
    elif it['assignee_id'] is None and len(names) > 1 and it['kind'] not in ('note', 'birthday'):
        extra.append(i18n.tr('anyone', lang))
    return f"• {' '.join(parts)} – {', '.join(extra)}"


def digest(conn, user, today):
    """(subject, body) of the user's reminder for `today`, or None when there is nothing to say."""
    lang = user['language']
    sections = {'today': [], 'soon': [], 'overdue': []}
    for fam in conn.execute('SELECT family_id FROM members WHERE user_id = ?', (user['id'],)).fetchall():
        names = conn.execute('SELECT user_id FROM members WHERE family_id = ?', (fam['family_id'],)).fetchall()
        items = conn.execute('''SELECT * FROM items WHERE family_id = ? AND done_at IS NULL AND deleted_at IS NULL AND due_date IS NOT NULL
                                AND (assignee_id IS NULL OR assignee_id = ?) ORDER BY due_date, due_time''',
                             (fam['family_id'], user['id'])).fetchall()
        people = {r['id']: r['name'] for r in conn.execute('SELECT id, name FROM people WHERE family_id = ?', (fam['family_id'],))}
        for it in items:
            age = None
            if it['kind'] == 'birthday':
                due, age = next_birthday(it['due_date'], today)
            else:
                due = datetime.date.fromisoformat(it['due_date'])
            line = _line(it, lang, names, people, due, age)
            if due == today:
                sections['today'].append(line)
            elif due < today:
                # A past appointment is not "overdue", nor is a notice (it is over or still going on)
                if it['kind'] not in ('appointment', 'note'):
                    sections['overdue'].append(line)
            elif it['remind_days'] is not None and (due - datetime.timedelta(days=it['remind_days'])) <= today:
                # From the reminder day onwards, and at most once a week, so it is not daily noise
                if (due - today).days == it['remind_days'] or (due - today).days % 7 == 0:
                    sections['soon'].append(line)
    # Overdue items alone are only reported on Mondays
    if not sections['today'] and not sections['soon'] and (not sections['overdue'] or today.weekday() != 0):
        return None
    titles = {'today': i18n.tr('Today', lang), 'soon': i18n.tr('Coming up', lang), 'overdue': i18n.tr('Overdue', lang)}
    body = [i18n.tr('Hi {name}, here is what needs attention:', lang, name=user['name']), '']
    for key in ('today', 'soon', 'overdue'):
        if sections[key]:
            body += [titles[key].upper()] + sections[key] + ['']
    from auth import BASE_URL
    if BASE_URL:
        body.append(BASE_URL + '/')
    body.append(i18n.tr('You can turn off these emails in the Family page of the app.', lang))
    n = len(sections['today']) + len(sections['soon'])
    subject = i18n.tr('doTrack: {n} things to remember', lang, n=n) if n != 1 else i18n.tr('doTrack: 1 thing to remember', lang)
    if not n:
        subject = i18n.tr('doTrack: overdue items', lang)
    return subject, '\n'.join(body)


def run_once(today=None):
    """Send today's reminders to whoever hasn't had them yet. Returns how many were sent."""
    today = today or datetime.date.today()
    sent = 0
    with db.transaction() as conn:
        users = conn.execute('''SELECT * FROM users WHERE reminders_email = 1 AND email_verified = 1
                                AND id NOT IN (SELECT user_id FROM reminder_runs WHERE day = ?)''',
                             (today.isoformat(),)).fetchall()
        for u in users:
            msg = digest(conn, u, today)
            conn.execute('INSERT OR IGNORE INTO reminder_runs (user_id, day) VALUES (?,?)', (u['id'], today.isoformat()))
            if msg:
                mail.send(u['email'], *msg)
                sent += 1
        conn.execute("DELETE FROM reminder_runs WHERE day < date('now', '-30 days')")
    return sent


# ---------- Timed reminders ----------

def reminder_moment(item, today):
    """Local datetime at which the item's reminder fires, or None.
    The day is `remind_days` before the date; the time is `remind_time`, otherwise one hour before the
    appointment when the reminder is on the same day, otherwise the morning HOUR."""
    if item['remind_days'] is None or not item['due_date']:
        return None
    if item['kind'] == 'birthday':
        due, _ = next_birthday(item['due_date'], today - datetime.timedelta(days=1))
    else:
        due = datetime.date.fromisoformat(item['due_date'])
    day = due - datetime.timedelta(days=item['remind_days'])
    if item['remind_time']:
        at = datetime.time.fromisoformat(item['remind_time'])
    elif item['remind_days'] == 0 and item['due_time']:
        start = datetime.datetime.combine(due, datetime.time.fromisoformat(item['due_time']))
        return max(start - datetime.timedelta(hours=1), datetime.datetime.combine(due, datetime.time()))
    else:
        at = datetime.time(min(max(HOUR, 0), 23))
    return datetime.datetime.combine(day, at)


def _reminder_text(item, lang, people):
    """Title and body of a reminder notification."""
    icon = {'deadline': '⏰ ', 'appointment': '📅 ', 'birthday': '🎂 ', 'note': '📌 '}.get(item['kind'], '')
    parts = [notify.when_text(item, lang)] if item['kind'] != 'birthday' else []
    if item['location']:
        parts.append(item['location'])
    if item['person_id'] in people:
        parts.append(people[item['person_id']])
    return icon + item['title'], ' · '.join(p for p in parts if p)


def push_due(now=None):
    """Fire the reminders whose moment has come (within the last day). Returns how many items fired."""
    now = now or datetime.datetime.now()
    today = now.date()
    fired = 0
    with db.transaction() as conn:
        items = conn.execute("""SELECT * FROM items WHERE done_at IS NULL AND deleted_at IS NULL AND remind_days IS NOT NULL AND due_date IS NOT NULL
                                AND (kind = 'birthday' OR due_date >= date(?, '-1 day'))""", (today.isoformat(),)).fetchall()
        for it in items:
            moment = reminder_moment(it, today)
            if not moment or not (moment <= now < moment + datetime.timedelta(days=1)):
                continue
            key = moment.isoformat(timespec='minutes')
            if conn.execute('INSERT OR IGNORE INTO reminders_sent (item_id, moment) VALUES (?,?)', (it['id'], key)).rowcount == 0:
                continue
            people = {r['id']: r['name'] for r in conn.execute('SELECT id, name FROM people WHERE family_id = ?', (it['family_id'],))}
            for uid in notify.concerned(conn, it):
                title, body = _reminder_text(it, notify.language_of(conn, uid), people)
                notify.notify(conn, uid, it['family_id'], 'reminder', title, body, item_id=it['id'])
            fired += 1
        conn.execute("DELETE FROM reminders_sent WHERE moment < datetime('now', '-400 days')")
    return fired


def start_scheduler():
    """Background threads: the daily email after HOUR (local time), checked every 10 minutes;
    timed reminders, checked every minute."""
    def daily():
        while True:
            try:
                if datetime.datetime.now().hour >= HOUR:
                    run_once()
                from api_items import purge_trash
                purge_trash()  # what has been in the trash for more than a month
            except Exception as e:  # must never stop the app
                print(f'[reminders] error: {e}', flush=True)
            time.sleep(600)

    def timed():
        while True:
            try:
                push_due()
            except Exception as e:
                print(f'[reminders] push error: {e}', flush=True)
            time.sleep(60 - datetime.datetime.now().second)

    threading.Thread(target=daily, daemon=True, name='reminders').start()
    threading.Thread(target=timed, daemon=True, name='timed-reminders').start()

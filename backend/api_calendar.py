"""Calendar integration: a private iCal (.ics) address per user.

Google Calendar → "Other calendars" → "From URL" subscribes to it and refreshes it periodically
(Google decides how often: usually every few hours). No Google account linking is needed, and it
works the same with Apple Calendar, Outlook and any other calendar app."""
import datetime
import os
import secrets
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import Blueprint, Response, abort, g, jsonify, request

import db
import i18n
from auth import BASE_URL, rate_limit
from common import body

bp = Blueprint('calendar', __name__)


def local_zone():
    try:
        return ZoneInfo(os.environ.get('TZ') or 'Europe/Rome')
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo('UTC')


def _base():
    return BASE_URL or request.host_url.rstrip('/')


def _feed_json(row):
    url = f"{_base()}/api/ical/{row['token']}.ics"
    return {'url': url, 'webcal': 'webcal://' + url.split('://', 1)[1], 'scope': row['scope']}


@bp.get('/calendar/feed')
def get_feed():
    """The user's feed address, created on first request."""
    with db.transaction() as conn:
        row = conn.execute('SELECT * FROM calendar_feeds WHERE user_id = ?', (g.user['id'],)).fetchone()
        if not row:
            conn.execute('INSERT INTO calendar_feeds (user_id, family_id, token) VALUES (?,?,?)',
                         (g.user['id'], g.family_id, secrets.token_urlsafe(24)))
        elif row['family_id'] != g.family_id:
            conn.execute('UPDATE calendar_feeds SET family_id = ? WHERE user_id = ?', (g.family_id, g.user['id']))
        row = conn.execute('SELECT * FROM calendar_feeds WHERE user_id = ?', (g.user['id'],)).fetchone()
    return jsonify(_feed_json(row))


@bp.put('/calendar/feed')
def update_feed():
    """scope: 'mine' (assigned to me or to anyone) or 'all'; regenerate=true makes a new address
    (the old one stops working: useful if it was shared by mistake)."""
    d = body()
    get_feed()  # make sure it exists
    with db.transaction() as conn:
        if d.get('scope') is not None:
            if d['scope'] not in db.FEED_SCOPES:
                abort(400, 'Invalid scope')
            conn.execute('UPDATE calendar_feeds SET scope = ? WHERE user_id = ?', (d['scope'], g.user['id']))
        if d.get('regenerate'):
            conn.execute('UPDATE calendar_feeds SET token = ? WHERE user_id = ?', (secrets.token_urlsafe(24), g.user['id']))
        row = conn.execute('SELECT * FROM calendar_feeds WHERE user_id = ?', (g.user['id'],)).fetchone()
    return jsonify(_feed_json(row))


# ---------- The .ics file (public: the secret token is the authorization) ----------

def _escape(s):
    return str(s).replace('\\', '\\\\').replace(';', '\\;').replace(',', '\\,').replace('\r\n', '\\n').replace('\n', '\\n')


def _fold(line):
    """Lines longer than 75 octets are split (RFC 5545 §3.1)."""
    raw = line.encode('utf-8')
    if len(raw) <= 75:
        return line
    parts, start, limit = [], 0, 75
    while start < len(raw):
        end = min(start + limit, len(raw))
        while end < len(raw) and (raw[end] & 0xC0) == 0x80:  # don't cut a UTF-8 character in half
            end -= 1
        parts.append(raw[start:end].decode('utf-8'))
        start, limit = end, 74
    return '\r\n '.join(parts)


def _utc(date_str, time_str, zone):
    local = datetime.datetime.combine(datetime.date.fromisoformat(date_str), datetime.time.fromisoformat(time_str), zone)
    return local.astimezone(datetime.timezone.utc)


def _stamp(dt):
    return dt.strftime('%Y%m%dT%H%M%SZ')


def build_ics(conn, feed, lang):
    zone = local_zone()
    family = conn.execute('SELECT name FROM families WHERE id = ?', (feed['family_id'],)).fetchone()
    names = {r['id']: r['name'] for r in conn.execute(
        'SELECT u.id, u.name FROM members m JOIN users u ON u.id = m.user_id WHERE m.family_id = ?', (feed['family_id'],))}
    people = {r['id']: r['name'] for r in conn.execute('SELECT id, name FROM people WHERE family_id = ?', (feed['family_id'],))}
    # Birthdays are dated with the birth date and repeat every year (RRULE), so they are always included
    where = 'family_id = ? AND deleted_at IS NULL AND due_date IS NOT NULL AND (done_at IS NULL OR kind = \'appointment\') ' \
            "AND (kind = 'birthday' OR COALESCE(end_date, due_date) >= date('now', '-180 days'))"
    params = [feed['family_id']]
    if feed['scope'] == 'mine':
        where += ' AND (assignee_id IS NULL OR assignee_id = ?)'
        params.append(feed['user_id'])
    items = conn.execute(f'SELECT * FROM items WHERE {where} ORDER BY due_date', params).fetchall()
    checks = {}
    for r in conn.execute('''SELECT item_id, text FROM item_checks WHERE item_id IN
                             (SELECT id FROM items WHERE family_id = ?) ORDER BY position, id''', (feed['family_id'],)):
        checks.setdefault(r['item_id'], []).append(r['text'])

    now = _stamp(datetime.datetime.now(datetime.timezone.utc))
    host = (BASE_URL or request.host_url).split('://')[-1].strip('/').split('/')[0].split(':')[0] or 'dotrack'
    lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//doTrack//IT', 'CALSCALE:GREGORIAN', 'METHOD:PUBLISH',
             f'X-WR-CALNAME:{_escape("doTrack – " + (family["name"] if family else ""))}',
             'X-PUBLISHED-TTL:PT1H', 'REFRESH-INTERVAL;VALUE=DURATION:PT1H']
    for it in items:
        summary = it['title']
        if it['assignee_id'] and feed['scope'] == 'all' and it['assignee_id'] in names:
            summary += f" ({names[it['assignee_id']]})"
        elif it['person_id'] in people:
            summary += f" ({people[it['person_id']]})"
        summary = {'deadline': '⏰ ', 'birthday': '🎂 ', 'note': '📌 '}.get(it['kind'], '') + summary
        desc = []
        if it['subject']:
            desc.append(f"{i18n.tr('About', lang)}: {it['subject']}")
        if it['kind'] != 'birthday':
            desc.append(f"{i18n.tr('Category', lang)}: {i18n.label(it['category'], lang)}")
        if it['notes']:
            desc += ['', it['notes']]
        if checks.get(it['id']):
            heading = i18n.tr('Questions to ask', lang) if it['kind'] == 'appointment' else i18n.tr('Checklist', lang)
            desc += ['', heading + ':'] + [f'• {c}' for c in checks[it['id']]]
        desc += ['', f"{BASE_URL or request.host_url.rstrip('/')}/#/item/{it['id']}"]
        lines += ['BEGIN:VEVENT', f"UID:item-{it['id']}@{host}", f'DTSTAMP:{now}',
                  f"LAST-MODIFIED:{it['updated_at'].replace('-', '').replace(':', '').replace(' ', 'T')}Z"]
        if it['due_time']:
            start = _utc(it['due_date'], it['due_time'], zone)
            end = _utc(it['due_date'], it['end_time'], zone) if it['end_time'] else start + datetime.timedelta(hours=1)
            if end <= start:
                end = start + datetime.timedelta(hours=1)
            lines += [f'DTSTART:{_stamp(start)}', f'DTEND:{_stamp(end)}']
        else:
            day = datetime.date.fromisoformat(it['due_date'])
            last = datetime.date.fromisoformat(it['end_date']) if it['end_date'] else day
            lines += [f"DTSTART;VALUE=DATE:{day.strftime('%Y%m%d')}",
                      f"DTEND;VALUE=DATE:{(last + datetime.timedelta(days=1)).strftime('%Y%m%d')}",
                      'TRANSP:TRANSPARENT']
            if it['kind'] == 'birthday':
                # 29 February: on the last day of February in the other years
                lines.append('RRULE:FREQ=YEARLY;BYMONTH=2;BYMONTHDAY=-1' if (day.month, day.day) == (2, 29) else 'RRULE:FREQ=YEARLY')
        lines += [f'SUMMARY:{_escape(summary)}', f"DESCRIPTION:{_escape(chr(10).join(desc))}"]
        if it['location']:
            lines.append(f"LOCATION:{_escape(it['location'])}")
        if it['done_at']:
            lines.append('STATUS:CONFIRMED')
        if it['remind_days'] is not None and not it['done_at']:
            trigger = f"-P{it['remind_days']}D" if it['remind_days'] else ('-PT1H' if it['due_time'] else 'PT9H')
            lines += ['BEGIN:VALARM', 'ACTION:DISPLAY', f'DESCRIPTION:{_escape(it["title"])}', f'TRIGGER:{trigger}', 'END:VALARM']
        lines.append('END:VEVENT')
    lines.append('END:VCALENDAR')
    return '\r\n'.join(_fold(line) for line in lines) + '\r\n'


@bp.get('/ical/<token>.ics')
def ical(token):
    rate_limit(f'ical:{request.remote_addr}', 120, 3600)
    if len(token) > 64:
        abort(404, 'Calendar not found')
    with db.transaction() as conn:
        feed = conn.execute('''SELECT f.*, u.language FROM calendar_feeds f JOIN users u ON u.id = f.user_id
                               JOIN members m ON m.user_id = f.user_id AND m.family_id = f.family_id
                               WHERE f.token = ?''', (token,)).fetchone()
        if not feed:
            abort(404, 'Calendar not found')
        ics = build_ics(conn, feed, feed['language'])
    resp = Response(ics, mimetype='text/calendar')
    resp.headers['Content-Disposition'] = 'inline; filename="dotrack.ics"'
    resp.headers['Cache-Control'] = 'no-cache'
    return resp

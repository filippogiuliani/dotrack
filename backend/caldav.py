"""CalDAV server: two-way sync with phone and desktop apps (DAVx⁵ + Tasks.org / jtx Board on Android,
Calendar and Reminders on iPhone/Mac, Thunderbird…).

Each user sees, for each family they belong to, one calendar with the items that are in no list ("doTrack")
and one calendar per list. To-dos and deadlines are VTODOs; appointments, notices and birthdays are VEVENTs.

Signing in uses the email and an *app password* created in the Family page (never the account password):
it can be revoked on its own, and works for accounts that sign in with Google.

What has no place in iCalendar (who is in charge, category, "about", questions and answers, attachments,
comments) is kept as it is when a client sends a change."""
import datetime
import functools
import hashlib
import re
import secrets
import xml.etree.ElementTree as ET
from urllib.parse import unquote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import Blueprint, Response, abort, g, jsonify, request
from werkzeug.exceptions import HTTPException

import api_items
import db
import reminders
from api_calendar import _escape, _fold, local_zone
from auth import BASE_URL, client_ip, rate_limit
from common import body, text

dav = Blueprint('caldav', __name__)       # /dav/… and /.well-known/caldav
bp = Blueprint('caldav_api', __name__)    # /api/caldav/… (app passwords, settings page)

NS = {'d': 'DAV:', 'c': 'urn:ietf:params:xml:ns:caldav', 'cs': 'http://calendarserver.org/ns/', 'ic': 'http://apple.com/ns/ical/'}
for _p, _u in NS.items():
    ET.register_namespace({'d': 'D', 'c': 'C', 'cs': 'CS', 'ic': 'IC'}[_p], _u)
D, C, CS, IC = ('{%s}' % NS[k] for k in ('d', 'c', 'cs', 'ic'))

COLOR_HEX = {'blue': '#2563EB', 'green': '#16A34A', 'red': '#DC2626', 'orange': '#EA580C', 'yellow': '#CA8A04',
             'purple': '#7C3AED', 'pink': '#DB2777', 'teal': '#0D9488', 'gray': '#6B7280'}
MAX_ICS = 256 * 1024
EVENT_KINDS = ('appointment', 'note', 'birthday')


# ======================================================================
# App passwords (JSON API, signed in with the session)
# ======================================================================

def _hash(secret):
    return hashlib.sha256(secret.encode()).hexdigest()


def dav_url():
    return f"{BASE_URL or request.host_url.rstrip('/')}/dav/"


@bp.get('/caldav')
def info():
    with db.transaction() as conn:
        rows = [dict(r) for r in conn.execute(
            'SELECT id, name, last_used_at, created_at FROM app_passwords WHERE user_id = ? ORDER BY id', (g.user['id'],))]
    return jsonify(url=dav_url(), username=g.user['email'], passwords=rows)


@bp.post('/caldav/passwords')
def create_password():
    """A new app password, shown only now (only its hash is kept)."""
    name = text(body().get('name'), 60) or 'CalDAV'
    secret = '-'.join(secrets.token_hex(2) + secrets.token_hex(2) for _ in range(4))  # e.g. 1a2b3c4d-…, easy to type
    with db.transaction() as conn:
        if conn.execute('SELECT COUNT(*) FROM app_passwords WHERE user_id = ?', (g.user['id'],)).fetchone()[0] >= 20:
            abort(400, 'Too many app passwords')
        conn.execute('INSERT INTO app_passwords (user_id, name, hash) VALUES (?,?,?)', (g.user['id'], name, _hash(secret)))
    return jsonify(password=secret, username=g.user['email'], url=dav_url()), 201


@bp.delete('/caldav/passwords/<int:pid>')
def delete_password(pid):
    with db.transaction() as conn:
        conn.execute('DELETE FROM app_passwords WHERE id = ? AND user_id = ?', (pid, g.user['id']))
    return info()


# ======================================================================
# iCalendar: reading and writing
# ======================================================================

def _unescape(v):
    return re.sub(r'\\([\\;,nN])', lambda m: '\n' if m.group(1) in 'nN' else m.group(1), v)


def _split_prop(line):
    """'DTSTART;TZID="Europe/Rome":2026…' -> ('DTSTART', {'TZID': 'Europe/Rome'}, '2026…')"""
    i, quoted = 0, False
    while i < len(line):
        ch = line[i]
        if ch == '"':
            quoted = not quoted
        elif ch == ':' and not quoted:
            break
        i += 1
    head, value = line[:i], line[i + 1:]
    parts = re.findall(r'(?:[^;"]|"[^"]*")+', head)
    name = parts[0].upper() if parts else ''
    params = {}
    for p in parts[1:]:
        if '=' in p:
            k, v = p.split('=', 1)
            params[k.upper()] = v.strip('"')
    return name, params, value


def parse_ics(data):
    """Tree of components: {'name', 'props': [(name, params, value)], 'subs': [...]}"""
    data = data.replace('\r\n', '\n').replace('\r', '\n')
    lines = re.sub(r'\n[ \t]', '', data).split('\n')
    root = {'name': 'ROOT', 'props': [], 'subs': []}
    stack = [root]
    for line in lines:
        if not line.strip():
            continue
        name, params, value = _split_prop(line)
        if name == 'BEGIN':
            comp = {'name': value.strip().upper(), 'props': [], 'subs': []}
            stack[-1]['subs'].append(comp)
            stack.append(comp)
        elif name == 'END':
            if len(stack) > 1:
                stack.pop()
        else:
            stack[-1]['props'].append((name, params, value))
    return root


def _prop(comp, name):
    for n, params, value in comp['props']:
        if n == name:
            return params, value
    return None, None


def _zone(params):
    tz = (params or {}).get('TZID')
    if tz:
        try:
            return ZoneInfo(tz.strip('/'))
        except (ZoneInfoNotFoundError, ValueError):
            pass
    return local_zone()


def _when(params, value):
    """(date, 'HH:MM' or None) in local time from a DATE or DATE-TIME value."""
    value = (value or '').strip()
    if not value:
        return None, None
    try:
        if (params or {}).get('VALUE') == 'DATE' or len(value) == 8:
            return datetime.datetime.strptime(value[:8], '%Y%m%d').date(), None
        dt = datetime.datetime.strptime(value[:15], '%Y%m%dT%H%M%S')
    except ValueError:
        return None, None
    if value.endswith('Z'):
        dt = dt.replace(tzinfo=datetime.timezone.utc).astimezone(local_zone())
    elif (params or {}).get('TZID'):
        dt = dt.replace(tzinfo=_zone(params)).astimezone(local_zone())
    return dt.date(), dt.strftime('%H:%M')


DURATION_RE = re.compile(r'^([+-])?P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$')


def _duration(value):
    m = DURATION_RE.match((value or '').strip())
    if not m:
        return None
    sign, w, d, h, mi, s = m.groups()
    delta = datetime.timedelta(weeks=int(w or 0), days=int(d or 0), hours=int(h or 0), minutes=int(mi or 0), seconds=int(s or 0))
    return -delta if sign == '-' else delta


def _alarm(comp, due_date, due_time):
    """(remind_days, remind_time) from the first VALARM, or (None, None)."""
    alarm = next((s for s in comp['subs'] if s['name'] == 'VALARM'), None)
    if not alarm or not due_date:
        return None, None
    params, value = _prop(alarm, 'TRIGGER')
    if value is None:
        return None, None
    if (params or {}).get('VALUE') == 'DATE-TIME':
        day, at = _when(params, value)
        if not day:
            return None, None
        moment = datetime.datetime.combine(day, datetime.time.fromisoformat(at or '09:00'))
    else:
        delta = _duration(value)
        if delta is None:
            return None, None
        start = datetime.datetime.combine(due_date, datetime.time.fromisoformat(due_time) if due_time else datetime.time())
        moment = start + delta
    days = (due_date - moment.date()).days
    if not 0 <= days <= 365:
        return None, None
    at = moment.strftime('%H:%M')
    # The app's default (the morning hour) is not stored as an explicit time
    if at == f'{reminders.HOUR:02d}:00' and not (days == 0 and due_time):
        at = None
    return days, at


RRULE_UNITS = {'DAILY': 'day', 'WEEKLY': 'week', 'MONTHLY': 'month', 'YEARLY': 'year'}


def _rrule(value):
    if not value:
        return None, None
    parts = dict(p.split('=', 1) for p in value.upper().split(';') if '=' in p)
    unit = RRULE_UNITS.get(parts.get('FREQ'))
    if not unit:
        return None, None
    try:
        every = max(1, min(int(parts.get('INTERVAL', '1')), 100))
    except ValueError:
        every = 1
    return unit, every


def _priority(value):
    try:
        p = int(value)
    except (TypeError, ValueError):
        return 0
    return 1 if 1 <= p <= 4 else -1 if 6 <= p <= 9 else 0


def fields_from_ics(comp, current):
    """The item (as sent to the API) described by a VTODO/VEVENT, on top of the current values."""
    d = dict(current or {})
    event = comp['name'] == 'VEVENT'
    _, summary = _prop(comp, 'SUMMARY')
    d['title'] = _unescape(summary or '').strip()
    # Birthdays and notices carry an emoji in front, added by us
    d['title'] = re.sub(r'^(⏰|🎂|📌)\s*', '', d['title']) or d.get('title') or '?'
    _, desc = _prop(comp, 'DESCRIPTION')
    d['notes'] = _unescape(desc or '').strip()
    _, loc = _prop(comp, 'LOCATION')
    d['location'] = _unescape(loc or '').strip()
    _, prio = _prop(comp, 'PRIORITY')
    d['priority'] = _priority(prio)
    _, rrule = _prop(comp, 'RRULE')
    d['recur_unit'], d['recur_every'] = _rrule(rrule)
    _, cats = _prop(comp, 'CATEGORIES')
    labels = [_unescape(c).strip() for c in re.split(r'(?<!\\),', cats or '') if c.strip()]
    d['labels'] = labels[:api_items.MAX_LABELS]

    if event:
        sp, sv = _prop(comp, 'DTSTART')
        start, start_time = _when(sp, sv)
        ep, ev = _prop(comp, 'DTEND')
        end, end_time = _when(ep, ev)
        if not ev:
            dp, dv = _prop(comp, 'DURATION')
            delta = _duration(dv)
            if start and delta:
                if start_time:
                    e = datetime.datetime.combine(start, datetime.time.fromisoformat(start_time)) + delta
                    end, end_time = e.date(), e.strftime('%H:%M')
                else:
                    end = start + delta
        kind = d.get('kind') if d.get('kind') in EVENT_KINDS else None
        multi_day = start and not start_time and end and (end - start).days > 1
        if not kind:
            kind = 'note' if multi_day else 'appointment'
        if kind == 'birthday':
            d['recur_unit'] = d['recur_every'] = None
        d['kind'] = kind
        d['due_date'] = start.isoformat() if start else None
        d['due_time'] = start_time
        d['end_time'] = end_time if start_time and end == start else None
        d['end_date'] = (end - datetime.timedelta(days=1)).isoformat() if kind == 'note' and end and not start_time else None
        done = False
    else:
        if d.get('kind') not in ('task', 'deadline'):
            d['kind'] = 'task'
        dp, dv = _prop(comp, 'DUE')
        if not dv:
            dp, dv = _prop(comp, 'DTSTART')
        due, due_time = _when(dp, dv)
        d['due_date'] = due.isoformat() if due else None
        d['due_time'] = due_time
        d['end_time'] = d['end_date'] = None
        _, status = _prop(comp, 'STATUS')
        _, completed = _prop(comp, 'COMPLETED')
        done = (status or '').upper() == 'COMPLETED' or bool(completed)

    due = datetime.date.fromisoformat(d['due_date']) if d.get('due_date') else None
    d['remind_days'], d['remind_time'] = _alarm(comp, due, d.get('due_time'))
    if d['remind_days'] is not None and d['remind_time'] and d.get('due_time') and d['remind_days'] == 0:
        # "One hour before" is the app's default for same-day reminders
        start = datetime.datetime.combine(due, datetime.time.fromisoformat(d['due_time']))
        if (start - datetime.timedelta(hours=1)).strftime('%H:%M') == d['remind_time']:
            d['remind_time'] = None
    return d, done


# ---------- Writing ----------

def _stamp(dt):
    return dt.strftime('%Y%m%dT%H%M%SZ')


def _db_time(s):
    """'2026-11-09 10:00:00' (UTC, from SQLite) -> iCalendar UTC stamp."""
    return (s or '').replace('-', '').replace(':', '').replace(' ', 'T')[:15] + 'Z'


def _local(date_str, time_str):
    return datetime.datetime.combine(datetime.date.fromisoformat(date_str), datetime.time.fromisoformat(time_str))


def _fmt_local(dt):
    return dt.strftime('%Y%m%dT%H%M%S')


def _nth_weekday(year, month, weekday, nth):
    """Date of the nth (or last, nth=-1) `weekday` (0 = Monday) of a month."""
    if nth > 0:
        d = datetime.date(year, month, 1)
        d += datetime.timedelta(days=(weekday - d.weekday()) % 7 + 7 * (nth - 1))
    else:
        d = datetime.date(year + month // 12, month % 12 + 1, 1) - datetime.timedelta(days=1)
        d -= datetime.timedelta(days=(d.weekday() - weekday) % 7)
    return d


@functools.lru_cache(maxsize=16)
def _vtimezone(key, year):
    zone = ZoneInfo(key) if key != 'UTC' else datetime.timezone.utc
    utc = datetime.timezone.utc

    def off(td):
        mins = int(td.total_seconds() // 60)
        return f"{'+' if mins >= 0 else '-'}{abs(mins) // 60:02d}{abs(mins) % 60:02d}"

    # Changes of offset during the year, found hour by hour
    t, end = datetime.datetime(year, 1, 1, tzinfo=utc), datetime.datetime(year + 1, 1, 1, tzinfo=utc)
    prev = t.astimezone(zone).utcoffset()
    changes = []
    while t < end:
        t += datetime.timedelta(hours=1)
        local = t.astimezone(zone)
        if local.utcoffset() != prev:
            changes.append(((t + prev).replace(tzinfo=None), prev, local.utcoffset(), bool(local.dst())))
            prev = local.utcoffset()
    lines = ['BEGIN:VTIMEZONE', f'TZID:{key}']
    if not changes:
        o = off(prev)
        lines += ['BEGIN:STANDARD', 'DTSTART:19700101T000000', f'TZOFFSETFROM:{o}', f'TZOFFSETTO:{o}', 'END:STANDARD']
    for wall, before, after, dst in changes:
        last = (wall + datetime.timedelta(days=7)).month != wall.month
        nth = -1 if last else (wall.day - 1) // 7 + 1
        first = _nth_weekday(1970, wall.month, wall.weekday(), nth)
        part = 'DAYLIGHT' if dst else 'STANDARD'
        day = ['MO', 'TU', 'WE', 'TH', 'FR', 'SA', 'SU'][wall.weekday()]
        lines += [f'BEGIN:{part}', f"DTSTART:{first.strftime('%Y%m%d')}T{wall.strftime('%H%M%S')}",
                  f'RRULE:FREQ=YEARLY;BYMONTH={wall.month};BYDAY={nth}{day}',
                  f'TZOFFSETFROM:{off(before)}', f'TZOFFSETTO:{off(after)}', f'END:{part}']
    lines.append('END:VTIMEZONE')
    return tuple(lines)


def vtimezone(zone, year):
    """VTIMEZONE for the local zone, with yearly rules taken from that year's changes."""
    return list(_vtimezone(getattr(zone, 'key', 'UTC'), year))


def uid_of(item, host):
    return item['caldav_uid'] or f"item-{item['id']}@{host}"


def name_of(item):
    return item['caldav_name'] or f"item-{item['id']}.ics"


def _host():
    return (BASE_URL or request.host_url).split('://')[-1].strip('/').split('/')[0].split(':')[0] or 'dotrack'


def item_ics(item, labels, host):
    zone = local_zone()
    tzid = getattr(zone, 'key', 'UTC')
    event = item['kind'] in EVENT_KINDS
    comp = 'VEVENT' if event else 'VTODO'
    lines = [f'BEGIN:{comp}', f'UID:{_escape(uid_of(item, host))}', f"DTSTAMP:{_db_time(item['updated_at'])}",
             f"CREATED:{_db_time(item['created_at'])}", f"LAST-MODIFIED:{_db_time(item['updated_at'])}"]
    summary = {'birthday': '🎂 ', 'note': '📌 '}.get(item['kind'], '') + item['title']
    lines.append(f'SUMMARY:{_escape(summary)}')
    if item['notes']:
        lines.append(f"DESCRIPTION:{_escape(item['notes'])}")
    if item['location']:
        lines.append(f"LOCATION:{_escape(item['location'])}")
    if item['priority']:
        lines.append(f"PRIORITY:{1 if item['priority'] > 0 else 9}")
    names = [labels[i] for i in item['labels'] if i in labels]
    if names:
        lines.append('CATEGORIES:' + ','.join(_escape(n) for n in names))
    due = item['due_date']
    if event and due:
        if item['due_time']:
            start = _local(due, item['due_time'])
            end = _local(due, item['end_time']) if item['end_time'] else None
            if not end or end <= start:
                end = start + datetime.timedelta(hours=1)
            lines += [f'DTSTART;TZID={tzid}:{_fmt_local(start)}', f'DTEND;TZID={tzid}:{_fmt_local(end)}']
        else:
            day = datetime.date.fromisoformat(due)
            last = datetime.date.fromisoformat(item['end_date']) if item['end_date'] else day
            lines += [f"DTSTART;VALUE=DATE:{day.strftime('%Y%m%d')}",
                      f"DTEND;VALUE=DATE:{(last + datetime.timedelta(days=1)).strftime('%Y%m%d')}", 'TRANSP:TRANSPARENT']
        if item['kind'] == 'birthday':
            day = datetime.date.fromisoformat(due)
            lines.append('RRULE:FREQ=YEARLY;BYMONTH=2;BYMONTHDAY=-1' if (day.month, day.day) == (2, 29) else 'RRULE:FREQ=YEARLY')
    elif due:
        if item['due_time']:
            lines.append(f"DUE;TZID={tzid}:{_fmt_local(_local(due, item['due_time']))}")
        else:
            lines.append(f"DUE;VALUE=DATE:{due.replace('-', '')}")
    if item['recur_unit'] and due and item['kind'] != 'birthday':
        freq = {v: k for k, v in RRULE_UNITS.items()}[item['recur_unit']]
        lines.append(f"RRULE:FREQ={freq}" + (f";INTERVAL={item['recur_every']}" if (item['recur_every'] or 1) > 1 else ''))
    if not event:
        if item['done_at']:
            lines += ['STATUS:COMPLETED', 'PERCENT-COMPLETE:100', f"COMPLETED:{_db_time(item['done_at'])}"]
        else:
            lines.append('STATUS:NEEDS-ACTION')
    if item['remind_days'] is not None and due and not item['done_at']:
        start = _local(due, item['due_time'] or '00:00')
        day = datetime.date.fromisoformat(due) - datetime.timedelta(days=item['remind_days'])
        if item['remind_time']:
            moment = datetime.datetime.combine(day, datetime.time.fromisoformat(item['remind_time']))
        elif item['remind_days'] == 0 and item['due_time']:
            moment = start - datetime.timedelta(hours=1)
        else:
            moment = datetime.datetime.combine(day, datetime.time(reminders.HOUR))
        delta = int((moment - start).total_seconds() // 60)
        sign = '-' if delta < 0 else ''
        delta = abs(delta)
        trigger = f'{sign}P{delta // 1440}DT{(delta % 1440) // 60}H{delta % 60}M'
        lines += ['BEGIN:VALARM', 'ACTION:DISPLAY', f'DESCRIPTION:{_escape(item["title"])}', f'TRIGGER:{trigger}', 'END:VALARM']
    lines.append(f'END:{comp}')
    return lines


def resource(item, labels, host):
    """The full .ics of one item, and its ETag."""
    zone = local_zone()
    lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//doTrack//CalDAV//IT', 'CALSCALE:GREGORIAN']
    if item['due_time'] and item['due_date']:
        lines += vtimezone(zone, int(item['due_date'][:4]))
    lines += item_ics(item, labels, host)
    lines.append('END:VCALENDAR')
    ics = '\r\n'.join(_fold(line) for line in lines) + '\r\n'
    return ics, '"' + hashlib.sha1(ics.encode()).hexdigest()[:20] + '"'


# ======================================================================
# Requests
# ======================================================================

def _authenticate():
    """g.user from HTTP Basic (email + app password), otherwise a 401 that asks for credentials."""
    a = request.authorization
    if a and a.type == 'basic' and a.username and a.password:
        with db.transaction() as conn:
            row = conn.execute('''SELECT u.id, u.name, u.email, u.language, p.id AS pid, p.last_used_at
                                  FROM app_passwords p JOIN users u ON u.id = p.user_id
                                  WHERE p.hash = ? AND u.email = ? COLLATE NOCASE''',
                               (_hash(a.password.strip()), a.username.strip())).fetchone()
            if row:
                hour_ago = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1)).strftime('%Y-%m-%d %H:%M:%S')
                if not row['last_used_at'] or row['last_used_at'] < hour_ago:
                    conn.execute("UPDATE app_passwords SET last_used_at = datetime('now') WHERE id = ?", (row['pid'],))
                g.user = {'id': row['id'], 'name': row['name'], 'email': row['email'], 'language': row['language']}
                g.families = [dict(r) for r in conn.execute(
                    '''SELECT f.id, f.name FROM members m JOIN families f ON f.id = m.family_id
                       WHERE m.user_id = ? ORDER BY m.created_at''', (row['id'],))]
                return None
        rate_limit(f'dav:{client_ip()}', 30, 900)
    resp = Response('Authentication required', 401)
    resp.headers['WWW-Authenticate'] = 'Basic realm="doTrack", charset="UTF-8"'
    return resp


def _base():
    return f"/dav/calendars/{g.user['id']}/"


def _collections(conn):
    """[(id, name, color, family_id, list_id)] for the user: per family the "doTrack" calendar and its lists."""
    out = []
    multi = len(g.families) > 1
    for f in g.families:
        out.append((f"f{f['id']}", 'doTrack' + (f" – {f['name']}" if multi else ''), 'blue', f['id'], None))
        for r in conn.execute('SELECT id, name, color FROM lists WHERE family_id = ? AND archived = 0 AND template = 0 ORDER BY position, id', (f['id'],)):
            out.append((f"l{r['id']}", r['name'] + (f" ({f['name']})" if multi else ''), r['color'], f['id'], r['id']))
    return out


def _collection(conn, coll):
    found = next((c for c in _collections(conn) if c[0] == coll), None)
    if not found:
        abort(404)
    g.family_id = found[3]
    return found


def _items(conn, coll):
    """Items of a collection, open ones plus those done/past recently."""
    _, _, _, family_id, list_id = coll
    g.family_id = family_id
    where = ('i.list_id = ?' if list_id else 'i.list_id IS NULL') + \
        " AND (i.done_at IS NULL OR i.done_at > datetime('now', '-30 days'))" \
        " AND (i.kind = 'birthday' OR i.due_date IS NULL OR COALESCE(i.end_date, i.due_date) >= date('now', '-180 days'))"
    return api_items._load(conn, where, (list_id,) if list_id else (), dav=True)


def _labels(conn, family_id):
    return {r['id']: r['name'] for r in conn.execute('SELECT id, name FROM labels WHERE family_id = ?', (family_id,))}


def _find(conn, coll, name):
    """The item stored under resource `name` in a collection, or None."""
    _, _, _, family_id, list_id = coll
    row = conn.execute('SELECT id FROM items WHERE family_id = ? AND caldav_name = ?', (family_id, name)).fetchone()
    if not row:
        m = re.fullmatch(r'item-(\d+)\.ics', name)
        if m:
            row = conn.execute('SELECT id FROM items WHERE family_id = ? AND id = ? AND caldav_name IS NULL',
                               (family_id, int(m.group(1)))).fetchone()
    if not row:
        return None
    found = api_items._load(conn, 'i.id = ?', (row['id'],), dav=True)
    if not found or found[0]['list_id'] != list_id:
        return None
    return found[0]


# ---------- XML ----------

def _requested(root):
    """Names of the properties asked for in a PROPFIND/REPORT body; None = all."""
    if root is None:
        return None
    prop = root.find(D + 'prop')
    if prop is None:
        return None
    return [child.tag for child in prop]


def _multistatus(responses):
    ms = ET.Element(D + 'multistatus')
    for href, found, missing in responses:
        r = ET.SubElement(ms, D + 'response')
        ET.SubElement(r, D + 'href').text = href
        if found:
            ps = ET.SubElement(r, D + 'propstat')
            p = ET.SubElement(ps, D + 'prop')
            for tag, value in found:
                el = ET.SubElement(p, tag)
                if callable(value):
                    value(el)
                elif value is not None:
                    el.text = str(value)
            ET.SubElement(ps, D + 'status').text = 'HTTP/1.1 200 OK'
        if missing:
            ps = ET.SubElement(r, D + 'propstat')
            p = ET.SubElement(ps, D + 'prop')
            for tag in missing:
                ET.SubElement(p, tag)
            ET.SubElement(ps, D + 'status').text = 'HTTP/1.1 404 Not Found'
        if not found and not missing:
            ET.SubElement(r, D + 'status').text = 'HTTP/1.1 404 Not Found'
    xml = b'<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(ms, encoding='utf-8')
    return Response(xml, 207, content_type='application/xml; charset=utf-8')


def _href(path):
    def fill(el):
        ET.SubElement(el, D + 'href').text = path
    return fill


def _children(*tags):
    def fill(el):
        for t in tags:
            ET.SubElement(el, t)
    return fill


def _comps(*names):
    def fill(el):
        for n in names:
            ET.SubElement(el, C + 'comp', name=n)
    return fill


def _reports(el):
    for name in (C + 'calendar-multiget', C + 'calendar-query'):
        r = ET.SubElement(ET.SubElement(el, D + 'supported-report'), D + 'report')
        ET.SubElement(r, name)


def _privileges(el):
    for p in ('read', 'write', 'write-content', 'write-properties', 'bind', 'unbind', 'read-current-user-privilege-set'):
        ET.SubElement(ET.SubElement(el, D + 'privilege'), D + p)


def _answer(props, requested):
    """Split the available `props` (tag -> value) into found/missing for the requested names."""
    if requested is None:
        return list(props.items()), []
    found = [(t, props[t]) for t in requested if t in props]
    missing = [t for t in requested if t not in props]
    return found, missing


def _principal_props():
    uid = g.user['id']
    return {
        D + 'resourcetype': _children(D + 'principal'),
        D + 'displayname': g.user['name'],
        D + 'current-user-principal': _href(f'/dav/principals/{uid}/'),
        D + 'principal-URL': _href(f'/dav/principals/{uid}/'),
        C + 'calendar-home-set': _href(_base()),
        C + 'calendar-user-address-set': _href('mailto:' + g.user['email']),
    }


def _ctag(conn, coll, items=None):
    items = items if items is not None else _items(conn, coll)
    labels, host = _labels(conn, coll[3]), _host()
    h = hashlib.sha1()
    for it in items:
        h.update(resource(it, labels, host)[1].encode())
        h.update(name_of(it).encode())
    return '"' + h.hexdigest()[:20] + '"'


def _collection_props(conn, coll, items=None):
    cid, name, color, _, list_id = coll
    return {
        D + 'resourcetype': _children(D + 'collection', C + 'calendar'),
        D + 'displayname': name,
        D + 'current-user-principal': _href(f"/dav/principals/{g.user['id']}/"),
        D + 'owner': _href(f"/dav/principals/{g.user['id']}/"),
        D + 'current-user-privilege-set': _privileges,
        D + 'supported-report-set': _reports,
        C + 'supported-calendar-component-set': _comps('VTODO', 'VEVENT'),
        C + 'calendar-description': 'doTrack',
        CS + 'getctag': _ctag(conn, coll, items),
        IC + 'calendar-color': COLOR_HEX.get(color, '#2563EB'),
        IC + 'calendar-order': str(list_id or 0),
        D + 'getcontenttype': None,
    }


def _resource_props(item, labels, host, with_data=True):
    ics, etag = resource(item, labels, host)
    props = {
        D + 'resourcetype': None,
        D + 'getetag': etag,
        D + 'getcontenttype': 'text/calendar; charset=utf-8; component=' + ('VEVENT' if item['kind'] in EVENT_KINDS else 'VTODO'),
        D + 'getcontentlength': str(len(ics.encode())),
    }
    if with_data:
        props[C + 'calendar-data'] = ics
    return props


def _xml_body():
    data = request.get_data(cache=True)
    if not data or not data.strip():
        return None
    if len(data) > 1024 * 1024 or b'<!DOCTYPE' in data or b'<!ENTITY' in data:
        abort(400)
    try:
        return ET.fromstring(data)
    except ET.ParseError:
        abort(400)


def _depth():
    return request.headers.get('Depth', '1' if request.method == 'PROPFIND' else '0')


def _options():
    resp = Response('', 200)
    resp.headers['DAV'] = '1, 3, calendar-access'
    resp.headers['Allow'] = 'OPTIONS, GET, HEAD, PUT, DELETE, PROPFIND, PROPPATCH, REPORT'
    return resp


def _proppatch_ok(href):
    """Clients try to set colours and names: accepted and ignored (names come from the app)."""
    root = _xml_body()
    tags = [child.tag for el in (root.iter(D + 'prop') if root is not None else []) for child in el]
    return _multistatus([(href, [(t, None) for t in tags], [])])


# ======================================================================
# Routes
# ======================================================================

METHODS = ['OPTIONS', 'GET', 'HEAD', 'PUT', 'DELETE', 'PROPFIND', 'PROPPATCH', 'REPORT', 'MKCALENDAR', 'MKCOL', 'MOVE', 'COPY',
           'LOCK', 'UNLOCK', 'POST']


@dav.route('/.well-known/caldav', methods=METHODS, strict_slashes=False)
def well_known():
    resp = Response('', 301)
    resp.headers['Location'] = '/dav/'
    return resp


@dav.before_request
def _auth():
    if request.method == 'OPTIONS' or request.path.startswith('/.well-known/'):
        return None
    return _authenticate()


@dav.errorhandler(HTTPException)
def _error(e):
    return Response(e.description if e.code != 404 else 'Not found', e.code or 500, content_type='text/plain; charset=utf-8')


@dav.route('/dav/', methods=METHODS, strict_slashes=False)
@dav.route('/dav/principals/', methods=METHODS, strict_slashes=False)
def root():
    if request.method == 'OPTIONS':
        return _options()
    if request.method == 'PROPPATCH':
        return _proppatch_ok(request.path)
    if request.method != 'PROPFIND':
        if request.method in ('GET', 'HEAD'):
            return Response('doTrack CalDAV', 200, content_type='text/plain')
        abort(405)
    props = {D + 'resourcetype': _children(D + 'collection'), D + 'displayname': 'doTrack',
             D + 'current-user-principal': _href(f"/dav/principals/{g.user['id']}/"),
             D + 'principal-URL': _href(f"/dav/principals/{g.user['id']}/"),
             C + 'calendar-home-set': _href(_base())}
    found, missing = _answer(props, _requested(_xml_body()))
    return _multistatus([(request.path if request.path.endswith('/') else request.path + '/', found, missing)])


@dav.route('/dav/principals/<int:uid>/', methods=METHODS, strict_slashes=False)
def principal(uid):
    if request.method == 'OPTIONS':
        return _options()
    if uid != g.user['id']:
        abort(403)
    if request.method == 'PROPPATCH':
        return _proppatch_ok(f'/dav/principals/{uid}/')
    if request.method not in ('PROPFIND', 'REPORT'):
        abort(405)
    props = _principal_props()
    found, missing = _answer(props, _requested(_xml_body()))
    return _multistatus([(f'/dav/principals/{uid}/', found, missing)])


@dav.route('/dav/calendars/<int:uid>/', methods=METHODS, strict_slashes=False)
def home(uid):
    if request.method == 'OPTIONS':
        return _options()
    if uid != g.user['id']:
        abort(403)
    if request.method == 'PROPPATCH':
        return _proppatch_ok(_base())
    if request.method in ('MKCALENDAR', 'MKCOL'):
        abort(403, 'Create lists in the app')
    if request.method != 'PROPFIND':
        abort(405)
    requested = _requested(_xml_body())
    home_props = {D + 'resourcetype': _children(D + 'collection'), D + 'displayname': 'doTrack',
                  D + 'current-user-principal': _href(f'/dav/principals/{uid}/'), D + 'owner': _href(f'/dav/principals/{uid}/'),
                  D + 'current-user-privilege-set': _privileges}
    responses = [(_base(), *_answer(home_props, requested))]
    if _depth() != '0':
        with db.transaction() as conn:
            for coll in _collections(conn):
                responses.append((_base() + coll[0] + '/', *_answer(_collection_props(conn, coll), requested)))
    return _multistatus(responses)


@dav.route('/dav/calendars/<int:uid>/<coll>/', methods=METHODS, strict_slashes=False)
def calendar(uid, coll):
    if request.method == 'OPTIONS':
        return _options()
    if uid != g.user['id']:
        abort(403)
    href = _base() + coll + '/'
    if request.method == 'PROPPATCH':
        return _proppatch_ok(href)
    if request.method in ('MKCALENDAR', 'MKCOL'):
        abort(403, 'Create lists in the app')
    if request.method == 'DELETE':
        abort(403, 'Delete lists in the app')
    if request.method not in ('PROPFIND', 'REPORT', 'GET', 'HEAD'):
        abort(405)
    root_el = _xml_body()
    with db.transaction() as conn:
        c = _collection(conn, coll)
        items = _items(conn, c)
        labels, host = _labels(conn, c[3]), _host()
        if request.method in ('GET', 'HEAD'):
            # The whole calendar as one file (handy for a quick look or a backup)
            lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//doTrack//CalDAV//IT']
            lines += vtimezone(local_zone(), datetime.date.today().year)
            for it in items:
                lines += item_ics(it, labels, host)
            lines.append('END:VCALENDAR')
            return Response('\r\n'.join(_fold(x) for x in lines) + '\r\n', content_type='text/calendar; charset=utf-8')
        requested = _requested(root_el)
        if request.method == 'PROPFIND':
            responses = [(href, *_answer(_collection_props(conn, c, items), requested))]
            if _depth() != '0':
                for it in items:
                    props = _resource_props(it, labels, host, with_data=bool(requested and C + 'calendar-data' in requested))
                    responses.append((href + name_of(it), *_answer(props, requested)))
            return _multistatus(responses)
        # REPORT
        if root_el is None:
            abort(400)
        if root_el.tag == C + 'calendar-multiget':
            wanted = [h.text.strip() for h in root_el.iter(D + 'href') if h.text]
            by_name = {name_of(it): it for it in items}
            responses = []
            for h in wanted:
                name = unquote(h.rstrip('/').rsplit('/', 1)[-1])
                it = by_name.get(name) or _find(conn, c, name)
                if it:
                    responses.append((h, *_answer(_resource_props(it, labels, host), requested)))
                else:
                    responses.append((h, [], []))
            return _multistatus(responses)
        if root_el.tag == C + 'calendar-query':
            # Only the component type is filtered; time ranges are ignored (sending a little more is allowed)
            comp = None
            for f in root_el.iter(C + 'comp-filter'):
                if f.get('name') in ('VTODO', 'VEVENT'):
                    comp = f.get('name')
            responses = []
            for it in items:
                is_event = it['kind'] in EVENT_KINDS
                if comp == 'VTODO' and is_event or comp == 'VEVENT' and not is_event:
                    continue
                responses.append((href + name_of(it), *_answer(_resource_props(it, labels, host), requested)))
            return _multistatus(responses)
        abort(403, 'Report not supported')


@dav.route('/dav/calendars/<int:uid>/<coll>/<name>', methods=METHODS)
def item_resource(uid, coll, name):
    if request.method == 'OPTIONS':
        return _options()
    if uid != g.user['id']:
        abort(403)
    if request.method in ('MOVE', 'COPY', 'LOCK', 'UNLOCK', 'MKCALENDAR', 'MKCOL', 'POST'):
        abort(405)
    with db.transaction() as conn:
        c = _collection(conn, coll)
        labels, host = _labels(conn, c[3]), _host()
        item = _find(conn, c, name)
        href = _base() + coll + '/' + name
        if request.method in ('GET', 'HEAD'):
            if not item:
                abort(404)
            ics, etag = resource(item, labels, host)
            resp = Response(ics if request.method == 'GET' else '', content_type='text/calendar; charset=utf-8')
            resp.headers['ETag'] = etag
            return resp
        if request.method == 'PROPFIND':
            if not item:
                abort(404)
            return _multistatus([(href, *_answer(_resource_props(item, labels, host, with_data=False), _requested(_xml_body())))])
        if request.method == 'PROPPATCH':
            return _proppatch_ok(href)
        if request.method == 'REPORT':
            abort(405)
        etag = resource(item, labels, host)[1] if item else None
        if_match, if_none = request.headers.get('If-Match'), request.headers.get('If-None-Match')
        if if_none == '*' and item:
            abort(412)
        if if_match and if_match != '*' and if_match != etag:
            abort(412)
        if if_match and not item:
            abort(412)
        if request.method == 'DELETE':
            if not item:
                abort(404)
            # To the trash, like in the app: it can be restored for a month
            api_items.trash_item(conn, item['id'])
            return Response('', 204)
        if request.method == 'PUT':
            return _put(conn, c, name, item, labels, host)
    abort(405)


def _put(conn, coll, name, item, labels, host):
    data = request.get_data(as_text=True)
    if len(data) > MAX_ICS:
        abort(413)
    cal = parse_ics(data)
    vcal = next((s for s in cal['subs'] if s['name'] == 'VCALENDAR'), None)
    comps = [s for s in (vcal['subs'] if vcal else []) if s['name'] in ('VTODO', 'VEVENT')]
    if not comps:
        abort(415, 'Only VTODO and VEVENT are supported')
    # Recurring events may come with exceptions (RECURRENCE-ID): only the master is used
    comp = next((s for s in comps if _prop(s, 'RECURRENCE-ID')[1] is None), comps[0])
    _, uid = _prop(comp, 'UID')
    uid = (uid or '').strip()[:255] or None
    if not item and uid:
        # Same UID under another name (some clients rename): it is the same item
        m = re.fullmatch(r'item-(\d+)@.*', uid)
        row = conn.execute('SELECT id FROM items WHERE family_id = ? AND caldav_uid = ?', (coll[3], uid)).fetchone()
        if not row and m:
            row = conn.execute('SELECT id FROM items WHERE family_id = ? AND id = ? AND caldav_uid IS NULL',
                               (coll[3], int(m.group(1)))).fetchone()
        if row:
            found = api_items._load(conn, 'i.id = ?', (row['id'],), dav=True)
            item = found[0] if found and found[0]['list_id'] == coll[4] else None
    current = None
    if item:
        current = {k: item[k] for k in ('kind', 'category', 'subject', 'assignee_id', 'person_id', 'recur_from', 'list_id', 'title')}
        current['checks'] = None
    else:
        current = {'kind': None, 'category': 'other', 'subject': '', 'assignee_id': None, 'person_id': None,
                   'recur_from': 'due', 'list_id': coll[4]}
    fields, done = fields_from_ics(comp, current)
    fields['list_id'] = coll[4]
    g.family_id = coll[3]
    f = api_items._fields(conn, fields)
    if item:
        conn.execute(f'UPDATE items SET {", ".join(c + " = ?" for c in f)}, updated_at = datetime(\'now\') WHERE id = ?',
                     (*f.values(), item['id']))
        item_id = item['id']
        api_items._save_labels(conn, item_id, fields['labels'])
        api_items.log(conn, item_id, 'updated')
    else:
        cols = list(f)
        item_id = conn.execute(f'INSERT INTO items (family_id, created_by, caldav_uid, caldav_name, {", ".join(cols)}) '
                               f'VALUES (?, ?, ?, ?, {", ".join("?" * len(cols))})',
                               (coll[3], g.user['id'], uid, name, *f.values())).lastrowid
        api_items._save_labels(conn, item_id, fields['labels'])
        api_items.log(conn, item_id, 'created')
    if item and (item['caldav_name'] != name and name != f"item-{item_id}.ics"):
        conn.execute('UPDATE items SET caldav_name = ? WHERE id = ?', (name, item_id))
    saved = api_items._load(conn, 'i.id = ?', (item_id,), dav=True)[0]
    if f['kind'] not in EVENT_KINDS:
        if done and not saved['done']:
            api_items.complete_item(conn, saved, g.user['id'], coll[3])
        elif not done and saved['done']:
            api_items.reopen_item(conn, item_id, coll[3])
            api_items.log(conn, item_id, 'reopened')
    return Response('', 204 if item else 201)

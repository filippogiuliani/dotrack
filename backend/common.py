"""Helpers shared by the API modules."""
import calendar
import datetime
import re

from flask import abort, g, request

TIME_RE = re.compile(r'^([01]\d|2[0-3]):[0-5]\d$')


def body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        abort(400, 'Invalid request (JSON expected)')
    return data


def valid_date(value, field='date'):
    try:
        return datetime.date.fromisoformat(str(value)).isoformat()
    except ValueError:
        abort(400, f'{field}: invalid date')


def valid_time(value, field='time'):
    """HH:MM, or None when empty."""
    if value in (None, ''):
        return None
    v = str(value)[:5]
    if not TIME_RE.match(v):
        abort(400, f'{field}: invalid time')
    return v


def text(value, max_len=2000):
    return str(value or '').strip()[:max_len]


def rows(cursor):
    return [dict(r) for r in cursor.fetchall()]


def placeholders(values):
    return ','.join('?' * len(values))


def family_member(conn, value):
    """Id of a member of the current family, None for "anyone", otherwise 400."""
    if value in (None, '', 0):
        return None
    try:
        uid = int(value)
    except (TypeError, ValueError):
        abort(400, 'Invalid member')
    if not conn.execute('SELECT 1 FROM members WHERE family_id = ? AND user_id = ?', (g.family_id, uid)).fetchone():
        abort(400, 'Invalid member')
    return uid


def family_person(conn, value):
    """Id of a person (without an account) of the current family, None when empty, otherwise 400."""
    if value in (None, '', 0):
        return None
    try:
        pid = int(value)
    except (TypeError, ValueError):
        abort(400, 'Invalid member')
    if not conn.execute('SELECT 1 FROM people WHERE family_id = ? AND id = ?', (g.family_id, pid)).fetchone():
        abort(400, 'Invalid member')
    return pid


# Birthdays whose year is unknown are stored with this (leap) year
NO_YEAR = 1904


def anniversary(birth, year):
    """The birthday in `year` (29 February becomes the 28th in other years)."""
    return datetime.date(year, birth.month, min(birth.day, calendar.monthrange(year, birth.month)[1]))


def next_birthday(birth_iso, today):
    """Next birthday on or after `today`, and the age then (None when the year is unknown)."""
    birth = datetime.date.fromisoformat(birth_iso)
    day = anniversary(birth, today.year)
    if day < today:
        day = anniversary(birth, today.year + 1)
    return day, (None if birth.year == NO_YEAR else day.year - birth.year)

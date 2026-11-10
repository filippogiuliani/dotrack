"""CalDAV: discovery, reading and two-way changes, as a client like DAVx⁵ or Apple Reminders would do."""
import base64
import xml.etree.ElementTree as ET

import caldav
import reminders
from conftest import ok

D, C, CS = '{DAV:}', '{urn:ietf:params:xml:ns:caldav}', '{http://calendarserver.org/ns/}'


def basic(user, password):
    return {'Authorization': 'Basic ' + base64.b64encode(f'{user}:{password}'.encode()).decode()}


class Dav:
    def __init__(self, client, family):
        self.c = client()
        created = ok(family.c.post('/api/caldav/passwords', json={'name': 'Telefono'}), 201)
        self.h = basic(created['username'], created['password'])
        self.uid = family.uid

    def req(self, method, path, body=None, depth=None, **headers):
        h = {**self.h, **headers}
        if depth is not None:
            h['Depth'] = depth
        return self.c.open(path, method=method, data=body, headers=h)

    def multistatus(self, method, path, body=None, depth='1'):
        r = self.req(method, path, body, depth)
        assert r.status_code == 207, (r.status_code, r.get_data(as_text=True)[:300])
        out = {}
        for resp in ET.fromstring(r.data).findall(D + 'response'):
            props = {}
            for ps in resp.findall(D + 'propstat'):
                if '200' in ps.find(D + 'status').text:
                    for p in ps.find(D + 'prop'):
                        props[p.tag] = p
            out[resp.find(D + 'href').text] = props
        return out


PROPFIND_ALL = b'''<?xml version="1.0"?><d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav"
  xmlns:cs="http://calendarserver.org/ns/"><d:prop><d:resourcetype/><d:displayname/><cs:getctag/><d:getetag/>
  <c:supported-calendar-component-set/><d:current-user-principal/><c:calendar-home-set/></d:prop></d:propfind>'''

VTODO = '''BEGIN:VCALENDAR\r
VERSION:2.0\r
PRODID:-//Test//EN\r
BEGIN:VTODO\r
UID:abc-123\r
SUMMARY:Comprare il latte\\, pane\r
DESCRIPTION:Riga 1\\nRiga 2\r
DUE;TZID=Europe/Rome:20261120T153000\r
PRIORITY:1\r
CATEGORIES:casa,urgente\r
RRULE:FREQ=WEEKLY;INTERVAL=2\r
BEGIN:VALARM\r
TRIGGER:-P1D\r
ACTION:DISPLAY\r
END:VALARM\r
{extra}END:VTODO\r
END:VCALENDAR\r
'''


def test_auth(client, family):
    c = client()
    assert c.open('/dav/', method='PROPFIND').status_code == 401
    assert 'Basic' in c.open('/dav/', method='PROPFIND').headers['WWW-Authenticate']
    # The account password is not enough: only app passwords
    assert c.open('/dav/', method='PROPFIND', headers=basic('fil@example.com', 'secret123')).status_code == 401
    dav = Dav(client, family)
    assert dav.req('PROPFIND', '/dav/', depth='0').status_code == 207
    assert c.open('/dav/', method='PROPFIND', headers=basic('sara@example.com', dav.h['Authorization'])).status_code == 401
    # Revoked: no longer works
    pid = ok(family.c.get('/api/caldav'))['passwords'][0]['id']
    ok(family.c.delete(f'/api/caldav/passwords/{pid}'))
    assert dav.req('PROPFIND', '/dav/', depth='0').status_code == 401
    # The well-known address points to the server; OPTIONS advertises CalDAV
    assert c.get('/.well-known/caldav').headers['Location'] == '/dav/'
    assert 'calendar-access' in c.open('/dav/', method='OPTIONS').headers['DAV']


def test_discovery(client, family):
    ok(family.c.post('/api/lists', json={'name': 'Spesa', 'color': 'green'}), 201)
    dav = Dav(client, family)
    root = dav.multistatus('PROPFIND', '/dav/', PROPFIND_ALL, depth='0')
    principal = root['/dav/'][D + 'current-user-principal'].find(D + 'href').text
    home = dav.multistatus('PROPFIND', principal, PROPFIND_ALL, depth='0')[principal][C + 'calendar-home-set'].find(D + 'href').text
    assert home == f'/dav/calendars/{dav.uid}/'
    cals = dav.multistatus('PROPFIND', home, PROPFIND_ALL)
    names = {href: p[D + 'displayname'].text for href, p in cals.items() if href != home}
    assert sorted(names.values()) == ['Spesa', 'doTrack']
    coll = next(h for h, n in names.items() if n == 'doTrack')
    props = cals[coll]
    assert props[D + 'resourcetype'].find(C + 'calendar') is not None
    assert {x.get('name') for x in props[C + 'supported-calendar-component-set']} == {'VTODO', 'VEVENT'}
    assert props[CS + 'getctag'].text
    # Someone else's calendars are off limits
    assert dav.req('PROPFIND', f'/dav/calendars/{dav.uid + 1}/', depth='1').status_code == 403


def test_items_appear_and_changes_come_back(client, family):
    f = family
    dav = Dav(client, f)
    task = f.item(title='Bollo auto', kind='deadline', due_date='2026-11-30', remind_days=30, recur_unit='year', recur_every=1,
                  labels=['auto'], priority=1, assignee_id=f.uid, subject='Panda', checks=[{'text': 'Pagare online'}])
    appt = f.item(title='Pediatra', kind='appointment', due_date='2026-11-20', due_time='10:30', end_time='11:00', location='Studio')
    coll = f'/dav/calendars/{dav.uid}/f{f.me["family"]["id"]}/'
    listing = dav.multistatus('PROPFIND', coll, PROPFIND_ALL)
    assert f'{coll}item-{task["id"]}.ics' in listing and f'{coll}item-{appt["id"]}.ics' in listing
    ctag = listing[coll][CS + 'getctag'].text

    ics = dav.req('GET', f'{coll}item-{task["id"]}.ics').get_data(as_text=True)
    assert 'BEGIN:VTODO' in ics and 'SUMMARY:Bollo auto' in ics and 'DUE;VALUE=DATE:20261130' in ics
    assert 'RRULE:FREQ=YEARLY' in ics and 'CATEGORIES:auto' in ics and 'PRIORITY:1' in ics and f'TRIGGER:-P29DT{24 - reminders.HOUR}H0M' in ics
    ics2 = dav.req('GET', f'{coll}item-{appt["id"]}.ics').get_data(as_text=True)
    assert 'BEGIN:VEVENT' in ics2 and 'DTSTART;TZID=Europe/Rome:20261120T103000' in ics2 and 'BEGIN:VTIMEZONE' in ics2

    # The phone changes the title and completes it: the next occurrence is created as in the app
    etag = dav.req('GET', f'{coll}item-{task["id"]}.ics').headers['ETag']
    changed = ics.replace('SUMMARY:Bollo auto', 'SUMMARY:Bollo Panda').replace('STATUS:NEEDS-ACTION', 'STATUS:COMPLETED')
    assert dav.req('PUT', f'{coll}item-{task["id"]}.ics', changed, **{'If-Match': '"stale"'}).status_code == 412
    assert dav.req('PUT', f'{coll}item-{task["id"]}.ics', changed, **{'If-Match': etag}).status_code == 204
    item = ok(f.c.get(f'/api/items/{task["id"]}'))
    assert item['title'] == 'Bollo Panda' and item['done'] and item['done_by'] == f.uid
    # What iCalendar can't carry is kept
    assert (item['assignee_id'], item['subject'], [c['text'] for c in item['checks']]) == (f.uid, 'Panda', ['Pagare online'])
    nxt = [i for i in ok(f.c.get('/api/items')) if i['title'] == 'Bollo Panda' and not i['done']]
    assert len(nxt) == 1 and nxt[0]['due_date'] == '2027-11-30'
    assert dav.multistatus('PROPFIND', coll, PROPFIND_ALL)[coll][CS + 'getctag'].text != ctag


def test_new_items_from_the_phone(client, family):
    f = family
    dav = Dav(client, f)
    spesa = ok(f.c.post('/api/lists', json={'name': 'Spesa'}), 201)
    coll = f'/dav/calendars/{dav.uid}/l{spesa["id"]}/'
    r = dav.req('PUT', coll + 'abc-123.ics', VTODO.format(extra=''), **{'If-None-Match': '*'})
    assert r.status_code == 201
    items = [i for i in ok(f.c.get('/api/items')) if i['list_id'] == spesa['id']]
    assert len(items) == 1
    it = items[0]
    assert (it['title'], it['notes'], it['due_date'], it['due_time']) == ('Comprare il latte, pane', 'Riga 1\nRiga 2', '2026-11-20', '15:30')
    assert (it['priority'], it['recur_unit'], it['recur_every'], it['remind_days'], it['remind_time']) == (1, 'week', 2, 1, '15:30')
    assert sorted(x['name'] for x in ok(f.c.get('/api/labels'))) == ['casa', 'urgente']
    # Same name again with If-None-Match: refused
    assert dav.req('PUT', coll + 'abc-123.ics', VTODO.format(extra=''), **{'If-None-Match': '*'}).status_code == 412
    # Read back under the client's name, with the client's UID
    back = dav.req('GET', coll + 'abc-123.ics').get_data(as_text=True)
    assert 'UID:abc-123' in back and 'SUMMARY:Comprare il latte\\, pane' in back
    # A UTC time is converted to local time
    utc = VTODO.format(extra='').replace('UID:abc-123', 'UID:zzz').replace('DUE;TZID=Europe/Rome:20261120T153000', 'DUE:20260720T080000Z')
    assert dav.req('PUT', coll + 'zzz.ics', utc).status_code == 201
    summer = next(i for i in ok(f.c.get('/api/items')) if i['list_id'] == spesa['id'] and i['due_date'] == '2026-07-20')
    assert summer['due_time'] == '10:00'
    # Events become appointments (or notices when they span days)
    event = ('BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:ev1\r\nSUMMARY:Ferie\r\nDTSTART;VALUE=DATE:20261224\r\n'
             'DTEND;VALUE=DATE:20270102\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n')
    assert dav.req('PUT', coll + 'ev1.ics', event).status_code == 201
    ferie = next(i for i in ok(f.c.get('/api/items')) if i['title'] == 'Ferie')
    assert (ferie['kind'], ferie['due_date'], ferie['end_date']) == ('note', '2026-12-24', '2027-01-01')

    # Multiget and query, as clients fetch after a change of ctag
    multiget = f'''<c:calendar-multiget xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav"><d:prop><d:getetag/>
      <c:calendar-data/></d:prop><d:href>{coll}abc-123.ics</d:href><d:href>{coll}missing.ics</d:href></c:calendar-multiget>'''
    got = dav.multistatus('REPORT', coll, multiget)
    assert 'BEGIN:VTODO' in got[coll + 'abc-123.ics'][C + 'calendar-data'].text and got[coll + 'missing.ics'] == {}
    query = '''<c:calendar-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav"><d:prop><d:getetag/></d:prop>
      <c:filter><c:comp-filter name="VCALENDAR"><c:comp-filter name="VEVENT"/></c:comp-filter></c:filter></c:calendar-query>'''
    assert list(dav.multistatus('REPORT', coll, query)) == [coll + 'ev1.ics']

    # Deleted from the phone
    assert dav.req('DELETE', coll + 'ev1.ics').status_code == 204
    assert all(i['title'] != 'Ferie' for i in ok(f.c.get('/api/items')))
    assert dav.req('GET', coll + 'ev1.ics').status_code == 404


def test_deleted_from_a_phone_goes_to_the_trash(client, family):
    import io
    f = family
    dav = Dav(client, f)
    item = f.item(title='Visita', kind='appointment', due_date='2026-11-20')
    ok(f.c.post(f"/api/items/{item['id']}/attachments", data={'file': (io.BytesIO(b'%PDF'), 'r.pdf')},
                content_type='multipart/form-data'), 201)
    coll = f'/dav/calendars/{dav.uid}/f{f.me["family"]["id"]}/'
    assert dav.req('DELETE', f'{coll}item-{item["id"]}.ics').status_code == 204
    assert f.c.get(f"/api/items/{item['id']}").status_code == 404
    assert [i['title'] for i in ok(f.c.get('/api/trash'))] == ['Visita']
    restored = ok(f.c.post(f"/api/items/{item['id']}/restore"))
    assert restored['title'] == 'Visita' and len(restored['attachments']) == 1
    assert dav.req('GET', f'{coll}item-{item["id"]}.ics').status_code == 200


def test_reopen_from_the_phone(client, family):
    f = family
    dav = Dav(client, f)
    item = f.item(title='Chiamare')
    ok(f.c.post(f"/api/items/{item['id']}/done"))
    coll = f'/dav/calendars/{dav.uid}/f{f.me["family"]["id"]}/'
    ics = dav.req('GET', f'{coll}item-{item["id"]}.ics').get_data(as_text=True)
    assert 'STATUS:COMPLETED' in ics
    reopened = '\r\n'.join(x for x in ics.split('\r\n') if not x.startswith(('COMPLETED', 'PERCENT'))).replace('STATUS:COMPLETED', 'STATUS:NEEDS-ACTION')
    assert dav.req('PUT', f'{coll}item-{item["id"]}.ics', reopened).status_code == 204
    assert not ok(f.c.get(f"/api/items/{item['id']}"))['done']


def test_round_trip_keeps_reminder_defaults():
    comp = caldav.parse_ics(VTODO.format(extra=''))['subs'][0]['subs'][0]
    fields, done = caldav.fields_from_ics(comp, {})
    assert (fields['remind_days'], fields['remind_time'], done) == (1, '15:30', False)  # a day before, same time
    # The app's default reminder (morning of the day before) goes out and comes back unchanged
    item = {'id': 1, 'kind': 'task', 'title': 'x', 'notes': '', 'location': '', 'priority': 0, 'labels': [], 'due_date': '2026-11-20',
            'due_time': '15:30', 'end_time': None, 'end_date': None, 'recur_unit': None, 'recur_every': None, 'done_at': None,
            'remind_days': 1, 'remind_time': None, 'caldav_uid': None, 'updated_at': '2026-11-01 10:00:00', 'created_at': '2026-11-01 10:00:00'}
    out = caldav.parse_ics('BEGIN:VCALENDAR\r\n' + '\r\n'.join(caldav.item_ics(item, {}, 'h')) + '\r\nEND:VCALENDAR\r\n')
    fields, _ = caldav.fields_from_ics(out['subs'][0]['subs'][0], {})
    assert (fields['remind_days'], fields['remind_time'], fields['due_time']) == (1, None, '15:30')
    for days, at in ((0, None), (2, '18:45'), (0, '07:00')):
        out = caldav.parse_ics('BEGIN:VCALENDAR\r\n' + '\r\n'.join(caldav.item_ics({**item, 'remind_days': days, 'remind_time': at}, {}, 'h'))
                               + '\r\nEND:VCALENDAR\r\n')
        fields, _ = caldav.fields_from_ics(out['subs'][0]['subs'][0], {})
        assert (fields['remind_days'], fields['remind_time']) == (days, at)
    timed = VTODO.format(extra='').replace('TRIGGER:-P1D', 'TRIGGER:-PT1H').replace('RRULE:FREQ=WEEKLY;INTERVAL=2\r\n', '')
    fields, _ = caldav.fields_from_ics(caldav.parse_ics(timed)['subs'][0]['subs'][0], {})
    assert (fields['remind_days'], fields['remind_time']) == (0, None)  # one hour before = the default
    evening = VTODO.format(extra='').replace('TRIGGER:-P1D', 'TRIGGER:-PT21H')
    fields, _ = caldav.fields_from_ics(caldav.parse_ics(evening)['subs'][0]['subs'][0], {})
    assert (fields['remind_days'], fields['remind_time']) == (1, '18:30')

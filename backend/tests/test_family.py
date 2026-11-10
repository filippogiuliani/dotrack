"""Families, invitations, roles and above all isolation: nobody can see or change another family's data."""
import io

from conftest import PASSWORD, invite_token, ok, sign_up


def test_families_are_isolated(client, family):
    f = family
    item = f.item(title='Bollo auto', due_date='2026-12-01', checks=[{'text': 'Q?'}])
    item = ok(f.c.post(f"/api/items/{item['id']}/attachments",
                       data={'file': (io.BytesIO(b'%PDF-1.4'), 'referto.pdf')}, content_type='multipart/form-data'), 201)
    att = item['attachments'][0]['id']

    other = client()
    sign_up(other, email='anna@example.com', name='Anna')
    attempts = {
        'read item': other.get(f"/api/items/{item['id']}"),
        'update item': other.put(f"/api/items/{item['id']}", json={'title': 'hack'}),
        'complete item': other.post(f"/api/items/{item['id']}/done"),
        'undo item': other.post(f"/api/items/{item['id']}/undo"),
        'tick check': other.patch(f"/api/items/{item['id']}/checks/{item['checks'][0]['id']}", json={'done': True}),
        'delete item': other.delete(f"/api/items/{item['id']}"),
        'upload': other.post(f"/api/items/{item['id']}/attachments", data={'file': (io.BytesIO(b'x'), 'a.pdf')},
                             content_type='multipart/form-data'),
        'download': other.get(f'/api/attachments/{att}'),
        'delete attachment': other.delete(f'/api/attachments/{att}'),
        'assign to foreign user': other.post('/api/items', json={'title': 'x', 'assignee_id': f.uid}),
        'switch to foreign family': other.post('/api/family/switch', json={'family_id': f.me['family']['id']}),
    }
    passed = {k: r.status_code for k, r in attempts.items() if r.status_code not in (400, 403, 404)}
    assert not passed, f'isolation broken: {passed}'
    assert ok(other.get('/api/items')) == []
    # The first family's data is untouched
    mine = ok(f.c.get('/api/items'))
    assert [i['title'] for i in mine] == ['Bollo auto'] and len(mine[0]['attachments']) == 1


def test_invitation_for_new_user_and_roles(client, family):
    f = family
    invite = invite_token(f.c)
    partner = client()
    assert ok(partner.get(f'/api/invites/{invite}'))['family']
    me = sign_up(partner, email='partner@example.com', name='Partner', invite=invite)
    assert me['family']['id'] == f.me['family']['id'] and me['family']['role'] == 'member'
    assert [m['name'] for m in me['members']] == ['Fil', 'Partner']
    # Sees and writes the shared items, and can be assigned
    item = f.item(c=partner, title='Pediatra', kind='appointment', assignee_id=f.uid)
    assert [i['title'] for i in ok(f.c.get('/api/items'))] == ['Pediatra']
    assert item['assignee_id'] == f.uid and item['created_by'] == me['user']['id']
    # Single-use invitation
    assert client().post('/api/signup', json={'name': 'Z', 'email': 'z@example.com', 'password': PASSWORD,
                                              'consent': True, 'invite': invite}).status_code == 400
    # A member cannot do admin operations
    assert partner.post('/api/family/invites').status_code == 403
    assert partner.put('/api/family', json={'name': 'x'}).status_code == 403


def test_existing_user_accepts_invitation_and_is_removed(client, family):
    f = family
    anna = client()
    me_anna = sign_up(anna, email='anna@example.com', name='Anna')
    ok(anna.post(f'/api/invites/{invite_token(f.c)}/accept'))
    me = ok(anna.get('/api/me'))
    assert len(me['families']) == 2 and me['family']['id'] == f.me['family']['id']
    ok(anna.post('/api/family/switch', json={'family_id': me_anna['family']['id']}))
    ok(f.c.delete(f"/api/family/members/{me_anna['user']['id']}"))
    assert anna.post('/api/family/switch', json={'family_id': f.me['family']['id']}).status_code == 404


def test_removed_member_assignments_become_anyone(family):
    f = family
    f.add_partner()
    item = f.item(title='Spesa', assignee_id=f.puid)
    ok(f.c.delete(f'/api/family/members/{f.puid}'))
    assert ok(f.c.get(f"/api/items/{item['id']}"))['assignee_id'] is None
    assert f.c.post('/api/items', json={'title': 'x', 'assignee_id': f.puid}).status_code == 400

<script>
  import { del, get, post, put } from '../lib/api.js';
  import { app, loadItems, loadMe, openEditor, showError, toast } from '../lib/store.svelte.js';
  import { t } from '../lib/i18n.svelte.js';
  import { fmtDayMonth, fromNow } from '../lib/date.js';
  import { currentSubscription, disablePush, enablePush, iosNeedsInstall, pushSupported } from '../lib/push.js';
  import { age, byDue, when } from '../lib/items.js';
  import LanguageSwitch from '../components/LanguageSwitch.svelte';
  import Icon from '../components/Icon.svelte';

  let { onlogout, initialError = '' } = $props();
  let family = $state(null);
  let invite = $state(null);
  let feed = $state(null);
  let familyName = $state('');
  let userName = $state(app.me?.user?.name ?? '');
  let pwd = $state({ current: '', new: '' });

  const admin = $derived(family?.role === 'admin');
  const user = $derived(app.me?.user);

  async function load() {
    try { family = await get('/family'); familyName = family.name; } catch (e) { showError(e); }
  }
  $effect(() => { app.me?.family?.id; load(); });
  $effect(() => { app.me?.family?.id; get('/calendar/feed').then((f) => (feed = f)).catch(showError); });
  $effect(() => { if (initialError) toast(initialError, 'error'); });

  async function run(fn, message) {
    try { await fn(); if (message) toast(message); await loadMe(); await load(); return true; } catch (e) { showError(e); return false; }
  }

  // --- Family
  const rename = () => run(() => put('/family', { name: familyName }), t('common.saved'));
  const switchFamily = (id) => run(async () => { await post('/family/switch', { family_id: id }); await loadItems(); });

  // --- People without an account
  let newPerson = $state('');
  async function addPerson(e) {
    e.preventDefault();
    const name = newPerson.trim();
    if (name && await run(() => post('/family/people', { name }), t('people.added', { name }))) newPerson = '';
  }
  async function renamePerson(p) {
    const name = prompt(t('people.rename_prompt'), p.name)?.trim();
    if (name && name !== p.name) await run(() => put(`/family/people/${p.id}`, { name }), t('common.saved'));
  }
  async function removePerson(p) {
    if (!confirm(t('people.confirm_delete', { name: p.name }))) return;
    await run(async () => { await del(`/family/people/${p.id}`); await loadItems(); });
  }

  // --- Birthdays, next one first
  const birthdays = $derived(app.items.filter((i) => i.kind === 'birthday').sort(byDue));

  // --- Calendar and reminders
  async function setScope(scope) {
    try { feed = await put('/calendar/feed', { scope }); } catch (e) { showError(e); }
  }
  async function regenerate() {
    if (!confirm(t('gcal.confirm_regenerate'))) return;
    try { feed = await put('/calendar/feed', { regenerate: true }); toast(t('gcal.regenerated')); } catch (e) { showError(e); }
  }
  async function copyFeed() {
    try { await navigator.clipboard.writeText(feed.url); toast(t('invite.copied')); } catch { /* the address stays visible */ }
  }
  const googleSubscribe = $derived(feed ? 'https://calendar.google.com/calendar/r?cid=' + encodeURIComponent(feed.webcal) : '#');
  // --- Push notifications on this device
  let push = $state({ state: 'loading' }); // unsupported | ios | insecure | denied | off | on
  async function checkPush() {
    if (!window.isSecureContext) return (push = { state: 'insecure' });
    if (!pushSupported()) return (push = { state: iosNeedsInstall() ? 'ios' : 'unsupported' });
    if (Notification.permission === 'denied') return (push = { state: 'denied' });
    try { push = { state: (await currentSubscription()) ? 'on' : 'off' }; } catch { push = { state: 'off' }; }
  }
  checkPush();
  let pushBusy = $state(false);
  async function togglePush(on) {
    pushBusy = true;
    try {
      if (on) { await enablePush(); toast(t('push.enabled')); } else { await disablePush(); toast(t('push.disabled')); }
    } catch (e) {
      if (e.message !== 'denied') showError(e);
    } finally { pushBusy = false; await checkPush(); }
  }
  async function testPush() {
    try { await post('/push/test'); toast(t('push.test_sent')); } catch (e) { showError(e); }
  }

  // --- CalDAV (sync with other apps)
  let dav = $state(null);
  let newSecret = $state(null);
  $effect(() => { get('/caldav').then((d) => (dav = d)).catch(() => {}); });
  async function createSecret() {
    const name = prompt(t('caldav.password_name'))?.trim();
    if (name === undefined || name === null) return;
    try {
      newSecret = await post('/caldav/passwords', { name: name || 'CalDAV' });
      dav = await get('/caldav');
    } catch (e) { showError(e); }
  }
  async function revoke(p) {
    if (!confirm(t('caldav.confirm_revoke', { name: p.name }))) return;
    try { dav = await del(`/caldav/passwords/${p.id}`); } catch (e) { showError(e); }
  }
  async function copy(text) {
    try { await navigator.clipboard.writeText(text); toast(t('invite.copied')); } catch { /* stays visible */ }
  }
  const usedOn = (s) => fmtDayMonth(s.slice(0, 10));

  // --- Two-step verification
  let twofa = $state(null); // { enabled, recovery_left }
  let setup = $state(null); // { secret, uri, qr } while being set up
  let setupCode = $state('');
  let recovery = $state(null); // codes just created: shown once
  $effect(() => { get('/account/2fa').then((d) => (twofa = d)).catch(() => {}); });
  async function startSetup() {
    try { setup = await post('/account/2fa/setup'); setupCode = ''; } catch (e) { showError(e); }
  }
  async function confirmSetup(e) {
    e.preventDefault();
    try {
      const r = await post('/account/2fa/enable', { code: setupCode });
      twofa = r; recovery = r.recovery_codes; setup = null;
      toast(t('twofa.enabled')); await loadMe();
    } catch (err) { showError(err); }
  }
  /** A 6-digit code or a recovery code (xxxx-xxxx) is sent as a code, anything else as the password */
  function confirmation() {
    const v = prompt(user.has_password ? t('twofa.confirm_password_or_code') : t('twofa.confirm_code'))?.trim();
    if (!v) return null;
    return /^\d{6}$/.test(v.replace(/\s/g, '')) || /^[0-9a-f]{4}-?[0-9a-f]{4}$/i.test(v) ? { code: v } : { password: v };
  }
  async function disable2fa() {
    const c = confirmation();
    if (!c) return;
    try { twofa = await post('/account/2fa/disable', c); recovery = null; toast(t('twofa.disabled')); await loadMe(); } catch (e) { showError(e); }
  }
  async function newCodes() {
    const c = confirmation();
    if (!c) return;
    try { const r = await post('/account/2fa/recovery-codes', c); twofa = r; recovery = r.recovery_codes; } catch (e) { showError(e); }
  }
  async function signOutElsewhere() {
    if (!confirm(t('security.confirm_others'))) return;
    try { await post('/account/sessions/revoke'); toast(t('security.others_out')); } catch (e) { showError(e); }
  }

  // --- API tokens and webhooks
  let tokens = $state([]);
  let newToken = $state(null);
  let hooks = $state(null);
  let hookUrl = $state('');
  let hookSecret = $state(null);
  const EVENTS = ['item.created', 'item.updated', 'item.done', 'item.reopened', 'item.deleted', 'comment.created'];
  let hookEvents = $state([...EVENTS]);
  $effect(() => {
    app.me?.family?.id;
    get('/account/tokens').then((d) => (tokens = d)).catch(() => {});
    if (admin) get('/family/webhooks').then((d) => (hooks = d)).catch(() => {});
  });
  async function createApiToken() {
    const name = prompt(t('api.token_name'))?.trim();
    if (name === undefined || name === null) return;
    try { newToken = await post('/account/tokens', { name: name || 'API' }); tokens = await get('/account/tokens'); } catch (e) { showError(e); }
  }
  async function revokeToken(tk) {
    if (!confirm(t('api.confirm_revoke', { name: tk.name }))) return;
    try { tokens = await del(`/account/tokens/${tk.id}`); } catch (e) { showError(e); }
  }
  async function addHook(e) {
    e.preventDefault();
    try {
      const r = await post('/family/webhooks', { url: hookUrl.trim(), events: hookEvents });
      hooks = r.webhooks; hookSecret = r.secret; hookUrl = '';
    } catch (err) { showError(err); }
  }
  async function testHook(h) {
    try { const r = await post(`/family/webhooks/${h.id}/test`); toast(t('api.hook_test_result', { status: r.status })); hooks = await get('/family/webhooks'); }
    catch (e) { showError(e); }
  }
  async function removeHook(h) {
    if (!confirm(t('api.hook_confirm_delete', { url: h.url }))) return;
    try { hooks = await del(`/family/webhooks/${h.id}`); } catch (e) { showError(e); }
  }
  const apiBase = location.origin + '/api';

  const setReminders = (on) => run(() => put('/account', { reminders_email: on }), on ? t('reminders.on') : t('reminders.off'));

  // --- Members and invitations
  async function createInvite() {
    try { invite = await post('/family/invites'); } catch (e) { showError(e); }
  }
  async function shareInvite() {
    const text = t('invite.message', { family: family.name });
    if (navigator.share) {
      try { await navigator.share({ title: 'doTrack', text, url: invite.link }); return; } catch { /* cancelled */ }
    }
    try { await navigator.clipboard.writeText(invite.link); toast(t('invite.copied')); } catch { /* the link stays visible */ }
  }
  async function remove(m) {
    const self = m.me;
    if (!confirm(self ? t('family.confirm_leave') : t('family.confirm_remove', { name: m.name }))) return;
    await run(async () => { await del(`/family/members/${m.id}`); await loadItems(); },
              self ? t('family.left') : t('family.removed'));
  }

  // --- Account
  const saveName = () => run(() => put('/account', { name: userName }), t('common.saved'));
  const saveLanguage = (l) => run(() => put('/account', { language: l }));
  const resend = () => run(() => post('/account/resend-verification'), t('account.verification_sent'));
  async function changePassword(e) {
    e.preventDefault();
    if (await run(() => post('/account/password', pwd), t('account.password_changed'))) pwd = { current: '', new: '' };
  }
  const unlink = (p) => run(() => del(`/account/identities/${p}`), t('account.unlinked'));
  async function deleteAccount() {
    const confirmation = user.has_password
      ? prompt(t('account.delete_password'))
      : prompt(t('account.delete_email', { email: user.email }));
    if (!confirmation) return;
    try {
      await del('/account', user.has_password ? { password: confirmation } : { confirm_email: confirmation });
      toast(t('account.deleted'));
      onlogout(true);
    } catch (e) { showError(e); }
  }
</script>

<header class="head"><h1>{t('nav.family')}</h1><p class="muted">{t('family.subtitle')}</p></header>

{#if family && user}
<div class="layout">
  {#if app.me.hub}
  <!-- Managed in weHub -->
  <section class="card stack">
    <h2>{t('family.family')}</h2>
    <p><b>{family.name}</b></p>
    <p class="small muted">{t('hub.managed')}</p>
    <ul class="list">
      {#each family.members as m (m.id)}
        <li><div class="grow"><b>{m.name}</b>{#if m.me}<span class="muted small you">({t('family.you')})</span>{/if}
          <div class="tiny muted">{m.email} · {m.role === 'admin' ? t('family.role_admin') : t('family.role_member')}</div></div></li>
      {/each}
    </ul>
    {#if family.people.length}<p class="small">{t('people.title')}: {family.people.map((p) => p.name).join(', ')}</p>{/if}
    <a class="btn primary" href="{app.me.hub.url}/#/family">{t('hub.open')}</a>
  </section>
  {:else}
  <!-- Family -->
  <section class="card stack">
    <h2>{t('family.family')}</h2>
    {#if admin}
      <form class="row" onsubmit={(e) => { e.preventDefault(); rename(); }}>
        <input class="input grow" bind:value={familyName} maxlength="80" aria-label={t('family.name')} />
        <button class="btn" disabled={!familyName.trim() || familyName === family.name}>{t('common.save')}</button>
      </form>
    {:else}
      <p><b>{family.name}</b></p>
    {/if}
    {#if app.me.families.length > 1}
      <div class="field">
        <span class="label">{t('family.switch')}</span>
        <div class="seg stacked">
          {#each app.me.families as f (f.id)}
            <button class:on={f.id === app.me.family.id} onclick={() => switchFamily(f.id)}>{f.name}</button>
          {/each}
        </div>
      </div>
    {/if}
    <h3 class="sub">{t('family.members')}</h3>
    <ul class="list">
      {#each family.members as m (m.id)}
        <li>
          <div class="grow">
            <b>{m.name}</b>{#if m.me}<span class="muted small you">({t('family.you')})</span>{/if}
            <div class="tiny muted email">{m.email} · {m.role === 'admin' ? t('family.role_admin') : t('family.role_member')}</div>
          </div>
          {#if m.me && family.members.length > 1}
            <button class="btn ghost sm" onclick={() => remove(m)}>{t('family.leave')}</button>
          {:else if admin && !m.me}
            <button class="btn ghost sm" onclick={() => remove(m)}>{t('family.remove')}</button>
          {/if}
        </li>
      {/each}
    </ul>
    {#if admin}
      {#if invite}
        <div class="invite stack">
          <p class="small">{t('invite.instructions')}</p>
          <input class="input" readonly value={invite.link} onfocus={(e) => e.currentTarget.select()} aria-label={t('invite.link')} />
          <button class="btn primary" onclick={shareInvite}>{t('invite.share')}</button>
        </div>
      {:else}
        <button class="btn primary" onclick={createInvite}>{t('invite.create')}</button>
        <p class="tiny muted">{t('invite.explanation')}</p>
      {/if}
    {/if}
  </section>

  <!-- People without an account -->
  <section class="card stack">
    <h2 class="ic"><Icon name="people" />{t('people.title')}</h2>
    <p class="small muted">{t('people.explain')}</p>
    {#if family.people.length}
      <ul class="list">
        {#each family.people as p (p.id)}
          <li>
            <span class="grow name">{p.name}</span>
            <button class="btn icon sm ghost" onclick={() => renamePerson(p)} aria-label={t('people.rename', { name: p.name })}><Icon name="edit" size={16} /></button>
            <button class="btn icon sm ghost" onclick={() => removePerson(p)} aria-label={t('people.delete', { name: p.name })}><Icon name="trash" size={16} /></button>
          </li>
        {/each}
      </ul>
    {/if}
    <form class="row" onsubmit={addPerson}>
      <input class="input grow" bind:value={newPerson} maxlength="60" placeholder={t('people.placeholder')} aria-label={t('people.placeholder')} />
      <button class="btn" disabled={!newPerson.trim()}>{t('people.add')}</button>
    </form>
  </section>

  {/if}

  <!-- Birthdays -->
  <section class="card stack">
    <h2 class="ic"><Icon name="birthday" />{t('birthdays.title')}</h2>
    <p class="small muted">{t('birthdays.explain')}</p>
    {#if birthdays.length}
      <ul class="list">
        {#each birthdays as b (b.id)}
          {@const years = age(b)}
          <li>
            <button class="bday" onclick={() => openEditor(b)}>
              <span class="grow">
                <b>{b.title}</b>
                <span class="tiny muted d">{fmtDayMonth(when(b))} · {fromNow(when(b))}{#if years} · {t('birthday.turns', { n: years })}{/if}</span>
              </span>
            </button>
          </li>
        {/each}
      </ul>
    {:else}
      <p class="small muted">{t('birthdays.empty')}</p>
    {/if}
    <button class="btn soft" onclick={() => openEditor(null, { kind: 'birthday' })}><Icon name="plus" size={16} />{t('birthdays.add')}</button>
  </section>

  <!-- Google Calendar -->
  <section class="card stack">
    <h2 class="ic"><Icon name="google" />{t('gcal.title')}</h2>
    <p class="small muted">{t('gcal.intro')}</p>
    {#if feed}
      <div class="field">
        <span class="label">{t('gcal.what')}</span>
        <div class="seg stacked">
          <button class:on={feed.scope === 'mine'} onclick={() => setScope('mine')}>{t('gcal.scope_mine')}</button>
          <button class:on={feed.scope === 'all'} onclick={() => setScope('all')}>{t('gcal.scope_all')}</button>
        </div>
      </div>
      <a class="btn primary" href={googleSubscribe} target="_blank" rel="noopener"><Icon name="external" size={16} />{t('gcal.subscribe')}</a>
      <details class="small">
        <summary>{t('gcal.manual')}</summary>
        <div class="stack manual">
          <ol>
            <li>{t('gcal.step1')}</li>
            <li>{t('gcal.step2')}</li>
            <li>{t('gcal.step3')}</li>
          </ol>
          <div class="row">
            <input class="input grow" readonly value={feed.url} onfocus={(e) => e.currentTarget.select()} aria-label={t('gcal.address')} />
            <button class="btn icon soft" onclick={copyFeed} aria-label={t('gcal.copy')}><Icon name="copy" /></button>
          </div>
        </div>
      </details>
      <p class="tiny muted">{t('gcal.note')}</p>
      <p class="tiny muted">{t('gcal.private')} <button class="linkish" onclick={regenerate}>{t('gcal.regenerate')}</button></p>
    {/if}
  </section>

  <!-- Reminders -->
  <section class="card stack">
    <h2 class="ic"><Icon name="bell" />{t('reminders.title')}</h2>
    <label class="toggle"><input type="checkbox" checked={user.reminders_email} onchange={(e) => setReminders(e.currentTarget.checked)} />
      {t('reminders.email')}</label>
    <p class="small muted">{t('reminders.explain', { email: user.email })}</p>
    {#if !user.email_verified}<p class="small warn">{t('reminders.verify_first')}</p>{/if}

    <h3 class="sub ic"><Icon name="phone" size={16} />{t('push.title')}</h3>
    <p class="small muted">{t('push.explain')}</p>
    {#if push.state === 'on'}
      <p class="small"><span class="badge ok"><Icon name="check" size={12} />{t('push.on')}</span></p>
      <div class="row wrap">
        <button class="btn soft" onclick={testPush}>{t('push.test')}</button>
        <button class="btn ghost" disabled={pushBusy} onclick={() => togglePush(false)}>{t('push.disable')}</button>
      </div>
    {:else if push.state === 'off'}
      <button class="btn primary" disabled={pushBusy} onclick={() => togglePush(true)}><Icon name="bell" size={16} />{t('push.enable')}</button>
    {:else if push.state !== 'loading'}
      <p class="small warn">{t('push.' + push.state)}</p>
    {/if}
    <p class="tiny muted">{t('push.reminder_hint', { h: (app.me?.reminder_hour ?? 8) + ':00' })}</p>
  </section>

  <!-- CalDAV -->
  {#if dav}
  <section class="card stack">
    <h2 class="ic"><Icon name="sync" />{t('caldav.title')}</h2>
    <p class="small muted">{t('caldav.intro')}</p>
    <div class="creds">
      <span class="label">{t('caldav.server')}</span>
      <div class="row"><input class="input grow mono" readonly value={dav.url} onfocus={(e) => e.currentTarget.select()} aria-label={t('caldav.server')} />
        <button class="btn icon soft" onclick={() => copy(dav.url)} aria-label={t('caldav.copy')}><Icon name="copy" /></button></div>
      <span class="label">{t('caldav.username')}</span>
      <div class="row"><input class="input grow mono" readonly value={dav.username} onfocus={(e) => e.currentTarget.select()} aria-label={t('caldav.username')} />
        <button class="btn icon soft" onclick={() => copy(dav.username)} aria-label={t('caldav.copy')}><Icon name="copy" /></button></div>
    </div>
    {#if newSecret}
      <div class="invite stack">
        <span class="label">{t('caldav.password')}</span>
        <div class="row"><input class="input grow mono" readonly value={newSecret.password} onfocus={(e) => e.currentTarget.select()} aria-label={t('caldav.password')} />
          <button class="btn icon soft" onclick={() => copy(newSecret.password)} aria-label={t('caldav.copy')}><Icon name="copy" /></button></div>
        <p class="tiny">{t('caldav.password_once')}</p>
      </div>
    {/if}
    <button class="btn primary" onclick={createSecret}><Icon name="key" size={16} />{t('caldav.new_password')}</button>
    {#if dav.passwords.length}
      <h3 class="sub">{t('caldav.passwords')}</h3>
      <ul class="list">
        {#each dav.passwords as p (p.id)}
          <li>
            <div class="grow"><b>{p.name}</b>
              <div class="tiny muted">{p.last_used_at ? t('caldav.last_used', { date: usedOn(p.last_used_at) }) : t('caldav.never_used')}</div></div>
            <button class="btn ghost sm" onclick={() => revoke(p)}>{t('caldav.revoke')}</button>
          </li>
        {/each}
      </ul>
    {/if}
    <details class="small">
      <summary>{t('caldav.how')}</summary>
      <ul class="how">
        <li>{t('caldav.how_ios')}</li>
        <li>{t('caldav.how_android')}</li>
        <li>{t('caldav.how_other')}</li>
      </ul>
    </details>
    <p class="tiny muted">{t('caldav.what')}</p>
  </section>
  {/if}

  <!-- Integrations -->
  <section class="card stack">
    <h2 class="ic"><Icon name="external" />{t('api.title')}</h2>
    <p class="small muted">{t('api.intro')}</p>
    {#if newToken}
      <div class="invite stack">
        <span class="label">{t('api.token')}</span>
        <div class="row"><input class="input grow mono" readonly value={newToken.token} onfocus={(e) => e.currentTarget.select()} aria-label={t('api.token')} />
          <button class="btn icon soft" onclick={() => copy(newToken.token)} aria-label={t('caldav.copy')}><Icon name="copy" /></button></div>
        <p class="tiny">{t('api.token_once')}</p>
      </div>
    {/if}
    <button class="btn" onclick={createApiToken}><Icon name="key" size={16} />{t('api.new_token')}</button>
    {#if tokens.length}
      <ul class="list">
        {#each tokens as tk (tk.id)}
          <li>
            <div class="grow"><b>{tk.name}</b> <span class="tiny muted mono">{tk.hint}</span>
              <div class="tiny muted">{tk.last_used_at ? t('caldav.last_used', { date: usedOn(tk.last_used_at) }) : t('caldav.never_used')}</div></div>
            <button class="btn ghost sm" onclick={() => revokeToken(tk)}>{t('caldav.revoke')}</button>
          </li>
        {/each}
      </ul>
    {/if}
    <details class="small">
      <summary>{t('api.examples')}</summary>
      <div class="stack examples">
        <p class="tiny muted">{t('api.example_add')}</p>
        <pre class="mono code">curl -X POST {apiBase}/lists/&lt;id&gt;/items \
  -H "Authorization: Bearer dt_…" -H "Content-Type: application/json" \
  -d '&#123;"items": ["latte", "2 kg mele"]&#125;'</pre>
        <p class="tiny muted">{t('api.example_ha')}</p>
        <pre class="mono code">sensor:
  - platform: rest
    name: doTrack oggi
    resource: {apiBase}/summary
    headers:
      Authorization: Bearer dt_…
    value_template: "&#123;&#123; value_json.today &#125;&#125;"
    json_attributes: [overdue, appointments_today, lists]</pre>
      </div>
    </details>

    {#if admin && hooks}
      <h3 class="sub">{t('api.webhooks')}</h3>
      <p class="small muted">{t('api.webhooks_explain')}</p>
      {#if hooks.length}
        <ul class="list">
          {#each hooks as h (h.id)}
            <li>
              <div class="grow"><span class="mono small url">{h.url}</span>
                <div class="tiny muted">{h.events.join(', ')}{#if h.last_status} · {t('api.hook_last', { status: h.last_status })}{/if}</div></div>
              <button class="btn ghost sm" onclick={() => testHook(h)}>{t('api.hook_test')}</button>
              <button class="btn icon sm ghost" onclick={() => removeHook(h)} aria-label={t('common.delete')}><Icon name="trash" size={16} /></button>
            </li>
          {/each}
        </ul>
      {/if}
      {#if hookSecret}
        <div class="invite stack">
          <span class="label">{t('api.hook_secret')}</span>
          <div class="row"><input class="input grow mono" readonly value={hookSecret} onfocus={(e) => e.currentTarget.select()} aria-label={t('api.hook_secret')} />
            <button class="btn icon soft" onclick={() => copy(hookSecret)} aria-label={t('caldav.copy')}><Icon name="copy" /></button></div>
          <p class="tiny">{t('api.hook_secret_explain')}</p>
        </div>
      {/if}
      <form class="stack" onsubmit={addHook}>
        <input class="input" type="url" bind:value={hookUrl} placeholder="https://…" aria-label={t('api.hook_url')} required />
        <div class="chips">
          {#each EVENTS as ev (ev)}
            <button type="button" class="chip" class:on={hookEvents.includes(ev)}
                    onclick={() => (hookEvents = hookEvents.includes(ev) ? hookEvents.filter((x) => x !== ev) : [...hookEvents, ev])}>{ev}</button>
          {/each}
        </div>
        <button class="btn" disabled={!hookUrl.trim() || !hookEvents.length}>{t('api.hook_add')}</button>
      </form>
    {/if}
  </section>

  <!-- Account -->
  <section class="card stack">
    <h2>{t('account.title')}</h2>
    <form class="row" onsubmit={(e) => { e.preventDefault(); saveName(); }}>
      <input class="input grow" bind:value={userName} maxlength="80" aria-label={t('auth.your_name')} />
      <button class="btn" disabled={!userName.trim() || userName === user.name}>{t('common.save')}</button>
    </form>
    <div class="spread wrap">
      <span class="small email">{user.email}</span>
      {#if user.email_verified}<span class="badge ok">{t('account.verified')}</span>
      {:else}<button class="btn ghost sm" onclick={resend}>{t('account.resend')}</button>{/if}
    </div>
    <div class="spread">
      <span class="small">{t('common.language')}</span>
      <LanguageSwitch onchoose={saveLanguage} />
    </div>

    {#if !app.me.hub}
    <h3 class="sub">{user.has_password ? t('account.change_password') : t('account.set_password')}</h3>
    <form class="stack" onsubmit={changePassword}>
      {#if user.has_password}
        <input class="input" type="password" bind:value={pwd.current} placeholder={t('account.current_password')} autocomplete="current-password" required />
      {/if}
      <input class="input" type="password" bind:value={pwd.new} placeholder={t('auth.new_password')} autocomplete="new-password" minlength="8" required />
      <button class="btn">{t('auth.save_password')}</button>
    </form>

    <h3 class="sub ic"><Icon name="key" size={16} />{t('twofa.title')}</h3>
    {#if twofa}
      {#if twofa.enabled}
        <p class="small"><span class="badge ok"><Icon name="check" size={12} />{t('twofa.on')}</span>
          <span class="tiny muted">{t('twofa.codes_left', { n: twofa.recovery_left })}</span></p>
        <div class="row wrap">
          <button class="btn sm" onclick={newCodes}>{t('twofa.new_codes')}</button>
          <button class="btn ghost sm" onclick={disable2fa}>{t('twofa.disable')}</button>
        </div>
      {:else if setup}
        <div class="invite stack">
          <p class="small">{t('twofa.scan')}</p>
          <img class="qr" src={setup.qr} alt={t('twofa.qr_alt')} width="200" height="200" />
          <p class="tiny">{t('twofa.or_type')} <code class="mono">{setup.secret}</code>
            <a class="hide-desktop" href={setup.uri}>{t('twofa.open_app')}</a></p>
          <form class="row" onsubmit={confirmSetup}>
            <input class="input grow mono" bind:value={setupCode} inputmode="numeric" autocomplete="one-time-code" maxlength="6"
                   placeholder="123456" aria-label={t('twofa.code')} />
            <button class="btn primary" disabled={setupCode.replace(/\D/g, '').length !== 6}>{t('twofa.confirm')}</button>
          </form>
          <button class="btn ghost sm" onclick={() => (setup = null)}>{t('common.close')}</button>
        </div>
      {:else}
        <p class="small muted">{user.has_password ? t('twofa.explain') : t('twofa.explain_oidc')}</p>
        <button class="btn" onclick={startSetup}>{t('twofa.enable')}</button>
      {/if}
      {#if recovery}
        <div class="invite stack">
          <p class="small"><b>{t('twofa.recovery_title')}</b> {t('twofa.recovery_explain')}</p>
          <pre class="codes mono">{recovery.join('\n')}</pre>
          <button class="btn soft sm" onclick={() => copy(recovery.join('\n'))}><Icon name="copy" size={15} />{t('caldav.copy')}</button>
        </div>
      {/if}
    {/if}
    {/if}
    <button class="btn ghost sm others" onclick={signOutElsewhere}>{t('security.sign_out_others')}</button>

    {#if app.me.oidc?.length && !app.me.hub}
      <h3 class="sub">{t('account.sign_ins')}</h3>
      <ul class="list">
        {#each app.me.oidc as p (p.id)}
          <li>
            <span class="grow">{p.name}</span>
            {#if user.identities.includes(p.id)}
              <span class="badge ok">{t('account.linked')}</span>
              <button class="btn ghost sm" onclick={() => unlink(p.id)}>{t('account.unlink')}</button>
            {:else}
              <a class="btn ghost sm" href="/api/oidc/{encodeURIComponent(p.id)}/login?link=1">{t('account.link')}</a>
            {/if}
          </li>
        {/each}
      </ul>
    {/if}

    <div class="row wrap sub">
      <button class="btn" onclick={() => onlogout()}>{t('account.sign_out')}</button>
      {#if !app.me.hub}<button class="btn danger" onclick={deleteAccount}>{t('account.delete')}</button>{/if}
    </div>
    <p class="tiny muted">{#if !app.me.hub}{t('account.delete_note')} {/if}<a href="#/privacy">{t('auth.privacy_notice')}</a></p>
  </section>
</div>
{/if}

<style>
  .head { margin-bottom: 18px; }
  /* minmax(0, 1fr): a long label must never make the column wider than the phone */
  .layout { display: grid; gap: 14px; grid-template-columns: minmax(0, 1fr); }
  .layout > .card { min-width: 0; }
  @media (min-width: 1000px) { .layout { grid-template-columns: repeat(2, minmax(0, 1fr)); align-items: start; } }
  /* Options with long labels: one under the other, text allowed to wrap */
  .seg.stacked { flex-direction: column; overflow: visible; }
  .seg.stacked button { white-space: normal; text-align: left; justify-content: flex-start; padding: 7px 12px; line-height: 1.3; }
  @media (min-width: 560px) {
    .seg.stacked { flex-direction: row; }
    .seg.stacked button { text-align: center; justify-content: center; }
  }
  .email { overflow-wrap: anywhere; }
  .name { font-weight: 550; overflow-wrap: anywhere; }
  .list li:has(.bday) { padding: 0; }
  .bday { flex: 1; min-width: 0; display: flex; align-items: center; gap: 10px; padding: 9px 0; border: 0; background: none;
    font: inherit; color: inherit; text-align: left; cursor: pointer; }
  .bday:hover b { color: var(--primary); }
  .bday .d { display: block; }
  .sub { margin-top: 8px; }
  .list { list-style: none; margin: 0; padding: 0; }
  .list li { display: flex; align-items: center; gap: 8px; padding: 8px 0; border-bottom: 1px solid var(--line); }
  .list li:last-child { border: 0; }
  .list b { font-weight: 600; }
  .you { margin-left: 4px; }
  .invite { padding: 12px; border-radius: var(--r-md); background: var(--primary-soft); }
  .ic { display: flex; align-items: center; gap: 8px; }
  details summary { cursor: pointer; color: var(--primary); font-weight: 500; }
  .manual { margin-top: 8px; }
  .manual ol { margin: 0; padding-left: 20px; display: flex; flex-direction: column; gap: 4px; }
  .linkish { border: 0; background: none; padding: 0; color: var(--primary); cursor: pointer; text-decoration: underline; font: inherit; }
  .warn { color: var(--danger); }
  .creds { display: flex; flex-direction: column; gap: 6px; }
  .mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 0.85rem; }
  .qr { align-self: center; border-radius: var(--r-sm); background: #fff; padding: 4px; }
  .codes { margin: 0; padding: 10px; background: var(--surface); border-radius: var(--r-sm); columns: 2; font-size: 0.9rem; }
  .others { align-self: flex-start; }
  .code { margin: 0; padding: 10px; background: var(--surface-2); border-radius: var(--r-sm); font-size: 0.75rem; overflow-x: auto; white-space: pre; }
  .examples { margin-top: 8px; }
  .url { overflow-wrap: anywhere; }
  .how { margin: 8px 0 0; padding-left: 18px; display: flex; flex-direction: column; gap: 6px; }
  .toggle input:checked { background: var(--primary); }
</style>

<script>
  import { post, setUnauthorizedHandler } from './lib/api.js';
  import { app, clearCache, loadCache, loadCachedMe, loadItems, loadMe, loadNotifications, openEditor, showError, toast } from './lib/store.svelte.js';
  import { clearQueue, flush } from './lib/actions.js';
  import { registration, resyncPush } from './lib/push.js';
  import { setLanguage, t } from './lib/i18n.svelte.js';
  import { get } from './lib/api.js';
  import AppSwitcher from './components/AppSwitcher.svelte';
  import Toast from './components/Toast.svelte';
  import Icon from './components/Icon.svelte';
  import ItemSheet from './components/ItemSheet.svelte';
  import Bell from './components/Bell.svelte';
  import Notifications from './components/Notifications.svelte';
  import PostponeSheet from './components/PostponeSheet.svelte';
  import Trash from './pages/Trash.svelte';
  import LanguageSwitch from './components/LanguageSwitch.svelte';
  import Login from './pages/Login.svelte';
  import Signup from './pages/Signup.svelte';
  import ForgotPassword from './pages/ForgotPassword.svelte';
  import ResetPassword from './pages/ResetPassword.svelte';
  import VerifyEmail from './pages/VerifyEmail.svelte';
  import Invite from './pages/Invite.svelte';
  import Privacy from './pages/Privacy.svelte';
  import Agenda from './pages/Agenda.svelte';
  import Deadlines from './pages/Deadlines.svelte';
  import Appointments from './pages/Appointments.svelte';
  import Calendar from './pages/Calendar.svelte';
  import Lists from './pages/Lists.svelte';
  import Family from './pages/Family.svelte';

  const PAGES = [
    { id: 'agenda', comp: Agenda },
    { id: 'lists', comp: Lists },
    { id: 'deadlines', comp: Deadlines },
    { id: 'appointments', comp: Appointments },
    { id: 'calendar', comp: Calendar },
    { id: 'family', comp: Family },
  ];
  // Pages reachable without an account
  const PUBLIC = ['login', 'signup', 'forgot-password', 'reset', 'verify', 'invite', 'privacy'];

  let status = $state('loading'); // loading | ready | error
  let route = $state(readHash());

  function readHash() {
    const [path, query = ''] = location.hash.replace(/^#\/?/, '').split('?');
    const [name = '', param = ''] = path.split('/');
    return { name, param: decodeURIComponent(param), query: new URLSearchParams(query) };
  }
  $effect(() => {
    const onHash = () => { route = readHash(); window.scrollTo(0, 0); };
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  });

  const authenticated = $derived(!!app.me?.authenticated);
  // Page actually shown: only public pages without an account, app pages once signed in
  const page = $derived.by(() => {
    if (!authenticated) return PUBLIC.includes(route.name) ? route.name : 'login';
    if (['verify', 'invite', 'privacy', 'trash'].includes(route.name)) return route.name === 'trash' ? 'trash' : route.name;
    return PAGES.some((p) => p.id === route.name) ? route.name : 'agenda';
  });
  const Current = $derived(PAGES.find((p) => p.id === page)?.comp);
  const section = $derived(page === 'trash' ? 'lists' : page);

  // #/item/<id> (links from the calendar feed): open that item over the agenda
  $effect(() => {
    if (status !== 'ready' || !authenticated || route.name !== 'item') return;
    const id = Number(route.param);
    history.replaceState(null, '', '#/agenda');
    route = readHash();
    const found = app.items.find((i) => i.id === id);
    if (found) openEditor(found);
    else get(`/items/${id}`).then((i) => openEditor(i)).catch(showError);
  });
  // Keep the shared list fresh when coming back to the app (the other person may have changed things)
  $effect(() => {
    if (!authenticated) return;
    // Every few seconds while in view: has anything changed in the family? (cheap: one number)
    let busy = false;
    const tick = async () => {
      if (busy || document.visibilityState !== 'visible') return;
      busy = true;
      try {
        const s = await get('/sync');
        app.online = true;
        if (app.pending) await flush();
        if (app.version !== null && s.version !== app.version) await loadItems();
        app.version = s.version;
        if (s.unread !== app.notifications.unread) loadNotifications();
      } catch (e) {
        if (e.offline) app.online = false;
      } finally { busy = false; }
    };
    const onVisible = () => { if (document.visibilityState === 'visible') tick(); };
    const onOnline = () => { app.online = true; flush().then(tick); };
    const onOffline = () => (app.online = false);
    document.addEventListener('visibilitychange', onVisible);
    window.addEventListener('online', onOnline);
    window.addEventListener('offline', onOffline);
    const timer = setInterval(tick, 4000);
    tick();
    loadNotifications();
    resyncPush();
    return () => {
      document.removeEventListener('visibilitychange', onVisible);
      window.removeEventListener('online', onOnline);
      window.removeEventListener('offline', onOffline);
      clearInterval(timer);
    };
  });
  // A tap on a push notification while the app is open: show that item here
  $effect(() => {
    if (!('serviceWorker' in navigator)) return;
    registration().catch(() => {});
    const onMessage = (e) => {
      if (e.data?.type !== 'open') return;
      try { location.hash = new URL(e.data.url).hash || '#/agenda'; } catch { /* ignore */ }
      loadNotifications();
    };
    navigator.serviceWorker.addEventListener('message', onMessage);
    return () => navigator.serviceWorker.removeEventListener('message', onMessage);
  });

  setUnauthorizedHandler(() => { if (app.me) app.me = { ...app.me, authenticated: false }; });

  async function start() {
    try {
      let me;
      try {
        me = await loadMe();
      } catch (e) {
        // No connection: open with what was saved on this device
        const cached = e.offline ? loadCachedMe() : null;
        if (!cached?.authenticated) throw e;
        app.me = cached;
        app.online = false;
        if (cached.user.language) setLanguage(cached.user.language);
        loadCache();
        status = 'ready';
        return;
      }
      // The language saved in the profile wins over the browser's
      if (me.authenticated && me.user.language) setLanguage(me.user.language);
      if (me.authenticated) {
        loadCache(); // show at once, then refresh
        await flush();
        await loadItems().catch((e) => { if (!e.offline) throw e; });
      }
      status = 'ready';
    } catch (e) { showError(e); status = 'error'; }
  }
  start();

  async function logout(alreadyDeleted = false) {
    if (!alreadyDeleted) await post('/logout').catch(() => {});
    clearCache(); // nothing of the family stays on the device
    clearQueue();
    await loadMe().catch(() => {});
    location.hash = '#/login';
  }
  async function resend() {
    try { await post('/account/resend-verification'); toast(t('account.verification_sent')); } catch (e) { showError(e); }
  }
</script>

{#if status === 'loading'}
  <main class="center"><img class="pulse" src="/icon.svg" alt={t('common.wait')} width="56" height="56" /></main>
{:else if status === 'error'}
  <main class="center"><p class="empty">{t('error.server')}<br /><button class="btn soft" onclick={start}>{t('common.retry')}</button></p></main>
{:else if !authenticated || ['verify', 'invite', 'privacy'].includes(page)}
  <div class="public-language"><LanguageSwitch /></div>
  {#if page === 'signup'}<Signup ondone={start} external={!!route.query.get('external')} />
  {:else if page === 'forgot-password'}<ForgotPassword />
  {:else if page === 'reset'}<ResetPassword token={route.param} ondone={start} />
  {:else if page === 'verify'}<VerifyEmail token={route.param} ondone={start} />
  {:else if page === 'invite'}<Invite token={route.param} ondone={start} />
  {:else if page === 'privacy'}<Privacy />
  {:else}<Login ondone={start} initialError={route.query.get('error') ?? ''} />{/if}
{:else}
  <div class="shell">
    <nav class="nav" aria-label={t('nav.sections')}>
      <a class="logo" href="#/agenda"><img src="/icon.svg" alt="" width="28" height="28" /><span>doTrack</span></a>
      <div class="nav-apps hide-mobile"><AppSwitcher hub={app.me.hub} label /></div>
      {#each PAGES as p (p.id)}
        <a href="#/{p.id}" class:on={section === p.id} aria-current={page === p.id ? 'page' : undefined}>
          <span class="ico"><Icon name={p.id} size={22} /></span>
          <span class="lbl">{t('nav.' + p.id)}</span>
        </a>
      {/each}
      <div class="nav-bell hide-mobile"><Bell label /></div>
      <button class="logout hide-mobile" onclick={() => logout()} title={app.me.user.email}>
        <svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="M16 17l5-5-5-5"/><path d="M21 12H9"/></svg>
        <span class="lbl">{t('account.sign_out')}</span>
      </button>
    </nav>
    <main class="main">
      <!-- Phone: a slim top bar so signing out is always one tap away -->
      <div class="topbar hide-desktop">
        <a class="brand" href="#/agenda"><img src="/icon.svg" alt="" width="24" height="24" /><span>doTrack</span></a>
        <AppSwitcher hub={app.me.hub} />
        <span class="grow"></span>
        <Bell />
        <button class="btn ghost sm" onclick={() => logout()} aria-label={t('account.sign_out')}>
          <svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="M16 17l5-5-5-5"/><path d="M21 12H9"/></svg><span>{t('account.sign_out')}</span>
        </button>
      </div>
      {#if !app.online || app.pending}
        <div class="notice small offline" role="status">
          <span>{app.online ? t('offline.sending', { n: app.pending }) : app.pending ? t('offline.pending', { n: app.pending }) : t('offline.banner')}</span>
        </div>
      {/if}
      {#if !app.me.user.email_verified}
        <div class="notice small">
          <span>{t('account.not_verified', { email: app.me.user.email })}</span>
          <button class="btn ghost sm" onclick={resend}>{t('account.resend')}</button>
        </div>
      {/if}
      {#key page + ':' + app.me.family?.id}
        {#if page === 'family'}
          <Family onlogout={logout} initialError={route.query.get('error') ?? ''} />
        {:else if page === 'trash'}
          <Trash />
        {:else if page === 'lists'}
          {#key route.param}<Lists id={route.param} />{/key}
        {:else}
          <Current />
        {/if}
      {/key}
    </main>
  </div>
{/if}
{#if authenticated}<Notifications />{/if}
{#if app.postpone && authenticated}{#key app.postpone}<PostponeSheet />{/key}{/if}
{#if app.editor && authenticated}
  {#key app.editor}
    <ItemSheet item={app.editor.item ?? null} template={app.editor.template ?? {}} onclose={() => (app.editor = null)} />
  {/key}
{/if}
<Toast />

<style>
  .nav-apps { margin: -10px 0 8px; }
  .center { min-height: 100dvh; display: grid; place-items: center; padding: 16px; }
  .pulse { border-radius: 12px; animation: pulse 1s ease-in-out infinite alternate; }
  @keyframes pulse { to { opacity: 0.5; } }
  .public-language { position: absolute; top: 12px; right: 12px; z-index: 5; }

  .main { padding: 20px 16px calc(var(--nav-h) + 96px + env(safe-area-inset-bottom)); max-width: 1280px; margin: 0 auto; }
  .notice.offline { background: var(--danger-soft); color: var(--danger); font-weight: 550; }
  .notice { display: flex; align-items: center; justify-content: space-between; gap: 10px; flex-wrap: wrap;
    padding: 8px 12px; margin-bottom: 16px; border-radius: var(--r-sm); background: var(--primary-soft); }

  /* Phone: bottom bar */
  .nav {
    position: fixed; z-index: 50; left: 0; right: 0; bottom: 0;
    height: calc(var(--nav-h) + env(safe-area-inset-bottom)); padding: 6px 6px env(safe-area-inset-bottom);
    display: flex; background: var(--surface); border-top: 1px solid var(--line);
  }
  .logo { display: none; }
  .nav a:not(.logo) {
    flex: 1; min-width: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 3px;
    text-decoration: none; color: var(--muted); font-weight: 500; font-size: 0.7rem; border-radius: var(--r-sm);
    -webkit-tap-highlight-color: transparent;
  }
  .lbl { max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .ico { width: 22px; height: 22px; display: grid; place-items: center; }
  .nav a.on { color: var(--primary); }
  .topbar { display: flex; align-items: center; justify-content: space-between; margin: -8px 0 12px; }
  .brand { display: flex; align-items: center; gap: 8px; text-decoration: none; color: var(--ink); font-weight: 650; letter-spacing: -0.02em; }
  .brand img { border-radius: 6px; }
  .topbar .btn { gap: 6px; }
  .topbar .grow { flex: 1; }
  .topbar { gap: 4px; }
  .topbar .ico { width: 18px; height: 18px; }

  /* Desktop: sidebar */
  @media (min-width: 900px) {
    .shell { display: grid; grid-template-columns: 220px 1fr; }
    .nav { position: sticky; top: 0; height: 100dvh; flex-direction: column; gap: 2px; padding: 20px 12px; border-top: 0; border-right: 1px solid var(--line); }
    .logo { display: flex; align-items: center; gap: 10px; padding: 4px 10px 18px; text-decoration: none; color: var(--ink); font-size: 1.15rem; font-weight: 650; letter-spacing: -0.02em; }
    .logo img { border-radius: 7px; }
    .nav a:not(.logo) { flex: none; flex-direction: row; justify-content: flex-start; gap: 10px; padding: 9px 12px; font-size: 0.92rem; }
    .nav a:not(.logo) .ico { width: 18px; height: 18px; }
    .nav a:not(.logo) .ico :global(svg) { width: 18px; height: 18px; }
    .nav a.on { background: var(--primary-soft); }
    .main { padding: 32px 32px 48px; width: 100%; max-width: 1680px; }
    .nav-bell { margin-top: auto; padding: 0 6px; }
    .nav-bell :global(.bell) { width: 100%; padding: 9px 6px; font-size: 0.92rem; }
    .logout { display: flex; align-items: center; gap: 10px; padding: 9px 12px; border: 0; border-radius: var(--r-sm);
      background: transparent; color: var(--muted); font: inherit; font-weight: 500; font-size: 0.92rem; cursor: pointer; text-align: left;
    }
    .logout:hover { color: var(--ink); background: var(--surface-2); }
    .logout .ico { width: 18px; height: 18px; }
  }
</style>

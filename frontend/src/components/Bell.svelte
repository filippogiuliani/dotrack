<script>
  // The bell with the unread count; the panel itself is Notifications.svelte (rendered once in App)
  import { app, loadNotifications } from '../lib/store.svelte.js';
  import { t } from '../lib/i18n.svelte.js';
  import Icon from './Icon.svelte';

  let { label = false } = $props();
  const unread = $derived(app.notifications.unread);
  function open() { app.bell = true; loadNotifications(); }
</script>

<button class="bell" onclick={open} aria-label={unread ? `${t('notif.open')} – ${t('notif.unread', { n: unread })}` : t('notif.open')}
        title={t('notif.title')}>
  <span class="ico"><Icon name="bell" size={label ? 18 : 20} />{#if unread}<span class="count">{unread > 9 ? '9+' : unread}</span>{/if}</span>
  {#if label}<span class="lbl">{t('notif.title')}</span>{/if}
</button>

<style>
  .bell { position: relative; display: inline-flex; align-items: center; gap: 10px; border: 0; background: transparent; cursor: pointer;
    color: var(--muted); font: inherit; font-weight: 500; padding: 6px; border-radius: var(--r-sm); }
  .bell:hover { color: var(--ink); background: var(--surface-2); }
  .ico { position: relative; display: grid; place-items: center; }
  .count { position: absolute; top: -6px; right: -9px; min-width: 17px; height: 17px; padding: 0 4px; border-radius: 9px;
    background: var(--danger); color: #fff; font-size: 0.68rem; font-weight: 700; display: grid; place-items: center; line-height: 1; }
</style>

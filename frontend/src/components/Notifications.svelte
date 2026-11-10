<script>
  // Notifications panel: the latest ones, a tap opens the item
  import { get, post } from '../lib/api.js';
  import { app, openEditor, showError } from '../lib/store.svelte.js';
  import { language, t } from '../lib/i18n.svelte.js';
  import Icon from './Icon.svelte';
  import Sheet from './Sheet.svelte';

  const unread = $derived(app.notifications.unread);
  const ICONS = { reminder: 'bell', assigned: 'person', comment: 'comment', done: 'check' };

  const stamp = (s) => new Intl.DateTimeFormat(language.locale, { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
    .format(new Date(s.replace(' ', 'T') + 'Z'));

  async function show(n) {
    try {
      if (!n.read) app.notifications = await post('/notifications/read', { ids: [n.id] });
      if (n.item_id) {
        app.bell = false;
        const item = app.items.find((i) => i.id === n.item_id) ?? await get(`/items/${n.item_id}`);
        openEditor(item);
      }
    } catch (e) { showError(e); }
  }
  async function readAll() {
    try { app.notifications = await post('/notifications/read', {}); } catch (e) { showError(e); }
  }
</script>

{#if app.bell}
  <Sheet title={t('notif.title')} onclose={() => (app.bell = false)}>
    {#if !app.notifications.items.length}
      <p class="muted">{t('notif.empty')}</p>
    {:else}
      <ul class="notes">
        {#each app.notifications.items as n (n.id)}
          <li>
            <button class="note" class:unread={!n.read} onclick={() => show(n)}>
              <span class="nicon"><Icon name={ICONS[n.kind] ?? 'bell'} size={16} /></span>
              <span class="ntext">
                <b>{n.title}</b>
                {#if n.body}<span class="small nb">{n.body}</span>{/if}
                <span class="tiny muted">{stamp(n.created_at)}</span>
              </span>
            </button>
          </li>
        {/each}
      </ul>
    {/if}
    {#snippet footer()}
      {#if unread}<button class="btn grow" onclick={readAll}><Icon name="check" size={16} />{t('notif.read_all')}</button>{/if}
    {/snippet}
  </Sheet>
{/if}

<style>
  .notes { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; }
  .notes li { border-bottom: 1px solid var(--line); }
  .notes li:last-child { border: 0; }
  .note { width: 100%; display: flex; gap: 10px; align-items: flex-start; padding: 10px 4px; border: 0; background: none; text-align: left;
    cursor: pointer; font: inherit; color: var(--muted); }
  .note:hover b { color: var(--primary); }
  .note.unread { color: var(--ink); }
  .note.unread .nicon { background: var(--primary); color: var(--primary-ink); }
  .nicon { width: 28px; height: 28px; border-radius: 50%; display: grid; place-items: center; background: var(--surface-2); flex-shrink: 0; }
  .ntext { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
  .ntext b { font-weight: 600; overflow-wrap: anywhere; }
  .note:not(.unread) b { font-weight: 500; }
  .nb { overflow-wrap: anywhere; white-space: pre-wrap; }
</style>

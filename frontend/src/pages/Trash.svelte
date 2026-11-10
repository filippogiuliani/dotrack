<script>
  // Deleted items: restored with one tap, gone for good after 30 days (or when the trash is emptied)
  import { del, get } from '../lib/api.js';
  import { restore } from '../lib/actions.js';
  import { showError, toast } from '../lib/store.svelte.js';
  import { kindName, language, t } from '../lib/i18n.svelte.js';
  import Icon from '../components/Icon.svelte';

  let items = $state(null);
  async function load() {
    try { items = await get('/trash'); } catch (e) { showError(e); items = []; }
  }
  load();
  const when = (s) => new Intl.DateTimeFormat(language.locale, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
    .format(new Date(s.replace(' ', 'T') + 'Z'));
  async function back(item) {
    const { deleted_at, ...rest } = item;
    await restore({ ...rest, deleted_at: null });
    items = items.filter((x) => x.id !== item.id);
    toast(t('trash.restored'));
  }
  async function empty() {
    if (!confirm(t('trash.confirm_empty', { n: items.length }))) return;
    try { await del('/trash'); items = []; } catch (e) { showError(e); }
  }
</script>

<a class="back small" href="#/lists"><Icon name="left" size={16} />{t('nav.lists')}</a>
<header class="head">
  <div><h1>{t('trash.title')}</h1><p class="muted">{t('trash.explain')}</p></div>
  {#if items?.length}<button class="btn danger" onclick={empty}><Icon name="trash" size={16} />{t('trash.empty_button')}</button>{/if}
</header>

{#if items === null}
  <p class="muted">{t('common.wait')}</p>
{:else if !items.length}
  <p class="empty">{t('trash.empty')}</p>
{:else}
  <ul class="card list">
    {#each items as item (item.id)}
      <li>
        <span class="grow">
          <b>{item.title}</b>
          <span class="tiny muted">{kindName(item.kind)} · {t('trash.deleted_on', { date: when(item.deleted_at) })}
            {#if item.attachments.length} · <Icon name="clip" size={12} />{item.attachments.length}{/if}</span>
        </span>
        <button class="btn soft sm" onclick={() => back(item)}><Icon name="undo" size={15} />{t('trash.restore')}</button>
      </li>
    {/each}
  </ul>
{/if}

<style>
  .back { display: inline-flex; align-items: center; gap: 4px; margin-bottom: 10px; text-decoration: none; font-weight: 500; }
  .head { display: flex; flex-wrap: wrap; align-items: flex-end; justify-content: space-between; gap: 12px; margin-bottom: 16px; }
  .list { list-style: none; margin: 0; padding: 0; max-width: 760px; overflow: hidden; }
  .list li { display: flex; align-items: center; gap: 10px; padding: 10px 14px; border-bottom: 1px solid var(--line); }
  .list li:last-child { border: 0; }
  .grow { display: flex; flex-direction: column; min-width: 0; }
  .grow b { font-weight: 550; overflow-wrap: anywhere; }
  .grow .tiny { display: inline-flex; align-items: center; gap: 3px; flex-wrap: wrap; }
</style>

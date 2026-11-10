<script>
  // Deadlines: car tax, insurance, licence, documents… with a countdown
  import { app, openEditor, whoName } from '../lib/store.svelte.js';
  import { categoryName, t } from '../lib/i18n.svelte.js';
  import { fmtDate, fromNow } from '../lib/date.js';
  import { CATEGORIES, PRESETS, byDue, dueInfo, recurName } from '../lib/items.js';
  import Icon from '../components/Icon.svelte';
  import WhoFilter, { matchesWho } from '../components/WhoFilter.svelte';

  let who = $state('all');
  let category = $state('all');

  const all = $derived(app.items.filter((i) => i.kind === 'deadline' && !i.done && matchesWho(i, who)).sort(byDue));
  const used = $derived(CATEGORIES.filter((c) => all.some((i) => i.category === c)));
  const list = $derived(all.filter((i) => category === 'all' || i.category === category));
  // Presets not in use yet, as suggestions
  const suggestions = $derived(PRESETS.filter((p) => !app.items.some((i) => i.kind === 'deadline' && i.title === t('preset.' + p.key))));

  function fromPreset(p) {
    openEditor(null, { kind: 'deadline', title: t('preset.' + p.key), category: p.category, recur_unit: p.recur_unit,
                       recur_every: p.recur_every, remind_days: p.remind_days });
  }
</script>

<header class="head">
  <div>
    <h1>{t('nav.deadlines')}</h1>
    <p class="muted">{t('deadlines.subtitle')}</p>
  </div>
  <button class="btn primary" onclick={() => openEditor(null, { kind: 'deadline' })}><Icon name="plus" size={16} />{t('item.new_deadline')}</button>
</header>

<WhoFilter bind:value={who} />
{#if used.length > 1}
  <div class="chips scroll cats">
    <button class="chip" class:on={category === 'all'} onclick={() => (category = 'all')}>{t('common.all_f')}</button>
    {#each used as c (c)}
      <button class="chip" class:on={category === c} onclick={() => (category = c)}><Icon name={c} size={14} />{categoryName(c)}</button>
    {/each}
  </div>
{/if}

{#if app.loaded && !all.length}
  <p class="empty">{t('deadlines.empty')}</p>
{/if}

<div class="grid">
  {#each list as item (item.id)}
    {@const due = dueInfo(item)}
    <button class="card dl {due?.level}" onclick={() => openEditor(item)}>
      <div class="spread top">
        <span class="cat"><Icon name={item.category} size={15} />{item.subject || categoryName(item.category)}</span>
        {#if item.recur_unit}<span class="tiny muted rep"><Icon name="repeat" size={12} />{recurName(item.recur_unit, item.recur_every)}</span>{/if}
      </div>
      <h3>{#if item.priority > 0}<span class="flag" title={t('priority.high')}><Icon name="flag" size={15} /></span>{/if}{item.title}</h3>
      {#if item.due_date}
        <div class="when">
          <span class="big">{fromNow(item.due_date)}</span>
          <span class="small muted">{fmtDate(item.due_date)}</span>
        </div>
      {:else}
        <span class="small muted">{t('deadlines.no_date')}</span>
      {/if}
      <div class="foot tiny muted">
        {#if whoName(item)}<span><Icon name="person" size={12} />{whoName(item)}</span>{/if}
        {#if item.attachments.length}<span><Icon name="clip" size={12} />{item.attachments.length}</span>{/if}
      </div>
    </button>
  {/each}
</div>

{#if suggestions.length}
  <section class="suggest">
    <h2>{t('deadlines.suggestions')}</h2>
    <p class="muted small">{t('deadlines.suggestions_note')}</p>
    <div class="chips">
      {#each suggestions as p (p.key)}
        <button class="chip" onclick={() => fromPreset(p)}><Icon name="plus" size={13} />{t('preset.' + p.key)}</button>
      {/each}
    </div>
  </section>
{/if}

<style>
  .head { display: flex; flex-wrap: wrap; align-items: flex-end; justify-content: space-between; gap: 12px; margin-bottom: 16px; }
  .cats { margin: 8px 0 4px; }
  .grid { display: grid; gap: 12px; grid-template-columns: repeat(auto-fill, minmax(250px, 1fr)); margin-top: 14px; }
  .dl { text-align: left; cursor: pointer; display: flex; flex-direction: column; gap: 8px; padding: 16px; font: inherit; color: inherit; transition: border-color 0.12s; }
  .dl:hover { border-color: var(--primary); }
  .dl.warn { border-color: var(--primary); background: var(--primary-soft); }
  .dl.primary { border-color: var(--primary); box-shadow: inset 0 0 0 1px var(--primary); }
  .dl.danger { border-color: var(--danger); background: var(--danger-soft); }
  .dl.danger .big { color: var(--danger); }
  .top { align-items: flex-start; }
  .cat { display: inline-flex; align-items: center; gap: 6px; font-size: 0.8rem; font-weight: 600; color: var(--muted); text-transform: uppercase; letter-spacing: 0.04em; }
  .rep { display: inline-flex; align-items: center; gap: 4px; }
  h3 { font-size: 1.05rem; }
  .when { display: flex; align-items: baseline; flex-wrap: wrap; gap: 4px 10px; }
  .big { font-size: 1.25rem; font-weight: 650; letter-spacing: -0.02em; color: var(--primary); }
  .foot { display: flex; gap: 12px; }
  .foot span { display: inline-flex; align-items: center; gap: 4px; }
  .foot:empty { display: none; }
  .suggest { margin-top: 28px; display: flex; flex-direction: column; gap: 8px; max-width: 900px; }
  .flag { display: inline-flex; vertical-align: -2px; margin-right: 5px; color: var(--danger); }
</style>

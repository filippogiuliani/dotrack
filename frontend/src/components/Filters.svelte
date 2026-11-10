<script module>
  import { app, labelById, listById, whoName } from '../lib/store.svelte.js';

  export const GROUPS = ['when', 'category', 'list', 'who', 'priority'];
  export const emptyFilters = () => ({ q: '', kinds: [], categories: [], labels: [], priority: null, group: 'when' });

  /** Filters saved on this device, per page */
  export function loadFilters(key) {
    try {
      const saved = JSON.parse(localStorage.getItem('dotrack.filters.' + key) ?? 'null');
      if (saved && typeof saved === 'object') return { ...emptyFilters(), ...saved, q: '' };
    } catch { /* storage unavailable or invalid */ }
    return emptyFilters();
  }
  export function saveFilters(key, f) {
    try { localStorage.setItem('dotrack.filters.' + key, JSON.stringify({ ...f, q: '' })); } catch { /* ignore */ }
  }

  export const activeCount = (f) => f.kinds.length + f.categories.length + f.labels.length + (f.priority === null ? 0 : 1);

  export function matchesFilters(item, f) {
    if (f.kinds.length && !f.kinds.includes(item.kind)) return false;
    if (f.categories.length && (item.kind === 'birthday' || !f.categories.includes(item.category))) return false;
    if (f.priority !== null && (item.priority ?? 0) !== f.priority) return false;
    const labels = f.labels.filter((id) => labelById(id)); // a label deleted meanwhile no longer filters
    if (labels.length && !labels.some((id) => item.labels?.includes(id))) return false;
    const q = f.q.trim().toLowerCase();
    if (q) {
      const text = [item.title, item.notes, item.subject, item.location, whoName(item), listById(item.list_id)?.name,
                    ...(item.labels ?? []).map((id) => '#' + (labelById(id)?.name ?? ''))].filter(Boolean).join(' ').toLowerCase();
      if (!q.split(/\s+/).every((w) => text.includes(w))) return false;
    }
    return true;
  }
</script>

<script>
  // Search box + "Filters" panel: type, category, priority and (optionally) how to group the list
  import { categoryName, kindName, t } from '../lib/i18n.svelte.js';
  import { CATEGORIES, KINDS, PRIORITIES } from '../lib/items.js';
  import Icon from './Icon.svelte';

  let { value = $bindable(), groupable = false, categories = CATEGORIES } = $props();
  let open = $state(false);
  const count = $derived(activeCount(value));

  const toggle = (list, v) => (list.includes(v) ? list.filter((x) => x !== v) : [...list, v]);
  function reset() { value = { ...emptyFilters(), group: value.group }; }
</script>

<div class="bar">
  <label class="search grow">
    <span class="sr-only">{t('filter.search')}</span>
    <input class="input" type="search" bind:value={value.q} placeholder={t('filter.search')} />
  </label>
  <button class="btn" class:on={open || count} onclick={() => (open = !open)} aria-expanded={open}>
    <Icon name="filter" size={16} /><span class="hide-narrow">{t('filter.button')}</span>{#if count}<span class="count">{count}</span>{/if}
  </button>
</div>

{#if open}
  <div class="panel card">
    <div class="field">
      <span class="label">{t('filter.kind')}</span>
      <div class="chips">
        {#each KINDS as k (k)}
          <button class="chip" class:on={value.kinds.includes(k)} aria-pressed={value.kinds.includes(k)}
                  onclick={() => (value.kinds = toggle(value.kinds, k))}><Icon name={k} size={14} />{kindName(k)}</button>
        {/each}
      </div>
    </div>
    <div class="field">
      <span class="label">{t('filter.category')}</span>
      <div class="chips">
        {#each categories as c (c)}
          <button class="chip" class:on={value.categories.includes(c)} aria-pressed={value.categories.includes(c)}
                  onclick={() => (value.categories = toggle(value.categories, c))}><Icon name={c} size={14} />{categoryName(c)}</button>
        {/each}
      </div>
    </div>
    <div class="field">
      <span class="label">{t('filter.priority')}</span>
      <div class="chips">
        {#each PRIORITIES as p (p)}
          <button class="chip" class:on={value.priority === p} aria-pressed={value.priority === p}
                  onclick={() => (value.priority = value.priority === p ? null : p)}>
            {#if p > 0}<Icon name="flag" size={14} />{:else if p < 0}<Icon name="low" size={14} />{/if}{t('priority.' + p)}
          </button>
        {/each}
      </div>
    </div>
    {#if app.labels.length}
      <div class="field">
        <span class="label">{t('filter.labels')}</span>
        <div class="chips">
          {#each app.labels as l (l.id)}
            <button class="chip c-{l.color}" class:on={value.labels.includes(l.id)} aria-pressed={value.labels.includes(l.id)}
                    onclick={() => (value.labels = toggle(value.labels, l.id))}><span class="dot"></span>{l.name}</button>
          {/each}
        </div>
      </div>
    {/if}
    {#if groupable}
      <div class="field">
        <span class="label">{t('filter.group')}</span>
        <div class="seg">
          {#each GROUPS as g (g)}
            <button class:on={value.group === g} onclick={() => (value.group = g)}>{t('group.' + g)}</button>
          {/each}
        </div>
      </div>
    {/if}
    {#if count}<button class="btn ghost sm reset" onclick={reset}>{t('filter.reset')}</button>{/if}
  </div>
{/if}

<style>
  .bar { display: flex; gap: 8px; margin-bottom: 10px; max-width: 720px; }
  .btn.on { border-color: var(--primary); color: var(--primary); }
  .count { min-width: 20px; height: 20px; padding: 0 6px; border-radius: 10px; background: var(--primary); color: var(--primary-ink);
    font-size: 0.75rem; display: inline-grid; place-items: center; }
  .panel { display: flex; flex-direction: column; gap: 14px; margin-bottom: 12px; max-width: 900px; padding: 14px; }
  .reset { align-self: flex-start; }
  .search input::-webkit-search-cancel-button { cursor: pointer; }
  @media (max-width: 380px) { .hide-narrow { display: none; } }
</style>

<script>
  // Home: everything still to do, by when (or by category, person, priority), with notices on top
  import { app, listById, listOnly, openEditor, whoName } from '../lib/store.svelte.js';
  import { categoryName, kindName, t } from '../lib/i18n.svelte.js';
  import { BUCKETS, CATEGORIES, PRIORITIES, TICKABLE, bucket, byDue, ongoing, over, when } from '../lib/items.js';
  import { daysFromToday } from '../lib/date.js';
  import ItemRow from '../components/ItemRow.svelte';
  import QuickAdd from '../components/QuickAdd.svelte';
  import Icon from '../components/Icon.svelte';
  import WhoFilter, { matchesWho } from '../components/WhoFilter.svelte';
  import Filters, { activeCount, loadFilters, matchesFilters, saveFilters } from '../components/Filters.svelte';

  let who = $state('all');
  let showDone = $state(false);
  let filters = $state(loadFilters('agenda'));
  $effect(() => saveFilters('agenda', $state.snapshot(filters)));

  // Over: past appointments (they live in Appointments) and notices that ended. Birthdays only within a month.
  // Undated entries of a checklist (the shopping list) stay in their list.
  const visible = $derived(app.items.filter((i) => matchesWho(i, who) && matchesFilters(i, filters) && !over(i) && !listOnly(i) &&
    !(i.kind === 'birthday' && daysFromToday(when(i)) > 31)));
  // Notices going on now or starting within two weeks stay on top
  const isNotice = (i) => i.kind === 'note' && (ongoing(i) || daysFromToday(i.due_date) <= 14);
  const notices = $derived(visible.filter((i) => isNotice(i) && !i.done).sort(byDue));
  const open = $derived(visible.filter((i) => !i.done && !isNotice(i)).sort(byDue));
  const done = $derived(visible.filter((i) => i.done).sort((a, b) => b.done_at.localeCompare(a.done_at)));
  const todo = $derived(open.filter(TICKABLE));
  const overdue = $derived(todo.filter((i) => bucket(i) === 'overdue').length);
  const todayCount = $derived(todo.filter((i) => bucket(i) === 'today').length);
  const filtering = $derived(activeCount(filters) > 0 || !!filters.q.trim());

  /** Sections of the list, depending on how it is grouped */
  const sections = $derived.by(() => {
    const g = filters.group;
    let groups;
    if (g === 'category') {
      groups = [...CATEGORIES.map((c) => ({ id: c, title: categoryName(c), icon: c, test: (i) => i.kind !== 'birthday' && i.category === c })),
                { id: 'birthday', title: kindName('birthday'), icon: 'birthday', test: (i) => i.kind === 'birthday' }];
    } else if (g === 'priority') {
      groups = PRIORITIES.map((p) => ({ id: 'p' + p, title: t('priority.' + p), icon: p > 0 ? 'flag' : p < 0 ? 'low' : null,
                                        test: (i) => (i.priority ?? 0) === p }));
    } else if (g === 'list') {
      const ids = [...new Set(open.map((i) => i.list_id ?? 0))].sort((a, b) =>
        (a === 0 ? 1 : b === 0 ? -1 : (listById(a)?.position ?? 0) - (listById(b)?.position ?? 0)));
      groups = ids.map((id) => ({ id: 'l' + id, title: listById(id)?.name ?? t('item.no_list'), icon: id ? (listById(id)?.kind === 'project' ? 'project' : 'list') : null,
                                  test: (i) => (i.list_id ?? 0) === id }));
    } else if (g === 'who') {
      const names = [...new Set(open.map((i) => whoName(i) ?? ''))].sort((a, b) => (a === '' ? 1 : b === '' ? -1 : a.localeCompare(b)));
      groups = names.map((n) => ({ id: 'w' + n, title: n || t('assign.anyone'), icon: 'person', test: (i) => (whoName(i) ?? '') === n }));
    } else {
      groups = BUCKETS.map((b) => ({ id: b, title: t('bucket.' + b), late: b === 'overdue', test: (i) => bucket(i) === b }));
    }
    return groups.map((s) => ({ ...s, items: open.filter(s.test) })).filter((s) => s.items.length);
  });

  // Quick add follows the "who" filter: added while looking at Sara's things, it is Sara's
  const quickDefaults = $derived.by(() => {
    if (who.startsWith('p')) return { person_id: Number(who.slice(1)) };
    if (who === 'mine') return { assignee_id: app.me.user.id };
    return Number(who) ? { assignee_id: Number(who) } : {};
  });
</script>

<header class="head">
  <div>
    <h1>{t('agenda.hello', { name: app.me.user.name })}</h1>
    <p class="muted">
      {#if !todo.length}{t('agenda.all_clear')}
      {:else}{t('agenda.summary', { n: todo.length })}{#if todayCount} · {t('agenda.today_n', { n: todayCount })}{/if}{#if overdue} · <span class="late">{t('agenda.overdue_n', { n: overdue })}</span>{/if}{/if}
    </p>
  </div>
  <button class="btn primary" onclick={() => openEditor()}><Icon name="plus" size={16} />{t('item.new')}</button>
</header>

<QuickAdd defaults={quickDefaults} />

<WhoFilter bind:value={who} />
<Filters bind:value={filters} groupable />

{#if !app.loaded}
  <p class="muted">{t('common.wait')}</p>
{:else if filtering && !sections.length && !notices.length}
  <p class="empty">{t('filter.none')}</p>
{:else if !sections.length && !notices.length}
  <div class="empty">
    <p>{t('agenda.empty')}</p>
    <div class="row wrap center">
      <button class="btn soft sm" onclick={() => openEditor(null, { kind: 'deadline' })}>{t('item.new_deadline')}</button>
      <button class="btn soft sm" onclick={() => openEditor(null, { kind: 'appointment' })}>{t('item.new_appointment')}</button>
    </div>
  </div>
{/if}

<div class="sections">
  {#if notices.length}
    <section>
      <h2 class="notice-title"><Icon name="note" size={16} />{t('agenda.notices')}</h2>
      <div class="card list notices">
        {#each notices as item (item.id)}<ItemRow {item} />{/each}
      </div>
    </section>
  {/if}
  {#each sections as s (s.id)}
    <section>
      <h2 class:late={s.late}>{#if s.icon}<Icon name={s.icon} size={16} />{/if}{s.title} <span class="badge">{s.items.length}</span></h2>
      <div class="card list">
        {#each s.items as item (item.id)}<ItemRow {item} showKind showDate={filters.group !== 'when' || !['today', 'tomorrow'].includes(s.id)} />{/each}
      </div>
    </section>
  {/each}
</div>

{#if done.length}
  <section class="done">
    <button class="btn ghost sm" onclick={() => (showDone = !showDone)}>{showDone ? t('agenda.hide_done') : t('agenda.show_done', { n: done.length })}</button>
    {#if showDone}
      <div class="card list">{#each done as item (item.id)}<ItemRow {item} showKind />{/each}</div>
    {/if}
  </section>
{/if}

<style>
  .head { display: flex; flex-wrap: wrap; align-items: flex-end; justify-content: space-between; gap: 12px; margin-bottom: 16px; }
  .late { color: var(--danger); }
  .sections { display: flex; flex-direction: column; gap: 20px; margin-top: 16px; max-width: 900px; }
  section h2 { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; font-size: 0.95rem; }
  .list { padding: 0; overflow: hidden; }
  .notice-title { color: var(--danger); }
  .notices { border-color: color-mix(in srgb, var(--danger) 35%, var(--line)); background: color-mix(in srgb, var(--danger-soft) 55%, var(--surface)); }
  .done { margin-top: 20px; max-width: 900px; display: flex; flex-direction: column; gap: 8px; align-items: flex-start; }
  .done .list { width: 100%; }
  .empty { max-width: 720px; display: flex; flex-direction: column; gap: 12px; margin-top: 16px; }
  .center { justify-content: center; }
  /* Wide screens: the groups (overdue, today, next days…) side by side */
  @media (min-width: 1400px) {
    .sections { display: block; max-width: none; columns: 2 460px; column-gap: 24px; }
    .sections > :global(*) { break-inside: avoid; margin: 0 0 20px; }
    .done { max-width: none; }
  }
</style>

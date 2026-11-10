<script>
  // "Postpone to…": tomorrow, in a few days, next weekend, next week or a chosen day
  import { app } from '../lib/store.svelte.js';
  import { postpone } from '../lib/actions.js';
  import { t } from '../lib/i18n.svelte.js';
  import { addDays, fmtDayMonth, parse, today } from '../lib/date.js';
  import Sheet from './Sheet.svelte';

  const item = app.postpone;
  const now = today();
  const wd = (parse(now).getDay() + 6) % 7; // Monday = 0
  const options = [
    ...(item.due_date && item.due_date < now ? [{ key: 'today', date: now }] : []),
    { key: 'tomorrow', date: addDays(now, 1) },
    { key: 'in_2_days', date: addDays(now, 2) },
    ...(wd < 5 ? [{ key: 'weekend', date: addDays(now, 5 - wd) }] : []),
    { key: 'next_monday', date: addDays(now, 7 - wd) },
    { key: 'in_a_week', date: addDays(item.due_date && item.due_date > now ? item.due_date : now, 7) },
  ];
  let custom = $state(item.due_date ?? addDays(now, 1));
  const close = () => (app.postpone = null);
  async function go(date) {
    close();
    await postpone(item, date);
  }
</script>

<Sheet title={t('postpone.title')} onclose={close}>
  <p class="small muted title">{item.title}</p>
  <div class="opts">
    {#each options as o (o.key)}
      <button class="opt" onclick={() => go(o.date)}><span>{t('postpone.' + o.key)}</span><span class="muted small">{fmtDayMonth(o.date)}</span></button>
    {/each}
  </div>
  <form class="row pick" onsubmit={(e) => { e.preventDefault(); if (custom) go(custom); }}>
    <input class="input grow" type="date" bind:value={custom} aria-label={t('postpone.pick')} />
    <button class="btn primary" disabled={!custom}>{t('postpone.move')}</button>
  </form>
</Sheet>

<style>
  .title { margin-bottom: 8px; overflow-wrap: anywhere; }
  .opts { display: flex; flex-direction: column; }
  .opt { display: flex; justify-content: space-between; align-items: center; gap: 12px; padding: 12px 4px; border: 0;
    border-bottom: 1px solid var(--line); background: none; font: inherit; font-weight: 550; cursor: pointer; text-align: left; color: var(--ink); }
  .opt:hover { color: var(--primary); }
  .pick { margin-top: 14px; }
</style>

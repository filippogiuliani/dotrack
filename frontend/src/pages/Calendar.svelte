<script>
  // Everything with a date: month, week or day (with the hours)
  import { app, openEditor } from '../lib/store.svelte.js';
  import { t } from '../lib/i18n.svelte.js';
  import { addDays, fmtFull, fmtMonth, fmtShort, iso, parse, today, weekdayName } from '../lib/date.js';
  import { byDue, daysIn } from '../lib/items.js';
  import ItemRow from '../components/ItemRow.svelte';
  import Icon from '../components/Icon.svelte';
  import WhoFilter, { matchesWho } from '../components/WhoFilter.svelte';
  import Filters, { loadFilters, matchesFilters, saveFilters } from '../components/Filters.svelte';

  let who = $state('all');
  let filters = $state(loadFilters('calendar'));
  $effect(() => saveFilters('calendar', $state.snapshot(filters)));
  let month = $state(today().slice(0, 7) + '-01');
  let selected = $state(today());
  const VIEWS = ['month', 'week', 'day'];
  let view = $state((() => { try { return VIEWS.includes(localStorage.getItem('dotrack.calview')) ? localStorage.getItem('dotrack.calview') : 'month'; } catch { return 'month'; } })());
  $effect(() => { try { localStorage.setItem('dotrack.calview', view); } catch { /* ignore */ } });
  let narrow = $state(window.matchMedia('(max-width: 699px)').matches);
  $effect(() => {
    const mq = window.matchMedia('(max-width: 699px)');
    const on = () => (narrow = mq.matches);
    mq.addEventListener('change', on);
    return () => mq.removeEventListener('change', on);
  });
  const visibleItems = $derived(app.items.filter((x) => x.due_date && matchesWho(x, who) && matchesFilters(x, filters)));

  // ---- Week / day: columns of days, untimed things on top, timed ones on the hours
  const HOUR = 46; // px per hour
  const monday = (d) => addDays(d, -((parse(d).getDay() + 6) % 7));
  const columns = $derived(view === 'day' ? [selected] : Array.from({ length: 7 }, (_, i) => addDays(monday(selected), i)));
  const minutes = (hhmm) => { const [h, m] = hhmm.split(':').map(Number); return h * 60 + m; };
  /** Per day: untimed items, and timed ones with their place (top, height, lane) so overlaps sit side by side */
  const perDay = $derived.by(() => {
    const out = new Map();
    for (const d of columns) {
      const list = visibleItems.filter((i) => daysIn(i, d, d).length);
      const allDay = list.filter((i) => !i.due_time).sort(byDue);
      const timed = list.filter((i) => i.due_time).map((i) => {
        const start = minutes(i.due_time);
        const end = Math.max(start + 30, i.end_time && minutes(i.end_time) > start ? minutes(i.end_time) : start + 60);
        return { item: i, start, end };
      }).sort((a, b) => a.start - b.start || b.end - a.end);
      // Lanes: each event takes the first lane free at its start; a cluster of overlapping events shares the width
      let cluster = [], clusterEnd = -1;
      const lanesEnd = [];
      const close = () => { const n = Math.max(...cluster.map((c) => c.lane)) + 1; cluster.forEach((c) => (c.lanes = n)); cluster = []; lanesEnd.length = 0; };
      for (const ev of timed) {
        if (ev.start >= clusterEnd && cluster.length) close();
        let lane = lanesEnd.findIndex((e) => e <= ev.start);
        if (lane < 0) { lane = lanesEnd.length; lanesEnd.push(ev.end); } else lanesEnd[lane] = ev.end;
        ev.lane = lane;
        cluster.push(ev);
        clusterEnd = Math.max(clusterEnd, ev.end);
      }
      if (cluster.length) close();
      out.set(d, { allDay, timed });
    }
    return out;
  });
  let scroller = $state();
  $effect(() => { if (scroller && view !== 'month') scroller.scrollTop = HOUR * 7 - 8; }); // the morning in view
  let nowMin = $state(new Date().getHours() * 60 + new Date().getMinutes());
  $effect(() => { const id = setInterval(() => (nowMin = new Date().getHours() * 60 + new Date().getMinutes()), 60000); return () => clearInterval(id); });
  function newAt(d, e) {
    const y = e.clientY - e.currentTarget.getBoundingClientRect().top;
    const slot = Math.max(0, Math.min(23 * 60 + 30, Math.floor((y / HOUR) * 2) * 30));
    openEditor(null, { kind: 'appointment', due_date: d, due_time: `${String(Math.floor(slot / 60)).padStart(2, '0')}:${String(slot % 60).padStart(2, '0')}` });
  }
  const rangeTitle = $derived(view === 'day' ? fmtFull(selected)
    : `${fmtShort(columns[0])} – ${fmtShort(columns[6])} ${columns[6].slice(0, 4)}`);


  // 6 weeks starting on the Monday on or before the 1st
  const days = $derived.by(() => {
    const first = parse(month);
    const startDay = addDays(month, -((first.getDay() + 6) % 7));
    return Array.from({ length: 42 }, (_, i) => addDays(startDay, i));
  });
  const weeks = $derived(days.slice(35).every((d) => d.slice(0, 7) !== month.slice(0, 7)) ? days.slice(0, 35) : days);

  // Items per day of the visible weeks: notices over a period show on each of their days, birthdays every year
  const byDay = $derived.by(() => {
    const m = new Map();
    const from = weeks[0], to = weeks[weeks.length - 1];
    for (const i of app.items.filter((x) => x.due_date && matchesWho(x, who) && matchesFilters(x, filters))) {
      for (const d of daysIn(i, from, to)) {
        if (!m.has(d)) m.set(d, []);
        m.get(d).push(i);
      }
    }
    // Notices and birthdays first: they say what kind of day it is
    const rank = (i) => (i.kind === 'note' ? 0 : i.kind === 'birthday' ? 1 : 2);
    for (const list of m.values()) list.sort((a, b) => rank(a) - rank(b) || byDue(a, b));
    return m;
  });

  function shift(n) {
    if (view !== 'month') {
      selected = addDays(selected, n * (view === 'week' ? 7 : 1));
      month = selected.slice(0, 7) + '-01';
      return;
    }
    const d = parse(month);
    d.setMonth(d.getMonth() + n);
    month = iso(d);
  }
  function goToday() { month = today().slice(0, 7) + '-01'; selected = today(); }
  // The selected day may be outside the month shown
  const dayItems = $derived(app.items.filter((x) => matchesWho(x, who) && matchesFilters(x, filters) && daysIn(x, selected, selected).length)
    .sort((a, b) => (a.kind === 'note' ? -1 : 0) - (b.kind === 'note' ? -1 : 0) || byDue(a, b)));
</script>

<header class="head">
  <h1>{t('nav.calendar')}</h1>
  <div class="seg views" role="tablist">
    {#each VIEWS as v (v)}<button role="tab" aria-selected={view === v} class:on={view === v} onclick={() => (view = v)}>{t('calendar.view_' + v)}</button>{/each}
  </div>
  <button class="btn primary" onclick={() => openEditor(null, { due_date: selected, kind: 'appointment' })}><Icon name="plus" size={16} />{t('item.new')}</button>
</header>

<WhoFilter bind:value={who} />
<Filters bind:value={filters} />

{#if view !== 'month'}
  <div class="card cal tg-card">
    <div class="spread bar">
      <button class="btn icon sm ghost" onclick={() => shift(-1)} aria-label={t('calendar.previous')}><Icon name="left" /></button>
      <button class="month" onclick={goToday} title={t('calendar.today')}>{rangeTitle}</button>
      <button class="btn icon sm ghost" onclick={() => shift(1)} aria-label={t('calendar.next')}><Icon name="right" /></button>
    </div>
    {#if view === 'week' && narrow}
      <!-- Phone: the week as a list of days -->
      <div class="wlist">
        {#each columns as d (d)}
          {@const day = perDay.get(d)}
          <section class:today={d === today()}>
            <button class="wday" onclick={() => { selected = d; view = 'day'; }}>{fmtFull(d)}</button>
            {#if day.allDay.length || day.timed.length}
              <div class="list">
                {#each [...day.allDay, ...day.timed.map((x) => x.item)] as item (item.id)}<ItemRow {item} showDate={false} showKind />{/each}
              </div>
            {:else}<p class="tiny muted none">{t('calendar.nothing')}</p>{/if}
          </section>
        {/each}
      </div>
    {:else}
      <div class="tg" style:--cols={columns.length}>
        <div class="tg-head">
          <span class="gutter"></span>
          {#each columns as d (d)}
            <button class="dh" class:today={d === today()} onclick={() => { selected = d; view = 'day'; }}>
              <span class="tiny muted">{weekdayName((parse(d).getDay() + 6) % 7, 'short')}</span><b>{parse(d).getDate()}</b></button>
          {/each}
        </div>
        <div class="tg-allday">
          <span class="gutter tiny muted">{t('calendar.all_day')}</span>
          {#each columns as d (d)}
            <div class="ad">
              {#each perDay.get(d).allDay as i (i.id)}
                <button class="ev {i.kind}" class:done={i.done} onclick={() => openEditor(i)}>{i.title}</button>
              {/each}
            </div>
          {/each}
        </div>
        <div class="tg-body" bind:this={scroller}>
          <div class="hours">
            {#each Array(24) as _, h (h)}<span class="hl" style:top="{h * HOUR}px">{String(h).padStart(2, '0')}:00</span>{/each}
          </div>
          {#each columns as d (d)}
            <div class="col" style:height="{HOUR * 24}px" onclick={(e) => e.target === e.currentTarget && newAt(d, e)} role="presentation">
              {#each Array(24) as _, h (h)}<span class="line" style:top="{h * HOUR}px"></span>{/each}
              {#if d === today()}<span class="now" style:top="{(nowMin / 60) * HOUR}px"></span>{/if}
              {#each perDay.get(d).timed as ev (ev.item.id)}
                <button class="ev timed {ev.item.kind}" class:done={ev.item.done} onclick={() => openEditor(ev.item)}
                        style:top="{(ev.start / 60) * HOUR}px" style:height="{Math.max(((ev.end - ev.start) / 60) * HOUR - 2, 20)}px"
                        style:left="calc({(ev.lane / ev.lanes) * 100}% + 2px)" style:width="calc({100 / ev.lanes}% - 4px)">
                  <span class="et">{ev.item.due_time}</span> {ev.item.title}
                  {#if ev.item.location && ev.end - ev.start >= 60}<span class="el">{ev.item.location}</span>{/if}
                </button>
              {/each}
            </div>
          {/each}
        </div>
      </div>
      <p class="tiny muted tip">{t('calendar.tap_to_add')}</p>
    {/if}
  </div>
{:else}
<div class="layout">
  <div class="card cal">
    <div class="spread bar">
      <button class="btn icon sm ghost" onclick={() => shift(-1)} aria-label={t('calendar.previous')}><Icon name="left" /></button>
      <button class="month" onclick={goToday} title={t('calendar.today')}>{fmtMonth(month)}</button>
      <button class="btn icon sm ghost" onclick={() => shift(1)} aria-label={t('calendar.next')}><Icon name="right" /></button>
    </div>
    <div class="grid">
      {#each Array(7) as _, i (i)}<div class="wd">{weekdayName(i, 'narrow')}</div>{/each}
      {#each weeks as d (d)}
        {@const list = byDay.get(d) ?? []}
        <button class="day" class:other={d.slice(0, 7) !== month.slice(0, 7)} class:today={d === today()} class:sel={d === selected}
                onclick={() => (selected = d)} aria-label={fmtFull(d) + (list.length ? ` – ${list.length}` : '')}>
          <span class="n">{parse(d).getDate()}</span>
          <span class="ev hide-mobile">
            {#each list.slice(0, 3) as i (i.id)}<span class="e {i.kind}" class:done={i.done}>{#if i.kind === 'birthday'}<span class="bi"><Icon name="birthday" size={11} /></span>{/if}{i.due_time ? i.due_time + ' ' : ''}{i.title}</span>{/each}
            {#if list.length > 3}<span class="more">+{list.length - 3}</span>{/if}
          </span>
          <span class="dots hide-desktop">{#each list.slice(0, 4) as i (i.id)}<i class="{i.kind}" class:done={i.done}></i>{/each}</span>
        </button>
      {/each}
    </div>
  </div>

  <section class="dayview">
    <h2>{fmtFull(selected)}</h2>
    {#if dayItems.length}
      <div class="card list">{#each dayItems as item (item.id)}<ItemRow {item} showDate={false} showKind />{/each}</div>
    {:else}
      <p class="empty small">{t('calendar.nothing')}</p>
    {/if}
    <div class="row wrap">
      <button class="btn soft sm" onclick={() => openEditor(null, { kind: 'task', due_date: selected })}>{t('item.new_task')}</button>
      <button class="btn soft sm" onclick={() => openEditor(null, { kind: 'appointment', due_date: selected })}>{t('item.new_appointment')}</button>
      <button class="btn soft sm" onclick={() => openEditor(null, { kind: 'deadline', due_date: selected })}>{t('item.new_deadline')}</button>
      <button class="btn soft sm" onclick={() => openEditor(null, { kind: 'note', due_date: selected })}>{t('item.new_note')}</button>
    </div>
  </section>
</div>
{/if}

<style>
  .head { display: flex; align-items: flex-end; justify-content: space-between; gap: 12px; margin-bottom: 16px; flex-wrap: wrap; }
  .views { flex: 0 1 auto; margin-left: auto; }
  .head h1 { margin-right: auto; }
  .tg-card { margin-top: 12px; padding: 12px; }
  .tg { display: flex; flex-direction: column; }
  .tg-head, .tg-allday { display: grid; grid-template-columns: 52px repeat(var(--cols), minmax(0, 1fr)); gap: 2px; }
  .gutter { font-size: 0.7rem; align-self: center; }
  .dh { border: 0; background: none; cursor: pointer; display: flex; flex-direction: column; align-items: center; padding: 4px 0; border-radius: var(--r-sm); font: inherit; color: inherit; }
  .dh:hover { background: var(--surface-2); }
  .dh b { font-size: 1.05rem; width: 30px; height: 30px; display: grid; place-items: center; border-radius: 50%; }
  .dh.today b { background: var(--primary); color: var(--primary-ink); }
  .tg-allday { border-bottom: 1px solid var(--line); padding: 4px 0; }
  .ad { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
  .tg-body { position: relative; display: grid; grid-template-columns: 52px repeat(var(--cols), minmax(0, 1fr)); gap: 2px;
    max-height: min(65vh, 640px); overflow-y: auto; }
  .hours { position: relative; }
  .hl { position: absolute; right: 8px; transform: translateY(-50%); font-size: 0.68rem; color: var(--muted); }
  .hl:first-child { display: none; }
  .col { position: relative; border-left: 1px solid var(--line); cursor: copy; }
  .line { position: absolute; left: 0; right: 0; border-top: 1px solid var(--line); pointer-events: none; }
  .now { position: absolute; left: 0; right: 0; border-top: 2px solid var(--danger); z-index: 2; pointer-events: none; }
  .ev { display: block; width: 100%; text-align: left; border: 0; cursor: pointer; font: inherit; font-size: 0.74rem; line-height: 1.25;
    padding: 2px 6px; border-radius: 5px; background: var(--surface-2); color: var(--ink); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .ev.appointment { background: var(--primary-soft); color: var(--primary); font-weight: 550; }
  .ev.note { background: var(--danger-soft); color: var(--danger); font-weight: 550; }
  .ev.done { text-decoration: line-through; opacity: 0.6; }
  .ev.timed { position: absolute; white-space: normal; z-index: 1; border-left: 3px solid var(--primary); }
  .ev.timed.task, .ev.timed.deadline { border-left-color: var(--muted); }
  .et { font-weight: 700; }
  .el { display: block; opacity: 0.8; font-weight: 400; }
  .tip { margin-top: 8px; }
  .wlist { display: flex; flex-direction: column; gap: 12px; }
  .wlist .wday { border: 0; background: none; padding: 0 0 4px; font: inherit; font-weight: 650; text-transform: capitalize; cursor: pointer; color: var(--ink); }
  .wlist section.today .wday { color: var(--primary); }
  .wlist .list { border: 1px solid var(--line); border-radius: var(--r-md); }
  .none { padding-left: 2px; }
  .layout { display: grid; gap: 16px; margin-top: 12px; }
  @media (min-width: 1100px) { .layout { grid-template-columns: 1fr 340px; align-items: start; } }
  .cal { padding: 12px; }
  .bar { margin-bottom: 8px; }
  .month { border: 0; background: none; cursor: pointer; font-weight: 650; font-size: 1.05rem; text-transform: capitalize; padding: 4px 10px; border-radius: var(--r-sm); }
  .month:hover { background: var(--surface-2); }
  .grid { display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); gap: 2px; }
  .wd { text-align: center; font-size: 0.72rem; font-weight: 600; color: var(--muted); text-transform: uppercase; padding: 4px 0; }
  .day { min-height: 52px; border: 1px solid transparent; border-radius: var(--r-sm); background: none; cursor: pointer; padding: 4px;
    display: flex; flex-direction: column; align-items: center; gap: 3px; font: inherit; color: inherit; overflow: hidden; }
  .day:hover { background: var(--surface-2); }
  .day.other { color: var(--muted); opacity: 0.55; }
  .day.sel { border-color: var(--primary); background: var(--primary-soft); }
  .n { font-size: 0.85rem; font-weight: 550; width: 26px; height: 26px; display: grid; place-items: center; border-radius: 50%; }
  .today .n { background: var(--primary); color: var(--primary-ink); }
  .dots { display: flex; gap: 3px; }
  .dots i { width: 5px; height: 5px; border-radius: 50%; background: var(--primary); }
  .dots i.note { background: var(--danger); }
  .dots i.birthday { background: transparent; box-shadow: inset 0 0 0 1.5px var(--primary); }
  .dots i.done { background: var(--line-strong); }
  @media (min-width: 900px) {
    .day { min-height: 92px; align-items: stretch; }
    .n { align-self: flex-end; }
    .ev { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
    .e { font-size: 0.72rem; text-align: left; padding: 1px 5px; border-radius: 4px; background: var(--surface-2); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .e.appointment { background: var(--primary-soft); color: var(--primary); font-weight: 550; }
    .e.note { background: var(--danger-soft); color: var(--danger); font-weight: 550; }
    .bi { display: inline-block; vertical-align: -1px; margin-right: 3px; }
    .e.birthday { background: none; color: var(--primary); font-weight: 550; padding-left: 2px; }
    .e.done { text-decoration: line-through; color: var(--muted); background: none; }
    .more { font-size: 0.7rem; color: var(--muted); text-align: left; padding-left: 5px; }
  }
  .dayview { display: flex; flex-direction: column; gap: 10px; }
  .dayview h2 { text-transform: capitalize; font-size: 1rem; }
  .list { padding: 0; overflow: hidden; }
</style>

<script>
  // One item in a list: tick to complete, tap to open. On phones swipe right to complete, left to postpone;
  // on computers a "postpone" button shows on hover.
  import { app, hasOthers, labelById, listById, openEditor, whoName } from '../lib/store.svelte.js';
  import { complete, reopen } from '../lib/actions.js';
  import { categoryName, kindName, t } from '../lib/i18n.svelte.js';
  import { fmtDayMonth, fmtRange, fromNow } from '../lib/date.js';
  import { TICKABLE, age, dueInfo, ongoing, recurName, when } from '../lib/items.js';
  import Icon from './Icon.svelte';

  let { item, showDate = true, showKind = false, showList = true, compact = false, handle = false } = $props();
  let busy = $state(false);
  const due = $derived(dueInfo(item));
  const assignee = $derived(whoName(item));
  const shared = $derived(hasOthers());
  const tickable = $derived(TICKABLE(item));
  const date = $derived(when(item));
  const years = $derived(item.kind === 'birthday' && item.due_date ? age(item) : null);
  const labels = $derived((item.labels ?? []).map(labelById).filter(Boolean));
  const list = $derived(showList ? listById(item.list_id) : null);
  const answered = $derived(item.checks.filter((c) => (item.kind === 'appointment' ? c.answer : c.done)).length);
  const qty = $derived(/^\d+([.,]\d+)?$/.test(item.quantity ?? '') ? '×' + item.quantity : item.quantity);
  const movable = $derived(tickable && !item.done && item.kind !== 'birthday');

  async function toggle() {
    busy = true;
    try { await (item.done ? reopen(item) : complete(item)); } finally { busy = false; }
  }

  // ---- Swipe (touch only)
  const LIMIT = 84;
  let dx = $state(0);
  let start = null;
  function down(e) {
    if (e.pointerType !== 'touch' || !tickable || e.target.closest('.handle')) return;
    start = { x: e.clientX, y: e.clientY, horizontal: null };
  }
  function move(e) {
    if (!start) return;
    const x = e.clientX - start.x, y = e.clientY - start.y;
    if (start.horizontal === null && (Math.abs(x) > 8 || Math.abs(y) > 8)) start.horizontal = Math.abs(x) > Math.abs(y) * 1.3;
    if (!start.horizontal) return;
    dx = Math.max(-140, Math.min(140, x));
    if (x < 0 && !movable) dx = Math.max(dx, -24);
  }
  let swiped = false; // the click that ends a swipe must not open the item
  function up() {
    if (!start) return;
    const d = dx;
    if (start.horizontal) { swiped = true; setTimeout(() => (swiped = false), 80); }
    start = null;
    dx = 0;
    if (d > LIMIT) toggle();
    else if (d < -LIMIT && movable) app.postpone = item;
  }
  function open() {
    if (!swiped) openEditor(item);
  }
</script>

<div class="swipe" class:right={dx > 0} class:left={dx < 0} class:armed={Math.abs(dx) > LIMIT}>
<span class="hint r"><Icon name={item.done ? 'undo' : 'check'} size={18} /></span>
<span class="hint l"><Icon name="deadline" size={18} /></span>
<div class="row-item" class:done={item.done} class:compact class:pending={item.offline} style:transform={dx ? `translateX(${dx}px)` : null}
     role="group" aria-label={item.title} class:dragging={dx !== 0} onpointerdown={down} onpointermove={move} onpointerup={up} onpointercancel={up} data-id={item.id}>
  {#if handle}<span class="handle" aria-hidden="true">⠿</span>{/if}
  {#if tickable}
    <button class="tick" class:on={item.done} disabled={busy} onclick={toggle}
            aria-label={item.done ? t('item.mark_open', { title: item.title }) : t('item.mark_done', { title: item.title })}>
      {#if item.done}<Icon name="check" size={14} />{/if}
    </button>
  {:else}
    <span class="mark {item.kind}" title={kindName(item.kind)}><Icon name={item.kind} size={14} /></span>
  {/if}
  <button class="body" onclick={open}>
    <span class="title">
      {#if showKind && tickable && item.kind !== 'task'}<span class="kind"><Icon name={item.kind} size={15} /></span>{/if}
      {#if item.priority > 0}<span class="prio high" title={t('priority.high')}><Icon name="flag" size={14} /></span>{/if}
      <span class="t">{item.title}</span>
      {#if item.quantity}<span class="qty">{qty}</span>{/if}
      {#if item.priority < 0}<span class="prio low" title={t('priority.label') + ': ' + t('priority.-1')}><Icon name="low" size={13} /></span>{/if}
    </span>
    <span class="meta">
      {#if item.kind === 'note' && item.end_date && ongoing(item)}
        <span class="badge primary">{t('note.until', { date: fmtDayMonth(item.end_date) })}</span>
      {:else if item.kind === 'note' && item.end_date && showDate}
        <span class="badge {due.level}">{fromNow(date)} · {fmtRange(item.due_date, item.end_date)}</span>
      {:else if showDate && date}
        <span class="badge {due.level}">{fromNow(date)}{#if Math.abs(due.n) > 1} · {fmtDayMonth(date)}{/if}{#if item.due_time} · {item.due_time}{/if}</span>
      {:else if item.due_time}
        <span class="badge">{item.due_time}</span>
      {/if}
      {#if years}<span class="m">{t('birthday.turns', { n: years })}</span>{/if}
      {#if list}<span class="pill c-{list.color}"><Icon name={list.kind === 'project' ? 'project' : 'list'} size={11} />{list.name}</span>{/if}
      {#each labels as l (l.id)}<span class="pill c-{l.color}">#{l.name}</span>{/each}
      {#if item.kind !== 'birthday' && !compact}
        <span class="m"><Icon name={item.category} size={13} />{item.subject || categoryName(item.category)}</span>
      {:else if compact && item.subject}
        <span class="m">{item.subject}</span>
      {/if}
      {#if item.location}<span class="m loc"><Icon name="pin" size={13} />{item.location}</span>{/if}
      {#if assignee || (shared && tickable && !compact)}
        <span class="m" class:mine={item.assignee_id === app.me.user.id}><Icon name="person" size={13} />{assignee ?? t('assign.anyone')}</span>
      {/if}
      {#if item.recur_unit}<span class="m" title={recurName(item.recur_unit, item.recur_every)}><Icon name="repeat" size={13} />{#if item.rotation}<Icon name="people" size={13} />{/if}</span>{/if}
      {#if item.checks.length}
        <span class="m" title={item.kind === 'appointment' ? t('checks.questions') : t('checks.checklist')}>
          <Icon name={item.kind === 'appointment' ? 'question' : 'task'} size={13} />{answered}/{item.checks.length}
        </span>
      {/if}
      {#if item.attachments.length}<span class="m"><Icon name="clip" size={13} />{item.attachments.length}</span>{/if}
      {#if item.comment_count}<span class="m" title={t('comments.n', { n: item.comment_count })}><Icon name="comment" size={13} />{item.comment_count}</span>{/if}
    </span>
  </button>
  {#if movable}
    <button class="later hide-mobile" onclick={() => (app.postpone = item)} aria-label={t('postpone.title')} title={t('postpone.title')}>
      <Icon name="deadline" size={16} /></button>
  {/if}
</div>
</div>

<style>
  .swipe { position: relative; overflow: hidden; border-bottom: 1px solid var(--line); }
  .swipe:last-child { border-bottom: 0; }
  .hint { position: absolute; top: 0; bottom: 0; width: 50%; display: none; align-items: center; padding: 0 22px; color: #fff; }
  .hint.r { left: 0; background: var(--primary); }
  .hint.l { right: 0; justify-content: flex-end; background: var(--danger); }
  .swipe.right .hint.r, .swipe.left .hint.l { display: flex; opacity: 0.55; }
  .swipe.armed .hint { opacity: 1; }
  .row-item { position: relative; display: flex; align-items: flex-start; gap: 10px; padding: 10px 12px; background: var(--surface);
    touch-action: pan-y; transition: transform 0.18s ease; }
  .row-item.dragging { transition: none; }
  .row-item.pending { opacity: 0.7; }
  .handle { cursor: grab; color: var(--muted); padding: 0 2px; margin-top: 1px; touch-action: none; user-select: none; font-size: 1.1rem; line-height: 1.2; }
  .qty { font-size: 0.78rem; font-weight: 600; color: var(--primary); background: var(--primary-soft); border-radius: 6px; padding: 0 6px; white-space: nowrap; }
  .later { flex-shrink: 0; border: 0; background: none; color: var(--muted); cursor: pointer; padding: 3px; border-radius: var(--r-xs); opacity: 0; }
  .row-item:hover .later, .later:focus-visible { opacity: 1; }
  .later:hover { color: var(--ink); background: var(--surface-2); }
  .compact { padding: 8px 12px; }
  .compact .body { gap: 2px; }
  .tick {
    flex-shrink: 0; width: 22px; height: 22px; margin-top: 1px; border-radius: 50%; cursor: pointer;
    border: 1.5px solid var(--line-strong); background: var(--surface); color: var(--primary-ink);
    display: grid; place-items: center; padding: 0; transition: background 0.12s, border-color 0.12s;
  }
  .tick:hover { border-color: var(--primary); }
  .tick.on { background: var(--primary); border-color: var(--primary); }
  .body { flex: 1; min-width: 0; text-align: left; border: 0; background: none; padding: 0; cursor: pointer; display: flex; flex-direction: column; gap: 5px; }
  .title { font-weight: 550; line-height: 1.3; display: flex; align-items: center; gap: 6px; }
  .t { min-width: 0; overflow-wrap: anywhere; }
  .prio { display: inline-flex; }
  .prio.high { color: var(--danger); }
  .prio.low { color: var(--muted); }
  .mark { flex-shrink: 0; width: 22px; height: 22px; margin-top: 1px; border-radius: 50%; display: grid; place-items: center; }
  .mark.note { background: var(--danger-soft); color: var(--danger); }
  .mark.birthday { background: var(--primary-soft); color: var(--primary); }
  .kind { color: var(--muted); }
  .done .t { color: var(--muted); text-decoration: line-through; }
  .meta { display: flex; flex-wrap: wrap; align-items: center; gap: 4px 10px; font-size: 0.8rem; color: var(--muted); }
  .m { display: inline-flex; align-items: center; gap: 4px; min-width: 0; }
  .m.mine { color: var(--primary); font-weight: 600; }
  .loc { max-width: 220px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .badge.warn { background: var(--primary-soft); color: var(--primary); border-color: transparent; }
  .badge.primary { background: var(--primary); color: var(--primary-ink); }
  .body:hover .title { color: var(--primary); }
</style>

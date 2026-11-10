<script>
  // Appointments: upcoming ones with the questions to ask, past ones with answers and medical reports
  import { get } from '../lib/api.js';
  import { app, openEditor, whoName, showError } from '../lib/store.svelte.js';
  import { categoryName, t } from '../lib/i18n.svelte.js';
  import { daysFromToday, fmtFull, fromNow, parse } from '../lib/date.js';
  import { byDue } from '../lib/items.js';
  import { language } from '../lib/i18n.svelte.js';
  import Icon from '../components/Icon.svelte';
  import WhoFilter, { matchesWho } from '../components/WhoFilter.svelte';

  let who = $state('all');
  let subject = $state('');
  let archive = $state([]); // done appointments older than the ones in app.items

  $effect(() => {
    get('/items?done=1').then((r) => (archive = r.filter((i) => i.kind === 'appointment'))).catch(showError);
  });

  const all = $derived.by(() => {
    const map = new Map(archive.map((i) => [i.id, i]));
    for (const i of app.items) if (i.kind === 'appointment') map.set(i.id, i);
    return [...map.values()].filter((i) => matchesWho(i, who) && (!subject || i.subject === subject));
  });
  const isPast = (i) => i.done || (i.due_date && daysFromToday(i.due_date) < 0);
  const upcoming = $derived(all.filter((i) => !isPast(i)).sort(byDue));
  const past = $derived(all.filter(isPast).sort((a, b) => byDue(b, a)));
  const subjects = $derived([...new Set([...archive, ...app.items].filter((i) => i.kind === 'appointment' && i.subject).map((i) => i.subject))].sort());

  const day = (s) => parse(s).getDate();
  const month = (s) => new Intl.DateTimeFormat(language.locale, { month: 'short' }).format(parse(s));
  const answered = (i) => i.checks.filter((c) => c.answer).length;
</script>

<header class="head">
  <div>
    <h1>{t('nav.appointments')}</h1>
    <p class="muted">{t('appointments.subtitle')}</p>
  </div>
  <button class="btn primary" onclick={() => openEditor(null, { kind: 'appointment', subject })}><Icon name="plus" size={16} />{t('item.new_appointment')}</button>
</header>

<WhoFilter bind:value={who} />
{#if subjects.length > 1}
  <div class="chips scroll subj">
    <button class="chip" class:on={!subject} onclick={() => (subject = '')}>{t('common.all')}</button>
    {#each subjects as s (s)}<button class="chip" class:on={subject === s} onclick={() => (subject = s)}>{s}</button>{/each}
  </div>
{/if}

{#snippet card(item, pastCard)}
  <button class="card appt" class:past={pastCard} onclick={() => openEditor(item)}>
    {#if item.due_date}
      <div class="date"><b>{day(item.due_date)}</b><span>{month(item.due_date)}</span></div>
    {:else}
      <div class="date"><b>?</b></div>
    {/if}
    <div class="info">
      <h3>{#if item.priority > 0}<span class="flag" title={t('priority.high')}><Icon name="flag" size={15} /></span>{/if}{item.title}</h3>
      <p class="small muted">
        {#if item.due_date}{fmtFull(item.due_date)}{#if item.due_time} · {item.due_time}{#if item.end_time}–{item.end_time}{/if}{/if}{#if !pastCard} · <b class="soon">{fromNow(item.due_date)}</b>{/if}{:else}{t('appointments.to_book')}{/if}
      </p>
      <div class="meta tiny muted">
        <span><Icon name={item.category} size={13} />{item.subject || categoryName(item.category)}</span>
        {#if item.location}<span class="loc"><Icon name="pin" size={13} />{item.location}</span>{/if}
        {#if whoName(item)}<span><Icon name="person" size={13} />{whoName(item)}</span>{/if}
      </div>
      {#if item.checks.length || item.attachments.length}
        <div class="row wrap tags">
          {#if item.checks.length}
            <span class="badge {pastCard || answered(item) ? '' : 'primary'}"><Icon name="question" size={12} />
              {pastCard || answered(item) ? t('appointments.answered', { n: answered(item), total: item.checks.length }) : t('appointments.questions', { n: item.checks.length })}</span>
          {/if}
          {#if item.attachments.length}<span class="badge"><Icon name="clip" size={12} />{t('appointments.files', { n: item.attachments.length })}</span>{/if}
        </div>
      {/if}
    </div>
  </button>
{/snippet}

<section>
  <h2>{t('appointments.upcoming')}</h2>
  {#if !upcoming.length}<p class="empty small">{t('appointments.none_upcoming')}</p>{/if}
  <div class="list">{#each upcoming as item (item.id)}{@render card(item, false)}{/each}</div>
</section>

{#if past.length}
  <section>
    <h2>{t('appointments.past')}</h2>
    <p class="muted small">{t('appointments.past_note')}</p>
    <div class="list">{#each past as item (item.id)}{@render card(item, true)}{/each}</div>
  </section>
{/if}

<style>
  .head { display: flex; flex-wrap: wrap; align-items: flex-end; justify-content: space-between; gap: 12px; margin-bottom: 16px; }
  .subj { margin-top: 8px; }
  section { margin-top: 20px; max-width: 900px; display: flex; flex-direction: column; gap: 8px; }
  .list { display: flex; flex-direction: column; gap: 10px; }
  .appt { display: flex; gap: 14px; align-items: flex-start; text-align: left; cursor: pointer; padding: 14px; font: inherit; color: inherit; transition: border-color 0.12s; }
  .appt:hover { border-color: var(--primary); }
  .date { flex-shrink: 0; width: 54px; padding: 6px 0; border-radius: var(--r-sm); background: var(--primary-soft); color: var(--primary);
    display: flex; flex-direction: column; align-items: center; line-height: 1.1; }
  .date b { font-size: 1.35rem; font-weight: 700; }
  .date span { font-size: 0.75rem; font-weight: 600; text-transform: uppercase; }
  .past .date { background: var(--surface-2); color: var(--muted); }
  .info { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 4px; }
  .soon { color: var(--primary); font-weight: 600; }
  .meta { display: flex; flex-wrap: wrap; gap: 4px 12px; }
  .meta span { display: inline-flex; align-items: center; gap: 4px; }
  .loc { max-width: 260px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .tags { margin-top: 4px; gap: 6px; }
  .tags .badge { gap: 4px; }
  .flag { display: inline-flex; vertical-align: -2px; margin-right: 5px; color: var(--danger); }
</style>

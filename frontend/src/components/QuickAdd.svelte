<script>
  // Quick add box: plain words become date, time, repetition, labels, list, who and priority,
  // shown as chips while typing so it is clear what was understood.
  import { app, listById, loadLabels, quickContext, showError, toast } from '../lib/store.svelte.js';
  import { create } from '../lib/actions.js';
  import { t } from '../lib/i18n.svelte.js';
  import { fmtDayMonth, fromNow } from '../lib/date.js';
  import { recurName } from '../lib/items.js';
  import { parseQuick, splitQuantity } from '../lib/quickadd.js';
  import Icon from './Icon.svelte';

  // shopping: quantities ("2 kg mele") and `suggestions` (what was bought before) as chips
  let { defaults = {}, placeholder = t('agenda.quick_smart'), onadded = null, shopping = false, suggestions = [] } = $props();
  let text = $state('');
  let help = $state(false);
  let busy = $state(false);
  let input = $state();

  const parsed = $derived.by(() => {
    if (!text.trim()) return null;
    const p = parseQuick(text, quickContext());
    p.quantity = '';
    if (shopping) [p.title, p.quantity] = splitQuantity(p.title);
    return p;
  });
  const matching = $derived.by(() => {
    if (!shopping) return [];
    const q = text.trim().toLowerCase();
    return (q ? suggestions.filter((s) => s.name.toLowerCase().includes(q) && s.name.toLowerCase() !== q) : suggestions).slice(0, q ? 6 : 10);
  });
  const label = (name) => app.labels.find((l) => l.name.toLowerCase() === name.toLowerCase());
  const whoName = (p) => p.assignee_id
    ? (p.assignee_id === app.me.user.id ? t('assign.me') : app.me.members.find((m) => m.id === p.assignee_id)?.name)
    : app.me.people.find((x) => x.id === p.person_id)?.name;
  const chips = $derived.by(() => {
    const p = parsed;
    if (!p) return [];
    const out = [];
    if (p.quantity) out.push({ icon: 'list', text: p.quantity });
    if (p.due_date) out.push({ icon: 'calendar', text: `${fromNow(p.due_date)} · ${fmtDayMonth(p.due_date)}${p.due_time ? ' · ' + p.due_time : ''}` });
    else if (p.due_time) out.push({ icon: 'calendar', text: p.due_time });
    if (p.recur_unit) out.push({ icon: 'repeat', text: recurName(p.recur_unit, p.recur_every) });
    if (p.priority) out.push({ icon: p.priority > 0 ? 'flag' : 'low', text: t('priority.' + p.priority) });
    for (const name of p.labels) out.push({ icon: 'tag', text: name, color: label(name)?.color ?? 'gray', pill: true });
    if (p.list_id) out.push({ icon: listById(p.list_id)?.kind === 'project' ? 'project' : 'list', text: listById(p.list_id)?.name,
                              color: listById(p.list_id)?.color, pill: true });
    if (p.assignee_id || p.person_id) out.push({ icon: 'person', text: whoName(p) });
    return out;
  });

  async function add(e, suggestion = null) {
    e?.preventDefault();
    const p = suggestion ? { title: suggestion.name, quantity: '', labels: [], priority: 0 } : parsed;
    if (!p?.title || busy) return;
    busy = true;
    try {
      const body = {
        kind: 'task', category: 'home', ...defaults,
        title: p.title, due_date: p.due_date ?? null, due_time: p.due_time ?? null, recur_unit: p.recur_unit ?? null,
        recur_every: p.recur_every ?? null, priority: p.priority, labels: p.labels, list_id: p.list_id ?? defaults.list_id ?? null,
      };
      if (p.quantity) body.quantity = p.quantity;
      if (suggestion?.section) body.section = suggestion.section;
      if (p.assignee_id || p.person_id) Object.assign(body, { assignee_id: p.assignee_id, person_id: p.person_id });
      const item = await create(body);
      if (!item.offline && p.labels.some((n) => !label(n))) await loadLabels();
      text = '';
      if (!shopping) toast(t('agenda.added'));
      onadded?.(item);
      input?.focus();
    } catch (err) { showError(err); } finally { busy = false; }
  }
</script>

<form class="quick" onsubmit={add}>
  <div class="row">
    <input class="input grow" bind:this={input} bind:value={text} maxlength="300" {placeholder} aria-label={placeholder}
           autocomplete="off" enterkeyhint="done" />
    <button type="button" class="btn icon ghost" class:on={help} onclick={() => (help = !help)} aria-expanded={help}
            aria-label={t('quick.help_button')} title={t('quick.help_button')}><Icon name="question" size={18} /></button>
    <button class="btn soft" disabled={!parsed?.title || busy}>{t('agenda.add')}</button>
  </div>
  {#if chips.length}
    <div class="understood" aria-live="polite">
      <span class="tiny muted">{t('quick.understood')}:</span>
      <b class="small t">{parsed.title}</b>
      {#each chips as c, i (i)}
        {#if c.pill}<span class="pill c-{c.color}"><Icon name={c.icon} size={12} />{c.text}</span>
        {:else}<span class="badge"><Icon name={c.icon} size={12} />{c.text}</span>{/if}
      {/each}
    </div>
  {/if}
  {#if matching.length}
    <div class="sugg" role="group" aria-label={t('shop.suggestions')}>
      {#each matching as sg (sg.name)}
        <button type="button" class="chip" onclick={() => add(null, sg)}><Icon name="plus" size={12} />{sg.name}</button>
      {/each}
    </div>
  {/if}
  {#if help}<p class="tiny muted help">{shopping ? t('shop.help') : t('quick.help')}</p>{/if}
</form>

<style>
  .quick { display: flex; flex-direction: column; gap: 6px; margin-bottom: 12px; max-width: 720px; }
  .btn.on { color: var(--primary); }
  .understood { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; padding: 0 2px; }
  .understood .badge { display: inline-flex; align-items: center; gap: 4px; }
  .t { overflow-wrap: anywhere; }
  .help { padding: 0 2px; }
  .sugg { display: flex; flex-wrap: wrap; gap: 6px; }
  .sugg .chip { min-height: 28px; font-size: 0.82rem; }
</style>

<script>
  // Create / edit an item: to-do, deadline or appointment, with questions (and answers) and attachments
  import { untrack } from 'svelte';
  import { api, del, get, post, put } from '../lib/api.js';
  import { app, findItem, listById, loadItems, loadLabels, loadMe, memberName, showError, toast, upsert } from '../lib/store.svelte.js';
  import * as actions from '../lib/actions.js';
  import { categoryName, kindName, language, t } from '../lib/i18n.svelte.js';
  import { fmtDayMonth } from '../lib/date.js';
  import {
    SECTIONS, CATEGORIES, DEFAULTS, KINDS, NOTE_PRESETS, NO_YEAR, PRESETS, PRIORITIES, RECURRENCES, REMINDERS, TICKABLE, blankItem,
    fileSize, googleCalendarLink, mapsLink, recurKey, recurName, reminderName,
  } from '../lib/items.js';
  import Sheet from './Sheet.svelte';
  import Icon from './Icon.svelte';
  import { appIcons } from '$famkit/apps.js';

  let { item = null, template = {}, onclose } = $props();

  // Working copy (strings for the inputs). The sheet is re-created for each item (keyed in App),
  // so reading the props once is intended.
  const start = untrack(() => $state.snapshot(item) ?? blankItem(template));
  // A birthday without a known year is stored in NO_YEAR: shown here with this year's date
  let noYear = $state(start.kind === 'birthday' && +(start.due_date ?? '').slice(0, 4) === NO_YEAR);
  let form = $state({
    ...start, due_date: start.due_date ?? '', due_time: start.due_time ?? '', end_time: start.end_time ?? '',
    end_date: start.end_date ?? '', priority: start.priority ?? 0, person_id: start.person_id ?? null,
    checks: (start.checks ?? []).map((c) => ({ ...c })), labels: [...(start.labels ?? [])], list_id: start.list_id ?? null,
    recur_from: start.recur_from ?? 'due', remind_time: start.remind_time ?? '',
    quantity: start.quantity ?? '', section: start.section ?? null,
    rotation: start.rotation ? start.rotation.split(',') : [],
  });
  if (noYear) form.due_date = new Date().getFullYear() + form.due_date.slice(4);
  let id = $state(start.id ?? null);
  let attachments = $state(start.attachments ?? []);
  // paTrack (weHub mode): a deadline's document lives in the family archive
  let extUrl = $state(start.ext_url ?? null);
  let patrackInput = $state();
  const usesPatrack = $derived((app.me.hub?.apps ?? []).some((a) => a.id === 'patrack'));
  let saving = $state(false);
  let uploading = $state(false);
  let newCheck = $state('');
  let fileInput = $state();
  let cameraInput = $state();
  const isNew = !start.id;
  let titleInput = $state();
  $effect(() => { if (isNew) titleInput?.focus(); });

  // Comments and history of a saved item
  let comments = $state([]);
  let history = $state([]);
  let newComment = $state('');
  let sending = $state(false);
  async function loadExtra() {
    if (!id) return;
    try { const full = await get(`/items/${id}`); comments = full.comments; history = full.history; } catch { /* shown without them */ }
  }
  if (!isNew) loadExtra();
  async function sendComment(e) {
    e.preventDefault();
    const text = newComment.trim();
    if (!text || sending) return;
    sending = true;
    try {
      comments.push(await post(`/items/${id}/comments`, { text }));
      newComment = '';
      const it = app.items.find((x) => x.id === id);
      if (it) it.comment_count = comments.length;
    } catch (err) { showError(err); } finally { sending = false; }
  }
  async function deleteComment(c) {
    if (!confirm(t('comments.confirm_delete'))) return;
    try {
      await del(`/comments/${c.id}`);
      comments = comments.filter((x) => x.id !== c.id);
      const it = app.items.find((x) => x.id === id);
      if (it) it.comment_count = comments.length;
    } catch (err) { showError(err); }
  }
  const stamp = (s) => new Intl.DateTimeFormat(language.locale, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
    .format(new Date(s.replace(' ', 'T') + 'Z'));

  // Labels: ids of existing ones, names of those to create on save
  let newLabel = $state('');
  let addingLabel = $state(false);
  const hasLabel = (id) => form.labels.includes(id);
  const toggleLabel = (id) => (form.labels = hasLabel(id) ? form.labels.filter((x) => x !== id) : [...form.labels, id]);
  function addLabel(e) {
    e?.preventDefault();
    const name = newLabel.trim().replace(/^[#*]/, '');
    if (!name) { addingLabel = false; return; }
    const existing = app.labels.find((l) => l.name.toLowerCase() === name.toLowerCase());
    if (existing) { if (!hasLabel(existing.id)) form.labels.push(existing.id); }
    else if (!form.labels.some((x) => typeof x === 'string' && x.toLowerCase() === name.toLowerCase())) form.labels.push(name);
    newLabel = '';
    addingLabel = false;
  }
  const lists = $derived(app.lists.filter((l) => !l.archived || l.id === form.list_id));
  // An entry of a checklist (the shopping list): quantity and aisle
  const shoppingItem = $derived(listById(form.list_id)?.kind === 'checklist');
  // Chores in turn: whoever is ticked takes a turn, in the order they were ticked
  const turnKey = (assignee, person) => (person ? 'p' + person : 'u' + assignee);
  function toggleTurn(k) {
    form.rotation = form.rotation.includes(k) ? form.rotation.filter((x) => x !== k) : [...form.rotation, k];
    // The first one in turn is who does it now, unless the current one is already in turn
    const now = form.person_id ? 'p' + form.person_id : form.assignee_id ? 'u' + form.assignee_id : null;
    if (form.rotation.length && !form.rotation.includes(now)) {
      const first = form.rotation[0];
      setWho(first[0] === 'u' ? Number(first.slice(1)) : null, first[0] === 'p' ? Number(first.slice(1)) : null);
    }
  }

  const members = $derived(app.me?.members ?? []);
  const people = $derived(app.me?.people ?? []);
  const appointment = $derived(form.kind === 'appointment');
  const note = $derived(form.kind === 'note');
  const birthday = $derived(form.kind === 'birthday');
  const tickable = $derived(TICKABLE(form));
  const subjects = $derived([...new Set(app.items.map((i) => i.subject).filter(Boolean))].sort());
  const gcal = $derived(googleCalendarLink(form));

  function setKind(k) {
    // Switching type on a new item applies that type's defaults (category, reminder)
    if (isNew && !form.title) Object.assign(form, DEFAULTS[k]);
    if (isNew && !form.due_date) form.due_date = blankItem({ kind: k }).due_date;
    form.kind = k;
  }
  function applyNotePreset(p) {
    form.title = t('note_preset.' + p.key);
    form.category = p.category;
  }
  function setWho(assignee_id, person_id) {
    form.assignee_id = assignee_id;
    form.person_id = person_id;
  }
  async function addPerson() {
    const name = prompt(t('assign.new_person'))?.trim();
    if (!name) return;
    try {
      const p = await post('/family/people', { name });
      await loadMe();
      setWho(null, p.id);
    } catch (e) { showError(e); }
  }
  function applyPreset(p) {
    Object.assign(form, {
      kind: 'deadline', title: t('preset.' + p.key), category: p.category, recur_unit: p.recur_unit,
      recur_every: p.recur_every, remind_days: p.remind_days,
    });
  }
  function setRecur(v) {
    const [unit, every] = v ? v.split(':') : [null, null];
    form.recur_unit = unit;
    form.recur_every = every ? Number(every) : null;
  }

  function addCheck() {
    const text = newCheck.trim();
    if (!text) return;
    form.checks.push({ text, answer: '', done: false });
    newCheck = '';
  }
  const removeCheck = (i) => form.checks.splice(i, 1);

  function payload() {
    if (newCheck.trim()) addCheck(); // a question typed but not added yet is kept
    if (newLabel.trim()) addLabel(); // same for a label
    const due_date = birthday && noYear && form.due_date ? NO_YEAR + form.due_date.slice(4) : form.due_date || null;
    return {
      kind: form.kind, title: form.title, notes: birthday ? '' : form.notes, category: form.category,
      subject: birthday ? '' : form.subject, due_date, due_time: tickable ? form.due_time || null : null,
      end_time: form.end_time || null, end_date: note ? form.end_date || null : null,
      location: appointment ? form.location : '', assignee_id: form.assignee_id, person_id: form.person_id,
      priority: tickable ? form.priority : 0,
      recur_unit: form.due_date && tickable ? form.recur_unit : null, recur_every: form.due_date && tickable ? form.recur_every : null,
      remind_days: form.remind_days, remind_time: form.remind_days !== null ? form.remind_time || null : null,
      recur_from: form.recur_unit ? form.recur_from : 'due', list_id: form.list_id || null,
      labels: [...form.labels], quantity: shoppingItem ? form.quantity : '', section: shoppingItem ? form.section : null,
      rotation: form.recur_unit && form.rotation.length > 1 ? [...form.rotation] : null,
      checks: tickable ? form.checks.map(({ text, answer, done }) => ({ text, answer, done })) : [],
    };
  }

  async function persist() {
    const data = payload();
    const saved = id ? await put(`/items/${id}`, data) : await post('/items', data);
    if (data.labels.some((x) => typeof x === 'string')) await loadLabels();
    form.labels = [...saved.labels];
    id = saved.id;
    form.checks = saved.checks.map((c) => ({ ...c }));
    attachments = saved.attachments;
    upsert(saved);
    return saved;
  }

  const canSave = $derived(!!form.title.trim() && (tickable || !!form.due_date));
  async function save() {
    if (!canSave) return;
    saving = true;
    try { await persist(); toast(t('common.saved')); onclose(); } catch (e) { showError(e); } finally { saving = false; }
  }

  async function complete() {
    saving = true;
    try {
      const saved = await persist();
      onclose();
      await actions.complete(saved);
    } catch (e) { showError(e); } finally { saving = false; }
  }
  async function reopen() {
    await actions.reopen(findItem(id) ?? { ...start, id });
    form.done = false;
  }

  // To the trash, with "Undo" (no confirmation needed)
  async function remove() {
    onclose();
    await actions.remove(findItem(id) ?? { ...start, id });
  }

  async function upload(e) {
    const files = [...(e.currentTarget.files ?? [])];
    e.currentTarget.value = '';
    if (!files.length) return;
    if (!form.title.trim()) { toast(t('item.title_first'), 'error'); return; }
    uploading = true;
    try {
      if (!id) await persist(); // the file needs a saved item to belong to
      for (const f of files) {
        const fd = new FormData();
        fd.append('file', f);
        const saved = await api(`/items/${id}/attachments`, { method: 'POST', form: fd });
        attachments = saved.attachments;
        upsert(saved);
      }
      toast(t('files.uploaded'));
    } catch (err) { showError(err); } finally { uploading = false; }
  }
  async function toPatrack(e) {
    const f = e.currentTarget.files?.[0];
    e.currentTarget.value = '';
    if (!f) return;
    if (!form.title.trim() || !form.due_date) { toast(t('patrack.needs_date'), 'error'); return; }
    uploading = true;
    try {
      await persist(); // the deadline as it is now (date, person, reminder) goes with the document
      const fd = new FormData();
      fd.append('file', f);
      const saved = await api(`/items/${id}/to-patrack`, { method: 'POST', form: fd });
      extUrl = saved.ext_url;
      upsert(saved);
      toast(t('patrack.sent'));
    } catch (err) { showError(err); } finally { uploading = false; }
  }
  async function removeFile(a) {
    if (!confirm(t('files.confirm_delete', { name: a.name }))) return;
    try { const saved = await del(`/attachments/${a.id}`); attachments = saved.attachments; upsert(saved); } catch (e) { showError(e); }
  }
</script>

<Sheet title={isNew ? t('item.new_' + form.kind) : kindName(form.kind)} {onclose} wide>
  <div class="stack">
    {#if isNew}
      <div class="seg kinds" role="tablist">
        {#each KINDS as k (k)}
          <button class:on={form.kind === k} onclick={() => setKind(k)}><Icon name={k} size={15} />{kindName(k)}</button>
        {/each}
      </div>
    {/if}

    {#if isNew && form.kind === 'deadline' && !form.title}
      <div class="field">
        <span class="label">{t('preset.title')}</span>
        <div class="chips scroll">
          {#each PRESETS as p (p.key)}
            <button class="chip" onclick={() => applyPreset(p)}>{t('preset.' + p.key)}</button>
          {/each}
        </div>
      </div>
    {/if}

    {#if isNew && note && !form.title}
      <div class="field">
        <span class="label">{t('note_preset.title')}</span>
        <div class="chips scroll">
          {#each NOTE_PRESETS as p (p.key)}
            <button class="chip" onclick={() => applyNotePreset(p)}>{t('note_preset.' + p.key)}</button>
          {/each}
        </div>
      </div>
    {/if}

    <label class="field"><span class="label">{birthday ? t('item.title_birthday') : t('item.title')}</span>
      <input class="input big" bind:this={titleInput} bind:value={form.title} maxlength="200"
             placeholder={t('item.title_example_' + form.kind)} onkeydown={(e) => e.key === 'Enter' && save()} /></label>

    <div class="grid2">
      <label class="field"><span class="label">{t('item.date_' + form.kind)}</span>
        <input class="input" type="date" bind:value={form.due_date} /></label>
      {#if birthday}
        <label class="check-line"><input type="checkbox" class="cb" bind:checked={noYear} />{t('item.no_year')}</label>
      {:else if note}
        <label class="field"><span class="label">{t('item.end_date')} <span class="opt">({t('common.optional')})</span></span>
          <input class="input" type="date" bind:value={form.end_date} min={form.due_date} /></label>
      {:else if form.due_date}
        <div class="row times">
          <label class="field grow"><span class="label">{t('item.time')}</span>
            <input class="input" type="time" bind:value={form.due_time} /></label>
          {#if appointment && form.due_time}
            <label class="field grow"><span class="label">{t('item.end_time')}</span>
              <input class="input" type="time" bind:value={form.end_time} /></label>
          {/if}
        </div>
      {/if}
    </div>

    {#if appointment}
      <label class="field"><span class="label">{t('item.location')}</span>
        <div class="row">
          <input class="input grow" bind:value={form.location} maxlength="200" placeholder={t('item.location_example')} />
          {#if form.location}<a class="btn icon soft" href={mapsLink(form.location)} target="_blank" rel="noopener" aria-label={t('item.open_map')}><Icon name="pin" /></a>{/if}
        </div>
      </label>
    {/if}

    {#if note}<p class="tiny muted hint">{t('item.note_hint')}</p>{/if}

    {#if !birthday}
      <div class="field">
        <span class="label">{t('assign.who')}</span>
        <div class="chips">
          <button class="chip" class:on={!form.assignee_id && !form.person_id} onclick={() => setWho(null, null)}>{t('assign.anyone')}</button>
          {#each members as m (m.id)}
            <button class="chip" class:on={form.assignee_id === m.id} onclick={() => setWho(m.id, null)}>{m.id === app.me.user.id ? t('assign.me') : m.name}</button>
          {/each}
          {#each people as p (p.id)}
            <button class="chip" class:on={form.person_id === p.id} onclick={() => setWho(null, p.id)}>{p.name}</button>
          {/each}
          <button class="chip add" onclick={addPerson}><Icon name="plus" size={13} />{t('assign.add_person')}</button>
        </div>
      </div>
    {/if}

    {#if tickable}
      <div class="field">
        <span class="label">{t('priority.label')}</span>
        <div class="seg prio">
          {#each PRIORITIES as p (p)}
            <button class:on={form.priority === p} class:high={p > 0} onclick={() => (form.priority = p)}>
              {#if p > 0}<Icon name="flag" size={14} />{:else if p < 0}<Icon name="low" size={14} />{/if}{t('priority.' + p)}
            </button>
          {/each}
        </div>
      </div>
    {/if}

    {#if !birthday}
      <div class="field">
        <span class="label">{t('item.category')}</span>
        <div class="chips">
          {#each CATEGORIES as c (c)}
            <button class="chip" class:on={form.category === c} aria-pressed={form.category === c} onclick={() => (form.category = c)}>
              <Icon name={c} size={14} />{categoryName(c)}
            </button>
          {/each}
        </div>
      </div>

      <label class="field"><span class="label">{t('item.subject')}</span>
        <input class="input" bind:value={form.subject} maxlength="80" list="subjects" placeholder={t('item.subject_example')} />
        <datalist id="subjects">{#each subjects as s (s)}<option value={s}></option>{/each}</datalist>
      </label>
    {/if}

    {#if lists.length && !birthday}
      <label class="field"><span class="label">{t('item.list')}</span>
        <select class="input" value={form.list_id ?? ''} onchange={(e) => (form.list_id = Number(e.currentTarget.value) || null)}>
          <option value="">{t('item.no_list')}</option>
          {#each lists as l (l.id)}<option value={l.id}>{l.name}{l.template ? ` (${t('templates.badge')})` : ''}</option>{/each}
        </select></label>
    {/if}

    {#if shoppingItem}
      <div class="grid2">
        <label class="field"><span class="label">{t('shop.quantity')}</span>
          <input class="input" bind:value={form.quantity} maxlength="40" placeholder={t('shop.quantity_example')} /></label>
        <label class="field"><span class="label">{t('shop.section')}</span>
          <select class="input" value={form.section ?? ''} onchange={(e) => (form.section = e.currentTarget.value || null)}>
            <option value="">{t('shop.section_auto')}</option>
            {#each SECTIONS as sec (sec)}<option value={sec}>{t('section.' + sec)}</option>{/each}
          </select></label>
      </div>
    {/if}

    {#if !birthday}
      <div class="field">
        <span class="label">{t('item.labels')}</span>
        <div class="chips">
          {#each app.labels as l (l.id)}
            <button class="chip c-{l.color}" class:on={hasLabel(l.id)} aria-pressed={hasLabel(l.id)} onclick={() => toggleLabel(l.id)}>
              <span class="dot"></span>{l.name}</button>
          {/each}
          {#each form.labels.filter((x) => typeof x === 'string') as name (name)}
            <button class="chip on" onclick={() => (form.labels = form.labels.filter((x) => x !== name))}><span class="dot"></span>{name}</button>
          {/each}
          {#if addingLabel}
            <form class="new-label" onsubmit={addLabel}>
              <!-- svelte-ignore a11y_autofocus -->
              <input class="input sm" bind:value={newLabel} maxlength="40" placeholder={t('labels.placeholder')} autofocus
                     onblur={() => addLabel()} aria-label={t('labels.placeholder')} />
            </form>
          {:else}
            <button class="chip add" onclick={() => (addingLabel = true)}><Icon name="plus" size={13} />{t('item.add_label')}</button>
          {/if}
        </div>
      </div>
    {/if}

    {#if form.due_date && !tickable}
      <div class="grid2">
        <label class="field"><span class="label">{t('item.reminder')}</span>
          <select class="input" value={form.remind_days ?? ''} onchange={(e) => (form.remind_days = e.currentTarget.value === '' ? null : Number(e.currentTarget.value))}>
            {#each REMINDERS as d (d)}<option value={d ?? ''}>{reminderName(d)}</option>{/each}
          </select></label>
        {#if form.remind_days !== null}{@render remindAt()}{/if}
      </div>
    {:else if form.due_date}
      <div class="grid2">
        <label class="field"><span class="label">{t('item.repeat')}</span>
          <select class="input" value={recurKey(form.recur_unit, form.recur_every)} onchange={(e) => setRecur(e.currentTarget.value)}>
            {#each RECURRENCES as [u, n] (recurKey(u, n))}<option value={recurKey(u, n)}>{recurName(u, n)}</option>{/each}
            {#if form.recur_unit && !RECURRENCES.some(([u, n]) => u === form.recur_unit && n === form.recur_every)}
              <option value={recurKey(form.recur_unit, form.recur_every)}>{recurName(form.recur_unit, form.recur_every)}</option>
            {/if}
          </select></label>
        <label class="field"><span class="label">{t('item.reminder')}</span>
          <select class="input" value={form.remind_days ?? ''} onchange={(e) => (form.remind_days = e.currentTarget.value === '' ? null : Number(e.currentTarget.value))}>
            {#each REMINDERS as d (d)}<option value={d ?? ''}>{reminderName(d)}</option>{/each}
          </select></label>
      </div>
      {#if form.remind_days !== null}<div class="grid2">{@render remindAt()}</div>{/if}
      {#if form.recur_unit && (members.length + people.length) > 1}
        <div class="field">
          <span class="label">{t('turns.label')}</span>
          <div class="chips">
            {#each members as m (m.id)}
              {@const k = turnKey(m.id, null)}
              <button class="chip" class:on={form.rotation.includes(k)} onclick={() => toggleTurn(k)}>
                {#if form.rotation.includes(k)}<span class="nth">{form.rotation.indexOf(k) + 1}</span>{/if}{m.id === app.me.user.id ? t('assign.me') : m.name}</button>
            {/each}
            {#each people as p (p.id)}
              {@const k = turnKey(null, p.id)}
              <button class="chip" class:on={form.rotation.includes(k)} onclick={() => toggleTurn(k)}>
                {#if form.rotation.includes(k)}<span class="nth">{form.rotation.indexOf(k) + 1}</span>{/if}{p.name}</button>
            {/each}
          </div>
          <span class="tiny muted">{form.rotation.length > 1 ? t('turns.hint_on') : t('turns.hint')}</span>
        </div>
      {/if}
      {#if form.recur_unit}
        <label class="check-line"><input type="checkbox" class="cb" checked={form.recur_from === 'done'}
               onchange={(e) => (form.recur_from = e.currentTarget.checked ? 'done' : 'due')} />{t('item.repeat_from_done')}</label>
        <p class="tiny muted hint">{form.recur_from === 'done' ? t('item.repeat_from_done_hint') : t('item.repeat_hint')}</p>
      {/if}
    {/if}

    {#snippet remindAt()}
      <label class="field"><span class="label">{t('item.remind_at')} <span class="opt">({t('common.optional')})</span></span>
        <input class="input" type="time" bind:value={form.remind_time}
               title={form.remind_days === 0 && form.due_time ? t('item.remind_hour_before') : t('item.remind_morning', { h: (app.me?.reminder_hour ?? 8) + ':00' })} />
        {#if !form.remind_time}<span class="tiny muted">{form.remind_days === 0 && form.due_time ? t('item.remind_hour_before') : t('item.remind_morning', { h: (app.me?.reminder_hour ?? 8) + ':00' })}</span>{/if}
      </label>
    {/snippet}

    <!-- Questions to ask (appointments) or checklist -->
    {#if tickable}
    <section class="block">
      <h3><Icon name={appointment ? 'question' : 'task'} size={16} />{appointment ? t('checks.questions') : t('checks.checklist')}</h3>
      {#if appointment && form.checks.length}<p class="tiny muted">{t('checks.answers_hint')}</p>{/if}
      <ul class="checks">
        {#each form.checks as c, i (i)}
          <li class:qa={appointment}>
            {#if appointment}
              <div class="row">
                <span class="qn">{i + 1}.</span>
                <input class="input plain grow q" bind:value={c.text} maxlength="1000" aria-label={t('checks.question_n', { n: i + 1 })} />
                <button class="btn icon sm ghost" onclick={() => removeCheck(i)} aria-label={t('common.remove')}>✕</button>
              </div>
              <textarea class="input answer" rows="2" bind:value={c.answer} placeholder={t('checks.answer_placeholder')}></textarea>
            {:else}
              <div class="row">
                <input type="checkbox" class="cb" bind:checked={c.done} aria-label={c.text} />
                <input class="input plain grow" class:struck={c.done} bind:value={c.text} maxlength="1000" />
                <button class="btn icon sm ghost" onclick={() => removeCheck(i)} aria-label={t('common.remove')}>✕</button>
              </div>
            {/if}
          </li>
        {/each}
      </ul>
      <form class="row" onsubmit={(e) => { e.preventDefault(); addCheck(); }}>
        <input class="input grow" bind:value={newCheck} maxlength="1000" placeholder={appointment ? t('checks.add_question') : t('checks.add_entry')} />
        <button class="btn soft" disabled={!newCheck.trim()} aria-label={t('checks.add')}><Icon name="plus" /></button>
      </form>
    </section>
    {/if}

    {#if !birthday}
    <label class="field"><span class="label">{appointment ? t('item.notes_appointment') : t('item.notes')}</span>
      <textarea class="input" rows="3" bind:value={form.notes} maxlength="10000" placeholder={appointment ? t('item.notes_appointment_example') : ''}></textarea></label>

    <!-- Attachments: medical reports, receipts, photos -->
    <section class="block">
      <h3><Icon name="clip" size={16} />{appointment ? t('files.reports') : t('files.title')}</h3>
      {#if attachments.length}
        <ul class="files">
          {#each attachments as a (a.id)}
            <li>
              <a class="file" href="/api/attachments/{a.id}" target="_blank" rel="noopener">
                {#if a.mime.startsWith('image/') && a.mime !== 'image/heic' && a.mime !== 'image/heif'}
                  <img src="/api/attachments/{a.id}" alt="" loading="lazy" />
                {:else}<span class="ficon"><Icon name="file" size={20} /></span>{/if}
                <span class="fname">{a.name}<span class="tiny muted">{fileSize(a.size)}</span></span>
              </a>
              <button class="btn icon sm ghost" onclick={() => removeFile(a)} aria-label={t('files.delete', { name: a.name })}><Icon name="trash" size={16} /></button>
            </li>
          {/each}
        </ul>
      {/if}
      <div class="row wrap">
        <input bind:this={fileInput} class="sr-only" type="file" multiple onchange={upload}
               accept=".pdf,.jpg,.jpeg,.png,.webp,.gif,.heic,.heif,.txt,.doc,.docx,.odt,.xls,.xlsx,.csv,.zip,.dcm" />
        <input bind:this={cameraInput} class="sr-only" type="file" accept="image/*" capture="environment" onchange={upload} />
        <button class="btn soft sm" disabled={uploading} onclick={() => fileInput.click()}><Icon name="upload" size={16} />{uploading ? t('common.wait') : t('files.add')}</button>
        <button class="btn soft sm hide-desktop" disabled={uploading} onclick={() => cameraInput.click()}><Icon name="camera" size={16} />{t('files.photo')}</button>
        <span class="tiny muted">{t('files.limits')}</span>
      </div>
      {#if form.kind === 'deadline' && (extUrl || usesPatrack)}
        <div class="patrack">
          {#if extUrl}
            <a class="btn soft sm" href={extUrl} target="_blank" rel="noopener"><img src={appIcons.patrack} alt="" width="18" height="18" />{t('patrack.open')}</a>
            <span class="tiny muted">{t('patrack.kept_in_step')}</span>
          {:else}
            <input bind:this={patrackInput} class="sr-only" type="file" onchange={toPatrack}
                   accept=".pdf,.jpg,.jpeg,.png,.webp,.gif,.heic,.heif,.txt,.doc,.docx,.odt,.xls,.xlsx,.csv,.zip,.dcm" />
            <button class="btn soft sm" disabled={uploading || !app.online} onclick={() => patrackInput.click()}>
              <img src={appIcons.patrack} alt="" width="18" height="18" />{t('patrack.archive')}</button>
            <span class="tiny muted">{t('patrack.archive_note')}</span>
          {/if}
        </div>
      {/if}
    </section>
    {/if}

    {#if id}
      <section class="block">
        <h3><Icon name="comment" size={16} />{t('comments.title')}</h3>
        {#if comments.length}
          <ul class="comments">
            {#each comments as c (c.id)}
              <li>
                <div class="spread"><b class="small">{memberName(c.user_id) ?? t('history.someone')}</b>
                  <span class="tiny muted">{stamp(c.created_at)}
                    {#if c.user_id === app.me.user.id}<button class="btn icon sm ghost" onclick={() => deleteComment(c)} aria-label={t('comments.delete')}>✕</button>{/if}
                  </span></div>
                <p class="small ctext">{c.text}</p>
              </li>
            {/each}
          </ul>
        {/if}
        <form class="row" onsubmit={sendComment}>
          <input class="input grow" bind:value={newComment} maxlength="5000" placeholder={t('comments.placeholder')} aria-label={t('comments.placeholder')} />
          <button class="btn soft" disabled={!newComment.trim() || sending}>{t('comments.send')}</button>
        </form>
        {#if history.length}
          <details class="tiny muted">
            <summary><Icon name="history" size={13} />{t('history.title')}</summary>
            <ul class="history">
              {#each history as h, i (i)}
                <li>{t('history.' + h.action, { name: memberName(h.user_id) ?? t('history.someone') })} · {stamp(h.created_at)}</li>
              {/each}
            </ul>
          </details>
        {/if}
      </section>
    {/if}

    {#if gcal}
      <a class="gcal small" href={gcal} target="_blank" rel="noopener"><Icon name="google" size={16} />{t('gcal.add_one')}<Icon name="external" size={13} /></a>
    {/if}
  </div>

  {#snippet footer()}
    {#if id}<button class="btn danger icon" onclick={remove} aria-label={t('common.delete')}><Icon name="trash" /></button>{/if}
    {#if id && form.done}
      <button class="btn" onclick={reopen}><Icon name="undo" size={16} />{t('item.reopen')}</button>
    {:else if id && tickable}
      <button class="btn soft" disabled={saving || !form.title.trim()} onclick={complete}><Icon name="check" size={16} />{t('item.complete')}</button>
    {/if}
    <button class="btn primary grow" disabled={saving || !canSave} onclick={save}>{saving ? t('common.saving') : t('common.save')}</button>
  {/snippet}
</Sheet>

<style>
  .patrack { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-top: 10px; padding-top: 10px; border-top: 1px solid var(--line); }
  .patrack img { border-radius: 4px; }
  .seg button { display: inline-flex; align-items: center; justify-content: center; gap: 6px; }
  .kinds { flex-wrap: wrap; }
  .kinds button { flex: 1 1 auto; }
  .seg.prio button.high.on { color: var(--danger); }
  .chip.add { color: var(--primary); border-style: dashed; }
  .opt { text-transform: none; letter-spacing: 0; font-weight: 400; }
  .check-line { display: flex; align-items: center; gap: 8px; font-size: 0.9rem; align-self: end; min-height: 40px; cursor: pointer; }
  .big { font-size: 1.05rem; font-weight: 550; }
  .grid2 { display: grid; gap: 12px; grid-template-columns: 1fr; }
  @media (min-width: 560px) { .grid2 { grid-template-columns: 1fr 1fr; } }
  .times { align-items: flex-end; }
  .hint { margin-top: -6px; }
  .block { display: flex; flex-direction: column; gap: 8px; padding: 14px; border-radius: var(--r-md); background: var(--surface-2); }
  .block h3 { display: flex; align-items: center; gap: 8px; font-size: 0.92rem; }
  .checks { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
  .checks li.qa { display: flex; flex-direction: column; gap: 4px; padding: 8px; border-radius: var(--r-sm); background: var(--surface); border: 1px solid var(--line); }
  .qn { color: var(--muted); font-weight: 600; font-size: 0.85rem; min-width: 18px; }
  .plain { border-color: transparent; background: transparent; min-height: 34px; padding: 4px 8px; }
  .plain:hover { border-color: var(--line); }
  .plain:focus { background: var(--surface); }
  .q { font-weight: 550; }
  .answer { min-height: 54px; font-size: 0.9rem; }
  .struck { text-decoration: line-through; color: var(--muted); }
  .cb { width: 18px; height: 18px; accent-color: var(--primary); flex-shrink: 0; margin: 0 4px; }
  .files { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
  .files li { display: flex; align-items: center; gap: 6px; }
  .file { flex: 1; min-width: 0; display: flex; align-items: center; gap: 10px; padding: 6px 8px; border-radius: var(--r-sm);
    background: var(--surface); border: 1px solid var(--line); text-decoration: none; color: var(--ink); }
  .file:hover { border-color: var(--primary); }
  .file img, .ficon { width: 40px; height: 40px; border-radius: var(--r-xs); object-fit: cover; flex-shrink: 0; }
  .ficon { display: grid; place-items: center; background: var(--primary-soft); color: var(--primary); }
  .fname { min-width: 0; display: flex; flex-direction: column; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 500; font-size: 0.9rem; }
  .comments { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 8px; }
  .comments li { padding: 8px 10px; border-radius: var(--r-sm); background: var(--surface); border: 1px solid var(--line); }
  .comments .spread { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
  .comments .spread span { display: inline-flex; align-items: center; gap: 2px; }
  .ctext { white-space: pre-wrap; overflow-wrap: anywhere; }
  details summary { cursor: pointer; display: inline-flex; align-items: center; gap: 6px; }
  .history { margin: 6px 0 0; padding-left: 18px; display: flex; flex-direction: column; gap: 2px; }
  .new-label { display: inline-flex; }
  .nth { font-size: 0.7rem; font-weight: 700; background: var(--primary-ink); color: var(--primary); border-radius: 50%;
    width: 16px; height: 16px; display: inline-grid; place-items: center; }
  .input.sm { min-height: 30px; padding: 3px 10px; width: 150px; font-size: 0.875rem; }
  .gcal { display: inline-flex; align-items: center; gap: 6px; align-self: flex-start; font-weight: 500; text-decoration: none; }
  .gcal:hover { text-decoration: underline; }
</style>

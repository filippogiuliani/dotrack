<script>
  // Lists (shopping, packing…) and projects, one level only; templates; the family's labels.
  // Without `id`: all lists. With `id`: that list, with its own quick add.
  import { del, get, post, put } from '../lib/api.js';
  import { app, itemsOfList, loadItems, loadLabels, loadLists, openEditor, showError, toast } from '../lib/store.svelte.js';
  import { t } from '../lib/i18n.svelte.js';
  import { SECTIONS, byDue } from '../lib/items.js';
  import { sortable } from '../lib/sortable.js';
  import ItemRow from '../components/ItemRow.svelte';
  import QuickAdd from '../components/QuickAdd.svelte';
  import Icon from '../components/Icon.svelte';

  let { id = '' } = $props();
  const COLORS = ['blue', 'green', 'red', 'orange', 'yellow', 'purple', 'pink', 'teal', 'gray'];
  const SUGGESTIONS = [
    { key: 'shopping', kind: 'checklist', color: 'green', sections: true }, { key: 'packing', kind: 'checklist', color: 'blue' },
    { key: 'gifts', kind: 'checklist', color: 'pink' }, { key: 'works', kind: 'project', color: 'orange' },
  ];

  const current = $derived(id ? app.lists.find((l) => l.id === Number(id)) ?? null : null);
  const openOf = (l) => itemsOfList(l.id).filter((i) => !i.done);
  const active = $derived(app.lists.filter((l) => !l.archived && !l.template));
  const templates = $derived(app.lists.filter((l) => l.template));
  const archived = $derived(app.lists.filter((l) => l.archived && !l.template));

  // ---------- New list / edit
  let creating = $state(false);
  let editing = $state(false);
  let draft = $state({ name: '', kind: 'checklist', color: 'blue', sections: false });
  function startCreate(s = null) {
    draft = s ? { name: t('lists.suggest_' + s.key), kind: s.kind, color: s.color, sections: !!s.sections }
              : { name: '', kind: 'checklist', color: 'blue', sections: false };
    creating = true;
  }
  async function create(e) {
    e?.preventDefault();
    if (!draft.name.trim()) return;
    try {
      const l = await post('/lists', draft);
      await loadLists();
      creating = false;
      toast(t('lists.created'));
      location.hash = `#/lists/${l.id}`;
    } catch (err) { showError(err); }
  }
  function startEdit() {
    draft = { name: current.name, kind: current.kind, color: current.color, sections: current.sections };
    editing = true;
  }
  async function saveEdit(e) {
    e?.preventDefault();
    try { await put(`/lists/${current.id}`, draft); await loadLists(); editing = false; toast(t('common.saved')); } catch (err) { showError(err); }
  }
  async function setArchived(on) {
    try { await put(`/lists/${current.id}`, { archived: on }); await loadLists(); editing = false; } catch (err) { showError(err); }
  }
  async function removeList() {
    if (!confirm(t('lists.confirm_delete', { name: current.name, n: itemsOfList(current.id).length }))) return;
    try {
      await del(`/lists/${current.id}`);
      await loadItems();
      toast(t('lists.deleted'));
      location.hash = '#/lists';
    } catch (err) { showError(err); }
  }
  /** Duplicate, save as template, or start a list from a template */
  async function copy(src, template) {
    const suggested = template ? t('templates.name', { name: src.name }) : src.template ? src.name.replace(/\s*\(.*\)$/, '') : t('templates.copy_name', { name: src.name });
    const name = prompt(t('lists.name'), suggested)?.trim();
    if (!name) return;
    try {
      const l = await post(`/lists/${src.id}/copy`, { name, template });
      await loadItems();
      toast(template ? t('templates.saved') : t('lists.created'));
      location.hash = `#/lists/${l.id}`;
    } catch (err) { showError(err); }
  }

  // ---------- One list
  const checklist = $derived(current?.kind === 'checklist');
  let order = $state([]); // ids of the open entries, in the order shown (changes while dragging)
  let dragging = $state(false);
  $effect(() => {
    if (!current || dragging) return;
    const items = openOf(current);
    order = (checklist ? items.sort((a, b) => a.position - b.position || a.id - b.id) : items.sort(byDue)).map((i) => i.id);
  });
  const byId = $derived(new Map(itemsOfList(current?.id).map((i) => [i.id, i])));
  const open = $derived(order.map((x) => byId.get(x)).filter((i) => i && !i.done));
  const groups = $derived.by(() => {
    if (!current?.sections) return [{ key: 'all', items: open }];
    return SECTIONS.map((sec) => ({ key: sec, items: open.filter((i) => (i.section ?? 'other') === sec) })).filter((g) => g.items.length);
  });
  const done = $derived(current ? itemsOfList(current.id).filter((i) => i.done).sort((a, b) => b.done_at.localeCompare(a.done_at)) : []);
  let showDone = $state(false);
  async function clearDone() {
    try {
      const r = await post(`/lists/${current.id}/clear-done`);
      await loadItems();
      toast(t('lists.cleared', { n: r.removed }));
    } catch (err) { showError(err); }
  }

  // Drag to reorder (within an aisle when grouped)
  function moveTo(groupItems) {
    return (itemId, index) => {
      dragging = true;
      const ids = groupItems.map((i) => i.id).filter((x) => x !== itemId);
      ids.splice(index, 0, itemId);
      // Rebuild the full order: this group's ids replace its old positions
      const set = new Set(ids);
      const slots = order.map((x, i) => (set.has(x) ? i : -1)).filter((i) => i >= 0);
      const next = [...order];
      slots.forEach((slot, k) => (next[slot] = ids[k]));
      order = next;
    };
  }
  async function saveOrder() {
    try {
      await put(`/lists/${current.id}/items/order`, { ids: order });
      order.forEach((x, i) => { const it = byId.get(x); if (it) it.position = i; });
    } catch (err) { showError(err); } finally { dragging = false; }
  }

  // Suggestions: what was bought before
  let suggestions = $state([]);
  async function loadSuggestions() {
    if (!checklist || !current) return;
    try { suggestions = await get(`/lists/${current.id}/suggestions`); } catch { /* offline: none */ }
  }
  $effect(() => { if (current?.id && checklist) loadSuggestions(); });
  const shownSuggestions = $derived(suggestions.filter((s) => !open.some((i) => i.title.toLowerCase() === s.name.toLowerCase())));

  // ---------- Labels
  let newLabel = $state('');
  async function addLabel(e) {
    e.preventDefault();
    const name = newLabel.trim();
    if (!name) return;
    try { await post('/labels', { name }); newLabel = ''; await loadLabels(); } catch (err) { showError(err); }
  }
  async function renameLabel(l) {
    const name = prompt(t('labels.rename_prompt'), l.name)?.trim();
    if (!name || name === l.name) return;
    try { await put(`/labels/${l.id}`, { name }); await loadLabels(); } catch (err) { showError(err); }
  }
  async function recolorLabel(l) {
    const next = COLORS[(COLORS.indexOf(l.color) + 1) % COLORS.length];
    try { await put(`/labels/${l.id}`, { color: next }); await loadLabels(); } catch (err) { showError(err); }
  }
  async function removeLabel(l) {
    if (!confirm(t('labels.confirm_delete', { name: l.name }))) return;
    try {
      await del(`/labels/${l.id}`);
      await loadLabels();
      for (const i of app.items) if (i.labels.includes(l.id)) i.labels = i.labels.filter((x) => x !== l.id);
    } catch (err) { showError(err); }
  }
</script>

{#snippet listForm(onsubmit, submitLabel)}
  <form class="card stack form" {onsubmit}>
    <label class="field"><span class="label">{t('lists.name')}</span>
      <!-- svelte-ignore a11y_autofocus -->
      <input class="input" bind:value={draft.name} maxlength="60" placeholder={t('lists.name_placeholder')} autofocus /></label>
    <div class="field">
      <span class="label">{t('lists.kind')}</span>
      <div class="seg">
        <button type="button" class:on={draft.kind === 'checklist'} onclick={() => (draft.kind = 'checklist')}><Icon name="list" size={15} />{t('lists.kind_checklist')}</button>
        <button type="button" class:on={draft.kind === 'project'} onclick={() => (draft.kind = 'project')}><Icon name="project" size={15} />{t('lists.kind_project')}</button>
      </div>
      <p class="tiny muted">{draft.kind === 'checklist' ? t('lists.kind_checklist_hint') : t('lists.kind_project_hint')}</p>
    </div>
    {#if draft.kind === 'checklist'}
      <label class="check-line"><input type="checkbox" class="cb" bind:checked={draft.sections} />{t('shop.by_section')}</label>
    {/if}
    <div class="field">
      <span class="label">{t('lists.color')}</span>
      <div class="swatches" role="radiogroup" aria-label={t('lists.color')}>
        {#each COLORS as c (c)}
          <button type="button" class="swatch c-{c}" class:on={draft.color === c} role="radio" aria-checked={draft.color === c}
                  aria-label={t('color.' + c)} title={t('color.' + c)} onclick={() => (draft.color = c)}></button>
        {/each}
      </div>
    </div>
    <div class="row">
      <button type="button" class="btn" onclick={() => { creating = false; editing = false; }}>{t('common.close')}</button>
      <button class="btn primary grow" disabled={!draft.name.trim()}>{submitLabel}</button>
    </div>
  </form>
{/snippet}

{#if id}
  <!-- ===== One list ===== -->
  <a class="back small" href="#/lists"><Icon name="left" size={16} />{t('lists.back')}</a>
  {#if !app.loaded}
    <p class="muted">{t('common.wait')}</p>
  {:else if !current}
    <p class="empty">{t('lists.not_found')}</p>
  {:else}
    <header class="head">
      <h1 class="title c-{current.color}"><span class="dot big"></span>{current.name}
        {#if current.template}<span class="badge primary">{t('templates.badge')}</span>{/if}
        {#if current.archived}<span class="badge">{t('lists.archived')}</span>{/if}</h1>
      <div class="row">
        <button class="btn icon ghost" onclick={() => (editing ? (editing = false) : startEdit())} aria-label={t('lists.edit')} title={t('lists.edit')}><Icon name="edit" /></button>
        {#if current.template}
          <button class="btn primary" onclick={() => copy(current, false)}><Icon name="copy" size={16} />{t('templates.use')}</button>
        {:else if current.kind === 'project'}
          <button class="btn primary" onclick={() => openEditor(null, { list_id: current.id })}><Icon name="plus" size={16} />{t('item.new')}</button>
        {/if}
      </div>
    </header>
    {#if current.template}<p class="small muted tpl-note">{t('templates.explain')}</p>{/if}

    {#if editing}
      {@render listForm(saveEdit, t('common.save'))}
      <div class="row wrap edit-actions">
        <button class="btn" onclick={() => copy(current, false)}><Icon name="copy" size={16} />{t('templates.duplicate')}</button>
        {#if !current.template}<button class="btn" onclick={() => copy(current, true)}><Icon name="project" size={16} />{t('templates.save_as')}</button>{/if}
        {#if !current.template}<button class="btn" onclick={() => setArchived(!current.archived)}>{current.archived ? t('lists.unarchive') : t('lists.archive')}</button>{/if}
        <button class="btn danger" onclick={removeList}><Icon name="trash" size={16} />{t('lists.delete')}</button>
      </div>
    {/if}

    <QuickAdd defaults={{ list_id: current.id, category: checklist ? 'shopping' : 'home' }} shopping={checklist}
              suggestions={shownSuggestions} onadded={() => checklist && loadSuggestions()}
              placeholder={checklist ? t('lists.add_checklist') : t('lists.add_project')} />

    <div class="items">
      {#if open.length}
        {#each groups as gr (gr.key)}
          <section class="group">
            {#if gr.key !== 'all'}<h2 class="sec">{t('section.' + gr.key)} <span class="badge">{gr.items.length}</span></h2>{/if}
            <div class="card list" use:sortable={{ onmove: moveTo(gr.items), onend: saveOrder }}>
              {#each gr.items as item (item.id)}<ItemRow {item} showList={false} compact={checklist} handle={checklist} />{/each}
            </div>
          </section>
        {/each}
      {:else}
        <p class="muted small">{done.length ? t('lists.all_done') : t('lists.nothing')}</p>
      {/if}

      {#if done.length}
        <div class="row wrap">
          <button class="btn ghost sm" onclick={() => (showDone = !showDone)}>{t('lists.done_section', { n: done.length })}</button>
          <button class="btn soft sm" onclick={clearDone}><Icon name="broom" size={15} />{t('lists.clear_done')}</button>
        </div>
        {#if showDone}
          <div class="card list">{#each done as item (item.id)}<ItemRow {item} showList={false} compact={checklist} />{/each}</div>
        {/if}
      {/if}
    </div>
  {/if}
{:else}
  <!-- ===== All lists ===== -->
  <header class="head">
    <div><h1>{t('nav.lists')}</h1><p class="muted">{t('lists.subtitle')}</p></div>
    {#if !creating}<button class="btn primary" onclick={() => startCreate()}><Icon name="plus" size={16} />{t('lists.new')}</button>{/if}
  </header>

  {#if creating}
    {@render listForm(create, t('lists.new'))}
  {/if}

  {#if app.loaded && !active.length && !creating}
    <div class="empty stack"><p>{t('lists.empty')}</p></div>
  {/if}
  {#if !creating}
    <div class="chips suggestions">
      <span class="tiny muted">{t('lists.suggestions')}:</span>
      {#each SUGGESTIONS.filter((s) => !app.lists.some((l) => l.name === t('lists.suggest_' + s.key))) as s (s.key)}
        <button class="chip" onclick={() => startCreate(s)}><Icon name={s.kind === 'project' ? 'project' : 'list'} size={14} />{t('lists.suggest_' + s.key)}</button>
      {/each}
    </div>
  {/if}

  <div class="grid">
    {#each active as l (l.id)}
      {@const n = openOf(l).length}
      <a class="card tile c-{l.color}" href="#/lists/{l.id}">
        <span class="bar"></span>
        <span class="name"><Icon name={l.kind === 'project' ? 'project' : 'list'} size={16} />{l.name}</span>
        <span class="small muted">{n ? t('lists.open_n', { n }) : itemsOfList(l.id).length ? t('lists.all_done') : t('lists.nothing')}</span>
        {#if n}
          <span class="preview tiny muted">{openOf(l).slice(0, 4).map((i) => i.title).join(' · ')}{n > 4 ? ' …' : ''}</span>
        {/if}
      </a>
    {/each}
  </div>

  {#if templates.length}
    <section class="templates">
      <h2 class="ic"><Icon name="copy" />{t('templates.title')}</h2>
      <p class="small muted">{t('templates.explain')}</p>
      <ul class="tpl-list">
        {#each templates as l (l.id)}
          <li class="c-{l.color}">
            <span class="dot"></span>
            <a class="grow lname" href="#/lists/{l.id}">{l.name}</a>
            <span class="tiny muted">{itemsOfList(l.id).length}</span>
            <button class="btn soft sm" onclick={() => copy(l, false)}>{t('templates.use')}</button>
          </li>
        {/each}
      </ul>
    </section>
  {/if}

  {#if archived.length}
    <details class="archived">
      <summary class="small">{t('lists.archived')} ({archived.length})</summary>
      <div class="grid">
        {#each archived as l (l.id)}
          <a class="card tile c-{l.color} faded" href="#/lists/{l.id}"><span class="bar"></span><span class="name">{l.name}</span></a>
        {/each}
      </div>
    </details>
  {/if}

  <!-- Labels -->
  <section class="card stack labels">
    <h2 class="ic"><Icon name="tag" />{t('labels.title')}</h2>
    <p class="small muted">{t('labels.explain')}</p>
    {#if app.labels.length}
      <ul class="lbl-list">
        {#each app.labels as l (l.id)}
          <li class="c-{l.color}">
            <button class="swatch sm" onclick={() => recolorLabel(l)} aria-label={t('labels.color', { name: l.name })} title={t('color.' + l.color)}></button>
            <span class="grow lname">{l.name}</span>
            <span class="tiny muted">{l.count}</span>
            <button class="btn icon sm ghost" onclick={() => renameLabel(l)} aria-label={t('labels.rename', { name: l.name })}><Icon name="edit" size={16} /></button>
            <button class="btn icon sm ghost" onclick={() => removeLabel(l)} aria-label={t('labels.delete', { name: l.name })}><Icon name="trash" size={16} /></button>
          </li>
        {/each}
      </ul>
    {:else}
      <p class="small muted">{t('labels.empty')}</p>
    {/if}
    <form class="row" onsubmit={addLabel}>
      <input class="input grow" bind:value={newLabel} maxlength="40" placeholder={t('labels.placeholder')} aria-label={t('labels.placeholder')} />
      <button class="btn" disabled={!newLabel.trim()}>{t('labels.add')}</button>
    </form>
  </section>

  <p class="trash-link small"><a href="#/trash"><Icon name="trash" size={15} />{t('trash.title')}</a></p>
{/if}

<style>
  .head { display: flex; flex-wrap: wrap; align-items: flex-end; justify-content: space-between; gap: 12px; margin-bottom: 16px; }
  .title { display: flex; align-items: center; gap: 10px; overflow-wrap: anywhere; flex-wrap: wrap; }
  .dot.big { width: 14px; height: 14px; }
  .back { display: inline-flex; align-items: center; gap: 4px; margin-bottom: 10px; text-decoration: none; font-weight: 500; }
  .tpl-note { margin: -8px 0 14px; max-width: 640px; }
  .form { max-width: 560px; margin-bottom: 16px; }
  .seg button { display: inline-flex; align-items: center; justify-content: center; gap: 6px; }
  .check-line { display: flex; align-items: center; gap: 8px; font-size: 0.9rem; cursor: pointer; }
  .cb { width: 18px; height: 18px; accent-color: var(--primary); }
  .swatches { display: flex; flex-wrap: wrap; gap: 8px; }
  .swatch { width: 30px; height: 30px; border-radius: 50%; border: 2px solid var(--surface); background: var(--c); cursor: pointer;
    box-shadow: 0 0 0 1px var(--line-strong); padding: 0; }
  .swatch.on { box-shadow: 0 0 0 2px var(--ink); }
  .swatch.sm { width: 18px; height: 18px; border-width: 0; box-shadow: none; flex-shrink: 0; }
  .edit-actions { margin: -6px 0 16px; }
  .suggestions { align-items: center; margin-bottom: 14px; }
  .empty { margin-bottom: 12px; }
  .grid { display: grid; gap: 12px; grid-template-columns: repeat(auto-fill, minmax(min(100%, 230px), 1fr)); margin-bottom: 20px; max-width: 1000px; }
  .tile { position: relative; overflow: hidden; display: flex; flex-direction: column; gap: 4px; text-decoration: none; color: var(--ink);
    padding: 16px 16px 14px 20px; min-width: 0; }
  .tile:hover { border-color: var(--c); }
  .tile .bar { position: absolute; left: 0; top: 0; bottom: 0; width: 5px; background: var(--c); }
  .tile .name { display: flex; align-items: center; gap: 8px; font-weight: 600; overflow-wrap: anywhere; }
  .tile .name :global(svg) { color: var(--c); }
  .preview { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .faded { opacity: 0.65; }
  .templates { max-width: 560px; margin-bottom: 20px; display: flex; flex-direction: column; gap: 8px; }
  .tpl-list { list-style: none; margin: 0; padding: 0; }
  .tpl-list li { display: flex; align-items: center; gap: 10px; padding: 6px 0; border-bottom: 1px solid var(--line); }
  .tpl-list li:last-child { border: 0; }
  .tpl-list a { color: var(--ink); text-decoration: none; }
  .tpl-list a:hover { color: var(--primary); }
  .archived { margin-bottom: 20px; }
  .archived summary { cursor: pointer; color: var(--muted); margin-bottom: 10px; }
  .items { display: flex; flex-direction: column; gap: 12px; max-width: 760px; }
  .group { display: flex; flex-direction: column; gap: 6px; }
  .sec { display: flex; align-items: center; gap: 8px; font-size: 0.9rem; }
  .list { padding: 0; overflow: hidden; }
  :global(.sorting) { user-select: none; cursor: grabbing; }
  .labels { max-width: 560px; }
  .ic { display: flex; align-items: center; gap: 8px; }
  .lbl-list { list-style: none; margin: 0; padding: 0; }
  .lbl-list li { display: flex; align-items: center; gap: 8px; padding: 6px 0; border-bottom: 1px solid var(--line); }
  .lbl-list li:last-child { border: 0; }
  .lname { font-weight: 550; overflow-wrap: anywhere; }
  .trash-link { margin-top: 18px; }
  .trash-link a { display: inline-flex; align-items: center; gap: 6px; color: var(--muted); text-decoration: none; }
  .trash-link a:hover { color: var(--ink); }
</style>

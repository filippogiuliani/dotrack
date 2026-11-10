// Changes to items that also work offline: applied here at once, sent to the server now or, without a
// connection, queued on the device and sent in order when it is back. Items created offline get a
// temporary negative id until the server gives them a real one.
import { api } from './api.js';
import { t } from './i18n.svelte.js';
import { app, findItem, loadItems, removeItem, showError, toast, upsert } from './store.svelte.js';
import { fmtDayMonth, today } from './date.js';

const KEY = 'dotrack.outbox';
let queue = [];
try { queue = JSON.parse(localStorage.getItem(KEY) ?? '[]'); } catch { queue = []; }
app.pending = queue.length;
const save = () => {
  app.pending = queue.length;
  try { localStorage.setItem(KEY, JSON.stringify(queue)); } catch { /* ignore */ }
};

/** Run a change: online → the server's answer; offline → null, after queueing it */
async function send(method, path, body) {
  if (navigator.onLine && !queue.length) {
    try {
      return await api(path, { method, body });
    } catch (e) {
      if (!e.offline) throw e;
    }
  }
  queue.push({ method, path, body });
  save();
  app.online = false;
  return null;
}

/** Signing out: queued changes must not be sent as someone else */
export function clearQueue() {
  queue = [];
  save();
}

let flushing = false;
/** Send what was queued. Stops at the first network error; a change the server refuses is dropped. */
export async function flush() {
  if (flushing || !queue.length) return;
  flushing = true;
  const ids = {}; // temporary id → real id
  const real = (path) => path.replace(/\/items\/(-\d+)/, (m, tmp) => `/items/${ids[tmp] ?? tmp}`);
  try {
    while (queue.length) {
      const job = queue[0];
      if (/\/items\/-\d+/.test(real(job.path))) { queue.shift(); save(); continue; } // its creation failed
      try {
        const r = await api(real(job.path), { method: job.method, body: job.body });
        if (job.temp && r?.id) { ids[job.temp] = r.id; removeItem(Number(job.temp)); upsert(r); }
      } catch (e) {
        if (e.offline) return;
        showError(e);
      }
      queue.shift();
      save();
    }
    app.online = true;
    await loadItems().catch(() => {});
  } finally { flushing = false; }
}

// ---------- Actions ----------

export async function complete(item, { undoable = true } = {}) {
  upsert({ ...item, done: true, done_at: new Date().toISOString().slice(0, 19).replace('T', ' ') });
  try {
    const r = await send('POST', `/items/${item.id}/done`);
    if (r) { upsert(r.item); if (r.next) upsert(r.next); }
    const msg = r?.next ? t('item.done_next', { date: fmtDayMonth(r.next.due_date) }) : t('item.done');
    toast(msg, 'ok', undoable ? { label: t('common.undo'), run: () => reopen(findItem(item.id) ?? item) } : null);
  } catch (e) { upsert(item); showError(e); }
}

export async function reopen(item) {
  upsert({ ...item, done: false, done_at: null });
  try {
    const r = await send('POST', `/items/${item.id}/undo`);
    if (r) { upsert(r); await loadItems(); } // the next occurrence created on completion may be gone
  } catch (e) { upsert(item); showError(e); }
}

export async function toggleCheck(item, check, done) {
  const local = { ...item, checks: item.checks.map((c) => (c.id === check.id ? { ...c, done } : c)) };
  upsert(local);
  try { const r = await send('PATCH', `/items/${item.id}/checks/${check.id}`, { done }); if (r) upsert(r); }
  catch (e) { upsert(item); showError(e); }
}

export async function postpone(item, date) {
  upsert({ ...item, due_date: date });
  try {
    const r = await send('POST', `/items/${item.id}/postpone`, { date });
    if (r) upsert(r);
    toast(t('postpone.done', { date: fmtDayMonth(date) }), 'ok', { label: t('common.undo'), run: () => postpone(findItem(item.id) ?? item, item.due_date ?? today()) });
  } catch (e) { upsert(item); showError(e); }
}

export async function remove(item) {
  removeItem(item.id);
  try {
    await send('DELETE', `/items/${item.id}`);
    toast(t('item.deleted'), 'ok', { label: t('common.undo'), run: () => restore(item) });
  } catch (e) { upsert(item); showError(e); }
}

export async function restore(item) {
  upsert(item);
  try { const r = await send('POST', `/items/${item.id}/restore`); if (r) upsert(r); }
  catch (e) { removeItem(item.id); showError(e); }
}

/** Create an item; offline it shows at once with a temporary id */
export async function create(body) {
  if (navigator.onLine && !queue.length) {
    try {
      const item = await api('/items', { method: 'POST', body });
      upsert(item);
      return item;
    } catch (e) {
      if (!e.offline) throw e;
    }
  }
  const temp = -Date.now();
  const item = {
    id: temp, kind: 'task', category: 'other', notes: '', subject: '', due_date: null, due_time: null, end_time: null, end_date: null,
    location: '', assignee_id: null, person_id: null, priority: 0, recur_unit: null, recur_every: null, recur_from: 'due',
    remind_days: null, remind_time: null, list_id: null, quantity: '', section: null, rotation: null, position: 1e9,
    checks: [], attachments: [], comment_count: 0, done: false, done_at: null, created_at: new Date().toISOString(),
    ...body, labels: (body.labels ?? []).filter((x) => typeof x === 'number'), offline: true,
  };
  upsert(item);
  queue.push({ method: 'POST', path: '/items', body, temp: String(temp) });
  save();
  app.online = false;
  return item;
}

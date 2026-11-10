// Shared state: session (user, family, members), items, lists, labels and notifications.
// What was last loaded is kept on the device, so the app opens (and the shopping list works) without a connection;
// changes made offline wait in a queue (lib/offline.js) and are sent when the connection is back.
import { get } from './api.js';
import { language } from './i18n.svelte.js';

export const app = $state({
  toast: null,
  me: null, // response of /api/me
  items: [], // open items + recently done (not those in templates)
  templateItems: [], // entries of template lists: never in agenda or calendar
  loaded: false,
  editor: null, // item being edited in the global sheet: { item } or { template }
  postpone: null, // item being moved to another day (quick action)
  lists: [], // lists and projects of the family
  labels: [], // labels of the family
  notifications: { items: [], unread: 0 },
  bell: false, // notifications panel open
  online: typeof navigator === 'undefined' ? true : navigator.onLine,
  pending: 0, // changes waiting to be sent
  version: null, // family version last seen (see /api/sync)
});

// ---------- Copy on the device ----------
const CACHE = 'dotrack.cache';
function cacheKey() { return `${CACHE}.${app.me?.user?.id ?? 0}.${app.me?.family?.id ?? 0}`; }
export function saveCache() {
  try {
    localStorage.setItem(cacheKey(), JSON.stringify({ items: [...app.items, ...app.templateItems], lists: app.lists, labels: app.labels }));
    localStorage.setItem(CACHE + '.me', JSON.stringify(app.me));
  } catch { /* storage full or unavailable */ }
}
export function loadCachedMe() {
  try { return JSON.parse(localStorage.getItem(CACHE + '.me') ?? 'null'); } catch { return null; }
}
export function loadCache() {
  try {
    const c = JSON.parse(localStorage.getItem(cacheKey()) ?? 'null');
    if (!c) return false;
    setData(c.items, c.lists, c.labels);
    return true;
  } catch { return false; }
}
export function clearCache() {
  try { for (const k of Object.keys(localStorage)) if (k.startsWith(CACHE)) localStorage.removeItem(k); } catch { /* ignore */ }
}

const isTemplate = (listId) => !!listId && app.lists.find((l) => l.id === listId)?.template;
function setData(items, lists, labels) {
  app.lists = lists;
  app.labels = labels;
  app.items = items.filter((i) => !isTemplate(i.list_id));
  app.templateItems = items.filter((i) => isTemplate(i.list_id));
  app.loaded = true;
}

export async function loadMe() {
  app.me = await get('/me');
  return app.me;
}

export async function loadItems() {
  const [items, lists, labels] = await Promise.all([get('/items'), get('/lists'), get('/labels')]);
  setData(items, lists, labels);
  saveCache();
}
export async function loadLists() {
  app.lists = await get('/lists');
  // An entry may have moved in or out of a template
  setData([...app.items, ...app.templateItems], app.lists, app.labels);
  saveCache();
}
export async function loadLabels() { app.labels = await get('/labels'); saveCache(); }
export async function loadNotifications() {
  try { app.notifications = await get('/notifications'); } catch { /* offline: keep the old ones */ }
}

export const listById = (id) => (id ? app.lists.find((l) => l.id === id) ?? null : null);
export const labelById = (id) => app.labels.find((l) => l.id === id) ?? null;
/** Undated entries of a checklist (the shopping list…) live in their list, not in the agenda */
export const listOnly = (item) => !item.due_date && listById(item.list_id)?.kind === 'checklist';
/** Entries of a list, templates included */
export const itemsOfList = (id) => [...app.items, ...app.templateItems].filter((i) => i.list_id === id);

/** What the quick-add parser needs to recognise lists, labels and people */
export function quickContext() {
  return {
    me: app.me?.user?.id, members: app.me?.members ?? [], people: app.me?.people ?? [],
    lists: app.lists.filter((l) => !l.archived && !l.template), labels: app.labels,
    dayFirst: !/^en-(US|CA|PH)$/i.test(language.locale),
  };
}

/** Put a changed item (as returned by the API) in the list without reloading everything */
export function upsert(item) {
  if (!item) return;
  const target = isTemplate(item.list_id) ? 'templateItems' : 'items';
  const other = target === 'items' ? 'templateItems' : 'items';
  if (app[other].some((x) => x.id === item.id)) app[other] = app[other].filter((x) => x.id !== item.id);
  const i = app[target].findIndex((x) => x.id === item.id);
  if (i >= 0) app[target][i] = item;
  else app[target].push(item);
  saveCache();
}
export function removeItem(id) {
  app.items = app.items.filter((x) => x.id !== id);
  app.templateItems = app.templateItems.filter((x) => x.id !== id);
  saveCache();
}
export const findItem = (id) => app.items.find((x) => x.id === id) ?? app.templateItems.find((x) => x.id === id) ?? null;

export function memberName(id) {
  return app.me?.members?.find((m) => m.id === id)?.name ?? null;
}
export function personName(id) {
  return app.me?.people?.find((p) => p.id === id)?.name ?? null;
}
/** Who is in charge of an item: a member's or a person's name, null for "anyone" */
export const whoName = (item) => (item.person_id ? personName(item.person_id) : item.assignee_id ? memberName(item.assignee_id) : null);
/** Whether "who" choices are worth showing: someone else in the family, with or without an account */
export const hasOthers = () => (app.me?.members?.length ?? 0) > 1 || (app.me?.people?.length ?? 0) > 0;

export function openEditor(item = null, template = {}) {
  app.editor = item ? { item } : { template };
}

let timer;
/** A short message; `action` = { label, run } adds a button (e.g. "Undo") and keeps it a little longer */
export function toast(message, kind = 'ok', action = null) {
  app.toast = { message, kind, action, id: Date.now() };
  clearTimeout(timer);
  timer = setTimeout(() => (app.toast = null), action ? 6000 : kind === 'error' ? 5000 : 2600);
}
export const showError = (e) => toast(e?.message || String(e), 'error');

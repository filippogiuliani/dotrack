// Item constants and helpers shared by the pages
import { t } from './i18n.svelte.js';
import { addDays, daysFromToday, iso, today } from './date.js';

// note: a notice for a day or a period (babysitter away, office closed…), nothing to tick off.
// birthday: due_date is the birth date, it comes back every year.
export const KINDS = ['task', 'deadline', 'appointment', 'note', 'birthday'];
export const TICKABLE = (item) => item.kind !== 'note' && item.kind !== 'birthday';
export const CATEGORIES = ['home', 'shopping', 'car', 'health', 'kids', 'school', 'documents', 'money', 'work', 'leisure', 'other'];
export const PRIORITIES = [1, 0, -1]; // high, normal, low
// Supermarket aisles, in the order one usually walks through a shop
export const SECTIONS = ['produce', 'bakery', 'meat_fish', 'dairy', 'frozen', 'pantry', 'drinks', 'snacks', 'household', 'personal_care',
  'baby', 'pets', 'other'];
export const NO_YEAR = 1904; // birthdays whose year is unknown

// Repetition choices: [unit, every]
export const RECURRENCES = [
  [null, null], ['week', 1], ['month', 1], ['month', 3], ['month', 6], ['year', 1], ['year', 2], ['year', 5], ['year', 10],
];
export const recurKey = (unit, every) => (unit ? `${unit}:${every || 1}` : '');
export function recurName(unit, every) {
  if (!unit) return t('recur.none');
  const n = every || 1;
  return t(n === 1 ? `recur.${unit}` : `recur.${unit}s`, { n });
}

// Reminder choices, in days before
export const REMINDERS = [null, 0, 1, 2, 3, 7, 14, 30, 60, 90];
export function reminderName(d) {
  if (d === null || d === undefined) return t('remind.none');
  if (d === 0) return t('remind.same_day');
  if (d === 1) return t('remind.day_before');
  return t('remind.days_before', { n: d });
}

// Defaults per type
export const DEFAULTS = {
  task: { remind_days: null, category: 'home' },
  deadline: { remind_days: 30, category: 'car' },
  appointment: { remind_days: 1, category: 'health' },
  note: { remind_days: 1, category: 'kids' },
  birthday: { remind_days: 3, category: 'other' },
};

// Ready-made notices: title key, category, whether it usually covers a period
export const NOTE_PRESETS = [
  { key: 'babysitter', category: 'kids' },
  { key: 'office_closed', category: 'work', period: true },
  { key: 'school_closed', category: 'school', period: true },
  { key: 'holidays', category: 'leisure', period: true },
  { key: 'strike', category: 'school' },
];

/** Birthday in a given year (29 February becomes the 28th in the other years) */
function anniversary(birth, year) {
  const [, m, d] = birth.split('-').map(Number);
  const last = new Date(year, m, 0).getDate();
  return iso(new Date(year, m - 1, Math.min(d, last)));
}
/** Date the item is about: the next birthday (today or later) for birthdays, otherwise its date */
export function when(item) {
  if (item.kind === 'birthday' && item.due_date) {
    const t = today();
    const y = +t.slice(0, 4);
    const d = anniversary(item.due_date, y);
    return d >= t ? d : anniversary(item.due_date, y + 1);
  }
  return item.due_date || null;
}
/** Age at the next birthday, null when the year is unknown */
export function age(item) {
  const y = +item.due_date.slice(0, 4);
  return y === NO_YEAR ? null : +when(item).slice(0, 4) - y;
}
/** Days an item shows on in the calendar between `from` and `to` (inclusive, ISO dates) */
export function daysIn(item, from, to) {
  if (!item.due_date) return [];
  if (item.kind === 'birthday') {
    const out = [];
    for (let y = +from.slice(0, 4); y <= +to.slice(0, 4); y++) {
      const d = anniversary(item.due_date, y);
      if (d >= from && d <= to) out.push(d);
    }
    return out;
  }
  const last = item.end_date || item.due_date;
  if (last < from || item.due_date > to) return [];
  const out = [];
  for (let d = item.due_date < from ? from : item.due_date; d <= last && d <= to; d = addDays(d, 1)) out.push(d);
  return out;
}
/** A notice that is going on today */
export const ongoing = (item) => item.kind === 'note' && item.due_date <= today() && (item.end_date || item.due_date) >= today();
/** Past notices and past appointments are over: they don't belong in the agenda */
export const over = (item) =>
  (item.kind === 'note' && (item.end_date || item.due_date) < today()) ||
  (item.kind === 'appointment' && item.due_date && daysFromToday(item.due_date) < 0);


// Ready-made deadlines (Italian life admin): title key, category, repetition, reminder
export const PRESETS = [
  { key: 'car_tax', category: 'car', recur_unit: 'year', recur_every: 1, remind_days: 30 },
  { key: 'car_insurance', category: 'car', recur_unit: 'year', recur_every: 1, remind_days: 30 },
  { key: 'car_inspection', category: 'car', recur_unit: 'year', recur_every: 2, remind_days: 30 },
  { key: 'car_service', category: 'car', recur_unit: 'year', recur_every: 1, remind_days: 14 },
  { key: 'tyres', category: 'car', recur_unit: 'month', recur_every: 6, remind_days: 14 },
  { key: 'licence', category: 'documents', recur_unit: 'year', recur_every: 10, remind_days: 90 },
  { key: 'id_card', category: 'documents', recur_unit: 'year', recur_every: 10, remind_days: 90 },
  { key: 'passport', category: 'documents', recur_unit: 'year', recur_every: 10, remind_days: 90 },
  { key: 'health_card', category: 'documents', recur_unit: 'year', recur_every: 6, remind_days: 60 },
  { key: 'home_insurance', category: 'home', recur_unit: 'year', recur_every: 1, remind_days: 30 },
  { key: 'boiler', category: 'home', recur_unit: 'year', recur_every: 1, remind_days: 30 },
  { key: 'tax_return', category: 'money', recur_unit: 'year', recur_every: 1, remind_days: 30 },
  { key: 'vaccine', category: 'kids', recur_unit: null, recur_every: null, remind_days: 7 },
];

/** Where an item stands: label ("tra 3 giorni") and level for the badge colour */
export function dueInfo(item) {
  const date = when(item);
  if (!date) return null;
  const n = daysFromToday(date);
  let level = '';
  if (!item.done) {
    if (n < 0) level = 'danger';
    else if (n === 0) level = 'primary';
    else if (item.remind_days !== null && n <= item.remind_days) level = 'warn';
  }
  return { n, level };
}

/** Section of the agenda an open item belongs to */
export function bucket(item) {
  if (ongoing(item)) return 'today';
  const date = when(item);
  if (!date) return 'someday';
  const n = daysFromToday(date);
  if (n < 0) return 'overdue';
  if (n === 0) return 'today';
  if (n === 1) return 'tomorrow';
  if (n <= 7) return 'week';
  if (n <= 31) return 'month';
  return 'later';
}
export const BUCKETS = ['overdue', 'today', 'tomorrow', 'week', 'month', 'later', 'someday'];

/** By date, then time, then priority (high first) */
export const byDue = (a, b) =>
  (when(a) ?? '9999').localeCompare(when(b) ?? '9999') ||
  (a.due_time ?? '99').localeCompare(b.due_time ?? '99') || (b.priority ?? 0) - (a.priority ?? 0) || a.id - b.id;

/** Link that opens Google Calendar with the event pre-filled (one-off copy, not kept in sync) */
export function googleCalendarLink(item) {
  if (!item.due_date) return null;
  const d = when(item).replaceAll('-', '');
  let dates;
  if (item.due_time) {
    const start = item.due_time.replace(':', '') + '00';
    let end = item.end_time;
    if (!end || end <= item.due_time) {
      const [h, m] = item.due_time.split(':').map(Number);
      end = `${String(Math.min(h + 1, 23)).padStart(2, '0')}:${String(h + 1 > 23 ? 59 : m).padStart(2, '0')}`;
    }
    dates = `${d}T${start}/${d}T${end.replace(':', '')}00`;
  } else {
    dates = `${d}/${addDays(item.end_date || item.due_date, 1).replaceAll('-', '')}`;
  }
  const details = [item.notes, ...(item.checks ?? []).map((c) => '• ' + c.text)].filter(Boolean).join('\n');
  const p = new URLSearchParams({ action: 'TEMPLATE', text: item.title, dates, ctz: 'Europe/Rome' });
  if (item.kind === 'birthday') p.set('recur', 'RRULE:FREQ=YEARLY');
  if (details) p.set('details', details);
  if (item.location) p.set('location', item.location);
  return 'https://calendar.google.com/calendar/render?' + p.toString();
}

export const mapsLink = (place) => 'https://www.google.com/maps/search/?api=1&query=' + encodeURIComponent(place);

export function blankItem(template = {}) {
  const kind = template.kind ?? 'task';
  return {
    kind, title: '', notes: '', subject: '', due_date: template.due_date ?? (kind === 'task' || kind === 'birthday' ? '' : today()), due_time: '',
    end_time: '', end_date: '', location: '', assignee_id: null, person_id: null, priority: 0, recur_unit: null, recur_every: null,
    checks: [], attachments: [],
    ...DEFAULTS[kind], ...template,
  };
}

export const fileSize = (n) => (n < 1024 * 1024 ? `${Math.max(1, Math.round(n / 1024))} KB` : `${(n / 1024 / 1024).toFixed(1)} MB`);

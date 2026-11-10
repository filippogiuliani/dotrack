// Quick add: understands dates, times, repetition, #labels, +list, @who and !priority typed in plain words,
// in Italian or English. "Dentista martedì alle 15:30 #salute @Sara !" → title "Dentista", next Tuesday
// at 15:30, label "salute", assigned to Sara, high priority.
// Pure functions (no Svelte, no DOM): tested with `npm test`.

const pad = (n) => String(n).padStart(2, '0');
const iso = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const addDays = (d, n) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + n);
function addMonths(d, n) {
  const last = new Date(d.getFullYear(), d.getMonth() + n + 1, 0).getDate();
  return new Date(d.getFullYear(), d.getMonth() + n, Math.min(d.getDate(), last));
}

// Word boundaries that also work with accented letters (lunedì, più…)
const B = '(?<![\\p{L}\\p{N}])';
const E = '(?![\\p{L}\\p{N}])';
const re = (src) => new RegExp(B + '(?:' + src + ')' + E, 'iu');

// Monday = 0
const WEEKDAYS = [
  ['lunedì', 'lunedi', 'monday'], ['martedì', 'martedi', 'tuesday'], ['mercoledì', 'mercoledi', 'wednesday'],
  ['giovedì', 'giovedi', 'thursday'], ['venerdì', 'venerdi', 'friday'], ['sabato', 'saturday'], ['domenica', 'sunday'],
];
const MONTHS = [
  ['gennaio', 'gen', 'january', 'jan'], ['febbraio', 'feb', 'february'], ['marzo', 'mar', 'march'], ['aprile', 'apr', 'april'],
  ['maggio', 'mag', 'may'], ['giugno', 'giu', 'june', 'jun'], ['luglio', 'lug', 'july', 'jul'], ['agosto', 'ago', 'august', 'aug'],
  ['settembre', 'sett', 'september', 'sep', 'sept'], ['ottobre', 'ott', 'october', 'oct'], ['novembre', 'nov', 'november'],
  ['dicembre', 'dic', 'december', 'dec'],
];
const WEEKDAY_RE = WEEKDAYS.flat().join('|');
const MONTH_RE = MONTHS.flat().sort((a, b) => b.length - a.length).join('|');
const weekdayIndex = (w) => WEEKDAYS.findIndex((names) => names.includes(w.toLowerCase()));
const monthIndex = (m) => MONTHS.findIndex((names) => names.includes(m.toLowerCase().replace(/\.$/, '')));

const UNITS = {
  giorno: 'day', giorni: 'day', day: 'day', days: 'day',
  settimana: 'week', settimane: 'week', week: 'week', weeks: 'week',
  mese: 'month', mesi: 'month', month: 'month', months: 'month',
  anno: 'year', anni: 'year', year: 'year', years: 'year',
};
const UNIT_RE = Object.keys(UNITS).sort((a, b) => b.length - a.length).join('|');
const NUMBER_WORDS = { un: 1, uno: 1, una: 1, a: 1, an: 1, one: 1, due: 2, two: 2, tre: 3, three: 3, quattro: 4, four: 4, cinque: 5, five: 5,
  sei: 6, six: 6, sette: 7, seven: 7, otto: 8, eight: 8, nove: 9, nine: 9, dieci: 10, ten: 10 };
const num = (s) => (s === undefined ? 1 : /^\d+$/.test(s) ? Number(s) : NUMBER_WORDS[s.toLowerCase()] ?? 1);
const NUM_RE = '\\d{1,3}|' + Object.keys(NUMBER_WORDS).join('|');

function nextWeekday(today, wd, forceNext = false) {
  const cur = (today.getDay() + 6) % 7;
  let n = (wd - cur + 7) % 7;
  if (n === 0 && forceNext) n = 7;
  return addDays(today, n);
}

/** A date from day/month(/year): this year, or next year when already past */
function dayMonth(today, d, m, y) {
  if (m < 0 || m > 11 || d < 1 || d > 31) return null;
  let year = y ? (y < 100 ? 2000 + y : y) : today.getFullYear();
  let date = new Date(year, m, d);
  if (date.getMonth() !== m) return null; // 31 April
  if (!y && date < today) date = new Date(year + 1, m, d);
  return date;
}

// Words that only introduce a date or a time and go away with it ("entro venerdì", "alle 15")
const LEAD = '(?:(?:entro|per|di|il|lo|la|on|by|due|before)\\s+)?';

/**
 * @param {string} text
 * @param {object} ctx  { lists: [{id, name}], labels: [{id, name}], members: [{id, name}], people: [{id, name}],
 *                        me: id, today: Date, dayFirst: true }
 * @returns {{ title, due_date, due_time, recur_unit, recur_every, priority, labels: string[], list_id, assignee_id,
 *             person_id, found: {type, text}[] }}
 */
export function parseQuick(text, ctx = {}) {
  const today = ctx.today ? new Date(ctx.today.getFullYear(), ctx.today.getMonth(), ctx.today.getDate()) : (() => {
    const n = new Date(); return new Date(n.getFullYear(), n.getMonth(), n.getDate());
  })();
  const dayFirst = ctx.dayFirst ?? true;
  const out = { title: '', due_date: null, due_time: null, recur_unit: null, recur_every: null, priority: 0, labels: [],
                list_id: null, assignee_id: null, person_id: null, found: [] };
  let s = ' ' + text + ' ';
  let date = null;

  // Takes the first match of `regex` out of the text and hands it to `fn`; returns true when found
  function take(regex, type, fn) {
    const m = s.match(regex);
    if (!m) return false;
    if (fn(m) === false) return false;
    s = s.slice(0, m.index) + ' ' + s.slice(m.index + m[0].length);
    out.found.push({ type, text: m[0].trim() });
    return true;
  }

  // ---- Repetition: "ogni 2 settimane", "ogni lunedì", "tutti i giorni", "every month", "weekly"
  take(re(`(?:ogni|every)\\s+(${WEEKDAY_RE})`), 'repeat', (m) => {
    out.recur_unit = 'week'; out.recur_every = 1;
    date = nextWeekday(today, weekdayIndex(m[1]));
  }) ||
  take(re(`(?:ogni|every)\\s+(?:(${NUM_RE})\\s+)?(${UNIT_RE})`), 'repeat', (m) => {
    out.recur_unit = UNITS[m[2].toLowerCase()]; out.recur_every = num(m[1]);
  }) ||
  take(re('tutti\\s+i\\s+giorni|daily'), 'repeat', () => { out.recur_unit = 'day'; out.recur_every = 1; }) ||
  take(re('weekly'), 'repeat', () => { out.recur_unit = 'week'; out.recur_every = 1; }) ||
  take(re('monthly'), 'repeat', () => { out.recur_unit = 'month'; out.recur_every = 1; }) ||
  take(re('yearly|annually'), 'repeat', () => { out.recur_unit = 'year'; out.recur_every = 1; });

  // ---- Dates
  if (!date) {
    take(re(LEAD + 'dopodomani|day\\s+after\\s+tomorrow'), 'date', () => { date = addDays(today, 2); }) ||
    take(re(LEAD + '(?:oggi|today|stasera|tonight)'), 'date', () => { date = today; }) ||
    take(re(LEAD + '(?:domani|tomorrow)'), 'date', () => { date = addDays(today, 1); }) ||
    take(re(LEAD + `(?:(?:tra|fra|in)\\s+(${NUM_RE})\\s+(${UNIT_RE}))`), 'date', (m) => {
      const n = num(m[1]), u = UNITS[m[2].toLowerCase()];
      date = u === 'day' ? addDays(today, n) : u === 'week' ? addDays(today, 7 * n) : addMonths(today, u === 'year' ? 12 * n : n);
    }) ||
    take(re(LEAD + '(?:la\\s+)?(?:prossima\\s+settimana|settimana\\s+prossima|next\\s+week)'), 'date', () => {
      date = nextWeekday(today, 0, true);
    }) ||
    take(re(LEAD + '(?:fine\\s+(?:del\\s+)?mese|end\\s+of\\s+(?:the\\s+)?month)'), 'date', () => {
      date = new Date(today.getFullYear(), today.getMonth() + 1, 0);
    }) ||
    take(re(LEAD + `(?:(prossimo|prossima|next)\\s+)?(${WEEKDAY_RE})(?:\\s+(prossimo|prossima))?`), 'date', (m) => {
      date = nextWeekday(today, weekdayIndex(m[2]), !!(m[1] || m[3]));
    }) ||
    // 15 novembre (2026), 3 mar
    take(re(LEAD + `(\\d{1,2})\\s+(${MONTH_RE})\\.?(?:\\s+(\\d{4}))?`), 'date', (m) => {
      date = dayMonth(today, +m[1], monthIndex(m[2]), m[3] ? +m[3] : null);
      return !!date;
    }) ||
    // November 15
    take(re(LEAD + `(${MONTH_RE})\\.?\\s+(\\d{1,2})(?:st|nd|rd|th)?(?:,?\\s+(\\d{4}))?`), 'date', (m) => {
      date = dayMonth(today, +m[2], monthIndex(m[1]), m[3] ? +m[3] : null);
      return !!date;
    }) ||
    // 15/11, 15/11/2026, 15-11-26, 2026-11-15
    take(re(LEAD + '(\\d{4})-(\\d{1,2})-(\\d{1,2})'), 'date', (m) => {
      date = dayMonth(today, +m[3], +m[2] - 1, +m[1]);
      return !!date;
    }) ||
    take(re(LEAD + '(\\d{1,2})[/.-](\\d{1,2})(?:[/.-](\\d{2}|\\d{4}))?'), 'date', (m) => {
      // "9.30" is a time, not 9 March: with a dot only when a year follows
      if (m[0].includes('.') && !m[3]) return false;
      const [d, mo] = dayFirst ? [+m[1], +m[2]] : [+m[2], +m[1]];
      date = dayMonth(today, d, mo - 1, m[3] ? +m[3] : null);
      return !!date;
    }) ||
    // "il 15": the next 15th
    take(re('(?:il|entro\\s+il|on\\s+the)\\s+(\\d{1,2})(?:st|nd|rd|th)?'), 'date', (m) => {
      const d = +m[1];
      if (d < 1 || d > 31) return false;
      let c = new Date(today.getFullYear(), today.getMonth(), d);
      if (c.getDate() !== d || c < today) c = new Date(today.getFullYear(), today.getMonth() + 1, d);
      if (c.getDate() !== d) return false;
      date = c;
    });
  }

  // ---- Time: "alle 15", "alle 9:30", "ore 18", "h 9", "15:30", "at 3pm", "3:30 pm"
  const setTime = (h, mi, ampm) => {
    h = +h; mi = +(mi ?? 0);
    if (ampm) {
      const pm = ampm.toLowerCase() === 'pm';
      if (h < 1 || h > 12) return false;
      h = (h % 12) + (pm ? 12 : 0);
    }
    if (h > 23 || mi > 59) return false;
    out.due_time = `${pad(h)}:${pad(mi)}`;
  };
  take(re('(?:alle|all\'|ore|h|at)\\s*(\\d{1,2})(?:[:.](\\d{2}))?\\s*(am|pm)?'), 'time', (m) => setTime(m[1], m[2], m[3])) ||
  take(re('(\\d{1,2})(?::(\\d{2}))?\\s*(am|pm)'), 'time', (m) => setTime(m[1], m[2], m[3])) ||
  take(re('(\\d{1,2})[:](\\d{2})'), 'time', (m) => setTime(m[1], m[2]));
  if (/stasera|tonight/i.test(out.found.map((f) => f.text).join(' ')) && !out.due_time) out.due_time = '20:00';
  if (out.due_time && !date) {
    // A time alone: today, or tomorrow when that time has passed
    const now = ctx.now ?? new Date();
    const passed = ctx.today ? false : `${pad(now.getHours())}:${pad(now.getMinutes())}` > out.due_time;
    date = passed ? addDays(today, 1) : today;
  }
  if (out.recur_unit && !date) date = today;

  // ---- !priority
  take(/(?<=\s)(?:!{1,3}(?:alta|high|urgente|urgent)?|!(?:bassa|low))(?=\s)/iu, 'priority', (m) => {
    out.priority = /bassa|low/i.test(m[0]) ? -1 : 1;
  });

  // ---- #labels (several)
  for (let i = 0; i < 10; i++) {
    if (!take(/(?<=\s)[#*]([\p{L}\p{N}_-]{1,40})(?=\s)/u, 'label', (m) => {
      const existing = (ctx.labels ?? []).find((l) => l.name.toLowerCase() === m[1].toLowerCase());
      const name = existing?.name ?? m[1];
      if (!out.labels.some((l) => l.toLowerCase() === name.toLowerCase())) out.labels.push(name);
    })) break;
  }

  // ---- +list: only lists that exist ("+spesa"; "+lista-spesa" or "+bagno" for "Lavori bagno")
  const norm = (x) => x.toLowerCase().replace(/[\s_-]+/g, '');
  take(/(?<=\s)\+([\p{L}\p{N}_-]{1,60})(?=\s)/u, 'list', (m) => {
    const lists = ctx.lists ?? [], w = norm(m[1]);
    const list = lists.find((l) => norm(l.name) === w) ?? lists.find((l) => norm(l.name).startsWith(w)) ??
                 lists.find((l) => l.name.toLowerCase().split(/\s+/).some((part) => norm(part).startsWith(w)));
    if (!list) return false;
    out.list_id = list.id;
  });

  // ---- @who: a member or a person without an account ("@io"/"@me" = me)
  take(/(?<=\s)@([\p{L}\p{N}_-]{1,60})(?=\s)/u, 'who', (m) => {
    const w = m[1].toLowerCase();
    if (['io', 'me', 'mia', 'mio'].includes(w) && ctx.me) { out.assignee_id = ctx.me; return; }
    const match = (x) => x.name.toLowerCase() === w || x.name.toLowerCase().split(/\s+/)[0] === w;
    const member = (ctx.members ?? []).find(match);
    if (member) { out.assignee_id = member.id; return; }
    const person = (ctx.people ?? []).find(match);
    if (person) { out.person_id = person.id; return; }
    return false;
  });

  if (date) out.due_date = iso(date);
  out.title = s.replace(/\s+/g, ' ').trim().replace(/^[,;:–-]\s*|\s*[,;:–-]$/g, '');
  return out;
}

// Quantities on shopping lists: "2 kg mele" → ["mele", "2 kg"], "latte x2" → ["latte", "2"]
const QTY_RE = /^\s*(\d+(?:[.,]\d+)?)\s*(kg|g|gr|hg|l|lt|ml|cl|pz|conf|x)?\.?\s+(?:di\s+|of\s+)?(.+)$/i;
const TRAILING_QTY_RE = /^(.+?)\s+(?:x\s*(\d+)|(\d+)\s*x|×\s*(\d+))\s*$/i;
export function splitQuantity(text) {
  let m = text.match(TRAILING_QTY_RE);
  if (m) return [m[1].trim(), m[2] ?? m[3] ?? m[4]];
  m = text.match(QTY_RE);
  if (m && m[3].trim()) {
    const unit = (m[2] ?? '').toLowerCase();
    return [m[3].trim(), m[1] + (unit && unit !== 'x' ? ' ' + unit : '')];
  }
  return [text.trim(), ''];
}

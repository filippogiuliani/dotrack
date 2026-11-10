// node --test: the quick-add parser
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseQuick } from './quickadd.js';

// Monday 9 November 2026
const today = new Date(2026, 10, 9);
const ctx = {
  today, me: 1,
  members: [{ id: 1, name: 'Fil' }, { id: 2, name: 'Sara Rossi' }],
  people: [{ id: 7, name: 'Giulia' }],
  lists: [{ id: 3, name: 'Spesa' }, { id: 4, name: 'Lavori bagno' }],
  labels: [{ id: 9, name: 'Casa' }],
};
const p = (text) => parseQuick(text, ctx);

test('plain text stays as it is', () => {
  const r = p('Comprare 2 litri di latte');
  assert.equal(r.title, 'Comprare 2 litri di latte');
  assert.equal(r.due_date, null);
  assert.equal(r.found.length, 0);
});

test('relative days', () => {
  assert.deepEqual([p('Chiamare idraulico domani').title, p('Chiamare idraulico domani').due_date], ['Chiamare idraulico', '2026-11-10']);
  assert.equal(p('x oggi').due_date, '2026-11-09');
  assert.equal(p('x dopodomani').due_date, '2026-11-11');
  assert.equal(p('x tra 3 giorni').due_date, '2026-11-12');
  assert.equal(p('x fra due settimane').due_date, '2026-11-23');
  assert.equal(p('x tra 1 mese').due_date, '2026-12-09');
  assert.equal(p('x in 2 weeks').due_date, '2026-11-23');
  assert.equal(p('x tomorrow').due_date, '2026-11-10');
  assert.equal(p('x la prossima settimana').due_date, '2026-11-16');
  assert.equal(p('x fine mese').due_date, '2026-11-30');
  assert.equal(p('Regalo per domani').title, 'Regalo');
});

test('weekdays', () => {
  assert.equal(p('x venerdì').due_date, '2026-11-13');
  assert.equal(p('x entro venerdi').due_date, '2026-11-13');
  assert.equal(p('Pagare entro venerdì').title, 'Pagare');
  assert.equal(p('x lunedì').due_date, '2026-11-09'); // today is Monday
  assert.equal(p('x lunedì prossimo').due_date, '2026-11-16');
  assert.equal(p('x next monday').due_date, '2026-11-16');
  assert.equal(p('x sunday').due_date, '2026-11-15');
});

test('explicit dates', () => {
  assert.equal(p('x 15/11').due_date, '2026-11-15');
  assert.equal(p('x 3/1').due_date, '2027-01-03'); // already past this year
  assert.equal(p('x 15/11/2027').due_date, '2027-11-15');
  assert.equal(p('x 15.11.27').due_date, '2027-11-15');
  assert.equal(p('x 2026-12-24').due_date, '2026-12-24');
  assert.equal(p('x il 20').due_date, '2026-11-20');
  assert.equal(p('x il 5').due_date, '2026-12-05');
  assert.equal(p('x 24 dicembre').due_date, '2026-12-24');
  assert.equal(p('x 3 mar').due_date, '2027-03-03');
  assert.equal(p('x December 24').due_date, '2026-12-24');
  assert.equal(p('x 31/4').due_date, null); // no such day
  assert.equal(parseQuick('x 11/15', { ...ctx, dayFirst: false }).due_date, '2026-11-15');
  assert.equal(p('Tagliando a 30.000 km').due_date, null);
  assert.equal(p('Comprare 5 set di bicchieri').due_date, null);
});

test('times', () => {
  let r = p('Dentista martedì alle 15:30');
  assert.deepEqual([r.title, r.due_date, r.due_time], ['Dentista', '2026-11-10', '15:30']);
  assert.equal(p('x domani alle 9').due_time, '09:00');
  assert.equal(p('x domani alle 9.30').due_time, '09:30');
  assert.equal(p('x domani ore 18').due_time, '18:00');
  assert.equal(p('x tomorrow at 3pm').due_time, '15:00');
  assert.equal(p('x tomorrow 12am').due_time, '00:00');
  assert.equal(p('x domani 14:45').due_time, '14:45');
  assert.equal(p('x domani alle 25').due_time, null);
  r = p('Cena stasera');
  assert.deepEqual([r.title, r.due_date, r.due_time], ['Cena', '2026-11-09', '20:00']);
  // A time alone means today
  assert.equal(p('Chiamare alle 17').due_date, '2026-11-09');
  assert.equal(p('Comprare 2 uova').due_time, null);
});

test('repetition', () => {
  let r = p('Buttare la plastica ogni lunedì');
  assert.deepEqual([r.title, r.recur_unit, r.recur_every, r.due_date], ['Buttare la plastica', 'week', 1, '2026-11-09']);
  r = p('Filtro cappa ogni 3 mesi');
  assert.deepEqual([r.recur_unit, r.recur_every, r.due_date], ['month', 3, '2026-11-09']);
  r = p('Bollo ogni anno 30/11');
  assert.deepEqual([r.title, r.recur_unit, r.due_date], ['Bollo', 'year', '2026-11-30']);
  assert.equal(p('Vitamine tutti i giorni').recur_unit, 'day');
  assert.equal(p('x every 2 weeks').recur_every, 2);
  assert.equal(p('x monthly').recur_unit, 'month');
});

test('labels, list, who, priority', () => {
  const r = p('Chiamare idraulico #casa #urgente +bagno @sara !');
  assert.equal(r.title, 'Chiamare idraulico');
  assert.deepEqual(r.labels, ['Casa', 'urgente']); // existing label keeps its spelling
  assert.equal(r.list_id, 4); // "bagno" → "Lavori bagno"
  assert.equal(r.assignee_id, 2);
  assert.equal(r.priority, 1);
  assert.equal(p('Latte +spesa').list_id, 3);
  assert.equal(p('Latte +lavori-bagno').list_id, 4);
  assert.equal(p('Latte +nonesiste').title, 'Latte +nonesiste');
  assert.equal(p('Compiti @giulia').person_id, 7);
  assert.equal(p('x @io').assignee_id, 1);
  assert.equal(p('x @nessuno').title, 'x @nessuno');
  assert.equal(p('x !bassa').priority, -1);
  assert.equal(p('Scrivere a mario@example.com').title, 'Scrivere a mario@example.com');
});

import { splitQuantity } from './quickadd.js';
test('shopping quantities', () => {
  assert.deepEqual(splitQuantity('2 kg mele'), ['mele', '2 kg']);
  assert.deepEqual(splitQuantity('latte x2'), ['latte', '2']);
  assert.deepEqual(splitQuantity('500 g di farina'), ['farina', '500 g']);
  assert.deepEqual(splitQuantity('3 uova'), ['uova', '3']);
  assert.deepEqual(splitQuantity('Pane'), ['Pane', '']);
});

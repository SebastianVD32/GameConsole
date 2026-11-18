const { test } = require('node:test');
const assert = require('node:assert/strict');
const { EventDelivery } = require('../static/js/gamestats');
const response = (status, body) => ({ status, ok: status >= 200 && status < 300, json: async () => body });
const settle = () => new Promise(resolve => setImmediate(resolve));
const event = (id, matchId, sequence) => ({ eventId: id, matchId, sequence });

test('requests are ordered per match, while a failed match does not block another', async () => {
  const sent = [], retry = [];
  const delivery = new EventDelivery({ schedule: cb => retry.push(cb), fetcher: async (_url, options) => {
    const e = JSON.parse(options.body); sent.push(e.eventId);
    return e.matchId === 'offline' ? response(503, { message: 'offline' }) : response(201, { accepted: true });
  } });
  delivery.enqueue(event('a1', 'offline', 1)); delivery.enqueue(event('a2', 'offline', 2));
  delivery.enqueue(event('b1', 'online', 1)); delivery.enqueue(event('b2', 'online', 2));
  await settle(); assert.deepEqual(sent, ['a1', 'b1', 'b2']);
  assert.deepEqual(delivery.queue.map(e => e.eventId), ['a1', 'a2']); assert.equal(retry.length, 1);
});

test('retry preserves event IDs and accepts only the explicit duplicate acknowledgment', async () => {
  const saved = new Map(); let attempts = 0;
  const delivery = new EventDelivery({ storage: { getItem: k => saved.get(k), setItem: (k, v) => saved.set(k, v) }, schedule: () => {},
    fetcher: async () => ++attempts === 1 ? response(503, {}) : response(409, { code: 'DUPLICATE_EVENT' }) });
  delivery.enqueue(event('stable-id', 'a', 1)); await settle();
  assert.equal(JSON.parse(saved.get(delivery.key))[0].eventId, 'stable-id');
  delivery.retry(); await settle(); assert.equal(delivery.queue.length, 0); assert.equal(delivery.sent, 1);
});

test('validation errors stop automatic retries and retain events for diagnosis', async () => {
  const delivery = new EventDelivery({ schedule: () => assert.fail('must not retry a rejected payload'),
    fetcher: async () => response(422, { message: 'invalid sequence' }) });
  delivery.enqueue(event('a1', 'a', 1)); await settle();
  assert.equal(delivery.queue.length, 1); assert.equal(delivery.error, 'invalid sequence');
});

test('storage failure keeps events in memory and pending queue survives reload', async () => {
  const offline = async () => { throw new TypeError('offline'); };
  const d = new EventDelivery({ storage: { getItem: () => JSON.stringify([event('old', 'a', 1)]), setItem: () => { throw Error(); } }, fetcher: offline, schedule: () => {} });
  d.flush(); await settle(); assert.equal(d.queue[0].eventId, 'old'); assert.equal(d.persistent, false);
});

const { test } = require('node:test');
const assert = require('node:assert/strict');
const { Circuit, RaceCar, RacingGame } = require('../static/js/racing-engine');
const { completeRace } = require('./racing-scenarios.cjs');

test('circuit closes smoothly and its positions and safe speeds remain finite', () => {
  const track = new Circuit();
  assert.deepEqual(track.point(0), track.point(track.length));
  for (let distance = -15; distance <= track.length + 15; distance += 5) {
    const p = track.position(distance, -9);
    assert.ok(Number.isFinite(p.x) && Number.isFinite(p.y) && Number.isFinite(p.angle));
    assert.ok(track.safeSpeed(distance) >= 27 && track.safeSpeed(distance) <= 72);
  }
  const before = track.point(track.length - 0.01), after = track.point(0.01);
  assert.ok(Math.hypot(before.x - after.x, before.y - after.y) < 0.1);
});

test('countdown starts exactly one match and does not move cars early', () => {
  const game = new RacingGame(); game.start(); game.start();
  for (let i = 0; i < 29; i++) game.update(0.1);
  assert.equal(game.state, 'countdown'); assert.equal(game.events.length, 0);
  assert.ok(game.cars.every(car => car.distance === 0));
  game.update(0.1); assert.equal(game.state, 'running'); assert.equal(game.events.length, 1);
  assert.equal(game.events[0].playerId, null);
  assert.equal(new Set(game.events[0].data.driverIds).size, 4);
});

test('acceleration, braking and lateral controls act without reversing', () => {
  const car = new RaceCar({ id: 'p', lane: 0 }), track = new Circuit();
  for (let i = 0; i < 100; i++) car.drive(0.01, { throttle: 1 }, track, i / 100);
  assert.ok(car.speed > 8); const speed = car.speed;
  car.drive(0.1, { brake: 1, steer: 1 }, track, 1.1);
  assert.ok(car.speed < speed); assert.ok(car.lane > 0);
  for (let i = 0; i < 100; i++) car.drive(0.01, { brake: 1 }, track, 2 + i / 100);
  assert.equal(car.speed, 0); assert.ok(car.distance > 0);
});

test('grass slows a car, steering can recover even from a standstill', () => {
  const track = new Circuit(), asphalt = new RaceCar({ id: 'a', lane: 0 }), grass = new RaceCar({ id: 'b', lane: 20 });
  asphalt.speed = grass.speed = 30;
  for (let i = 0; i < 100; i++) {
    asphalt.drive(0.01, { throttle: 1 }, track, i / 100); grass.drive(0.01, { throttle: 1 }, track, i / 100);
  }
  assert.ok(grass.speed < asphalt.speed / 2);
  grass.speed = 0; grass.drive(0.1, { steer: -1 }, track, 2); assert.ok(grass.lane < 20);
});

test('contacts slow both cars once per cooldown and do not add unsupported events', () => {
  const game = new RacingGame(); game.start({ countdown: false }); game.elapsed = 2;
  const [a, b] = game.cars; a.distance = b.distance = 100; a.lane = b.lane = 0; a.speed = b.speed = 50;
  game.checkCollisions(); assert.equal(a.speed, 32.5); assert.equal(b.speed, 32.5);
  game.checkCollisions(); assert.equal(a.collisions, 1); assert.equal(b.collisions, 1);
  assert.equal(game.events.length, 1);
});

test('pause freezes countdown, lap clocks and every car, and clears held input', () => {
  const game = new RacingGame(); game.start(); game.update(0.2); game.pause();
  const count = game.countdown; game.update(0.2); assert.equal(game.countdown, count);
  game.resume(); for (let i = 0; i < 30; i++) game.update(0.1);
  game.setInput({ throttle: 1 }); game.update(0.1); game.pause();
  const elapsed = game.elapsed, distances = game.cars.map(car => car.distance);
  for (let i = 0; i < 10; i++) game.update(0.2);
  assert.equal(game.elapsed, elapsed); assert.deepEqual(game.cars.map(car => car.distance), distances);
  game.resume(); assert.equal(game.input.throttle, 0);
});

test('crossings use actual crossing times rather than the car array order', () => {
  const game = new RacingGame({ plannedLaps: 1 }); game.start({ countdown: false });
  const [a, b] = game.cars;
  a.distance = game.circuit.length - 2; b.distance = game.circuit.length - 1;
  a.speed = b.speed = 40;
  game.setInput({ throttle: 1 }); game.update(0.1);
  const laps = game.events.filter(e => e.type === 'LAP_COMPLETED');
  assert.equal(laps[0].playerId, b.id); assert.equal(laps[0].data.position, 1);
  assert.equal(laps[1].playerId, a.id); assert.equal(laps[1].data.position, 2);
  assert.equal(game.state, 'finishing'); assert.equal(game.events.some(e => e.type === 'MATCH_FINISHED'), false);
});

test('all pilots complete three continuous laps before the sole final event', () => {
  const game = completeRace();
  assert.equal(game.events.length, 14); assert.equal(game.playerPosition, 1);
  assert.equal(game.events.at(-1).type, 'MATCH_FINISHED'); assert.equal(game.events.at(-1).playerId, null);
  for (const car of game.cars) {
    assert.equal(car.completedLaps, 3); assert.ok(car.laps.every(time => Number.isInteger(time) && time > 0));
    assert.equal(car.finishTimeMs, car.laps.reduce((a, b) => a + b));
    const laps = game.events.filter(e => e.type === 'LAP_COMPLETED' && e.playerId === car.id);
    assert.deepEqual(laps.map(e => e.data.lapNumber), [1, 2, 3]);
  }
  for (let lap = 1; lap <= 3; lap++) {
    assert.deepEqual(game.events.filter(e => e.type === 'LAP_COMPLETED' && e.data.lapNumber === lap).map(e => e.data.position).sort(), [1, 2, 3, 4]);
  }
  const expected = [...game.cars].sort((a, b) => a.finishTimeMs - b.finishTimeMs || a.lastLapPosition - b.lastLapPosition)
    .map((car, i) => ({ playerId: car.id, position: i + 1 }));
  assert.deepEqual(game.result, expected);
  const count = game.events.length; game.update(1); game.start(); game.begin(); assert.equal(game.events.length, count);
});

test('a slower human car loses without blocking rival completion', () => {
  const game = completeRace({ slowPlayer: true });
  assert.equal(game.state, 'finished'); assert.equal(game.playerPosition, 4);
});

test('abandoning never fabricates a complete result; instances remain independent', () => {
  const a = new RacingGame(), b = new RacingGame(); a.start({ countdown: false });
  a.setInput({ throttle: 1 }); a.update(0.2); a.abandon(); a.update(1);
  assert.equal(a.state, 'abandoned'); assert.equal(a.events.length, 2);
  assert.equal(a.events.at(-1).type, 'MATCH_ABORTED');
  assert.equal(a.events.at(-1).playerId, null);
  assert.deepEqual(a.events.at(-1).data, { reason: 'USER_QUIT' });
  assert.equal(b.events.length, 0); assert.equal(b.player.distance, 0);
  assert.notEqual(a.matchId, b.matchId); assert.notEqual(a.circuit.samples, b.circuit.samples);
});

test('abort reasons close a started race exactly once; countdown has no remote match', () => {
  for (const reason of ['USER_QUIT', 'RESTARTED', 'PAGE_CLOSED']) {
    const game = new RacingGame(); game.start({ countdown: false });
    game.pause(); game.abandon(reason); game.abandon(reason); game.update(1);
    assert.equal(game.events.length, 2);
    assert.deepEqual(game.events.at(-1).data, { reason });
    assert.equal(game.events.at(-1).sequence, 2);
  }
  const early = new RacingGame(); early.start(); early.abandon();
  assert.equal(early.events.length, 0);
  const complete = completeRace(); const count = complete.events.length;
  complete.abandon(); assert.equal(complete.events.length, count);
});

test('physics is independent of animation frame frequency', () => {
  const a = new RacingGame(), b = new RacingGame();
  [a, b].forEach(g => { g.start({ countdown: false }); g.setInput({ throttle: 1 }); });
  for (let i = 0; i < 100; i++) a.update(0.1);
  for (let i = 0; i < 600; i++) b.update(1 / 60);
  assert.ok(Math.abs(a.player.distance - b.player.distance) < 0.01);
  assert.ok(Math.abs(a.player.speed - b.player.speed) < 0.01);
});

test('contract identities, UTC timestamps and sequences are stable for the full race', () => {
  const game = completeRace({ plannedLaps: 1 });
  const fields = ['eventId', 'timestamp', 'gameId', 'gameVersion', 'matchId', 'sequence', 'playerId', 'type', 'data'].sort();
  game.events.forEach((event, index) => {
    assert.deepEqual(Object.keys(event).sort(), fields); assert.equal(event.sequence, index + 1);
    assert.equal(event.matchId, game.matchId); assert.equal(event.gameId, 'RACING'); assert.equal(event.gameVersion, '1.0');
    assert.match(event.timestamp, /Z$/);
    if (index) assert.ok(Date.parse(event.timestamp) >= Date.parse(game.events[index - 1].timestamp));
  });
  assert.equal(new Set(game.events.map(e => e.eventId)).size, game.events.length);
});

const { test } = require('node:test');
const assert = require('node:assert/strict');
const { PacmanGame, Maze } = require('../static/js/pacman-engine');
const { winningGame } = require('./pacman-scenarios.cjs');

function fixture() {
  let clock = Date.parse('2026-11-18T18:00:00Z');
  const game = new PacmanGame({ now: () => clock });
  return { game, tick(seconds = 0.14) { clock += seconds * 1000; game.update(seconds); }, advance(ms) { clock += ms; } };
}

test('all pellets and actor spawns are reachable inside a rectangular maze', () => {
  const m = new Maze(), reachable = m.distances({ x: 10, y: 13 });
  assert.ok(m.rows.every(row => row.length === m.width));
  assert.ok([...m.pellets.keys()].every(id => reachable.has(id)));
  new PacmanGame().ghosts.forEach(g => assert.ok(reachable.has(`${g.x},${g.y}`)));
});

test('start is idempotent, blocked turns are buffered, walls cannot be crossed', () => {
  const f = fixture(), g = f.game; g.start(); g.start();
  assert.equal(g.events.length, 1);
  g.steer('up'); f.tick(); // Wall above spawn: keep moving left until turn becomes possible.
  assert.deepEqual([g.player.x, g.player.y], [9, 13]);
  assert.equal(g.score, 10);
  f.tick(); assert.deepEqual([g.player.x, g.player.y], [9, 12]);
  f.tick(); f.tick(); assert.ok(g.maze.walkable(g.player.x, g.player.y));
});

test('pause freezes movement and active play time; wall-clock power still expires', () => {
  const f = fixture(), g = f.game; g.start();
  Object.assign(g.player, { x: 1, y: 1 }); g.collect();
  assert.ok(g.powered); g.pause(); const elapsed = g.elapsed;
  f.tick(0.2); assert.equal(g.elapsed, elapsed); assert.equal(g.player.x, 1);
  f.advance(8000); assert.equal(g.powered, false);
  g.resume(); f.tick(); assert.equal(g.state, 'running');
});

test('power chain uses exact IDs and scores; each ghost is consumed once per effect', () => {
  const f = fixture(), g = f.game; g.start();
  Object.assign(g.player, { x: 1, y: 1 }); g.collect();
  const power = g.powerEvent;
  for (const ghost of g.ghosts) { Object.assign(ghost, { x: 1, y: 1 }); g.collide(); }
  assert.equal(g.score, 50 + 200 + 400 + 800 + 1600);
  assert.equal(g.events.filter(e => e.type === 'GHOST_EATEN').length, 4);
  g.collide(); assert.equal(g.events.length, 6);
  assert.ok(g.events.filter(e => e.type === 'GHOST_EATEN').every(e => e.data.powerUpEventId === power.eventId));
});

test('expiration boundary kills the player, cancels power and respawns safely', () => {
  const f = fixture(), g = f.game; g.start();
  Object.assign(g.player, { x: 1, y: 1 }); g.collect(); f.advance(8000);
  Object.assign(g.ghosts[0], { x: 1, y: 1 }); g.collide();
  assert.equal(g.lives, 2); assert.equal(g.powerEvent, null);
  assert.deepEqual([g.player.x, g.player.y], [10, 13]);
  const position = [g.player.x, g.player.y]; f.tick(); assert.deepEqual([g.player.x, g.player.y], position);
});

test('losing all lives produces one finish and never permits later events', () => {
  const f = fixture(), g = f.game; g.start();
  for (let i = 0; i < 3; i++) { Object.assign(g.ghosts[0], { x: g.player.x, y: g.player.y }); g.collide(); }
  assert.equal(g.state, 'lost'); const count = g.events.length;
  g.update(1); g.start(); g.finish('RESTARTED'); assert.equal(g.events.length, count);
  assert.deepEqual(g.events.at(-1).data, { score: 0, reason: 'GAME_OVER' });
});

test('full level wins with contract scoring and contiguous sequences', () => {
  const g = winningGame();
  const pellets = g.events.filter(e => e.type === 'PELLET_EATEN').length;
  const powers = g.events.filter(e => e.type === 'POWER_UP_COLLECTED').length;
  assert.equal(pellets + powers, g.maze.total); assert.equal(powers, 4);
  assert.equal(g.score, pellets * 10 + powers * 50);
  assert.equal(g.events.at(-2).type, 'LEVEL_COMPLETED');
  assert.equal(g.events.at(-1).type, 'MATCH_FINISHED');
  g.events.forEach((e, i) => { assert.equal(e.sequence, i + 1); assert.equal(e.matchId, g.matchId); });
  assert.equal(new Set(g.events.map(e => e.eventId)).size, g.events.length);
});

test('simultaneous instances and restarts do not share state or identifiers', () => {
  const a = new PacmanGame(), b = new PacmanGame();
  a.start(); a.update(0.14); assert.equal(b.state, 'ready'); assert.equal(b.score, 0);
  assert.notEqual(a.matchId, b.matchId); assert.notEqual(a.maze.pellets, b.maze.pellets);
  a.finish('RESTARTED'); assert.equal(a.events.at(-1).data.reason, 'RESTARTED');
});

test('active ghosts navigate corridors and eventually catch an idle player', () => {
  const f = fixture(), g = f.game; g.start();
  for (let i = 0; i < 3000 && g.state === 'running'; i++) {
    f.tick(0.1);
    assert.ok(g.ghosts.every(ghost => g.maze.walkable(ghost.x, ghost.y)));
  }
  assert.equal(g.state, 'lost'); assert.equal(g.lives, 0);
});

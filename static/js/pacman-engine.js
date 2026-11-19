/* Rules are independent of the DOM so every tab owns a separate game. */
(function (root) {
  'use strict';
  const DIRECTIONS = { up: [0, -1], left: [-1, 0], down: [0, 1], right: [1, 0] };
  const MAP = [
    '#####################',
    '#o........#........o#',
    '#.###.###.#.###.###.#',
    '#...................#',
    '#.###.#.#####.#.###.#',
    '#.....#...#...#.....#',
    '#####.###.#.###.#####',
    '#.....#.......#.....#',
    '#.###.#.## ##.#.###.#',
    '#...#...     ...#...#',
    '###.#.#.#####.#.#.###',
    '#.....#...#...#.....#',
    '#.#######.#.#######.#',
    '#......... .........#',
    '#.###.#.#####.#.###.#',
    '#o..#.#...#...#.#..o#',
    '###.#.###.#.###.#.###',
    '#.....#.......#.....#',
    '#.#######.#.#######.#',
    '#.........#.........#',
    '#####################',
  ];
  const uuid = () => globalThis.crypto.randomUUID();
  const key = (x, y) => `${x},${y}`;

  class Maze {
    constructor(rows = MAP) {
      this.rows = rows;
      this.width = rows[0].length;
      this.height = rows.length;
      this.pellets = new Map();
      rows.forEach((row, y) => [...row].forEach((cell, x) => {
        if (cell === '.' || cell === 'o') this.pellets.set(key(x, y), cell);
      }));
      this.total = this.pellets.size;
    }
    walkable(x, y) { return !!this.rows[y]?.[x] && this.rows[y][x] !== '#'; }
    neighbors(x, y) {
      return Object.entries(DIRECTIONS).map(([direction, [dx, dy]]) => ({ x: x + dx, y: y + dy, direction }))
        .filter(p => this.walkable(p.x, p.y));
    }
    distances(target) {
      const result = new Map([[key(target.x, target.y), 0]]);
      const queue = [target];
      for (let i = 0; i < queue.length; i++) {
        const p = queue[i];
        for (const next of this.neighbors(p.x, p.y)) {
          const id = key(next.x, next.y);
          if (!result.has(id)) { result.set(id, result.get(key(p.x, p.y)) + 1); queue.push(next); }
        }
      }
      return result;
    }
  }

  class Actor {
    constructor(x, y) { this.spawn = { x, y }; this.reset(); }
    reset() { Object.assign(this, this.spawn); this.previous = { ...this.spawn }; this.direction = 'left'; }
    move(position) { this.previous = { x: this.x, y: this.y }; Object.assign(this, position); }
  }

  class Ghost extends Actor {
    constructor(id, color, x, y, delay) {
      super(x, y); Object.assign(this, { id, color, delay, homeDelay: delay });
    }
    advance(game) {
      if (game.elapsed < this.delay || game.eaten.has(this.id)) return;
      let options = game.maze.neighbors(this.x, this.y);
      const forward = options.filter(p => p.x !== this.previous.x || p.y !== this.previous.y);
      if (forward.length) options = forward;
      let target = game.player;
      // Pinky anticipates a reachable tile; Clyde patrols when close to the player.
      if (this.id === 'PINKY') {
        const [dx, dy] = DIRECTIONS[game.player.direction];
        for (let n = 3; n > 0; n--) {
          if (game.maze.walkable(target.x + dx * n, target.y + dy * n)) {
            target = { x: target.x + dx * n, y: target.y + dy * n }; break;
          }
        }
      }
      if (this.id === 'CLYDE' && Math.abs(this.x - target.x) + Math.abs(this.y - target.y) < 6) target = { x: 1, y: 19 };
      if (this.id === 'INKY' && Math.floor(game.elapsed / 8) % 2 === 0) target = { x: 19, y: 1 };
      const distances = game.maze.distances(target);
      options.sort((a, b) => {
        const difference = (distances.get(key(a.x, a.y)) ?? 999) - (distances.get(key(b.x, b.y)) ?? 999);
        return game.powered ? -difference : difference;
      });
      if (options[0]) this.move(options[0]);
    }
  }

  class PacmanGame {
    constructor({ playerId = uuid(), onEvent = () => {}, now = Date.now, makeId = uuid } = {}) {
      Object.assign(this, { playerId, onEvent, now, makeId });
      this.matchId = makeId();
      this.maze = new Maze();
      this.player = new Actor(10, 13);
      this.ghosts = [new Ghost('BLINKY', '#ff6b7d', 10, 9, 2), new Ghost('PINKY', '#f49bd5', 9, 9, 5),
        new Ghost('INKY', '#42d8ef', 11, 9, 8), new Ghost('CLYDE', '#ffad57', 10, 8, 11)];
      this.state = 'ready';
      this.score = 0; this.lives = 3; this.elapsed = 0; this.events = [];
      this.playerClock = 0; this.ghostClock = 0; this.respawnTime = 0;
      this.nextDirection = 'left'; this.powerUntil = 0; this.powerEvent = null; this.eaten = new Set();
      this.lastTimestamp = 0;
    }
    get powered() { return !!this.powerEvent && Math.max(this.lastTimestamp, this.now()) < this.powerUntil; }
    emit(type, data, timestamp = this.now()) {
      this.lastTimestamp = Math.max(this.lastTimestamp, timestamp);
      const event = { eventId: this.makeId(), timestamp: new Date(this.lastTimestamp).toISOString(),
        gameId: 'PACMAN', gameVersion: '1.0', matchId: this.matchId, sequence: this.events.length + 1,
        playerId: type === 'MATCH_STARTED' || type === 'MATCH_FINISHED' ? null : this.playerId, type, data };
      this.events.push(event); this.onEvent(event); return event;
    }
    start() {
      if (this.state !== 'ready') return;
      this.state = 'running';
      this.emit('MATCH_STARTED', { playerId: this.playerId, initialLevel: 1, initialLives: 3 });
    }
    pause() { if (this.state === 'running') this.state = 'paused'; }
    resume() { if (this.state === 'paused') this.state = 'running'; }
    steer(direction) { if (DIRECTIONS[direction]) this.nextDirection = direction; }
    finish(reason) {
      if (!['running', 'paused'].includes(this.state)) return;
      this.state = reason === 'LEVEL_CLEARED' ? 'won' : reason === 'GAME_OVER' ? 'lost' : 'finished';
      this.emit('MATCH_FINISHED', { score: this.score, reason });
    }
    clearPower() { this.powerEvent = null; this.powerUntil = 0; this.eaten.clear(); }
    collect() {
      if (this.state !== 'running') return;
      const id = key(this.player.x, this.player.y);
      const pellet = this.maze.pellets.get(id);
      if (!pellet) return;
      this.maze.pellets.delete(id);
      if (pellet === 'o') {
        this.clearPower(); this.score += 50;
        this.powerEvent = this.emit('POWER_UP_COLLECTED', { level: 1, pelletId: id, durationMs: 8000 });
        this.powerUntil = Date.parse(this.powerEvent.timestamp) + 8000;
      } else { this.score += 10; this.emit('PELLET_EATEN', { level: 1, pelletId: id }); }
      if (!this.maze.pellets.size) {
        this.emit('LEVEL_COMPLETED', { level: 1 }); this.clearPower(); this.finish('LEVEL_CLEARED');
      }
    }
    collide() {
      if (this.state !== 'running') return;
      for (const ghost of this.ghosts) {
        if (this.eaten.has(ghost.id) || ghost.x !== this.player.x || ghost.y !== this.player.y) continue;
        const timestamp = Math.max(this.lastTimestamp, this.now());
        if (this.powerEvent && timestamp < this.powerUntil) {
          this.score += 200 * (2 ** this.eaten.size); this.eaten.add(ghost.id);
          this.emit('GHOST_EATEN', { level: 1, ghostId: ghost.id, powerUpEventId: this.powerEvent.eventId }, timestamp);
        } else {
          this.lives--; this.emit('LIFE_LOST', { level: 1, cause: ghost.id, livesRemaining: this.lives });
          this.clearPower();
          if (!this.lives) { this.finish('GAME_OVER'); return; }
          this.player.reset(); this.nextDirection = 'left';
          this.ghosts.forEach(g => { g.reset(); g.delay = this.elapsed + g.homeDelay; });
          this.playerClock = 0; this.ghostClock = 0; this.respawnTime = 1.5;
          return;
        }
      }
    }
    update(dt) {
      if (this.state !== 'running' || !Number.isFinite(dt) || dt <= 0) return;
      // Small substeps detect head-on collisions, even with a slow animation frame.
      let remaining = Math.min(dt, 0.25);
      while (remaining > 0 && this.state === 'running') {
        const step = Math.min(remaining, 0.01); remaining -= step; this.elapsed += step;
        if (this.powerEvent && !this.powered) this.clearPower();
        if (this.respawnTime > 0) { this.respawnTime = Math.max(0, this.respawnTime - step); continue; }
        this.playerClock += step; this.ghostClock += step;
        if (this.playerClock >= 0.13) {
          this.playerClock -= 0.13;
          const player = this.player;
          const [nx, ny] = DIRECTIONS[this.nextDirection];
          if (this.maze.walkable(player.x + nx, player.y + ny)) player.direction = this.nextDirection;
          const [dx, dy] = DIRECTIONS[player.direction];
          if (this.maze.walkable(player.x + dx, player.y + dy)) player.move({ x: player.x + dx, y: player.y + dy });
          this.collect(); if (this.state !== 'running') return;
          this.collide(); if (this.respawnTime > 0 || this.state !== 'running') continue;
        }
        if (this.ghostClock >= (this.powered ? 0.32 : 0.23)) {
          this.ghostClock = 0;
          this.ghosts.forEach(ghost => ghost.advance(this)); this.collide();
        }
      }
    }
  }
  const api = { Maze, Actor, Ghost, PacmanGame, MAP, DIRECTIONS };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.Pacman = api;
})(globalThis);

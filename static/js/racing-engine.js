/* Circuit geometry, car physics and match rules are independent of the browser. */
(function (root) {
  'use strict';
  const clamp = (n, low, high) => Math.max(low, Math.min(high, n));
  const wrap = (n, length) => ((n % length) + length) % length;
  const angleDifference = (a, b) => Math.atan2(Math.sin(a - b), Math.cos(a - b));
  const uuid = () => globalThis.crypto.randomUUID();

  class Circuit {
    constructor() {
      this.length = 1500; this.halfWidth = 12; this.laneScale = 2.2;
      const anchors = [[190, 120], [420, 100], [570, 175], [745, 120], [815, 255],
        [745, 440], [555, 495], [400, 405], [240, 500], [100, 370], [145, 245]];
      const points = [];
      for (let i = 0; i < anchors.length; i++) {
        const p = [-1, 0, 1, 2].map(offset => anchors[wrap(i + offset, anchors.length)]);
        for (let j = 0; j < 64; j++) {
          const t = j / 64;
          const value = axis => 0.5 * ((2 * p[1][axis]) + (-p[0][axis] + p[2][axis]) * t +
            (2 * p[0][axis] - 5 * p[1][axis] + 4 * p[2][axis] - p[3][axis]) * t * t +
            (-p[0][axis] + 3 * p[1][axis] - 3 * p[2][axis] + p[3][axis]) * t * t * t);
          points.push({ x: value(0), y: value(1) });
        }
      }
      const distances = [0];
      for (let i = 1; i <= points.length; i++) {
        const a = points[i - 1], b = points[i % points.length];
        distances.push(distances[i - 1] + Math.hypot(b.x - a.x, b.y - a.y));
      }
      // Re-sample at equal distances so speed is independent of spline segments.
      const total = distances.at(-1); let index = 0;
      this.samples = Array.from({ length: 1200 }, (_, i) => {
        const distance = i / 1200 * total;
        while (distances[index + 1] < distance) index++;
        const a = points[index], b = points[(index + 1) % points.length];
        const t = (distance - distances[index]) / (distances[index + 1] - distances[index]);
        return { x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t };
      });
    }
    point(distance) {
      const index = wrap(distance, this.length) / this.length * this.samples.length;
      const a = this.samples[Math.floor(index)], b = this.samples[(Math.floor(index) + 1) % this.samples.length];
      const t = index % 1;
      return { x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t };
    }
    heading(distance) {
      const a = this.point(distance - 2), b = this.point(distance + 2);
      return Math.atan2(b.y - a.y, b.x - a.x);
    }
    curvature(distance) { return angleDifference(this.heading(distance + 12), this.heading(distance - 12)) / 24; }
    safeSpeed(distance) { return clamp(Math.sqrt(17 / Math.max(0.003, Math.abs(this.curvature(distance)))), 27, 72); }
    position(distance, lane = 0) {
      const p = this.point(distance), angle = this.heading(distance);
      return { x: p.x - Math.sin(angle) * lane * this.laneScale,
        y: p.y + Math.cos(angle) * lane * this.laneScale, angle };
    }
  }

  class RaceCar {
    constructor({ id, name, color, lane, pace = 1, human = false }) {
      Object.assign(this, { id, name, color, lane, pace, human });
      this.gridLane = lane; this.distance = 0; this.speed = 0; this.laps = [];
      this.lapClockMs = 0; this.finishTimeMs = null; this.lastLapPosition = null;
      this.bumpUntil = 0; this.collisions = 0;
    }
    get completedLaps() { return this.laps.length; }
    get finished() { return this.finishTimeMs !== null; }
    drive(dt, input, circuit, elapsed) {
      if (this.finished) return;
      const throttle = clamp(Number(input.throttle) || 0, 0, 1);
      const brake = clamp(Number(input.brake) || 0, 0, 1);
      this.speed = clamp(this.speed + (throttle * 10.5 - brake * 32 - 2.4) * dt, 0, 72);
      if (elapsed < this.bumpUntil) this.speed = Math.min(this.speed, 29);
      const steering = clamp(Number(input.steer) || 0, -1, 1);
      const safe = circuit.safeSpeed(this.distance);
      const outward = -Math.sign(circuit.curvature(this.distance));
      const drift = outward * Math.max(0, this.speed - safe) * 0.22;
      this.lane = clamp(this.lane + (steering * (2.5 + this.speed * 0.14) + drift) * dt, -22, 22);
      if (Math.abs(this.lane) > circuit.halfWidth) this.speed = Math.max(0, this.speed - 34 * dt);
      this.distance += this.speed * dt;
    }
  }

  class RivalDriver {
    constructor(car) { this.car = car; }
    input(game) {
      const car = this.car, circuit = game.circuit;
      const safe = Math.min(circuit.safeSpeed(car.distance), circuit.safeSpeed(car.distance + 45));
      let targetSpeed = Math.min(62 * car.pace, safe * car.pace);
      let targetLane = car.gridLane * 0.65 + Math.sin(car.distance / 110 + car.gridLane) * 1.5;
      for (const other of game.cars) {
        if (other === car || other.finished) continue;
        const gap = wrap(other.distance - car.distance, circuit.length);
        if (gap > 0 && gap < 22 && Math.abs(other.lane - car.lane) < 4) {
          targetLane = other.lane > 0 ? -6 : 6;
          if (gap < 10) targetSpeed = Math.min(targetSpeed, Math.max(20, other.speed - 3));
        }
      }
      const drift = -Math.sign(circuit.curvature(car.distance)) * Math.max(0, car.speed - circuit.safeSpeed(car.distance)) * 0.22;
      return { throttle: car.speed < targetSpeed ? 1 : 0.23, brake: car.speed > targetSpeed + 1 ? 0.5 : 0,
        steer: clamp(((targetLane - car.lane) * 2 - drift) / (2.5 + car.speed * 0.14), -1, 1) };
    }
  }

  class RacingGame {
    constructor({ playerId = uuid(), onEvent = () => {}, now = Date.now, makeId = uuid, plannedLaps = 3 } = {}) {
      if (!Number.isInteger(plannedLaps) || plannedLaps < 1 || plannedLaps > 10) throw Error('Invalid planned laps');
      Object.assign(this, { playerId, onEvent, now, makeId, plannedLaps });
      this.matchId = makeId(); this.circuit = new Circuit();
      this.player = new RaceCar({ id: playerId, name: 'Tú', color: '#42d8ef', lane: -9, human: true });
      this.cars = [this.player,
        new RaceCar({ id: makeId(), name: 'Vector', color: '#f49bd5', lane: -3, pace: 0.98 }),
        new RaceCar({ id: makeId(), name: 'Apex', color: '#ffc857', lane: 3, pace: 0.93 }),
        new RaceCar({ id: makeId(), name: 'Turbo', color: '#9c87ff', lane: 9, pace: 0.88 })];
      this.rivals = this.cars.slice(1).map(car => new RivalDriver(car));
      this.state = 'ready'; this.elapsed = 0; this.countdown = 3; this.events = [];
      this.input = { throttle: 0, brake: 0, steer: 0 }; this.crossings = new Map();
      this.lastTimestamp = 0; this.result = null;
    }
    emit(type, data, playerId = null) {
      this.lastTimestamp = Math.max(this.lastTimestamp, this.now());
      const event = { eventId: this.makeId(), timestamp: new Date(this.lastTimestamp).toISOString(),
        gameId: 'RACING', gameVersion: '1.0', matchId: this.matchId, sequence: this.events.length + 1,
        playerId, type, data };
      this.events.push(event); this.onEvent(event); return event;
    }
    start({ countdown = true } = {}) {
      if (this.state !== 'ready') return;
      if (countdown) this.state = 'countdown';
      else this.begin();
    }
    begin() {
      if (!['ready', 'countdown'].includes(this.state)) return;
      this.state = 'running';
      this.emit('MATCH_STARTED', { driverIds: this.cars.map(car => car.id), plannedLaps: this.plannedLaps });
    }
    setInput(input) { this.input = { throttle: 0, brake: 0, steer: 0, ...input }; }
    pause() {
      if (!['countdown', 'running', 'finishing'].includes(this.state)) return;
      this.resumeState = this.state; this.state = 'paused'; this.setInput({});
    }
    resume() { if (this.state === 'paused') { this.state = this.resumeState; this.setInput({}); } }
    abandon(reason = 'USER_QUIT') {
      if (['finished', 'abandoned'].includes(this.state)) return;
      if (!['USER_QUIT', 'RESTARTED', 'PAGE_CLOSED'].includes(reason)) throw Error('Invalid abort reason');
      this.state = 'abandoned'; this.setInput({});
      this.abortReason = reason;
      if (this.events.length) this.emit('MATCH_ABORTED', { reason });
    }
    standings() {
      return [...this.cars].sort((a, b) => {
        if (a.finished && b.finished) return a.finishTimeMs - b.finishTimeMs || a.lastLapPosition - b.lastLapPosition;
        if (a.finished !== b.finished) return a.finished ? -1 : 1;
        return b.distance - a.distance || this.cars.indexOf(a) - this.cars.indexOf(b);
      });
    }
    get playerPosition() { return this.standings().indexOf(this.player) + 1; }
    get currentLap() { return Math.min(this.player.completedLaps + 1, this.plannedLaps); }
    get lapTimeMs() { return this.player.finished ? 0 : Math.max(0, Math.round(this.elapsed * 1000) - this.player.lapClockMs); }
    checkCollisions() {
      for (let i = 0; i < this.cars.length; i++) {
        for (let j = i + 1; j < this.cars.length; j++) {
          const a = this.cars[i], b = this.cars[j];
          if (a.finished || b.finished || this.elapsed < a.bumpUntil || this.elapsed < b.bumpUntil) continue;
          const gap = Math.abs(wrap(a.distance - b.distance + this.circuit.length / 2, this.circuit.length) - this.circuit.length / 2);
          if (gap < 6 && Math.abs(a.lane - b.lane) < 3.1 && Math.max(a.speed, b.speed) > 5) {
            a.speed *= 0.65; b.speed *= 0.65;
            a.bumpUntil = b.bumpUntil = this.elapsed + 0.9; a.collisions++; b.collisions++;
            const sign = a.lane <= b.lane ? -1 : 1;
            a.lane = clamp(a.lane + sign * 1.7, -22, 22); b.lane = clamp(b.lane - sign * 1.7, -22, 22);
          }
        }
      }
    }
    step(dt) {
      if (this.state === 'countdown') {
        this.countdown = Math.max(0, this.countdown - dt);
        if (this.countdown < 0.000001) this.begin();
        return;
      }
      const previousElapsed = this.elapsed; this.elapsed += dt;
      const crossings = [];
      for (const car of this.cars) {
        if (car.finished) continue;
        const previousDistance = car.distance;
        const input = car.human ? this.input : this.rivals.find(driver => driver.car === car).input(this);
        car.drive(dt, input, this.circuit, this.elapsed);
        const nextLine = (car.completedLaps + 1) * this.circuit.length;
        if (car.distance >= nextLine) {
          const fraction = clamp((nextLine - previousDistance) / (car.distance - previousDistance), 0, 1);
          crossings.push({ car, timeMs: Math.round((previousElapsed + dt * fraction) * 1000) });
        }
      }
      crossings.sort((a, b) => a.timeMs - b.timeMs || this.cars.indexOf(a.car) - this.cars.indexOf(b.car));
      for (const { car, timeMs } of crossings) {
        const lapNumber = car.completedLaps + 1;
        const position = (this.crossings.get(lapNumber) || 0) + 1; this.crossings.set(lapNumber, position);
        const lapTimeMs = Math.max(1, timeMs - car.lapClockMs);
        car.laps.push(lapTimeMs); car.lapClockMs += lapTimeMs; car.lastLapPosition = position;
        this.emit('LAP_COMPLETED', { lapNumber, lapTimeMs, position }, car.id);
        if (car.completedLaps === this.plannedLaps) {
          car.finishTimeMs = car.lapClockMs; car.distance = this.plannedLaps * this.circuit.length; car.speed = 0;
          if (car.human) { this.state = 'finishing'; this.setInput({}); }
        }
      }
      this.checkCollisions();
      if (this.cars.every(car => car.finished)) {
        this.result = this.standings().map((car, index) => ({ playerId: car.id, position: index + 1 }));
        this.state = 'finished'; this.setInput({}); this.emit('MATCH_FINISHED', { classification: this.result });
      }
    }
    update(dt) {
      if (!['countdown', 'running', 'finishing'].includes(this.state) || !Number.isFinite(dt) || dt <= 0) return;
      let remaining = Math.min(dt, 0.25);
      while (remaining > 0.000001 && ['countdown', 'running', 'finishing'].includes(this.state)) {
        const step = Math.min(remaining, 1 / 120); this.step(step); remaining -= step;
      }
    }
  }
  const api = { Circuit, RaceCar, RivalDriver, RacingGame };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.Racing = api;
})(globalThis);

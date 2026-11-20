(function (root) {
  'use strict';
  class EventDelivery {
    constructor({ storage, storageKey = 'gameconsole.pacman.pending.v1', endpoint = '/api/arcade/events', fetcher = (...args) => fetch(...args), onChange = () => {}, schedule = (callback, delay) => globalThis.setTimeout(callback, delay) } = {}) {
      Object.assign(this, { storage, endpoint, fetcher, onChange, schedule });
      this.key = storageKey; this.queue = []; this.busy = new Set(); this.blocked = new Set();
      this.sent = 0; this.error = ''; this.persistent = Boolean(storage);
      try { this.queue = JSON.parse(storage?.getItem(this.key) || '[]'); if (!Array.isArray(this.queue)) this.queue = []; }
      catch { this.persistent = false; }
    }
    persist() {
      try { this.storage?.setItem(this.key, JSON.stringify(this.queue)); }
      catch { this.persistent = false; }
      this.onChange(this);
    }
    enqueue(event) { this.queue.push(event); this.persist(); this.flush(); }
    flush() {
      // One in-flight request per match preserves sequence; other matches run independently.
      for (const id of new Set(this.queue.map(e => e.matchId))) {
        if (!this.busy.has(id) && !this.blocked.has(id)) void this.send(id);
      }
    }
    retry() { this.blocked.clear(); this.flush(); }
    handoff(send = (url, body) => navigator.sendBeacon(url, body)) {
      // The server commits these events before acknowledging them. Duplicates are idempotent.
      let batch = [];
      const submit = () => { if (batch.length) send(`${this.endpoint}/batch`, new Blob([JSON.stringify(batch)], { type: 'application/json' })); };
      for (const event of this.queue) {
        if (new Blob([JSON.stringify([...batch, event])]).size > 48000) { submit(); batch = []; }
        batch.push(event);
      }
      submit();
    }
    async send(id) {
      this.busy.add(id);
      let transient = false;
      try {
        while (true) {
          const event = this.queue.find(e => e.matchId === id);
          if (!event) break;
          const response = await this.fetcher(this.endpoint, {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(event),
            signal: AbortSignal.timeout(8000),
          });
          const body = await response.json();
          // Go deduplicates globally. A lost acknowledgment can safely be retried with the same ID.
          if (!(response.ok && body.accepted) && !(response.status === 409 && body.code === 'DUPLICATE_EVENT')) {
            transient = response.status >= 500;
            throw new Error(body.message || body.error || 'La consola rechazó un evento. Descarga el registro para revisarlo.');
          }
          this.queue = this.queue.filter(e => e.eventId !== event.eventId);
          this.sent++; this.error = ''; this.persist();
        }
      } catch (error) {
        transient ||= error.name === 'TypeError' || error.name === 'TimeoutError' || error.name === 'AbortError';
        this.error = error.message; this.blocked.add(id); this.persist();
      } finally {
        this.busy.delete(id);
        if (transient) this.schedule(() => { this.blocked.delete(id); this.flush(); }, 5000);
      }
    }
  }

  class SimulationClock {
    constructor(step, { now = () => performance.now(), budget = 2 } = {}) {
      this.step = step; this.now = now; this.budget = budget; this.reset();
    }
    reset() { this.last = this.now(); this.debt = 0; }
    pulse() {
      const time = this.now(); this.debt += Math.max(0, (time - this.last) / 1000); this.last = time;
      let available = Math.min(this.debt, this.budget);
      while (available > 0.000001) {
        const dt = Math.min(available, 0.05); this.step(dt); available -= dt; this.debt = Math.max(0, this.debt - dt);
      }
    }
    start() { this.reset(); this.timer = globalThis.setInterval(() => this.pulse(), 50); }
    stop() { globalThis.clearInterval(this.timer); }
  }

  class DeliveryMonitor {
    constructor(onChange) { this.onChange = onChange; this.busy = false; this.last = 0; }
    async poll(matchId, force = false) {
      if (!matchId || this.busy || (!force && Date.now() - this.last < 2500)) return;
      this.busy = true; this.last = Date.now();
      try {
        const response = await fetch(`/api/arcade/partidas/${encodeURIComponent(matchId)}/envio`, { signal: AbortSignal.timeout(6000), cache: 'no-store' });
        if (response.ok) this.onChange(await response.json());
      } catch { /* The local queue retains events when the console cannot be reached. */ }
      finally { this.busy = false; }
    }
    async retry(matchId) {
      try { await fetch(`/api/arcade/partidas/${encodeURIComponent(matchId)}/reintentar`, { method: 'POST', signal: AbortSignal.timeout(6000) }); }
      catch { /* A later poll/retry can recover. */ }
      return this.poll(matchId, true);
    }
  }
  const api = { EventDelivery, SimulationClock, DeliveryMonitor };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.GameStats = api;
})(globalThis);

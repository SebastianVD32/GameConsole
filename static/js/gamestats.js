(function (root) {
  'use strict';
  class EventDelivery {
    constructor({ storage, fetcher = (...args) => fetch(...args), onChange = () => {}, schedule = setTimeout } = {}) {
      Object.assign(this, { storage, fetcher, onChange, schedule });
      this.key = 'gameconsole.pacman.pending.v1'; this.queue = []; this.busy = new Set(); this.blocked = new Set();
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
    async send(id) {
      this.busy.add(id);
      let transient = false;
      try {
        while (true) {
          const event = this.queue.find(e => e.matchId === id);
          if (!event) break;
          const response = await this.fetcher('/api/gamestats/events', {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(event),
            signal: AbortSignal.timeout(8000),
          });
          const body = await response.json();
          // Go deduplicates globally. A lost acknowledgment can safely be retried with the same ID.
          if (!(response.ok && body.accepted) && !(response.status === 409 && body.code === 'DUPLICATE_EVENT')) {
            transient = response.status >= 500;
            throw new Error(body.message || 'GameStats rechazó un evento. Descarga el registro para revisarlo.');
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
  if (typeof module !== 'undefined' && module.exports) module.exports = { EventDelivery };
  else root.GameStats = { EventDelivery };
})(globalThis);

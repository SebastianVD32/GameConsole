/* Canvas rendering and accessible controls; rules live in pacman-engine.js. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  let sessionStorageSafe;
  let playerId = crypto.randomUUID();
  try {
    sessionStorageSafe = window.sessionStorage;
    playerId = localStorage.getItem('gameconsole.player') || playerId;
    localStorage.setItem('gameconsole.player', playerId);
  } catch { /* Private browsing can disable storage; play remains available. */ }

  class PacmanRenderer {
    constructor(canvas) { this.canvas = canvas; this.ctx = canvas.getContext('2d'); this.positions = new WeakMap(); }
    draw(game, time, dt) {
      const ctx = this.ctx, tile = 30;
      ctx.clearRect(0, 0, 630, 630);
      ctx.fillStyle = '#070c15'; ctx.fillRect(0, 0, 630, 630);
      game.maze.rows.forEach((row, y) => [...row].forEach((cell, x) => {
        if (cell !== '#') return;
        ctx.fillStyle = '#17223d'; ctx.strokeStyle = '#7062b1'; ctx.lineWidth = 1.4;
        ctx.beginPath(); ctx.roundRect(x * tile + 3, y * tile + 3, 24, 24, 6); ctx.fill(); ctx.stroke();
      }));
      for (const [id, type] of game.maze.pellets) {
        const [x, y] = id.split(',').map(Number);
        ctx.beginPath(); ctx.fillStyle = type === 'o' ? '#ffc857' : '#d8ccb0';
        ctx.arc(x * tile + 15, y * tile + 15, type === 'o' ? 6 + Math.sin(time / 180) : 2.4, 0, Math.PI * 2); ctx.fill();
      }
      const position = actor => {
        let p = this.positions.get(actor) || { x: actor.x, y: actor.y };
        const distance = Math.abs(p.x - actor.x) + Math.abs(p.y - actor.y);
        const blend = distance > 2 || game.respawnTime > 0 ? 1 : 1 - Math.exp(-dt * 28);
        p = { x: p.x + (actor.x - p.x) * blend, y: p.y + (actor.y - p.y) * blend };
        this.positions.set(actor, p); return { x: p.x * tile + 15, y: p.y * tile + 15 };
      };
      for (const ghost of game.ghosts) {
        if (game.eaten.has(ghost.id)) continue;
        const p = position(ghost);
        ctx.save(); ctx.translate(p.x, p.y);
        const blinking = game.powered && game.powerUntil - game.now() < 2000 && Math.floor(time / 180) % 2;
        ctx.fillStyle = game.powered ? (blinking ? '#e8eef9' : '#5268ef') : ghost.color;
        ctx.beginPath(); ctx.arc(0, -1, 11, Math.PI, 0); ctx.lineTo(11, 11);
        for (let x = 11; x > -11; x -= 5.5) ctx.lineTo(x - 2.75, 7), ctx.lineTo(x - 5.5, 11);
        ctx.closePath(); ctx.fill();
        ctx.fillStyle = '#fff';
        [-4.5, 4.5].forEach(x => { ctx.beginPath(); ctx.ellipse(x, -1, 3.5, 4.2, 0, 0, Math.PI * 2); ctx.fill(); });
        ctx.fillStyle = '#152443'; const [dx, dy] = Pacman.DIRECTIONS[ghost.direction];
        [-4.5, 4.5].forEach(x => { ctx.beginPath(); ctx.arc(x + dx, -1 + dy, 1.8, 0, Math.PI * 2); ctx.fill(); });
        ctx.restore();
      }
      const p = position(game.player);
      ctx.save(); ctx.translate(p.x, p.y);
      ctx.rotate({ right: 0, down: Math.PI / 2, left: Math.PI, up: -Math.PI / 2 }[game.player.direction]);
      const mouth = game.state === 'running' ? 0.14 + (Math.sin(time / 65) + 1) * 0.2 : 0.28;
      ctx.fillStyle = '#ffc857'; ctx.shadowColor = '#ffc857'; ctx.shadowBlur = 12;
      ctx.beginPath(); ctx.moveTo(0, 0); ctx.arc(0, 0, 12, mouth, Math.PI * 2 - mouth); ctx.closePath(); ctx.fill(); ctx.restore();
      if (game.respawnTime > 0) {
        ctx.fillStyle = 'rgba(7,12,21,.65)'; ctx.fillRect(0, 275, 630, 70);
        ctx.fillStyle = '#ffc857'; ctx.textAlign = 'center'; ctx.font = 'bold 22px system-ui';
        ctx.fillText('¡Otra oportunidad!', 315, 318);
      }
    }
  }

  class PacmanController {
    constructor() {
      this.renderer = new PacmanRenderer($('pacman-board'));
      this.delivery = new GameStats.EventDelivery({ storage: sessionStorageSafe, onChange: delivery => this.deliveryStatus(delivery) });
      this.monitor = new GameStats.DeliveryMonitor(status => {
        if (status.matchId !== this.game.matchId) return;
        $('delivery-status').textContent = `${status.delivered} aceptados por GameStats · ${status.pending} pendientes en consola.${status.lastError ? ` ${status.lastError}` : ''}`;
        $('stats-badge').textContent = status.state === 'DELIVERED' ? 'AL DÍA' : 'PENDIENTE';
      });
      this.deliveryStatus(this.delivery);
      this.newGame(); this.bind(); this.delivery.flush(); this.pollStats();
      this.statsTimer = setInterval(() => this.pollStats(), 5000);
      this.lastFrame = performance.now(); this.lastHud = 0;
      this.clock = new GameStats.SimulationClock(dt => this.game.update(dt)); this.clock.start();
      requestAnimationFrame(time => this.frame(time));
    }
    newGame() {
      this.clock?.reset();
      this.game?.finish('RESTARTED');
      this.game = new Pacman.PacmanGame({ playerId, onEvent: event => this.delivery.enqueue(event) });
      this.lastEventCount = -1; this.refresh();
    }
    play() {
      this.clock?.reset();
      if (this.game.state === 'ready') this.game.start();
      else if (this.game.state === 'paused') this.game.resume();
      else { this.newGame(); this.game.start(); }
      this.refresh(); $('pacman-board').focus({ preventScroll: true });
    }
    togglePause() {
      this.clock?.reset();
      if (this.game.state === 'running') this.game.pause();
      else if (this.game.state === 'paused') this.game.resume();
      this.refresh();
    }
    bind() {
      $('start-game').addEventListener('click', () => this.play());
      $('pause-game').addEventListener('click', () => this.togglePause());
      $('restart-game').addEventListener('click', () => this.newGame());
      $('retry-events').addEventListener('click', () => { this.delivery.retry(); this.monitor.retry(this.game.matchId); this.pollStats(); });
      const keys = { ArrowUp: 'up', ArrowDown: 'down', ArrowLeft: 'left', ArrowRight: 'right', w: 'up', s: 'down', a: 'left', d: 'right' };
      document.addEventListener('keydown', event => {
        if (event.ctrlKey || event.metaKey || event.altKey || event.target.matches('input, textarea, select')) return;
        const key = event.key.length === 1 ? event.key.toLowerCase() : event.key;
        if (keys[key]) { event.preventDefault(); this.game.steer(keys[key]); }
        if (key === 'p' && !event.repeat) { event.preventDefault(); this.togglePause(); }
      });
      document.querySelectorAll('[data-direction]').forEach(button => {
        button.addEventListener('pointerdown', event => {
          event.preventDefault(); this.game.steer(button.dataset.direction);
        });
        button.addEventListener('click', () => this.game.steer(button.dataset.direction));
      });
      window.addEventListener('pagehide', () => { this.game.finish('PAGE_CLOSED'); this.delivery.persist(); this.delivery.handoff(); });
      window.addEventListener('pageshow', event => { if (event.persisted) this.newGame(); });
      // Warn only while an actual game or unacknowledged events would be lost.
      window.addEventListener('beforeunload', event => {
        if (['running', 'paused'].includes(this.game.state) || this.delivery.queue.length) event.preventDefault();
      });
      $('export-events').addEventListener('click', () => {
        const blob = new Blob([this.game.events.map(e => JSON.stringify(e)).join('\n') + '\n'], { type: 'application/x-ndjson' });
        const url = URL.createObjectURL(blob), link = document.createElement('a');
        link.href = url; link.download = `pacman-${this.game.matchId}.jsonl`; link.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
      });
    }
    deliveryStatus(delivery) {
      $('delivery-status').textContent = delivery.error
        ? `${delivery.queue.length} eventos pendientes. ${delivery.error}`
        : `${delivery.sent} guardados en consola · ${delivery.queue.length} pendientes de guardar.`;
      if (!delivery.persistent) $('delivery-status').textContent += ' Almacenamiento no disponible; conserva esta pestaña abierta.';
      $('stats-badge').textContent = delivery.error ? 'PENDIENTE' : delivery.queue.length ? 'ENVIANDO' : delivery.sent ? 'GUARDADO' : 'LISTO';
    }
    async pollStats() {
      if (this.polling) return;
      this.polling = true;
      try {
        const response = await fetch(`/api/gamestats/pacman/players/${encodeURIComponent(playerId)}`, { signal: AbortSignal.timeout(7000) });
        if (!response.ok) throw new Error('El historial no está disponible. Inicia GameStats para consultar tus resultados.');
        const data = await response.json();
        $('stats-matches').textContent = data.completedMatches;
        $('stats-best').textContent = data.bestScore === null ? '—' : data.bestScore.toLocaleString('es');
        $('stats-status').textContent = 'Historial consultado en GameStats. Se actualiza después de terminar cada partida.';
      } catch (error) { $('stats-status').textContent = error.message; }
      finally { this.polling = false; }
    }
    refresh() {
      const game = this.game;
      const states = { ready: 'Listo para jugar', running: 'En juego', paused: 'En pausa', won: 'Nivel completado', lost: 'Sin vidas', finished: 'Finalizada' };
      $('match-status').textContent = states[game.state];
      $('match-label').textContent = `PA-${game.matchId.slice(0, 8)}`;
      $('match-label').title = game.matchId;
      $('pac-score').textContent = game.score.toLocaleString('es'); $('pac-lives').textContent = game.lives;
      $('pac-pellets').textContent = game.maze.pellets.size;
      $('pac-time').textContent = `${Math.floor(game.elapsed / 60).toString().padStart(2, '0')}:${Math.floor(game.elapsed % 60).toString().padStart(2, '0')}`;
      $('pause-game').disabled = !['running', 'paused'].includes(game.state);
      $('pause-game').textContent = game.state === 'paused' ? '▶ Continuar' : 'Ⅱ Pausar';
      $('export-events').disabled = !game.events.length;
      $('event-count').textContent = game.events.length;
      const power = game.powered ? Math.max(0, (game.powerUntil - game.now()) / 1000) : 0;
      $('power-progress').value = power;
      $('power-label').textContent = power ? `Poder activo · ${power.toFixed(1)} s` : 'Recoge un poder para atrapar fantasmas';
      $('game-overlay').hidden = game.state === 'running';
      const overlays = {
        ready: ['El laberinto te espera', 'Recoge todas las pastillas. Los poderes te permiten atrapar fantasmas durante 8 segundos.', 'Jugar ahora →'],
        paused: ['Un respiro', 'La partida está pausada. Los poderes vencen a los 8 segundos reales, incluso en pausa.', 'Continuar →'],
        won: ['¡Laberinto completado!', `Terminaste el nivel con ${game.score} puntos y ${game.lives} vidas.`, 'Volver a jugar →'],
        lost: ['Se acabaron las vidas', `Conseguiste ${game.score} puntos. ¡El próximo intento puede ser mejor!`, 'Volver a jugar →'],
        finished: ['Partida finalizada', 'Puedes iniciar otra partida con un identificador nuevo.', 'Volver a jugar →'],
      };
      if (overlays[game.state]) {
        const [title, description, action] = overlays[game.state];
        $('overlay-title').textContent = title; $('overlay-description').textContent = description; $('start-game').textContent = action;
      }
      if (this.lastEventCount !== game.events.length) {
        this.lastEventCount = game.events.length;
        if (game.events.length) $('pac-events').replaceChildren(...game.events.slice(-4).reverse().map(event => {
          const li = document.createElement('li'), dot = document.createElement('i'), text = document.createElement('span');
          const code = document.createElement('code'), small = document.createElement('small');
          code.textContent = event.type; small.textContent = `#${event.sequence} · ${new Date(event.timestamp).toLocaleTimeString('es')}`;
          text.append(code, small); li.append(dot, text); return li;
        }));
        else $('pac-events').replaceChildren();
      }
    }
    frame(time) {
      const dt = Math.min((time - this.lastFrame) / 1000, 0.1); this.lastFrame = time;
      this.renderer.draw(this.game, time, dt);
      if (time - this.lastHud > 80) { this.refresh(); this.lastHud = time; void this.monitor.poll(this.game.matchId); }
      requestAnimationFrame(next => this.frame(next));
    }
  }
  new PacmanController();
})();

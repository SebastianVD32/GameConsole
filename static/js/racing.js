(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const text = (id, value) => { if ($(id).textContent !== String(value)) $(id).textContent = value; };
  const formatTime = ms => {
    const tenths = Math.floor(Math.max(0, ms) / 100);
    return `${String(Math.floor(tenths / 600)).padStart(2, '0')}:${String(Math.floor(tenths / 10) % 60).padStart(2, '0')}.${tenths % 10}`;
  };
  let storage, playerId = crypto.randomUUID();
  try {
    storage = sessionStorage;
    playerId = localStorage.getItem('gameconsole.player') || playerId;
    localStorage.setItem('gameconsole.player', playerId);
  } catch { /* Racing remains available when browser storage is disabled. */ }

  class CircuitRenderer {
    constructor(canvas, circuit) {
      this.canvas = canvas; this.ctx = canvas.getContext('2d');
      this.background = document.createElement('canvas'); this.background.width = 900; this.background.height = 620;
      const ctx = this.background.getContext('2d');
      ctx.fillStyle = '#0a191c'; ctx.fillRect(0, 0, 900, 620);
      ctx.fillStyle = '#163034';
      for (let x = 12; x < 900; x += 20) for (let y = 12; y < 620; y += 20) ctx.fillRect(x, y, 1, 1);
      const path = () => {
        ctx.beginPath(); circuit.samples.forEach((p, i) => i ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y)); ctx.closePath();
      };
      ctx.lineJoin = 'round'; ctx.lineCap = 'round';
      [[93, '#10272a'], [77, '#d5ddd8'], [69, '#20474b'], [59, '#25313f']].forEach(([width, color]) => {
        ctx.lineWidth = width; ctx.strokeStyle = color; path(); ctx.stroke();
      });
      ctx.setLineDash([13, 16]); ctx.lineWidth = 72; ctx.strokeStyle = '#b24c5b'; path(); ctx.stroke();
      ctx.setLineDash([]); ctx.lineWidth = 59; ctx.strokeStyle = '#25313f'; path(); ctx.stroke();
      ctx.lineWidth = 1.5; ctx.strokeStyle = '#8093a25c'; ctx.setLineDash([10, 14]); path(); ctx.stroke(); ctx.setLineDash([]);
      const start = circuit.position(0);
      ctx.save(); ctx.translate(start.x, start.y); ctx.rotate(start.angle);
      for (let row = 0; row < 2; row++) for (let col = 0; col < 10; col++) {
        ctx.fillStyle = (row + col) % 2 ? '#17222d' : '#f0f5f6'; ctx.fillRect(row * 6 - 6, col * 6 - 30, 6, 6);
      }
      ctx.fillStyle = '#42d8ef'; ctx.font = '11px monospace'; ctx.textAlign = 'center'; ctx.fillText('META', 0, -48); ctx.restore();
      ctx.textAlign = 'center'; ctx.fillStyle = '#42d8ef'; ctx.font = 'bold 24px system-ui'; ctx.fillText('CIRCUITO NEÓN', 456, 291);
      ctx.fillStyle = '#688c91'; ctx.font = '12px monospace'; ctx.fillText('1.500 m  /  3 VUELTAS', 456, 316);
      ctx.strokeStyle = '#42d8ef33'; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(345, 337); ctx.lineTo(567, 337); ctx.stroke();
      ctx.fillStyle = '#42666b'; ctx.font = '10px monospace'; ctx.fillText('GAMECONSOLE  MOTORSPORT', 456, 359);
    }
    draw(game, time) {
      const ctx = this.ctx; ctx.drawImage(this.background, 0, 0);
      // Finished cars park in the infield instead of covering the finish line.
      for (const [index, car] of game.cars.entries()) {
        const position = car.finished ? { x: 393 + index * 42, y: 240, angle: -Math.PI / 2 } : game.circuit.position(car.distance, car.lane);
        if (car.human) {
          ctx.strokeStyle = '#42d8ef66'; ctx.lineWidth = 1.4; ctx.beginPath(); ctx.arc(position.x, position.y, 21, 0, Math.PI * 2); ctx.stroke();
          ctx.fillStyle = '#a5f4ff'; ctx.textAlign = 'center'; ctx.font = 'bold 10px system-ui'; ctx.fillText('TÚ', position.x, position.y - 28);
        }
        ctx.save(); ctx.translate(position.x, position.y); ctx.rotate(position.angle + Math.PI / 2);
        ctx.shadowColor = car.color; ctx.shadowBlur = car.human ? 14 : 5;
        ctx.fillStyle = '#05090d'; [[-9, -8], [5, -8], [-9, 7], [5, 7]].forEach(([x, y]) => ctx.fillRect(x, y, 4, 6));
        ctx.fillStyle = car.color; ctx.beginPath(); ctx.roundRect(-6.5, -15, 13, 29, 4); ctx.fill(); ctx.shadowBlur = 0;
        ctx.fillStyle = '#112533'; ctx.fillRect(-4.5, -7, 9, 7); ctx.fillRect(-4.5, 5, 9, 5);
        ctx.fillStyle = '#f3ffff'; ctx.fillRect(-5, -13, 3, 2); ctx.fillRect(2, -13, 3, 2);
        ctx.fillStyle = '#fd7d86'; ctx.fillRect(-5, 12, 3, 2); ctx.fillRect(2, 12, 3, 2);
        ctx.restore();
      }
      const lights = game.state === 'countdown' ? Math.ceil(game.countdown) : 0;
      if (lights) {
        ctx.fillStyle = '#091118dd'; ctx.fillRect(365, 30, 170, 36);
        for (let i = 0; i < 3; i++) {
          ctx.fillStyle = i < 4 - lights ? '#ff6b7d' : '#293440';
          ctx.beginPath(); ctx.arc(400 + i * 50, 48, 9, 0, Math.PI * 2); ctx.fill();
        }
      }
      if (game.player.bumpUntil > game.elapsed && Math.floor(time / 130) % 2) {
        ctx.strokeStyle = '#ffc857'; ctx.lineWidth = 4; ctx.strokeRect(2, 2, 896, 616);
      }
    }
  }

  class RacingController {
    constructor() {
      this.keys = new Set(); this.touch = new Map(); this.statsFor = null; this.lastStats = 0;
      this.delivery = new GameStats.EventDelivery({ storage, storageKey: 'gameconsole.racing.pending.v1', onChange: delivery => this.deliveryStatus(delivery) });
      this.monitor = new GameStats.DeliveryMonitor(status => {
        if (status.matchId !== this.game.matchId) return;
        text('race-delivery', `${status.delivered} aceptados por GameStats · ${status.pending} pendientes en consola.${status.lastError ? ` ${status.lastError}` : ''}`);
        text('race-sync', status.state === 'DELIVERED' ? 'AL DÍA' : 'PENDIENTE');
      });
      this.deliveryStatus(this.delivery); this.newGame(); this.bind(); this.delivery.flush();
      this.lastFrame = performance.now(); this.lastHud = 0;
      this.clock = new GameStats.SimulationClock(dt => { this.readInput(); this.game.update(dt); }); this.clock.start();
      requestAnimationFrame(time => this.frame(time));
    }
    clearInput() { this.keys.clear(); this.touch.clear(); this.game?.setInput({}); }
    newGame() {
      this.clock?.reset();
      const interrupted = this.game?.events.length && !['finished', 'abandoned'].includes(this.game.state);
      this.game?.abandon('RESTARTED'); this.clearInput();
      this.game = new Racing.RacingGame({ playerId, onEvent: event => this.delivery.enqueue(event) });
      this.renderer = new CircuitRenderer($('racing-board'), this.game.circuit);
      this.statsFor = null; this.lastStats = 0; this.lastEventCount = -1;
      this.standingRows = this.game.cars.map(car => {
        const li = document.createElement('li'), position = document.createElement('strong'), dot = document.createElement('i');
        const name = document.createElement('span'), detail = document.createElement('small');
        dot.style.background = car.color; name.textContent = car.name; li.append(position, dot, name, detail);
        li.classList.toggle('is-player', car.human); return { car, li, position, detail };
      });
      text('race-best-official', '—'); text('race-position-official', '—');
      text('race-analytics-status', 'GameStats procesa el resultado cuando todos completan las tres vueltas.');
      this.refresh();
      if (interrupted) showToast('Carrera anterior abortada. Su cierre se enviará a GameStats.');
    }
    play() {
      this.clock?.reset();
      if (this.game.state === 'paused') this.game.resume();
      else { if (this.game.state !== 'ready') this.newGame(); this.game.start(); }
      this.clearInput(); this.refresh(); $('racing-board').focus({ preventScroll: true });
    }
    pause() {
      this.clock?.reset();
      if (this.game.state === 'paused') this.game.resume(); else this.game.pause();
      this.clearInput(); this.refresh();
    }
    bind() {
      $('race-start').addEventListener('click', () => this.play());
      $('race-pause').addEventListener('click', () => this.pause());
      $('race-restart').addEventListener('click', () => this.newGame());
      $('race-abort').addEventListener('click', () => { this.game.abandon('USER_QUIT'); this.clearInput(); this.refresh(); });
      $('race-retry').addEventListener('click', () => { this.delivery.retry(); this.monitor.retry(this.game.matchId); this.pollResult(true); });
      const keys = { ArrowUp: 'throttle', w: 'throttle', ArrowDown: 'brake', s: 'brake', ArrowLeft: 'left', a: 'left', ArrowRight: 'right', d: 'right' };
      const keyName = event => event.key.length === 1 ? event.key.toLowerCase() : event.key;
      document.addEventListener('keydown', event => {
        if (event.ctrlKey || event.altKey || event.metaKey || event.target.matches('input, textarea, select')) return;
        const key = keyName(event);
        if (keys[key]) { event.preventDefault(); this.keys.add(key); }
        if (key === 'p' && !event.repeat) { event.preventDefault(); this.pause(); }
      });
      document.addEventListener('keyup', event => this.keys.delete(keyName(event)));
      document.querySelectorAll('[data-drive]').forEach(button => {
        button.addEventListener('pointerdown', event => {
          if (event.pointerType === 'mouse' && event.button !== 0) return;
          event.preventDefault(); button.setPointerCapture(event.pointerId); this.touch.set(event.pointerId, button.dataset.drive);
        });
        const release = event => this.touch.delete(event.pointerId);
        button.addEventListener('pointerup', release); button.addEventListener('pointercancel', release); button.addEventListener('lostpointercapture', release);
        button.addEventListener('keydown', event => {
          if (event.key === ' ' || event.key === 'Enter') { event.preventDefault(); this.keys.add(`button-${button.dataset.drive}`); }
        });
        button.addEventListener('keyup', event => {
          if (event.key === ' ' || event.key === 'Enter') this.keys.delete(`button-${button.dataset.drive}`);
        });
        button.addEventListener('blur', () => this.keys.delete(`button-${button.dataset.drive}`));
      });
      this.controls = keys;
      window.addEventListener('blur', () => this.clearInput());
      document.addEventListener('visibilitychange', () => { if (document.hidden) this.clearInput(); });
      window.addEventListener('pagehide', () => { this.game.abandon('PAGE_CLOSED'); this.clearInput(); this.delivery.persist(); this.delivery.handoff(); });
      window.addEventListener('pageshow', event => { if (event.persisted) this.newGame(); });
      $('race-export').addEventListener('click', () => {
        const blob = new Blob([this.game.events.map(e => JSON.stringify(e)).join('\n') + '\n'], { type: 'application/x-ndjson' });
        const url = URL.createObjectURL(blob), a = document.createElement('a');
        a.href = url; a.download = `racing-${this.game.matchId}.jsonl`; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
      });
    }
    readInput() {
      const held = new Set([...this.keys].map(key => key.startsWith('button-') ? key.slice(7) : this.controls[key]));
      this.touch.forEach(control => held.add(control));
      const input = { throttle: held.has('throttle') ? 1 : 0, brake: held.has('brake') ? 1 : 0,
        steer: Number(held.has('right')) - Number(held.has('left')) };
      this.game.setInput(input);
      document.querySelectorAll('[data-drive]').forEach(button => button.classList.toggle('is-held', held.has(button.dataset.drive)));
    }
    deliveryStatus(delivery) {
      text('race-delivery', delivery.error ? `${delivery.queue.length} pendientes. ${delivery.error}` : `${delivery.sent} guardados en consola · ${delivery.queue.length} pendientes de guardar.`);
      if (!delivery.persistent) text('race-delivery', $('race-delivery').textContent + ' Sin almacenamiento; conserva esta pestaña abierta.');
      text('race-sync', delivery.error ? 'PENDIENTE' : delivery.queue.length ? 'ENVIANDO' : delivery.sent ? 'GUARDADO' : 'LISTO');
    }
    async pollResult(force = false) {
      const game = this.game;
      if (!['finished', 'abandoned'].includes(game.state) || !game.events.length || this.polling || this.statsFor === game.matchId || (!force && Date.now() - this.lastStats < 5000)) return;
      this.polling = true; this.lastStats = Date.now();
      try {
        const response = await fetch(`/api/gamestats/matches/${encodeURIComponent(game.matchId)}`, { signal: AbortSignal.timeout(7000) });
        if (this.game !== game) return;
        if (response.status === 404) { text('race-analytics-status', 'Esperando a que GameStats procese el cierre de la carrera…'); return; }
        if (!response.ok) throw Error('Resultado oficial no disponible. Inicia GameStats y reintenta la conexión.');
        const result = await response.json();
        if (this.game !== game) return;
        if (result.status === 'ABORTED' && result.gameId === 'RACING' && result.matchId === game.matchId) {
          const reasons = { USER_QUIT: 'retiro voluntario', RESTARTED: 'reinicio', PAGE_CLOSED: 'cierre de pestaña' };
          text('race-best-official', '—'); text('race-position-official', '—');
          text('race-analytics-status', `GameStats procesó el abandono por ${reasons[result.reason] || result.reason}. Sin ganador ni clasificación.`);
          this.statsFor = game.matchId; return;
        }
        const own = result.drivers?.find(driver => driver.playerId === game.playerId);
        if (!own || result.gameId !== 'RACING' || result.matchId !== game.matchId) throw Error('GameStats devolvió un resultado inesperado.');
        text('race-best-official', formatTime(own.bestLapTimeMs)); text('race-position-official', `${own.finalPosition}º`);
        text('race-analytics-status', 'Resultado recibido directamente del analizador Scala de GameStats.'); this.statsFor = game.matchId;
      } catch (error) { if (this.game === game) text('race-analytics-status', error.message); }
      finally { this.polling = false; }
    }
    refresh() {
      const game = this.game, player = game.player;
      const states = { ready: 'En parrilla', countdown: 'Preparados', running: 'En carrera', paused: 'En pausa', finishing: 'Esperando rivales', finished: 'Bandera a cuadros', abandoned: 'Interrumpida' };
      text('race-status', states[game.state]); text('race-match', `CA-${game.matchId.slice(0, 8)}`); $('race-match').title = game.matchId;
      text('race-speed', Math.round(player.speed * 3.6)); text('race-lap', `${game.currentLap} / ${game.plannedLaps}`);
      text('race-position', `${game.playerPosition} / ${game.cars.length}`); text('race-clock', formatTime(player.finishTimeMs ?? game.elapsed * 1000));
      text('race-lap-time', formatTime(game.lapTimeMs)); text('race-last-lap', player.laps.length ? formatTime(player.laps.at(-1)) : '—');
      const progress = Math.min(100, player.distance / (game.circuit.length * game.plannedLaps) * 100);
      $('race-progress').value = progress; text('race-progress-label', `${Math.floor(progress)} % de carrera`);
      const active = ['countdown', 'running', 'paused', 'finishing'].includes(game.state);
      $('race-pause').disabled = !active; text('race-pause', game.state === 'paused' ? '▶ Continuar' : 'Ⅱ Pausar');
      $('race-abort').disabled = !active;
      $('race-export').disabled = !game.events.length;
      let feedback = 'Mantén ↑ o W para acelerar.';
      if (game.state === 'paused') feedback = 'Partida pausada. Continúa cuando estés listo.';
      else if (game.state === 'abandoned') feedback = 'Carrera abortada. GameStats conserva el progreso sin asignar un ganador.';
      else if (game.state === 'finished') feedback = `Carrera terminada: ${game.playerPosition}º puesto.`;
      else if (player.finished) feedback = 'Ya cruzaste la meta. Los demás pilotos siguen en carrera.';
      else if (Math.abs(player.lane) > game.circuit.halfWidth) feedback = 'Fuera de pista. Vuelve hacia el centro para recuperar velocidad.';
      else if (player.bumpUntil > game.elapsed) feedback = 'Contacto: velocidad reducida.';
      else if (player.speed > game.circuit.safeSpeed(player.distance + 35)) feedback = 'Curva cerrada: frena para evitar salirte.';
      else if (game.state === 'running' && player.speed > 5) feedback = 'Mantén tu carril y busca espacio para adelantar.';
      text('race-feedback', feedback);
      const overlay = ['ready', 'paused', 'finished', 'abandoned', 'countdown'].includes(game.state);
      $('race-overlay').hidden = !overlay; $('race-overlay').classList.toggle('is-countdown', game.state === 'countdown');
      $('race-start').hidden = game.state === 'countdown';
      const overlays = {
        ready: ['Tu lugar en la parrilla', 'Domina las curvas, adelanta a tus rivales y completa tres vueltas. Tu automóvil es el cian.', 'Encender motores →'],
        countdown: [String(Math.max(1, Math.ceil(game.countdown))), 'Prepárate. Mantén ↑ o W para acelerar al apagarse las luces.', ''],
        paused: ['Una parada en el camino', 'La carrera y el cronómetro están pausados.', 'Continuar →'],
        finished: [game.playerPosition === 1 ? '¡Lo más alto del podio!' : `Llegaste en ${game.playerPosition}º lugar`,
          `Tres vueltas en ${formatTime(player.finishTimeMs)}. ${game.playerPosition === 1 ? 'El circuito es tuyo.' : 'Cada curva es una nueva oportunidad.'}`, 'Volver a correr →'],
        abandoned: ['Carrera abortada', 'El progreso se envía a GameStats. Este cierre no cuenta como una carrera completada ni asigna ganador.', 'Nueva carrera →'],
      };
      if (overlays[game.state]) {
        const [title, description, action] = overlays[game.state];
        text('race-overlay-title', title); text('race-overlay-description', description); text('race-start', action);
      }
      const ordered = game.standings();
      ordered.forEach((car, i) => {
        const row = this.standingRows.find(row => row.car === car);
        row.position.textContent = `${i + 1}`;
        row.detail.textContent = car.finished ? formatTime(car.finishTimeMs) : `${car.completedLaps}/${game.plannedLaps} v.`;
      });
      const nodes = ordered.map(car => this.standingRows.find(row => row.car === car).li);
      if (nodes.some((node, i) => $('race-standings').children[i] !== node)) $('race-standings').replaceChildren(...nodes);
      if (this.lastEventCount !== game.events.length) {
        this.lastEventCount = game.events.length; text('race-event-count', `${game.events.length} eventos`);
        $('race-events').replaceChildren(...game.events.slice(-4).reverse().map(event => {
          const li = document.createElement('li'), dot = document.createElement('i'), span = document.createElement('span');
          const code = document.createElement('code'), small = document.createElement('small'); code.textContent = event.type;
          const driver = game.cars.find(car => car.id === event.playerId);
          small.textContent = `#${event.sequence}${driver ? ` · ${driver.name} · vuelta ${event.data.lapNumber}` : ' · Carrera'}`;
          span.append(code, small); li.append(dot, span); return li;
        }));
      }
    }
    frame(time) {
      this.renderer.draw(this.game, time);
      if (time - this.lastHud > 80) { this.refresh(); this.lastHud = time; void this.pollResult(); void this.monitor.poll(this.game.matchId); }
      requestAnimationFrame(next => this.frame(next));
    }
  }
  new RacingController();
})();

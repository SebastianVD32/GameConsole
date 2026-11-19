// Cliente del ajedrez: dibuja el estado que entrega el servidor y envía jugadas.
// Las reglas viven en el servidor (Python) y la IA en Prolog; aquí solo hay presentación.
(() => {
  const FILES = 'abcdefgh';
  const api = (path, options = {}) => fetch(`/api/ajedrez/partidas${path}`, {
    headers: { 'Content-Type': 'application/json' }, cache: 'no-store', ...options,
  });
  const $ = (selector, root = document) => root.querySelector(selector);

  const els = {
    setup: $('[data-chess-setup]'), setupError: $('[data-setup-error]'), game: $('[data-chess-game]'),
    board: $('[data-board]'), status: $('[data-chess-status]'), id: $('[data-chess-id]'),
    matchLabel: $('[data-chess-match]'), delivery: $('[data-chess-delivery]'), resign: $('[data-action="resign"]'),
    result: $('[data-result]'), promotion: $('[data-promotion]'), moves: $('[data-moves]'),
    moveCount: $('[data-move-count]'), events: $('[data-events]'), gsResult: $('[data-gs-result]'),
  };

  let matchId = new URLSearchParams(window.location.search).get('partida');
  let state = null;
  let fetchedAt = 0;
  let selected = null;
  let pendingPromotion = null;
  let pollTimer = null;
  let resultLoaded = false;
  let busy = false;

  const squareName = (i) => `${FILES[i % 8]}${Math.floor(i / 8) + 1}`;
  const squareIndex = (name) => (Number(name[1]) - 1) * 8 + FILES.indexOf(name[0]);
  const fmtClock = (ms) => {
    const total = Math.max(0, Math.ceil(ms / 1000));
    return `${String(Math.floor(total / 60)).padStart(2, '0')}:${String(total % 60).padStart(2, '0')}`;
  };
  const toast = (message) => {
    const el = $('#toast'); if (!el) return;
    el.textContent = message; el.classList.add('is-visible');
    window.clearTimeout(el._timer); el._timer = window.setTimeout(() => el.classList.remove('is-visible'), 2600);
  };

  // ------------------------------------------------------------------ creación
  els.setup.addEventListener('submit', async (event) => {
    event.preventDefault();
    const form = new FormData(els.setup);
    const button = els.setup.querySelector('button[type="submit"]');
    button.disabled = true; els.setupError.hidden = true;
    try {
      const response = await api('', {
        method: 'POST',
        body: JSON.stringify({
          name: form.get('name'), color: form.get('color'),
          depth: Number(form.get('depth')), control: form.get('control'),
        }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'No se pudo crear la partida');
      matchId = data.matchId;
      const url = new URL(window.location.href); url.searchParams.set('partida', matchId);
      window.history.replaceState({}, '', url);
      apply(data);
    } catch (error) {
      els.setupError.textContent = error.message; els.setupError.hidden = false;
    } finally {
      button.disabled = false;
    }
  });

  // ------------------------------------------------------------------ sondeo
  async function poll() {
    window.clearTimeout(pollTimer);
    if (!matchId) return;
    try {
      const response = await api(`/${encodeURIComponent(matchId)}`);
      if (response.status === 404) {
        toast('La partida no existe en esta consola. Inicia una nueva.');
        matchId = null; showSetup(); return;
      }
      apply(await response.json());
    } catch (error) {
      els.status.lastChild.textContent = 'Sin conexión';
    }
    schedule();
  }

  function schedule() {
    window.clearTimeout(pollTimer);
    if (!state) return;
    if (state.finished) {
      if (!resultLoaded) pollTimer = window.setTimeout(loadResult, 1500);
      return;
    }
    const aiTurn = state.ai.thinking || state.turn !== state.orientation;
    pollTimer = window.setTimeout(poll, aiTurn ? 400 : 1200);
  }

  async function loadResult() {
    // Resultado calculado por GameStats (Scala) para esta partida.
    try {
      const statusResponse = await api(`/${encodeURIComponent(matchId)}`);
      if (statusResponse.ok) apply(await statusResponse.json(), false);
      const response = await fetch(`/api/estadisticas/partidas/${encodeURIComponent(matchId)}`, { cache: 'no-store' });
      if (response.ok) {
        renderGameStatsResult(await response.json());
        resultLoaded = true;
        return;
      }
    } catch (error) { /* se reintenta */ }
    pollTimer = window.setTimeout(loadResult, 2000);
  }

  // ------------------------------------------------------------------ render
  function showSetup() {
    els.setup.hidden = false; els.game.hidden = true; els.resign.disabled = true;
  }

  function apply(data, reschedule = true) {
    state = data; fetchedAt = performance.now();
    els.setup.hidden = true; els.game.hidden = false;
    els.id.textContent = `Jugador vs. IA Prolog · ${data.clock.control}`;
    els.matchLabel.textContent = data.matchId;
    els.status.lastChild.textContent = data.status;
    els.resign.disabled = data.finished;
    renderBoard(); renderPlayers(); renderMoves(); renderAi(); renderEvents(); renderResult();
    if (reschedule) schedule();
  }

  function orderedSquares() {
    const order = [];
    const whiteBottom = state.orientation === 'WHITE';
    for (let row = 0; row < 8; row += 1) {
      const rank = whiteBottom ? 7 - row : row;
      for (let col = 0; col < 8; col += 1) order.push(rank * 8 + (whiteBottom ? col : 7 - col));
    }
    return order;
  }

  function movesFrom(square) {
    return state.legalMoves.filter((m) => m.from === square);
  }

  function renderBoard() {
    const targets = new Set(selected ? movesFrom(selected).map((m) => m.to) : []);
    const fragment = document.createDocumentFragment();
    orderedSquares().forEach((index, position) => {
      const name = squareName(index);
      const piece = state.board[index];
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'square';
      const dark = (Math.floor(index / 8) + (index % 8)) % 2 === 0;
      button.classList.add(dark ? 'is-dark' : 'is-light');
      if (piece) {
        button.textContent = piece.glyph;
        button.classList.add(piece.color === 'WHITE' ? 'piece-white' : 'piece-black');
      }
      if (state.lastMove && (state.lastMove.from === name || state.lastMove.to === name)) button.classList.add('is-last');
      if (state.check === name) button.classList.add('is-check');
      if (selected === name) button.classList.add('is-selected');
      if (targets.has(name)) button.classList.add(piece ? 'is-capture' : 'is-target');
      button.dataset.square = name;
      button.setAttribute('aria-label', `${name}${piece ? ` ${piece.kind} ${piece.color}` : ''}`);
      if (position % 8 === 0) button.dataset.rank = name[1];
      if (position >= 56) button.dataset.file = name[0];
      fragment.append(button);
    });
    els.board.replaceChildren(fragment);
  }

  function renderPlayers() {
    const human = state.players.find((p) => !p.automated);
    const computer = state.players.find((p) => p.automated);
    const fill = (slot, player) => {
      const bar = $(`[data-player="${slot}"]`);
      $('[data-name]', bar).textContent = player.name;
      $('[data-detail]', bar).textContent = `${player.color === 'WHITE' ? 'Blancas' : 'Negras'} · ${player.playerId}`;
      bar.classList.toggle('is-turn', !state.finished && state.turn === player.color);
      bar.dataset.color = player.color;
    };
    fill('top', computer); fill('bottom', human);
    $('[data-captured="top"]').textContent = (state.captured[computer.color] || []).join(' ');
    $('[data-captured="bottom"]').textContent = (state.captured[human.color] || []).join(' ');
    tickClocks();
  }

  function tickClocks() {
    if (!state) return;
    const elapsed = performance.now() - fetchedAt;
    document.querySelectorAll('[data-player]').forEach((bar) => {
      const color = bar.dataset.color;
      let ms = state.clock[color];
      if (!state.finished && state.clock.running === color) ms -= elapsed;
      const clock = $('[data-clock]', bar);
      clock.textContent = fmtClock(ms);
      clock.classList.toggle('is-low', ms < 30000);
    });
  }

  function renderMoves() {
    els.moveCount.textContent = state.history.length;
    const items = [];
    for (let i = 0; i < state.history.length; i += 2) {
      const li = document.createElement('li');
      const white = state.history[i]; const black = state.history[i + 1];
      li.innerHTML = '<b></b><span></span><span></span>';
      li.children[0].textContent = `${i / 2 + 1}.`;
      li.children[1].textContent = white.san + (white.byComputer ? ' ⚙' : '');
      li.children[2].textContent = black ? black.san + (black.byComputer ? ' ⚙' : '') : '';
      items.push(li);
    }
    els.moves.replaceChildren(...items);
    els.moves.scrollTop = els.moves.scrollHeight;
  }

  function renderAi() {
    const ai = state.ai; const d = ai.lastDecision;
    $('[data-ai-badge]').textContent = ai.thinking ? 'PENSANDO' : ai.error ? 'ERROR' : 'IDLE';
    $('[data-ai="move"]').textContent = d ? d.move : '—';
    $('[data-ai="score"]').textContent = d ? (d.score > 0 ? `+${d.score}` : d.score) : '—';
    $('[data-ai="nodes"]').textContent = d ? d.nodes.toLocaleString('es-CR') : '—';
    $('[data-ai="depth"]').textContent = `profundidad ${ai.depth}`;
    $('[data-ai="time"]').textContent = d ? `${d.thinkMs} ms` : '—';
    if (ai.error) toast(`Motor Prolog: ${ai.error}`);
  }

  function renderEvents() {
    const delivery = state.delivery || {};
    $('[data-gs="emitted"]').textContent = state.events.emitted;
    $('[data-gs="delivered"]').textContent = delivery.delivered ?? 0;
    $('[data-gs="pending"]').textContent = `${delivery.pending ?? 0} pendientes`;
    const labels = { OK: 'Sincronizado', RETRYING: 'Reintentando', RESYNCING: 'Re-sincronizando', REJECTED: 'Rechazado', DISABLED: 'Sin GameStats' };
    const label = labels[delivery.state] || 'Sincronizado';
    $('[data-gs="state"]').textContent = label;
    $('[data-gs-badge]').textContent = delivery.state === 'OK' || !delivery.state ? 'SYNC' : delivery.state;
    els.delivery.textContent = `GameStats: ${label}${delivery.lastError ? ` · ${delivery.lastError}` : ''}`;
    const items = state.events.recent.map((event) => {
      const li = document.createElement('li');
      li.innerHTML = '<i></i><span><code></code><small></small></span>';
      li.querySelector('code').textContent = `#${event.sequence} ${event.type}`;
      li.querySelector('small').textContent = `${new Date(event.timestamp).toLocaleTimeString('es-CR')} · ${event.playerId || 'partida'}`;
      return li;
    });
    els.events.replaceChildren(...items);
  }

  function renderResult() {
    if (!state.result) { els.result.hidden = true; return; }
    const r = state.result;
    els.result.hidden = false;
    els.result.textContent = `${r.detail}${r.winnerName ? ` · gana ${r.winnerName}` : ''}`;
  }

  function renderGameStatsResult(result) {
    const rows = [
      ['Motivo', result.reason], ['Duración', `${(result.durationMs / 1000).toFixed(1)} s`],
      ['Movimientos', result.totalMoves], ['Capturas', result.totalCaptures],
    ];
    (result.players || []).forEach((p) => rows.push([
      p.playerId, `${p.moves} jug. · ${p.captures} capt. · ${p.averageDecisionTimeMs === null ? '—' : `${Math.round(p.averageDecisionTimeMs)} ms`}${p.timePressure ? ' · apuro de tiempo' : ''}`,
    ]));
    const title = document.createElement('strong'); title.textContent = 'Resultado calculado por GameStats';
    const list = document.createElement('dl');
    rows.forEach(([k, v]) => {
      const dt = document.createElement('dt'); dt.textContent = k;
      const dd = document.createElement('dd'); dd.textContent = v;
      list.append(dt, dd);
    });
    els.gsResult.replaceChildren(title, list);
    els.gsResult.hidden = false;
  }

  // ------------------------------------------------------------------ interacción
  els.board.addEventListener('click', (event) => {
    const button = event.target.closest('[data-square]');
    if (!button || !state || state.finished || busy) return;
    const square = button.dataset.square;
    if (selected) {
      const options = movesFrom(selected).filter((m) => m.to === square);
      if (options.length) {
        if (options.some((m) => m.promotion)) {
          pendingPromotion = { from: selected, to: square };
          els.promotion.hidden = false;
          return;
        }
        play(`${selected}${square}`);
        return;
      }
    }
    selected = movesFrom(square).length ? square : null;
    if (!state.legalMoves.length && state.board[squareIndex(square)]) toast('Espera tu turno: la IA está pensando.');
    renderBoard();
  });

  els.promotion.addEventListener('click', (event) => {
    const button = event.target.closest('[data-promo]');
    if (!button || !pendingPromotion) return;
    els.promotion.hidden = true;
    play(`${pendingPromotion.from}${pendingPromotion.to}${button.dataset.promo}`);
    pendingPromotion = null;
  });

  async function play(uci) {
    busy = true; selected = null;
    try {
      const response = await api(`/${encodeURIComponent(matchId)}/movimientos`, {
        method: 'POST', body: JSON.stringify({ move: uci }),
      });
      const data = await response.json();
      if (!response.ok) { toast(data.error || 'Movimiento rechazado'); if (data.state) apply(data.state); else renderBoard(); return; }
      apply(data);
    } finally {
      busy = false;
    }
  }

  els.resign.addEventListener('click', async () => {
    if (!matchId || !window.confirm('¿Abandonar la partida? La IA ganará por abandono.')) return;
    const response = await api(`/${encodeURIComponent(matchId)}/abandonar`, { method: 'POST' });
    const data = await response.json();
    if (response.ok) apply(data); else toast(data.error);
  });

  window.setInterval(tickClocks, 250);
  if (matchId) poll(); else showSetup();
})();

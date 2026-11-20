// Panel de estadísticas: consulta /api/estadisticas (proxy hacia GameStats) cada pocos segundos.
(() => {
  const REFRESH_MS = 2500;
  const GAME_NAMES = { CHESS: 'Ajedrez', PACMAN: 'Pac-Man', RACING: 'Carreras', BASKETBALL: 'Baloncesto' };
  const REASONS = { CHECKMATE: 'Jaque mate', RESIGNATION: 'Abandono', DRAW: 'Tablas', TIMEOUT: 'Tiempo agotado' };

  const fmtInt = (v) => (v === null || v === undefined ? '—' : Number(v).toLocaleString('es-CR'));
  const fmtDec = (v, d = 1) => (v === null || v === undefined ? '—' : Number(v).toLocaleString('es-CR', { maximumFractionDigits: d, minimumFractionDigits: d }));
  const fmtPct = (v) => (v === null || v === undefined ? 'sin partidas' : `${fmtDec(v, 1)} %`);
  function fmtDuration(ms) {
    if (ms === null || ms === undefined) return '—';
    const total = Math.round(ms / 1000);
    const h = Math.floor(total / 3600), m = Math.floor((total % 3600) / 60), s = total % 60;
    return h ? `${h}h ${String(m).padStart(2, '0')}m` : `${m}:${String(s).padStart(2, '0')}`;
  }
  const fmtMs = (ms) => (ms === null || ms === undefined ? '—' : ms >= 1000 ? `${fmtDec(ms / 1000, 2)} s` : `${fmtInt(Math.round(ms))} ms`);

  const setAll = (selector, text) => document.querySelectorAll(selector).forEach((el) => { el.textContent = text; });
  const metric = (name, text) => setAll(`[data-metric="${name}"]`, text);
  const chess = (name, text) => setAll(`[data-chess="${name}"]`, text);

  function fillRows(tbody, rows, columns) {
    if (!tbody) return;
    tbody.replaceChildren();
    if (!rows.length) {
      const tr = document.createElement('tr');
      const td = document.createElement('td');
      td.colSpan = columns; td.className = 'muted'; td.textContent = 'Sin datos todavía';
      tr.append(td); tbody.append(tr);
      return;
    }
    rows.forEach((cells) => {
      const tr = document.createElement('tr');
      cells.forEach((value, index) => {
        const cell = document.createElement(index === 0 ? 'th' : 'td');
        cell.textContent = value;
        tr.append(cell);
      });
      tbody.append(tr);
    });
  }

  function progressText(match) {
    const p = match.progress || {};
    if (match.gameId === 'CHESS') return `${fmtInt(p.moves)} movimientos · ${fmtInt(p.captures)} capturas · ${fmtInt(p.aiDecisions)} decisiones IA`;
    return Object.entries(p).map(([k, v]) => `${k}: ${v}`).join(' · ') || '—';
  }

  function render(data) {
    const ingestion = data.ingestion || null;
    const analytics = data.analytics || null;
    const totals = ingestion?.totals || {};
    const general = analytics?.general || {};

    metric('startedMatches', fmtInt(totals.startedMatches));
    metric('activeMatches', fmtInt(totals.activeMatches));
    metric('acceptedEvents', fmtInt(totals.acceptedEvents));
    metric('completedMatches', fmtInt(general.processedMatches ?? general.completedMatches));
    metric('averageDuration', fmtDuration(general.averageDurationMs));
    metric('totalPlayTime', fmtDuration(general.totalPlayTimeMs));

    const ok = !data.errors?.length;
    metric('connection', ok ? 'GameStats conectado' : 'GameStats con problemas');
    metric('liveBadge', ok ? 'LIVE' : 'ERROR');
    metric('updatedAt', `Actualizado ${new Date().toLocaleTimeString('es-CR')}`);
    const errorBox = document.querySelector('[data-stats-errors]');
    if (errorBox) {
      errorBox.hidden = ok;
      errorBox.textContent = ok ? '' : data.errors.join(' · ');
    }

    const analyzedByGame = general.processedMatchesByGame || general.matchesByGame || {};
    fillRows(document.querySelector('[data-instances]'), (ingestion?.games || []).map((g) => [
      GAME_NAMES[g.gameId] || g.gameId, fmtInt(g.startedMatches), fmtInt(g.activeMatches),
      fmtInt(g.finishedMatches), fmtInt(g.acceptedEvents), fmtInt(analyzedByGame[g.gameId] ?? 0),
    ]), 6);

    const c = analytics?.games?.CHESS;
    if (c) {
      chess('completedMatches', fmtInt(c.completedMatches));
      chess('averageMoves', fmtDec(c.averageMoves));
      chess('averageCaptures', fmtDec(c.averageCaptures));
      chess('averageDuration', fmtDuration(c.averageDurationMs));
      const white = (c.winsByColor || []).find((x) => x.color === 'WHITE');
      const black = (c.winsByColor || []).find((x) => x.color === 'BLACK');
      chess('whiteWins', fmtInt(white?.wins)); chess('whitePct', fmtPct(white?.winPercentage));
      chess('blackWins', fmtInt(black?.wins)); chess('blackPct', fmtPct(black?.winPercentage));
      fillRows(document.querySelector('[data-chess-reasons]'),
        Object.entries(c.results || {}).map(([reason, count]) => [REASONS[reason] || reason, fmtInt(count)]), 2);
      const ai = c.ai || {};
      fillRows(document.querySelector('[data-chess-ai]'), ai.decisions ? [
        ['Decisiones registradas', fmtInt(ai.decisions)],
        ['Profundidad promedio', fmtDec(ai.averageDepth, 2)],
        ['Nodos evaluados (promedio)', fmtInt(Math.round(ai.averageNodes))],
        ['Nodos evaluados (máximo)', fmtInt(ai.maxNodes)],
        ['Tiempo de cálculo promedio', fmtMs(ai.averageThinkTimeMs)],
      ] : [], 2);
      fillRows(document.querySelector('[data-chess-players]'), (c.players || []).map((p) => [
        p.playerId, fmtInt(p.matches), fmtInt(p.wins), fmtInt(p.draws), fmtInt(p.losses), fmtMs(p.averageDecisionTimeMs),
      ]), 6);
    }

    const pac = analytics?.games?.PACMAN;
    fillRows(document.querySelector('[data-game-table="PACMAN"]'), pac ? [
      ['Partidas analizadas', fmtInt(pac.completedMatches)],
      ['Puntuación promedio', fmtDec(pac.averageScore)],
      ['Mejor puntuación', fmtInt(pac.bestScore)],
      ['Fantasmas comidos', fmtInt(pac.totalGhosts)],
      ['Niveles completados', fmtInt(pac.totalLevelsCompleted)],
      ['Duración promedio', fmtDuration(pac.averageDurationMs)],
    ] : [], 2);
    const race = analytics?.games?.RACING;
    fillRows(document.querySelector('[data-game-table="RACING"]'), race ? [
      ['Carreras completadas', fmtInt(race.completedMatches)],
      ['Carreras abortadas', fmtInt(race.abortedMatches)],
      ['Vuelta más rápida', race.bestLap ? `${fmtMs(race.bestLap.lapTimeMs)} · ${race.bestLap.playerId}` : '—'],
      ['Paradas en boxes', fmtInt(race.totalPitStops)],
      ['Remontadas', fmtInt(race.comebacks)],
      ['Duración promedio', fmtDuration(race.averageDurationMs)],
    ] : [], 2);

    fillRows(document.querySelector('[data-active-matches]'), (ingestion?.activeMatches || []).map((m) => [
      m.matchId, GAME_NAMES[m.gameId] || m.gameId, fmtInt(m.events), progressText(m),
      m.lastEventAt ? new Date(m.lastEventAt).toLocaleTimeString('es-CR') : '—',
    ]), 5);
  }

  async function refresh() {
    try {
      const response = await fetch('/api/estadisticas', { cache: 'no-store' });
      render(await response.json());
    } catch (error) {
      metric('connection', 'Sin conexión con la consola');
    } finally {
      window.setTimeout(refresh, REFRESH_MS);
    }
  }
  refresh();
})();

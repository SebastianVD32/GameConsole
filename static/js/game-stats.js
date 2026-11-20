/* Shared in-game view: every metric comes directly from GameStats. */
(() => {
  const root = document.querySelector('[data-game-stats]');
  if (!root) return;
  const values = root.querySelector('[data-game-stats-values]');
  const status = root.querySelector('[data-game-stats-status]');
  const number = value => value == null ? '—' : Number(value).toLocaleString('es-CR');
  async function refresh() {
    try {
      const response = await fetch('/api/estadisticas', { cache: 'no-store', signal: AbortSignal.timeout(10000) });
      if (!response.ok) throw Error('No se pudo consultar GameStats.');
      const data = await response.json();
      const id = root.dataset.gameStats;
      const live = data.ingestion?.games?.find(game => game.gameId === id);
      const game = data.analytics?.games?.[id];
      if (!live && !game) throw Error('GameStats todavía no devuelve datos de este juego.');
      const rows = [
        ['Instancias iniciadas', live?.startedMatches],
        ['Partidas activas', live?.activeMatches],
        ['Partidas analizadas', game?.completedMatches],
      ];
      if (id === 'CHESS') rows.push(['Movimientos promedio', game?.averageMoves], ['Decisiones de IA', game?.ai?.decisions]);
      if (id === 'PACMAN') rows.push(['Mejor puntuación', game?.bestScore], ['Puntuación promedio', game?.averageScore]);
      if (id === 'RACING') rows.push(['Carreras abortadas', game?.abortedMatches], ['Mejor vuelta (ms)', game?.bestLap?.lapTimeMs]);
      values.replaceChildren(...rows.map(([label, value]) => {
        const article = document.createElement('article');
        const span = document.createElement('span'); span.textContent = label;
        const strong = document.createElement('strong'); strong.textContent = number(value);
        article.append(span, strong); return article;
      }));
      status.textContent = data.errors?.length
        ? `Datos parciales. ${data.errors.join(' · ')}`
        : `GameStats actualizado a las ${new Date().toLocaleTimeString('es-CR')}. Las instancias se actualizan durante el juego; los resultados, al finalizar. Historial compartido de este juego.`;
    } catch (error) {
      status.textContent = `No se pudo actualizar: ${error.message} Los valores anteriores pueden estar desactualizados.`;
    } finally { window.setTimeout(refresh, 2500); }
  }
  refresh();
})();

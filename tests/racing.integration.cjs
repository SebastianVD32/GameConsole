// Live test: Flask -> real Go, with optional result verification against Scala.
const assert = require('node:assert/strict');
const { completeRace, abortedRace } = require('./racing-scenarios.cjs');
const { powerAndLossGame } = require('./pacman-scenarios.cjs');
const consoleUrl = process.env.CONSOLE_URL || 'http://127.0.0.1:5000';
const ingestionUrl = process.env.GAMESTATS_INGESTION_URL || 'http://127.0.0.1:8080';

(async () => {
  const before = process.env.VERIFY_SCALA === '1'
    ? (await (await fetch(`${consoleUrl}/api/estadisticas`)).json()).analytics.games.RACING : null;
  const games = [completeRace(), completeRace({ slowPlayer: true }), powerAndLossGame(),
    abortedRace(), abortedRace({ partial: true, reason: 'RESTARTED' }), abortedRace({ reason: 'PAGE_CLOSED' })];
  await Promise.all(games.map(async game => {
    for (const event of game.events) {
      const response = await fetch(`${consoleUrl}/api/arcade/events`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(event), signal: AbortSignal.timeout(10000),
      });
      const body = await response.json();
      assert.equal(response.status, 202, JSON.stringify({ event, body })); assert.equal(body.persisted, true);
    }
    const deadline = Date.now() + 30000;
    while (true) {
      const state = await (await fetch(`${consoleUrl}/api/arcade/partidas/${game.matchId}/envio`)).json();
      assert.notEqual(state.state, 'REJECTED', JSON.stringify(state));
      if (state.state === 'DELIVERED') break;
      assert.ok(Date.now() < deadline, `Delivery timeout: ${JSON.stringify(state)}`);
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    const batch = await (await fetch(`${ingestionUrl}/api/v1/matches/${game.matchId}`)).json();
    const canonical = events => events.map(e => ({ ...e, timestamp: new Date(e.timestamp).toISOString() }));
    assert.deepEqual(canonical(batch.events), canonical(game.events));
    if (batch.gameId === 'RACING') {
      if (game.state === 'abandoned') {
        if (process.env.VERIFY_SCALA === '1') {
          const response = await fetch(`${consoleUrl}/api/gamestats/matches/${game.matchId}`);
          const result = await response.json(); assert.equal(response.status, 200, JSON.stringify(result));
          assert.equal(result.status, 'ABORTED'); assert.equal(result.reason, game.abortReason);
          assert.equal(result.classification, undefined); assert.equal(result.fastestLaps, undefined);
          for (const car of game.cars) {
            const progress = result.driverProgress.find(driver => driver.playerId === car.id);
            assert.equal(progress.completedLaps, car.completedLaps);
            assert.equal(progress.completedLapTimeMs, car.laps.reduce((a, b) => a + b, 0));
          }
        }
        console.log(`RACING: abandono ${game.abortReason} verificado, ${game.events.length} eventos.`);
        return;
      }
      assert.equal(batch.events.filter(e => e.type === 'LAP_COMPLETED').length, 12);
      console.log(`RACING: ${game.events.length} eventos aceptados, jugador en posicion ${game.playerPosition}, ${game.matchId}`);
      if (process.env.VERIFY_SCALA === '1') {
        const response = await fetch(`${consoleUrl}/api/gamestats/matches/${game.matchId}`);
        const result = await response.json(); assert.equal(response.status, 200, JSON.stringify(result));
        assert.deepEqual(result.classification, game.result);
        for (const car of game.cars) {
          const stats = result.drivers.find(driver => driver.playerId === car.id);
          assert.equal(stats.bestLapTimeMs, Math.min(...car.laps));
          assert.equal(stats.totalTimeMs, car.finishTimeMs); assert.equal(stats.completedLaps, 3);
        }
        console.log('Resultado oficial Scala verificado.');
      }
    } else console.log(`PACMAN: regresion verificada, ${game.events.length} eventos aceptados.`);
  }));
  const summary = await (await fetch(`${ingestionUrl}/api/v1/summary`)).json();
  assert.ok(summary.activeMatches.every(match => !games.some(game => game.matchId === match.matchId)));
  if (before) {
    const after = (await (await fetch(`${consoleUrl}/api/estadisticas`)).json()).analytics.games.RACING;
    assert.equal(after.completedMatches, before.completedMatches + 2);
    assert.equal(after.abortedMatches, before.abortedMatches + 3);
    for (const reason of ['USER_QUIT', 'RESTARTED', 'PAGE_CLOSED']) {
      assert.equal(after.abortsByReason[reason], before.abortsByReason[reason] + 1);
    }
  }
  console.log('Seis partidas concurrentes verificadas mediante Flask -> GameStats Go.');
})().catch(error => { console.error(error); process.exitCode = 1; });

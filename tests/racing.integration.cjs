// Live test: Flask -> real Go, with optional result verification against Scala.
const assert = require('node:assert/strict');
const { completeRace } = require('./racing-scenarios.cjs');
const { powerAndLossGame } = require('./pacman-scenarios.cjs');
const consoleUrl = process.env.CONSOLE_URL || 'http://127.0.0.1:5000';
const ingestionUrl = process.env.GAMESTATS_INGESTION_URL || 'http://127.0.0.1:8080';

(async () => {
  const games = [completeRace(), completeRace({ slowPlayer: true }), powerAndLossGame()];
  await Promise.all(games.map(async game => {
    for (const event of game.events) {
      const response = await fetch(`${consoleUrl}/api/gamestats/events`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(event), signal: AbortSignal.timeout(10000),
      });
      const body = await response.json();
      assert.equal(response.status, 201, JSON.stringify({ event, body })); assert.equal(body.accepted, true);
    }
    const batch = await (await fetch(`${ingestionUrl}/api/v1/matches/${game.matchId}`)).json();
    const canonical = events => events.map(e => ({ ...e, timestamp: new Date(e.timestamp).toISOString() }));
    assert.deepEqual(canonical(batch.events), canonical(game.events));
    if (batch.gameId === 'RACING') {
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
  console.log('Tres partidas concurrentes verificadas mediante Flask -> GameStats Go.');
})().catch(error => { console.error(error); process.exitCode = 1; });

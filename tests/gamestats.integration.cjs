// Optional live integration: start Flask and the real GameStats Go service first.
const assert = require('node:assert/strict');
const { winningGame, powerAndLossGame } = require('./pacman-scenarios.cjs');
const consoleUrl = process.env.CONSOLE_URL || 'http://127.0.0.1:5000';
const ingestionUrl = process.env.GAMESTATS_INGESTION_URL || 'http://127.0.0.1:8080';

(async () => {
  const games = [winningGame(), powerAndLossGame()];
  await Promise.all(games.map(async game => {
    for (const event of game.events) {
      const response = await fetch(`${consoleUrl}/api/gamestats/events`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(event),
      });
      const body = await response.json();
      assert.equal(response.status, 201, JSON.stringify({ event, body }));
      assert.equal(body.accepted, true);
    }
    const response = await fetch(`${ingestionUrl}/api/v1/matches/${game.matchId}`);
    const batch = await response.json();
    // Go serializes equivalent UTC instants without trailing fractional zeroes.
    const canonical = events => events.map(e => ({ ...e, timestamp: new Date(e.timestamp).toISOString() }));
    assert.deepEqual(canonical(batch.events), canonical(game.events));
    console.log(`${game.state}: ${game.events.length} eventos aceptados, ${game.score} puntos, ${game.matchId}`);
  }));
  console.log('Dos partidas concurrentes verificadas mediante Flask -> GameStats Go.');
})().catch(error => { console.error(error); process.exitCode = 1; });

const { RacingGame, RivalDriver } = require('../static/js/racing-engine');

function completeRace({ slowPlayer = false, plannedLaps = 3 } = {}) {
  let clock = Date.now();
  const game = new RacingGame({ now: () => clock, plannedLaps });
  // Test-only autopilot supplies ordinary throttle/brake/steering inputs to the human car.
  if (slowPlayer) game.player.pace = 0.72;
  const autopilot = new RivalDriver(game.player);
  game.start({ countdown: false });
  for (let i = 0; i < 6000 && game.state !== 'finished'; i++) {
    game.setInput(autopilot.input(game)); clock += 100; game.update(0.1);
  }
  if (game.state !== 'finished') throw Error('Race did not finish');
  return game;
}
module.exports = { completeRace };

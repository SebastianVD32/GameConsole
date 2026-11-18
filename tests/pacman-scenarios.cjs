const { PacmanGame } = require('../static/js/pacman-engine');

function winningGame() {
  let clock = Date.now();
  const game = new PacmanGame({ now: () => clock });
  game.ghosts.forEach(ghost => { ghost.delay = Infinity; });
  game.start();
  // Test autopilot follows real movement, with opponents disabled to exhaust the maze.
  for (let i = 0; i < 10000 && game.state === 'running'; i++) {
    const distances = game.maze.distances(game.player);
    const nearest = [...game.maze.pellets.keys()].sort((a, b) => distances.get(a) - distances.get(b))[0];
    const [x, y] = nearest.split(',').map(Number);
    const target = game.maze.distances({ x, y });
    const next = game.maze.neighbors(game.player.x, game.player.y)
      .sort((a, b) => target.get(`${a.x},${a.y}`) - target.get(`${b.x},${b.y}`))[0];
    game.steer(next.direction); clock += 130; game.update(0.13);
  }
  if (game.state !== 'won') throw Error('Autopilot did not clear the maze');
  return game;
}

function powerAndLossGame() {
  let clock = Date.now();
  const game = new PacmanGame({ now: () => clock });
  game.start(); Object.assign(game.player, { x: 1, y: 1 }); game.collect();
  for (const ghost of game.ghosts) { Object.assign(ghost, { x: 1, y: 1 }); game.collide(); }
  clock += 8000; game.update(0.01);
  for (let i = 0; i < 3; i++) {
    Object.assign(game.ghosts[0], { x: game.player.x, y: game.player.y }); game.collide();
  }
  return game;
}
module.exports = { winningGame, powerAndLossGame };

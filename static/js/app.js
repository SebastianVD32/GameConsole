const sidebar = document.querySelector('#sidebar');
const menuButton = document.querySelector('#menu-button');
const toast = document.querySelector('#toast');
let toastTimer;

const activeGameMeta = {
  CHESS: { name: 'Ajedrez', icon: '♞', accent: 'violet', path: '/juegos/ajedrez' },
  PACMAN: { name: 'Pac-Man', icon: '●', accent: 'amber', path: '/juegos/pacman' },
  RACING: { name: 'Carreras', icon: '↗', accent: 'cyan', path: '/juegos/carreras' },
};

function showToast(message) {
  if (!toast) return;
  toast.textContent = message;
  toast.classList.add('is-visible');
  window.clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => toast.classList.remove('is-visible'), 2600);
}

menuButton?.addEventListener('click', () => {
  const isOpen = sidebar.classList.toggle('is-open');
  menuButton.setAttribute('aria-expanded', String(isOpen));
});

document.addEventListener('click', (event) => {
  const toastTrigger = event.target.closest('[data-toast]');
  const scrollTrigger = event.target.closest('[data-scroll-to]');

  if (toastTrigger) showToast(toastTrigger.dataset.toast);
  if (scrollTrigger) document.querySelector(`#${scrollTrigger.dataset.scrollTo}`)?.scrollIntoView({ behavior: 'smooth' });

  if (window.innerWidth <= 960 && sidebar?.classList.contains('is-open') &&
      !event.target.closest('#sidebar') && !event.target.closest('#menu-button')) {
    sidebar.classList.remove('is-open');
    menuButton?.setAttribute('aria-expanded', 'false');
  }
});

const activityItems = document.querySelectorAll('.activity-item');
const focusedSession = document.querySelector('#focused-session');
activityItems.forEach((item) => {
  item.addEventListener('click', () => {
    activityItems.forEach((entry) => entry.classList.remove('is-selected'));
    item.classList.add('is-selected');
    if (focusedSession) focusedSession.textContent = item.dataset.session;
  });
});

function activeMatchHref(match) {
  const meta = activeGameMeta[match.gameId];
  if (match.gameId === 'CHESS') return `${meta.path}?partida=${encodeURIComponent(match.matchId)}`;
  return '/estadisticas#partidas-en-curso';
}

function activeMatchDetail(match) {
  if (match.status && match.events === undefined) return `${match.status} · ${String(match.matchId).slice(0, 12)}`;
  const events = Number(match.events || 0);
  return `${events} ${events === 1 ? 'evento' : 'eventos'} · ${String(match.matchId).slice(0, 12)}`;
}

function renderActiveSessions(matches) {
  const supported = matches.filter(match => activeGameMeta[match.gameId] && match.matchId).slice(0, 8);
  document.querySelectorAll('[data-active-count]').forEach(node => { node.textContent = supported.length; });

  document.querySelectorAll('[data-active-sessions]').forEach(container => {
    const cards = container.dataset.variant === 'cards';
    if (!supported.length) {
      const empty = document.createElement('p');
      empty.className = cards ? 'empty-note' : 'session-empty';
      empty.textContent = 'Sin partidas en curso';
      container.replaceChildren(empty);
      return;
    }

    const nodes = supported.map(match => {
      const meta = activeGameMeta[match.gameId];
      const link = document.createElement('a');
      link.href = activeMatchHref(match);
      link.title = match.gameId === 'CHESS' ? 'Abrir esta partida' : 'Ver actividad en GameStats';

      if (cards) {
        link.className = 'activity-item';
        const icon = document.createElement('span');
        icon.className = `activity-icon ${meta.accent}`;
        icon.textContent = meta.icon;
        const copy = document.createElement('span');
        const name = document.createElement('strong');
        const detail = document.createElement('small');
        name.textContent = meta.name; detail.textContent = activeMatchDetail(match);
        copy.append(name, detail);
        const time = document.createElement('time');
        time.textContent = match.lastEventAt ? new Date(match.lastEventAt).toLocaleTimeString('es-CR', { hour: '2-digit', minute: '2-digit' }) : 'Activa';
        link.append(icon, copy, time);
      } else {
        link.className = 'session-link';
        const dot = document.createElement('span');
        dot.className = `session-dot ${meta.accent}`;
        const copy = document.createElement('span');
        const name = document.createElement('strong');
        const detail = document.createElement('small');
        name.textContent = meta.name; detail.textContent = activeMatchDetail(match);
        copy.append(name, detail); link.append(dot, copy);
      }
      return link;
    });
    container.replaceChildren(...nodes);
  });
}

async function refreshActiveSessions() {
  try {
    const [statsResult, localResult] = await Promise.allSettled([
      fetch('/api/estadisticas', { cache: 'no-store' }).then(response => response.ok ? response.json() : null),
      fetch('/api/partidas', { cache: 'no-store' }).then(response => response.ok ? response.json() : []),
    ]);
    const reported = statsResult.status === 'fulfilled' && Array.isArray(statsResult.value?.ingestion?.activeMatches)
      ? statsResult.value.ingestion.activeMatches : [];
    const local = localResult.status === 'fulfilled' && Array.isArray(localResult.value)
      ? localResult.value.filter(match => !match.finished) : [];
    if (statsResult.status === 'fulfilled' || localResult.status === 'fulfilled') {
      const unique = new Map([...local, ...reported].map(match => [match.matchId, match]));
      renderActiveSessions([...unique.values()]);
    }
  } catch { /* Keep the server-rendered list when GameStats is unavailable. */ }
}

if (document.querySelector('[data-active-sessions]')) {
  refreshActiveSessions();
  window.setInterval(refreshActiveSessions, 5000);
}

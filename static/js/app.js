const sidebar = document.querySelector('#sidebar');
const menuButton = document.querySelector('#menu-button');
const toast = document.querySelector('#toast');
let toastTimer;

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

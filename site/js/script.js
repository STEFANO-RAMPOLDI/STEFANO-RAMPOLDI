// Mobile nav toggle
const navToggle = document.getElementById('navToggle');
const mainNav = document.querySelector('.main-nav');

if (navToggle && mainNav) {
  navToggle.addEventListener('click', () => {
    mainNav.classList.toggle('open');
  });
  mainNav.addEventListener('click', (e) => {
    if (e.target.tagName === 'A') mainNav.classList.remove('open');
  });
}

// Demo form (client-side only — no backend wired yet)
const form = document.getElementById('demoForm');
const msg = document.getElementById('formMsg');

if (form) {
  form.addEventListener('submit', (e) => {
    e.preventDefault();
    const data = new FormData(form);
    const nome = (data.get('nome') || '').toString().trim();
    const email = (data.get('email') || '').toString().trim();
    const emailOk = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);

    if (!nome || !emailOk) {
      msg.textContent = '⚠️ Inserisci nome ed email aziendale validi.';
      return;
    }
    msg.textContent = `✅ Grazie ${nome.split(' ')[0]}! Ti contatteremo a breve per organizzare la demo.`;
    form.reset();
  });
}

// Reveal-on-scroll animation
const observer = new IntersectionObserver((entries) => {
  entries.forEach((entry) => {
    if (entry.isIntersecting) {
      entry.target.style.opacity = '1';
      entry.target.style.transform = 'none';
      observer.unobserve(entry.target);
    }
  });
}, { threshold: 0.12 });

document.querySelectorAll('.pillar, .card, .side, .kpi, .plan, .phase, .sector-col, .agent-group').forEach((el) => {
  el.style.opacity = '0';
  el.style.transform = 'translateY(20px)';
  el.style.transition = 'opacity .6s ease, transform .6s ease';
  observer.observe(el);
});

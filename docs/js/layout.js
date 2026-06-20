// ===================== SHARED LAYOUT (header + footer) =====================
// Injected on every page so navigation stays consistent and DRY.

const NAV_LINKS = [
  { href: 'index.html', label: 'Home', key: 'home' },
  { href: 'soluzioni.html', label: 'Soluzioni', key: 'soluzioni' },
  { href: 'piattaforma.html', label: 'Piattaforma', key: 'piattaforma' },
  { href: 'settori.html', label: 'Settori', key: 'settori' },
  { href: 'risultati.html', label: 'Risultati', key: 'risultati' },
];

function buildHeader(active) {
  const links = NAV_LINKS.map(
    (l) => `<li><a href="${l.href}" class="${l.key === active ? 'is-active' : ''}">${l.label}</a></li>`
  ).join('');
  return `
  <header class="site-header" id="top">
    <div class="container header-inner">
      <a class="brand" href="index.html">
        <span class="brand-mark">RE<span class="dot">·</span>DOTS</span>
        <span class="brand-sub">Procurement</span>
      </a>
      <nav class="main-nav" aria-label="Navigazione principale">
        <ul>${links}</ul>
      </nav>
      <div class="header-cta">
        <a href="contatti.html" class="btn btn-ghost">Accedi</a>
        <a href="contatti.html" class="btn btn-primary">Richiedi una demo</a>
      </div>
      <button class="nav-toggle" aria-label="Apri menu" id="navToggle">
        <span></span><span></span><span></span>
      </button>
    </div>
  </header>`;
}

function buildFooter() {
  return `
  <footer class="site-footer">
    <div class="container footer-grid">
      <div class="footer-brand">
        <span class="brand-mark">RE<span class="dot">·</span>DOTS</span>
        <p>La piattaforma AI on-premise per il procurement sanitario. By SomaMed — Healthcare Transformation Platform.</p>
        <div class="footer-badges">
          <span>🔒 On-premise</span><span>⚙️ Open Source</span><span>✅ ROI 90 giorni</span>
        </div>
      </div>
      <div class="footer-col">
        <h4>Soluzioni</h4>
        <ul>
          <li><a href="soluzioni.html#acquisti">Lato Acquisti</a></li>
          <li><a href="soluzioni.html#vendita">Lato Vendita</a></li>
          <li><a href="soluzioni.html#usecase">Use case</a></li>
          <li><a href="piattaforma.html#moduli">Moduli</a></li>
        </ul>
      </div>
      <div class="footer-col">
        <h4>Piattaforma</h4>
        <ul>
          <li><a href="piattaforma.html#ai">Architettura AI</a></li>
          <li><a href="piattaforma.html#sicurezza">Sicurezza &amp; RBAC</a></li>
          <li><a href="piattaforma.html#compliance">Compliance</a></li>
          <li><a href="piattaforma.html#roadmap">Roadmap</a></li>
        </ul>
      </div>
      <div class="footer-col">
        <h4>Azienda</h4>
        <ul>
          <li><a href="settori.html">Settori</a></li>
          <li><a href="risultati.html">Risultati</a></li>
          <li><a href="contatti.html">Contatti</a></li>
          <li><a href="https://somamed.it" target="_blank" rel="noopener">somamed.it</a></li>
        </ul>
      </div>
      <div class="footer-col">
        <h4>SomaMed</h4>
        <ul class="footer-contact">
          <li>Via Felice Casati 32</li>
          <li>20124 Milano</li>
          <li>P.IVA 10435410963</li>
        </ul>
      </div>
    </div>
    <div class="container footer-bottom">
      <p>© 2026 SomaMed S.r.l. — REDOTS Procurement. Tutti i diritti riservati.</p>
      <p class="footer-compliance">MDR · NIS2 · D.lgs 36/2023 · GDPR Art. 9 by design</p>
    </div>
  </footer>`;
}

// Inject into placeholders
document.addEventListener('DOMContentLoaded', () => {
  const headerSlot = document.querySelector('[data-layout="header"]');
  const footerSlot = document.querySelector('[data-layout="footer"]');
  if (headerSlot) headerSlot.outerHTML = buildHeader(document.body.dataset.page || '');
  if (footerSlot) footerSlot.outerHTML = buildFooter();

  // Mobile nav toggle (header now in DOM)
  const navToggle = document.getElementById('navToggle');
  const mainNav = document.querySelector('.main-nav');
  if (navToggle && mainNav) {
    navToggle.addEventListener('click', () => mainNav.classList.toggle('open'));
    mainNav.addEventListener('click', (e) => {
      if (e.target.tagName === 'A') mainNav.classList.remove('open');
    });
  }

  initReveal();
  initForm();
});

// Reveal-on-scroll
function initReveal() {
  const observer = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) {
        entry.target.style.opacity = '1';
        entry.target.style.transform = 'none';
        observer.unobserve(entry.target);
      }
    });
  }, { threshold: 0.12 });
  document.querySelectorAll('.reveal').forEach((el) => {
    el.style.opacity = '0';
    el.style.transform = 'translateY(20px)';
    el.style.transition = 'opacity .6s ease, transform .6s ease';
    observer.observe(el);
  });
}

// Demo form
function initForm() {
  const form = document.getElementById('demoForm');
  const msg = document.getElementById('formMsg');
  if (!form) return;
  form.addEventListener('submit', (e) => {
    e.preventDefault();
    const data = new FormData(form);
    const nome = (data.get('nome') || '').toString().trim();
    const email = (data.get('email') || '').toString().trim();
    const emailOk = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
    if (!nome || !emailOk) {
      msg.textContent = '⚠️ Inserisci nome ed email aziendale validi.';
      msg.className = 'form-msg is-error';
      return;
    }
    msg.textContent = `✅ Grazie ${nome.split(' ')[0]}! Ti contatteremo a breve per organizzare la demo.`;
    msg.className = 'form-msg is-ok';
    form.reset();
  });
}

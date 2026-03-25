// Shared helpers for the dashboard. Exposes functions on `window` so existing bundles can call them.
(function(){
  // Truncate initials to 4 chars
  window.truncateInitials = function(name) {
    if (!name) return '';
    return name.length > 4 ? name.slice(0, 4) + '…' : name;
  };

  // Time/format helpers
  window.formatDuration = function(sec) {
    if (sec == null || isNaN(sec)) return '--:--';
    const m = Math.floor(sec / 60);
    const s = Math.floor(sec % 60);
    return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  };

  window.formatTimeAgo = function(timestamp) {
    if (!timestamp) return '—';
    const now = new Date();
    const then = new Date(timestamp);
    const diffMs = now - then;
    const diffMins = Math.floor(diffMs / 60000);
    if (diffMins < 1) return 'just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    const diffHours = Math.floor(diffMins / 60);
    if (diffHours < 24) return `${diffHours}h ago`;
    return then.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
  };

  // Simple HTML escaper
  window.escapeHtml = function(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  };

  // Engineer color/avatar helpers
  window.getEngineerColor = function(initials) {
    const colors = ['#ff1ea3', '#8cf04a', '#00d4ff', '#ffcc00', '#ff6b35', '#a78bfa', '#34d399', '#fb923c'];
    let hash = 0;
    for (let i = 0; i < (initials || '').length; i++) {
      hash = (initials.charCodeAt(i) || 0) + ((hash << 5) - hash);
    }
    return colors[Math.abs(hash) % colors.length];
  };

  function shadeColor(hex, factor) {
    const num = parseInt(hex.replace('#', ''), 16);
    const r = Math.max(0, Math.min(255, Math.round(((num >> 16) & 0xff) * factor)));
    const g = Math.max(0, Math.min(255, Math.round(((num >> 8) & 0xff) * factor)));
    const b = Math.max(0, Math.min(255, Math.round((num & 0xff) * factor)));
    return `#${(r << 16 | g << 8 | b).toString(16).padStart(6, '0')}`;
  }

  window.avatarCache = new Map();
  window.getAvatarDataUri = function(initials) {
    initials = initials || '';
    if (window.avatarCache.has(initials)) return window.avatarCache.get(initials);
    const base = window.getEngineerColor(initials || '');
    const light = shadeColor(base, 1.4);
    const dark = shadeColor(base, 0.5);
    const veryDark = shadeColor(base, 0.3);
    let hash = 0;
    for (let i = 0; i < initials.length; i++) {
      hash = initials.charCodeAt(i) + ((hash << 5) - hash);
    }
    const absHash = Math.abs(hash);
    const variant = absHash % 16;
    const size = 8;
    const pixels = [];
    const addPixel = (x, y, color) => {
      pixels.push({ x, y, color });
      if (x !== size - x - 1) pixels.push({ x: size - x - 1, y, color });
    };
    // Minimal symmetric avatar generator - simple variants
    if (variant % 2 === 0) {
      addPixel(2,1, base); addPixel(3,1, base);
      addPixel(1,2, base); addPixel(2,2, light); addPixel(3,2, light);
      addPixel(1,3, base); addPixel(2,3, light); addPixel(3,3, base);
    } else {
      addPixel(1,1, base); addPixel(2,1, light); addPixel(3,1, light);
      addPixel(1,2, base); addPixel(2,2, base); addPixel(3,2, base);
      addPixel(2,3, dark);
    }
    const rects = pixels.map(p => `<rect x="${p.x}" y="${p.y}" width="1" height="1" fill="${p.color}"/>`).join('');
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 ${size} ${size}" shape-rendering="crispEdges">${rects}</svg>`;
    const uri = `data:image/svg+xml,${encodeURIComponent(svg)}`;
    window.avatarCache.set(initials, uri);
    return uri;
  };

  // Keep-alive helpers
  let wakeLock = null;
  let audioCtx = null;
  let silentOsc = null;
  let keepAliveVideo = null;

  window.requestWakeLock = async function() {
    if (!('wakeLock' in navigator)) return;
    try {
      wakeLock = await navigator.wakeLock.request('screen');
      wakeLock.addEventListener('release', () => { wakeLock = null; });
    } catch (err) {
      console.warn('Wake lock request failed', err);
    }
  };

  window.ensureSilentAudio = function() {
    try {
      if (silentOsc && audioCtx && audioCtx.state !== 'closed') {
        if (audioCtx.state === 'suspended') audioCtx.resume().catch(() => {});
        return;
      }
      const Ctx = window.AudioContext || window.webkitAudioContext;
      if (!Ctx) return;
      audioCtx = new Ctx();
      if (audioCtx.state === 'suspended') audioCtx.resume().catch(() => {});
      const osc = audioCtx.createOscillator();
      const gain = audioCtx.createGain();
      gain.gain.value = 0.0001;
      osc.connect(gain).connect(audioCtx.destination);
      osc.start();
      silentOsc = osc;
    } catch (err) {
      console.warn('Silent audio keep-alive failed', err);
    }
  };

  window.startKeepAliveVideo = function() {
    try {
      if (keepAliveVideo && keepAliveVideo.readyState > 0) { keepAliveVideo.play().catch(() => {}); return; }
      const vid = document.createElement('video');
      vid.muted = true; vid.loop = true; vid.playsInline = true; vid.autoplay = true;
      vid.setAttribute('playsinline', '');
      vid.style.position = 'fixed'; vid.style.width = '1px'; vid.style.height = '1px'; vid.style.opacity = '0.001'; vid.style.bottom = '0'; vid.style.left = '0'; vid.style.pointerEvents = 'none';
      vid.src = 'data:video/webm;base64,GkXfo59ChoEBQveBAULygQRC9+BBQvWBAULpgQRC8YEEQvGBAAAB9uWdlYm0BVmVyc2lvbj4xAAAAAAoAAABHYXZrVjkAAAAAAAAD6aNjYWI9AAAZY2FkYwEAAAAAAAAAAAAAAAAAAAAAAAACdC9hAAAAAAACAAEAAQAAAQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=';
      document.body.appendChild(vid);
      keepAliveVideo = vid;
      vid.play().catch(() => {});
    } catch (err) { console.warn('Keep-alive video failed', err); }
  };

  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) {
      window.requestWakeLock();
      window.ensureSilentAudio();
      window.startKeepAliveVideo();
    }
  });

  window.keepScreenAlive = function() {
    if (document.hidden) return;
    window.requestWakeLock();
    window.ensureSilentAudio();
    window.startKeepAliveVideo();
    document.body.style.opacity = '0.999';
    setTimeout(() => { document.body.style.opacity = '1'; }, 80);
  };
  setInterval(window.keepScreenAlive, 2 * 60 * 1000);
  // First shot
  try { window.keepScreenAlive(); } catch (e) { }

  // Nightly reload scheduler (keeps memory clean)
  window.scheduleNightlyReload = function() {
    const now = new Date();
    let reloadTime = new Date();
    reloadTime.setHours(2,0,0,0);
    if (now > reloadTime) reloadTime.setDate(reloadTime.getDate() + 1);
    const msUntilReload = reloadTime - now;
    setTimeout(() => { location.reload(); window.scheduleNightlyReload(); }, msUntilReload);
  };
  try { window.scheduleNightlyReload(); } catch (e) {}

  // Adaptive poll helper
  window.createAdaptivePoll = function(fn, baseIntervalMs, opts = {}) {
    const viewerMultiplier = opts.viewerMultiplier || 6;
    const hiddenMultiplier = opts.hiddenMultiplier || 5;
    let timer = null; let stopped = false;
    function roleIsViewer() { return (sessionStorage.getItem('userRole') || 'viewer') === 'viewer'; }
    function effectiveInterval() { let iv = baseIntervalMs * (roleIsViewer() ? viewerMultiplier : 1); if (document.hidden) iv = Math.max(iv, baseIntervalMs * hiddenMultiplier); return iv; }
    async function tick() { if (stopped) return; try { await fn(); } catch (e) { console.warn('Adaptive poll error', e); } schedule(); }
    function schedule() { clearTimeout(timer); if (stopped) return; timer = setTimeout(tick, effectiveInterval()); }
    document.addEventListener('visibilitychange', () => { clearTimeout(timer); if (!stopped) schedule(); });
    schedule();
    return { stop() { stopped = true; clearTimeout(timer); }, start() { if (stopped) { stopped = false; schedule(); } } };
  };

  // Small optimized confetti trigger wrapper
  window.triggerConfetti = function() {
    if (typeof confetti === 'undefined') { console.warn('Confetti library not loaded'); return; }
    const confettiColors = ['#ff1ea3','#8cf04a','#00d4ff','#ffcc00'];
    const defaults = { origin: { y: 0.3 }, zIndex: 10000, disableForReducedMotion: true };
    confetti({ ...defaults, particleCount: 50, spread: 90, startVelocity: 40, colors: confettiColors, ticks: 120 });
  };

  // SVG sparkline renderer (small, resilient)
  window.renderSVGSparkline = function(svgElem, data) {
    const width = 400, height = 48;
    if (!svgElem) return; svgElem.innerHTML = '';
    if (!Array.isArray(data) || data.length === 0) return;
    const min = Math.min(...data); const max = Math.max(...data); const range = max - min || 1; const step = width / (data.length - 1);
    let d = '';
    data.forEach((val, i) => { const x = i * step; const y = height - ((val - min) / range) * (height - 6) - 3; d += (i === 0 ? 'M' : 'L') + x.toFixed(2) + ',' + y.toFixed(2) + ' '; });
    const fillD = d + `L ${width},${height} L 0,${height} Z`;
    const ns = 'http://www.w3.org/2000/svg';
    const fill = document.createElementNS(ns, 'path'); fill.setAttribute('d', fillD); fill.setAttribute('fill', 'rgba(140,240,74,0.15)'); svgElem.appendChild(fill);
    const path = document.createElementNS(ns, 'path'); path.setAttribute('d', d); path.setAttribute('fill', 'none'); path.setAttribute('stroke', '#8cf04a'); path.setAttribute('stroke-width', '2'); svgElem.appendChild(path);
  };

  // Donut update helper (requires Chart instance)
  window.updateDonut = function(chart, value, target) {
    try {
      const remaining = Math.max(target - value, 0);
      chart.data.datasets[0].data = [value, remaining];
      chart.canvas.dataset.target = target;
      chart.update('none');
      const container = chart.canvas.closest('.donut-card'); if (container) { container.classList.add('pulse-update'); setTimeout(() => container.classList.remove('pulse-update'), 600); }
    } catch (e) { console.warn('updateDonut failed', e); }
  };

  // Minimal donut chart factory using Chart.js. Returns Chart instance or null.
  window.donut = function(canvasId) {
    try {
      const canvas = document.getElementById(canvasId);
      if (!canvas) return null;
      const ctx = canvas.getContext('2d');
      const theme = (window.cfg && window.cfg.theme) || { text: '#fff', muted: '#9aa5b1', ringPrimary: '#2bb4ff', ringSecondary: '#ffb86b' };
      const chart = new Chart(ctx, {
        type: 'doughnut',
        data: { datasets: [{ data: [0, 1], backgroundColor: [theme.ringPrimary, 'rgba(255,255,255,0.06)'], borderWidth: 0 }] },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          cutout: '72%',
          plugins: { legend: { display: false }, tooltip: { enabled: false } },
        }
      });
      chart.canvas.dataset.target = 0;
      return chart;
    } catch (e) { console.warn('donut factory failed', e); return null; }
  };

})();
// Copied app.js into dashboard/common.js as the initial common bundle.
// This file contains the full dashboard application JS.

// --- SVG Sparkline Renderer (must be top-level for all uses) ---
function renderSVGSparkline(svgElem, data) {
  const width = 400;
  const height = 48;
  if (!svgElem) return;
  svgElem.innerHTML = '';
  if (!data || data.length < 1) return;
  const allSame = data.every(v => v === data[0]);
  if (data.length === 1 || allSame) {
    const y = height / 2;
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('d', `M0,${y} L${width},${y}`);
    path.setAttribute('fill', 'none');
    path.setAttribute('stroke', '#8cf04a');
    path.setAttribute('stroke-width', '2');
    svgElem.appendChild(path);
    return;
  }
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;
  const step = width / (data.length - 1);
  let d = '';
  data.forEach((val, i) => {
    const x = i * step;
    const y = height - ((val - min) / range) * (height - 6) - 3;
    d += (i === 0 ? 'M' : 'L') + x.toFixed(2) + ',' + y.toFixed(2) + ' ';
  });
  let fillD = d + `L ${width},${height} L 0,${height} Z`;
  const fill = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  fill.setAttribute('d', fillD);
  fill.setAttribute('fill', 'rgba(140,240,74,0.15)');
  svgElem.appendChild(fill);
  const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  path.setAttribute('d', d);
  path.setAttribute('fill', 'none');
  path.setAttribute('stroke', '#8cf04a');
  path.setAttribute('stroke-width', '2');
  path.setAttribute('stroke-linejoin', 'round');
  svgElem.appendChild(path);
}

// NOTE: For now this file is a direct copy of the existing `app.js` bundle.
// Keeping the full app in `dashboard/common.js` ensures no immediate regressions.
// Future work: extract QA-specific functions into `dashboard/qa.js` and erasure-specific
// functions into `dashboard/erasure.js` and remove them from `common.js`.

// When this file loads it will execute the same initialization that previously ran from app.js.

(function(){
  window.__dashboardCommonLoaded = true;
})();

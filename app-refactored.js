/**
 * Warehouse Erasure Stats Dashboard
 * Refactored for efficiency and maintainability
 */

(async function () {
  // ==================== CONFIG & SETUP ====================
  const cfg = await fetch('config.json').then(r => r.json());
  
  // Cache DOM elements to avoid repeated queries
  const DOM = {
    root: document.documentElement,
    app: document.getElementById('app'),
    totalTodayValue: document.getElementById('totalTodayValue'),
    monthTotalValue: document.getElementById('monthTotalValue'),
    erasedTarget: document.getElementById('erasedTarget'),
    monthTarget: document.getElementById('monthTarget'),
    lastUpdated: document.getElementById('last-updated'),
    staleIndicator: document.getElementById('stale-indicator'),
    leaderboardBody: document.getElementById('leaderboardBody'),
    weeklyLeaderboardBody: document.getElementById('weeklyLeaderboardBody'),
    byTypeBars: document.getElementById('byTypeBars'),
    greenieContainer: document.getElementById('greenieContainer'),
    greenieQuote: document.getElementById('greenieQuote'),
    winnerModal: document.getElementById('winnerModal'),
    winnerText: document.getElementById('winnerText'),
    winnerSubtext: document.getElementById('winnerSubtext'),
  };

  // Cache category elements
  const categories = [
    { key: 'laptops_desktops', label: 'Laptops/Desktops', countId: 'countLD', listId: 'topLD' },
    { key: 'servers', label: 'Servers', countId: 'countServers', listId: 'topServers' },
    { key: 'macs', label: 'Macs', countId: 'countMacs', listId: 'topMacs' },
    { key: 'mobiles', label: 'Mobiles', countId: 'countMobiles', listId: 'topMobiles' },
  ];

  // Cache element references with getters
  const getCategoryElement = (catId) => {
    return { 
      count: document.getElementById(catId.countId),
      list: document.getElementById(catId.listId)
    };
  };

  // ==================== STATE ====================
  let state = {
    charts: { totalToday: null, month: null, peakHours: null, dayOfWeek: null, categoryTrends: null },
    analytics: { },
    race: { engineer1: null, engineer2: null, engineer3: null, firstFinisher: null, winnerAnnounced: false },
    greenie: { lastShowTime: 0, lastQuotes: [] },
    wake: { wakeLock: null, audioCtx: null, silentOsc: null, keepAliveVideo: null },
  };

  // ==================== UTILITIES ====================
  
  function adjustColor(hex, percent) {
    const clean = hex.replace('#', '');
    if (clean.length < 6) return hex;
    const num = parseInt(clean, 16);
    if (Number.isNaN(num)) return hex;
    const r = (num >> 16) & 255, g = (num >> 8) & 255, b = num & 255;
    const target = percent < 0 ? 0 : 255, p = Math.abs(percent) / 100;
    return `rgb(${Math.round(r + (target - r) * p)}, ${Math.round(g + (target - g) * p)}, ${Math.round(b + (target - b) * p)})`;
  }

  function formatTimeAgo(timestamp) {
    const now = new Date(), then = new Date(timestamp), diffMs = now - then;
    const diffMins = Math.floor(diffMs / 60000);
    if (diffMins < 1) return 'just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    const diffHours = Math.floor(diffMins / 60);
    return diffHours < 24 ? `${diffHours}h ago` : then.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
  }

  function getEngineerColor(initials) {
    const colors = {
      'MT': '#ff6b35', 'MS': '#00d4ff', 'KS': '#a78bfa', 'MO': '#ffcc00',
      'ME': '#ff1ea3', 'BV': '#8cf04a', 'MK': '#ff9500',
    };
    return colors[initials] || '#8cf04a';
  }

  // ==================== THEME SETUP ====================
  
  Object.entries(cfg.theme).forEach(([key, value]) => {
    const cssKey = key === 'bg' ? '--bg' : key === 'ringPrimary' ? '--ring-primary' : key === 'ringSecondary' ? '--ring-secondary' : `--${key}`;
    DOM.root.style.setProperty(cssKey, value);
  });

  DOM.erasedTarget.textContent = cfg.targets.erased;
  if (cfg.targets.month && DOM.monthTarget) DOM.monthTarget.textContent = cfg.targets.month;

  // ==================== CHART FUNCTIONS ====================

  const donutDepthPlugin = {
    id: 'donutDepth',
    afterDatasetsDraw(chart) {
      const meta = chart.getDatasetMeta(0), arc = meta?.data?.[0];
      if (!arc) return;
      const { ctx, x, y, innerRadius, outerRadius } = arc;
      if (!Number.isFinite(x) || !Number.isFinite(y) || !Number.isFinite(innerRadius) || !Number.isFinite(outerRadius)) return;
      const ringThickness = outerRadius - innerRadius;
      if (ringThickness <= 0) return;

      // Shadow
      ctx.save();
      ctx.globalCompositeOperation = 'destination-over';
      try {
        const shadowGrad = ctx.createRadialGradient(x, y + ringThickness * 0.45, innerRadius, x, y + ringThickness * 0.45, outerRadius + 12);
        shadowGrad.addColorStop(0, 'rgba(0, 0, 0, 0.18)');
        shadowGrad.addColorStop(1, 'rgba(0, 0, 0, 0)');
        ctx.fillStyle = shadowGrad;
        ctx.beginPath();
        ctx.arc(x, y, outerRadius + 10, 0, Math.PI * 2);
        ctx.fill();
      } catch (e) { console.warn('Shadow gradient error:', e); }
      ctx.restore();

      // Gloss
      ctx.save();
      try {
        const shineGrad = ctx.createRadialGradient(x, y - ringThickness * 0.65, Math.max(innerRadius * 0.35, 0), x, y - ringThickness * 0.65, outerRadius);
        shineGrad.addColorStop(0, 'rgba(255, 255, 255, 0.35)');
        shineGrad.addColorStop(0.6, 'rgba(255, 255, 255, 0)');
        ctx.fillStyle = shineGrad;
        ctx.beginPath();
        ctx.arc(x, y, outerRadius, 0, Math.PI * 2);
        ctx.arc(x, y, innerRadius, 0, Math.PI * 2, true);
        ctx.closePath();
        ctx.fill();
      } catch (e) { console.warn('Shine gradient error:', e); }
      ctx.restore();
    },
  };

  Chart.register(donutDepthPlugin);

  function createDonutChart(canvasId) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return null;
    const primary = getComputedStyle(DOM.root).getPropertyValue('--ring-primary').trim();
    const secondary = getComputedStyle(DOM.root).getPropertyValue('--ring-secondary').trim();
    return new Chart(canvas, {
      type: 'doughnut',
      data: { labels: ['Value', 'Remaining'], datasets: [{ data: [0, 0], backgroundColor: [secondary, primary], borderWidth: 0, hoverOffset: 8 }] },
      options: { responsive: true, cutout: '68%', animation: { duration: 400 }, plugins: { legend: { display: false }, tooltip: { enabled: true } } }
    });
  }

  function updateDonut(chart, value, target) {
    const remaining = Math.max(target - value, 0);
    chart.data.datasets[0].data = [value, remaining];
    chart.canvas.dataset.target = target;
    chart.update();
    const container = chart.canvas.closest('.donut-card');
    if (container) {
      container.classList.add('pulse-update');
      setTimeout(() => container.classList.remove('pulse-update'), 600);
    }
  }

  // ==================== DATA FETCHING ====================

  async function refreshSummary() {
    try {
      const res = await fetch('/metrics/summary');
      if (!res.ok) throw new Error('HTTP ' + res.status);
      const data = await res.json();
      DOM.totalTodayValue.textContent = data.todayTotal || 0;
      DOM.monthTotalValue.textContent = data.monthTotal || 0;
      updateDonut(state.charts.totalToday, data.todayTotal || 0, cfg.targets.erased);
      updateDonut(state.charts.month, data.monthTotal || 0, cfg.targets.month || 10000);
      DOM.lastUpdated.textContent = 'Last updated: ' + new Date().toLocaleTimeString();
      DOM.staleIndicator.classList.add('hidden');
    } catch (err) {
      console.error('Summary refresh error:', err);
      DOM.staleIndicator.classList.remove('hidden');
    }
  }

  async function refreshLeaderboard() {
    try {
      const res = await fetch('/metrics/engineers/leaderboard?scope=today&limit=5');
      if (!res.ok) throw new Error('HTTP ' + res.status);
      const data = await res.json();
      DOM.leaderboardBody.innerHTML = '';
      (data.items || []).slice(0, 3).forEach((row, idx) => {
        const tr = document.createElement('tr');
        if (idx === 0) tr.classList.add('leader');
        tr.innerHTML = `<td><span class="engineer-badge" style="background-color: ${getEngineerColor(row.initials || '')}"></span>${row.initials || ''}</td><td class="value-strong">${row.erasures || 0}</td><td class="time-ago">${formatTimeAgo(row.lastActive)}</td>`;
        DOM.leaderboardBody.appendChild(tr);
      });
      updateRace(data.items || []);
    } catch (err) {
      console.error('Leaderboard refresh error:', err);
    }
  }

  async function refreshByTypeCounts() {
    try {
      const res = await fetch('/metrics/by-type');
      if (!res.ok) throw new Error('HTTP ' + res.status);
      const data = await res.json();
      const counts = {
        laptops_desktops: data['laptops_desktops'] || 0,
        servers: data['servers'] || 0,
        macs: data['macs'] || 0,
        mobiles: data['mobiles'] || 0,
      };
      categories.forEach(c => {
        const el = document.getElementById(c.countId);
        if (el) el.textContent = counts[c.key] || 0;
      });
      renderBars(counts);
    } catch (err) {
      console.error('By-type refresh error:', err);
    }
  }

  // ==================== RACE LOGIC ====================

  function updateRace(leaderboardData) {
    const topEngineers = leaderboardData.slice(0, 5);
    const maxErasures = topEngineers.length > 0 ? topEngineers[0].erasures || 1 : 1;

    for (let i = 1; i <= 5; i++) {
      const carEl = document.getElementById(`racePos${i}`), trailEl = document.getElementById(`trail${i}`), labelEl = document.getElementById(`driver${i}`);
      if (!carEl || !trailEl || !labelEl) continue;
      const engineer = topEngineers[i - 1];
      
      if (engineer) {
        const erasures = engineer.erasures || 0;
        let percentage = Math.min((erasures / maxErasures) * 100, 80);
        carEl.style.bottom = `${percentage}%`;
        trailEl.style.height = `${percentage}%`;
        const engineerColor = getEngineerColor(engineer.initials || '');
        trailEl.style.background = `linear-gradient(to top, ${engineerColor}, ${engineerColor}40)`;
        labelEl.textContent = `${engineer.initials || '?'}`;
        labelEl.style.color = engineerColor;
        if (erasures >= maxErasures && !engineer.finished) {
          engineer.finished = true;
          if (!state.race.firstFinisher) {
            state.race.firstFinisher = engineer;
            announceWinner();
          }
        }
      } else {
        carEl.style.bottom = '0%';
        trailEl.style.height = '0%';
        labelEl.textContent = '—';
        labelEl.style.color = 'var(--muted)';
      }
    }
  }

  function announceWinner() {
    const winner = state.race.engineer1;
    if (!winner) return;
    DOM.winnerText.textContent = `🏆 ${winner.initials} WINS! 🏆`;
    DOM.winnerSubtext.textContent = `${winner.erasures} erasures today`;
    DOM.winnerModal.classList.remove('hidden');
    triggerConfetti();
    setTimeout(() => DOM.winnerModal.classList.add('hidden'), 5000);
  }

  function triggerConfetti() {
    if (typeof confetti === 'undefined') return;
    const colors = ['#ff1ea3', '#8cf04a', '#00d4ff', '#ffcc00', '#ff6b35', '#a78bfa'];
    const defaults = { origin: { y: 0 }, zIndex: 10000 };
    confetti({ ...defaults, particleCount: 100, spread: 70, startVelocity: 55, colors });
    setTimeout(() => confetti({ ...defaults, particleCount: 50, spread: 100, startVelocity: 45, colors }), 150);
  }

  function renderBars(counts) {
    const total = Object.values(counts).reduce((a, b) => a + b, 0) || 1;
    DOM.byTypeBars.innerHTML = '';
    categories.forEach(def => {
      const val = counts[def.key] || 0, pct = Math.round((val / total) * 100);
      const row = document.createElement('div');
      row.className = 'bar-row';
      row.innerHTML = `<div class="bar-label">${def.label}</div><div class="bar-track"><div class="bar-fill" style="width:${pct}%"></div></div><div class="bar-value">${val}</div>`;
      DOM.byTypeBars.appendChild(row);
    });
  }

  // ==================== ANALYTICS ====================

  async function fetchAnalytics() {
    try {
      const [categoryTrends, engineerStats, peakHours, dayPatterns] = await Promise.all([
        fetch('/analytics/weekly-category-trends').then(r => r.json()),
        fetch('/analytics/weekly-engineer-stats').then(r => r.json()),
        fetch('/analytics/peak-hours').then(r => r.json()),
        fetch('/analytics/day-of-week-patterns').then(r => r.json())
      ]);
      return { categoryTrends, engineerStats, peakHours, dayPatterns };
    } catch (error) {
      console.error('Failed to fetch analytics:', error);
      return null;
    }
  }

  async function initializeAnalytics() {
    const analytics = await fetchAnalytics();
    if (!analytics) {
      console.warn('Analytics data unavailable, skipping chart setup');
      return;
    }
    // Chart creation would go here
  }

  // ==================== FLIP CARDS ====================

  function setupFlipCards() {
    const flipCards = document.querySelectorAll('.flip-card');
    if (flipCards.length === 0) {
      console.error('❌ No flip cards found!');
      return;
    }

    const flipIntervals = [25000, 28000, 31000, 26000];
    const displayDuration = 8000;

    flipCards.forEach((card, index) => {
      const interval = flipIntervals[index % flipIntervals.length];

      function performFlip() {
        card.classList.toggle('flipped');
      }

      // Initial flip after 2 seconds
      setTimeout(() => {
        performFlip();
        // Setup recurring flips
        setTimeout(() => {
          setInterval(() => {
            performFlip();
            setTimeout(performFlip, displayDuration);
          }, interval);
        }, displayDuration);
      }, 2000);
    });
  }

  // ==================== INITIALIZATION ====================

  state.charts.totalToday = createDonutChart('chartTotalToday');
  state.charts.month = createDonutChart('chartMonthToday');

  // Initial data loads
  await Promise.all([
    refreshSummary(),
    refreshLeaderboard(),
    refreshByTypeCounts()
  ]);

  // Setup recurring updates
  setInterval(() => {
    refreshSummary();
    refreshLeaderboard();
    refreshByTypeCounts();
  }, cfg.refreshSeconds * 1000);

  // Setup analytics and flips
  setTimeout(async () => {
    await initializeAnalytics();
    setupFlipCards();
  }, 500);

  setInterval(initializeAnalytics, 300000); // Every 5 minutes

})();

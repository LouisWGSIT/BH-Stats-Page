(async function () {
  const authUiApi = window.DashboardAuthUI && typeof window.DashboardAuthUI.init === 'function'
    ? window.DashboardAuthUI.init()
    : null;
  if (authUiApi && typeof authUiApi.ensureAuthenticated === 'function') {
    await authUiApi.ensureAuthenticated();
  }

  // Now proceed with dashboard initialization
  const cfg = await fetch('/config.json').then(r => r.json());
  const SHIFT_START = 8;
  const SHIFT_END = 16;
  const SHIFT_HOURS = SHIFT_END - SHIFT_START;

  const categories = [
    { key: 'laptops_desktops', label: 'Laptops/Desktops', listId: 'topLD', countId: 'countLD' },
    { key: 'servers', label: 'Servers', listId: 'topServers', countId: 'countServers' },
    { key: 'macs', label: 'Macs', listId: 'topMacs', countId: 'countMacs' },
    { key: 'mobiles', label: 'Mobiles', listId: 'topMobiles', countId: 'countMobiles' },
  ];

  const speedChallengeData = {
    am: { wasActive: false, isFinished: false },
    pm: { wasActive: false, isFinished: false },
  };

  const raceData = {
    winnerAnnounced: false,
    firstFinisher: null,
    engineer1: null,
    engineer2: null,
    engineer3: null,
  };

  const leaderboardState = {
    leader: null,
    gap: null,
    lastRaceSize: 0,
    lastLeaderCount: 0,
  };

  const keepAliveApi = (window.DisplayKeepAlive && typeof window.DisplayKeepAlive.init === 'function')
    ? window.DisplayKeepAlive.init()
    : null;

  function keepScreenAlive() {
    if (keepAliveApi && typeof keepAliveApi.ping === 'function') {
      keepAliveApi.ping();
    }
  }

  function truncateInitials(initials) {
    const value = (initials || '').toString().trim();
    if (!value) return '—';
    return value.length > 12 ? `${value.slice(0, 12)}...` : value;
  }

  function renderTopList(listId, engineers) {
    const listEl = document.getElementById(listId);
    if (!listEl) return;
    listEl.innerHTML = '';
    const rows = Array.isArray(engineers) ? engineers : [];
    if (rows.length === 0) {
      listEl.innerHTML = '<li><span class="no-data">No data yet</span></li>';
      return;
    }
    const fragment = document.createDocumentFragment();
    rows.forEach((row) => {
      const name = truncateInitials((row.initials || '').toString().trim());
      const value = row.count ?? row.erasures ?? 0;
      const li = document.createElement('li');
      li.innerHTML = `
        <span class="engineer-chip">
          <span class="engineer-avatar" style="background-image: url(${getAvatarDataUri(name)})"></span>
          <span class="engineer-name">${name}</span>
        </span>
        <span class="value">${value}</span>
      `;
      fragment.appendChild(li);
    });
    listEl.appendChild(fragment);
  }

  let greenieHideTimer = null;
  let lastGreeniePulse = '';

  function triggerGreenie(message) {
    const container = document.getElementById('greenieContainer');
    const wrapper = container ? container.querySelector('.greenie-wrapper') : null;
    const quote = document.getElementById('greenieQuote');
    if (!container || !wrapper || !quote) return;

    quote.textContent = message || 'Keep pushing, team.';
    container.classList.remove('hidden');
    wrapper.classList.remove('exit');
    void wrapper.offsetWidth;

    if (greenieHideTimer) {
      clearTimeout(greenieHideTimer);
      greenieHideTimer = null;
    }

    greenieHideTimer = setTimeout(() => {
      wrapper.classList.add('exit');
      setTimeout(() => {
        container.classList.add('hidden');
        wrapper.classList.remove('exit');
      }, 1900);
    }, 7000);
  }

  function checkGreenieTime() {
    const now = new Date();
    if (now.getMinutes() !== 0) return;
    const pulseKey = `${now.getFullYear()}-${now.getMonth()}-${now.getDate()}-${now.getHours()}`;
    if (pulseKey === lastGreeniePulse) return;
    lastGreeniePulse = pulseKey;
    triggerGreenie('Hourly check-in: keep the momentum rolling.');
  }

  function triggerRaceConfetti() {
    if (typeof confetti === 'undefined') return;
    const palette = ['#ff1ea3', '#8cf04a', '#00d4ff', '#ffcc00'];
    confetti({
      particleCount: 50,
      spread: 80,
      startVelocity: 38,
      origin: { y: 0.35 },
      colors: palette,
      zIndex: 10000,
      disableForReducedMotion: true,
    });
  }

  function createDonutChart(canvasId, color) {
    const canvas = document.getElementById(canvasId);
    if (!canvas || typeof Chart === 'undefined') return null;
    const ctx = canvas.getContext('2d');
    return new Chart(ctx, {
      type: 'doughnut',
      data: {
        labels: ['Value', 'Remaining'],
        datasets: [{
          data: [0, 1],
          backgroundColor: [color, 'rgba(255,255,255,0.08)'],
          borderWidth: 0,
          hoverOffset: 0,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        cutout: '72%',
        plugins: {
          legend: { display: false },
          tooltip: { enabled: false },
        },
      },
    });
  }

  const totalTodayChart = createDonutChart('chartTotalToday', '#ff1ea3');
  const monthChart = createDonutChart('chartMonthToday', '#8cf04a');

  async function refreshSummary() {}
  async function refreshAllTopLists() {}
  async function refreshByTypeCounts() {}

  function animateNumberUpdate(elementId) {
    const el = document.getElementById(elementId);
    if (!el) return;

    const rawText = (el.textContent || '').trim();
    const numericText = rawText.replace(/,/g, '');
    const isPlainInteger = /^-?\d+$/.test(numericText);

    // Always trigger a lightweight visual pulse even for non-numeric labels.
    el.classList.remove('count-animating');
    void el.offsetWidth;
    el.classList.add('count-animating');

    if (!isPlainInteger) {
      return;
    }

    const currentValue = parseInt(numericText, 10);
    const prevAttr = el.getAttribute('data-prev-value');
    const previousValue = prevAttr == null ? currentValue : parseInt(prevAttr, 10);

    if (Number.isNaN(previousValue) || previousValue === currentValue) {
      el.setAttribute('data-prev-value', String(currentValue));
      return;
    }

    const startTs = performance.now();
    const duration = 450;
    const start = previousValue;
    const delta = currentValue - previousValue;

    function frame(now) {
      const progress = Math.min((now - startTs) / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      const value = Math.round(start + delta * eased);
      el.textContent = value.toLocaleString();

      if (progress < 1) {
        requestAnimationFrame(frame);
      } else {
        el.textContent = currentValue.toLocaleString();
        el.setAttribute('data-prev-value', String(currentValue));
      }
    }

    requestAnimationFrame(frame);
  }

  // ==================== ALL TIME TOTALS ====================
  const allTimeTotalsApi = (window.AllTimeTotals && typeof window.AllTimeTotals.init === 'function')
    ? window.AllTimeTotals.init({
        animateNumberUpdate,
      })
    : null;

  async function refreshAllTimeTotals() {
    if (allTimeTotalsApi && typeof allTimeTotalsApi.refreshAllTimeTotals === 'function') {
      return allTimeTotalsApi.refreshAllTimeTotals();
    }
  }

  const competitionAnnouncementsApi = (window.CompetitionAnnouncements && typeof window.CompetitionAnnouncements.init === 'function')
    ? window.CompetitionAnnouncements.init({
        getSpeedChallengeData: () => speedChallengeData,
        getRaceData: () => raceData,
        escapeHtml: (text) => escapeHtml(text),
      })
    : null;

  async function refreshSpeedChallenge(windowName, listId, statusId) {
    if (!competitionAnnouncementsApi || typeof competitionAnnouncementsApi.refreshSpeedChallenge !== 'function') {
      return;
    }
    return competitionAnnouncementsApi.refreshSpeedChallenge(windowName, listId, statusId);
  }

  async function refreshCategorySpecialists() {
    if (!competitionAnnouncementsApi || typeof competitionAnnouncementsApi.refreshCategorySpecialists !== 'function') {
      return;
    }
    return competitionAnnouncementsApi.refreshCategorySpecialists();
  }

  async function refreshConsistency() {
    if (!competitionAnnouncementsApi || typeof competitionAnnouncementsApi.refreshConsistency !== 'function') {
      return;
    }
    return competitionAnnouncementsApi.refreshConsistency();
  }

  const raceLeaderboardApi = (window.RaceLeaderboard && typeof window.RaceLeaderboard.init === 'function')
    ? window.RaceLeaderboard.init({
        getEngineerColor,
        getAvatarDataUri,
        formatTimeAgo,
        getRaceData: () => raceData,
        announceWinner,
        triggerRaceConfetti,
        triggerGreenie,
      })
    : null;

  async function refreshLeaderboard() {
    if (!raceLeaderboardApi || typeof raceLeaderboardApi.refreshLeaderboard !== 'function') {
      return;
    }
    return raceLeaderboardApi.refreshLeaderboard();
  }

  function updateRace(leaderboardData) {
    if (!raceLeaderboardApi || typeof raceLeaderboardApi.updateRace !== 'function') {
      return;
    }
    return raceLeaderboardApi.updateRace(leaderboardData);
  }

  function checkAndTriggerWinner() {
    if (!competitionAnnouncementsApi || typeof competitionAnnouncementsApi.checkAndTriggerWinner !== 'function') {
      return;
    }
    return competitionAnnouncementsApi.checkAndTriggerWinner();
  }

  async function announceWinner() {
    if (!competitionAnnouncementsApi || typeof competitionAnnouncementsApi.announceWinner !== 'function') {
      return;
    }
    return competitionAnnouncementsApi.announceWinner();
  }

  function renderBars(counts) {
    const total = Object.values(counts).reduce((a, b) => a + b, 0) || 1;
    const defs = categories;
    const container = document.getElementById('byTypeBars');
    if (!container) return;
    container.innerHTML = '';
    
    // Use DocumentFragment for better performance
    const fragment = document.createDocumentFragment();
    defs.forEach(def => {
      const val = counts[def.key] || 0;
      const pct = Math.round((val / total) * 100);
      const row = document.createElement('div');
      row.className = 'bar-row';
      row.innerHTML = `
        <div class="bar-label">${def.label}</div>
        <div class="bar-track"><div class="bar-fill" style="width:${pct}%"></div></div>
        <div class="bar-value">${val}</div>
      `;
      fragment.appendChild(row);
    });
    container.appendChild(fragment);
  }

  function updateDonut(chart, value, target) {
    const remaining = Math.max(target - value, 0);
    chart.data.datasets[0].data = [value, remaining];
    chart.canvas.dataset.target = target;
    chart.update('none'); // Skip animation for better performance
    
    // Trigger pulse animation on chart container
    const container = chart.canvas.closest('.donut-card');
    if (container) {
      container.classList.add('pulse-update');
      setTimeout(() => container.classList.remove('pulse-update'), 600);
    }
  }

  function formatDuration(sec) {
    if (sec == null || isNaN(sec)) return '--:--';
    const m = Math.floor(sec / 60);
    const s = Math.floor(sec % 60);
    return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  }

  function getEngineerColor(initials) {
    const colors = ['#ff1ea3', '#8cf04a', '#00d4ff', '#ffcc00', '#ff6b35', '#a78bfa', '#34d399', '#fb923c'];
    let hash = 0;
    for (let i = 0; i < initials.length; i++) {
      hash = initials.charCodeAt(i) + ((hash << 5) - hash);
    }
    return colors[Math.abs(hash) % colors.length];
  }

  const avatarCache = new Map();

  function shadeColor(hex, factor) {
    const num = parseInt(hex.replace('#', ''), 16);
    const r = Math.max(0, Math.min(255, Math.round(((num >> 16) & 0xff) * factor)));
    const g = Math.max(0, Math.min(255, Math.round(((num >> 8) & 0xff) * factor)));
    const b = Math.max(0, Math.min(255, Math.round((num & 0xff) * factor)));
    return `#${(r << 16 | g << 8 | b).toString(16).padStart(6, '0')}`;
  }

  function getAvatarDataUri(initials) {
    if (avatarCache.has(initials)) return avatarCache.get(initials);
    
    const base = getEngineerColor(initials || '');
    const light = shadeColor(base, 1.4);
    const dark = shadeColor(base, 0.5);
    const veryDark = shadeColor(base, 0.3);
    
    let hash = 0;
    for (let i = 0; i < initials.length; i++) {
      hash = initials.charCodeAt(i) + ((hash << 5) - hash);
    }
    const absHash = Math.abs(hash);
    const variant = absHash % 16; // 16 different creature types
    
    const size = 8;
    const pixels = [];
    
    // Helper to add symmetric pixels
    const addPixel = (x, y, color) => {
      pixels.push({ x, y, color });
      if (x !== size - x - 1) {
        pixels.push({ x: size - x - 1, y, color });
      }
    };

    // Base head shape variants
    if (variant === 0) {
      // Round blob with big eyes
      addPixel(2, 1, base); addPixel(3, 1, base);
      addPixel(1, 2, base); addPixel(2, 2, light); addPixel(3, 2, light);
      addPixel(1, 3, base); addPixel(2, 3, light); addPixel(3, 3, base);
      addPixel(1, 4, base); addPixel(2, 4, dark); addPixel(3, 4, dark);
      addPixel(2, 5, base); addPixel(3, 5, base);
      // Eyes
      addPixel(2, 2, '#fff'); addPixel(2, 3, veryDark);
    } else if (variant === 1) {
      // Square head with antenna
      addPixel(2, 0, light); // antenna
      addPixel(1, 1, base); addPixel(2, 1, light); addPixel(3, 1, light);
      addPixel(1, 2, base); addPixel(2, 2, base); addPixel(3, 2, base);
      addPixel(1, 3, base); addPixel(2, 3, light); addPixel(3, 3, light);
      addPixel(1, 4, base); addPixel(2, 4, base); addPixel(3, 4, base);
      addPixel(2, 5, dark);
      // Eyes
      addPixel(2, 2, '#fff'); addPixel(2, 3, '#0d1b2a');
    } else if (variant === 2) {
      // Cyclops
      addPixel(2, 1, base); addPixel(3, 1, base);
      addPixel(1, 2, base); addPixel(2, 2, light); addPixel(3, 2, light);
      addPixel(1, 3, base); addPixel(2, 3, light); addPixel(3, 3, light);
      addPixel(1, 4, base); addPixel(2, 4, base); addPixel(3, 4, base);
      addPixel(2, 5, dark); addPixel(3, 5, dark);
      // Single eye
      pixels.push({ x: 3, y: 2, color: '#fff' });
      pixels.push({ x: 4, y: 2, color: '#fff' });
      pixels.push({ x: 3, y: 3, color: '#0d1b2a' });
      pixels.push({ x: 4, y: 3, color: '#0d1b2a' });
    } else if (variant === 3) {
      // Horned creature
      addPixel(1, 0, dark); addPixel(3, 0, dark);
      addPixel(1, 1, base); addPixel(2, 1, light); addPixel(3, 1, light);
      addPixel(1, 2, base); addPixel(2, 2, light); addPixel(3, 2, light);
      addPixel(1, 3, base); addPixel(2, 3, base); addPixel(3, 3, base);
      addPixel(1, 4, base); addPixel(2, 4, dark); addPixel(3, 4, dark);
      addPixel(2, 5, base);
      // Eyes
      addPixel(2, 2, '#fff'); addPixel(2, 3, veryDark);
    } else if (variant === 4) {
      // Tall thin creature
      addPixel(2, 0, light); addPixel(3, 0, light);
      addPixel(2, 1, base); addPixel(3, 1, base);
      addPixel(2, 2, light); addPixel(3, 2, light);
      addPixel(2, 3, base); addPixel(3, 3, base);
      addPixel(2, 4, base); addPixel(3, 4, base);
      addPixel(2, 5, dark); addPixel(3, 5, dark);
      // Eyes
      pixels.push({ x: 3, y: 2, color: '#fff' });
      pixels.push({ x: 4, y: 2, color: '#fff' });
      pixels.push({ x: 3, y: 3, color: '#0d1b2a' });
    } else if (variant === 5) {
      // Wide creature with ears
      addPixel(0, 1, base); addPixel(1, 1, light); addPixel(2, 1, light); addPixel(3, 1, light);
      addPixel(0, 2, base); addPixel(1, 2, base); addPixel(2, 2, base); addPixel(3, 2, base);
      addPixel(1, 3, base); addPixel(2, 3, light); addPixel(3, 3, light);
      addPixel(1, 4, base); addPixel(2, 4, base); addPixel(3, 4, base);
      addPixel(2, 5, dark);
      // Eyes
      addPixel(1, 2, '#fff'); addPixel(2, 3, veryDark);
    } else if (variant === 6) {
      // Spiky top
      addPixel(1, 0, light); addPixel(2, 0, base); addPixel(3, 0, light);
      addPixel(1, 1, base); addPixel(2, 1, light); addPixel(3, 1, light);
      addPixel(1, 2, base); addPixel(2, 2, base); addPixel(3, 2, base);
      addPixel(1, 3, base); addPixel(2, 3, light); addPixel(3, 3, light);
      addPixel(1, 4, base); addPixel(2, 4, dark); addPixel(3, 4, dark);
      addPixel(2, 5, veryDark);
      // Eyes
      addPixel(2, 2, '#fff'); addPixel(2, 3, '#0d1b2a');
    } else if (variant === 7) {
      // Compact blob
      addPixel(1, 1, base); addPixel(2, 1, light); addPixel(3, 1, light);
      addPixel(1, 2, base); addPixel(2, 2, light); addPixel(3, 2, light);
      addPixel(1, 3, base); addPixel(2, 3, base); addPixel(3, 3, base);
      addPixel(1, 4, dark); addPixel(2, 4, dark); addPixel(3, 4, dark);
      // Eyes
      addPixel(2, 2, '#fff'); addPixel(2, 3, veryDark);
    } else if (variant === 8) {
      // Robot square head
      addPixel(1, 1, base); addPixel(2, 1, base); addPixel(3, 1, base);
      addPixel(1, 2, light); addPixel(2, 2, light); addPixel(3, 2, light);
      addPixel(1, 3, base); addPixel(2, 3, base); addPixel(3, 3, base);
      addPixel(1, 4, base); addPixel(2, 4, light); addPixel(3, 4, light);
      addPixel(2, 5, dark); addPixel(3, 5, dark);
      // Eyes
      addPixel(1, 2, '#fff'); addPixel(3, 2, '#fff');
      addPixel(1, 3, veryDark); addPixel(3, 3, veryDark);
    } else if (variant === 9) {
      // Triangle alien
      addPixel(3, 1, light);
      addPixel(2, 2, base); addPixel(3, 2, light);
      addPixel(1, 3, base); addPixel(2, 3, light); addPixel(3, 3, light);
      addPixel(0, 4, base); addPixel(1, 4, base); addPixel(2, 4, base); addPixel(3, 4, base);
      addPixel(1, 5, dark); addPixel(2, 5, dark);
      // Eyes
      addPixel(1, 3, '#fff'); addPixel(3, 3, '#fff');
      addPixel(1, 4, veryDark); addPixel(3, 4, veryDark);
    } else if (variant === 10) {
      // Rounded with double antenna
      addPixel(1, 0, light); addPixel(3, 0, light);
      addPixel(2, 1, base); addPixel(3, 1, base);
      addPixel(1, 2, base); addPixel(2, 2, light); addPixel(3, 2, light);
      addPixel(1, 3, base); addPixel(2, 3, base); addPixel(3, 3, base);
      addPixel(1, 4, dark); addPixel(2, 4, dark); addPixel(3, 4, dark);
      addPixel(2, 5, veryDark);
      // Eyes
      addPixel(2, 2, '#fff'); addPixel(2, 3, '#0d1b2a');
    } else if (variant === 11) {
      // Side-eye creature
      addPixel(1, 1, base); addPixel(2, 1, light); addPixel(3, 1, light);
      addPixel(1, 2, base); addPixel(2, 2, base); addPixel(3, 2, base);
      addPixel(1, 3, light); addPixel(2, 3, light); addPixel(3, 3, light);
      addPixel(1, 4, base); addPixel(2, 4, dark); addPixel(3, 4, dark);
      addPixel(2, 5, veryDark);
      // Side eyes
      addPixel(1, 2, '#fff'); addPixel(3, 2, '#fff');
      pixels.push({ x: 1, y: 3, color: veryDark });
      pixels.push({ x: 3, y: 3, color: veryDark });
    } else if (variant === 12) {
      // Tall narrow creature
      addPixel(2, 0, base); addPixel(3, 0, base);
      addPixel(2, 1, light); addPixel(3, 1, light);
      addPixel(2, 2, base); addPixel(3, 2, base);
      addPixel(2, 3, light); addPixel(3, 3, light);
      addPixel(2, 4, base); addPixel(3, 4, base);
      addPixel(2, 5, dark); addPixel(3, 5, dark);
      addPixel(2, 6, veryDark);
      // Small eyes
      pixels.push({ x: 3, y: 2, color: '#fff' });
      pixels.push({ x: 4, y: 2, color: '#fff' });
      pixels.push({ x: 3, y: 3, color: '#0d1b2a' });
    } else if (variant === 13) {
      // Wide flat creature
      addPixel(0, 2, base); addPixel(1, 2, light); addPixel(2, 2, light); addPixel(3, 2, light);
      addPixel(0, 3, base); addPixel(1, 3, base); addPixel(2, 3, base); addPixel(3, 3, base);
      addPixel(0, 4, dark); addPixel(1, 4, dark); addPixel(2, 4, dark); addPixel(3, 4, dark);
      addPixel(1, 5, veryDark); addPixel(2, 5, veryDark);
      // Wide eyes
      addPixel(1, 3, '#fff'); addPixel(3, 3, '#fff');
      pixels.push({ x: 1, y: 4, color: '#0d1b2a' });
      pixels.push({ x: 3, y: 4, color: '#0d1b2a' });
    } else if (variant === 14) {
      // Mohawk creature
      addPixel(2, 0, light); 
      addPixel(1, 1, base); addPixel(2, 1, light); addPixel(3, 1, base);
      addPixel(1, 2, base); addPixel(2, 2, light); addPixel(3, 2, light);
      addPixel(1, 3, base); addPixel(2, 3, base); addPixel(3, 3, base);
      addPixel(1, 4, dark); addPixel(2, 4, dark); addPixel(3, 4, dark);
      addPixel(2, 5, veryDark);
      // Eyes
      addPixel(2, 2, '#fff'); addPixel(2, 3, veryDark);
    } else {
      // Rounded ears creature
      addPixel(0, 1, light); addPixel(1, 1, base); addPixel(2, 1, light); addPixel(3, 1, light);
      addPixel(1, 2, base); addPixel(2, 2, light); addPixel(3, 2, light);
      addPixel(1, 3, base); addPixel(2, 3, base); addPixel(3, 3, base);
      addPixel(1, 4, dark); addPixel(2, 4, dark); addPixel(3, 4, dark);
      addPixel(2, 5, veryDark);
      // Eyes
      addPixel(2, 2, '#fff'); addPixel(2, 3, '#0d1b2a');
    }

    const rects = pixels.map(p => `<rect x="${p.x}" y="${p.y}" width="1" height="1" fill="${p.color}"/>`).join('');
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 ${size} ${size}" shape-rendering="crispEdges">${rects}</svg>`;
    const uri = `data:image/svg+xml,${encodeURIComponent(svg)}`;
    avatarCache.set(initials, uri);
    return uri;
  }

  function formatTimeAgo(timestamp) {
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
  }

  // ==================== ANALYTICS & FLIP CARDS ====================
  const analyticsChartsApi = (window.AnalyticsCharts && typeof window.AnalyticsCharts.init === 'function')
    ? window.AnalyticsCharts.init({
        cfg,
        getAvatarDataUri,
        truncateInitials,
      })
    : null;

  async function fetchAnalytics() {
    if (!analyticsChartsApi || typeof analyticsChartsApi.fetchAnalytics !== 'function') return null;
    return analyticsChartsApi.fetchAnalytics();
  }

  function createPeakHoursChart(data) {
    if (analyticsChartsApi && typeof analyticsChartsApi.createPeakHoursChart === 'function') {
      return analyticsChartsApi.createPeakHoursChart(data);
    }
  }

  function createDayOfWeekChart(data) {
    if (analyticsChartsApi && typeof analyticsChartsApi.createDayOfWeekChart === 'function') {
      return analyticsChartsApi.createDayOfWeekChart(data);
    }
  }

  function createWeeklyCategoryTrendsChart(data) {
    if (analyticsChartsApi && typeof analyticsChartsApi.createWeeklyCategoryTrendsChart === 'function') {
      return analyticsChartsApi.createWeeklyCategoryTrendsChart(data);
    }
  }

  function updateWeeklyLeaderboard(data) {
    if (analyticsChartsApi && typeof analyticsChartsApi.updateWeeklyLeaderboard === 'function') {
      return analyticsChartsApi.updateWeeklyLeaderboard(data);
    }
  }

  async function initializeAnalytics() {
    if (!analyticsChartsApi || typeof analyticsChartsApi.initializeAnalytics !== 'function') {
      return;
    }
    return analyticsChartsApi.initializeAnalytics();
  }

  // ==================== NEW FLIP CARDS DATA ====================

  function updateRecordsMilestones() {
    const overallEl = document.getElementById('recordOverallErasures');
    const bestDayEl = document.getElementById('recordBestDay');
    const bestDateEl = document.getElementById('recordBestDayDate');
    const topEngEl = document.getElementById('recordTopEngineer');
    const topCountEl = document.getElementById('recordTopEngineerCount');
    const streakEl = document.getElementById('currentStreak');
    const mostHourEl = document.getElementById('recordMostHour');
    const mostHourDateEl = document.getElementById('recordMostHourDate');
    const mostWeekEl = document.getElementById('recordMostWeek');
    const mostWeekDateEl = document.getElementById('recordMostWeekDate');

    fetch('/metrics/records')
      .then(r => r.json())
      .then(data => {
        console.log('Records data:', data); // Debug log

        // Overall Erasures (all-time)
        if (overallEl && typeof data.overallErasures === 'number') {
          overallEl.textContent = data.overallErasures;
        }

        // Best Day Ever
        if (data.bestDay && data.bestDay.count) {
          if (bestDayEl) bestDayEl.textContent = data.bestDay.count;
          if (bestDateEl && data.bestDay.date) {
            bestDateEl.textContent = new Date(data.bestDay.date).toLocaleDateString();
          }
        }

        // Top Engineer (All-Time)
        if (data.topEngineer && data.topEngineer.initials) {
          if (topEngEl) topEngEl.textContent = data.topEngineer.initials;
          if (topCountEl) topCountEl.textContent = `${data.topEngineer.totalCount || 0} erasures`;
        }

        // Current Streak
        if (typeof data.currentStreak === 'number' && data.currentStreak > 0) {
          if (streakEl) streakEl.textContent = data.currentStreak;
        }

        // Most Erased in 1 Hour
        if (data.mostHour && typeof data.mostHour.count === 'number') {
          if (mostHourEl) mostHourEl.textContent = data.mostHour.count;
          if (mostHourDateEl && data.mostHour.date) {
            mostHourDateEl.textContent = new Date(data.mostHour.date).toLocaleDateString();
          }
        }

        // Most Erased in 1 Week
        if (data.mostWeek && typeof data.mostWeek.count === 'number') {
          if (mostWeekEl) mostWeekEl.textContent = data.mostWeek.count;
          if (mostWeekDateEl && data.mostWeek.date) {
            mostWeekDateEl.textContent = new Date(data.mostWeek.date).toLocaleDateString();
          }
        }
      })
      .catch(err => {
        console.error('Records fetch error:', err);
      });
  }

  function updateWeeklyRecords() {
    const weekTotalEl = document.getElementById('weekTotal');
    const weekBestDayEl = document.getElementById('weekBestDay');
    const weekBestDayDateEl = document.getElementById('weekBestDayDate');
    const weekAverageEl = document.getElementById('weekAverage');

    fetch('/metrics/weekly')
      .then(r => r.json())
      .then(data => {
        if (weekTotalEl) weekTotalEl.textContent = data.weekTotal || 0;
        if (weekBestDayEl) weekBestDayEl.textContent = data.bestDayOfWeek?.count || 0;
        if (weekBestDayDateEl && data.bestDayOfWeek?.date) {
          weekBestDayDateEl.textContent = new Date(data.bestDayOfWeek.date).toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' });
        }
        if (weekAverageEl) weekAverageEl.textContent = data.weekAverage || 0;
      })
      .catch(err => {
        console.error('Weekly stats fetch error:', err);
      });

    // Fetch Mon-Fri breakdown for this week
    fetch('/analytics/weekly-daily-totals')
      .then(r => r.json())
      .then(data => {
        const days = (data.days || []);
        // Map: 0=Mon, 1=Tue, 2=Wed, 3=Thu, 4=Fri
        const ids = ['monVal', 'tueVal', 'wedVal', 'thuVal', 'friVal'];
        for (let i = 0; i < 5; i++) {
          const el = document.getElementById(ids[i]);
          if (el) {
            el.textContent = days[i] ? days[i].count : '—';
          }
        }
      })
      .catch(err => {
        console.error('Weekly Mon-Fri breakdown fetch error:', err);
        // No fallback: leave values as-is if backend fails
      });
  }

  function updateTodayStats() {
    const leaderboard = Array.from(document.querySelectorAll('#leaderboardBody tr')).map(tr => {
      const cells = tr.querySelectorAll('td');
      return {
        initials: cells[0]?.textContent || '',
        count: parseInt(cells[1]?.textContent) || 0
      };
    });

    const activeCount = leaderboard.filter(e => e.count > 0).length;
    const todayTotal = parseInt(document.getElementById('totalTodayValue')?.textContent) || 0;
    const avgPerEng = activeCount > 0 ? Math.round(todayTotal / activeCount) : 0;

    const activeEl = document.getElementById('activeEngineers');
    const avgEl = document.getElementById('avgPerEngineer');
    const topHourEl = document.getElementById('topHour');
    const topHourCountEl = document.getElementById('topHourCount');

    if (activeEl) activeEl.textContent = activeCount;
    if (avgEl) avgEl.textContent = avgPerEng;
    
    // Fetch most productive hour from backend
    fetch('/analytics/peak-hours')
      .then(r => r.json())
      .then(data => {
        // Only use backend-provided hours
        const hours = Array.isArray(data) ? data : (data?.hours || []);
        if (hours.length > 0) {
          // Find hour with highest count
          const peakHour = hours.reduce((max, curr) => curr.count > max.count ? curr : max, hours[0]);
          if (topHourEl && peakHour.count > 0) {
            const hour12 = peakHour.hour === 0 ? 12 : peakHour.hour > 12 ? peakHour.hour - 12 : peakHour.hour;
            const ampm = peakHour.hour >= 12 ? 'PM' : 'AM';
            topHourEl.textContent = `${hour12}:00 ${ampm}`;
            if (topHourCountEl) topHourCountEl.textContent = `${peakHour.count} erasures`;
          } else {
            if (topHourEl) topHourEl.textContent = 'N/A';
            if (topHourCountEl) topHourCountEl.textContent = 'No data yet';
          }
        } else {
          if (topHourEl) topHourEl.textContent = 'N/A';
          if (topHourCountEl) topHourCountEl.textContent = 'No data yet';
        }
      })
      .catch(err => {
        console.error('Peak hours fetch error:', err);
        if (topHourEl) topHourEl.textContent = 'N/A';
        if (topHourCountEl) topHourCountEl.textContent = 'Error';
      });
  }

  function updateMonthlyProgress() {
    const monthTotal = parseInt(document.getElementById('monthTotalValue')?.textContent) || 0;
    const today = new Date().getDate();
    const daysInMonth = new Date(new Date().getFullYear(), new Date().getMonth() + 1, 0).getDate();
    const targetMonthly = parseInt(cfg.targets.month);
    const dailyAvg = Math.round(monthTotal / today);
    const projectedTotal = Math.round(dailyAvg * daysInMonth);
    const paceEl = document.getElementById('monthPaceStatus');
    if (paceEl) {
      paceEl.innerHTML = '';
      const icon = document.createElement('img');
      icon.className = 'pixel pace-icon';
      icon.width = 18;
      icon.height = 18;
      if (projectedTotal >= targetMonthly) {
        icon.src = 'assets/pace-on-pixel.svg';
        icon.alt = 'On Pace';
        paceEl.appendChild(icon);
        paceEl.appendChild(document.createTextNode(' On Pace'));
      } else {
        icon.src = 'assets/pace-behind-pixel.svg';
        icon.alt = 'Behind Pace';
        paceEl.appendChild(icon);
        paceEl.appendChild(document.createTextNode(' Behind Pace'));
      }
    }
    const projEl = document.getElementById('monthProjection');
    if (projEl) projEl.textContent = `Projected: ${projectedTotal} by end of month`;

    // Sparkline (daily erasures for the month)
    const monthSparkSVG = document.getElementById('monthSparklineSVG');
    if (monthSparkSVG) {
      fetch('/analytics/daily-totals')
        .then(r => r.json())
        .then(data => {
          const days = data.days || Array.from({length: daysInMonth}, (_, i) => ({day: i+1, count: 0}));
          const values = days.map(d => d.count);
          console.log('[SVG Sparkline] Monthly data:', values);
          renderSVGSparkline(monthSparkSVG, values);
        })
        .catch(e => {
          console.error('[SVG Sparkline] Error fetching monthly data:', e);
        });
    }

    // Stat list (unique monthly stats)
    const statList = document.getElementById('monthStatList');
    if (statList) {
      // Fetch top 4 engineers for the month and update chips efficiently to avoid flicker
      fetch('/metrics/engineers/leaderboard?scope=month&limit=4')
        .then(r => r.json())
        .then(data => {
          const engineers = (data.items || []).slice(0, 4);
          // If number of chips changed, rebuild; else update contents only
          if (statList.children.length !== engineers.length) {
            statList.innerHTML = '';
            engineers.forEach((row, idx) => {
              const li = document.createElement('li');
              const color = getEngineerColor(row.initials || '');
              const avatar = getAvatarDataUri(row.initials || '');
              li.innerHTML = `
                <span class=\"engineer-chip engineer-chip-vertical\">
                  <span class=\"engineer-avatar\" style=\"background-image: url(${avatar}); border-color: ${color}\"></span>
                  <span class=\"engineer-name\">${row.initials}</span>
                  <span class=\"engineer-count engineer-count-below\">${row.erasures || 0}</span>
                </span>`;
              statList.appendChild(li);
            });
          } else {
            engineers.forEach((row, idx) => {
              const li = statList.children[idx];
              const chip = li.querySelector('.engineer-chip');
              const avatarEl = chip.querySelector('.engineer-avatar');
              const nameEl = chip.querySelector('.engineer-name');
              const countEl = chip.querySelector('.engineer-count');
              avatarEl.style.backgroundImage = `url(${getAvatarDataUri(row.initials || '')})`;
              avatarEl.style.borderColor = getEngineerColor(row.initials || '');
              nameEl.textContent = row.initials;
              countEl.textContent = row.erasures || 0;
            });
          }
        });
    }

    // Progress bar and labels
    const fillEl = document.getElementById('monthTrackerFill');
    let percent = 0;
    if (targetMonthly > 0) {
      percent = Math.min(100, Math.round((monthTotal / targetMonthly) * 100));
    }
    if (fillEl) fillEl.style.width = percent + '%';
    const currentEl = document.getElementById('monthTrackerCurrent');
    if (currentEl) currentEl.textContent = monthTotal;
    const targetEl = document.getElementById('monthTrackerTarget');
    if (targetEl) targetEl.textContent = targetMonthly;
    // Hide days above target if present
    const daysAboveTarget = document.getElementById('monthDaysAboveTarget');
    if (daysAboveTarget) daysAboveTarget.style.display = 'none';
  }

  function updateRaceUpdates() {
    const leaderboardBody = document.getElementById('leaderboardBody');
    const rows = leaderboardBody?.querySelectorAll('tr') || [];
    
    if (rows.length >= 2) {
      const first = rows[0].querySelectorAll('td');
      const second = rows[1].querySelectorAll('td');
      if (first.length >= 2 && second.length >= 2) {
        // Extract initials from the .engineer-name span, not the whole cell
        const firstName = first[0].querySelector('.engineer-name')?.textContent.trim() || '?';
        const firstCount = parseInt(first[1].textContent.trim()) || 0;
        const secondName = second[0].querySelector('.engineer-name')?.textContent.trim() || '?';
        const secondCount = parseInt(second[1].textContent.trim()) || 0;
        const gap = firstCount - secondCount;
        
        // Trigger Greenie if leader changed or gap narrowed significantly
        if (leaderboardState.leader !== firstName) {
          leaderboardState.leader = firstName;
          const leaderQuotes = [
            `${firstName} takes the lead! All eyes on them! 👀`,
            `Fresh leader: ${firstName} is dominating today! 🔥`,
            `${firstName} just claimed the top spot! Impressive! 💪`,
            `🚨 NEW LEADER ALERT! ${firstName} is unstoppable right now! 🚨`,
            `Plot twist! ${firstName} just surged to first place! 📈`,
            `${firstName} said "Not today!" and took the lead! 💯`,
            `The momentum shifts! ${firstName} is in control now! 👑`
          ];
          triggerGreenie(leaderQuotes[Math.floor(Math.random() * leaderQuotes.length)]);
        } else if (leaderboardState.gap !== null && gap < leaderboardState.gap && gap <= 5) {
          const closingQuotes = [
            `${secondName} closing in on ${firstName}! This race is ON! 🏁`,
            `Gap tightening! ${secondName} is making moves! 🚀`,
            `Only ${gap} erasures between them! Tension rising! ⚡`,
            `🔥 DRAMA! The gap is shrinking! ${secondName} is RIGHT THERE! 🔥`,
            `${secondName} is not giving up! The pressure is ON for ${firstName}!`,
            `This is getting SPICY! ${gap} erasures - anything can happen! 🌶️`,
            `${secondName} is hunting! ${firstName}, watch your back! 👀`
          ];
          triggerGreenie(closingQuotes[Math.floor(Math.random() * closingQuotes.length)]);
        } else if (leaderboardState.gap !== null && gap > leaderboardState.gap + 3) {
          // Gap widening - momentum shift
          const breakawayQuotes = [
            `${firstName} is PULLING AWAY! Dominant performance! 🏃‍♂️💨`,
            `${firstName} is running away with this! The lead is growing! 📊`,
            `${firstName} putting on a MASTERCLASS right now! Incredible pace! 🎯`
          ];
          triggerGreenie(breakawayQuotes[Math.floor(Math.random() * breakawayQuotes.length)]);
        } else if (leaderboardState.gap !== null && rows.length > (leaderboardState.lastRaceSize || 0)) {
          // New competitor entered top 5
          const newCompetitorQuotes = [
            `We've got a new challenger in the top 5! The race is WIDE OPEN! 🆕`,
            `Fresh blood entering the race! This just got more interesting! 🎪`,
            `Another contender steps up! May the best engineer win! ⚡`
          ];
          triggerGreenie(newCompetitorQuotes[Math.floor(Math.random() * newCompetitorQuotes.length)]);
          leaderboardState.lastRaceSize = rows.length;
        } else if (leaderboardState.gap !== null && firstCount > (leaderboardState.lastLeaderCount || 0)) {
          // Leader is extending their lead organically
          const momentumQuotes = [
            `${firstName} keeps the pedal down! Steady progress! 💪`,
            `The momentum continues! ${firstName} is in the zone! 🎯`,
            `Consistency wins races! ${firstName} adding more to the lead! ✨`
          ];
          triggerGreenie(momentumQuotes[Math.floor(Math.random() * momentumQuotes.length)]);
        }
        leaderboardState.gap = gap;
        leaderboardState.lastLeaderCount = firstCount;
        
        const leaderGapEl = document.getElementById('leaderGap');
        if (leaderGapEl) {
          leaderGapEl.textContent = `${firstName} leads by ${gap} erasures`;
          animateNumberUpdate('leaderGap');
        }
        
        const closestRaceEl = document.getElementById('closestRace');
        if (closestRaceEl) {
          if (gap <= 5 && gap > 0) {
            closestRaceEl.textContent = `${secondName} closing in - only ${gap} behind!`;
          } else {
            closestRaceEl.textContent = 'Race is heating up! 🔥';
          }
        }
      }
    }
    
    if (rows.length >= 3) {
      const third = rows[2].querySelectorAll('td');
      if (third.length >= 2) {
        const thirdName = third[0].querySelector('.engineer-name')?.textContent.trim() || '?';
        const thirdCount = parseInt(third[1].textContent.trim()) || 0;
        const comebackEl = document.getElementById('comebackStory');
        if (comebackEl) {
          comebackEl.textContent = `${thirdName} making moves with ${thirdCount} erasures`;
        }
      }
    }
  }

  function updateCategoryChampions() {
    categories.forEach(cat => {
      const listEl = document.getElementById(cat.listId);
      if (listEl) {
        const firstItem = listEl.querySelector('li');
        if (firstItem) {
          const text = firstItem.textContent.trim();
          const parts = text.match(/(.+?)\s+(\d+)$/);
          if (parts) {
            const champId = cat.key === 'laptops_desktops' ? 'champLD' :
                           cat.key === 'servers' ? 'champServers' :
                           cat.key === 'macs' ? 'champMacs' : 'champMobiles';
            document.getElementById(champId).textContent = `${parts[1]} (${parts[2]})`;
          }
        }
      }

    });
  }

  function updateTargetTracker() {

    const todayTotal = parseInt(document.getElementById('totalTodayValue')?.textContent) || 0;
    const target = parseInt(cfg.targets.erased) || 500;
    const percentage = target > 0 ? Math.min((todayTotal / target) * 100, 100) : 0;

    // Shift hours: 8:00–16:00 (8 hours)
    const SHIFT_START = 8;
    const SHIFT_END = 16;
    const SHIFT_HOURS = SHIFT_END - SHIFT_START;
    const now = new Date();
    let hour = now.getHours();
    // Clamp hour to shift range
    if (hour < SHIFT_START) hour = SHIFT_START;
    if (hour > SHIFT_END) hour = SHIFT_END;
    const hoursElapsed = Math.max(1, hour - SHIFT_START + 1);
    const currentPace = todayTotal / hoursElapsed;
    const requiredPace = target / SHIFT_HOURS;

    // Pace indicator (pixel art icon)
    const statusEl = document.getElementById('trackerStatus');
    if (statusEl) {
      statusEl.innerHTML = '';
      const icon = document.createElement('img');
      icon.className = 'pixel pace-icon';
      icon.width = 18;
      icon.height = 18;
      if (currentPace >= requiredPace) {
        icon.src = 'assets/pace-on-pixel.svg';
        icon.alt = 'On Pace';
        statusEl.appendChild(icon);
        statusEl.appendChild(document.createTextNode(' On Pace'));
      } else {
        icon.src = 'assets/pace-behind-pixel.svg';
        icon.alt = 'Behind Pace';
        statusEl.appendChild(icon);
        statusEl.appendChild(document.createTextNode(' Behind Pace'));
      }
    }

    // Projected end
    const projectedEnd = Math.round(currentPace * SHIFT_HOURS);
    const projEl = document.getElementById('trackerProjection');
    if (projEl) projEl.textContent = `Projected: ${projectedEnd} by end of day`;

    // Sparkline (erasures per hour)
    const trackerSparkSVG = document.getElementById('trackerSparklineSVG');
    if (trackerSparkSVG) {
      fetch('/analytics/hourly-totals')
        .then(r => r.json())
        .then(data => {
          // Only use shift hours (8:00–15:00)
          const hours = (data.hours || [])
            .filter(h => h.hour >= SHIFT_START && h.hour < SHIFT_END);
          // Only use backend-provided hours
          const values = hours.map(h => h.count);
          console.log('[SVG Sparkline] Today tracker data:', values);
          renderSVGSparkline(trackerSparkSVG, values);
        })
        .catch(e => {
          console.error('[SVG Sparkline] Error fetching today tracker data:', e);
        });
    }

    // Stat list (unique daily stats)
    const statList = document.getElementById('trackerStatList');
    if (statList) {
      statList.innerHTML = '';
      const li1 = document.createElement('li');
      li1.textContent = `So far: ${todayTotal}`;
      const li2 = document.createElement('li');
      li2.textContent = `Best hour: --`;
      // Optionally fetch and fill best hour
      fetch('/analytics/peak-hours').then(r => r.json()).then(data => {
        const hours = Array.isArray(data) ? data : (data?.hours || []);
        if (hours.length > 0) {
          const peak = hours.reduce((max, curr) => curr.count > max.count ? curr : max, hours[0]);
          li2.textContent = `Best hour: ${peak.hour}:00 (${peak.count})`;
        }
      });
      statList.appendChild(li1);
      statList.appendChild(li2);
    }

    // Progress bar and labels
    const fillEl = document.getElementById('trackerFill');
    if (fillEl) fillEl.style.width = `${percentage}%`;
    const currentEl = document.getElementById('trackerCurrent');
    if (currentEl) currentEl.textContent = todayTotal;
    const targetEl = document.getElementById('trackerTarget');
    if (targetEl) targetEl.textContent = target;
  }

  const flipCardsUpdaterApi = (window.FlipCardsUpdater && typeof window.FlipCardsUpdater.init === 'function')
    ? window.FlipCardsUpdater.init({
        cfg,
        categories,
        leaderboardState,
        triggerGreenie,
        getEngineerColor,
        getAvatarDataUri,
        renderSVGSparkline,
        animateNumberUpdate,
      })
    : null;

  if (flipCardsUpdaterApi) {
    updateRecordsMilestones = function () {
      return flipCardsUpdaterApi.updateRecordsMilestones();
    };
    updateWeeklyRecords = function () {
      return flipCardsUpdaterApi.updateWeeklyRecords();
    };
    updateTodayStats = function () {
      return flipCardsUpdaterApi.updateTodayStats();
    };
    updateMonthlyProgress = function () {
      return flipCardsUpdaterApi.updateMonthlyProgress();
    };
    updateRaceUpdates = function () {
      return flipCardsUpdaterApi.updateRaceUpdates();
    };
    updateCategoryChampions = function () {
      return flipCardsUpdaterApi.updateCategoryChampions();
    };
    updateTargetTracker = function () {
      return flipCardsUpdaterApi.updateTargetTracker();
    };
  }

  const monthlyMomentumChartApi = (window.MonthlyMomentumChart && typeof window.MonthlyMomentumChart.init === 'function')
    ? window.MonthlyMomentumChart.init({
        cfg,
        analyticsCharts,
      })
    : null;

  async function createMonthlyMomentumChart() {
    if (!monthlyMomentumChartApi || typeof monthlyMomentumChartApi.createMonthlyMomentumChart !== 'function') {
      return;
    }
    return monthlyMomentumChartApi.createMonthlyMomentumChart();
  }

  // Flip/rotator lifecycle delegated to core module.
  const flipRotatorLifecycleApi = (window.FlipRotatorLifecycle && typeof window.FlipRotatorLifecycle.init === 'function')
    ? window.FlipRotatorLifecycle.init()
    : null;

  function cleanupFlipCards() {
    if (flipRotatorLifecycleApi && typeof flipRotatorLifecycleApi.cleanupFlipCards === 'function') {
      return flipRotatorLifecycleApi.cleanupFlipCards();
    }
  }

  function setupFlipCards() {
    if (flipRotatorLifecycleApi && typeof flipRotatorLifecycleApi.setupFlipCards === 'function') {
      return flipRotatorLifecycleApi.setupFlipCards();
    }
  }

  function cleanupRotatorCards() {
    if (flipRotatorLifecycleApi && typeof flipRotatorLifecycleApi.cleanupRotatorCards === 'function') {
      return flipRotatorLifecycleApi.cleanupRotatorCards();
    }
  }

  function setupRotatorCards() {
    if (flipRotatorLifecycleApi && typeof flipRotatorLifecycleApi.setupRotatorCards === 'function') {
      return flipRotatorLifecycleApi.setupRotatorCards();
    }
  }

  // Initialize analytics and flip on first load
  setTimeout(async () => {
    await initializeAnalytics();
    setupFlipCards();
    setupRotatorCards();
    // Ensure donut and rotator cards keep rotating after dynamic changes
    document.addEventListener('visibilitychange', () => {
      if (!document.hidden) {
        setupFlipCards();
        setupRotatorCards();
      } else {
        // Clean up when tab is hidden to save resources
        cleanupRotatorCards();
        cleanupFlipCards();
      }
    });
  }, 500);

  const createAdaptivePoll = (window.AdaptivePoll && typeof window.AdaptivePoll.create === 'function')
    ? window.AdaptivePoll.create
    : null;

  if (!createAdaptivePoll) {
    console.error('AdaptivePoll module is not loaded; adaptive refresh loops are disabled.');
  }

  // Periodic competition refresh (adaptive: respects Page Visibility and viewer role)
  // Use adaptive poll for competitions so leaving a tab open won't hammer the server
  if (createAdaptivePoll) {
    createAdaptivePoll(async () => {
      refreshSpeedChallenge('am', 'speedAmList', 'speedAmStatus');
      refreshSpeedChallenge('pm', 'speedPmList', 'speedPmStatus');
      refreshCategorySpecialists();
      refreshConsistency();
    }, cfg.refreshSeconds * 1000, { viewerMultiplier: 6, hiddenMultiplier: 10 });
  }

  // Initial competition data load
  refreshSpeedChallenge('am', 'speedAmList', 'speedAmStatus');
  refreshSpeedChallenge('pm', 'speedPmList', 'speedPmStatus');
  refreshCategorySpecialists();
  refreshConsistency();

  // Refresh analytics every 5 minutes (adaptive)
  if (createAdaptivePoll) {
    createAdaptivePoll(async () => {
      await initializeAnalytics();
    }, 300000, { viewerMultiplier: 4, hiddenMultiplier: 8 });
  }

  // ==================== DASHBOARD SWITCHING ====================
  
  let currentDashboard = 0;

  const qaAdapterApi = (window.QaAdapter && typeof window.QaAdapter.init === 'function')
    ? window.QaAdapter.init({
        getAvatarDataUri,
        renderSVGSparkline,
      })
    : null;

  const escapeHtml = (qaAdapterApi && typeof qaAdapterApi.escapeHtml === 'function')
    ? qaAdapterApi.escapeHtml
    : function (text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
      };

  async function loadQADashboard(period = 'this_week') {
    if (!qaAdapterApi || typeof qaAdapterApi.load !== 'function') return;
    return qaAdapterApi.load(period);
  }

  const overallStatsApi = (window.OverallStatsDashboard && typeof window.OverallStatsDashboard.init === 'function')
    ? window.OverallStatsDashboard.init()
    : null;

  function loadOverallDashboard() {
    if (!overallStatsApi || typeof overallStatsApi.load !== 'function') return;
    return overallStatsApi.load();
  }
  
  if (window.DashboardSwitcher && typeof window.DashboardSwitcher.init === 'function') {
    window.DashboardSwitcher.init({
      loadQADashboard,
      loadOverallDashboard,
      setCurrentDashboard: (index) => {
        currentDashboard = index;
      },
      getCurrentDashboard: () => currentDashboard,
    });
  }

  // ==================== CSV EXPORT ====================
  
  const exportManagerApi = (window.ExportManager && typeof window.ExportManager.init === 'function')
    ? window.ExportManager.init({
        getCurrentDashboard: () => currentDashboard,
        categories,
        SHIFT_HOURS,
        formatTimeAgo,
      })
    : null;

  async function generateCSV() {
    if (exportManagerApi && typeof exportManagerApi.generateCSV === 'function') {
      return exportManagerApi.generateCSV();
    }
    return '';
  }

  // Download button removed from dashboard - exports available via manager.html

  // ==================== INITIALIZATION ====================
  const aggregatedRefreshApi = (window.AggregatedRefresh && typeof window.AggregatedRefresh.init === 'function')
    ? window.AggregatedRefresh.init({
        cfg,
        categories,
        animateNumberUpdate,
        updateDonut,
        totalTodayChart,
        monthChart,
        renderBars,
        getEngineerColor,
        getAvatarDataUri,
        formatTimeAgo,
        updateRace,
        renderSVGSparkline,
        keepScreenAlive,
        refreshSummary,
        refreshAllTopLists,
        refreshByTypeCounts,
        refreshLeaderboard,
      })
    : null;

  // Kick off refresh loops (after all functions are defined)
  async function refreshAggregated() {
    if (!aggregatedRefreshApi || typeof aggregatedRefreshApi.refresh !== 'function') {
      console.error('AggregatedRefresh module is not loaded; falling back to discrete refresh functions.');
      try { refreshSummary(); } catch (e) {}
      try { refreshAllTopLists(); } catch (e) {}
      try { refreshByTypeCounts(); } catch (e) {}
      try { refreshLeaderboard(); } catch (e) {}
      return;
    }
    return aggregatedRefreshApi.refresh();
  }

  // Kick off using aggregated payload
  refreshAggregated();
  
  // Initialize new flip cards
  updateRecordsMilestones();
  updateWeeklyRecords();
  updateTodayStats();
  updateMonthlyProgress();
  updateRaceUpdates();
  updateCategoryChampions();
  updateTargetTracker();
  createMonthlyMomentumChart();


  setInterval(() => {
    refreshAggregated();
    checkAndTriggerWinner();
    checkGreenieTime();
    // Update new flip cards
    updateRecordsMilestones();
    updateWeeklyRecords();
    updateTodayStats();
    updateMonthlyProgress();
    updateRaceUpdates();
    updateCategoryChampions();
    updateTargetTracker();
  }, cfg.refreshSeconds * 1000);

  if (window.ErasureCategoryCards && typeof window.ErasureCategoryCards.init === 'function') {
    const erasureCards = window.ErasureCategoryCards.init({
      categories,
      renderTopList,
      truncateInitials,
      getAvatarDataUri,
      setupRotatorCards,
    });
    erasureCards.init();
  }

})();


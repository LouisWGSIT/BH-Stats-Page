// app.js (loader): lazy-load the dashboard bundles placed under /dashboard/
(function(){
  function loadScript(src, attrs) {
    const s = document.createElement('script');
    s.src = src;
    if (attrs) Object.keys(attrs).forEach(k => s.setAttribute(k, attrs[k]));
    document.head.appendChild(s);
    return s;
  }

  // Always load the shared/common bundle (moved from root app.js to dashboard/common.js)
  // If the page already included it (e.g., index.html), skip dynamic load.
  if (!window.__dashboardCommonLoaded) {
    loadScript('dashboard/common.js');
  }

  // Determine which dashboard-specific bundle to load.
  // Prefer an explicit `data-view` on the <body>, else inspect the URL/hash.
  const view = document.body && document.body.dataset && document.body.dataset.view
    ? document.body.dataset.view
    : (location.hash.includes('qa') ? 'qa' : (location.pathname.includes('qa') ? 'qa' : 'erasure'));

  if (view === 'qa') {
    loadScript('dashboard/qa/qa.js', { defer: 'defer' });
  } else if (view === 'erasure') {
    loadScript('dashboard/erasure/erasure.js', { defer: 'defer' });
  }
})();

  // Apply theme variables
  // Ensure `cfg` exists (fallback for local static loads where server doesn't inject config)
  if (typeof cfg === 'undefined') {
    window.cfg = {
      theme: { bg: '#071826', text: '#FFFFFF', muted: '#9aa5b1', ringPrimary: '#2bb4ff', ringSecondary: '#ffb86b' },
      targets: { erased: '0', month: '0' },
      refreshSeconds: 120
    };
  }

  const root = document.documentElement;
  root.style.setProperty('--bg', cfg.theme.bg);
  root.style.setProperty('--text', cfg.theme.text);
  root.style.setProperty('--muted', cfg.theme.muted);
  root.style.setProperty('--ring-primary', cfg.theme.ringPrimary);
  root.style.setProperty('--ring-secondary', cfg.theme.ringSecondary);

  // Targets
  document.getElementById('erasedTarget').textContent = cfg.targets.erased;
  if (cfg.targets.month) {
    const mt = document.getElementById('monthTarget');
    if (mt) mt.textContent = cfg.targets.month;
  }

  // Charts
  const totalTodayChart = donut('chartTotalToday');
  const monthChart = donut('chartMonthToday');

  const categories = [
    { key: 'laptops_desktops', label: 'Laptops/Desktops', countId: 'countLD', listId: 'topLD' },
    { key: 'servers', label: 'Servers', countId: 'countServers', listId: 'topServers' },
    { key: 'macs', label: 'Macs', countId: 'countMacs', listId: 'topMacs' },
    { key: 'mobiles', label: 'Mobiles', countId: 'countMobiles', listId: 'topMobiles' },
  ];

  const SHIFT_HOURS = 8; // Standard shift duration (08:00-16:00)

  // Track leaderboard state for Greenie commentary
  let leaderboardState = { leader: null, gap: null };

  // Track race data for winner announcement
  // QA functions moved to dashboard/qa.js — delegate to implementations exposed on `window`.
  async function loadQADashboard(period = 'this_week') { return window.loadQADashboard ? window.loadQADashboard(period) : Promise.resolve(); }
  function startQATopFlipRotation() { return window.startQATopFlipRotation && window.startQATopFlipRotation(); }
  function updateQATrendPanel(opts) { return window.updateQATrendPanel && window.updateQATrendPanel(opts); }
  function startQARotator(todayData, weeklyData, allTimeData) { return window.startQARotator && window.startQARotator(todayData, weeklyData, allTimeData); }
  function populateQACard(totalId, listId, data, type = 'qa', maxItems = 6) { return window.populateQACard && window.populateQACard(totalId, listId, data, type, maxItems); }
  function populateQAAppCard(totalId, listId, data, maxItems = 8) { return window.populateQAAppCard && window.populateQAAppCard(totalId, listId, data, maxItems); }
  function populateMetricsCard(todayData, weeklyData) { return window.populateMetricsCard && window.populateMetricsCard(todayData, weeklyData); }
  function showQAError(message) { return window.showQAError && window.showQAError(message); }
  function escapeHtml(text) { return window.escapeHtml ? window.escapeHtml(text) : (text == null ? '' : String(text)); }
  function formatQaName(rawName) { return window.formatQaName ? window.formatQaName(rawName) : (rawName || ''); }
  function getQaInitials(displayName) { return window.getQaInitials ? window.getQaInitials(displayName) : ''; }

  // Safe delegate for summary refresh — implemented in `dashboard/common.js` or `dashboard/erasure/erasure.js`
  async function refreshSummary() { return window.refreshSummary ? window.refreshSummary() : Promise.resolve(); }

  // Safe wrappers (call sites use these) to avoid name collisions with global implementations
  async function callRefreshSpeedChallenge(when, listId, statusId) {
    if (typeof window.refreshSpeedChallenge === 'function' && window.refreshSpeedChallenge !== callRefreshSpeedChallenge) {
      return window.refreshSpeedChallenge(when, listId, statusId);
    }
    return Promise.resolve();
  }

  function callRefreshCategorySpecialists() {
    if (typeof window.refreshCategorySpecialists === 'function' && window.refreshCategorySpecialists !== callRefreshCategorySpecialists) {
      return window.refreshCategorySpecialists();
    }
    return null;
  }

  // Wrapper for refreshConsistency (may be implemented in common/erasure bundles)
  function callRefreshConsistency() {
    if (typeof window.refreshConsistency === 'function' && window.refreshConsistency !== callRefreshConsistency) {
      return window.refreshConsistency();
    }
    return null;
  }

  function updateRace(leaderboardData) {
    const topEngineers = leaderboardData.slice(0, 5);
    const maxErasures = topEngineers.length > 0 ? topEngineers[0].erasures || 1 : 1;

    // Update all 5 lanes
    for (let i = 1; i <= 5; i++) {
      const carEl = document.getElementById(`racePos${i}`);
      const trailEl = document.getElementById(`trail${i}`);
      const labelEl = document.getElementById(`driver${i}`);
      
      if (!carEl || !trailEl || !labelEl) continue;
      
      const engineer = topEngineers[i - 1];
      
      if (engineer) {
        const erasures = engineer.erasures || 0;
        let percentage = Math.min((erasures / maxErasures) * 100, 100);
        
        // Cap at 80% so car doesn't go past finish line until 15:58
        percentage = Math.min(percentage, 80);
        
        // Only update if value actually changed to reduce DOM thrashing
        if (carEl.style.bottom !== `${percentage}%`) {
          carEl.style.bottom = `${percentage}%`;
        }
        
        // Update trail height from bottom to current car position
        if (trailEl.style.height !== `${percentage}%`) {
          trailEl.style.height = `${percentage}%`;
        }
        
        // Color trail to match engineer color - use solid color instead of gradient for TV performance
        const engineerColor = getEngineerColor(engineer.initials || '');
        if (trailEl.style.background !== engineerColor) {
          trailEl.style.background = engineerColor;
        }
        
        // Update label with engineer initials
        if (labelEl.textContent !== engineer.initials) {
          labelEl.textContent = `${engineer.initials || '?'}`;
        }
        if (labelEl.style.color !== engineerColor) {
          labelEl.style.color = engineerColor;
        }

        // Check if car has finished (reached top/100%)
        // Only trigger finish message at 15:58 when race officially ends
        if (erasures >= maxErasures && !engineer.finished) {
          const now = new Date();
          const hours = now.getHours();
          const minutes = now.getMinutes();
          
          // Only at 15:58 does the race officially finish
          if (hours === 15 && minutes === 58) {
            engineer.finished = true;
            triggerRaceConfetti();
            triggerGreenie(`🏁 ${engineer.initials} CROSSES THE FINISH LINE! What a performance! 🎉`);
            
            // Trigger winner announcement if this is the first to finish
            if (!raceData.firstFinisher) {
              raceData.firstFinisher = engineer;
              announceWinner();
            }
          }
        }
      } else {
        // No engineer data for this lane - reset it
        carEl.style.bottom = '0%';
        trailEl.style.height = '0%';
        labelEl.textContent = '—';
        labelEl.style.color = 'var(--muted)';
      }
    }

    raceData.engineer1 = topEngineers[0] || null;
    raceData.engineer2 = topEngineers[1] || null;
    raceData.engineer3 = topEngineers[2] || null;
  }

  function checkAndTriggerWinner() {
    const now = new Date();
    const hours = now.getHours();
    const minutes = now.getMinutes();

    // Trigger at 15:58
    if (hours === 15 && minutes === 58 && !raceData.winnerAnnounced) {
      announceWinner();
    }

    // Reset flag at midnight for next day
    if (hours === 0 && minutes === 0) {
      raceData.winnerAnnounced = false;
      raceData.firstFinisher = null;
    }
  }

  // Enhanced announcement system
  const announcementTypes = {
    DAILY_SUMMARY: 'daily-summary',
    DAILY_RACE_WINNER: 'daily-race-winner',
    SPEED_CHALLENGE_AM: 'speed-challenge-am',
    SPEED_CHALLENGE_PM: 'speed-challenge-pm',
    CATEGORY_SPECIALIST: 'category-specialist',
    CONSISTENCY_KING: 'consistency-king',
    TOP_PERFORMER: 'top-performer',
  };

  const announcementMessages = {
    'daily-summary': (summary) => ({
      title: summary.title || '🏆 End of Day Awards',
      subtitle: summary.subtitle || '',
      duration: 600000, // 10 minutes
      emoji: '🏆🎉',
    }),
    'daily-race-winner': (winner) => ({
      title: `🏆 ${winner.initials} WINS THE DAILY RACE! 🏆`,
      subtitle: `Finished with ${winner.erasures} erasures today`,
      duration: 600000, // 10 minutes - display until they leave warehouse
      emoji: '🏁🎉',
    }),
    'speed-challenge-am': (winner) => ({
      title: `⚡ ${winner.initials} CRUSHES THE AM SPEED CHALLENGE! ⚡`,
      subtitle: `${winner.erasures} erasures in record time`,
      duration: 60000, // 1 minute
      emoji: '🏃💨',
    }),
    'speed-challenge-pm': (winner) => ({
      title: `🌙 ${winner.initials} DOMINATES THE PM SPEED CHALLENGE! 🌙`,
      subtitle: `${winner.erasures} erasures in the afternoon blitz`,
      duration: 60000, // 1 minute
      emoji: '🌟⚡',
    }),
    'category-specialist': (specialist) => ({
      title: `🎯 ${specialist.initials} IS THE ${specialist.category} SPECIALIST! 🎯`,
      subtitle: `Master of ${specialist.category} erasures`,
      duration: 7000,
      emoji: '👑✨',
    }),
    'consistency-king': (winner) => ({
      title: `🎪 ${winner.initials} IS TODAY'S CONSISTENCY KING/QUEEN! 🎪`,
      subtitle: `${winner.erasures} erasures with flawless pacing`,
      duration: 7000,
      emoji: '⏱️💯',
    }),
    'top-performer': (winner) => ({
      title: `⭐ ALL HAIL ${winner.initials}, TOP PERFORMER! ⭐`,
      subtitle: `${winner.erasures} erasures and counting`,
      duration: 7000,
      emoji: '👏🔥',
    }),
  };

  async function safeFetchJson(url) {
    try {
      const res = await fetch(url);
      if (!res.ok) return null;
      return await res.json();
    } catch (err) {
      return null;
    }
  }

  async function buildDailySummary() {
    const [leaderboardData, speedAmData, speedPmData, consistencyData, specialistsData] = await Promise.all([
      safeFetchJson('/metrics/engineers/leaderboard?scope=today&limit=1'),
      safeFetchJson('/competitions/speed-challenge?window=am'),
      safeFetchJson('/competitions/speed-challenge?window=pm'),
      safeFetchJson('/competitions/consistency'),
      safeFetchJson('/competitions/category-specialists'),
    ]);

    const items = [];

    const raceWinner = (leaderboardData && leaderboardData.items && leaderboardData.items[0]) || raceData.engineer1;
    if (raceWinner) {
      items.push({
        icon: '🏁',
        label: 'Daily Race',
        winner: raceWinner.initials || '—',
        value: `${raceWinner.erasures || 0} erasures`,
      });
    }

    const amWinner = speedAmData && speedAmData.leaderboard && speedAmData.leaderboard[0];
    if (amWinner) {
      items.push({
        icon: '⚡',
        label: 'Speed Challenge (AM)',
        winner: amWinner.initials || '—',
        value: `${amWinner.erasures || 0} erasures`,
      });
    }

    const pmWinner = speedPmData && speedPmData.leaderboard && speedPmData.leaderboard[0];
    if (pmWinner) {
      items.push({
        icon: '🌙',
        label: 'Speed Challenge (PM)',
        winner: pmWinner.initials || '—',
        value: `${pmWinner.erasures || 0} erasures`,
      });
    }

    const consistencyWinner = consistencyData && consistencyData.leaderboard && consistencyData.leaderboard[0];
    if (consistencyWinner) {
      items.push({
        icon: '⏱️',
        label: 'Consistency King/Queen',
        winner: consistencyWinner.initials || '—',
        value: `${consistencyWinner.erasures || 0} erasures`,
      });
    }

    const specialists = (specialistsData && specialistsData.specialists) || {};
    const specialistLabels = {
      laptops_desktops: 'Laptops/Desktops Specialist',
      servers: 'Servers Specialist',
      macs: 'Macs Specialist',
      mobiles: 'Mobiles Specialist',
    };
    Object.entries(specialistLabels).forEach(([key, label]) => {
      const row = (specialists[key] || [])[0];
      if (row) {
        items.push({
          icon: '🎯',
          label,
          winner: row.initials || '—',
          value: `${row.count || 0} erasures`,
        });
      }
    });

    if (items.length === 0) {
      items.push({
        icon: 'ℹ️',
        label: 'No results yet',
        winner: '—',
        value: 'Waiting for data',
      });
    }

    const todayLabel = new Date().toLocaleDateString(undefined, {
      weekday: 'long',
      month: 'short',
      day: 'numeric',
    });

    return {
      title: '🏆 End of Day Awards',
      subtitle: `${todayLabel} • Winners`,
      items,
    };
  }

  function showAnnouncement(type, data) {
    const config = announcementMessages[type];
    if (!config) return;

    const message = config(data);
    const modal = document.getElementById('winnerModal');
    const winnerText = document.getElementById('winnerText');
    const winnerSubtext = document.getElementById('winnerSubtext');
    const summaryContainer = document.getElementById('announcementSummary');
    const summaryTitle = document.getElementById('summaryTitle');
    const summarySubtitle = document.getElementById('summarySubtitle');
    const summaryGrid = document.getElementById('summaryGrid');

    if (type === announcementTypes.DAILY_SUMMARY && summaryContainer) {
      if (winnerText) winnerText.style.display = 'none';
      if (winnerSubtext) winnerSubtext.style.display = 'none';
      summaryContainer.classList.remove('hidden');
      if (summaryTitle) summaryTitle.textContent = data.title || message.title;
      if (summarySubtitle) summarySubtitle.textContent = data.subtitle || message.subtitle || '';
      if (summaryGrid) {
        summaryGrid.innerHTML = (data.items || []).map(item => `
          <div class="summary-item">
            <div class="summary-item-left">
              <span class="summary-icon">${item.icon || '🏆'}</span>
              <div>
                <div class="summary-label">${escapeHtml(item.label || '')}</div>
                <div class="summary-winner">${escapeHtml(item.winner || '—')}</div>
              </div>
            </div>
            <div class="summary-value">${escapeHtml(item.value || '')}</div>
          </div>
        `).join('');
      }
    } else {
      if (summaryContainer) summaryContainer.classList.add('hidden');
      if (winnerText) {
        winnerText.style.display = '';
        winnerText.textContent = message.title;
      }
      if (winnerSubtext) {
        winnerSubtext.style.display = '';
        winnerSubtext.textContent = message.subtitle;
      }
    }

    modal.classList.remove('hidden');

    // Trigger confetti for more impressive effect
    triggerConfetti();

    // Hide modal after configured duration
    setTimeout(() => {
      modal.classList.add('hidden');
    }, message.duration);
  }

  async function announceWinner() {
    if (raceData.winnerAnnounced) return;
    raceData.winnerAnnounced = true;
    const summary = await buildDailySummary();
    showAnnouncement(announcementTypes.DAILY_SUMMARY, summary);
  }

  function triggerConfetti() {
    if (typeof confetti === 'undefined') {
      console.warn('Confetti library not loaded');
      return;
    }

    const confettiColors = [
      '#ff1ea3', // pink
      '#8cf04a', // green
      '#00d4ff', // cyan
      '#ffcc00', // yellow
    ];

    const defaults = {
      origin: { y: 0.3 },
      zIndex: 10000,
      disableForReducedMotion: true,
    };

    // Single optimized burst for TV performance
    confetti({
      ...defaults,
      particleCount: 50, // Reduced from 100
      spread: 90,
      startVelocity: 40,
      colors: confettiColors,
      ticks: 120, // Limit animation duration
    });
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

  // `updateDonut` moved to dashboard/common.js

  // Keep-alive helpers moved to dashboard/common.js

  // Auto-reload page at 2 AM daily to clear cache and keep memory clean (off-hours)
  function scheduleNightlyReload() {
    const now = new Date();
    let reloadTime = new Date();
    reloadTime.setHours(2, 0, 0, 0); // 2 AM
    
    // If 2 AM has passed today, schedule for tomorrow
    if (now > reloadTime) {
      reloadTime.setDate(reloadTime.getDate() + 1);
    }
    
    const msUntilReload = reloadTime - now;
    setTimeout(() => {
      location.reload();
      scheduleNightlyReload(); // Reschedule for next day
    }, msUntilReload);
  }
  scheduleNightlyReload();

  // Avatar/color helpers moved to dashboard/common.js

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
  
  let analyticsCharts = {};

  async function fetchAnalytics() {
    try {
      const requests = [
        fetch('/analytics/weekly-category-trends'),
        fetch('/analytics/weekly-engineer-stats'),
        fetch('/analytics/peak-hours'),
        fetch('/analytics/day-of-week-patterns')
      ];
      const responses = await Promise.all(requests);
      // If any returned unauthorized (401) or not-ok, bail out to avoid passing invalid data
      if (responses.some(r => !r.ok)) {
        console.warn('One or more analytics requests failed', responses.map(r => r.status));
        return null;
      }
      const [categoryTrends, engineerStats, peakHours, dayPatterns] = await Promise.all(responses.map(r => r.json()));
      return { categoryTrends, engineerStats, peakHours, dayPatterns };
    } catch (error) {
      console.error('Failed to fetch analytics:', error);
      return null;
    }
  }

  function createPeakHoursChart(data) {
    const canvas = document.getElementById('chartPeakHours');
    if (!canvas) return;

    if (analyticsCharts.peakHours) {
      analyticsCharts.peakHours.destroy();
    }

    const ctx = canvas.getContext('2d');
    analyticsCharts.peakHours = new Chart(ctx, {
      type: 'bar',
      data: {
        labels: data.hours.map(h => `${h.hour}:00`),
        datasets: [{
          label: 'Erasures',
          data: data.hours.map(h => h.count),
          backgroundColor: cfg.theme.ringPrimary,
          borderRadius: 4,
          borderSkipped: false
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          title: {
            display: true,
            text: 'Hourly Activity',
            color: cfg.theme.text,
            font: { size: 14 }
          }
        },
        scales: {
          y: {
            beginAtZero: true,
            grid: { color: 'rgba(255,255,255,0.05)' },
            ticks: { color: cfg.theme.muted, font: { size: 10 } }
          },
          x: {
            grid: { display: false },
            ticks: { color: cfg.theme.muted, font: { size: 9 }, maxRotation: 0 }
          }
        }
      }
    });
  }

  function createDayOfWeekChart(data) {
    const canvas = document.getElementById('chartDayOfWeek');
    if (!canvas) return;

    if (analyticsCharts.dayOfWeek) {
      analyticsCharts.dayOfWeek.destroy();
    }

    const ctx = canvas.getContext('2d');
    analyticsCharts.dayOfWeek = new Chart(ctx, {
      type: 'bar',
      data: {
        labels: data.patterns.map(p => p.day),
        datasets: [{
          label: 'Avg Erasures',
          data: data.patterns.map(p => p.avgCount),
          backgroundColor: cfg.theme.ringSecondary,
          borderRadius: 4,
          borderSkipped: false
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          title: {
            display: true,
            text: 'Average by Day (Last 4 Weeks)',
            color: cfg.theme.text,
            font: { size: 14 }
          }
        },
        scales: {
          y: {
            beginAtZero: true,
            grid: { color: 'rgba(255,255,255,0.05)' },
            ticks: { color: cfg.theme.muted }
          },
          x: {
            grid: { display: false },
            ticks: { color: cfg.theme.muted }
          }
        }
      }
    });
  }

  function createWeeklyCategoryTrendsChart(data) {
    if (!data || !data.trends) { console.warn('createWeeklyCategoryTrendsChart: no data provided'); return; }
    const canvas = document.getElementById('chartWeeklyCategoryTrends');
    if (!canvas) return;

    if (analyticsCharts.categoryTrends) {
      analyticsCharts.categoryTrends.destroy();
    }


    const trends = data.trends;
    // Get today's date in YYYY-MM-DD
    const today = new Date();
    const todayStr = today.toISOString().slice(0, 10);

    // Get live stat card values for each category
    const liveValues = {
      laptops_desktops: parseInt(document.getElementById('countLD')?.textContent) || 0,
      servers: parseInt(document.getElementById('countServers')?.textContent) || 0,
      macs: parseInt(document.getElementById('countMacs')?.textContent) || 0,
      mobiles: parseInt(document.getElementById('countMobiles')?.textContent) || 0,
    };

    // Build all unique dates, and ensure today is included
    let allDates = [...new Set(
      Object.values(trends).flatMap(arr => arr.map(d => d.date))
    )];
    if (!allDates.includes(todayStr)) allDates.push(todayStr);
    allDates = allDates.sort();

    const datasets = Object.keys(trends).map((category, idx) => {
      const colorMap = {
        'laptops_desktops': '#4caf50', // green
        'servers': '#ffeb3b', // yellow
        'macs': '#2196f3', // blue
        'mobiles': '#ff1ea3' // pink
      };
      // Build data array, replacing or appending today's value with live stat card value
      const dataArr = allDates.map(date => {
        if (date === todayStr) {
          return liveValues[category] || 0;
        }
        const entry = trends[category].find(d => d.date === date);
        return entry ? entry.count : 0;
      });
      return {
        label: category.replace('_', ' / ').toUpperCase(),
        data: dataArr,
        borderColor: colorMap[category] || cfg.theme.ringPrimary,
        backgroundColor: colorMap[category] || cfg.theme.ringPrimary,
        tension: 0.3,
        borderWidth: 2,
        fill: false
      };
    });

    const ctx = canvas.getContext('2d');
    analyticsCharts.categoryTrends = new Chart(ctx, {
      type: 'line',
      data: {
        labels: allDates.map(d => new Date(d).toLocaleDateString('en-GB', { month: 'short', day: 'numeric' })),
        datasets: datasets
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: {
            display: true,
            position: 'top',
            labels: { color: cfg.theme.text, font: { size: 11 } }
          }
        },
        scales: {
          y: {
            beginAtZero: true,
            grid: { color: 'rgba(255,255,255,0.05)' },
            ticks: { color: cfg.theme.muted }
          },
          x: {
            grid: { display: false },
            ticks: { color: cfg.theme.muted, font: { size: 10 } }
          }
        }
      }
    });
  }

  function updateWeeklyLeaderboard(data) {
    const tbody = document.getElementById('weeklyLeaderboardBody');
    if (!tbody) return;

    tbody.innerHTML = data.stats.slice(0, 10).map(eng => {
      const avatar = getAvatarDataUri(eng.initials || '');
      const displayInitials = truncateInitials(eng.initials || '');
      return `
      <tr>
        <td>
          <span class="engineer-avatar" style="background-image: url(${avatar})"></span>
          <span class="engineer-name">${displayInitials}</span>
        </td>
        <td>${eng.weeklyTotal}</td>
        <td>${eng.daysActive}/5</td>
        <td>${eng.consistency}%</td>
      </tr>`;
    }).join('');
  }

  async function initializeAnalytics() {
    const analytics = await fetchAnalytics();
    if (!analytics) {
      console.warn('Analytics data unavailable, skipping chart setup');
      return;
    }

    createPeakHoursChart(analytics.peakHours);
    createDayOfWeekChart(analytics.dayPatterns);
    createWeeklyCategoryTrendsChart(analytics.categoryTrends);
    updateWeeklyLeaderboard(analytics.engineerStats);
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

  async function createMonthlyMomentumChart() {
    const canvas = document.getElementById('chartMonthlyMomentum');
    if (!canvas) return;

    if (analyticsCharts.monthlyMomentum) {
      analyticsCharts.monthlyMomentum.destroy();
    }

    // Fetch real monthly data from API
    let weeklyData = [0, 0, 0, 0];
    try {
      const response = await fetch('/metrics/monthly-momentum');
      const data = await response.json();
      if (data && data.weeklyTotals) {
        weeklyData = data.weeklyTotals;
      }
    } catch (error) {
      console.warn('Failed to fetch monthly momentum:', error);
      // No fallback: leave chart empty if backend fails
    }
    
    const ctx = canvas.getContext('2d');
    analyticsCharts.monthlyMomentum = new Chart(ctx, {
      type: 'bar',
      data: {
        labels: ['Week 1', 'Week 2', 'Week 3', 'Week 4'],
        datasets: [{
          label: 'Weekly Total',
          data: weeklyData,
          backgroundColor: cfg.theme.ringSecondary,
          borderRadius: 6,
          borderSkipped: false
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          title: {
            display: true,
            text: 'Week-by-Week Progress',
            color: cfg.theme.text,
            font: { size: 14 }
          }
        },
        scales: {
          y: {
            beginAtZero: true,
            grid: { color: 'rgba(255,255,255,0.05)' },
            ticks: { color: cfg.theme.muted }
          },
          x: {
            grid: { display: false },
            ticks: { color: cfg.theme.muted }
          }
        }
      }
    });
  }

  // Flip card logic with staggered timing
  // Track flip card intervals/timeouts so we can clean them up (prevents stacking on re-init)
  const flipIntervals = new Map();
  const flipTimeouts = new Map();

  function cleanupFlipCards() {
    flipIntervals.forEach(id => clearInterval(id));
    flipTimeouts.forEach(t => {
      if (Array.isArray(t)) {
        t.forEach(x => clearTimeout(x));
      } else {
        clearTimeout(t);
      }
    });
    flipIntervals.clear();
    flipTimeouts.clear();
    // Reset flip classes to safe state
    const flipCards = document.querySelectorAll('.flip-card');
    flipCards.forEach(card => {
      card.classList.remove('flipped', 'about-to-flip');
    });
  }

  function setupFlipCards() {
    // Clear any previous flip timers before setting new ones
    cleanupFlipCards();
    const flipCards = document.querySelectorAll('.flip-card');
    if (flipCards.length === 0) return;

    // Increase flip interval so cards rotate less often on PCs
    const FLIP_INTERVAL = 60000; // 60s between flips
    const FLIP_HOLD = 20000; // 20s hold before flipping back
    const PRE_FLIP_INDICATOR_TIME = 500; // Show indicator before flip

    flipCards.forEach((card, index) => {
      const inner = card.querySelector('.flip-card-inner');
      let isFlipping = false;
      
      function performFlip() {
        if (isFlipping) return;
        
        // Add pre-flip indicator
        card.classList.add('about-to-flip');
        
        setTimeout(() => {
          card.classList.remove('about-to-flip');
          isFlipping = true;
          card.classList.toggle('flipped');
        }, PRE_FLIP_INDICATOR_TIME);
      }
      
      // Listen for transition end to know when flip completes
      if (inner) {
        inner.addEventListener('transitionend', (e) => {
          if (e.propertyName === 'transform') {
            isFlipping = false;
          }
        });
      }
      
        // Initial flip after a brief stagger
        const startTimeout = setTimeout(() => {
          performFlip();

          // Flip back after hold (wait for flip to complete + hold time)
          const holdTimeout = setTimeout(() => {
            performFlip();
          }, FLIP_HOLD);

          // Setup recurring flips after initial cycle
          const recurringSetupTimeout = setTimeout(() => {
            const intervalId = setInterval(() => {
              performFlip();
              setTimeout(performFlip, FLIP_HOLD);
            }, FLIP_INTERVAL);
            flipIntervals.set(index, intervalId);
          }, FLIP_HOLD);

          // Track timeouts so we can clear them if needed
          flipTimeouts.set(index, [startTimeout, holdTimeout, recurringSetupTimeout]);
        }, 2000 + index * 300);
        // Also track the initial stagger timeout in case cleanup runs before it fires
        if (!flipTimeouts.has(index)) flipTimeouts.set(index, startTimeout);
    });
  }

  // Rotate multi-panel cards in place (bottom row)
  const rotatorIntervals = new Map();
  const rotatorTimeouts = new Map();
  
  function cleanupRotatorCards() {
    // Clear all intervals and timeouts
    rotatorIntervals.forEach(id => clearInterval(id));
    rotatorTimeouts.forEach(id => clearTimeout(id));
    rotatorIntervals.clear();
    rotatorTimeouts.clear();
  }
  
  function setupRotatorCards() {
    const cards = document.querySelectorAll('.rotator-card');
    if (!cards.length) return;

    // Clean up before setting up new ones
    cleanupRotatorCards();

    cards.forEach((card, cardIdx) => {
      // Clear any existing interval/timeout for this card
      if (rotatorIntervals.has(cardIdx)) {
        clearInterval(rotatorIntervals.get(cardIdx));
        rotatorIntervals.delete(cardIdx);
      }
      if (rotatorTimeouts.has(cardIdx)) {
        clearTimeout(rotatorTimeouts.get(cardIdx));
        rotatorTimeouts.delete(cardIdx);
      }
      
      const panels = Array.from(card.querySelectorAll('.panel'));
      if (panels.length <= 1) return;

      // Reset panel states to avoid stacking/overlap
      panels.forEach(panel => {
        panel.classList.remove('active', 'entering', 'exiting', 'about-to-rotate');
      });

      let index = 0;
      let isTransitioning = false;
      const interval = parseInt(card.dataset.interval, 10) || 14000;
      const PRE_ROTATE_INDICATOR_TIME = 400;

      function showPanel(nextIndex) {
        if (isTransitioning) {
          console.warn('Rotator card transition already in progress, skipping');
          return;
        }
        
        const currentIndex = panels.findIndex(p => p.classList.contains('active'));
        if (currentIndex === -1) {
          // First time setup - ensure only one active
          panels.forEach(panel => panel.classList.remove('active', 'entering', 'exiting', 'about-to-rotate'));
          panels[nextIndex].classList.add('active');
          return;
        }
        
        // Add pre-rotation indicator to current panel
        panels[currentIndex].classList.add('about-to-rotate');
        
        setTimeout(() => {
          isTransitioning = true;
          
          panels.forEach(panel => {
            panel.classList.remove('entering', 'exiting', 'about-to-rotate');
          });

          panels[currentIndex].classList.remove('active');
          panels[currentIndex].classList.add('exiting');

          const nextPanel = panels[nextIndex];
          nextPanel.classList.add('entering');
          nextPanel.classList.add('active');
          
          // Force repaint on TV browsers for better animation reliability
          void nextPanel.offsetHeight;
          
          // Wait for transition to complete before allowing next transition
          setTimeout(() => {
            panels[currentIndex].classList.remove('exiting');
            nextPanel.classList.remove('entering');
            isTransitioning = false;
          }, 1200);
          
          // Safety timeout to reset isTransitioning if something goes wrong
          setTimeout(() => {
            if (isTransitioning) {
              console.warn('Rotator card transition took too long, resetting');
              isTransitioning = false;
            }
          }, 3000);
        }, PRE_ROTATE_INDICATOR_TIME);
      }

      // Ensure the first panel is visible
      showPanel(index);

      // Begin rotation after a short delay to stagger with flip-cards
      const startTimeout = setTimeout(() => {
        const intervalId = setInterval(() => {
          index = (index + 1) % panels.length;
          showPanel(index);
        }, interval);
        
        // Store interval ID so we can clear it later if needed
        rotatorIntervals.set(cardIdx, intervalId);
      }, 3000);
      rotatorTimeouts.set(cardIdx, startTimeout);
    });
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
  // Periodic competition refresh (adaptive: respects Page Visibility and viewer role)
  function createAdaptivePoll(fn, baseIntervalMs, opts = {}) {
    const viewerMultiplier = opts.viewerMultiplier || 6;
    const hiddenMultiplier = opts.hiddenMultiplier || 5;
    let timer = null;
    let stopped = false;

    function roleIsViewer() {
      return (sessionStorage.getItem('userRole') || 'viewer') === 'viewer';
    }

    function effectiveInterval() {
      let iv = baseIntervalMs * (roleIsViewer() ? viewerMultiplier : 1);
      if (document.hidden) iv = Math.max(iv, baseIntervalMs * hiddenMultiplier);
      return iv;
    }

    async function tick() {
      if (stopped) return;
      try { await fn(); } catch (e) { console.warn('Adaptive poll error', e); }
      schedule();
    }

    function schedule() {
      clearTimeout(timer);
      if (stopped) return;
      timer = setTimeout(tick, effectiveInterval());
    }

    // Visibility-aware adjustments
    document.addEventListener('visibilitychange', () => {
      clearTimeout(timer);
      if (!stopped) schedule();
    });

    // Start immediately
    schedule();

    return {
      stop() { stopped = true; clearTimeout(timer); },
      start() { if (stopped) { stopped = false; schedule(); } }
    };
  }

  // Use adaptive poll for competitions so leaving a tab open won't hammer the server
  createAdaptivePoll(async () => {
    callRefreshSpeedChallenge('am', 'speedAmList', 'speedAmStatus');
    callRefreshSpeedChallenge('pm', 'speedPmList', 'speedPmStatus');
    callRefreshCategorySpecialists();
    callRefreshConsistency();
  }, cfg.refreshSeconds * 1000, { viewerMultiplier: 6, hiddenMultiplier: 10 });

  // Initial competition data load
  callRefreshSpeedChallenge('am', 'speedAmList', 'speedAmStatus');
  callRefreshSpeedChallenge('pm', 'speedPmList', 'speedPmStatus');
  callRefreshCategorySpecialists();
  callRefreshConsistency();

  // Refresh analytics every 5 minutes (adaptive)
  createAdaptivePoll(async () => {
    await initializeAnalytics();
  }, 300000, { viewerMultiplier: 4, hiddenMultiplier: 8 });

  // ==================== DASHBOARD SWITCHING ====================
  
  let currentDashboard = 0;
  let dashboardLocked = false;  // NEW: Lock dashboard to prevent rotation
  const dashboards = ['erasure', 'qa'];
  const dashboardTitles = {
    'erasure': 'Erasure Stats',
    'qa': 'QA Stats'
  };
  
  // Load QA dashboard data
  async function loadQADashboard(period = 'this_week') {
    try {
      // Load today, this week, and all-time data in parallel
      const [todayResponse, weeklyResponse, allTimeResponse] = await Promise.all([
        fetch(`/api/qa-dashboard?period=today`),
        fetch(`/api/qa-dashboard?period=this_week`),
        fetch(`/api/qa-dashboard?period=all_time`)
      ]);
      
      if (!todayResponse.ok || !weeklyResponse.ok || !allTimeResponse.ok) {
        showQAError(`Failed to load QA data`);
        return;
      }
      
      const todayData = await todayResponse.json();
      const weeklyData = await weeklyResponse.json();
      const allTimeData = await allTimeResponse.json();
      
      if (todayData.error || weeklyData.error || allTimeData.error) {
        console.error('QA data error');
        showQAError('Failed to load QA data');
        return;
      }
      
      // Top row: Today's QA, This Week's QA, All Time QA
      populateQACard('qaTodayTotal', 'qaTodayEngineers', todayData, 'qa', 6);
      populateQACard('qaWeekTotal', 'qaWeeklyEngineers', weeklyData, 'qa', 6);
      populateQACard('qaAllTimeTotal', 'qaAllTimeEngineers', allTimeData, 'qa', 8);
      
      // Bottom row: Rotating Data Bearing / Non Data Bearing cards, and Metrics
      startQARotator(todayData, weeklyData, allTimeData);
      populateMetricsCard(todayData, weeklyData);

      // QA trend panels for top cards
      const [todayTrend, weekTrend, allTimeTrend, todayInsights, weekInsights, allTimeInsights] = await Promise.all([
        fetch('/api/qa-trends?period=today').then(r => r.ok ? r.json() : null).catch(() => null),
        fetch('/api/qa-trends?period=this_week').then(r => r.ok ? r.json() : null).catch(() => null),
        fetch('/api/qa-trends?period=all_time').then(r => r.ok ? r.json() : null).catch(() => null),
        fetch('/api/insights/qa?period=today').then(r => r.ok ? r.json() : null).catch(() => null),
        fetch('/api/insights/qa?period=this_week').then(r => r.ok ? r.json() : null).catch(() => null),
        fetch('/api/insights/qa?period=all_time').then(r => r.ok ? r.json() : null).catch(() => null),
      ]);

      updateQATrendPanel({
        totalId: 'qaTodayTrendTotal',
        sparklineId: 'qaTodaySparkline',
        metricsId: 'qaTodayMetrics',
        trend: todayTrend,
        insights: todayInsights,
        mode: 'today'
      });
      updateQATrendPanel({
        totalId: 'qaWeekTrendTotal',
        sparklineId: 'qaWeekSparkline',
        metricsId: 'qaWeekMetrics',
        trend: weekTrend,
        insights: weekInsights,
        mode: 'week'
      });
      updateQATrendPanel({
        totalId: 'qaAllTimeTrendTotal',
        sparklineId: 'qaAllTimeSparkline',
        metricsId: 'qaAllTimeMetrics',
        trend: allTimeTrend,
        insights: allTimeInsights,
        mode: 'all_time'
      });

      startQATopFlipRotation();
      
      // Right side: Sorting (QA App)
      populateQAAppCard('qaAppTodayTotal', 'qaAppTodayEngineers', todayData, 6);
      populateQAAppCard('qaAppWeekTotal', 'qaAppWeeklyEngineers', weeklyData, 8);
      populateQAAppCard('qaAppAllTimeTotal', 'qaAppAllTimeEngineers', allTimeData, 10);
      
    } catch (error) {
      console.error('Failed to load QA dashboard:', error);
      showQAError('Connection error: ' + error.message);
    }
  }

  let qaTopFlipIntervalId = null;

  function startQATopFlipRotation() {
    const cards = document.querySelectorAll('.qa-top-flip-card');
    if (!cards.length) return;

    let flipped = false;
    cards.forEach(card => card.classList.remove('flipped'));

    if (qaTopFlipIntervalId) {
      clearInterval(qaTopFlipIntervalId);
    }

    qaTopFlipIntervalId = setInterval(() => {
      flipped = !flipped;
      cards.forEach(card => card.classList.toggle('flipped', flipped));
    }, 35000);
  }

  function updateQATrendPanel({ totalId, sparklineId, metricsId, trend, insights, mode }) {
    const totalEl = document.getElementById(totalId);
    const metricsEl = document.getElementById(metricsId);
    const sparklineEl = document.getElementById(sparklineId);

    if (!trend || !trend.series || !Array.isArray(trend.series)) {
      if (metricsEl) {
        metricsEl.innerHTML = '<div style="grid-column: 1 / -1; text-align: center; color: #888;">No trend data</div>';
      }
      if (sparklineEl) {
        renderSVGSparkline(sparklineEl, []);
      }
      return;
    }

    // Use qaTotal (DE + Non-DE only, excludes sorting) if available, fallback to total
    const values = trend.series.map(row => row.qaTotal !== undefined ? row.qaTotal : (row.deQa || 0) + (row.nonDeQa || 0));
    const total = (insights && typeof insights.total === 'number')
      ? insights.total
      : values.reduce((sum, v) => sum + v, 0);

    if (totalEl) {
      totalEl.textContent = total.toLocaleString();
    }

    if (sparklineEl) {
      renderSVGSparkline(sparklineEl, values);
    }

    if (!metricsEl) return;

    const metrics = [];
    if (mode === 'today') {
      const activeHours = trend.series.filter(row => (row.total || 0) > 0).length || 1;
      const hourlyAvg = Math.round(total / activeHours);
      metrics.push({ label: 'Hourly Avg', value: hourlyAvg.toLocaleString() });
      metrics.push({ label: 'Active Hours', value: activeHours.toString() });
      if (insights) {
        metrics.push({ label: 'Avg/Engineer', value: (insights.avgPerEngineer || 0).toLocaleString() });
        metrics.push({ label: 'Active Engineers', value: (insights.activeEngineers || 0).toString() });
      }
    } else {
      if (insights) {
        metrics.push({ label: 'Avg/Day', value: (insights.avgPerDay || 0).toLocaleString() });
        metrics.push({ label: 'Avg/Engineer', value: (insights.avgPerEngineer || 0).toLocaleString() });
        metrics.push({ label: '7D Avg', value: (insights.rolling7DayAvg || 0).toLocaleString() });
        metrics.push({ label: '30D Avg', value: (insights.rolling30DayAvg || 0).toLocaleString() });
      }
    }

    metricsEl.innerHTML = metrics.map(item => `
      <div class="qa-trend-metric">
        <div class="qa-trend-metric-label">${escapeHtml(item.label)}</div>
        <div class="qa-trend-metric-value">${escapeHtml(item.value)}</div>
      </div>
    `).join('');
  }
  
  let qaRotatorIntervalId = null;

  function startQARotator(todayData, weeklyData, allTimeData) {
    const datasets = [
      { data: todayData, label: "Today's" },
      { data: weeklyData, label: "This Week's" },
      { data: allTimeData, label: "All Time" }
    ];
    
    let currentIndex = 0;
    
    // Update the cards with current dataset
    function updateRotatingCards() {
      const current = datasets[currentIndex];
      
      // Get card elements
      const dataBearingCard = document.querySelector('#dataBeringToday').closest('.qa-de-card');
      const nonDataBearingCard = document.querySelector('#nonDataBeringToday').closest('.qa-de-card');
      
      // Add flip animation
      if (dataBearingCard) {
        dataBearingCard.classList.add('flipping');
        setTimeout(() => dataBearingCard.classList.remove('flipping'), 600);
      }
      if (nonDataBearingCard) {
        nonDataBearingCard.classList.add('flipping');
        setTimeout(() => nonDataBearingCard.classList.remove('flipping'), 600);
      }
      
      // Remove old color classes
      const colorClasses = ['qa-card-today', 'qa-card-week', 'qa-card-alltime'];
      if (dataBearingCard) {
        colorClasses.forEach(cls => dataBearingCard.classList.remove(cls));
      }
      if (nonDataBearingCard) {
        colorClasses.forEach(cls => nonDataBearingCard.classList.remove(cls));
      }
      
      // Add appropriate color class based on period (but keep data-bearing/non-data-bearing styling)
      let colorClass = '';
      if (current.label === "Today's") {
        colorClass = 'qa-card-today';
      } else if (current.label === "This Week's") {
        colorClass = 'qa-card-week';
      } else if (current.label === "All Time") {
        colorClass = 'qa-card-alltime';
      }
      
      // Apply color to data bearing card (keep qa-card-data-bearing for styling)
      if (dataBearingCard && colorClass) {
        dataBearingCard.classList.add(colorClass);
        // Ensure data-bearing class is always present
        if (!dataBearingCard.classList.contains('qa-card-data-bearing')) {
          dataBearingCard.classList.add('qa-card-data-bearing');
        }
      }
      
      // Apply color to non-data bearing card (keep qa-card-non-data-bearing for styling)
      if (nonDataBearingCard && colorClass) {
        nonDataBearingCard.classList.add(colorClass);
        // Ensure non-data-bearing class is always present
        if (!nonDataBearingCard.classList.contains('qa-card-non-data-bearing')) {
          nonDataBearingCard.classList.add('qa-card-non-data-bearing');
        }
      }
      
      // Update Data Bearing card
      const dataBearingTitle = dataBearingCard?.querySelector('h3');
      if (dataBearingTitle) {
        dataBearingTitle.textContent = `${current.label} Data Bearing`;
      }
      populateQACard('dataBeringToday', 'dataBeringTodayEngineers', current.data, 'de', 6);
      
      // Update Non Data Bearing card
      const nonDataBearingTitle = nonDataBearingCard?.querySelector('h3');
      if (nonDataBearingTitle) {
        nonDataBearingTitle.textContent = `${current.label} Non Data Bearing`;
      }
      populateQACard('nonDataBeringToday', 'nonDataBeringTodayEngineers', current.data, 'non_de', 6);
      
      currentIndex = (currentIndex + 1) % datasets.length;
    }
    
    // Initial display
    updateRotatingCards();
    
    // Rotate every 30 seconds (sync with metrics card)
    if (qaRotatorIntervalId) {
      clearInterval(qaRotatorIntervalId);
    }
    qaRotatorIntervalId = setInterval(updateRotatingCards, 30000);
  }
  
  function populateQACard(totalId, listId, data, type = 'qa', maxItems = 6) {
    const totalEl = document.getElementById(totalId);
    const listEl = document.getElementById(listId);
    
    let total = 0;
    let engineers = [];
    
    if (type === 'qa') {
      // All QA (data-bearing + non-data-bearing, NOT Sorting)
      total = (data.summary.deQaScans || 0) + (data.summary.nonDeQaScans || 0);
      engineers = (data.technicians || [])
        .filter(tech => ((tech.deQaScans || 0) + (tech.nonDeQaScans || 0)) > 0)
        .map(tech => ({
          name: tech.name,
          count: (tech.deQaScans || 0) + (tech.nonDeQaScans || 0)
        }))
        .sort((a, b) => b.count - a.count)
        .slice(0, maxItems);
    } else if (type === 'de') {
      // Data-bearing only
      total = data.summary.deQaScans || 0;
      engineers = (data.technicians || [])
        .filter(tech => (tech.deQaScans || 0) > 0)
        .map(tech => ({
          name: tech.name,
          count: tech.deQaScans || 0
        }))
        .sort((a, b) => b.count - a.count)
        .slice(0, maxItems);
    } else if (type === 'non_de') {
      // Non-data-bearing only
      total = data.summary.nonDeQaScans || 0;
      engineers = (data.technicians || [])
        .filter(tech => (tech.nonDeQaScans || 0) > 0)
        .map(tech => ({
          name: tech.name,
          count: tech.nonDeQaScans || 0
        }))
        .sort((a, b) => b.count - a.count)
        .slice(0, maxItems);
    }
    
    if (totalEl) {
      totalEl.textContent = total.toLocaleString();
    }
    
    if (listEl) {
      if (engineers.length === 0) {
        listEl.innerHTML = '<div style="padding: 12px; text-align: center; color: #888;">No data</div>';
      } else {
        listEl.innerHTML = engineers.map(eng => {
          const displayName = formatQaName(eng.name);
          const avatarKey = eng.name || displayName || 'QA';
          const avatar = getAvatarDataUri(avatarKey);
          return `
            <div class="qa-engineer-item">
              <div class="qa-engineer-left">
                <span class="qa-engineer-avatar" style="background-image: url(${avatar})"></span>
                <span class="qa-engineer-name">${escapeHtml(displayName)}</span>
              </div>
              <span class="qa-engineer-count">${eng.count.toLocaleString()}</span>
            </div>
          `;
        }).join('');
      }
    }
  }
  
  function populateQAAppCard(totalId, listId, data, maxItems = 8) {
    const totalEl = document.getElementById(totalId);
    const listEl = document.getElementById(listId);
    
    const qaTotal = data.summary.totalScans || 0;
    
    if (totalEl) {
      totalEl.textContent = qaTotal.toLocaleString();
    }
    
    if (listEl) {
      const qaEngineers = (data.technicians || [])
        .filter(tech => (tech.qaScans || 0) > 0)
        .filter(tech => (tech.name || '').toLowerCase() !== '(unassigned)')
        .map(tech => ({
          name: tech.name,
          qaScans: tech.qaScans || 0
        }))
        .sort((a, b) => b.qaScans - a.qaScans)
        .slice(0, maxItems);
      
      if (qaEngineers.length === 0) {
        listEl.innerHTML = '<div style="padding: 12px; text-align: center; color: #888;">No data</div>';
      } else {
        listEl.innerHTML = qaEngineers.map(eng => {
          const displayName = formatQaName(eng.name);
          const avatarKey = eng.name || displayName || 'QA';
          const avatar = getAvatarDataUri(avatarKey);
          return `
            <div class="qa-engineer-item">
              <div class="qa-engineer-left">
                <span class="qa-engineer-avatar" style="background-image: url(${avatar})"></span>
                <span class="qa-engineer-name">${escapeHtml(displayName)}</span>
              </div>
              <span class="qa-engineer-count">${eng.qaScans.toLocaleString()}</span>
            </div>
          `;
        }).join('');
      }
    }
  }
  
  let metricsFlipIntervalId = null;

  function populateMetricsCard(todayData, weeklyData) {
    const metricsContent = document.getElementById('metricsContent');
    const metricsValue = document.getElementById('metricsValue');
    const metricsLabel = document.getElementById('metricsLabel');
    
    if (!metricsContent) return;
    
    // QA-only totals (DE + Non-DE, excludes sorting/qaApp)
    const todayTotal = (todayData.summary.deQaScans || 0) + (todayData.summary.nonDeQaScans || 0);
    const weeklyTotal = (weeklyData.summary.deQaScans || 0) + (weeklyData.summary.nonDeQaScans || 0);
    const avgDaily = weeklyTotal > 0 ? Math.round(weeklyTotal / 5) : 0;
    // Count engineers with any QA activity (DE or Non-DE)
    const engineerCount = todayData.technicians ? todayData.technicians.filter(t => (t.deQaScans || 0) + (t.nonDeQaScans || 0) > 0).length : 0;
    const avgPerEngineer = engineerCount > 0 ? Math.round(todayTotal / engineerCount) : 0;
    const avgConsistency = todayData.summary.avgConsistency || 0;
    
    // Get daily records from either dataset
    const dailyRecords = todayData.summary.dailyRecord || weeklyData.summary.dailyRecord || { 
      data_bearing_records: [], 
      non_data_bearing_records: [] 
    };
    
    const metricsCard = document.querySelector('.qa-metrics-card');
    let currentView = 0; // 0 = stats, 1 = data-bearing, 2 = non-data-bearing
    
    function updateMetricsView() {
      // Add flip animation
      if (metricsCard) {
        metricsCard.classList.add('flipping');
        setTimeout(() => metricsCard.classList.remove('flipping'), 600);
      }
      
      if (currentView === 0) {
        // Show general stats
        metricsValue.textContent = todayTotal.toLocaleString();
        metricsLabel.textContent = "QA Summary";
        
        metricsContent.innerHTML = `
          <div class="qa-metric-item">
            <span class="qa-metric-label">Weekly Avg</span>
            <span class="qa-metric-value">${avgDaily.toLocaleString()}/day</span>
          </div>
          <div class="qa-metric-item">
            <span class="qa-metric-label">Active Engineers</span>
            <span class="qa-metric-value">${engineerCount}</span>
          </div>
          <div class="qa-metric-item">
            <span class="qa-metric-label">Avg per Engineer</span>
            <span class="qa-metric-value">${avgPerEngineer.toLocaleString()}</span>
          </div>
          <div class="qa-metric-item">
            <span class="qa-metric-label">Consistency</span>
            <span class="qa-metric-value">${Math.round(avgConsistency)}%</span>
          </div>
          <div class="qa-metric-item">
            <span class="qa-metric-label">Week Total</span>
            <span class="qa-metric-value">${weeklyTotal.toLocaleString()}</span>
          </div>
        `;
      } else if (currentView === 1) {
        // Show data-bearing records
        metricsValue.innerHTML = '<img class="qa-metrics-icon" src="assets/trophy-gold.svg" alt="Record">';
        metricsLabel.textContent = "Data Bearing - Most QA'd in 1 Day!";
        
        const dbRecords = dailyRecords.data_bearing_records || [];
        if (dbRecords.length === 0) {
          metricsContent.innerHTML = '<div style="padding: 12px; text-align: center; color: #888;">No records</div>';
        } else {
          const medals = ['🥇', '🥈', '🥉', '4.', '5.', '6.'];
          metricsContent.innerHTML = dbRecords.map((record, index) => `
            <div class="qa-metric-item">
              <span class="qa-metric-label">${medals[index] || (index + 1 + '.')} ${escapeHtml(record.name)}</span>
              <span class="qa-metric-value">${record.count.toLocaleString()}</span>
            </div>
          `).join('');
        }
      } else if (currentView === 2) {
        // Show non-data-bearing records
        metricsValue.innerHTML = '<img class="qa-metrics-icon" src="assets/trophy-silver.svg" alt="Record">';
        metricsLabel.textContent = "Non-Data Bearing - Most QA'd in 1 Day!";
        
        const ndbRecords = dailyRecords.non_data_bearing_records || [];
        if (ndbRecords.length === 0) {
          metricsContent.innerHTML = '<div style="padding: 12px; text-align: center; color: #888;">No records</div>';
        } else {
          const medals = ['🥇', '🥈', '🥉', '4.', '5.', '6.'];
          metricsContent.innerHTML = ndbRecords.map((record, index) => `
            <div class="qa-metric-item">
              <span class="qa-metric-label">${medals[index] || (index + 1 + '.')} ${escapeHtml(record.name)}</span>
              <span class="qa-metric-value">${record.count.toLocaleString()}</span>
            </div>
          `).join('');
        }
      }
      
      currentView = (currentView + 1) % 3;
    }
    
    // Initial display
    updateMetricsView();
    
    // Flip every 30 seconds for smooth TV viewing
    if (metricsFlipIntervalId) {
      clearInterval(metricsFlipIntervalId);
    }
    metricsFlipIntervalId = setInterval(updateMetricsView, 30000);
    
    // Also allow manual click to flip
    if (metricsCard) {
      metricsCard.style.cursor = 'pointer';
      metricsCard.onclick = updateMetricsView;
    }
  }
  
  // Show error message on QA dashboard
  // Show error message on QA dashboard
  function showQAError(message) {
    const deWeeklyEngineers = document.getElementById('deWeeklyEngineers');
    const deAllTimeEngineers = document.getElementById('deAllTimeEngineers');
    const qaWeeklyEngineers = document.getElementById('qaWeeklyEngineers');
    const qaAllTimeEngineers = document.getElementById('qaAllTimeEngineers');
    
    const errorHtml = `
      <div style="padding: 20px; text-align: center; color: #ff6b6b;">
        <div style="font-size: 14px; font-weight: 600;">⚠️ ${message}</div>
      </div>
    `;
    
    if (deWeeklyEngineers) deWeeklyEngineers.innerHTML = errorHtml;
    if (deAllTimeEngineers) deAllTimeEngineers.innerHTML = errorHtml;
    if (qaWeeklyEngineers) qaWeeklyEngineers.innerHTML = errorHtml;
    if (qaAllTimeEngineers) qaAllTimeEngineers.innerHTML = errorHtml;
  }
  
  // Helper function to escape HTML
  function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  function formatQaName(rawName) {
    if (!rawName) return '';
    const name = rawName.toString().trim();
    if (!name) return '';
    if (name.toLowerCase() === '(unassigned)') return '(unassigned)';
    if (name.toLowerCase() === 'unknown') return 'Unknown';

    const withoutDomain = name.replace(/@.*$/, '').replace(/[._-]+/g, ' ').trim();
    const parts = withoutDomain.split(/\s+/).filter(Boolean);
    if (parts.length === 0) return name;
    if (parts.length === 1) {
      return parts[0].charAt(0).toUpperCase() + parts[0].slice(1);
    }
    const first = parts[0];
    const lastInitial = parts[parts.length - 1][0];
    return `${first.charAt(0).toUpperCase() + first.slice(1)} ${lastInitial.toUpperCase()}`;
  }

  function getQaInitials(displayName) {
    if (!displayName) return '';
    const cleaned = displayName.replace(/[^a-zA-Z\s]/g, '').trim();
    if (!cleaned) return '';
    const parts = cleaned.split(/\s+/).filter(Boolean);
    if (parts.length >= 2) {
      return `${parts[0][0]}${parts[parts.length - 1][0]}`.toUpperCase();
    }
    return cleaned.slice(0, 2).toUpperCase();
  }
  
  function switchDashboard(index) {
    const erasureView = document.getElementById('erasureStatsView');
    const qaView = document.getElementById('qaStatsView');
    const titleElem = document.getElementById('dashboardTitle');
    const supportsGrid = typeof CSS !== 'undefined' && CSS.supports && CSS.supports('display', 'grid');
    
    if (index < 0 || index >= dashboards.length) {
      return;
    }
    
    currentDashboard = index;
    const dashboard = dashboards[index];

    if (erasureView) {
      erasureView.style.removeProperty('display');
    }
    if (qaView) {
      qaView.style.removeProperty('display');
    }

    if (dashboard === 'erasure') {
      erasureView.classList.add('is-active');
      qaView.classList.remove('is-active');
      erasureView.style.display = 'flex';
      qaView.style.display = 'none';
      titleElem.textContent = dashboardTitles.erasure;
    } else if (dashboard === 'qa') {
      erasureView.classList.remove('is-active');
      qaView.classList.add('is-active');
      erasureView.style.display = 'none';
      qaView.style.display = supportsGrid ? 'grid' : 'block';
      
      titleElem.textContent = dashboardTitles.qa;
      const performersGrid = document.getElementById('qaTopPerformersGrid');
      const techniciansGrid = document.getElementById('qaTechniciansGrid');
      if (performersGrid) {
        performersGrid.innerHTML = '<div style="grid-column: 1 / -1; padding: 24px; text-align: center; color: #999;">Loading QA data…</div>';
      }
      if (techniciansGrid) {
        techniciansGrid.innerHTML = '';
      }
      // Load QA data when switching to QA dashboard (but skip on initial restore)
      const periodValue = document.getElementById('dateSelector')?.value || 'this-week';
      const period = periodValue.replace(/-/g, '_');  // Convert "this-week" to "this_week"
      if (!_initialDashboardRestore) {
        loadQADashboard(period);
      } else {
        // Show a lightweight placeholder so page doesn't hammer QA endpoints
        const performersGrid = document.getElementById('qaTopPerformersGrid');
        if (performersGrid) performersGrid.innerHTML = '<div style="grid-column: 1 / -1; padding: 24px; text-align: center; color: #999;">QA data deferred — click to load</div>';
        // Attach click to view to trigger a manual load when user interacts
        const qaViewEl = qaView;
        const oneTimeLoad = () => {
          qaViewEl.removeEventListener('click', oneTimeLoad);
          loadQADashboard(period);
        };
        qaViewEl.addEventListener('click', oneTimeLoad);
      }
    }
    
    // Store preference
    localStorage.setItem('currentDashboard', index);
  }
  
  // Dashboard navigation buttons - respect lock
  document.getElementById('prevDashboard').addEventListener('click', () => {
    if (dashboardLocked) return;  // Prevent navigation if locked
    let newIndex = currentDashboard - 1;
    if (newIndex < 0) {
      newIndex = dashboards.length - 1;
    }
    switchDashboard(newIndex);
  });
  
  document.getElementById('nextDashboard').addEventListener('click', () => {
    if (dashboardLocked) return;  // Prevent navigation if locked
    let newIndex = currentDashboard + 1;
    if (newIndex >= dashboards.length) {
      newIndex = 0;
    }
    switchDashboard(newIndex);
  });
  
  // Lock dashboard feature - prevent switching on TVs
  function lockDashboard() {
    dashboardLocked = true;
    localStorage.setItem('dashboardLocked', 'true');
    console.log('Dashboard locked to', dashboards[currentDashboard]);
  }
  
  function unlockDashboard() {
    dashboardLocked = false;
    localStorage.removeItem('dashboardLocked');
    console.log('Dashboard unlocked');
  }
  
  // Check if dashboard should be locked (e.g., from TV display)
  const savedLock = localStorage.getItem('dashboardLocked') === 'true';
  if (savedLock) {
    lockDashboard();
  }

  // DEV HELPERS: Reveal manager UI only when explicitly requested via ?dev=1
  try {
    const params = new URLSearchParams(location.search);
    if (params.get('dev') === '1') {
      console.log('[Dev] ?dev=1 detected — unlocking dashboard and revealing manager UI');
      try { unlockDashboard(); } catch (err) { console.warn('unlockDashboard not available yet', err); }
      try {
        const mgr = document.querySelector('.manager-btn');
        if (mgr) mgr.style.display = 'inline-block';
        const up = document.getElementById('loginUpgradeIcon');
        if (up) up.style.display = 'inline-block';
      } catch (err) {
        console.warn('Failed to reveal manager button', err);
      }
    }
  } catch (err) {
    // silent
  }
  
  // Restore last dashboard view but avoid auto-fetching QA data on page load
  const savedDashboard = parseInt(localStorage.getItem('currentDashboard') || '0');
  // If savedDashboard is QA (1) we will restore the view but defer the initial QA data load
  let _initialDashboardRestore = true;
  function restoreDashboard(index) {
    // switchDashboard will not trigger QA fetch when _initialDashboardRestore is true
    switchDashboard(index);
    _initialDashboardRestore = false;
  }
  restoreDashboard(savedDashboard);
  
  // Refresh QA data when period changes
  if (document.getElementById('dateSelector')) {
    document.getElementById('dateSelector').addEventListener('change', (e) => {
      if (currentDashboard === 1) {  // QA dashboard index
        const period = e.target.value.replace('-', '_');
        loadQADashboard(period);
      }
    });
  }
  
  // Auto-refresh data every 2 minutes for live updates
  setInterval(() => {
    if (currentDashboard === 1) {  // Only refresh if on QA dashboard
      const periodValue = document.getElementById('dateSelector')?.value || 'this-week';
      const period = periodValue.replace(/-/g, '_');
      console.log('Auto-refreshing QA data...');
      loadQADashboard(period);
    }
  }, 2 * 60 * 1000); // 2 minutes

  // Erasure-specific exports moved to dashboard/erasure.js; delegate to window
  async function generateCSV() { return window.generateCSV ? window.generateCSV() : ''; }
  async function downloadExcel() { return window.downloadExcel ? window.downloadExcel() : undefined; }
  function showExportLoading() { return window.showExportLoading && window.showExportLoading(); }
  function hideExportLoading() { return window.hideExportLoading && window.hideExportLoading(); }
  let customRangeData = window.customRangeData || null;
  function populateMonthOptions() { return window.populateMonthOptions && window.populateMonthOptions(); }
  function showCustomRangeModal() { return window.showCustomRangeModal && window.showCustomRangeModal(); }
  function hideCustomRangeModal(revertSelector = true) { return window.hideCustomRangeModal && window.hideCustomRangeModal(revertSelector); }
  function handleCustomRangeConfirm() { return window.handleCustomRangeConfirm && window.handleCustomRangeConfirm(); }

  // Download button removed from dashboard - exports available via manager.html

  // ==================== INITIALIZATION ====================
  // Kick off refresh loops (after all functions are defined)
  refreshSummary();
  refreshAllTopLists();
  refreshByTypeCounts();
  refreshLeaderboard();
  
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
    refreshSummary();
    refreshAllTopLists();
    refreshByTypeCounts();
    refreshLeaderboard();
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


  // --- Middle Row Flip Mechanic ---
  // Enhanced: renderTopList now supports multiple faces for flip/rotation
  function renderTopListWithLabel(listId, engineers, label, total) {
    const el = document.getElementById(listId);
    // Track current face/period for each card
    el.dataset.currentPeriod = label;
    // Fade out for smooth transition
    el.style.opacity = 0;
    setTimeout(() => {
      el.innerHTML = '';
      if (engineers && engineers.length > 0) {
        engineers.forEach((eng) => {
          const name = truncateInitials((eng.initials || '').toString().trim());
          if (!name) return;
          const li = document.createElement('li');
          const avatar = getAvatarDataUri(name);
          li.innerHTML = `
            <span class="engineer-chip">
              <span class="engineer-avatar" style="background-image: url(${avatar})"></span>
              <span class="engineer-name">${name}</span>
            </span>
            <span class="value">${eng.count}</span>`;
          el.appendChild(li);
        });
      } else {
        // Show 'No data yet' if empty
        const li = document.createElement('li');
        li.innerHTML = `<span class="no-data">No data yet</span>`;
        el.appendChild(li);
      }
      // Always update label for the face (e.g., Today, Month, All Time)
      if (label) {
        const header = el.parentElement.querySelector('.stat-card__header, .card-header, .category-header, .top-row, .card-title-row') || el.parentElement;
        let labelEl = header.querySelector('.category-period-label');
        if (!labelEl) {
          labelEl = document.createElement('span');
          labelEl.className = 'category-period-label';
          labelEl.style = 'font-size:0.95em;color:var(--muted);margin-right:8px;vertical-align:middle;';
          header.insertBefore(labelEl, header.firstChild);
        }
        // Always set label text, including for All Time
        labelEl.textContent = label;
      }
      // Update the pip (total) ONLY if this is the currently visible face
      const header = el.parentElement.querySelector('.stat-card__header, .card-header, .category-header, .top-row, .card-title-row') || el.parentElement;
      const pill = header.querySelector('.pill');
      if (pill && typeof total === 'number') {
        // Only update pip if this face is currently visible
        if (el.dataset.currentPeriod === label) pill.textContent = total;
      }
      setTimeout(() => {
        el.style.opacity = 1;
      }, 200);
    }, 200);
  }

  // Enhanced: fetches for today, month, all-time for flip faces
  async function refreshTopByTypeAllScopes(type, listId) { return window.refreshTopByTypeAllScopes ? window.refreshTopByTypeAllScopes(type, listId) : Promise.resolve(); }

  // Enhanced: fetch all scopes for each category
  function refreshAllTopListsWithFlip() {
    categories.forEach(c => refreshTopByTypeAllScopes(c.key, c.listId));
  }

  // NEW: Refresh category rotator cards (delegate to migrated implementation)
  async function refreshCategoryRotatorCards() { return window.refreshCategoryRotatorCards ? window.refreshCategoryRotatorCards() : Promise.resolve(); }

  function setupCategoryFlipCards() { return window.setupCategoryFlipCards ? window.setupCategoryFlipCards() : null; }



  // Replace original refreshAllTopLists with the new category rotator logic
  window.refreshAllTopLists = function() {
    return refreshCategoryRotatorCards();
  };

  // On load, refresh category rotator cards
  refreshCategoryRotatorCards();

  // Start rotation intervals
  setTimeout(() => {
    setupRotatorCards();
  }, 2000);




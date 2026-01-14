(async function () {
  const cfg = await fetch('config.json').then(r => r.json());

  // ==================== CHART PLUGINS ====================

  // Depth/gloss plugin to give donuts a subtle 3D feel (optimized for TV performance)
  const donutDepthPlugin = {
    id: 'donutDepth',
    afterDatasetsDraw(chart) {
      const meta = chart.getDatasetMeta(0);
      const arc = meta?.data?.[0];
      if (!arc) return;

      const { ctx } = chart;
      const { x, y, innerRadius, outerRadius } = arc;
      
      // Validate that values are finite before drawing
      if (!Number.isFinite(x) || !Number.isFinite(y) || !Number.isFinite(innerRadius) || !Number.isFinite(outerRadius)) {
        return;
      }

      const ringThickness = outerRadius - innerRadius;
      if (ringThickness <= 0) return;

      // Simplified shadow - just the bottom part for subtle depth
      ctx.save();
      ctx.globalCompositeOperation = 'destination-over';
      try {
        const shadowGrad = ctx.createRadialGradient(
          x,
          y + ringThickness * 0.5,
          outerRadius * 0.7,
          x,
          y + ringThickness * 0.5,
          outerRadius + 8
        );
        shadowGrad.addColorStop(0, 'rgba(0, 0, 0, 0.1)');
        shadowGrad.addColorStop(1, 'rgba(0, 0, 0, 0)');
        ctx.fillStyle = shadowGrad;
        ctx.beginPath();
        ctx.arc(x, y, outerRadius + 6, 0, Math.PI * 2);
        ctx.fill();
      } catch (e) {
        // Silently fail - not critical
      }
      ctx.restore();

      // Very subtle top gloss - simplified
      ctx.save();
      try {
        const shineGrad = ctx.createLinearGradient(x, y - outerRadius, x, y - innerRadius);
        shineGrad.addColorStop(0, 'rgba(255, 255, 255, 0.15)');
        shineGrad.addColorStop(1, 'rgba(255, 255, 255, 0)');
        ctx.fillStyle = shineGrad;
        ctx.beginPath();
        ctx.arc(x, y, outerRadius, 0, Math.PI * 2);
        ctx.arc(x, y, innerRadius, 0, Math.PI * 2, true);
        ctx.closePath();
        ctx.fill();
      } catch (e) {
        // Silently fail - not critical
      }
      ctx.restore();
    },
  };

  Chart.register(donutDepthPlugin);

  function donut(canvasId) {
    const ctxEl = document.getElementById(canvasId);
    const primary = getComputedStyle(document.documentElement)
      .getPropertyValue('--ring-primary').trim();
    const secondary = getComputedStyle(document.documentElement)
      .getPropertyValue('--ring-secondary').trim();

    const chart = new Chart(ctxEl, {
      type: 'doughnut',
      data: {
        labels: ['Value', 'Remaining'],
        datasets: [{
          data: [0, 0],
          backgroundColor: [secondary, primary],
          borderWidth: 0,
          borderRadius: 0,
          hoverOffset: 8
        }]
      },
      options: {
        responsive: true,
        cutout: '68%',
        animation: { duration: 400 },
        plugins: {
          legend: { display: false },
          tooltip: {
            enabled: true,
            callbacks: {
              label: function(ctx) {
                return ctx.label + ': ' + ctx.raw;
              }
            }
          }
        }
      }
    });
    
    return chart;
  }

  // Apply theme variables
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

  // Race state
  let raceData = { engineer1: null, engineer2: null, engineer3: null, firstFinisher: null };
  let winnerAnnounced = false;

  // Greenie state
  let greenieState = {
    currentStats: { todayTotal: 0, monthTotal: 0, byType: {} },
    lastQuotes: [],
    lastShowTime: 0,
  };

  // Wake helpers to keep Fire Stick screen alive
  let wakeLock = null;
  let audioCtx = null;
  let silentOsc = null;
  let keepAliveVideo = null;

  const greenieQuotes = {
    praise: [
      (eng) => `${eng}, you're crushing it! Keep up the amazing work! 💪`,
      (eng) => `${eng}, you're the star of the show today! ⭐`,
      (eng) => `Way to go ${eng}! You're on fire! 🔥`,
      (eng) => `${eng}, absolutely dominating the leaderboard! 👑`,
    ],
    targetProgress: [
      (diff) => `We're only ${diff} erasures away from today's target! Push push push! 🎯`,
      (diff) => `${diff} more erasures to hit today's goal! We've got this! 💪`,
      (diff) => `Just ${diff} erasures left to smash today's target! 🚀`,
      (diff) => `Target incoming! Only ${diff} to go! 🎉`,
    ],
    categoryWins: [
      (cat) => `${cat} erasures are looking absolutely stellar today! 🌟`,
      (cat) => `${cat} team, you're absolutely crushing it! Keep that momentum! 🚀`,
      (cat) => `Outstanding work on the ${cat}! That's what I like to see! 💯`,
    ],
    motivation: [
      `Data erasure heroes, that's what you all are! 🦸‍♀️`,
      `Every erasure counts! Keep up the fantastic work! ✨`,
      `You're doing amazing work protecting data today! 🛡️`,
      `This team is unstoppable! Let's keep rolling! 🎯`,
      `Making a real difference one erasure at a time! 👍`,
      `The warehouse is looking spotless thanks to you! ✨`,
    ],
  };

  function getGreenieQuote() {
    // Update current stats for dynamic quotes
    const todayTotal = parseInt(document.getElementById('totalTodayValue').textContent) || 0;
    const target = parseInt(document.getElementById('erasedTarget').textContent) || 500;
    const leaderboardBody = document.getElementById('leaderboardBody');
    const topEngineer = leaderboardBody?.querySelector('tr')?.textContent || '';
    
    greenieState.currentStats = {
      todayTotal,
      target,
      diff: Math.max(0, target - todayTotal),
    };

    // Get random quote category
    const quoteCategories = ['praise', 'targetProgress', 'categoryWins', 'motivation'];
    let selectedCategory;
    let quote;
    let attempts = 0;

    // Try to avoid repeating the same category/type
    do {
      selectedCategory = quoteCategories[Math.floor(Math.random() * quoteCategories.length)];
      const quoteList = greenieQuotes[selectedCategory];
      
      if (selectedCategory === 'praise') {
        // Get top engineer initials
        const initials = topEngineer.split('\n')[0] || 'Team';
        quote = quoteList[Math.floor(Math.random() * quoteList.length)](initials);
      } else if (selectedCategory === 'targetProgress') {
        quote = quoteList[Math.floor(Math.random() * quoteList.length)](greenieState.currentStats.diff);
      } else if (selectedCategory === 'categoryWins') {
        const categoryList = ['Laptops/Desktops', 'Servers', 'Macs', 'Mobiles'];
        const category = categoryList[Math.floor(Math.random() * categoryList.length)];
        quote = quoteList[Math.floor(Math.random() * quoteList.length)](category);
      } else {
        quote = quoteList[Math.floor(Math.random() * quoteList.length)];
      }

      attempts++;
    } while (greenieState.lastQuotes.includes(quote) && attempts < 5);

    // Track quote to avoid repeats
    greenieState.lastQuotes.push(quote);
    if (greenieState.lastQuotes.length > 8) {
      greenieState.lastQuotes.shift();
    }

    return quote;
  }

  function showGreenie() {
    const container = document.getElementById('greenieContainer');
    const quoteEl = document.getElementById('greenieQuote');
    const wrapper = container.querySelector('.greenie-wrapper');

    // Get quote and display
    const quote = getGreenieQuote();
    quoteEl.textContent = quote;

    // Remove exit animation class if present
    wrapper.classList.remove('exit');

    // Show Greenie
    container.classList.remove('hidden');
    greenieState.lastShowTime = Date.now();

    // Auto-hide after 10 seconds total (2s in + 6s display + 2s out)
    setTimeout(() => {
      wrapper.classList.add('exit');
      setTimeout(() => {
        container.classList.add('hidden');
        wrapper.classList.remove('exit');
      }, 2000);
    }, 6000);
  }

  function checkGreenieTime() {
    const now = new Date();
    const hours = now.getHours();
    const minutes = now.getMinutes();

    // Only show between 8:00 and 16:00
    if (hours < 8 || hours >= 16) return;

    // Check if 15 minutes have passed since last show
    const timeSinceLastShow = Date.now() - greenieState.lastShowTime;
    const fifteenMinutes = 15 * 60 * 1000;

    if (timeSinceLastShow >= fifteenMinutes) {
      // Only show at specific times to avoid random triggers: :00, :15, :30, :45
      if (minutes === 0 || minutes === 15 || minutes === 30 || minutes === 45) {
        showGreenie();
      }
    }
  }

  async function refreshSummary() {
    try {
      const res = await fetch('/metrics/summary');
      if (!res.ok) throw new Error('HTTP ' + res.status);
      const data = await res.json();

      const todayTotal = data.todayTotal || 0;
      const monthTotal = data.monthTotal || 0;
      document.getElementById('totalTodayValue').textContent = todayTotal;
      document.getElementById('monthTotalValue').textContent = monthTotal;

      updateDonut(totalTodayChart, todayTotal, cfg.targets.erased);
      updateDonut(monthChart, monthTotal, cfg.targets.month || 10000);

      const lastUpdated = Date.now();
      document.getElementById('last-updated').textContent = 'Last updated: ' + new Date(lastUpdated).toLocaleTimeString();
      document.getElementById('stale-indicator').classList.add('hidden');
      
      // Keep screen alive by logging activity
      keepScreenAlive();
    } catch (err) {
      console.error('Summary refresh error:', err);
      document.getElementById('stale-indicator').classList.remove('hidden');
    }
  }

  function renderTopList(listId, engineers) {
    const el = document.getElementById(listId);
    el.innerHTML = '';
    if (engineers && engineers.length > 0) {
      engineers.forEach((eng) => {
        const name = (eng.initials || '').toString().trim();
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
    }
  }

  async function refreshTopByType(type, listId) {
    try {
      const res = await fetch(`/metrics/engineers/top-by-type?type=${encodeURIComponent(type)}`);
      if (!res.ok) throw new Error('HTTP ' + res.status);
      const data = await res.json();
      renderTopList(listId, data.engineers);
    } catch (err) {
      console.error('Top-by-type refresh error:', type, err);
    }
  }

  function refreshAllTopLists() {
    categories.forEach(c => refreshTopByType(c.key, c.listId));
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

  async function refreshLeaderboard() {
    try {
      const res = await fetch('/metrics/engineers/leaderboard?scope=today&limit=5');
      if (!res.ok) throw new Error('HTTP ' + res.status);
      const data = await res.json();
      const body = document.getElementById('leaderboardBody');
      body.innerHTML = '';
      // Display only first 3 in the leaderboard table, but get all 5 for the race
      (data.items || []).slice(0, 3).forEach((row, idx) => {
        const tr = document.createElement('tr');
        const color = getEngineerColor(row.initials || '');
        const avatar = getAvatarDataUri(row.initials || '');
        const lastActive = formatTimeAgo(row.lastActive);
        if (idx === 0) tr.classList.add('leader');
        tr.innerHTML = `
          <td>
            <span class="engineer-avatar" style="background-image: url(${avatar}); border-color: ${color}"></span>
            <span class="engineer-name">${row.initials || ''}</span>
          </td>
          <td class="value-strong">${row.erasures || 0}</td>
          <td class="time-ago">${lastActive}</td>
        `;
        body.appendChild(tr);
      });

      // Update race positions with all top 5 engineers
      updateRace(data.items || []);
    } catch (err) {
      console.error('Leaderboard refresh error:', err);
    }
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
        
        // Move car up the lane based on percentage (0% = bottom, 95% = near top)
        carEl.style.bottom = `${percentage}%`;
        
        // Update trail height from bottom to current car position
        trailEl.style.height = `${percentage}%`;
        
        // Color trail to match engineer color
        const engineerColor = getEngineerColor(engineer.initials || '');
        trailEl.style.background = `linear-gradient(to top, ${engineerColor}, ${engineerColor}40)`;
        
        // Update label with engineer initials
        labelEl.textContent = `${engineer.initials || '?'}`;
        labelEl.style.color = engineerColor;

        // Check if car has finished (reached top/100%)
        if (erasures >= maxErasures && !engineer.finished) {
          engineer.finished = true;
          // Trigger winner announcement if this is the first to finish
          if (!raceData.firstFinisher) {
            raceData.firstFinisher = engineer;
            announceWinner();
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
    if (hours === 15 && minutes === 58 && !winnerAnnounced) {
      winnerAnnounced = true;
      announceWinner();
    }

    // Reset flag at midnight for next day
    if (hours === 0 && minutes === 0) {
      winnerAnnounced = false;
    }
  }

  function announceWinner() {
    const winner = raceData.engineer1;
    if (!winner) return;

    const modal = document.getElementById('winnerModal');
    const winnerText = document.getElementById('winnerText');
    const winnerSubtext = document.getElementById('winnerSubtext');

    winnerText.textContent = `🏆 ${winner.initials} WINS! 🏆`;
    winnerSubtext.textContent = `${winner.erasures} erasures today`;

    modal.classList.remove('hidden');

    // Trigger confetti
    triggerConfetti();

    // Hide modal after 5 seconds
    setTimeout(() => {
      modal.classList.add('hidden');
    }, 5000);
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
      '#ff6b35', // orange
      '#a78bfa', // purple
    ];

    const defaults = {
      origin: { y: 0 },
      zIndex: 10000,
    };

    // Burst from multiple points
    confetti({
      ...defaults,
      particleCount: 100,
      spread: 70,
      startVelocity: 55,
      colors: confettiColors,
    });

    // Second burst after delay
    setTimeout(() => {
      confetti({
        ...defaults,
        particleCount: 50,
        spread: 100,
        startVelocity: 45,
        colors: confettiColors,
      });
    }, 150);
  }

  function renderBars(counts) {
    const total = Object.values(counts).reduce((a, b) => a + b, 0) || 1;
    const defs = categories;
    const container = document.getElementById('byTypeBars');
    if (!container) return;
    container.innerHTML = '';
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
      container.appendChild(row);
    });
  }

  function updateDonut(chart, value, target) {
    const remaining = Math.max(target - value, 0);
    chart.data.datasets[0].data = [value, remaining];
    chart.canvas.dataset.target = target;
    chart.update();
    
    // Trigger pulse animation on chart container
    const container = chart.canvas.closest('.donut-card');
    if (container) {
      container.classList.add('pulse-update');
      setTimeout(() => container.classList.remove('pulse-update'), 600);
    }
  }

  async function requestWakeLock() {
    if (!('wakeLock' in navigator)) return;
    try {
      wakeLock = await navigator.wakeLock.request('screen');
      wakeLock.addEventListener('release', () => { wakeLock = null; });
    } catch (err) {
      console.warn('Wake lock request failed', err);
    }
  }

  function ensureSilentAudio() {
    // Very quiet oscillator to count as activity and keep Fire Stick awake
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
  }

  function startKeepAliveVideo() {
    // Hidden muted looping video to keep media session active on devices that permit autoplay
    try {
      if (keepAliveVideo && keepAliveVideo.readyState > 0) {
        keepAliveVideo.play().catch(() => {});
        return;
      }
      const vid = document.createElement('video');
      vid.muted = true;
      vid.loop = true;
      vid.playsInline = true;
      vid.autoplay = true;
      vid.setAttribute('playsinline', '');
      vid.style.position = 'fixed';
      vid.style.width = '1px';
      vid.style.height = '1px';
      vid.style.opacity = '0.001';
      vid.style.bottom = '0';
      vid.style.left = '0';
      vid.style.pointerEvents = 'none';
      // 1s silent WebM
      vid.src = 'data:video/webm;base64,GkXfo59ChoEBQveBAULygQRC9+BBQvWBAULpgQRC8YEEQvGBAAAB9uWdlYm0BVmVyc2lvbj4xAAAAAAoAAABHYXZrVjkAAAAAAAAD6aNjYWI9AAAZY2FkYwEAAAAAAAAAAAAAAAAAAAAAAAACdC9hAAAAAAACAAEAAQAAAQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=';
      document.body.appendChild(vid);
      keepAliveVideo = vid;
      vid.play().catch(() => {});
    } catch (err) {
      console.warn('Keep-alive video failed', err);
    }
  }

  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) {
      requestWakeLock();
      ensureSilentAudio();
      startKeepAliveVideo();
    }
  });

  function keepScreenAlive() {
    if (document.hidden) return;
    requestWakeLock();
    ensureSilentAudio();
    startKeepAliveVideo();
    document.body.style.opacity = '0.999';
    setTimeout(() => { document.body.style.opacity = '1'; }, 80);
  }
  
  // Keep screen alive every 2 minutes to avoid Fire Stick sleep
  setInterval(keepScreenAlive, 2 * 60 * 1000);

  // First shot on load
  keepScreenAlive();

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
  
  let analyticsCharts = {};

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
    const canvas = document.getElementById('chartWeeklyCategoryTrends');
    if (!canvas) return;

    if (analyticsCharts.categoryTrends) {
      analyticsCharts.categoryTrends.destroy();
    }

    const trends = data.trends;
    const allDates = [...new Set(
      Object.values(trends).flatMap(arr => arr.map(d => d.date))
    )].sort();

    const datasets = Object.keys(trends).map((category, idx) => {
      const colorMap = {
        'laptops_desktops': cfg.theme.ringPrimary,
        'servers': cfg.theme.ringSecondary,
        'macs': '#ffcc00',
        'mobiles': cfg.theme.ringSecondary
      };
      
      return {
        label: category.replace('_', ' / ').toUpperCase(),
        data: allDates.map(date => {
          const entry = trends[category].find(d => d.date === date);
          return entry ? entry.count : 0;
        }),
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
          },
          title: {
            display: true,
            text: 'Last 7 Days',
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
      return `
      <tr>
        <td>
          <span class="engineer-avatar" style="background-image: url(${avatar})"></span>
          <span class="engineer-name">${eng.initials}</span>
        </td>
        <td>${eng.weeklyTotal}</td>
        <td>${eng.daysActive}/7</td>
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
    // Mock data - replace with real API calls
    document.getElementById('recordBestDay').textContent = '687';
    document.getElementById('recordBestDayDate').textContent = 'Dec 15, 2025';
    document.getElementById('recordTopEngineer').textContent = 'MS';
    document.getElementById('recordTopEngineerCount').textContent = '8,432 total erasures';
    document.getElementById('currentStreak').textContent = '3';
  }

  function updateMonthlyProgress() {
    const monthTotal = parseInt(document.getElementById('monthTotalValue')?.textContent) || 0;
    const today = new Date().getDate();
    const daysInMonth = new Date(new Date().getFullYear(), new Date().getMonth() + 1, 0).getDate();
    
    const dailyAvg = Math.round(monthTotal / today);
    document.getElementById('monthlyAverage').textContent = dailyAvg;
    
    const targetMonthly = parseInt(cfg.targets.month);
    const projectedTotal = Math.round(dailyAvg * daysInMonth);
    const paceStatus = projectedTotal >= targetMonthly ? '✅ On Pace' : '⚠️ Behind';
    document.getElementById('paceIndicator').textContent = paceStatus;
    
    document.getElementById('daysRemaining').textContent = daysInMonth - today;
  }

  function updateRaceUpdates() {
    const leaderboardBody = document.getElementById('leaderboardBody');
    const rows = leaderboardBody?.querySelectorAll('tr') || [];
    
    if (rows.length >= 2) {
      const first = rows[0].querySelectorAll('td');
      const second = rows[1].querySelectorAll('td');
      if (first.length >= 2 && second.length >= 2) {
        const firstName = first[0].textContent.trim();
        const firstCount = parseInt(first[1].textContent.trim()) || 0;
        const secondName = second[0].textContent.trim();
        const secondCount = parseInt(second[1].textContent.trim()) || 0;
        const gap = firstCount - secondCount;
        
        document.getElementById('leaderGap').textContent = `${firstName} leads by ${gap} erasures`;
        
        if (gap <= 5 && gap > 0) {
          document.getElementById('closestRace').textContent = `${secondName} closing in - only ${gap} behind!`;
        } else {
          document.getElementById('closestRace').textContent = 'Race is heating up! 🔥';
        }
      }
    }
    
    if (rows.length >= 3) {
      const third = rows[2].querySelectorAll('td');
      if (third.length >= 2) {
        const thirdName = third[0].textContent.trim();
        const thirdCount = parseInt(third[1].textContent.trim()) || 0;
        document.getElementById('comebackStory').textContent = `${thirdName} making moves with ${thirdCount} erasures`;
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
    const target = parseInt(cfg.targets.daily);
    const percentage = Math.min((todayTotal / target) * 100, 100);
    
    if (todayTotal >= target) {
      document.getElementById('trackerStatus').textContent = '🎯 TARGET ACHIEVED!';
    } else if (todayTotal >= target * 0.8) {
      document.getElementById('trackerStatus').textContent = `${target - todayTotal} away from target`;
    } else {
      document.getElementById('trackerStatus').textContent = `${Math.round(percentage)}% to target`;
    }
    
    const projectedEnd = Math.round((todayTotal / (new Date().getHours() || 1)) * 16);
    document.getElementById('trackerProjection').textContent = `Projected: ${projectedEnd} by end of day`;
    
    document.getElementById('trackerFill').style.width = `${percentage}%`;
    document.getElementById('trackerCurrent').textContent = todayTotal;
    document.getElementById('trackerTarget').textContent = target;
  }

  function createMonthlyMomentumChart() {
    const canvas = document.getElementById('chartMonthlyMomentum');
    if (!canvas) return;

    if (analyticsCharts.monthlyMomentum) {
      analyticsCharts.monthlyMomentum.destroy();
    }

    // Mock weekly data - replace with real API
    const weeklyData = [180, 245, 310, 380];
    
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
  function setupFlipCards() {
    const flipCards = document.querySelectorAll('.flip-card');
    if (flipCards.length === 0) return;

    const flipIntervals = [40000, 45000, 50000, 42000, 48000, 43000, 46000]; // Staggered timings (40-50s) for 7 cards
    
    flipCards.forEach((card, index) => {
      const interval = flipIntervals[index % flipIntervals.length];
      
      function performFlip() {
        card.classList.toggle('flipped');
      }
      
      // Initial flip after 2 seconds
      setTimeout(() => {
        performFlip();
        
        // Flip back after 8 seconds
        setTimeout(() => {
          performFlip();
        }, 8000);
        
        // Setup recurring flips after initial cycle
        setTimeout(() => {
          setInterval(() => {
            performFlip();
            setTimeout(performFlip, 8000);
          }, interval);
        }, 8000);
      }, 2000);
    });
  }

  // Initialize analytics and flip on first load
  setTimeout(async () => {
    await initializeAnalytics();
    setupFlipCards();
  }, 500);

  // Refresh analytics every 5 minutes
  setInterval(() => {
    initializeAnalytics();
  }, 300000);

  // ==================== CSV EXPORT ====================
  
  async function generateCSV() {
    const dateScope = document.getElementById('dateSelector')?.value || 'today';
    const isYesterday = dateScope === 'yesterday';
    
    // Calculate date for display and API calls
    const targetDate = new Date();
    if (isYesterday) {
      targetDate.setDate(targetDate.getDate() - 1);
    }
    const dateStr = targetDate.toLocaleDateString('en-GB');
    const time = new Date().toLocaleTimeString('en-GB');
    
    // Get current displayed values (only valid for "today")
    let todayTotal, monthTotal, target;
    if (!isYesterday) {
      todayTotal = document.getElementById('totalTodayValue')?.textContent || '0';
      monthTotal = document.getElementById('monthTotalValue')?.textContent || '0';
      target = document.getElementById('erasedTarget')?.textContent || '500';
    } else {
      // For yesterday, fetch from API
      todayTotal = '0';
      monthTotal = '0';
      target = '500';
      try {
        const res = await fetch(`/metrics/summary?date=${targetDate.toISOString().split('T')[0]}`);
        if (res.ok) {
          const data = await res.json();
          todayTotal = data.todayTotal || '0';
          monthTotal = data.monthTotal || '0';
        }
      } catch (err) {
        console.error('Failed to fetch summary for yesterday:', err);
      }
    }
    
    // Get leaderboard data (top 3 displayed) - only for today
    const leaderboardRows = [];
    if (!isYesterday) {
      const rows = document.getElementById('leaderboardBody')?.querySelectorAll('tr') || [];
      rows.forEach((row, idx) => {
        const cells = row.querySelectorAll('td');
        if (cells.length >= 2) {
          const engineer = cells[0].textContent.trim();
          const erasures = cells[1].textContent.trim();
          const lastActive = cells[2]?.textContent.trim() || '';
          leaderboardRows.push([idx + 1, engineer, erasures, lastActive]);
        }
      });
    }

    // Fetch full engineer list from API
    let allEngineersRows = [];
    try {
      const apiScope = isYesterday ? 'yesterday' : 'today';
      const res = await fetch(`/metrics/engineers/leaderboard?scope=${apiScope}&limit=50`);
      if (res.ok) {
        const data = await res.json();
        allEngineersRows = (data.items || []).map((eng, idx) => {
          const erasures = eng.erasures || 0;
          const avgPerHour = (erasures / SHIFT_HOURS).toFixed(1);
          
          return [
            idx + 1,
            eng.initials || '',
            erasures,
            formatTimeAgo(eng.lastActive),
            avgPerHour
          ];
        });
      }
    } catch (err) {
      console.error('Failed to fetch full engineer list:', err);
    }

    // Get category data - only for today
    const categoryRows = [];
    if (!isYesterday) {
      categories.forEach(cat => {
        const count = document.getElementById(cat.countId)?.textContent || '0';
        categoryRows.push([cat.label, count]);
      });
    } else {
      // For yesterday, fetch from API
      try {
        const res = await fetch(`/analytics/category-breakdown?date=${targetDate.toISOString().split('T')[0]}`);
        if (res.ok) {
          const data = await res.json();
          (data.categories || []).forEach(cat => {
            categoryRows.push([cat.name, cat.count]);
          });
        }
      } catch (err) {
        console.error('Failed to fetch category data:', err);
      }
    }

    // Get top performers per category - only for today
    const categoryTopPerformers = [];
    if (!isYesterday) {
      categories.forEach(cat => {
        const listEl = document.getElementById(cat.listId);
        if (listEl) {
          const items = listEl.querySelectorAll('li');
          if (items.length > 0) {
            items.forEach(item => {
              const text = item.textContent.trim();
              const parts = text.match(/(.+?)\s+(\d+)$/);
              if (parts) {
                categoryTopPerformers.push([cat.label, parts[1], parts[2]]);
              }
            });
          }
        }
      });
    }

    // Calculate monthly progress metrics
    const today = new Date().getDate();
    const daysInMonth = new Date(new Date().getFullYear(), new Date().getMonth() + 1, 0).getDate();
    const dailyAvg = Math.round(parseInt(monthTotal) / today);
    const projectedTotal = Math.round(dailyAvg * daysInMonth);
    const daysRemaining = daysInMonth - today;
    
    // Build CSV
    const reportTitle = isYesterday ? 'Warehouse Erasure Stats Report (Yesterday)' : 'Warehouse Erasure Stats Report';
    const csv = [
      [reportTitle],
      ['Report Date:', dateStr],
      ['Generated:', new Date().toLocaleDateString('en-GB'), time],
      [],
      ['SUMMARY'],
      ['Metric', 'Value'],
      [isYesterday ? 'Total' : 'Today Total', todayTotal],
      ['Month Total', monthTotal],
      ['Daily Target', target],
      ['Progress to Target', `${Math.round((parseInt(todayTotal) / parseInt(target)) * 100)}%`],
      ['Daily Average (Month)', dailyAvg],
      ['Projected Month Total', projectedTotal],
      ['Days Remaining', daysRemaining],
      [],
    ];

    if (!isYesterday && leaderboardRows.length > 0) {
      csv.push(['TOP 3 ENGINEERS (TODAY)']);
      csv.push(['Rank', 'Engineer', 'Erasures', 'Last Active']);
      csv.push(...leaderboardRows);
      
      // Add race gap analysis
      if (leaderboardRows.length >= 2) {
        const gap = parseInt(leaderboardRows[0][2]) - parseInt(leaderboardRows[1][2]);
        csv.push([]);
        csv.push(['Race Status', `${leaderboardRows[0][1]} leads ${leaderboardRows[1][1]} by ${gap} erasures`]);
      }
      
      csv.push([]);
    }

    csv.push([isYesterday ? 'ALL ENGINEERS (YESTERDAY)' : 'ALL ENGINEERS (TODAY)']);
    csv.push(['Rank', 'Engineer', 'Total Erasures', 'Last Active', 'Avg Per Hour']);
    csv.push(...(allEngineersRows.length > 0 ? allEngineersRows : [['No data available']]));
    csv.push([]);
    
    if (categoryRows.length > 0) {
      csv.push(['BREAKDOWN BY CATEGORY']);
      csv.push(['Category', 'Count']);
      csv.push(...categoryRows);
      csv.push([]);
    }

    if (categoryTopPerformers.length > 0) {
      csv.push(['TOP PERFORMERS BY CATEGORY']);
      csv.push(['Category', 'Engineer', 'Count']);
      csv.push(...categoryTopPerformers);
    }

    return csv.map(row => row.map(cell => `"${cell}"`).join(',')).join('\n');
  }

  async function downloadCSV() {
    const dateScope = document.getElementById('dateSelector')?.value || 'today';
    const csv = await generateCSV();
    const dateSuffix = dateScope === 'yesterday' ? 'yesterday' : new Date().toISOString().split('T')[0];
    const filename = `warehouse-stats-${dateSuffix}.csv`;
    
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const link = document.createElement('a');
    const url = URL.createObjectURL(blob);
    
    link.setAttribute('href', url);
    link.setAttribute('download', filename);
    link.style.visibility = 'hidden';
    
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  }

  // Add button listener
  document.getElementById('downloadBtn')?.addEventListener('click', downloadCSV);

  // ==================== INITIALIZATION ====================
  // Kick off refresh loops (after all functions are defined)
  refreshSummary();
  refreshAllTopLists();
  refreshByTypeCounts();
  refreshLeaderboard();
  
  // Initialize new flip cards
  updateRecordsMilestones();
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
    updateMonthlyProgress();
    updateRaceUpdates();
    updateCategoryChampions();
    updateTargetTracker();
  }, cfg.refreshSeconds * 1000);

})();

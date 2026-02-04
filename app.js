// --- SVG Sparkline Renderer (must be top-level for all uses) ---
function renderSVGSparkline(svgElem, data) {
  const width = 400;
  const height = 48;
  if (!svgElem) return;
  svgElem.innerHTML = '';
  if (!data || data.length < 1) return;
  // If only one point or all values are the same, draw a flat line
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
  // Find min/max for scaling
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;
  // Build path
  const step = width / (data.length - 1);
  let d = '';
  data.forEach((val, i) => {
    const x = i * step;
    // Invert y (SVG origin is top-left)
    const y = height - ((val - min) / range) * (height - 6) - 3;
    d += (i === 0 ? 'M' : 'L') + x.toFixed(2) + ',' + y.toFixed(2) + ' ';
  });
  // Draw filled area
  let fillD = d + `L ${width},${height} L 0,${height} Z`;
  const fill = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  fill.setAttribute('d', fillD);
  fill.setAttribute('fill', 'rgba(140,240,74,0.15)');
  svgElem.appendChild(fill);
  // Draw line
  const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  path.setAttribute('d', d);
  path.setAttribute('fill', 'none');
  path.setAttribute('stroke', '#8cf04a');
  path.setAttribute('stroke-width', '2');
  path.setAttribute('stroke-linejoin', 'round');
  svgElem.appendChild(path);
}
(async function () {
  // ==================== AUTHENTICATION ====================
  
  function setupAuthHeaders(token) {
    // Store token globally and wrap fetch
    window.__authToken = token;
    const originalFetch = window.fetch;
    
    window.fetch = function(resource, config = {}) {
      // Add auth header to all API requests
      if (typeof resource === 'string' && (resource.startsWith('/') || resource.startsWith('http'))) {
        config.headers = config.headers || {};
        config.headers['Authorization'] = 'Bearer ' + window.__authToken;
      }
      return originalFetch.call(this, resource, config);
    };
  }

  async function checkAuth() {
    try {
      // Check for device token first (remembered device)
      const deviceToken = localStorage.getItem('deviceToken');
      if (deviceToken) {
        setupAuthHeaders(deviceToken);
        try {
          const verifyRes = await fetch('/metrics/all-time-totals');
          if (verifyRes.ok) {
            console.log('Device token still valid - auto-login');
            return true;
          }
        } catch (verifyErr) {
          console.warn('Device token verification failed:', verifyErr);
        }
        localStorage.removeItem('deviceToken');
      }

      // Check for session token (from current login)
      const existingToken = sessionStorage.getItem('authToken');
      if (existingToken) {
        setupAuthHeaders(existingToken);
        try {
          const verifyRes = await fetch('/metrics/all-time-totals');
          if (verifyRes.ok) {
            console.log('Session auth token accepted');
            return true;
          }
        } catch (verifyErr) {
          console.warn('Session auth token verification failed:', verifyErr);
        }
        sessionStorage.removeItem('authToken');
      }

      const authRes = await fetch('/auth/status');
      const authData = await authRes.json();
      
      // If already authenticated (local network), proceed
      if (authData.authenticated) {
        console.log('Local network access granted');
        return true;
      }
      
      // External access - show login modal
      console.log('External access requires password');
      showLoginModal();
      return false;
    } catch (err) {
      console.error('Auth check failed:', err);
      // If check fails, show login anyway to be safe
      showLoginModal();
      return false;
    }
  }

  function showLoginModal() {
    console.log('showLoginModal called');
    const modal = document.getElementById('loginModal');
    const form = document.getElementById('loginForm');
    const accessMsg = document.getElementById('accessMessage');
    const passwordInput = document.getElementById('passwordInput');
    const accessGranted = document.getElementById('accessGranted');
    
    console.log('Modal element:', modal);
    
    if (!modal) {
      console.error('Login modal element not found!');
      return;
    }
    
    modal.classList.remove('hidden');
    console.log('Modal should now be visible');
    accessMsg.textContent = 'This dashboard is protected. External access requires a password.';
    form.style.display = 'flex';
    accessGranted.style.display = 'none';
    
    if (!form.dataset.bound) {
      form.dataset.bound = 'true';
      form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const password = passwordInput.value;
        
        try {
          const loginRes = await fetch('/auth/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ password })
          });
          
          if (loginRes.ok) {
            const loginData = await loginRes.json();
            // Store device token for future auto-login (persists across refreshes)
            if (loginData.device_token) {
              localStorage.setItem('deviceToken', loginData.device_token);
              console.log('Device remembered for future logins');
            }
            // Also store session token for this session
            sessionStorage.setItem('authToken', loginData.token);
            
            // Set auth header for future requests
            setupAuthHeaders(loginData.token);
            
            // Show success and continue
            form.style.display = 'none';
            accessGranted.style.display = 'block';
            
            // Close modal after brief delay
            setTimeout(() => {
              modal.classList.add('hidden');
              // Page will continue loading after modal closes
            }, 1000);
          } else {
            passwordInput.style.borderColor = '#f44336';
            passwordInput.value = '';
            accessMsg.textContent = 'Invalid password. Please try again.';
            accessMsg.style.color = '#f44336';
            setTimeout(() => {
              passwordInput.style.borderColor = 'var(--ring-secondary)';
              accessMsg.style.color = 'var(--muted)';
              accessMsg.textContent = 'This dashboard is protected. External access requires a password.';
            }, 2000);
          }
        } catch (err) {
          console.error('Login failed:', err);
          accessMsg.textContent = 'Connection error. Please try again.';
          accessMsg.style.color = '#f44336';
        }
      });
    }
    
    // Focus password input
    passwordInput.focus();
  }

  // Check auth before proceeding
  const isAuthenticated = await checkAuth();
  
  if (!isAuthenticated) {
    // Wait for user to login
    await new Promise(resolve => {
      const checkInterval = setInterval(() => {
        const token = sessionStorage.getItem('authToken');
        if (token) {
          clearInterval(checkInterval);
          setupAuthHeaders(token);
          resolve();
        }
      }, 100);
    });
  }

  // Now proceed with app initialization
  const cfg = await fetch('config.json').then(r => r.json());

  // ==================== ALL TIME TOTALS ====================
  async function refreshAllTimeTotals() {
    try {
      const res = await fetch('/metrics/all-time-totals');
      if (!res.ok) throw new Error('HTTP ' + res.status);
      const data = await res.json();
      const allTime = data.allTimeTotal || 0;
      // Update All Time card value
      const allTimeEl = document.getElementById('allTimeValue');
      if (allTimeEl) {
        allTimeEl.textContent = allTime;
        animateNumberUpdate('allTimeValue');
      }
      // (Removed global pip update. Pip is now updated per card/period in renderTopListWithLabel)
    } catch (err) {
      console.error('All Time totals fetch error:', err);
    }
  }

  // Call on load
  refreshAllTimeTotals();

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

  // Track leaderboard state for Greenie commentary
  let leaderboardState = { leader: null, gap: null };

  // Track race data for winner announcement
  let raceData = { engineer1: null, engineer2: null, engineer3: null, firstFinisher: null, winnerAnnounced: false };

  function triggerGreenie(quote) {
    const container = document.getElementById('greenieContainer');
    const quoteEl = document.getElementById('greenieQuote');
    const wrapper = container.querySelector('.greenie-wrapper');

    // Set the custom quote directly
    if (quoteEl && quote) {
      quoteEl.textContent = quote;
    }

    // Remove exit animation class if present
    wrapper.classList.remove('exit');

    // Show Greenie
    container.classList.remove('hidden');
    greenieState.lastShowTime = Date.now();

    // Auto-hide after 14 seconds total (2s in + 10s display + 2s out)
    setTimeout(() => {
      wrapper.classList.add('exit');
      setTimeout(() => {
        container.classList.add('hidden');
        wrapper.classList.remove('exit');
      }, 2000);
    }, 10000);
  }

  function animateNumberUpdate(elementId) {
    const el = document.getElementById(elementId);
    if (!el) return;
    el.classList.add('pulse-update');
    setTimeout(() => el.classList.remove('pulse-update'), 1000);
  }

  function triggerRaceConfetti() {
    // Check if someone has crossed the finish line
    const racePositions = ['racePos1', 'racePos2', 'racePos3', 'racePos4', 'racePos5'].map(id => {
      const el = document.getElementById(id);
      return el ? parseInt(el.style.bottom) || 0 : -9999;
    });
    
    const maxPosition = Math.max(...racePositions);
    if (maxPosition >= 85) { // Near finish line (90% height)
      confetti({
        particleCount: 100,
        spread: 70,
        origin: { y: 0.6 }
      });
      return true;
    }
    return false;
  }

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

    // Auto-hide after 14 seconds total (2s in + 10s display + 2s out)
    setTimeout(() => {
      wrapper.classList.add('exit');
      setTimeout(() => {
        container.classList.add('hidden');
        wrapper.classList.remove('exit');
      }, 2000);
    }, 10000);
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
      
      // Animate number updates
      const todayEl = document.getElementById('totalTodayValue');
      const monthEl = document.getElementById('monthTotalValue');
      if (todayEl) {
        const oldValue = parseInt(todayEl.textContent) || 0;
        if (oldValue !== todayTotal) {
          todayEl.classList.add('count-animating');
          setTimeout(() => todayEl.classList.remove('count-animating'), 500);
        }
        todayEl.textContent = todayTotal;
        animateNumberUpdate('totalTodayValue');
      }
      if (monthEl) {
        const oldValue = parseInt(monthEl.textContent) || 0;
        if (oldValue !== monthTotal) {
          monthEl.classList.add('count-animating');
          setTimeout(() => monthEl.classList.remove('count-animating'), 500);
        }
        monthEl.textContent = monthTotal;
        animateNumberUpdate('monthTotalValue');
      }

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

  // Make truncateInitials available globally
  function truncateInitials(name) {
    if (!name) return '';
    return name.length > 4 ? name.slice(0, 4) + '…' : name;
  }

  function renderTopList(listId, engineers) {
    const el = document.getElementById(listId);
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
      // Show "No data yet" message
      const li = document.createElement('li');
      li.style.color = 'var(--muted)';
      li.style.textAlign = 'center';
      li.style.padding = '12px 0';
      li.textContent = 'No data yet';
      el.appendChild(li);
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
          laptops_desktops: data.laptops_desktops || 0,
          servers: data.servers || 0,
          macs: data.macs || 0,
          mobiles: data.mobiles || 0,
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

  async function refreshSpeedChallenge(window, listId, statusId) {
    try {
      const res = await fetch(`/competitions/speed-challenge?window=${window}`);
      if (!res.ok) throw new Error('HTTP ' + res.status);
      const data = await res.json();
      const list = document.getElementById(listId);
      const statusEl = document.getElementById(statusId);
      if (statusEl && data.status) {
        const st = data.status;
        const liveBadge = st.isActive ? 'LIVE · ' : '';
        const remaining = st.isActive ? `${st.timeRemainingMinutes} mins left` : `${st.startTime} - ${st.endTime}`;
        statusEl.textContent = `${liveBadge}${st.name} (${remaining})`;
      }
      if (!list) return;
      list.innerHTML = '';
      (data.leaderboard || []).forEach((row, idx) => {
        const li = document.createElement('li');
        li.innerHTML = `
          <span class="speed-rank">${idx + 1}.</span>
          <span class="speed-name">${row.initials || '—'}</span>
          <span class="speed-count">${row.erasures || 0}</span>
        `;
        list.appendChild(li);
      });
    } catch (err) {
      console.error('Speed challenge fetch error:', err);
    }
  }

  async function refreshCategorySpecialists() {
    try {
      const res = await fetch('/competitions/category-specialists');
      if (!res.ok) throw new Error('HTTP ' + res.status);
      const data = await res.json();
      const map = {
        laptops_desktops: 'specLD',
        servers: 'specServers',
        macs: 'specMacs',
        mobiles: 'specMobiles'
      };
      Object.entries(map).forEach(([key, listId]) => {
        const list = document.getElementById(listId);
        if (!list) return;
        list.innerHTML = '';
        const rows = (data.specialists && data.specialists[key]) || [];
        rows.forEach((row, idx) => {
          const li = document.createElement('li');
          const trophyClass = idx === 0 ? 'gold' : idx === 1 ? 'silver' : 'bronze';
          li.innerHTML = `
            <span class="speed-rank">${idx + 1}.</span>
            <span class="speed-name">${row.initials || '—'}</span>
            <span class="speed-count">${row.count || 0}</span>
            <span class="trophy ${trophyClass}"></span>
          `;
          list.appendChild(li);
        });
      });
    } catch (err) {
      console.error('Category specialists fetch error:', err);
    }
  }

  async function refreshConsistency() {
    try {
      const res = await fetch('/competitions/consistency');
      if (!res.ok) throw new Error('HTTP ' + res.status);
      const data = await res.json();
      const list = document.getElementById('consistencyList');
      if (!list) return;
      list.innerHTML = '';
      (data.leaderboard || []).forEach((row, idx) => {
        const li = document.createElement('li');
        li.innerHTML = `
          <span class="speed-rank">${idx + 1}.</span>
          <span class="speed-name">${row.initials || '—'}</span>
          <div class="consistency-stats">
            <span class="speed-count">${row.erasures || 0} erasures</span>
            <span class="gap">avg time between actions: ${row.avgGapMinutes || 0} min • consistency (lower is steadier): ${row.consistencyScore || 0}</span>
          </div>
        `;
        list.appendChild(li);
      });
    } catch (err) {
      console.error('Consistency fetch error:', err);
    }
  }

  async function refreshLeaderboard() {
    try {
      const res = await fetch('/metrics/engineers/leaderboard?scope=today&limit=5');
      if (!res.ok) throw new Error('HTTP ' + res.status);
      const data = await res.json();
      const body = document.getElementById('leaderboardBody');
      body.innerHTML = '';
      // Display all top engineers in the leaderboard table (up to 5 to match race lanes)
      (data.items || []).slice(0, 5).forEach((row, idx) => {
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
      raceData.winnerAnnounced = true;
      announceWinner();
    }

    // Reset flag at midnight for next day
    if (hours === 0 && minutes === 0) {
      raceData.winnerAnnounced = false;
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
  function setupFlipCards() {
    const flipCards = document.querySelectorAll('.flip-card');
    if (flipCards.length === 0) return;

    const FLIP_INTERVAL = 25000;
    const FLIP_HOLD = 12000;
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
      setTimeout(() => {
        performFlip();
        
        // Flip back after hold (wait for flip to complete + hold time)
        setTimeout(() => {
          performFlip();
        }, FLIP_HOLD);
        
        // Setup recurring flips after initial cycle
        setTimeout(() => {
          setInterval(() => {
            performFlip();
            setTimeout(performFlip, FLIP_HOLD);
          }, FLIP_INTERVAL);
        }, FLIP_HOLD);
      }, 2000 + index * 300);
    });
  }

  // Rotate multi-panel cards in place (bottom row)
  const rotatorIntervals = new Map();
  
  function setupRotatorCards() {
    const cards = document.querySelectorAll('.rotator-card');
    if (!cards.length) return;

    cards.forEach((card, cardIdx) => {
      // Clear any existing interval for this card
      if (rotatorIntervals.has(cardIdx)) {
        clearInterval(rotatorIntervals.get(cardIdx));
        rotatorIntervals.delete(cardIdx);
      }
      
      const panels = Array.from(card.querySelectorAll('.panel'));
      if (panels.length <= 1) return;

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
          // First time setup - no indicator needed
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
      setTimeout(() => {
        const intervalId = setInterval(() => {
          index = (index + 1) % panels.length;
          showPanel(index);
        }, interval);
        
        // Store interval ID so we can clear it later if needed
        rotatorIntervals.set(cardIdx, intervalId);
      }, 3000);
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
      }
    });
  }, 500);

  // Periodic competition refresh
  setInterval(() => {
    refreshSpeedChallenge('am', 'speedAmList', 'speedAmStatus');
    refreshSpeedChallenge('pm', 'speedPmList', 'speedPmStatus');
    refreshCategorySpecialists();
    refreshConsistency();
  }, cfg.refreshSeconds * 1000);

  // Initial competition data load
  refreshSpeedChallenge('am', 'speedAmList', 'speedAmStatus');
  refreshSpeedChallenge('pm', 'speedPmList', 'speedPmStatus');
  refreshCategorySpecialists();
  refreshConsistency();

  // Refresh analytics every 5 minutes
  setInterval(() => {
    initializeAnalytics();
  }, 300000);

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
      console.log('Loading QA dashboard with period:', period);
      const response = await fetch(`/api/qa-dashboard?period=${period}`);
      const data = await response.json();
      
      console.log('QA data received:', data);
      
      if (data.error) {
        console.error('QA data error:', data.error);
        showQAError('Failed to load QA data: ' + data.error);
        return;
      }
      
      // Update summary cards
      document.getElementById('qaTotalScans').textContent = data.summary.totalScans.toLocaleString();
      document.getElementById('qaPassRate').textContent = data.summary.passRate + '%';
      document.getElementById('qaConsistency').textContent = data.summary.avgConsistency.toFixed(1);
      document.getElementById('qaTopTech').textContent = data.summary.topTechnician;
      document.getElementById('qaCurrentPeriod').textContent = data.period;
      document.getElementById('qaDateRange').textContent = data.dateRange;
      
      // Render top performers
      const performersGrid = document.getElementById('qaTopPerformersGrid');
      if (!data.topPerformers || data.topPerformers.length === 0) {
        const latestDate = data.dataBounds?.maxDate;
        const earliestDate = data.dataBounds?.minDate;
        const availabilityMsg = latestDate
          ? `Latest available QA data: ${latestDate}${earliestDate ? ` (earliest: ${earliestDate})` : ''}.`
          : 'No QA data available in the database.';
        performersGrid.innerHTML = `
          <div style="grid-column: 1 / -1; padding: 30px; text-align: center; color: #999;">
            <h3>No QA data for this period</h3>
            <p style="margin-top: 8px; font-size: 13px;">${availabilityMsg}</p>
            <p style="margin-top: 6px; font-size: 12px;">Try a date range within the available period.</p>
          </div>
        `;
      } else {
        performersGrid.innerHTML = data.topPerformers.map(tech => `
        <div class="qa-performer-card">
          <div class="qa-performer-name">${escapeHtml(tech.name)}</div>
          <div class="qa-performer-metric">
            <span class="qa-performer-metric-label">Scans:</span>
            <span class="qa-performer-metric-value">${tech.totalScans}</span>
          </div>
          <div class="qa-performer-metric">
            <span class="qa-performer-metric-label">Pass Rate:</span>
            <span class="qa-performer-metric-value">${tech.passRate}%</span>
          </div>
          <div class="qa-performer-metric">
            <span class="qa-performer-metric-label">Consistency:</span>
            <span class="qa-performer-metric-value">${tech.consistency}</span>
          </div>
          <div class="qa-performer-metric">
            <span class="qa-performer-metric-label">Reliability:</span>
            <span class="qa-performer-metric-value">${tech.reliability}</span>
          </div>
        </div>
      `).join('');
      }
      
      // Render all technicians
      const techniciansGrid = document.getElementById('qaTechniciansGrid');
      if (!data.technicians || data.technicians.length === 0) {
        techniciansGrid.innerHTML = '';
      } else {
        techniciansGrid.innerHTML = data.technicians.map(tech => {
        const maxScans = Math.max(...data.technicians.map(t => t.totalScans), 1);
        const dailyData = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']
          .map(day => tech.daily[day]?.scans || 0);
        const maxDaily = Math.max(...dailyData, 1);
        
        return `
          <div class="qa-tech-card">
            <div class="qa-tech-name">${escapeHtml(tech.name)}</div>
            <div class="qa-tech-stat">
              <span class="qa-tech-stat-label">Scans:</span>
              <span class="qa-tech-stat-value">${tech.totalScans}</span>
            </div>
            <div class="qa-tech-stat">
              <span class="qa-tech-stat-label">Pass:</span>
              <span class="qa-tech-stat-value">${tech.passRate}%</span>
            </div>
            <div class="qa-tech-stat">
              <span class="qa-tech-stat-label">Consistency:</span>
              <span class="qa-tech-stat-value">${tech.consistency}</span>
            </div>
            <div class="qa-tech-stat">
              <span class="qa-tech-stat-label">Avg/Day:</span>
              <span class="qa-tech-stat-value">${tech.avgPerDay}</span>
            </div>
            <div class="qa-daily-breakdown">
              ${dailyData.map((scans, idx) => `
                <div class="qa-day-bar ${scans > 0 ? 'active' : ''}">
                  <div class="qa-day-bar-inner" style="height: ${(scans / maxDaily) * 100}%"></div>
                  <div class="qa-day-label">${['M','T','W','T','F'][idx]}</div>
                </div>
              `).join('')}
            </div>
          </div>
        `;
        }).join('');
      }
      
    } catch (error) {
      console.error('Failed to load QA dashboard:', error);
      showQAError('Connection error: ' + error.message);
    }
  }
  
  // Show error message on QA dashboard
  function showQAError(message) {
    const performersGrid = document.getElementById('qaTopPerformersGrid');
    const techniciansGrid = document.getElementById('qaTechniciansGrid');
    
    if (performersGrid) {
      performersGrid.innerHTML = `
        <div style="grid-column: 1 / -1; padding: 40px; text-align: center; color: #ff6b6b;">
          <h3>⚠️ ${message}</h3>
          <p style="color: #999; margin-top: 10px;">Check console for details or try a different period.</p>
        </div>
      `;
    }
    
    if (techniciansGrid) {
      techniciansGrid.innerHTML = '';
    }
  }
  
  // Helper function to escape HTML
  function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }
  
  function switchDashboard(index) {
    const erasureView = document.getElementById('erasureStatsView');
    const qaView = document.getElementById('qaStatsView');
    const titleElem = document.getElementById('dashboardTitle');
    
    if (index < 0 || index >= dashboards.length) {
      return;
    }
    
    currentDashboard = index;
    const dashboard = dashboards[index];
    
    if (dashboard === 'erasure') {
      erasureView.style.display = '';
      qaView.style.setProperty('display', 'none');
      titleElem.textContent = dashboardTitles.erasure;
    } else if (dashboard === 'qa') {
      erasureView.style.display = 'none';
      qaView.style.setProperty('display', 'grid', 'important');
      titleElem.textContent = dashboardTitles.qa;
      // Load QA data when switching to QA dashboard
      const periodValue = document.getElementById('dateSelector')?.value || 'this-week';
      const period = periodValue.replace(/-/g, '_');  // Convert "this-week" to "this_week"
      loadQADashboard(period);
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
  
  // Restore last dashboard view
  const savedDashboard = parseInt(localStorage.getItem('currentDashboard') || '0');
  switchDashboard(savedDashboard);
  
  // Refresh QA data when period changes
  if (document.getElementById('dateSelector')) {
    document.getElementById('dateSelector').addEventListener('change', (e) => {
      if (currentDashboard === 1) {  // QA dashboard index
        const period = e.target.value.replace('-', '_');
        loadQADashboard(period);
      }
    });
  }

  // ==================== CSV EXPORT ====================
  
  async function generateCSV() {
    const dateScope = document.getElementById('dateSelector')?.value || 'this-week';
    const isThisWeek = dateScope === 'this-week';
    const isLastWeek = dateScope === 'last-week';
    const isThisMonth = dateScope === 'this-month';
    const isLastMonth = dateScope === 'last-month';
    const isMonthlyReport = isThisMonth || isLastMonth;
    const isWeeklyReport = isThisWeek || isLastWeek;
    
    // Calculate date range for display and API calls
    let targetDate = new Date();
    let dateRangeStr = '';
    let monthYearStr = '';
    
    if (isLastWeek) {
      // Get last week (Monday to Sunday)
      const today = new Date();
      const dayOfWeek = today.getDay();
      // Go back to last Sunday
      const daysToLastSunday = dayOfWeek === 0 ? 1 : dayOfWeek + 1;
      targetDate.setDate(today.getDate() - daysToLastSunday);
      // Go back to Monday of that week
      targetDate.setDate(targetDate.getDate() - 6);
      const startDate = new Date(targetDate);
      const endDate = new Date(startDate);
      endDate.setDate(endDate.getDate() + 6); // Sunday
      dateRangeStr = `${startDate.toLocaleDateString('en-GB')} - ${endDate.toLocaleDateString('en-GB')}`;
    } else if (isThisWeek) {
      // Get this week (Monday to today)
      const today = new Date();
      const dayOfWeek = today.getDay();
      const daysToMonday = dayOfWeek === 0 ? 6 : dayOfWeek - 1;
      const startDate = new Date(today);
      startDate.setDate(today.getDate() - daysToMonday);
      dateRangeStr = `${startDate.toLocaleDateString('en-GB')} - ${today.toLocaleDateString('en-GB')}`;
    } else if (isLastMonth) {
      // Get last month
      targetDate.setMonth(targetDate.getMonth() - 1);
      const year = targetDate.getFullYear();
      const month = targetDate.getMonth();
      // Set to first day of last month for consistency
      targetDate.setDate(1);
      monthYearStr = targetDate.toLocaleDateString('en-GB', { month: 'long', year: 'numeric' });
      dateRangeStr = monthYearStr;
    } else if (isThisMonth) {
      // Get this month
      const year = targetDate.getFullYear();
      const month = targetDate.getMonth();
      // Set to first day of this month for consistency
      targetDate.setDate(1);
      monthYearStr = targetDate.toLocaleDateString('en-GB', { month: 'long', year: 'numeric' });
      dateRangeStr = monthYearStr;
    } else {
      dateRangeStr = targetDate.toLocaleDateString('en-GB');
    }
    
    const time = new Date().toLocaleTimeString('en-GB');
    
    // Get current displayed values (only valid for "this-week")
    let todayTotal, monthTotal, target;
    if (!isWeeklyReport && !isMonthlyReport) {
      todayTotal = document.getElementById('totalTodayValue')?.textContent || '0';
      monthTotal = document.getElementById('monthTotalValue')?.textContent || '0';
      target = document.getElementById('erasedTarget')?.textContent || '500';
    } else {
      // For other scopes, fetch from API
      todayTotal = '0';
      monthTotal = '0';
      target = '500';
      try {
        if (isMonthlyReport) {
          // For monthly reports, get the month totals
          const monthDate = new Date(targetDate);
          const year = monthDate.getFullYear();
          const month = monthDate.getMonth();
          const firstDay = new Date(year, month, 1).toISOString().split('T')[0];
          const lastDay = new Date(year, month + 1, 0).toISOString().split('T')[0];
          const res = await fetch(`/metrics/summary?startDate=${firstDay}&endDate=${lastDay}`);
          if (res.ok) {
            const data = await res.json();
            monthTotal = data.monthTotal || '0';
          }
        } else {
          const res = await fetch(`/metrics/summary?date=${targetDate.toISOString().split('T')[0]}`);
          if (res.ok) {
            const data = await res.json();
            todayTotal = data.todayTotal || '0';
            monthTotal = data.monthTotal || '0';
          }
        }
      } catch (err) {
        console.error('Failed to fetch summary:', err);
      }
    }
    
    // For monthly reports, fetch engineer breakdown data
    let allEngineersRows = [];
    let engineerKPIs = {};
    try {
      let apiEndpoint = `/metrics/engineers/leaderboard?scope=${dateScope}&limit=50`;
      const res = await fetch(apiEndpoint);
      if (res.ok) {
        const data = await res.json();
        // Fetch KPI data for all engineers
        try {
          let kpiUrl = '/metrics/engineers/kpis/all';
          const kpiRes = await fetch(kpiUrl);
          if (kpiRes.ok) {
            const kpiData = await kpiRes.json();
            engineerKPIs = (kpiData.engineers || []).reduce((acc, kpi) => {
              acc[kpi.initials] = kpi;
              return acc;
            }, {});
          }
        } catch (err) {
          console.error('Failed to fetch engineer KPIs:', err);
        }
        allEngineersRows = (data.items || []).map((eng, idx) => {
          let erasures = eng.erasures || 0;
          let avgPerHour = isMonthlyReport ? (erasures / (targetDate.getDate() * SHIFT_HOURS)).toFixed(1) : (erasures / SHIFT_HOURS).toFixed(1);
          let lastActiveDisplay = isMonthlyReport ? 'N/A' : formatTimeAgo(eng.lastActive);
          const baseRow = [
            idx + 1,
            eng.initials || '',
            erasures,
            lastActiveDisplay,
            avgPerHour
          ];
          // Add KPI data if available
          if (engineerKPIs[eng.initials]) {
            const kpi = engineerKPIs[eng.initials];
            return [
              ...baseRow,
              kpi.avg7Day,
              kpi.avg30Day,
              kpi.trend,
              kpi.personalBest,
              kpi.consistencyScore,
              kpi.daysActiveMonth
            ];
          }
          return baseRow;
        });
      }
    } catch (err) {
      console.error('Failed to fetch engineer data:', err);
    }

    // Get category data - fetch for all report types
    const categoryRows = [];
    try {
      if (!isMonthlyReport && !isWeeklyReport) {
        categories.forEach(cat => {
          const count = document.getElementById(cat.countId)?.textContent || '0';
          categoryRows.push([cat.label, count]);
        });
      } else {
        // For weekly/monthly reports, would need API endpoint - skip for now
        console.log('Category breakdown for weekly/monthly reports not yet implemented');
      }
    } catch (err) {
      console.error('Failed to fetch category data:', err);
    }

    // Get top performers per category - fetch for all report types
    const categoryTopPerformers = [];
    try {
      if (!isMonthlyReport && !isWeeklyReport) {
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
      } else {
        // For monthly reports, fetch top performers by category
        const catOrder = ['laptops_desktops', 'servers', 'macs', 'mobiles'];
        const catNames = {
          laptops_desktops: 'Laptops/Desktops',
          servers: 'Servers',
          macs: 'Macs',
          mobiles: 'Mobiles'
        };
        const monthDate = new Date(targetDate);
        const year = monthDate.getFullYear();
        const month = monthDate.getMonth();
        const firstDay = new Date(year, month, 1).toISOString().split('T')[0];
        const lastDay = new Date(year, month + 1, 0).toISOString().split('T')[0];
        const res = await fetch(`/competitions/category-specialists?startDate=${firstDay}&endDate=${lastDay}`);
        if (res.ok) {
          const data = await res.json();
          if (data.specialists) {
            catOrder.forEach(cat => {
              (data.specialists[cat] || []).slice(0, 1).forEach((row, idx) => {
                categoryTopPerformers.push([catNames[cat], row.initials || '', row.count || 0]);
              });
            });
          }
        }
      }
    } catch (err) {
      console.error('Failed to fetch category top performers:', err);
    }

    // Calculate progress metrics
    let currentDay, daysInMonth, dailyAvg, projectedTotal, daysRemaining, progressPercent, statusIndicator, monthProgressPercent;
    if (isMonthlyReport) {
      daysInMonth = new Date(targetDate.getFullYear(), targetDate.getMonth() + 1, 0).getDate();
      dailyAvg = Math.round(parseInt(monthTotal) / daysInMonth);
      projectedTotal = dailyAvg * daysInMonth;
      daysRemaining = isThisMonth ? daysInMonth - targetDate.getDate() : 0;
      progressPercent = Math.round((parseInt(monthTotal) / (parseInt(target) * daysInMonth)) * 100);
      statusIndicator = progressPercent >= 100 ? 'ON PACE' : progressPercent >= 80 ? 'GOOD PACE' : 'BELOW PACE';
      monthProgressPercent = progressPercent;
    } else {
      currentDay = targetDate.getDate();
      daysInMonth = new Date(targetDate.getFullYear(), targetDate.getMonth() + 1, 0).getDate();
      dailyAvg = Math.round(parseInt(monthTotal) / currentDay);
      projectedTotal = Math.round(dailyAvg * daysInMonth);
      daysRemaining = daysInMonth - currentDay;
      progressPercent = Math.round((parseInt(todayTotal) / parseInt(target)) * 100);
      statusIndicator = progressPercent >= 100 ? 'ON TARGET' : progressPercent >= 80 ? 'APPROACHING' : 'BELOW TARGET';
      monthProgressPercent = Math.round((parseInt(monthTotal) / (parseInt(target) * currentDay)) * 100);
    }
    
    // Build professional report title
    let reportTitle, reportSubtitle;
    if (isThisMonth) {
      reportTitle = 'BH WAREHOUSE ERASURE STATS REPORT - THIS MONTH';
      reportSubtitle = `Monthly Report for: ${dateRangeStr}`;
    } else if (isLastMonth) {
      reportTitle = 'BH WAREHOUSE ERASURE STATS REPORT - LAST MONTH';
      reportSubtitle = `Monthly Report for: ${dateRangeStr}`;
    } else if (isLastWeek) {
      reportTitle = 'BH WAREHOUSE ERASURE STATS REPORT - LAST WEEK';
      reportSubtitle = `Weekly Report for: ${dateRangeStr}`;
    } else if (isThisWeek) {
      reportTitle = 'BH WAREHOUSE ERASURE STATS REPORT - THIS WEEK';
      reportSubtitle = `Current Week Status - ${dateRangeStr}`;
    } else {
      reportTitle = 'BH WAREHOUSE ERASURE STATS REPORT';
      reportSubtitle = `Current Status - ${dateRangeStr}`;
    }
    
    const csv = [
      [reportTitle],
      [reportSubtitle],
      ['Generated:', new Date().toLocaleDateString('en-GB', { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' })],
      ['Time:', time],
      [],
      ['EXECUTIVE SUMMARY'],
      ['Key Metric', 'Value', 'Status/Target', 'Performance'],
    ];
    
    if (isMonthlyReport) {
      csv.push(['Monthly Total', monthTotal, `Expected: ~${parseInt(target) * daysInMonth}`, statusIndicator]);
      csv.push(['Daily Average', dailyAvg, `Per day`, `vs ${target} target`]);
      csv.push(['Days in Month', daysInMonth, `Total days`, isThisMonth ? `${daysRemaining} remaining` : 'Complete']);
      csv.push(['Achievement Rate', `${progressPercent}%`, `of monthly expectation`, progressPercent >= 100 ? 'Exceeded Target' : 'Below Target']);
      csv.push(['Days Active', Object.values(engineerKPIs).reduce((sum, kpi) => sum + (kpi.daysActiveMonth || 0), 0), 'Across all engineers', 'Utilization metric']);
    } else if (isWeeklyReport) {
      csv.push(['Weekly Total', todayTotal, `Target: ~${parseInt(target) * 5}`, statusIndicator]);
      csv.push(['Daily Average', dailyAvg, 'Per day', `${dailyAvg > parseInt(target) ? 'Above' : 'Below'} target`]);
      csv.push(['Week Period', dateRangeStr, 'Mon-Sun', isThisWeek ? 'In Progress' : 'Complete']);
    } else {
      csv.push(['Today\'s Total', todayTotal, `Target: ${target}`, statusIndicator]);
      csv.push(['Month Total', monthTotal, `Avg ${target}/day`, `${monthProgressPercent}% of pace`]);
      csv.push(['Daily Average', dailyAvg, 'Per day', `${dailyAvg > parseInt(target) ? 'Above' : 'Below'} target`]);
      csv.push(['Projected Month', projectedTotal, `of ~${parseInt(target) * daysInMonth} max`, `${Math.round((projectedTotal / (parseInt(target) * daysInMonth)) * 100)}% utilization`]);
      csv.push(['Days Remaining', daysRemaining, `in ${targetDate.toLocaleDateString('en-US', { month: 'long' })}`, '']);
    }
    csv.push([]);

    // Additional analysis sections - fetch for all report types
    if (true) {
      try {
        const [perfTrends, targetAchievement, records, weekly, specialists, consistency] = await Promise.all([
          fetch(`/metrics/performance-trends?target=${target}`).then(r => r.ok ? r.json() : null),
          fetch(`/metrics/target-achievement?target=${target}`).then(r => r.ok ? r.json() : null),
          fetch('/metrics/records').then(r => r.ok ? r.json() : null),
          fetch('/metrics/weekly').then(r => r.ok ? r.json() : null),
          fetch('/competitions/category-specialists').then(r => r.ok ? r.json() : null),
          fetch('/competitions/consistency').then(r => r.ok ? r.json() : null)
        ]);

        // Performance Trends Section
        if (perfTrends) {
          csv.push(['PERFORMANCE TRENDS']);
          csv.push(['Metric', 'Value', 'Indicator', 'Notes']);
          csv.push(['Week-over-Week Change', `${perfTrends.wowChange > 0 ? '+' : ''}${perfTrends.wowChange}%`, perfTrends.trend, `Current: ${perfTrends.currentWeekTotal}, Previous: ${perfTrends.previousWeekTotal}`]);
          csv.push(['Month-over-Month Change', `${perfTrends.momChange > 0 ? '+' : ''}${perfTrends.momChange}%`, perfTrends.momChange > 0 ? 'Growth' : perfTrends.momChange < 0 ? 'Decline' : 'Flat', `Current: ${perfTrends.currentMonthTotal}, Previous: ${perfTrends.previousMonthTotal}`]);
          csv.push(['Rolling 7-Day Average', perfTrends.rolling7DayAvg, `${perfTrends.vsTargetPct}% of target`, `Target: ${target}/day`]);
          csv.push(['Trend Direction', perfTrends.trend, '', 'Based on last 7 days vs previous 7 days']);
          csv.push([]);
        }

        // Target Achievement Section
        if (targetAchievement) {
          csv.push(['TARGET ACHIEVEMENT METRICS']);
          csv.push(['Metric', 'Value', 'Details', 'Status']);
          csv.push(['Days Hitting Target', `${targetAchievement.daysHittingTarget} of ${targetAchievement.totalDaysThisMonth}`, `${targetAchievement.hitRatePct}% success rate`, targetAchievement.hitRatePct >= 80 ? 'Excellent' : targetAchievement.hitRatePct >= 60 ? 'Good' : 'Needs Improvement']);
          csv.push(['Current Streak', `${targetAchievement.currentStreak} days ${targetAchievement.streakType} target`, '', targetAchievement.streakType === 'above' ? '[HOT STREAK]' : '[BELOW TARGET]']);
          csv.push(['Projected Month Total', targetAchievement.projectedMonthTotal, `Based on ${dailyAvg}/day average`, targetAchievement.projectedMonthTotal >= targetAchievement.monthlyTarget ? 'On Track' : 'Below Pace']);
          csv.push(['Gap to Monthly Target', Math.abs(targetAchievement.gapToTarget), targetAchievement.gapToTarget <= 0 ? 'Target Exceeded!' : `${targetAchievement.daysRemaining} days remaining`, '']);
          csv.push(['Daily Rate Needed', targetAchievement.gapToTarget > 0 ? targetAchievement.dailyNeeded : 0, `to hit ${targetAchievement.monthlyTarget} target`, targetAchievement.dailyNeeded <= target ? 'Achievable' : 'Challenging']);
          csv.push([]);
        }

        // Add records & milestones
        if (records?.bestDay || records?.topEngineer || records?.currentStreak !== undefined) {
          csv.push(['HISTORICAL RECORDS & ACHIEVEMENTS']);
          csv.push(['Metric', 'Value', 'Details']);
          if (records.bestDay) {
            csv.push(['Best Day Ever', records.bestDay.count || 0, `Achieved on ${records.bestDay.date || 'N/A'}`]);
          }
          if (records.topEngineer) {
            csv.push(['Top Engineer (All-Time)', records.topEngineer.initials || '—', `${records.topEngineer.totalCount || 0} total erasures`]);
          }
          if (records.currentStreak !== undefined) {
            csv.push(['Current Streak', `${records.currentStreak || 0} days`, 'above daily target']);
          }
          csv.push([]);
        }

        // Add weekly statistics
        if (weekly?.weekTotal || weekly?.daysActive) {
          csv.push(['WEEKLY PERFORMANCE (Past 7 Days)']);
          csv.push(['Metric', 'Value', 'Comparison', 'Notes']);
          csv.push(['Week Total', weekly.weekTotal || 0, `${Math.round((weekly.weekTotal / (parseInt(target) * 7)) * 100)}% of weekly goal`, '']);
          csv.push(['Best Day', weekly.bestDayOfWeek?.count || 0, `(${weekly.bestDayOfWeek?.date || 'N/A'})`, weekly.bestDayOfWeek?.count >= parseInt(target) ? 'On Target' : 'Below Target']);
          csv.push(['Daily Average', weekly.weekAverage || 0, `vs ${target} target`, weekly.weekAverage >= parseInt(target) ? 'Above Target' : 'Below Target']);
          csv.push(['Days Active', weekly.daysActive || 0, `out of 7 days`, '']);
          csv.push([]);
        }

        // Consistency
        if (consistency?.leaderboard?.length) {
          csv.push([]);
          csv.push(['CONSISTENCY KINGS/QUEENS', 'Steadiest pace - lowest variability']);
          csv.push(['Rank', 'Engineer', 'Erasures', 'Avg Pace (min)', 'Consistency Score']);
          csv.push(...consistency.leaderboard.map((row, idx) => [
            idx + 1,
            row.initials || '',
            row.erasures || 0,
            row.avgGapMinutes || 0,
            row.consistencyScore || 0
          ]));
        }
      } catch (err) {
        console.error('Failed to fetch detailed metrics:', err);
      }
    }

    // Engineer leaderboard section
    if (!isMonthlyReport && !isWeeklyReport && allEngineersRows.length > 0) {
      csv.push(['TOP 3 ENGINEERS (Daily Leaders)']);
      csv.push(['Rank', 'Engineer', 'Erasures', 'Last Active', 'Status']);
      allEngineersRows.slice(0, 3).forEach((row, idx) => {
        const erasures = parseInt(row[2]);
        let status = erasures >= parseInt(target) ? 'Exceeding Target' : 'On Pace';
        csv.push([row[0], row[1], row[2], row[3], status]);
      });
      
      // Add race analysis
      if (allEngineersRows.length >= 2) {
        const lead = parseInt(allEngineersRows[0][2]);
        const second = parseInt(allEngineersRows[1][2]);
        const gap = lead - second;
        const gapPercent = Math.round((gap / second) * 100);
        csv.push([]);
        csv.push(['RACE ANALYSIS']);
        csv.push(['Leader', allEngineersRows[0][1]]);
        csv.push(['Lead Margin', `${gap} erasures (${gapPercent}% ahead)`]);
        csv.push(['Second Place', allEngineersRows[1][1]]);
      }
      csv.push([]);
    }

    // All engineers section
    csv.push([isMonthlyReport ? 'ENGINEER PERFORMANCE - MONTHLY SUMMARY' : isWeeklyReport ? 'ALL ENGINEERS - WEEKLY SUMMARY' : 'ALL ENGINEERS - DETAILED LEADERBOARD WITH KPIs']);
    csv.push(['Rank', 'Engineer', isMonthlyReport ? 'Month Total' : isWeeklyReport ? 'Week Total' : 'Today Total', 'Last Active', 'Per Hour', '% Target', '7-Day Avg', '30-Day Avg', 'Trend', 'Personal Best', 'Consistency', 'Days Active']);
    csv.push(...(allEngineersRows.length > 0 ? allEngineersRows.map(row => {
      const erasures = parseInt(row[2]);
      const pct = parseInt(target) > 0 ? Math.round((erasures / parseInt(target)) * 100) : 0;
      if (row.length > 5) {
        return [row[0], row[1], row[2], row[3], row[4], `${pct}%`, row[5], row[6], row[7], row[8], row[9], row[10]];
      } else {
        return null;
      }
    }).filter(Boolean) : [['No data available']]));
    
    // Device Specialization sheet
    let hasDeviceRows = false;
    let deviceRows = [];
    Object.values(engineerKPIs).forEach(kpi => {
      if (kpi.deviceBreakdown && kpi.deviceBreakdown.length > 0) {
        kpi.deviceBreakdown.forEach((device, idx) => {
          const deviceName = device.deviceType === 'laptops_desktops' ? 'Laptops/Desktops' :
                            device.deviceType === 'servers' ? 'Servers' :
                            device.deviceType === 'macs' ? 'Macs' :
                            device.deviceType === 'mobiles' ? 'Mobiles' :
                            device.deviceType;
          const note = idx === 0 ? 'Primary focus' : idx === 1 ? 'Secondary' : '';
          deviceRows.push([kpi.initials, deviceName, device.total, device.avgPerDay, note]);
          hasDeviceRows = true;
        });
      }
    });
    if (hasDeviceRows) {
      csv.push(['ENGINEER DEVICE SPECIALIZATION (Last 30 Days)']);
      csv.push(['Engineer', 'Device Type', 'Total Count', 'Avg Per Day', 'Notes']);
      csv.push(...deviceRows);
      csv.push([]);
    }

    // Category Breakdown sheet
    if (categoryRows.length > 0) {
      csv.push(['BREAKDOWN BY CATEGORY']);
      csv.push(['Category', 'Count']);
      csv.push(...categoryRows);
      csv.push([]);
    }

    // Category Leaders sheet
    if (categoryTopPerformers.length > 0) {
      csv.push(['TOP PERFORMERS BY CATEGORY']);
      csv.push(['Category', 'Engineer', 'Count']);
      csv.push(...categoryTopPerformers);
    }

    // Engineer weekly breakdown (for monthly reports only)
    if (isMonthlyReport) {
      try {
        const monthDate = new Date(targetDate);
        const year = monthDate.getFullYear();
        const month = monthDate.getMonth();
        const firstDay = new Date(year, month, 1).toISOString().split('T')[0];
        const lastDay = new Date(year, month + 1, 0).toISOString().split('T')[0];
        
        const res = await fetch(`/metrics/engineers/weekly-stats?startDate=${firstDay}&endDate=${lastDay}`);
        if (res.ok) {
          const data = await res.json();
          if (data.engineers && data.engineers.length > 0) {
            csv.push([]);
            csv.push(['ENGINEER WEEKLY BREAKDOWN']);
            csv.push(['Engineer', 'Device Type', 'Week 1', 'Week 2', 'Week 3', 'Week 4', 'Week 5', 'Monthly Total']);
            
            data.engineers.forEach(eng => {
              const row = [eng.initials, eng.device_type];
              // Add each week's count (weeks 1-5)
              for (let week = 1; week <= 5; week++) {
                row.push(eng.weekly_breakdown[week] || 0);
              }
              row.push(eng.total);
              csv.push(row);
            });
          }
        }
      } catch (err) {
        console.error('Failed to fetch engineer weekly stats:', err);
      }
      
      // Month-over-month comparison (only for last-month reports)
      if (isLastMonth) {
        try {
          const currentMonth = new Date(targetDate);
          const year = currentMonth.getFullYear();
          const month = currentMonth.getMonth();
          const currentStart = new Date(year, month, 1).toISOString().split('T')[0];
          const currentEnd = new Date(year, month + 1, 0).toISOString().split('T')[0];
          
          // Previous month
          const prevMonth = new Date(year, month - 1, 1);
          const prevStart = prevMonth.toISOString().split('T')[0];
          const prevEnd = new Date(prevMonth.getFullYear(), prevMonth.getMonth() + 1, 0).toISOString().split('T')[0];
          
          const res = await fetch(`/metrics/month-comparison?currentStart=${currentStart}&currentEnd=${currentEnd}&previousStart=${prevStart}&previousEnd=${prevEnd}`);
          if (res.ok) {
            const data = await res.json();
            csv.push([]);
            csv.push(['MONTH-OVER-MONTH COMPARISON']);
            csv.push(['Metric', 'Current Month', 'Previous Month', 'Change', 'Trend']);
            csv.push([
              'Total Erasures',
              data.current_month.total,
              data.previous_month.total,
              `${data.comparison.change > 0 ? '+' : ''}${data.comparison.change} (${data.comparison.change_percent}%)`,
              data.comparison.trend
            ]);
            csv.push([]);
            csv.push(['Top Engineers Comparison']);
            csv.push(['Rank', 'Current Month', 'Erasures', 'Previous Month', 'Erasures']);
            for (let i = 0; i < 5; i++) {
              const current = data.current_month.top_engineers[i];
              const previous = data.previous_month.top_engineers[i];
              csv.push([
                i + 1,
                current ? current.initials : '',
                current ? current.erasures : '',
                previous ? previous.initials : '',
                previous ? previous.erasures : ''
              ]);
            }
          }
        } catch (err) {
          console.error('Failed to fetch month comparison:', err);
        }
      }
    }

    // Add footer with notes and context
    csv.push([]);
    csv.push(['REPORT INFORMATION']);
    csv.push(['Report Type', isMonthlyReport ? 'Monthly Warehouse Erasure Statistics' : 'Daily Warehouse Erasure Statistics']);
    csv.push(['Target', `${target} erasures per day`]);
    csv.push(['Scope', isThisMonth ? 'Current month (to date)' : isLastMonth ? 'Previous month' : isThisWeek ? 'Current week (Monday to today)' : isLastWeek ? 'Previous week (Mon-Sun)' : 'Current day (real-time)']);
    csv.push(['Data Freshness', 'Real-time updates every 30 seconds']);
    csv.push(['Competitions', 'Speed Challenge (AM: 8-12, PM: 13:30-15:45) | Category Specialists | Consistency Kings/Queens']);
    
    csv.push([]);
    csv.push(['GLOSSARY & DEFINITIONS']);
    csv.push(['Term', 'Definition']);
    csv.push(['Status Indicator', 'ON TARGET (100%+) | APPROACHING (80-99%) | BELOW TARGET (<80%)']);
    csv.push(['On Pace', 'Engineer is performing at expected rate to meet daily target']);
    csv.push(['Exceeding Target', 'Engineer has already completed more than daily target']);
    csv.push(['7-Day Avg', 'Average daily erasures over the last 7 days']);
    csv.push(['30-Day Avg', 'Average daily erasures over the last 30 days (reflects device mix)']);
    csv.push(['Trend', 'IMPROVING (>10% increase) | DECLINING (>10% decrease) | STABLE']);
    csv.push(['Personal Best', 'Highest single-day erasure count achieved']);
    csv.push(['Consistency Score', 'Standard deviation of daily output (lower = more predictable)']);
    csv.push(['Days Active', 'Number of days with recorded activity this month']);
    csv.push(['Device Specialization', 'Shows which device types each engineer primarily works on']);
    csv.push(['Avg Gap', 'Average time between consecutive erasures (minutes)']);
    csv.push(['Std Dev', 'Standard Deviation - measure of consistency (lower is more consistent)']);
    csv.push(['Week Total', 'Sum of all erasures across 7-day period']);
    csv.push(['Daily Average', 'Total divided by number of days active']);
    csv.push(['Achievement Rate', 'Percentage of days hitting or exceeding daily target']);

    return csv.map(row => row.map(cell => `"${cell}"`).join(',')).join('\n');
  }

  async function downloadExcel() {
    const dateScope = document.getElementById('dateSelector')?.value || 'this-week';
    const period = dateScope.replace(/-/g, '_');

    // Determine export URL and filename
    let exportUrl, filename;
    if (currentDashboard === 1) {
      // QA dashboard export
      exportUrl = `/export/qa-stats?period=${period}`;
      filename = `qa-stats-${dateScope}.xlsx`;
    } else {
      // Erasure dashboard export (engineer deep dive)
      exportUrl = `/export/engineer-deepdive?period=${period}`;
      filename = `engineer-deepdive-${dateScope}.xlsx`;
    }

    try {
      // Fetch with authentication header
      const response = await fetch(exportUrl, {
        headers: {
          'Authorization': 'Bearer Gr33n5af3!'
        }
      });

      if (!response.ok) {
        throw new Error(`Export failed: ${response.statusText}`);
      }

      // Convert response to blob and download
      const blob = await response.blob();
      const downloadUrl = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = downloadUrl;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(downloadUrl);
    } catch (error) {
      console.error('Export error:', error);
      alert('Failed to download spreadsheet: ' + error.message);
    }
  }

  // Add button listener
  document.getElementById('downloadBtn')?.addEventListener('click', downloadExcel);

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
  async function refreshTopByTypeAllScopes(type, listId) {
    const scopes = [
      { key: 'today', label: "Today" },
      { key: 'month', label: "This Month" },
      { key: 'all', label: "All Time" }
    ];
    const results = {};
    let monthData = null;
    let allTimeData = null;
    for (const scope of scopes) {
      try {
        let url = `/metrics/engineers/top-by-type?type=${encodeURIComponent(type)}`;
        if (scope.key !== 'today') url += `&scope=${scope.key}`;
        console.log('[refreshTopByTypeAllScopes] Fetching engineers:', { type, url });
        const res = await fetch(url);
        let data = await res.json();
        // Fetch the true total for this category/period
        let total = 0;
        try {
          // Always use the full category key for type
          let totalUrl = `/metrics/total-by-type?type=${encodeURIComponent(type)}&scope=${scope.key}`;
          console.log('[refreshTopByTypeAllScopes] Fetching total:', { type, totalUrl });
          const totalRes = await fetch(totalUrl);
          const totalData = await totalRes.json();
          total = typeof totalData.total === 'number' ? totalData.total : 0;
        } catch (err) {
          total = (data.engineers || []).reduce((sum, e) => sum + (e.count || 0), 0);
        }
        if (scope.key === 'month') monthData = data.engineers;
        if (scope.key === 'all') allTimeData = data.engineers;
        results[scope.key] = { engineers: data.engineers, label: scope.label, total };
      } catch (err) {
        results[scope.key] = { engineers: [], label: scope.label, total: 0 };
        console.error('Top-by-type refresh error:', type, scope.key, err);
      }
    }
    if (!results.all) {
      results.all = { engineers: [], label: 'All Time', total: 0 };
    }
    window._categoryFlipData = window._categoryFlipData || {};
    window._categoryFlipData[listId] = results;
    // Render initial (today) with backend total
    renderTopListWithLabel(listId, results.today.engineers, results.today.label, results.today.total);
  }

  // Enhanced: fetch all scopes for each category
  function refreshAllTopListsWithFlip() {
    categories.forEach(c => refreshTopByTypeAllScopes(c.key, c.listId));
  }

  // NEW: Refresh category rotator cards (Today, This Month, All Time panels)
  async function refreshCategoryRotatorCards() {
    const categoryMappings = [
      { key: 'laptops_desktops', todayListId: 'topLD', monthListId: 'topLDMonth', allTimeListId: 'topLDAllTime', todayCountId: 'countLD', monthCountId: 'countLDMonth', allTimeCountId: 'countLDAllTime' },
      { key: 'servers', todayListId: 'topServers', monthListId: 'topServersMonth', allTimeListId: 'topServersAllTime', todayCountId: 'countServers', monthCountId: 'countServersMonth', allTimeCountId: 'countServersAllTime' },
      { key: 'macs', todayListId: 'topMacs', monthListId: 'topMacsMonth', allTimeListId: 'topMacsAllTime', todayCountId: 'countMacs', monthCountId: 'countMacsMonth', allTimeCountId: 'countMacsAllTime' },
      { key: 'mobiles', todayListId: 'topMobiles', monthListId: 'topMobilesMonth', allTimeListId: 'topMobilesAllTime', todayCountId: 'countMobiles', monthCountId: 'countMobilesMonth', allTimeCountId: 'countMobilesAllTime' },
    ];

    for (const cat of categoryMappings) {
      try {
        // Fetch Today data
        const todayRes = await fetch(`/metrics/engineers/top-by-type?type=${encodeURIComponent(cat.key)}`);
        const todayData = await todayRes.json();
        const todayTotalRes = await fetch(`/metrics/total-by-type?type=${encodeURIComponent(cat.key)}&scope=today`);
        const todayTotalData = await todayTotalRes.json();
        const todayTotal = todayTotalData.total || 0;

        // Fetch Month data
        const monthRes = await fetch(`/metrics/engineers/top-by-type?type=${encodeURIComponent(cat.key)}&scope=month`);
        const monthData = await monthRes.json();
        const monthTotalRes = await fetch(`/metrics/total-by-type?type=${encodeURIComponent(cat.key)}&scope=month`);
        const monthTotalData = await monthTotalRes.json();
        const monthTotal = monthTotalData.total || 0;

        // Fetch All Time data
        const allTimeRes = await fetch(`/metrics/engineers/top-by-type?type=${encodeURIComponent(cat.key)}&scope=all`);
        const allTimeData = await allTimeRes.json();
        const allTimeTotalRes = await fetch(`/metrics/total-by-type?type=${encodeURIComponent(cat.key)}&scope=all`);
        const allTimeTotalData = await allTimeTotalRes.json();
        const allTimeTotal = allTimeTotalData.total || 0;

        // Render Today panel
        renderTopList(cat.todayListId, todayData.engineers);
        const todayCountEl = document.getElementById(cat.todayCountId);
        if (todayCountEl) todayCountEl.textContent = todayTotal;

        // Render Month panel
        renderTopList(cat.monthListId, monthData.engineers);
        const monthCountEl = document.getElementById(cat.monthCountId);
        if (monthCountEl) monthCountEl.textContent = monthTotal;

        // Render All Time panel
        renderTopList(cat.allTimeListId, allTimeData.engineers);
        const allTimeCountEl = document.getElementById(cat.allTimeCountId);
        if (allTimeCountEl) allTimeCountEl.textContent = allTimeTotal;

      } catch (err) {
        console.error('Category rotator card refresh error:', cat.key, err);
      }
    }
  }

  function setupCategoryFlipCards() {
    if (!window._categoryFlipData) {
      return;
    }
    
    // Clear any existing intervals
    if (window._categoryFlipIntervals) {
      window._categoryFlipIntervals.forEach(id => clearInterval(id));
    }
    window._categoryFlipIntervals = [];
    
    categories.forEach(c => {
      const listId = c.listId;
      const el = document.getElementById(listId);
      if (!el) {
        return;
      }
      // Add label if not present
      // Move label to header row, left of pip
      const header = el.parentElement.querySelector('.card-header, .category-header, .top-row, .card-title-row') || el.parentElement;
      let label = header.querySelector('.category-period-label');
      if (!label) {
        label = document.createElement('span');
        label.className = 'category-period-label';
        label.style = 'font-size:0.95em;color:var(--muted);margin-right:8px;vertical-align:middle;';
        // Insert before pip if possible
        const pip = header.querySelector('.pip, .pip-count, .pip-value, .pip-number, .pipNum, .pipnum, .pipnumtop, .pipnum-top, .pip-number-top, .pip-number');
        if (pip) {
          header.insertBefore(label, pip);
        } else {
          header.appendChild(label);
        }
      }
      // Flip logic
      let flipIndex = 0;
      const flipData = window._categoryFlipData[listId];
      // Always rotate through all three periods: Today, Month, All Time
      const scopes = ['today', 'month', 'all'];
      
      // Function to perform the flip
      function performFlip() {
        flipIndex = (flipIndex + 1) % scopes.length;
        const currentEl = document.getElementById(listId);
        if (!currentEl) return;
        
        // Set opacity to 0 (initiates transition)
        currentEl.style.opacity = '0';
        
        // Wait for fade out
        setTimeout(() => {
          const data = flipData[scopes[flipIndex]];
          if (!data) {
            flipIndex = 0;
            data = flipData[scopes[0]];
          }
          
          // Force DOM update
          renderTopListWithLabel(listId, data.engineers, data.label, data.total);
          
          // Force reflow to ensure opacity transition is visible
          void document.body.offsetHeight;
          
          // Fade back in
          const elAfterUpdate = document.getElementById(listId);
          if (elAfterUpdate) {
            setTimeout(() => {
              elAfterUpdate.style.opacity = '1';
            }, 50);
          }
        }, 600);
      }
      
      // Start rotation after short delay and store interval ID
      setTimeout(() => {
        const intervalId = setInterval(performFlip, 20000);
        window._categoryFlipIntervals.push(intervalId);
        console.log(`[TV Rotation] Started interval for ${listId}`);
      }, 2000);
    });
    
    // Add visibility change listener to restart intervals if page becomes visible
    if (!window._categoryFlipVisibilityHandler) {
      window._categoryFlipVisibilityHandler = function() {
        if (!document.hidden) {
          console.log('[TV Rotation] Page visible, ensuring intervals are running');
          // Don't restart immediately, just log
        }
      };
      document.addEventListener('visibilitychange', window._categoryFlipVisibilityHandler);
    }
  }



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

})();



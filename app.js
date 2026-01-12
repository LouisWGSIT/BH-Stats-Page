(async function () {
  const cfg = await fetch('config.json').then(r => r.json());

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

  // Race state
  let raceData = { engineer1: null, engineer2: null, engineer3: null, firstFinisher: null };
  let winnerAnnounced = false;

  // Greenie state
  let greenieState = {
    currentStats: { todayTotal: 0, monthTotal: 0, byType: {} },
    lastQuotes: [],
    lastShowTime: 0,
  };

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
    const categories = ['praise', 'targetProgress', 'categoryWins', 'motivation'];
    let selectedCategory;
    let quote;
    let attempts = 0;

    // Try to avoid repeating the same category/type
    do {
      selectedCategory = categories[Math.floor(Math.random() * categories.length)];
      const quoteList = greenieQuotes[selectedCategory];
      
      if (selectedCategory === 'praise') {
        // Get top engineer initials
        const initials = topEngineer.split('\n')[0] || 'Team';
        quote = quoteList[Math.floor(Math.random() * quoteList.length)](initials);
      } else if (selectedCategory === 'targetProgress') {
        quote = quoteList[Math.floor(Math.random() * quoteList.length)](greenieState.currentStats.diff);
      } else if (selectedCategory === 'categoryWins') {
        const categories_list = ['Laptops/Desktops', 'Servers', 'Macs', 'Mobiles'];
        const category = categories_list[Math.floor(Math.random() * categories_list.length)];
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

    // Check if 20 minutes have passed since last show
    const timeSinceLastShow = Date.now() - greenieState.lastShowTime;
    const twentyMinutes = 20 * 60 * 1000;

    if (timeSinceLastShow >= twentyMinutes) {
      // Only show at specific times to avoid random triggers: :00, :20, :40
      if (minutes === 0 || minutes === 20 || minutes === 40) {
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
        li.innerHTML = `<span>${name}</span><span class="value">${eng.count}</span>`;
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
      const res = await fetch('/metrics/engineers/leaderboard?scope=today&limit=3');
      if (!res.ok) throw new Error('HTTP ' + res.status);
      const data = await res.json();
      const body = document.getElementById('leaderboardBody');
      body.innerHTML = '';
      (data.items || []).forEach((row) => {
        const tr = document.createElement('tr');
        const color = getEngineerColor(row.initials || '');
        const lastActive = formatTimeAgo(row.lastActive);
        tr.innerHTML = `
          <td>
            <span class="engineer-badge" style="background-color: ${color}"></span>
            ${row.initials || ''}
          </td>
          <td class="value-strong">${row.erasures || 0}</td>
          <td class="time-ago">${lastActive}</td>
        `;
        body.appendChild(tr);
      });

      // Update race positions
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
        const percentage = Math.min((erasures / maxErasures) * 100, 100);
        
        // Move car up the lane based on percentage (0% = bottom, 100% = top)
        const carPosition = 100 - percentage;
        carEl.style.bottom = `${carPosition}%`;
        
        // Update trail height from bottom to current car position
        trailEl.style.height = `${percentage}%`;
        
        // Color trail to match engineer color
        const engineerColor = getEngineerColor(engineer.initials || '');
        trailEl.style.background = `linear-gradient(to top, ${engineerColor}, ${engineerColor}40)`;
        
        // Update label with engineer initials
        labelEl.textContent = `${engineer.initials || '?'}`;
        labelEl.style.color = engineerColor;

        // Check if car has finished (reached top/100%)
        if (percentage >= 95 && !engineer.finished) {
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

  // Kick off refresh loops
  refreshSummary();
  refreshAllTopLists();
  refreshByTypeCounts();
  refreshLeaderboard();

  setInterval(() => {
    refreshSummary();
    refreshAllTopLists();
    refreshByTypeCounts();
    refreshLeaderboard();
    checkAndTriggerWinner();
    checkGreenieTime();
  }, cfg.refreshSeconds * 1000);

  function updateDonut(chart, value, target) {
    const remaining = Math.max(target - value, 0);
    chart.data.datasets[0].data = [value, remaining];
    chart.update();
  }

  function donut(canvasId) {
    const ctx = document.getElementById(canvasId);
    const primary = getComputedStyle(document.documentElement)
      .getPropertyValue('--ring-primary').trim();
    const secondary = getComputedStyle(document.documentElement)
      .getPropertyValue('--ring-secondary').trim();

    return new Chart(ctx, {
      type: 'doughnut',
      data: {
        labels: ['Value', 'Remaining'],
        datasets: [{
          data: [0, 0],
          backgroundColor: [secondary, primary],
          borderWidth: 0,
          hoverOffset: 4
        }]
      },
      options: {
        responsive: true,
        cutout: '65%',
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
  }

  function keepScreenAlive() {
    // Prevent Fire Stick timeout by periodically simulating user activity
    // This keeps the screen from timing out after 10 minutes of inactivity
    if (document.hidden) return; // Don't wake if app is hidden
    
    // Subtle visual pulse (barely noticeable)
    document.body.style.opacity = '0.999';
    setTimeout(() => { document.body.style.opacity = '1'; }, 100);
  }
  
  // Keep screen alive every 5 minutes
  setInterval(keepScreenAlive, 5 * 60 * 1000);

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
})();

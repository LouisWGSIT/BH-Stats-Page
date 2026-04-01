(async function () {
  const authUiApi = window.DashboardAuthUI && typeof window.DashboardAuthUI.init === 'function'
    ? window.DashboardAuthUI.init()
    : null;
  if (authUiApi && typeof authUiApi.ensureAuthenticated === 'function') {
    await authUiApi.ensureAuthenticated();
  }

  // Now proceed with dashboard initialization
  const cfg = await fetch('/config.json').then(r => r.json());

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

  async function refreshSpeedChallenge(window, listId, statusId) {
    try {
      const res = await fetch(`/competitions/speed-challenge?window=${window}`);
      if (!res.ok) throw new Error('HTTP ' + res.status);
      const data = await res.json();
      const list = document.getElementById(listId);
      const statusEl = document.getElementById(statusId);
      
      // Get tracker for this window
      const tracker = speedChallengeData[window];
      if (!tracker) return;

      if (statusEl && data.status) {
        const st = data.status;
        const liveBadge = st.isActive ? 'LIVE · ' : '';
        const remaining = st.isActive ? `${st.timeRemainingMinutes} mins left` : `${st.startTime} - ${st.endTime}`;
        statusEl.textContent = `${liveBadge}${st.name} (${remaining})`;
        
        // Check if challenge just finished (was active, now isn't)
        if (tracker.wasActive && !st.isActive && !tracker.isFinished) {
          tracker.isFinished = true;
          // Announce the winner after a short delay to let data settle
          setTimeout(() => {
            const firstPlace = (data.leaderboard || [])[0];
            if (firstPlace && firstPlace.initials) {
              const announcementType = window === 'am' 
                ? announcementTypes.SPEED_CHALLENGE_AM 
                : announcementTypes.SPEED_CHALLENGE_PM;
              showAnnouncement(announcementType, {
                initials: firstPlace.initials,
                erasures: firstPlace.erasures || 0,
              });
            }
          }, 500);
        }
        
        // Track if active for next check
        tracker.wasActive = st.isActive;
        
        // Reset finished flag when challenge becomes active again (next day)
        if (st.isActive && tracker.isFinished) {
          tracker.isFinished = false;
        }
      }

      if (!list) return;
      list.innerHTML = '';
      const fragment = document.createDocumentFragment();
      (data.leaderboard || []).forEach((row, idx) => {
        const li = document.createElement('li');
        li.innerHTML = `
          <span class="speed-rank">${idx + 1}.</span>
          <span class="speed-name">${row.initials || '—'}</span>
          <span class="speed-count">${row.erasures || 0}</span>
        `;
        fragment.appendChild(li);
      });
      list.appendChild(fragment);
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
        const fragment = document.createDocumentFragment();
        rows.forEach((row, idx) => {
          const li = document.createElement('li');
          const trophyClass = idx === 0 ? 'gold' : idx === 1 ? 'silver' : 'bronze';
          li.innerHTML = `
            <span class="speed-rank">${idx + 1}.</span>
            <span class="speed-name">${row.initials || '—'}</span>
            <span class="speed-count">${row.count || 0}</span>
            <span class="trophy ${trophyClass}"></span>
          `;
          fragment.appendChild(li);
        });
        list.appendChild(fragment);
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
      const fragment = document.createDocumentFragment();
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
        fragment.appendChild(li);
      });
      list.appendChild(fragment);
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
      const fragment = document.createDocumentFragment();
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
        fragment.appendChild(tr);
      });
      body.appendChild(fragment);

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
  
  if (window.DashboardSwitcher && typeof window.DashboardSwitcher.init === 'function') {
    window.DashboardSwitcher.init({
      loadQADashboard,
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



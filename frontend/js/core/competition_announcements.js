// Competition and announcement orchestration extracted from app.js.
(function () {
  function init(deps) {
    const announcementTypes = {
      DAILY_SUMMARY: 'daily-summary',
      HOURLY_CROSS_SECTION: 'hourly-cross-section',
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
        duration: 600000,
        emoji: '🏆🎉',
      }),
      'hourly-cross-section': (summary) => ({
        title: summary.title || '📣 Hourly Team Update',
        subtitle: summary.subtitle || '',
        duration: 45000,
        emoji: '📣📊',
      }),
      'daily-race-winner': (winner) => ({
        title: `🏆 ${winner.initials} WINS THE DAILY RACE! 🏆`,
        subtitle: `Finished with ${winner.erasures} erasures today`,
        duration: 600000,
        emoji: '🏁🎉',
      }),
      'speed-challenge-am': (winner) => ({
        title: `⚡ ${winner.initials} CRUSHES THE AM SPEED CHALLENGE! ⚡`,
        subtitle: `${winner.erasures} erasures in record time`,
        duration: 60000,
        emoji: '🏃💨',
      }),
      'speed-challenge-pm': (winner) => ({
        title: `🌙 ${winner.initials} DOMINATES THE PM SPEED CHALLENGE! 🌙`,
        subtitle: `${winner.erasures} erasures in the afternoon blitz`,
        duration: 60000,
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
    const ERASURE_ONLY_ANNOUNCEMENTS = new Set([
      announcementTypes.DAILY_RACE_WINNER,
      announcementTypes.SPEED_CHALLENGE_AM,
      announcementTypes.SPEED_CHALLENGE_PM,
      announcementTypes.CATEGORY_SPECIALIST,
      announcementTypes.CONSISTENCY_KING,
      announcementTypes.TOP_PERFORMER,
    ]);
    const HOURLY_ANNOUNCEMENT_HOURS = new Set([9, 10, 11, 13, 14, 15]);
    let lastHourlyAnnouncementKey = null;

    function triggerConfetti() {
      if (typeof confetti === 'undefined') {
        console.warn('Confetti library not loaded');
        return;
      }

      const confettiColors = ['#ff1ea3', '#8cf04a', '#00d4ff', '#ffcc00'];
      const defaults = {
        origin: { y: 0.3 },
        zIndex: 10000,
        disableForReducedMotion: true,
      };

      confetti({
        ...defaults,
        particleCount: 50,
        spread: 90,
        startVelocity: 40,
        colors: confettiColors,
        ticks: 120,
      });
    }

    async function safeFetchJson(url) {
      try {
        const res = await fetch(url);
        if (!res.ok) return null;
        return await res.json();
      } catch (err) {
        return null;
      }
    }

    function getInitials(value) {
      const cleaned = String(value || '').trim();
      if (!cleaned || cleaned === '—' || cleaned.toLowerCase().includes('unable')) return '--';
      const parts = cleaned.split(/\s+/).filter(Boolean);
      if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
      return `${parts[0][0] || ''}${parts[parts.length - 1][0] || ''}`.toUpperCase();
    }

    function toInt(value) {
      const n = Number(value);
      return Number.isFinite(n) ? n : 0;
    }

    function buildTopRows(rows, valueKey, maxRows = 3) {
      return (Array.isArray(rows) ? rows : [])
        .map((row) => ({
          initials: getInitials(row && (row.initials || row.name || row.engineer)),
          value: toInt(row && row[valueKey]),
        }))
        .filter((row) => row.initials !== '--' && row.value > 0)
        .sort((a, b) => b.value - a.value)
        .slice(0, maxRows);
    }

    function formatTopRows(rows, unit) {
      if (!rows.length) return ['No activity yet'];
      return rows.map((row, idx) => `${idx + 1}. ${row.initials} - ${row.value.toLocaleString()} ${unit}`);
    }

    async function buildCrossSectionStandings() {
      const [erasureData, qaTodayData] = await Promise.all([
        safeFetchJson('/metrics/engineers/leaderboard?scope=today&limit=6'),
        safeFetchJson('/api/qa-dashboard?period=today'),
      ]);

      const erasureTop = buildTopRows((erasureData && erasureData.items) || [], 'erasures', 3);
      const technicians = Array.isArray(qaTodayData && qaTodayData.technicians) ? qaTodayData.technicians : [];

      const qaTop = technicians
        .map((tech) => ({
          initials: getInitials(tech && tech.name),
          value: toInt(tech && tech.deQaScans) + toInt(tech && tech.nonDeQaScans),
        }))
        .filter((row) => row.initials !== '--' && row.value > 0)
        .sort((a, b) => b.value - a.value)
        .slice(0, 3);

      const sortingTop = technicians
        .map((tech) => ({
          initials: getInitials(tech && tech.name),
          value: toInt(tech && tech.qaScans),
        }))
        .filter((row) => row.initials !== '--' && row.value > 0)
        .sort((a, b) => b.value - a.value)
        .slice(0, 3);

      const erasureTotal = erasureTop.reduce((sum, row) => sum + row.value, 0);
      const qaTotal = qaTop.reduce((sum, row) => sum + row.value, 0);
      const sortingTotal = sortingTop.reduce((sum, row) => sum + row.value, 0);

      return {
        erasureTop,
        qaTop,
        sortingTop,
        erasureTotal,
        qaTotal,
        sortingTotal,
      };
    }

    async function buildDailySummary() {
      const standings = await buildCrossSectionStandings();
      const items = [
        {
          icon: '🟢',
          label: 'Erasure Top 3',
          winner: (standings.erasureTop[0] && standings.erasureTop[0].initials) || '—',
          lines: formatTopRows(standings.erasureTop, 'erasures'),
          value: `${standings.erasureTotal.toLocaleString()} total`,
        },
        {
          icon: '🔵',
          label: 'QA Top 3',
          winner: (standings.qaTop[0] && standings.qaTop[0].initials) || '—',
          lines: formatTopRows(standings.qaTop, "QA'd"),
          value: `${standings.qaTotal.toLocaleString()} total`,
        },
        {
          icon: '🟠',
          label: 'Sorting Top 3',
          winner: (standings.sortingTop[0] && standings.sortingTop[0].initials) || '—',
          lines: formatTopRows(standings.sortingTop, 'sorted'),
          value: `${standings.sortingTotal.toLocaleString()} total`,
        },
      ];

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

    async function buildHourlyCrossSectionSummary() {
      const standings = await buildCrossSectionStandings();
      const now = new Date();
      const hourLabel = now.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
      return {
        title: '📣 Hourly Top 3 Snapshot',
        subtitle: `${hourLabel} • Cross-dashboard standings`,
        items: [
          {
            icon: '🟢',
            label: 'Erasure Top 3',
            winner: (standings.erasureTop[0] && standings.erasureTop[0].initials) || '—',
            lines: formatTopRows(standings.erasureTop, 'erasures'),
            value: `${standings.erasureTotal.toLocaleString()} total`,
          },
          {
            icon: '🔵',
            label: 'QA Top 3',
            winner: (standings.qaTop[0] && standings.qaTop[0].initials) || '—',
            lines: formatTopRows(standings.qaTop, "QA'd"),
            value: `${standings.qaTotal.toLocaleString()} total`,
          },
          {
            icon: '🟠',
            label: 'Sorting Top 3',
            winner: (standings.sortingTop[0] && standings.sortingTop[0].initials) || '—',
            lines: formatTopRows(standings.sortingTop, 'sorted'),
            value: `${standings.sortingTotal.toLocaleString()} total`,
          },
        ],
      };
    }

    function showAnnouncement(type, data) {
      if (ERASURE_ONLY_ANNOUNCEMENTS.has(type) && typeof deps.isErasureDashboardActive === 'function' && !deps.isErasureDashboardActive()) {
        return;
      }
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

      const isSummaryType = (type === announcementTypes.DAILY_SUMMARY || type === announcementTypes.HOURLY_CROSS_SECTION);
      if (isSummaryType && summaryContainer) {
        if (winnerText) winnerText.style.display = 'none';
        if (winnerSubtext) winnerSubtext.style.display = 'none';
        summaryContainer.classList.remove('hidden');
        if (summaryTitle) summaryTitle.textContent = data.title || message.title;
        if (summarySubtitle) summarySubtitle.textContent = data.subtitle || message.subtitle || '';
        if (summaryGrid) {
          summaryGrid.innerHTML = (data.items || []).map((item) => `
            <div class="summary-item">
              <div class="summary-item-left">
                <span class="summary-icon">${item.icon || '🏆'}</span>
                  <div>
                    <div class="summary-label">${deps.escapeHtml(item.label || '')}</div>
                    <div class="summary-winner">${deps.escapeHtml(item.winner || '—')}</div>
                    ${Array.isArray(item.lines) && item.lines.length ? `
                      <div class="summary-lines">
                        ${item.lines.map((line) => `<div class="summary-line">${deps.escapeHtml(line)}</div>`).join('')}
                      </div>
                    ` : ''}
                  </div>
                </div>
                <div class="summary-value">${deps.escapeHtml(item.value || '')}</div>
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

      if (modal) {
        modal.classList.remove('hidden');
      }

      triggerConfetti();

      setTimeout(() => {
        if (modal) {
          modal.classList.add('hidden');
        }
      }, message.duration);
    }

    async function announceWinner() {
      const raceData = deps.getRaceData();
      if (raceData.winnerAnnounced) return;
      raceData.winnerAnnounced = true;
      const summary = await buildDailySummary();
      showAnnouncement(announcementTypes.DAILY_SUMMARY, summary);
    }

    async function checkAndTriggerHourlyCrossSectionAnnouncement() {
      const now = new Date();
      const hours = now.getHours();
      const minutes = now.getMinutes();
      if (!HOURLY_ANNOUNCEMENT_HOURS.has(hours)) return;
      if (minutes > 2) return;
      const dayKey = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
      const announceKey = `${dayKey}-${hours}`;
      if (lastHourlyAnnouncementKey === announceKey) return;

      lastHourlyAnnouncementKey = announceKey;
      const summary = await buildHourlyCrossSectionSummary();
      showAnnouncement(announcementTypes.HOURLY_CROSS_SECTION, summary);
    }

    function checkAndTriggerWinner() {
      const raceData = deps.getRaceData();
      const now = new Date();
      const hours = now.getHours();
      const minutes = now.getMinutes();

      checkAndTriggerHourlyCrossSectionAnnouncement();

      if (hours === 15 && minutes === 58 && !raceData.winnerAnnounced) {
        announceWinner();
      }

      if (hours === 0 && minutes === 0) {
        raceData.winnerAnnounced = false;
        raceData.firstFinisher = null;
      }
    }

    async function refreshSpeedChallenge(windowName, listId, statusId) {
      try {
        const res = await fetch(`/competitions/speed-challenge?window=${windowName}`);
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const data = await res.json();
        const list = document.getElementById(listId);
        const statusEl = document.getElementById(statusId);

        const speedChallengeData = deps.getSpeedChallengeData();
        const tracker = speedChallengeData[windowName];
        if (!tracker) return;

        if (statusEl && data.status) {
          const st = data.status;
          const liveBadge = st.isActive ? 'LIVE · ' : '';
          const remaining = st.isActive ? `${st.timeRemainingMinutes} mins left` : `${st.startTime} - ${st.endTime}`;
          statusEl.textContent = `${liveBadge}${st.name} (${remaining})`;

          if (tracker.wasActive && !st.isActive && !tracker.isFinished) {
            tracker.isFinished = true;
            setTimeout(() => {
              const firstPlace = (data.leaderboard || [])[0];
              if (firstPlace && firstPlace.initials) {
                const announcementType = windowName === 'am'
                  ? announcementTypes.SPEED_CHALLENGE_AM
                  : announcementTypes.SPEED_CHALLENGE_PM;
                showAnnouncement(announcementType, {
                  initials: firstPlace.initials,
                  erasures: firstPlace.erasures || 0,
                });
              }
            }, 500);
          }

          tracker.wasActive = st.isActive;
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
          mobiles: 'specMobiles',
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

    return {
      refreshSpeedChallenge,
      refreshCategorySpecialists,
      refreshConsistency,
      checkAndTriggerWinner,
      announceWinner,
    };
  }

  window.CompetitionAnnouncements = {
    init,
  };
})();

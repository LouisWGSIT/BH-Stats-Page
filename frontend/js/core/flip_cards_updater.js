// Flip card updater cluster extracted from app.js.
(function () {
  function init(deps) {
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
        .then((r) => r.json())
        .then((data) => {
          if (overallEl && typeof data.overallErasures === 'number') {
            overallEl.textContent = data.overallErasures;
          }
          if (data.bestDay && data.bestDay.count) {
            if (bestDayEl) bestDayEl.textContent = data.bestDay.count;
            if (bestDateEl && data.bestDay.date) {
              bestDateEl.textContent = new Date(data.bestDay.date).toLocaleDateString();
            }
          }
          if (data.topEngineer && data.topEngineer.initials) {
            if (topEngEl) topEngEl.textContent = data.topEngineer.initials;
            if (topCountEl) topCountEl.textContent = `${data.topEngineer.totalCount || 0} erasures`;
          }
          if (typeof data.currentStreak === 'number' && data.currentStreak > 0) {
            if (streakEl) streakEl.textContent = data.currentStreak;
          }
          if (data.mostHour && typeof data.mostHour.count === 'number') {
            if (mostHourEl) mostHourEl.textContent = data.mostHour.count;
            if (mostHourDateEl && data.mostHour.date) {
              mostHourDateEl.textContent = new Date(data.mostHour.date).toLocaleDateString();
            }
          }
          if (data.mostWeek && typeof data.mostWeek.count === 'number') {
            if (mostWeekEl) mostWeekEl.textContent = data.mostWeek.count;
            if (mostWeekDateEl && data.mostWeek.date) {
              mostWeekDateEl.textContent = new Date(data.mostWeek.date).toLocaleDateString();
            }
          }
        })
        .catch((err) => {
          console.error('Records fetch error:', err);
        });
    }

    function updateWeeklyRecords() {
      const weekTotalEl = document.getElementById('weekTotal');
      const weekBestDayEl = document.getElementById('weekBestDay');
      const weekBestDayDateEl = document.getElementById('weekBestDayDate');
      const weekAverageEl = document.getElementById('weekAverage');

      fetch('/metrics/weekly')
        .then((r) => r.json())
        .then((data) => {
          if (weekTotalEl) weekTotalEl.textContent = data.weekTotal || 0;
          if (weekBestDayEl) weekBestDayEl.textContent = data.bestDayOfWeek?.count || 0;
          if (weekBestDayDateEl && data.bestDayOfWeek?.date) {
            weekBestDayDateEl.textContent = new Date(data.bestDayOfWeek.date).toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' });
          }
          if (weekAverageEl) weekAverageEl.textContent = data.weekAverage || 0;
        })
        .catch((err) => {
          console.error('Weekly stats fetch error:', err);
        });

      fetch('/analytics/weekly-daily-totals')
        .then((r) => r.json())
        .then((data) => {
          const days = data.days || [];
          const ids = ['monVal', 'tueVal', 'wedVal', 'thuVal', 'friVal'];
          for (let i = 0; i < 5; i++) {
            const el = document.getElementById(ids[i]);
            if (el) {
              el.textContent = days[i] ? days[i].count : '—';
            }
          }
        })
        .catch((err) => {
          console.error('Weekly Mon-Fri breakdown fetch error:', err);
        });
    }

    function updateTodayStats() {
      const leaderboard = Array.from(document.querySelectorAll('#leaderboardBody tr')).map((tr) => {
        const cells = tr.querySelectorAll('td');
        return {
          initials: cells[0]?.textContent || '',
          count: parseInt(cells[1]?.textContent) || 0,
        };
      });

      const activeCount = leaderboard.filter((e) => e.count > 0).length;
      const todayTotal = parseInt(document.getElementById('totalTodayValue')?.textContent) || 0;
      const avgPerEng = activeCount > 0 ? Math.round(todayTotal / activeCount) : 0;

      const activeEl = document.getElementById('activeEngineers');
      const avgEl = document.getElementById('avgPerEngineer');
      const topHourEl = document.getElementById('topHour');
      const topHourCountEl = document.getElementById('topHourCount');

      if (activeEl) activeEl.textContent = activeCount;
      if (avgEl) avgEl.textContent = avgPerEng;

      fetch('/analytics/peak-hours')
        .then((r) => r.json())
        .then((data) => {
          const hours = Array.isArray(data) ? data : (data?.hours || []);
          if (hours.length > 0) {
            const peakHour = hours.reduce((max, curr) => (curr.count > max.count ? curr : max), hours[0]);
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
        .catch((err) => {
          console.error('Peak hours fetch error:', err);
          if (topHourEl) topHourEl.textContent = 'N/A';
          if (topHourCountEl) topHourCountEl.textContent = 'Error';
        });
    }

    function updateMonthlyProgress() {
      const monthTotal = parseInt(document.getElementById('monthTotalValue')?.textContent) || 0;
      const today = new Date().getDate();
      const daysInMonth = new Date(new Date().getFullYear(), new Date().getMonth() + 1, 0).getDate();
      const targetMonthly = parseInt(deps.cfg.targets.month);
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

      const monthSparkSVG = document.getElementById('monthSparklineSVG');
      if (monthSparkSVG) {
        fetch('/analytics/daily-totals')
          .then((r) => r.json())
          .then((data) => {
            const days = data.days || Array.from({ length: daysInMonth }, (_, i) => ({ day: i + 1, count: 0 }));
            const values = days.map((d) => d.count);
            deps.renderSVGSparkline(monthSparkSVG, values);
          })
          .catch((e) => {
            console.error('[SVG Sparkline] Error fetching monthly data:', e);
          });
      }

      const statList = document.getElementById('monthStatList');
      if (statList) {
        fetch('/metrics/engineers/leaderboard?scope=month&limit=4')
          .then((r) => r.json())
          .then((data) => {
            const engineers = (data.items || []).slice(0, 4);
            if (statList.children.length !== engineers.length) {
              statList.innerHTML = '';
              engineers.forEach((row) => {
                const li = document.createElement('li');
                const color = deps.getEngineerColor(row.initials || '');
                const avatar = deps.getAvatarDataUri(row.initials || '');
                li.innerHTML = `
                  <span class="engineer-chip engineer-chip-vertical">
                    <span class="engineer-avatar" style="background-image: url(${avatar}); border-color: ${color}"></span>
                    <span class="engineer-name">${row.initials}</span>
                    <span class="engineer-count engineer-count-below">${row.erasures || 0}</span>
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
                avatarEl.style.backgroundImage = `url(${deps.getAvatarDataUri(row.initials || '')})`;
                avatarEl.style.borderColor = deps.getEngineerColor(row.initials || '');
                nameEl.textContent = row.initials;
                countEl.textContent = row.erasures || 0;
              });
            }
          });
      }

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
          const firstName = first[0].querySelector('.engineer-name')?.textContent.trim() || '?';
          const firstCount = parseInt(first[1].textContent.trim()) || 0;
          const secondName = second[0].querySelector('.engineer-name')?.textContent.trim() || '?';
          const secondCount = parseInt(second[1].textContent.trim()) || 0;
          const gap = firstCount - secondCount;

          if (deps.leaderboardState.leader !== firstName) {
            deps.leaderboardState.leader = firstName;
            const leaderQuotes = [
              `${firstName} takes the lead! All eyes on them! 👀`,
              `Fresh leader: ${firstName} is dominating today! 🔥`,
              `${firstName} just claimed the top spot! Impressive! 💪`,
              `🚨 NEW LEADER ALERT! ${firstName} is unstoppable right now! 🚨`,
              `Plot twist! ${firstName} just surged to first place! 📈`,
              `${firstName} said "Not today!" and took the lead! 💯`,
              `The momentum shifts! ${firstName} is in control now! 👑`,
            ];
            deps.triggerGreenie(leaderQuotes[Math.floor(Math.random() * leaderQuotes.length)]);
          } else if (deps.leaderboardState.gap !== null && gap < deps.leaderboardState.gap && gap <= 5) {
            const closingQuotes = [
              `${secondName} closing in on ${firstName}! This race is ON! 🏁`,
              `Gap tightening! ${secondName} is making moves! 🚀`,
              `Only ${gap} erasures between them! Tension rising! ⚡`,
              `🔥 DRAMA! The gap is shrinking! ${secondName} is RIGHT THERE! 🔥`,
              `${secondName} is not giving up! The pressure is ON for ${firstName}!`,
              `This is getting SPICY! ${gap} erasures - anything can happen! 🌶️`,
              `${secondName} is hunting! ${firstName}, watch your back! 👀`,
            ];
            deps.triggerGreenie(closingQuotes[Math.floor(Math.random() * closingQuotes.length)]);
          } else if (deps.leaderboardState.gap !== null && gap > deps.leaderboardState.gap + 3) {
            const breakawayQuotes = [
              `${firstName} is PULLING AWAY! Dominant performance! 🏃‍♂️💨`,
              `${firstName} is running away with this! The lead is growing! 📊`,
              `${firstName} putting on a MASTERCLASS right now! Incredible pace! 🎯`,
            ];
            deps.triggerGreenie(breakawayQuotes[Math.floor(Math.random() * breakawayQuotes.length)]);
          } else if (deps.leaderboardState.gap !== null && rows.length > (deps.leaderboardState.lastRaceSize || 0)) {
            const newCompetitorQuotes = [
              `We've got a new challenger in the top 5! The race is WIDE OPEN! 🆕`,
              `Fresh blood entering the race! This just got more interesting! 🎪`,
              `Another contender steps up! May the best engineer win! ⚡`,
            ];
            deps.triggerGreenie(newCompetitorQuotes[Math.floor(Math.random() * newCompetitorQuotes.length)]);
            deps.leaderboardState.lastRaceSize = rows.length;
          } else if (deps.leaderboardState.gap !== null && firstCount > (deps.leaderboardState.lastLeaderCount || 0)) {
            const momentumQuotes = [
              `${firstName} keeps the pedal down! Steady progress! 💪`,
              `The momentum continues! ${firstName} is in the zone! 🎯`,
              `Consistency wins races! ${firstName} adding more to the lead! ✨`,
            ];
            deps.triggerGreenie(momentumQuotes[Math.floor(Math.random() * momentumQuotes.length)]);
          }
          deps.leaderboardState.gap = gap;
          deps.leaderboardState.lastLeaderCount = firstCount;

          const leaderGapEl = document.getElementById('leaderGap');
          if (leaderGapEl) {
            leaderGapEl.textContent = `${firstName} leads by ${gap} erasures`;
            deps.animateNumberUpdate('leaderGap');
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
      deps.categories.forEach((cat) => {
        const listEl = document.getElementById(cat.listId);
        if (listEl) {
          const firstItem = listEl.querySelector('li');
          if (firstItem) {
            const text = firstItem.textContent.trim();
            const parts = text.match(/(.+?)\s+(\d+)$/);
            if (parts) {
              const champId = cat.key === 'laptops_desktops'
                ? 'champLD'
                : cat.key === 'servers'
                ? 'champServers'
                : cat.key === 'macs'
                ? 'champMacs'
                : 'champMobiles';
              document.getElementById(champId).textContent = `${parts[1]} (${parts[2]})`;
            }
          }
        }
      });
    }

    function updateTargetTracker() {
      const todayTotal = parseInt(document.getElementById('totalTodayValue')?.textContent) || 0;
      const target = parseInt(deps.cfg.targets.erased) || 500;
      const percentage = target > 0 ? Math.min((todayTotal / target) * 100, 100) : 0;

      const SHIFT_START = 8;
      const SHIFT_END = 16;
      const SHIFT_HOURS = SHIFT_END - SHIFT_START;
      const now = new Date();
      let hour = now.getHours();
      if (hour < SHIFT_START) hour = SHIFT_START;
      if (hour > SHIFT_END) hour = SHIFT_END;
      const hoursElapsed = Math.max(1, hour - SHIFT_START + 1);
      const currentPace = todayTotal / hoursElapsed;
      const requiredPace = target / SHIFT_HOURS;

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

      const projectedEnd = Math.round(currentPace * SHIFT_HOURS);
      const projEl = document.getElementById('trackerProjection');
      if (projEl) projEl.textContent = `Projected: ${projectedEnd} by end of day`;

      const trackerSparkSVG = document.getElementById('trackerSparklineSVG');
      if (trackerSparkSVG) {
        fetch('/analytics/hourly-totals')
          .then((r) => r.json())
          .then((data) => {
            const hours = (data.hours || []).filter((h) => h.hour >= SHIFT_START && h.hour < SHIFT_END);
            const values = hours.map((h) => h.count);
            deps.renderSVGSparkline(trackerSparkSVG, values);
          })
          .catch((e) => {
            console.error('[SVG Sparkline] Error fetching today tracker data:', e);
          });
      }

      const statList = document.getElementById('trackerStatList');
      if (statList) {
        statList.innerHTML = '';
        const li1 = document.createElement('li');
        li1.textContent = `So far: ${todayTotal}`;
        const li2 = document.createElement('li');
        li2.textContent = 'Best hour: --';
        fetch('/analytics/peak-hours').then((r) => r.json()).then((data) => {
          const hours = Array.isArray(data) ? data : (data?.hours || []);
          if (hours.length > 0) {
            const peak = hours.reduce((max, curr) => (curr.count > max.count ? curr : max), hours[0]);
            li2.textContent = `Best hour: ${peak.hour}:00 (${peak.count})`;
          }
        });
        statList.appendChild(li1);
        statList.appendChild(li2);
      }

      const fillEl = document.getElementById('trackerFill');
      if (fillEl) fillEl.style.width = `${percentage}%`;
      const currentEl = document.getElementById('trackerCurrent');
      if (currentEl) currentEl.textContent = todayTotal;
      const targetEl = document.getElementById('trackerTarget');
      if (targetEl) targetEl.textContent = target;
    }

    return {
      updateRecordsMilestones,
      updateWeeklyRecords,
      updateTodayStats,
      updateMonthlyProgress,
      updateRaceUpdates,
      updateCategoryChampions,
      updateTargetTracker,
    };
  }

  window.FlipCardsUpdater = {
    init,
  };
})();

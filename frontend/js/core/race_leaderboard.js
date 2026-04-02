// Race leaderboard and lane animation extracted from app.js.
(function () {
  function init(deps) {
    function updateRace(leaderboardData) {
      const raceData = deps.getRaceData();
      const topEngineers = leaderboardData.slice(0, 5);
      const maxErasures = topEngineers.length > 0 ? topEngineers[0].erasures || 1 : 1;

      for (let i = 1; i <= 5; i++) {
        const carEl = document.getElementById(`racePos${i}`);
        const trailEl = document.getElementById(`trail${i}`);
        const labelEl = document.getElementById(`driver${i}`);

        if (!carEl || !trailEl || !labelEl) continue;

        const engineer = topEngineers[i - 1];

        if (engineer) {
          const erasures = engineer.erasures || 0;
          let percentage = Math.min((erasures / maxErasures) * 100, 100);
          percentage = Math.min(percentage, 80);

          if (carEl.style.bottom !== `${percentage}%`) {
            carEl.style.bottom = `${percentage}%`;
          }
          if (trailEl.style.height !== `${percentage}%`) {
            trailEl.style.height = `${percentage}%`;
          }

          const engineerColor = deps.getEngineerColor(engineer.initials || '');
          if (trailEl.style.background !== engineerColor) {
            trailEl.style.background = engineerColor;
          }

          if (labelEl.textContent !== engineer.initials) {
            labelEl.textContent = `${engineer.initials || '?'}`;
          }
          if (labelEl.style.color !== engineerColor) {
            labelEl.style.color = engineerColor;
          }

          if (erasures >= maxErasures && !engineer.finished) {
            const now = new Date();
            const hours = now.getHours();
            const minutes = now.getMinutes();

            if (hours === 15 && minutes === 58) {
              engineer.finished = true;
              if (typeof deps.triggerRaceConfetti === 'function') {
                deps.triggerRaceConfetti();
              }
              if (typeof deps.triggerGreenie === 'function') {
                deps.triggerGreenie(`🏁 ${engineer.initials} CROSSES THE FINISH LINE! What a performance! 🎉`);
              }
              if (!raceData.firstFinisher) {
                raceData.firstFinisher = engineer;
                if (typeof deps.announceWinner === 'function') {
                  deps.announceWinner();
                }
              }
            }
          }
        } else {
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

    async function refreshLeaderboard() {
      try {
        const res = await fetch('/metrics/engineers/leaderboard?scope=today&limit=5');
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const data = await res.json();
        const body = document.getElementById('leaderboardBody');
        if (!body) return;

        body.innerHTML = '';
        const fragment = document.createDocumentFragment();
        (data.items || []).slice(0, 5).forEach((row, idx) => {
          const tr = document.createElement('tr');
          const color = deps.getEngineerColor(row.initials || '');
          const avatar = deps.getAvatarDataUri(row.initials || '');
          const lastActive = deps.formatTimeAgo(row.lastActive);
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
        updateRace(data.items || []);
      } catch (err) {
        console.error('Leaderboard refresh error:', err);
      }
    }

    return {
      refreshLeaderboard,
      updateRace,
    };
  }

  window.RaceLeaderboard = {
    init,
  };
})();

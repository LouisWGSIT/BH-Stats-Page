// Aggregated dashboard refresh orchestration extracted from app.js.
(function () {
  function init(deps) {
    async function refresh() {
      try {
        const res = await fetch('/metrics/qa-summary');
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const data = await res.json();

        const summary = data.summary || {};
        const todayTotal = (summary.todayTotal != null) ? summary.todayTotal : (data.today && data.today.erased) || 0;
        const monthTotal = (summary.monthTotal != null) ? summary.monthTotal : (summary.monthTotal) || 0;

        const todayEl = document.getElementById('totalTodayValue');
        const monthEl = document.getElementById('monthTotalValue');
        if (todayEl) {
          todayEl.textContent = todayTotal;
          deps.animateNumberUpdate('totalTodayValue');
        }
        if (monthEl) {
          monthEl.textContent = monthTotal;
          deps.animateNumberUpdate('monthTotalValue');
        }
        deps.updateDonut(deps.totalTodayChart, todayTotal, deps.cfg.targets.erased);
        deps.updateDonut(deps.monthChart, monthTotal, deps.cfg.targets.month || 10000);

        const byType = data.byType || {};
        const counts = {
          laptops_desktops: byType.laptops_desktops || 0,
          servers: byType.servers || 0,
          macs: byType.macs || 0,
          mobiles: byType.mobiles || 0,
        };
        deps.categories.forEach((c) => {
          const el = document.getElementById(c.countId);
          if (el) el.textContent = counts[c.key] || 0;
        });
        deps.renderBars(counts);

        const lb = (data.engineersLeaderboard && data.engineersLeaderboard.items) || [];
        const body = document.getElementById('leaderboardBody');
        if (body) {
          body.innerHTML = '';
          const fragment = document.createDocumentFragment();
          (lb || []).slice(0, 5).forEach((row, idx) => {
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
          deps.updateRace(lb || []);
        }

        if (data.qaLast7 && Array.isArray(data.qaLast7)) {
          const spark = document.getElementById('qaSparkline');
          if (spark) {
            const series = data.qaLast7.map((r) => r.qaTotal || r.deQa + (r.nonDeQa || 0) || 0);
            deps.renderSVGSparkline(spark, series);
          }
        }

        try {
          const lastUpdated = Date.now();
          const lastEl = document.getElementById('last-updated');
          if (lastEl) lastEl.textContent = 'Last updated: ' + new Date(lastUpdated).toLocaleTimeString();
          const stale = document.getElementById('stale-indicator');
          if (stale) stale.classList.add('hidden');
        } catch (e) {
          // ignore
        }

        deps.keepScreenAlive();
      } catch (err) {
        console.error('Aggregated refresh error:', err);
        try { deps.refreshSummary(); } catch (e) {}
        try { deps.refreshAllTopLists(); } catch (e) {}
        try { deps.refreshByTypeCounts(); } catch (e) {}
        try { deps.refreshLeaderboard(); } catch (e) {}
      }
    }

    return { refresh };
  }

  window.AggregatedRefresh = {
    init,
  };
})();

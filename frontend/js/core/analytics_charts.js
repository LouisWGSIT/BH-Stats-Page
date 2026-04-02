// Analytics chart orchestration extracted from app.js.
(function () {
  function init(deps) {
    const analyticsCharts = {};

    async function fetchAnalytics() {
      try {
        const [categoryTrends, engineerStats, peakHours, dayPatterns] = await Promise.all([
          fetch('/analytics/weekly-category-trends').then((r) => r.json()),
          fetch('/analytics/weekly-engineer-stats').then((r) => r.json()),
          fetch('/analytics/peak-hours').then((r) => r.json()),
          fetch('/analytics/day-of-week-patterns').then((r) => r.json()),
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
          labels: data.hours.map((h) => `${h.hour}:00`),
          datasets: [{
            label: 'Erasures',
            data: data.hours.map((h) => h.count),
            backgroundColor: deps.cfg.theme.ringPrimary,
            borderRadius: 4,
            borderSkipped: false,
          }],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: { display: false },
            title: {
              display: true,
              text: 'Hourly Activity',
              color: deps.cfg.theme.text,
              font: { size: 14 },
            },
          },
          scales: {
            y: {
              beginAtZero: true,
              grid: { color: 'rgba(255,255,255,0.05)' },
              ticks: { color: deps.cfg.theme.muted, font: { size: 10 } },
            },
            x: {
              grid: { display: false },
              ticks: { color: deps.cfg.theme.muted, font: { size: 9 }, maxRotation: 0 },
            },
          },
        },
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
          labels: data.patterns.map((p) => p.day),
          datasets: [{
            label: 'Avg Erasures',
            data: data.patterns.map((p) => p.avgCount),
            backgroundColor: deps.cfg.theme.ringSecondary,
            borderRadius: 4,
            borderSkipped: false,
          }],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: { display: false },
            title: {
              display: true,
              text: 'Average by Day (Last 4 Weeks)',
              color: deps.cfg.theme.text,
              font: { size: 14 },
            },
          },
          scales: {
            y: {
              beginAtZero: true,
              grid: { color: 'rgba(255,255,255,0.05)' },
              ticks: { color: deps.cfg.theme.muted },
            },
            x: {
              grid: { display: false },
              ticks: { color: deps.cfg.theme.muted },
            },
          },
        },
      });
    }

    function createWeeklyCategoryTrendsChart(data) {
      const canvas = document.getElementById('chartWeeklyCategoryTrends');
      if (!canvas) return;

      if (analyticsCharts.categoryTrends) {
        analyticsCharts.categoryTrends.destroy();
      }

      const trends = data.trends;
      const today = new Date();
      const todayStr = today.toISOString().slice(0, 10);

      const liveValues = {
        laptops_desktops: parseInt(document.getElementById('countLD')?.textContent) || 0,
        servers: parseInt(document.getElementById('countServers')?.textContent) || 0,
        macs: parseInt(document.getElementById('countMacs')?.textContent) || 0,
        mobiles: parseInt(document.getElementById('countMobiles')?.textContent) || 0,
      };

      let allDates = [...new Set(
        Object.values(trends).flatMap((arr) => arr.map((d) => d.date))
      )];
      if (!allDates.includes(todayStr)) allDates.push(todayStr);
      allDates = allDates.sort();

      const datasets = Object.keys(trends).map((category) => {
        const colorMap = {
          laptops_desktops: '#4caf50',
          servers: '#ffeb3b',
          macs: '#2196f3',
          mobiles: '#ff1ea3',
        };
        const dataArr = allDates.map((date) => {
          if (date === todayStr) {
            return liveValues[category] || 0;
          }
          const entry = trends[category].find((d) => d.date === date);
          return entry ? entry.count : 0;
        });
        return {
          label: category.replace('_', ' / ').toUpperCase(),
          data: dataArr,
          borderColor: colorMap[category] || deps.cfg.theme.ringPrimary,
          backgroundColor: colorMap[category] || deps.cfg.theme.ringPrimary,
          tension: 0.3,
          borderWidth: 2,
          fill: false,
        };
      });

      const ctx = canvas.getContext('2d');
      analyticsCharts.categoryTrends = new Chart(ctx, {
        type: 'line',
        data: {
          labels: allDates.map((d) => new Date(d).toLocaleDateString('en-GB', { month: 'short', day: 'numeric' })),
          datasets,
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: {
              display: true,
              position: 'top',
              labels: { color: deps.cfg.theme.text, font: { size: 11 } },
            },
          },
          scales: {
            y: {
              beginAtZero: true,
              grid: { color: 'rgba(255,255,255,0.05)' },
              ticks: { color: deps.cfg.theme.muted },
            },
            x: {
              grid: { display: false },
              ticks: { color: deps.cfg.theme.muted, font: { size: 10 } },
            },
          },
        },
      });
    }

    function updateWeeklyLeaderboard(data) {
      const tbody = document.getElementById('weeklyLeaderboardBody');
      if (!tbody) return;

      tbody.innerHTML = data.stats.slice(0, 10).map((eng) => {
        const avatar = deps.getAvatarDataUri(eng.initials || '');
        const displayInitials = deps.truncateInitials(eng.initials || '');
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

    return {
      fetchAnalytics,
      createPeakHoursChart,
      createDayOfWeekChart,
      createWeeklyCategoryTrendsChart,
      updateWeeklyLeaderboard,
      initializeAnalytics,
    };
  }

  window.AnalyticsCharts = {
    init,
  };
})();

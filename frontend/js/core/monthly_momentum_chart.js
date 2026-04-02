// Monthly momentum chart extracted from app.js.
(function () {
  function init(deps) {
    async function createMonthlyMomentumChart() {
      const canvas = document.getElementById('chartMonthlyMomentum');
      if (!canvas) return;

      if (deps.analyticsCharts.monthlyMomentum) {
        deps.analyticsCharts.monthlyMomentum.destroy();
      }

      let weeklyData = [0, 0, 0, 0];
      try {
        const response = await fetch('/metrics/monthly-momentum');
        const data = await response.json();
        if (data && data.weeklyTotals) {
          weeklyData = data.weeklyTotals;
        }
      } catch (error) {
        console.warn('Failed to fetch monthly momentum:', error);
      }

      const ctx = canvas.getContext('2d');
      deps.analyticsCharts.monthlyMomentum = new Chart(ctx, {
        type: 'bar',
        data: {
          labels: ['Week 1', 'Week 2', 'Week 3', 'Week 4'],
          datasets: [{
            label: 'Weekly Total',
            data: weeklyData,
            backgroundColor: deps.cfg.theme.ringSecondary,
            borderRadius: 6,
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
              text: 'Week-by-Week Progress',
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

    return {
      createMonthlyMomentumChart,
    };
  }

  window.MonthlyMomentumChart = {
    init,
  };
})();

// QA trend panel rendering extracted from qa_dashboard.js.
(function () {
  function init(deps) {
    function updateQATrendPanel({ totalId, sparklineId, metricsId, trend, insights, mode }) {
      const totalEl = document.getElementById(totalId);
      const metricsEl = document.getElementById(metricsId);
      const sparklineEl = document.getElementById(sparklineId);

      if (!trend || !trend.series || !Array.isArray(trend.series)) {
        if (metricsEl) {
          metricsEl.innerHTML = '<div style="grid-column: 1 / -1; text-align: center; color: #888;">No trend data</div>';
        }
        if (sparklineEl) {
          deps.renderSVGSparkline(sparklineEl, []);
        }
        return;
      }

      const values = trend.series.map((row) => row.qaTotal !== undefined ? row.qaTotal : (row.deQa || 0) + (row.nonDeQa || 0));
      const total = (insights && typeof insights.total === 'number')
        ? insights.total
        : values.reduce((sum, v) => sum + v, 0);

      if (totalEl) {
        totalEl.textContent = total.toLocaleString();
      }

      if (sparklineEl) {
        deps.renderSVGSparkline(sparklineEl, values);
      }

      if (!metricsEl) return;

      const metrics = [];
      if (mode === 'today') {
        const activeHours = trend.series.filter((row) => (row.total || 0) > 0).length || 1;
        const hourlyAvg = Math.round(total / activeHours);
        metrics.push({ label: 'Hourly Avg', value: hourlyAvg.toLocaleString() });
        metrics.push({ label: 'Active Hours', value: activeHours.toString() });
        if (insights) {
          metrics.push({ label: 'Avg/Engineer', value: (insights.avgPerEngineer || 0).toLocaleString() });
          metrics.push({ label: 'Active Engineers', value: (insights.activeEngineers || 0).toString() });
        }
      } else {
        if (insights) {
          metrics.push({ label: 'Avg/Day', value: (insights.avgPerDay || 0).toLocaleString() });
          metrics.push({ label: 'Avg/Engineer', value: (insights.avgPerEngineer || 0).toLocaleString() });
          metrics.push({ label: '7D Avg', value: (insights.rolling7DayAvg || 0).toLocaleString() });
          metrics.push({ label: '30D Avg', value: (insights.rolling30DayAvg || 0).toLocaleString() });
        }
      }

      metricsEl.innerHTML = metrics.map((item) => `
        <div class="qa-trend-metric">
          <div class="qa-trend-metric-label">${deps.escapeHtml(item.label)}</div>
          <div class="qa-trend-metric-value">${deps.escapeHtml(item.value)}</div>
        </div>
      `).join('');
    }

    return {
      updateQATrendPanel,
    };
  }

  window.QATrendPanel = {
    init,
  };
})();

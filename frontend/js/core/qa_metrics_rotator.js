// QA metrics card rotator extracted from qa_dashboard.js.
(function () {
  function init(deps) {
    let metricsFlipIntervalId = null;

    function stop() {
      if (metricsFlipIntervalId) {
        clearInterval(metricsFlipIntervalId);
        metricsFlipIntervalId = null;
      }
    }

    function populateMetricsCard(todayData, weeklyData) {
      const metricsContent = document.getElementById('metricsContent');
      const metricsValue = document.getElementById('metricsValue');
      const metricsLabel = document.getElementById('metricsLabel');

      if (!metricsContent) return;

      const todayTotal = (todayData.summary.deQaScans || 0) + (todayData.summary.nonDeQaScans || 0);
      const weeklyTotal = (weeklyData.summary.deQaScans || 0) + (weeklyData.summary.nonDeQaScans || 0);
      const avgDaily = weeklyTotal > 0 ? Math.round(weeklyTotal / 5) : 0;
      const engineerCount = todayData.technicians ? todayData.technicians.filter((t) => (t.deQaScans || 0) + (t.nonDeQaScans || 0) > 0).length : 0;
      const avgPerEngineer = engineerCount > 0 ? Math.round(todayTotal / engineerCount) : 0;
      const avgConsistency = todayData.summary.avgConsistency || 0;

      const dailyRecords = todayData.summary.dailyRecord || weeklyData.summary.dailyRecord || {
        data_bearing_records: [],
        non_data_bearing_records: [],
      };

      const metricsCard = document.querySelector('.qa-metrics-card');
      let currentView = 0;

      function updateMetricsView() {
        if (metricsCard) {
          metricsCard.classList.add('flipping');
          setTimeout(() => metricsCard.classList.remove('flipping'), 600);
        }

        if (currentView === 0) {
          metricsValue.textContent = todayTotal.toLocaleString();
          metricsLabel.textContent = 'QA Summary';

          metricsContent.innerHTML = `
            <div class="qa-metric-item">
              <span class="qa-metric-label">Weekly Avg</span>
              <span class="qa-metric-value">${avgDaily.toLocaleString()}/day</span>
            </div>
            <div class="qa-metric-item">
              <span class="qa-metric-label">Active Engineers</span>
              <span class="qa-metric-value">${engineerCount}</span>
            </div>
            <div class="qa-metric-item">
              <span class="qa-metric-label">Avg per Engineer</span>
              <span class="qa-metric-value">${avgPerEngineer.toLocaleString()}</span>
            </div>
            <div class="qa-metric-item">
              <span class="qa-metric-label">Consistency</span>
              <span class="qa-metric-value">${Math.round(avgConsistency)}%</span>
            </div>
            <div class="qa-metric-item">
              <span class="qa-metric-label">Week Total</span>
              <span class="qa-metric-value">${weeklyTotal.toLocaleString()}</span>
            </div>
          `;
        } else if (currentView === 1) {
          metricsValue.innerHTML = '<img class="qa-metrics-icon" src="assets/trophy-gold.svg" alt="Record">';
          metricsLabel.textContent = "Data Bearing - Most QA'd in 1 Day!";

          const dbRecords = dailyRecords.data_bearing_records || [];
          if (dbRecords.length === 0) {
            metricsContent.innerHTML = '<div style="padding: 12px; text-align: center; color: #888;">No records</div>';
          } else {
            const medals = ['🥇', '🥈', '🥉', '4.', '5.', '6.'];
            metricsContent.innerHTML = dbRecords.map((record, index) => `
              <div class="qa-metric-item">
                <span class="qa-metric-label">${medals[index] || (index + 1 + '.')} ${deps.escapeHtml(record.name)}</span>
                <span class="qa-metric-value">${record.count.toLocaleString()}</span>
              </div>
            `).join('');
          }
        } else if (currentView === 2) {
          metricsValue.innerHTML = '<img class="qa-metrics-icon" src="assets/trophy-silver.svg" alt="Record">';
          metricsLabel.textContent = "Non-Data Bearing - Most QA'd in 1 Day!";

          const ndbRecords = dailyRecords.non_data_bearing_records || [];
          if (ndbRecords.length === 0) {
            metricsContent.innerHTML = '<div style="padding: 12px; text-align: center; color: #888;">No records</div>';
          } else {
            const medals = ['🥇', '🥈', '🥉', '4.', '5.', '6.'];
            metricsContent.innerHTML = ndbRecords.map((record, index) => `
              <div class="qa-metric-item">
                <span class="qa-metric-label">${medals[index] || (index + 1 + '.')} ${deps.escapeHtml(record.name)}</span>
                <span class="qa-metric-value">${record.count.toLocaleString()}</span>
              </div>
            `).join('');
          }
        }

        currentView = (currentView + 1) % 3;
      }

      updateMetricsView();

      stop();
      metricsFlipIntervalId = setInterval(updateMetricsView, 30000);

      if (metricsCard) {
        metricsCard.style.cursor = 'pointer';
        metricsCard.onclick = updateMetricsView;
      }
    }

    return {
      populateMetricsCard,
      stop,
    };
  }

  window.QAMetricsRotator = {
    init,
  };
})();

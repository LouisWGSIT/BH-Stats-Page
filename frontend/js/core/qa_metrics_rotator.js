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

      const summaryRows = [
        { label: 'Weekly Avg', value: `${avgDaily.toLocaleString()}/day` },
        { label: 'Active Engineers', value: `${engineerCount}` },
        { label: 'Avg per Engineer', value: `${avgPerEngineer.toLocaleString()}` },
        { label: 'Consistency', value: `${Math.round(avgConsistency)}%` },
        { label: 'Week Total', value: `${weeklyTotal.toLocaleString()}` },
      ];

      const summaryPages = [];
      for (let i = 0; i < summaryRows.length; i += 3) {
        summaryPages.push(summaryRows.slice(i, i + 3));
      }
      if (!summaryPages.length) {
        summaryPages.push([]);
      }

      function updateMetricsView() {
        if (metricsCard) {
          metricsCard.classList.add('flipping');
          setTimeout(() => metricsCard.classList.remove('flipping'), 600);
        }

        const summaryPageCount = summaryPages.length;
        const dbViewIndex = summaryPageCount;
        const nonDbViewIndex = summaryPageCount + 1;

        if (currentView < summaryPageCount) {
          metricsValue.textContent = todayTotal.toLocaleString();
          metricsLabel.textContent = summaryPageCount > 1
            ? `QA Summary ${currentView + 1}/${summaryPageCount}`
            : 'QA Summary';

          const page = summaryPages[currentView] || [];
          metricsContent.innerHTML = page.map((row) => `
            <div class="qa-metric-item">
              <span class="qa-metric-label">${row.label}</span>
              <span class="qa-metric-value">${row.value}</span>
            </div>
          `).join('');
        } else if (currentView === dbViewIndex) {
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
        } else if (currentView === nonDbViewIndex) {
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

        currentView = (currentView + 1) % (summaryPageCount + 2);
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

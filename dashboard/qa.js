// QA-specific loader/stub for future splitting.
// Currently a lightweight wrapper that triggers QA-specific initialization
// if `loadQADashboard` is available on the page (provided by common.js).
// QA-specific functions moved out of app.js. Expose APIs on `window` so
// the existing loader and `app.js` can call them without changing call sites.
(function(){
  // Interval IDs exposed on window for external control/inspection
  window.qaTopFlipIntervalId = null;
  window.qaRotatorIntervalId = null;
  window.metricsFlipIntervalId = null;

  window.formatQaName = function(rawName) {
    if (!rawName) return '';
    const name = rawName.toString().trim();
    if (!name) return '';
    if (name.toLowerCase() === '(unassigned)') return '(unassigned)';
    if (name.toLowerCase() === 'unknown') return 'Unknown';

    const withoutDomain = name.replace(/@.*$/, '').replace(/[._-]+/g, ' ').trim();
    const parts = withoutDomain.split(/\s+/).filter(Boolean);
    if (parts.length === 0) return name;
    if (parts.length === 1) {
      return parts[0].charAt(0).toUpperCase() + parts[0].slice(1);
    }
    const first = parts[0];
    const lastInitial = parts[parts.length - 1][0];
    return `${first.charAt(0).toUpperCase() + first.slice(1)} ${lastInitial.toUpperCase()}`;
  };

  window.getQaInitials = function(displayName) {
    if (!displayName) return '';
    const cleaned = displayName.replace(/[^a-zA-Z\s]/g, '').trim();
    if (!cleaned) return '';
    const parts = cleaned.split(/\s+/).filter(Boolean);
    if (parts.length >= 2) {
      return `${parts[0][0]}${parts[parts.length - 1][0]}`.toUpperCase();
    }
    return cleaned.slice(0, 2).toUpperCase();
  };

  window.loadQADashboard = async function(period = 'this_week') {
    try {
      const [todayResponse, weeklyResponse, allTimeResponse] = await Promise.all([
        fetch(`/api/qa-dashboard?period=today`),
        fetch(`/api/qa-dashboard?period=this_week`),
        fetch(`/api/qa-dashboard?period=all_time`)
      ]);

      if (!todayResponse.ok || !weeklyResponse.ok || !allTimeResponse.ok) {
        window.showQAError && window.showQAError(`Failed to load QA data`);
        return;
      }

      const todayData = await todayResponse.json();
      const weeklyData = await weeklyResponse.json();
      const allTimeData = await allTimeResponse.json();

      if (todayData.error || weeklyData.error || allTimeData.error) {
        console.error('QA data error');
        window.showQAError && window.showQAError('Failed to load QA data');
        return;
      }

      window.populateQACard && window.populateQACard('qaTodayTotal', 'qaTodayEngineers', todayData, 'qa', 6);
      window.populateQACard && window.populateQACard('qaWeekTotal', 'qaWeeklyEngineers', weeklyData, 'qa', 6);
      window.populateQACard && window.populateQACard('qaAllTimeTotal', 'qaAllTimeEngineers', allTimeData, 'qa', 8);

      window.startQARotator && window.startQARotator(todayData, weeklyData, allTimeData);
      window.populateMetricsCard && window.populateMetricsCard(todayData, weeklyData);

      const [todayTrend, weekTrend, allTimeTrend, todayInsights, weekInsights, allTimeInsights] = await Promise.all([
        fetch('/api/qa-trends?period=today').then(r => r.ok ? r.json() : null).catch(() => null),
        fetch('/api/qa-trends?period=this_week').then(r => r.ok ? r.json() : null).catch(() => null),
        fetch('/api/qa-trends?period=all_time').then(r => r.ok ? r.json() : null).catch(() => null),
        fetch('/api/insights/qa?period=today').then(r => r.ok ? r.json() : null).catch(() => null),
        fetch('/api/insights/qa?period=this_week').then(r => r.ok ? r.json() : null).catch(() => null),
        fetch('/api/insights/qa?period=all_time').then(r => r.ok ? r.json() : null).catch(() => null)
      ]);

      window.updateQATrendPanel && window.updateQATrendPanel({ totalId: 'qaTodayTrendTotal', sparklineId: 'qaTodaySparkline', metricsId: 'qaTodayMetrics', trend: todayTrend, insights: todayInsights, mode: 'today' });
      window.updateQATrendPanel && window.updateQATrendPanel({ totalId: 'qaWeekTrendTotal', sparklineId: 'qaWeekSparkline', metricsId: 'qaWeekMetrics', trend: weekTrend, insights: weekInsights, mode: 'week' });
      window.updateQATrendPanel && window.updateQATrendPanel({ totalId: 'qaAllTimeTrendTotal', sparklineId: 'qaAllTimeSparkline', metricsId: 'qaAllTimeMetrics', trend: allTimeTrend, insights: allTimeInsights, mode: 'all_time' });

      window.startQATopFlipRotation && window.startQATopFlipRotation();
      window.populateQAAppCard && window.populateQAAppCard('qaAppTodayTotal', 'qaAppTodayEngineers', todayData, 6);
      window.populateQAAppCard && window.populateQAAppCard('qaAppWeekTotal', 'qaAppWeeklyEngineers', weeklyData, 8);
      window.populateQAAppCard && window.populateQAAppCard('qaAppAllTimeTotal', 'qaAppAllTimeEngineers', allTimeData, 10);

    } catch (error) {
      console.error('Failed to load QA dashboard:', error);
      window.showQAError && window.showQAError('Connection error: ' + (error && error.message));
    }
  };

  window.startQATopFlipRotation = function() {
    const cards = document.querySelectorAll('.qa-top-flip-card');
    if (!cards.length) return;
    let flipped = false;
    cards.forEach(card => card.classList.remove('flipped'));
    if (window.qaTopFlipIntervalId) { clearInterval(window.qaTopFlipIntervalId); }
    window.qaTopFlipIntervalId = setInterval(() => {
      flipped = !flipped;
      cards.forEach(card => card.classList.toggle('flipped', flipped));
    }, 35000);
  };

  window.updateQATrendPanel = function({ totalId, sparklineId, metricsId, trend, insights, mode }) {
    const totalEl = document.getElementById(totalId);
    const metricsEl = document.getElementById(metricsId);
    const sparklineEl = document.getElementById(sparklineId);

    if (!trend || !trend.series || !Array.isArray(trend.series)) {
      if (metricsEl) metricsEl.innerHTML = '<div style="grid-column: 1 / -1; text-align: center; color: #888;'>No trend data</div>';
      if (sparklineEl) window.renderSVGSparkline && window.renderSVGSparkline(sparklineEl, []);
      return;
    }

    const values = trend.series.map(row => row.qaTotal !== undefined ? row.qaTotal : (row.deQa || 0) + (row.nonDeQa || 0));
    const total = (insights && typeof insights.total === 'number') ? insights.total : values.reduce((sum, v) => sum + v, 0);
    if (totalEl) totalEl.textContent = total.toLocaleString();
    if (sparklineEl) window.renderSVGSparkline && window.renderSVGSparkline(sparklineEl, values);
    if (!metricsEl) return;

    const metrics = [];
    if (mode === 'today') {
      const activeHours = trend.series.filter(row => (row.total || 0) > 0).length || 1;
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

    metricsEl.innerHTML = metrics.map(item => `\n      <div class="qa-trend-metric">\n        <div class="qa-trend-metric-label">${window.escapeHtml ? window.escapeHtml(item.label) : item.label}</div>\n        <div class="qa-trend-metric-value">${window.escapeHtml ? window.escapeHtml(item.value) : item.value}</div>\n      </div>\n    `).join('');
  };

  window.startQARotator = function(todayData, weeklyData, allTimeData) {
    const datasets = [
      { data: todayData, label: "Today's" },
      { data: weeklyData, label: "This Week's" },
      { data: allTimeData, label: "All Time" }
    ];
    let currentIndex = 0;

    function updateRotatingCards() {
      const current = datasets[currentIndex];
      const dataBearingCard = document.querySelector('#dataBeringToday')?.closest('.qa-de-card');
      const nonDataBearingCard = document.querySelector('#nonDataBeringToday')?.closest('.qa-de-card');
      if (dataBearingCard) { dataBearingCard.classList.add('flipping'); setTimeout(() => dataBearingCard.classList.remove('flipping'), 600); }
      if (nonDataBearingCard) { nonDataBearingCard.classList.add('flipping'); setTimeout(() => nonDataBearingCard.classList.remove('flipping'), 600); }
      const colorClasses = ['qa-card-today', 'qa-card-week', 'qa-card-alltime'];
      if (dataBearingCard) colorClasses.forEach(cls => dataBearingCard.classList.remove(cls));
      if (nonDataBearingCard) colorClasses.forEach(cls => nonDataBearingCard.classList.remove(cls));
      let colorClass = '';
      if (current.label === "Today's") colorClass = 'qa-card-today'; else if (current.label === "This Week's") colorClass = 'qa-card-week'; else if (current.label === 'All Time') colorClass = 'qa-card-alltime';
      if (dataBearingCard && colorClass) { dataBearingCard.classList.add(colorClass); if (!dataBearingCard.classList.contains('qa-card-data-bearing')) dataBearingCard.classList.add('qa-card-data-bearing'); }
      if (nonDataBearingCard && colorClass) { nonDataBearingCard.classList.add(colorClass); if (!nonDataBearingCard.classList.contains('qa-card-non-data-bearing')) nonDataBearingCard.classList.add('qa-card-non-data-bearing'); }
      const dataBearingTitle = dataBearingCard?.querySelector('h3'); if (dataBearingTitle) dataBearingTitle.textContent = `${current.label} Data Bearing`;
      window.populateQACard && window.populateQACard('dataBeringToday', 'dataBeringTodayEngineers', current.data, 'de', 6);
      const nonDataBearingTitle = nonDataBearingCard?.querySelector('h3'); if (nonDataBearingTitle) nonDataBearingTitle.textContent = `${current.label} Non Data Bearing`;
      window.populateQACard && window.populateQACard('nonDataBeringToday', 'nonDataBeringTodayEngineers', current.data, 'non_de', 6);
      currentIndex = (currentIndex + 1) % datasets.length;
    }

    updateRotatingCards();
    if (window.qaRotatorIntervalId) clearInterval(window.qaRotatorIntervalId);
    window.qaRotatorIntervalId = setInterval(updateRotatingCards, 30000);
  };

  window.populateQACard = function(totalId, listId, data, type = 'qa', maxItems = 6) {
    const totalEl = document.getElementById(totalId);
    const listEl = document.getElementById(listId);
    let total = 0; let engineers = [];
    if (type === 'qa') {
      total = (data.summary.deQaScans || 0) + (data.summary.nonDeQaScans || 0);
      engineers = (data.technicians || [])
        .filter(tech => ((tech.deQaScans || 0) + (tech.nonDeQaScans || 0)) > 0)
        .map(tech => ({ name: tech.name, count: (tech.deQaScans || 0) + (tech.nonDeQaScans || 0) }))
        .sort((a,b) => b.count - a.count).slice(0, maxItems);
    } else if (type === 'de') {
      total = data.summary.deQaScans || 0;
      engineers = (data.technicians || []).filter(tech => (tech.deQaScans || 0) > 0).map(tech => ({ name: tech.name, count: tech.deQaScans || 0 })).sort((a,b) => b.count - a.count).slice(0, maxItems);
    } else if (type === 'non_de') {
      total = data.summary.nonDeQaScans || 0;
      engineers = (data.technicians || []).filter(tech => (tech.nonDeQaScans || 0) > 0).map(tech => ({ name: tech.name, count: tech.nonDeQaScans || 0 })).sort((a,b) => b.count - a.count).slice(0, maxItems);
    }

    if (totalEl) totalEl.textContent = total.toLocaleString();
    if (listEl) {
      if (engineers.length === 0) {
        listEl.innerHTML = '<div style="padding: 12px; text-align: center; color: #888;">No data</div>';
      } else {
        listEl.innerHTML = engineers.map(eng => {
          const displayName = window.formatQaName ? window.formatQaName(eng.name) : (eng.name || '');
          const avatarKey = eng.name || displayName || 'QA';
          const avatar = window.getAvatarDataUri ? window.getAvatarDataUri(avatarKey) : '';
          return `\n            <div class="qa-engineer-item">\n              <div class="qa-engineer-left">\n                <span class="qa-engineer-avatar" style="background-image: url(${avatar})"></span>\n                <span class="qa-engineer-name">${window.escapeHtml ? window.escapeHtml(displayName) : displayName}</span>\n              </div>\n              <span class="qa-engineer-count">${eng.count.toLocaleString()}</span>\n            </div>\n          `;
        }).join('');
      }
    }
  };

  window.populateQAAppCard = function(totalId, listId, data, maxItems = 8) {
    const totalEl = document.getElementById(totalId);
    const listEl = document.getElementById(listId);
    const qaTotal = data.summary.totalScans || 0;
    if (totalEl) totalEl.textContent = qaTotal.toLocaleString();
    if (listEl) {
      const qaEngineers = (data.technicians || []).filter(tech => (tech.qaScans || 0) > 0).filter(tech => (tech.name || '').toLowerCase() !== '(unassigned)').map(tech => ({ name: tech.name, qaScans: tech.qaScans || 0 })).sort((a,b) => b.qaScans - a.qaScans).slice(0, maxItems);
      if (qaEngineers.length === 0) {
        listEl.innerHTML = '<div style="padding: 12px; text-align: center; color: #888;">No data</div>';
      } else {
        listEl.innerHTML = qaEngineers.map(eng => {
          const displayName = window.formatQaName ? window.formatQaName(eng.name) : (eng.name || '');
          const avatarKey = eng.name || displayName || 'QA';
          const avatar = window.getAvatarDataUri ? window.getAvatarDataUri(avatarKey) : '';
          return `\n            <div class="qa-engineer-item">\n              <div class="qa-engineer-left">\n                <span class="qa-engineer-avatar" style="background-image: url(${avatar})"></span>\n                <span class="qa-engineer-name">${window.escapeHtml ? window.escapeHtml(displayName) : displayName}</span>\n              </div>\n              <span class="qa-engineer-count">${eng.qaScans.toLocaleString()}</span>\n            </div>\n          `;
        }).join('');
      }
    }
  };

  window.populateMetricsCard = function(todayData, weeklyData) {
    const metricsContent = document.getElementById('metricsContent');
    const metricsValue = document.getElementById('metricsValue');
    const metricsLabel = document.getElementById('metricsLabel');
    if (!metricsContent) return;
    const todayTotal = (todayData.summary.deQaScans || 0) + (todayData.summary.nonDeQaScans || 0);
    const weeklyTotal = (weeklyData.summary.deQaScans || 0) + (weeklyData.summary.nonDeQaScans || 0);
    const avgDaily = weeklyTotal > 0 ? Math.round(weeklyTotal / 5) : 0;
    const engineerCount = todayData.technicians ? todayData.technicians.filter(t => (t.deQaScans || 0) + (t.nonDeQaScans || 0) > 0).length : 0;
    const avgPerEngineer = engineerCount > 0 ? Math.round(todayTotal / engineerCount) : 0;
    const avgConsistency = todayData.summary.avgConsistency || 0;
    const dailyRecords = todayData.summary.dailyRecord || weeklyData.summary.dailyRecord || { data_bearing_records: [], non_data_bearing_records: [] };
    const metricsCard = document.querySelector('.qa-metrics-card');
    let currentView = 0;

    function updateMetricsView() {
      if (metricsCard) { metricsCard.classList.add('flipping'); setTimeout(() => metricsCard.classList.remove('flipping'), 600); }
      if (currentView === 0) {
        metricsValue.textContent = todayTotal.toLocaleString();
        metricsLabel.textContent = "QA Summary";
        metricsContent.innerHTML = `\n          <div class="qa-metric-item">\n            <span class="qa-metric-label">Weekly Avg</span>\n            <span class="qa-metric-value">${avgDaily.toLocaleString()}/day</span>\n          </div>\n          <div class="qa-metric-item">\n            <span class="qa-metric-label">Active Engineers</span>\n            <span class="qa-metric-value">${engineerCount}</span>\n          </div>\n          <div class="qa-metric-item">\n            <span class="qa-metric-label">Avg per Engineer</span>\n            <span class="qa-metric-value">${avgPerEngineer.toLocaleString()}</span>\n          </div>\n          <div class="qa-metric-item">\n            <span class="qa-metric-label">Consistency</span>\n            <span class="qa-metric-value">${Math.round(avgConsistency)}%</span>\n          </div>\n          <div class="qa-metric-item">\n            <span class="qa-metric-label">Week Total</span>\n            <span class="qa-metric-value">${weeklyTotal.toLocaleString()}</span>\n          </div>\n        `;
      } else if (currentView === 1) {
        metricsValue.innerHTML = '<img class="qa-metrics-icon" src="assets/trophy-gold.svg" alt="Record">';
        metricsLabel.textContent = "Data Bearing - Most QA'd in 1 Day!";
        const dbRecords = dailyRecords.data_bearing_records || [];
        if (dbRecords.length === 0) {
          metricsContent.innerHTML = '<div style="padding: 12px; text-align: center; color: #888;">No records</div>';
        } else {
          const medals = ['🥇','🥈','🥉','4.','5.','6.'];
          metricsContent.innerHTML = dbRecords.map((record, index) => `\n            <div class="qa-metric-item">\n              <span class="qa-metric-label">${medals[index] || (index + 1 + '.')} ${window.escapeHtml ? window.escapeHtml(record.name) : record.name}</span>\n              <span class="qa-metric-value">${record.count.toLocaleString()}</span>\n            </div>\n          `).join('');
        }
      } else if (currentView === 2) {
        metricsValue.innerHTML = '<img class="qa-metrics-icon" src="assets/trophy-silver.svg" alt="Record">';
        metricsLabel.textContent = "Non-Data Bearing - Most QA'd in 1 Day!";
        const ndbRecords = dailyRecords.non_data_bearing_records || [];
        if (ndbRecords.length === 0) {
          metricsContent.innerHTML = '<div style="padding: 12px; text-align: center; color: #888;">No records</div>';
        } else {
          const medals = ['🥇','🥈','🥉','4.','5.','6.'];
          metricsContent.innerHTML = ndbRecords.map((record, index) => `\n            <div class="qa-metric-item">\n              <span class="qa-metric-label">${medals[index] || (index + 1 + '.')} ${window.escapeHtml ? window.escapeHtml(record.name) : record.name}</span>\n              <span class="qa-metric-value">${record.count.toLocaleString()}</span>\n            </div>\n          `).join('');
        }
      }
      currentView = (currentView + 1) % 3;
    }

    updateMetricsView();
    if (window.metricsFlipIntervalId) clearInterval(window.metricsFlipIntervalId);
    window.metricsFlipIntervalId = setInterval(updateMetricsView, 30000);
    if (metricsCard) { metricsCard.style.cursor = 'pointer'; metricsCard.onclick = updateMetricsView; }
  };

  window.showQAError = function(message) {
    const deWeeklyEngineers = document.getElementById('deWeeklyEngineers');
    const deAllTimeEngineers = document.getElementById('deAllTimeEngineers');
    const qaWeeklyEngineers = document.getElementById('qaWeeklyEngineers');
    const qaAllTimeEngineers = document.getElementById('qaAllTimeEngineers');
    const errorHtml = `\n      <div style="padding: 20px; text-align: center; color: #ff6b6b;">\n        <div style="font-size: 14px; font-weight: 600;">⚠️ ${message}</div>\n      </div>\n    `;
    if (deWeeklyEngineers) deWeeklyEngineers.innerHTML = errorHtml;
    if (deAllTimeEngineers) deAllTimeEngineers.innerHTML = errorHtml;
    if (qaWeeklyEngineers) qaWeeklyEngineers.innerHTML = errorHtml;
    if (qaAllTimeEngineers) qaAllTimeEngineers.innerHTML = errorHtml;
  };

  // Keep a flag so the common bundle can signal readiness if desired
  try { window.__dashboardQAReady = true; } catch (e) {}

})();

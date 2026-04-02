// QA dashboard module extracted from app.js to keep core bootstrap lean.
(function () {
  function createApi(deps) {
    const {
      escapeHtml,
      getAvatarDataUri,
      renderSVGSparkline,
    } = deps;

    const qaTrendPanelApi = (window.QATrendPanel && typeof window.QATrendPanel.init === 'function')
      ? window.QATrendPanel.init({
          escapeHtml,
          renderSVGSparkline,
        })
      : null;
    const qaMetricsRotatorApi = (window.QAMetricsRotator && typeof window.QAMetricsRotator.init === 'function')
      ? window.QAMetricsRotator.init({
          escapeHtml,
        })
      : null;

    let qaTopFlipIntervalId = null;
    let qaRotatorIntervalId = null;

    function clearIntervals() {
      if (qaTopFlipIntervalId) {
        clearInterval(qaTopFlipIntervalId);
        qaTopFlipIntervalId = null;
      }
      if (qaRotatorIntervalId) {
        clearInterval(qaRotatorIntervalId);
        qaRotatorIntervalId = null;
      }
      if (qaMetricsRotatorApi && typeof qaMetricsRotatorApi.stop === 'function') {
        qaMetricsRotatorApi.stop();
      }
    }

    async function loadQADashboard(period = 'this_week') {
      try {
        const [todayResponse, weeklyResponse, allTimeResponse] = await Promise.all([
          fetch('/api/qa-dashboard?period=today'),
          fetch('/api/qa-dashboard?period=this_week'),
          fetch('/api/qa-dashboard?period=all_time')
        ]);

        if (!todayResponse.ok || !weeklyResponse.ok || !allTimeResponse.ok) {
          showQAError('Failed to load QA data');
          return;
        }

        const todayData = await todayResponse.json();
        const weeklyData = await weeklyResponse.json();
        const allTimeData = await allTimeResponse.json();

        if (todayData.error || weeklyData.error || allTimeData.error) {
          console.error('QA data error');
          showQAError('Failed to load QA data');
          return;
        }

        populateQACard('qaTodayTotal', 'qaTodayEngineers', todayData, 'qa', 6);
        populateQACard('qaWeekTotal', 'qaWeeklyEngineers', weeklyData, 'qa', 6);
        populateQACard('qaAllTimeTotal', 'qaAllTimeEngineers', allTimeData, 'qa', 8);

        startQARotator(todayData, weeklyData, allTimeData);
        populateMetricsCard(todayData, weeklyData);

        const [todayTrend, weekTrend, allTimeTrend, todayInsights, weekInsights, allTimeInsights] = await Promise.all([
          fetch('/api/qa-trends?period=today').then(r => r.ok ? r.json() : null).catch(() => null),
          fetch('/api/qa-trends?period=this_week').then(r => r.ok ? r.json() : null).catch(() => null),
          fetch('/api/qa-trends?period=all_time').then(r => r.ok ? r.json() : null).catch(() => null),
          fetch('/api/insights/qa?period=today').then(r => r.ok ? r.json() : null).catch(() => null),
          fetch('/api/insights/qa?period=this_week').then(r => r.ok ? r.json() : null).catch(() => null),
          fetch('/api/insights/qa?period=all_time').then(r => r.ok ? r.json() : null).catch(() => null),
        ]);

        updateQATrendPanel({
          totalId: 'qaTodayTrendTotal',
          sparklineId: 'qaTodaySparkline',
          metricsId: 'qaTodayMetrics',
          trend: todayTrend,
          insights: todayInsights,
          mode: 'today'
        });
        updateQATrendPanel({
          totalId: 'qaWeekTrendTotal',
          sparklineId: 'qaWeekSparkline',
          metricsId: 'qaWeekMetrics',
          trend: weekTrend,
          insights: weekInsights,
          mode: 'week'
        });
        updateQATrendPanel({
          totalId: 'qaAllTimeTrendTotal',
          sparklineId: 'qaAllTimeSparkline',
          metricsId: 'qaAllTimeMetrics',
          trend: allTimeTrend,
          insights: allTimeInsights,
          mode: 'all_time'
        });

        startQATopFlipRotation();

        populateQAAppCard('qaAppTodayTotal', 'qaAppTodayEngineers', todayData, 6);
        populateQAAppCard('qaAppWeekTotal', 'qaAppWeeklyEngineers', weeklyData, 8);
        populateQAAppCard('qaAppAllTimeTotal', 'qaAppAllTimeEngineers', allTimeData, 10);
      } catch (error) {
        console.error('Failed to load QA dashboard:', error);
        showQAError('Connection error: ' + error.message);
      }
    }

    function startQATopFlipRotation() {
      const cards = document.querySelectorAll('.qa-top-flip-card');
      if (!cards.length) return;

      let flipped = false;
      cards.forEach(card => card.classList.remove('flipped'));

      if (qaTopFlipIntervalId) {
        clearInterval(qaTopFlipIntervalId);
      }

      qaTopFlipIntervalId = setInterval(() => {
        flipped = !flipped;
        cards.forEach(card => card.classList.toggle('flipped', flipped));
      }, 35000);
    }

    function updateQATrendPanel(params) {
      if (qaTrendPanelApi && typeof qaTrendPanelApi.updateQATrendPanel === 'function') {
        return qaTrendPanelApi.updateQATrendPanel(params);
      }
    }

    function startQARotator(todayData, weeklyData, allTimeData) {
      const datasets = [
        { data: todayData, label: "Today's" },
        { data: weeklyData, label: "This Week's" },
        { data: allTimeData, label: 'All Time' }
      ];

      let currentIndex = 0;

      function updateRotatingCards() {
        const current = datasets[currentIndex];

        const dataBearingCard = document.querySelector('#dataBeringToday')?.closest('.qa-de-card');
        const nonDataBearingCard = document.querySelector('#nonDataBeringToday')?.closest('.qa-de-card');

        if (dataBearingCard) {
          dataBearingCard.classList.add('flipping');
          setTimeout(() => dataBearingCard.classList.remove('flipping'), 600);
        }
        if (nonDataBearingCard) {
          nonDataBearingCard.classList.add('flipping');
          setTimeout(() => nonDataBearingCard.classList.remove('flipping'), 600);
        }

        const colorClasses = ['qa-card-today', 'qa-card-week', 'qa-card-alltime'];
        if (dataBearingCard) {
          colorClasses.forEach(cls => dataBearingCard.classList.remove(cls));
        }
        if (nonDataBearingCard) {
          colorClasses.forEach(cls => nonDataBearingCard.classList.remove(cls));
        }

        let colorClass = '';
        if (current.label === "Today's") {
          colorClass = 'qa-card-today';
        } else if (current.label === "This Week's") {
          colorClass = 'qa-card-week';
        } else if (current.label === 'All Time') {
          colorClass = 'qa-card-alltime';
        }

        if (dataBearingCard && colorClass) {
          dataBearingCard.classList.add(colorClass);
          if (!dataBearingCard.classList.contains('qa-card-data-bearing')) {
            dataBearingCard.classList.add('qa-card-data-bearing');
          }
        }

        if (nonDataBearingCard && colorClass) {
          nonDataBearingCard.classList.add(colorClass);
          if (!nonDataBearingCard.classList.contains('qa-card-non-data-bearing')) {
            nonDataBearingCard.classList.add('qa-card-non-data-bearing');
          }
        }

        const dataBearingTitle = dataBearingCard?.querySelector('h3');
        if (dataBearingTitle) {
          dataBearingTitle.textContent = `${current.label} Data Bearing`;
        }
        populateQACard('dataBeringToday', 'dataBeringTodayEngineers', current.data, 'de', 6);

        const nonDataBearingTitle = nonDataBearingCard?.querySelector('h3');
        if (nonDataBearingTitle) {
          nonDataBearingTitle.textContent = `${current.label} Non Data Bearing`;
        }
        populateQACard('nonDataBeringToday', 'nonDataBeringTodayEngineers', current.data, 'non_de', 6);

        currentIndex = (currentIndex + 1) % datasets.length;
      }

      updateRotatingCards();

      if (qaRotatorIntervalId) {
        clearInterval(qaRotatorIntervalId);
      }
      qaRotatorIntervalId = setInterval(updateRotatingCards, 30000);
    }

    function populateQACard(totalId, listId, data, type = 'qa', maxItems = 6) {
      const totalEl = document.getElementById(totalId);
      const listEl = document.getElementById(listId);

      let total = 0;
      let engineers = [];

      if (type === 'qa') {
        total = (data.summary.deQaScans || 0) + (data.summary.nonDeQaScans || 0);
        engineers = (data.technicians || [])
          .filter(tech => ((tech.deQaScans || 0) + (tech.nonDeQaScans || 0)) > 0)
          .map(tech => ({
            name: tech.name,
            count: (tech.deQaScans || 0) + (tech.nonDeQaScans || 0)
          }))
          .sort((a, b) => b.count - a.count)
          .slice(0, maxItems);
      } else if (type === 'de') {
        total = data.summary.deQaScans || 0;
        engineers = (data.technicians || [])
          .filter(tech => (tech.deQaScans || 0) > 0)
          .map(tech => ({
            name: tech.name,
            count: tech.deQaScans || 0
          }))
          .sort((a, b) => b.count - a.count)
          .slice(0, maxItems);
      } else if (type === 'non_de') {
        total = data.summary.nonDeQaScans || 0;
        engineers = (data.technicians || [])
          .filter(tech => (tech.nonDeQaScans || 0) > 0)
          .map(tech => ({
            name: tech.name,
            count: tech.nonDeQaScans || 0
          }))
          .sort((a, b) => b.count - a.count)
          .slice(0, maxItems);
      }

      if (totalEl) {
        totalEl.textContent = total.toLocaleString();
      }

      if (listEl) {
        if (engineers.length === 0) {
          listEl.innerHTML = '<div style="padding: 12px; text-align: center; color: #888;">No data</div>';
        } else {
          listEl.innerHTML = engineers.map(eng => {
            const displayName = formatQaName(eng.name);
            const avatarKey = eng.name || displayName || 'QA';
            const avatar = getAvatarDataUri(avatarKey);
            return `
              <div class="qa-engineer-item">
                <div class="qa-engineer-left">
                  <span class="qa-engineer-avatar" style="background-image: url(${avatar})"></span>
                  <span class="qa-engineer-name">${escapeHtml(displayName)}</span>
                </div>
                <span class="qa-engineer-count">${eng.count.toLocaleString()}</span>
              </div>
            `;
          }).join('');
        }
      }
    }

    function populateQAAppCard(totalId, listId, data, maxItems = 8) {
      const totalEl = document.getElementById(totalId);
      const listEl = document.getElementById(listId);

      const qaTotal = data.summary.totalScans || 0;

      if (totalEl) {
        totalEl.textContent = qaTotal.toLocaleString();
      }

      if (listEl) {
        const qaEngineers = (data.technicians || [])
          .filter(tech => (tech.qaScans || 0) > 0)
          .filter(tech => (tech.name || '').toLowerCase() !== '(unassigned)')
          .map(tech => ({
            name: tech.name,
            qaScans: tech.qaScans || 0
          }))
          .sort((a, b) => b.qaScans - a.qaScans)
          .slice(0, maxItems);

        if (qaEngineers.length === 0) {
          listEl.innerHTML = '<div style="padding: 12px; text-align: center; color: #888;">No data</div>';
        } else {
          listEl.innerHTML = qaEngineers.map(eng => {
            const displayName = formatQaName(eng.name);
            const avatarKey = eng.name || displayName || 'QA';
            const avatar = getAvatarDataUri(avatarKey);
            return `
              <div class="qa-engineer-item">
                <div class="qa-engineer-left">
                  <span class="qa-engineer-avatar" style="background-image: url(${avatar})"></span>
                  <span class="qa-engineer-name">${escapeHtml(displayName)}</span>
                </div>
                <span class="qa-engineer-count">${eng.qaScans.toLocaleString()}</span>
              </div>
            `;
          }).join('');
        }
      }
    }

    function populateMetricsCard(todayData, weeklyData) {
      if (qaMetricsRotatorApi && typeof qaMetricsRotatorApi.populateMetricsCard === 'function') {
        return qaMetricsRotatorApi.populateMetricsCard(todayData, weeklyData);
      }
    }

    function showQAError(message) {
      const deWeeklyEngineers = document.getElementById('deWeeklyEngineers');
      const deAllTimeEngineers = document.getElementById('deAllTimeEngineers');
      const qaWeeklyEngineers = document.getElementById('qaWeeklyEngineers');
      const qaAllTimeEngineers = document.getElementById('qaAllTimeEngineers');

      const errorHtml = `
        <div style="padding: 20px; text-align: center; color: #ff6b6b;">
          <div style="font-size: 14px; font-weight: 600;">⚠️ ${message}</div>
        </div>
      `;

      if (deWeeklyEngineers) deWeeklyEngineers.innerHTML = errorHtml;
      if (deAllTimeEngineers) deAllTimeEngineers.innerHTML = errorHtml;
      if (qaWeeklyEngineers) qaWeeklyEngineers.innerHTML = errorHtml;
      if (qaAllTimeEngineers) qaAllTimeEngineers.innerHTML = errorHtml;
    }

    function formatQaName(rawName) {
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
    }

    return {
      load: loadQADashboard,
      stop: clearIntervals,
    };
  }

  window.QADashboard = {
    init(deps) {
      return createApi(deps || {});
    },
  };
})();

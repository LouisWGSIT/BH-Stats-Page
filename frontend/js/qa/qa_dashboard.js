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
    const qaCardsRendererApi = (window.QACardsRenderer && typeof window.QACardsRenderer.init === 'function')
      ? window.QACardsRenderer.init({
          escapeHtml,
          getAvatarDataUri,
        })
      : null;
    const qaCardRotatorApi = (window.QACardRotator && typeof window.QACardRotator.init === 'function')
      ? window.QACardRotator.init({
          populateQACard: (totalId, listId, data, type, maxItems) =>
            populateQACard(totalId, listId, data, type, maxItems),
        })
      : null;
    const qaDashboardUiApi = (window.QADashboardUI && typeof window.QADashboardUI.init === 'function')
      ? window.QADashboardUI.init()
      : null;
    const qaDataLoaderApi = (window.QADataLoader && typeof window.QADataLoader.init === 'function')
      ? window.QADataLoader.init()
      : null;
    let sortingRotateIntervalId = null;
    let sortingViewIndex = 0;
    let throughputRotateIntervalId = null;

    function clearIntervals() {
      if (qaDashboardUiApi && typeof qaDashboardUiApi.stop === 'function') {
        qaDashboardUiApi.stop();
      }
      if (qaCardRotatorApi && typeof qaCardRotatorApi.stop === 'function') {
        qaCardRotatorApi.stop();
      }
      if (qaMetricsRotatorApi && typeof qaMetricsRotatorApi.stop === 'function') {
        qaMetricsRotatorApi.stop();
      }
      if (sortingRotateIntervalId) {
        clearInterval(sortingRotateIntervalId);
        sortingRotateIntervalId = null;
      }
      if (throughputRotateIntervalId) {
        clearInterval(throughputRotateIntervalId);
        throughputRotateIntervalId = null;
      }
    }

    function asNumber(value) {
      const num = Number(value);
      return Number.isFinite(num) ? num : 0;
    }

    function setText(id, value) {
      const el = document.getElementById(id);
      if (!el) return;
      el.textContent = value;
    }

    function setFlowComparisonText(id, todayValue, previousValue, compareDayShort) {
      const el = document.getElementById(id);
      if (!el) return;

      const today = asNumber(todayValue);
      const previous = asNumber(previousValue);

      el.classList.remove('is-up', 'is-down', 'is-flat');

      const delta = today - previous;
      const sign = delta > 0 ? '+' : '';
      if (delta > 0) {
        el.textContent = `▲ ${sign}${delta} vs ${compareDayShort || 'prev'}`;
        el.classList.add('is-up');
      } else if (delta < 0) {
        el.textContent = `▼ ${delta} vs ${compareDayShort || 'prev'}`;
        el.classList.add('is-down');
      } else {
        el.textContent = `• 0 vs ${compareDayShort || 'prev'}`;
        el.classList.add('is-flat');
      }
    }

    function getTechnicianName(tech) {
      const raw = tech && tech.name ? String(tech.name) : '';
      if (!raw) return 'Unknown';
      if (qaCardsRendererApi && typeof qaCardsRendererApi.formatQaName === 'function') {
        return qaCardsRendererApi.formatQaName(raw);
      }
      return raw;
    }

    function setActiveSortingPill(period) {
      const pills = document.querySelectorAll('#qaAppPeriodPills .qa-period-pill');
      pills.forEach((pill) => {
        pill.classList.toggle('is-active', pill.dataset.period === period);
      });
    }

    function startSortingCardRotator(todayData, weeklyData, allTimeData) {
      const datasets = [
        { period: 'today', title: "Today's", data: todayData, maxItems: 4 },
        { period: 'this_week', title: 'This Week', data: weeklyData, maxItems: 4 },
        { period: 'all_time', title: 'All Time', data: allTimeData, maxItems: 3 },
      ];

      const titleEl = document.getElementById('qaAppRotatingTitle');
      const cardEl = document.getElementById('qaAppRotatingCard');
      const pills = document.querySelectorAll('#qaAppPeriodPills .qa-period-pill');

      function renderCurrent() {
        const current = datasets[sortingViewIndex] || datasets[0];
        if (titleEl) titleEl.textContent = current.title;
        if (cardEl) {
          cardEl.classList.add('flipping');
          setTimeout(() => cardEl.classList.remove('flipping'), 400);
        }
        setActiveSortingPill(current.period);
        populateQAAppCard('qaAppRotatingTotal', 'qaAppRotatingEngineers', current.data, current.maxItems);
      }

      renderCurrent();
      if (sortingRotateIntervalId) {
        clearInterval(sortingRotateIntervalId);
        sortingRotateIntervalId = null;
      }
      sortingRotateIntervalId = setInterval(() => {
        sortingViewIndex = (sortingViewIndex + 1) % datasets.length;
        renderCurrent();
      }, 30000);

      pills.forEach((pill, idx) => {
        pill.onclick = () => {
          const period = pill.dataset.period;
          const nextIndex = datasets.findIndex((d) => d.period === period);
          sortingViewIndex = nextIndex >= 0 ? nextIndex : idx;
          renderCurrent();
        };
      });
    }

    function parseTrendSeries(trendPayload) {
      const series = Array.isArray(trendPayload && trendPayload.series) ? trendPayload.series : [];
      return series.map((point, idx) => ({
        label: String((point && (point.hour || point.day || point.date || point.label)) || `#${idx + 1}`),
        value: asNumber(point && (point.total || point.count || point.value || point.scans)),
      }));
    }

    function getThroughputPoints(trendPayload, metricKey) {
      const series = Array.isArray(trendPayload && trendPayload.series) ? trendPayload.series : [];
      return series.map((point, idx) => {
        const rawLabel = (point && (point.hour || point.day || point.date || point.label));
        const label = String(rawLabel != null ? rawLabel : `#${idx + 1}`);
        return {
          label,
          value: asNumber(point && (point[metricKey] ?? point.value ?? point.total ?? point.count ?? point.scans)),
        };
      });
    }

    function renderThroughputPulseWithConfig(trendPayload, metricKey, title) {
      const chartWrapEl = document.getElementById('qaThroughputTimeline');
      const sparklineEl = document.getElementById('qaSortingThroughputSpark');
      const xAxisEl = document.getElementById('qaThroughputXAxis');
      const titleEl = document.getElementById('qaThroughputTitle');
      if (!chartWrapEl || !sparklineEl || !xAxisEl) return;

      if (titleEl) {
        titleEl.textContent = title || "Throughput";
      }

      const points = getThroughputPoints(trendPayload, metricKey).slice(-8);
      const peak = points.reduce((max, p) => (p.value > max ? p.value : max), 0);
      const latest = points.length ? points[points.length - 1].value : 0;
      setText('qaThroughputPeak', latest > 0 ? latest.toLocaleString() : '--');

      if (!points.length) {
        sparklineEl.innerHTML = '';
        xAxisEl.innerHTML = '';
        chartWrapEl.classList.add('is-empty');
        chartWrapEl.dataset.emptyText = 'No hourly data yet.';
        return;
      }

      chartWrapEl.classList.remove('is-empty');
      chartWrapEl.dataset.emptyText = '';

      const values = points.map((p) => p.value);
      const width = 400;
      const height = 120;
      const paddingX = 16;
      const paddingY = 16;
      const chartWidth = width - (paddingX * 2);
      const chartHeight = height - (paddingY * 2);
      const maxValue = Math.max(...values, 1);
      const stepX = points.length > 1 ? chartWidth / (points.length - 1) : chartWidth;
      const coords = values.map((value, index) => {
        const x = paddingX + (index * stepX);
        const y = height - paddingY - ((value / maxValue) * chartHeight);
        return { x, y, value };
      });

      const linePath = coords.map((point, index) => `${index === 0 ? 'M' : 'L'}${point.x.toFixed(2)},${point.y.toFixed(2)}`).join(' ');
      const areaPath = `${linePath} L${(paddingX + chartWidth).toFixed(2)},${(height - paddingY).toFixed(2)} L${paddingX.toFixed(2)},${(height - paddingY).toFixed(2)} Z`;

      sparklineEl.innerHTML = `
        <defs>
          <linearGradient id="qaSortingThroughputFill" x1="0%" y1="0%" x2="0%" y2="100%">
            <stop offset="0%" stop-color="rgba(158,255,106,0.45)"></stop>
            <stop offset="100%" stop-color="rgba(158,255,106,0.03)"></stop>
          </linearGradient>
          <linearGradient id="qaSortingThroughputStroke" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%" stop-color="#7ef4b3"></stop>
            <stop offset="100%" stop-color="#d1ff65"></stop>
          </linearGradient>
        </defs>
        <line class="qa-throughput-gridline" x1="${paddingX}" y1="${height - paddingY}" x2="${width - paddingX}" y2="${height - paddingY}"></line>
        <line class="qa-throughput-gridline qa-throughput-gridline-mid" x1="${paddingX}" y1="${paddingY + (chartHeight / 2)}" x2="${width - paddingX}" y2="${paddingY + (chartHeight / 2)}"></line>
        <path class="qa-throughput-area" d="${areaPath}"></path>
        <path class="qa-throughput-line" d="${linePath}"></path>
        <circle class="qa-throughput-point" cx="${coords[coords.length - 1].x.toFixed(2)}" cy="${coords[coords.length - 1].y.toFixed(2)}" r="4"></circle>
      `;

      xAxisEl.style.gridTemplateColumns = `repeat(${points.length}, minmax(0, 1fr))`;
      xAxisEl.innerHTML = points.map((point) => (
        `<span class="qa-throughput-xlabel">${escapeHtml(point.label)}</span>`
      )).join('');
    }

    function renderThroughputPulse(todayTrend) {
      renderThroughputPulseWithConfig(todayTrend, 'qaTotal', "Throughput (QA'd per Hour)");
    }

    function startThroughputCardRotator(todayTrend, sortingTodayTrend) {
      const states = [
        { title: "Throughput (QA'd per Hour)", metricKey: 'qaTotal', trend: todayTrend },
        { title: "Throughput (Sorted per Hour)", metricKey: 'qaApp', trend: sortingTodayTrend || todayTrend },
      ];
      let idx = 0;
      renderThroughputPulseWithConfig(states[idx].trend, states[idx].metricKey, states[idx].title);
      if (throughputRotateIntervalId) {
        clearInterval(throughputRotateIntervalId);
        throughputRotateIntervalId = null;
      }
      throughputRotateIntervalId = setInterval(() => {
        idx = (idx + 1) % states.length;
        const current = states[idx];
        renderThroughputPulseWithConfig(current.trend, current.metricKey, current.title);
      }, 25000);
    }

    function populateMiddleLeaderboard(todayData) {
      populateQACard('qaLeaderboardTotal', 'qaLeaderboardEngineers', todayData, 'qa', 5);
    }

    function setAllTimeLoadingState(isLoading) {
      const allTimeLabelEl = document.querySelector('#qaAllTimeCard .qa-flip-front .qa-de-label');
      const allTimeListEl = document.getElementById('qaAllTimeEngineers');
      if (allTimeLabelEl) {
        allTimeLabelEl.textContent = isLoading ? 'Loading all-time…' : "Total QA'd";
      }
      if (allTimeListEl && isLoading) {
        allTimeListEl.innerHTML = '<div style="padding: 12px; text-align: center; color: #8cb2d6;">Loading all-time data…</div>';
      }
    }

    function emptyDashboardData(period = 'this_week') {
      if (qaDataLoaderApi && typeof qaDataLoaderApi.createEmptyDashboardPayload === 'function') {
        return qaDataLoaderApi.createEmptyDashboardPayload(period);
      }
      return {
        period,
        dateRange: '',
        technicians: [],
        summary: {
          totalScans: 0,
          deQaScans: 0,
          nonDeQaScans: 0,
          combinedScans: 0,
        },
        topPerformers: [],
      };
    }

    function buildTopMovers(todayData, weeklyData) {
      const todayByName = new Map();
      const weekByName = new Map();
      (todayData && Array.isArray(todayData.technicians) ? todayData.technicians : []).forEach((tech) => {
        todayByName.set(String(tech.name || '').toLowerCase(), tech);
      });
      (weeklyData && Array.isArray(weeklyData.technicians) ? weeklyData.technicians : []).forEach((tech) => {
        weekByName.set(String(tech.name || '').toLowerCase(), tech);
      });

      const rows = [];
      todayByName.forEach((todayTech, key) => {
        if (!key || key === '(unassigned)') return;
        const weekTech = weekByName.get(key) || {};
        const todayCount = asNumber(todayTech.qaScans);
        const weekCount = asNumber(weekTech.qaScans);
        const baseline = Math.max(1, Math.round(weekCount / 5));
        const delta = todayCount - baseline;
        rows.push({
          name: getTechnicianName(todayTech),
          todayCount,
          delta,
          score: Math.abs(delta),
        });
      });

      return rows
        .sort((a, b) => (b.score - a.score) || (b.todayCount - a.todayCount))
        .slice(0, 4);
    }

    function renderTopMovers(todayData, weeklyData) {
      const listEl = document.getElementById('qaTopMovers');
      if (!listEl) return;
      const movers = buildTopMovers(todayData, weeklyData);
      if (!movers.length) {
        listEl.innerHTML = '<div class="qa-throughput-empty">No mover data yet.</div>';
        setText('qaMoversLead', '--');
        return;
      }
      const lead = movers[0];
      setText('qaMoversLead', `${lead.delta >= 0 ? '+' : ''}${lead.delta}`);
      listEl.innerHTML = movers.map((m, index) => `
        <div class="qa-mover-item">
          <span class="qa-mover-rank">${index + 1}</span>
          <span class="qa-mover-name">${escapeHtml(m.name)}</span>
          <span class="qa-mover-delta ${m.delta > 0 ? 'is-up' : (m.delta < 0 ? 'is-down' : 'is-flat')}">${m.delta > 0 ? '+' : ''}${m.delta}</span>
          <span class="qa-mover-count">${m.todayCount.toLocaleString()}</span>
        </div>
      `).join('');
    }

    function renderFlowStrip(flowData, todayData) {
      const compareDayShort = String((flowData && flowData.compareDayShort) || 'prev');

      const erased = asNumber(flowData && flowData.erased && flowData.erased.today);
      const erasedPrev = asNumber(flowData && flowData.erased && flowData.erased.previous);

      const qaDone = asNumber(flowData && flowData.qa && flowData.qa.today);
      const qaPrev = asNumber(flowData && flowData.qa && flowData.qa.previous);

      const sorted = asNumber(flowData && flowData.sorting && flowData.sorting.today);
      const sortedPrev = asNumber(flowData && flowData.sorting && flowData.sorting.previous);

      const fallbackQa = asNumber(todayData && todayData.summary && (
        asNumber(todayData.summary.deQaScans) + asNumber(todayData.summary.nonDeQaScans)
      ));
      const fallbackSorted = asNumber(todayData && todayData.summary && todayData.summary.totalScans);

      const finalQa = fallbackQa > 0 ? fallbackQa : qaDone;
      const finalSorted = fallbackSorted > 0 ? fallbackSorted : sorted;

      setText('qaFlowErasedToday', erased.toLocaleString());
      setText('qaFlowQAToday', finalQa.toLocaleString());
      setText('qaFlowSortedToday', finalSorted.toLocaleString());

      setFlowComparisonText(
        'qaFlowErasedTrend',
        erased,
        erasedPrev,
        compareDayShort
      );
      setFlowComparisonText(
        'qaFlowQATrend',
        finalQa,
        qaPrev,
        compareDayShort
      );
      setFlowComparisonText(
        'qaFlowSortedTrend',
        finalSorted,
        sortedPrev,
        compareDayShort
      );

    }

    async function loadQADashboard(period = 'this_week') {
      try {
        if (!qaDataLoaderApi) {
          showQAError('Failed to load QA data');
          return;
        }

        const quickData = (typeof qaDataLoaderApi.loadDashboardDataQuick === 'function')
          ? await qaDataLoaderApi.loadDashboardDataQuick()
          : await qaDataLoaderApi.loadDashboardData();

        const dashboardData = quickData;
        if (!dashboardData || !dashboardData.ok) {
          showQAError((dashboardData && dashboardData.error) || 'Failed to load QA data');
          return;
        }

        const todayData = dashboardData.todayData || emptyDashboardData('today');
        const weeklyData = dashboardData.weeklyData || emptyDashboardData('this_week');
        let allTimeData = dashboardData.allTimeData || emptyDashboardData('all_time');

        populateQACard('qaTodayTotal', 'qaTodayEngineers', todayData, 'qa', 4);
        populateQACard('qaWeekTotal', 'qaWeeklyEngineers', weeklyData, 'qa', 4);
        populateQACard('qaAllTimeTotal', 'qaAllTimeEngineers', allTimeData, 'qa', 5);
        populateMiddleLeaderboard(todayData);
        setAllTimeLoadingState(true);

        startQARotator(todayData, weeklyData, allTimeData);

        startSortingCardRotator(todayData, weeklyData, allTimeData);
        renderTopMovers(todayData, weeklyData);

        lockQATopCardsToCharts();

        qaDataLoaderApi.loadFlowSummaryData()
          .then((flowData) => renderFlowStrip(flowData, todayData))
          .catch(() => renderFlowStrip(null, todayData));

        // Hydrate all-time data in the background so first paint is not blocked.
        if (typeof qaDataLoaderApi.loadDashboardPeriod === 'function') {
          qaDataLoaderApi.loadDashboardPeriod('all_time')
            .then((allTimePayload) => {
              if (!allTimePayload || allTimePayload.error) return;
              allTimeData = allTimePayload;
              populateQACard('qaAllTimeTotal', 'qaAllTimeEngineers', allTimeData, 'qa', 5);
              startQARotator(todayData, weeklyData, allTimeData);
              startSortingCardRotator(todayData, weeklyData, allTimeData);
              setAllTimeLoadingState(false);
            })
            .catch(() => {});
        }

        // Load trend/insight panels asynchronously so the main QA cards paint first.
        qaDataLoaderApi.loadTrendAndInsightsData()
          .then((trendData) => {
            if (!trendData) return;
            const {
              todayTrend,
              sortingTodayTrend,
              weekTrend,
              allTimeTrend,
              todayInsights,
              weekInsights,
              allTimeInsights,
            } = trendData;

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

            startThroughputCardRotator(todayTrend, sortingTodayTrend);
          })
          .catch(() => {
            // Keep existing panel state on background trend refresh errors.
            renderThroughputPulse(null);
          });
      } catch (error) {
        console.error('Failed to load QA dashboard:', error);
        showQAError('Connection error: ' + error.message);
      }
    }

    function startQATopFlipRotation() {
      if (qaDashboardUiApi && typeof qaDashboardUiApi.startQATopFlipRotation === 'function') {
        return qaDashboardUiApi.startQATopFlipRotation();
      }
    }

    function lockQATopCardsToCharts() {
      if (qaDashboardUiApi && typeof qaDashboardUiApi.lockQATopCardsToCharts === 'function') {
        return qaDashboardUiApi.lockQATopCardsToCharts();
      }
      startQATopFlipRotation();
    }

    function updateQATrendPanel(params) {
      if (qaTrendPanelApi && typeof qaTrendPanelApi.updateQATrendPanel === 'function') {
        return qaTrendPanelApi.updateQATrendPanel(params);
      }
    }

    function startQARotator(todayData, weeklyData, allTimeData) {
      if (qaCardRotatorApi && typeof qaCardRotatorApi.startQARotator === 'function') {
        return qaCardRotatorApi.startQARotator(todayData, weeklyData, allTimeData);
      }
    }

    function populateQACard(totalId, listId, data, type = 'qa', maxItems = 6) {
      if (qaCardsRendererApi && typeof qaCardsRendererApi.populateQACard === 'function') {
        return qaCardsRendererApi.populateQACard(totalId, listId, data, type, maxItems);
      }
    }

    function populateQAAppCard(totalId, listId, data, maxItems = 8) {
      if (qaCardsRendererApi && typeof qaCardsRendererApi.populateQAAppCard === 'function') {
        return qaCardsRendererApi.populateQAAppCard(totalId, listId, data, maxItems);
      }
    }

    function showQAError(message) {
      if (qaDashboardUiApi && typeof qaDashboardUiApi.showQAError === 'function') {
        return qaDashboardUiApi.showQAError(message);
      }
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

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
    }

    async function loadQADashboard(period = 'this_week') {
      try {
        if (!qaDataLoaderApi) {
          showQAError('Failed to load QA data');
          return;
        }

        const dashboardData = await qaDataLoaderApi.loadDashboardData();
        if (!dashboardData || !dashboardData.ok) {
          showQAError((dashboardData && dashboardData.error) || 'Failed to load QA data');
          return;
        }

        const { todayData, weeklyData, allTimeData } = dashboardData;

        populateQACard('qaTodayTotal', 'qaTodayEngineers', todayData, 'qa', 6);
        populateQACard('qaWeekTotal', 'qaWeeklyEngineers', weeklyData, 'qa', 6);
        populateQACard('qaAllTimeTotal', 'qaAllTimeEngineers', allTimeData, 'qa', 8);

        startQARotator(todayData, weeklyData, allTimeData);
        populateMetricsCard(todayData, weeklyData);

        const {
          todayTrend,
          weekTrend,
          allTimeTrend,
          todayInsights,
          weekInsights,
          allTimeInsights,
        } = await qaDataLoaderApi.loadTrendAndInsightsData();

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
      if (qaDashboardUiApi && typeof qaDashboardUiApi.startQATopFlipRotation === 'function') {
        return qaDashboardUiApi.startQATopFlipRotation();
      }
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

    function populateMetricsCard(todayData, weeklyData) {
      if (qaMetricsRotatorApi && typeof qaMetricsRotatorApi.populateMetricsCard === 'function') {
        return qaMetricsRotatorApi.populateMetricsCard(todayData, weeklyData);
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

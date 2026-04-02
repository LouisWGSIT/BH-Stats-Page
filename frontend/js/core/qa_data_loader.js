// QA data loading helpers extracted from qa_dashboard.js.
(function () {
  function init() {
    async function loadDashboardData() {
      const [todayResponse, weeklyResponse, allTimeResponse] = await Promise.all([
        fetch('/api/qa-dashboard?period=today'),
        fetch('/api/qa-dashboard?period=this_week'),
        fetch('/api/qa-dashboard?period=all_time'),
      ]);

      if (!todayResponse.ok || !weeklyResponse.ok || !allTimeResponse.ok) {
        return { ok: false, error: 'Failed to load QA data' };
      }

      const todayData = await todayResponse.json();
      const weeklyData = await weeklyResponse.json();
      const allTimeData = await allTimeResponse.json();

      if (todayData.error || weeklyData.error || allTimeData.error) {
        return { ok: false, error: 'Failed to load QA data' };
      }

      return {
        ok: true,
        todayData,
        weeklyData,
        allTimeData,
      };
    }

    async function loadTrendAndInsightsData() {
      const [todayTrend, weekTrend, allTimeTrend, todayInsights, weekInsights, allTimeInsights] = await Promise.all([
        fetch('/api/qa-trends?period=today').then((r) => (r.ok ? r.json() : null)).catch(() => null),
        fetch('/api/qa-trends?period=this_week').then((r) => (r.ok ? r.json() : null)).catch(() => null),
        fetch('/api/qa-trends?period=all_time').then((r) => (r.ok ? r.json() : null)).catch(() => null),
        fetch('/api/insights/qa?period=today').then((r) => (r.ok ? r.json() : null)).catch(() => null),
        fetch('/api/insights/qa?period=this_week').then((r) => (r.ok ? r.json() : null)).catch(() => null),
        fetch('/api/insights/qa?period=all_time').then((r) => (r.ok ? r.json() : null)).catch(() => null),
      ]);

      return {
        todayTrend,
        weekTrend,
        allTimeTrend,
        todayInsights,
        weekInsights,
        allTimeInsights,
      };
    }

    return {
      loadDashboardData,
      loadTrendAndInsightsData,
    };
  }

  window.QADataLoader = {
    init,
  };
})();

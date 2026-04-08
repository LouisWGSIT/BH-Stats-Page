// QA data loading helpers extracted from qa_dashboard.js.
(function () {
  function init() {
    const bootstrapCache = {
      fetchedAt: 0,
      payload: null,
    };
    const BOOTSTRAP_TTL_MS = 45000;

    function isUsableBootstrap(payload) {
      return !!(
        payload
        && typeof payload === 'object'
        && payload.dashboard
        && payload.trends
        && payload.insights
      );
    }

    async function loadBootstrapData(forceRefresh = false) {
      const now = Date.now();
      if (!forceRefresh && bootstrapCache.payload && (now - bootstrapCache.fetchedAt) < BOOTSTRAP_TTL_MS) {
        return bootstrapCache.payload;
      }

      try {
        const res = await fetch('/api/qa-bootstrap');
        if (!res.ok) return null;
        const payload = await res.json();
        if (!isUsableBootstrap(payload) || payload.error) return null;
        bootstrapCache.payload = payload;
        bootstrapCache.fetchedAt = now;
        return payload;
      } catch (_err) {
        return null;
      }
    }

    async function loadDashboardData() {
      const bootstrap = await loadBootstrapData();
      if (bootstrap && bootstrap.dashboard) {
        return {
          ok: true,
          todayData: bootstrap.dashboard.today,
          weeklyData: bootstrap.dashboard.this_week,
          allTimeData: bootstrap.dashboard.all_time,
        };
      }

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
      const bootstrap = await loadBootstrapData();
      if (bootstrap && bootstrap.trends && bootstrap.insights) {
        return {
          todayTrend: bootstrap.trends.today,
          weekTrend: bootstrap.trends.this_week,
          allTimeTrend: bootstrap.trends.all_time,
          todayInsights: bootstrap.insights.today,
          weekInsights: bootstrap.insights.this_week,
          allTimeInsights: bootstrap.insights.all_time,
        };
      }

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
      loadBootstrapData,
    };
  }

  window.QADataLoader = {
    init,
  };
})();

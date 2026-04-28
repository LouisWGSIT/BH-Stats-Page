// QA data loading helpers extracted from qa_dashboard.js.
(function () {
  function init() {
    const bootstrapCache = {
      fetchedAt: 0,
      payload: null,
    };
    const BOOTSTRAP_TTL_MS = 45000;
    const BOOTSTRAP_FETCH_TIMEOUT_MS = 4000;

    function createEmptyDashboardPayload(period = "this_week") {
      return {
        period,
        dateRange: '',
        technicians: [],
        summary: {
          totalScans: 0,
          deQaScans: 0,
          nonDeQaScans: 0,
          combinedScans: 0,
          passRate: 0,
          avgConsistency: 0,
          topTechnician: 'N/A',
          techniciansCount: 0,
        },
        topPerformers: [],
      };
    }

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
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), BOOTSTRAP_FETCH_TIMEOUT_MS);
        const res = await fetch('/api/qa-bootstrap', { signal: controller.signal });
        clearTimeout(timeoutId);
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

    async function loadDashboardPeriod(period = 'this_week') {
      const bootstrap = await loadBootstrapData();
      if (bootstrap && bootstrap.dashboard && bootstrap.dashboard[period]) {
        return bootstrap.dashboard[period];
      }

      try {
        const res = await fetch(`/api/qa-dashboard?period=${encodeURIComponent(period)}`);
        if (!res.ok) return createEmptyDashboardPayload(period);
        const payload = await res.json();
        if (!payload || payload.error) return createEmptyDashboardPayload(period);
        return payload;
      } catch (_err) {
        return createEmptyDashboardPayload(period);
      }
    }

    async function loadDashboardDataQuick() {
      const [todayData, weeklyData] = await Promise.all([
        loadDashboardPeriod('today'),
        loadDashboardPeriod('this_week'),
      ]);
      return {
        ok: true,
        todayData: todayData || createEmptyDashboardPayload('today'),
        weeklyData: weeklyData || createEmptyDashboardPayload('this_week'),
      };
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

    function asNumber(value) {
      const num = Number(value);
      return Number.isFinite(num) ? num : 0;
    }

    function getSectionDone(section) {
      const key = String(section && section.key ? section.key : '').toLowerCase();
      const rows = Array.isArray(section && section.subMetrics) ? section.subMetrics : [];
      const findValue = (patterns) => {
        for (const row of rows) {
          const label = String(row && row.label ? row.label : '').toLowerCase();
          if (patterns.some((pattern) => pattern.test(label))) {
            return asNumber(row.value);
          }
        }
        return 0;
      };

      if (key === 'erasure') {
        return findValue([/erased today/, /processed today/, /completed erasure/]);
      }
      if (key === 'qa') {
        return findValue([/completed qa today/, /qa complete/]);
      }
      if (key === 'sorting') {
        return findValue([/sorted today/, /sorted this morning/]);
      }
      return 0;
    }

    async function loadFlowSummaryData() {
      try {
        const flowRes = await fetch('/metrics/flow-comparison').catch(() => null);
        if (flowRes && flowRes.ok) {
          return await flowRes.json();
        }

        const [todayRes, yesterdayRes] = await Promise.all([
          fetch('/metrics/today').catch(() => null),
          fetch('/metrics/yesterday').catch(() => null),
        ]);
        const todayPayload = (todayRes && todayRes.ok) ? await todayRes.json() : {};
        const yesterdayPayload = (yesterdayRes && yesterdayRes.ok) ? await yesterdayRes.json() : {};
        return {
          compareDayShort: 'Prev',
          erased: {
            today: asNumber(todayPayload && todayPayload.erased),
            previous: asNumber(yesterdayPayload && yesterdayPayload.erased),
            delta: asNumber(todayPayload && todayPayload.erased) - asNumber(yesterdayPayload && yesterdayPayload.erased),
            deltaPct: null,
          },
          qa: { today: 0, previous: 0, delta: 0, deltaPct: null },
          sorting: { today: 0, previous: 0, delta: 0, deltaPct: null },
        };
      } catch (_err) {
        return null;
      }
    }

    return {
      loadDashboardData,
      loadDashboardDataQuick,
      loadDashboardPeriod,
      loadTrendAndInsightsData,
      loadBootstrapData,
      loadFlowSummaryData,
      createEmptyDashboardPayload,
    };
  }

  window.QADataLoader = {
    init,
  };
})();

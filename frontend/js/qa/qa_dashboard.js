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

    function setTrendText(id, delta) {
      const el = document.getElementById(id);
      if (!el) return;
      const n = asNumber(delta);
      const sign = n > 0 ? '+' : '';
      el.textContent = `${sign}${n}`;
      el.classList.remove('is-up', 'is-down', 'is-flat');
      if (n > 0) el.classList.add('is-up');
      else if (n < 0) el.classList.add('is-down');
      else el.classList.add('is-flat');
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
        { period: 'today', title: "Today's", data: todayData, maxItems: 6 },
        { period: 'this_week', title: 'This Week', data: weeklyData, maxItems: 8 },
        { period: 'all_time', title: 'All Time', data: allTimeData, maxItems: 10 },
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

    function renderThroughputPulse(todayTrend) {
      const listEl = document.getElementById('qaThroughputTimeline');
      if (!listEl) return;
      const points = parseTrendSeries(todayTrend).slice(-8);
      const peak = points.reduce((max, p) => (p.value > max ? p.value : max), 0);
      setText('qaThroughputPeak', peak > 0 ? peak.toLocaleString() : '--');
      if (!points.length) {
        listEl.innerHTML = '<div class="qa-throughput-empty">No hourly data yet.</div>';
        return;
      }
      const maxValue = peak || 1;
      listEl.innerHTML = points.map((p) => {
        const pct = Math.max(6, Math.round((p.value / maxValue) * 100));
        return `
          <div class="qa-throughput-item">
            <span class="qa-throughput-label">${escapeHtml(p.label)}</span>
            <span class="qa-throughput-bar"><span class="qa-throughput-fill" style="width:${pct}%"></span></span>
            <strong class="qa-throughput-value">${p.value.toLocaleString()}</strong>
          </div>
        `;
      }).join('');
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
        .slice(0, 5);
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

    function renderFlowStrip(flowData, todayData, weeklyData) {
      const erased = asNumber(flowData && flowData.erasedToday);
      const qaDone = asNumber(todayData && todayData.summary && (
        asNumber(todayData.summary.deQaScans) + asNumber(todayData.summary.nonDeQaScans)
      ));
      const sorted = asNumber(todayData && todayData.summary && todayData.summary.totalScans);
      setText('qaFlowErasedToday', erased.toLocaleString());
      setText('qaFlowQAToday', qaDone.toLocaleString());
      setText('qaFlowSortedToday', sorted.toLocaleString());

      const weekQaTotal = asNumber(weeklyData && weeklyData.summary && weeklyData.summary.deQaScans)
        + asNumber(weeklyData && weeklyData.summary && weeklyData.summary.nonDeQaScans);
      const weekSortingTotal = asNumber(weeklyData && weeklyData.summary && weeklyData.summary.totalScans);
      const qaBaseline = Math.max(1, Math.round(weekQaTotal / 5));
      const sortingBaseline = Math.max(1, Math.round(weekSortingTotal / 5));
      const qaTrend = qaDone - qaBaseline;
      const sortedTrend = sorted - sortingBaseline;
      const erasedYesterday = asNumber(flowData && flowData.erasedYesterday);
      const erasedTrend = erasedYesterday > 0 ? (erased - erasedYesterday) : (erased - qaDone);

      setTrendText('qaFlowErasedTrend', erasedTrend);
      setTrendText('qaFlowQATrend', qaTrend);
      setTrendText('qaFlowSortedTrend', sortedTrend);

      const checkupMessageEl = document.getElementById('qaGreenieCheckupMessage');
      if (checkupMessageEl) {
        if (qaDone >= erased && sorted >= qaDone) {
          checkupMessageEl.textContent = 'Flow is healthy. Teams are keeping pace today.';
        } else if (qaDone < erased) {
          checkupMessageEl.textContent = 'QA is trailing erasure. Check support for QA lane.';
        } else {
          checkupMessageEl.textContent = 'Sorting output is behind QA. Dispatch may need support.';
        }
      }

      const pointsEl = document.getElementById('qaGreenieCheckupPoints');
      if (pointsEl) {
        pointsEl.innerHTML = `
          <div class="qa-greenie-point">Erasure to QA gap: <strong>${Math.max(0, erased - qaDone)}</strong></div>
          <div class="qa-greenie-point">QA to Sorting gap: <strong>${Math.max(0, qaDone - sorted)}</strong></div>
          <div class="qa-greenie-point">Sorting throughput: <strong>${sorted.toLocaleString()}</strong> scans today</div>
        `;
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

        startSortingCardRotator(todayData, weeklyData, allTimeData);
        renderTopMovers(todayData, weeklyData);

        startQATopFlipRotation();

        qaDataLoaderApi.loadFlowSummaryData()
          .then((flowData) => renderFlowStrip(flowData, todayData, weeklyData))
          .catch(() => renderFlowStrip(null, todayData, weeklyData));

        // Load trend/insight panels asynchronously so the main QA cards paint first.
        qaDataLoaderApi.loadTrendAndInsightsData()
          .then((trendData) => {
            if (!trendData) return;
            const {
              todayTrend,
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

            renderThroughputPulse(todayTrend);
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

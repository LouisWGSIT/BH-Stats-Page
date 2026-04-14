// Overall stats dashboard with mock operational data for staffing huddles.
(function () {
  function init() {
    let isLoading = false;

    const mockSections = [
      {
        key: 'goods_in',
        name: 'Goods In',
        target: 90,
        current: 412,
        trend: 14,
        owner: 'Inbound Team',
        queueLabel: 'GRNs (Last 3 Months)',
        subMetrics: [
          { label: 'Total Received (Not Booked In)', value: 412 },
          { label: 'Booked In Today', value: 61 },
          { label: 'Awaiting IA (All Booked In)', value: 1743 },
        ],
      },
      {
        key: 'ia',
        name: 'IA',
        target: 72,
        current: 0,
        trend: 0,
        owner: 'Assessment Team',
        queueLabel: 'Totes Awaiting IA',
        subMetrics: [
          { label: 'Awaiting IA', value: 0 },
          { label: 'Completed IA', value: 0 },
          { label: 'Ready for Erasure', value: 0 },
        ],
      },
      {
        key: 'erasure',
        name: 'Erasure',
        target: 140,
        current: 0,
        trend: 0,
        owner: 'Erasure Team',
        queueLabel: 'Data-Bearing Awaiting Erasure',
        subMetrics: [
          { label: 'Roller 1 Queue', value: 0 },
          { label: 'Roller 2 Queue', value: 0 },
          { label: 'Roller 3 Queue', value: 0 },
        ],
      },
      {
        key: 'qa',
        name: 'QA',
        target: 95,
        current: 67,
        trend: -8,
        owner: 'QA Team',
        queueLabel: 'Items Awaiting QA',
        subMetrics: [
          { label: 'DB Awaiting QA', value: 44 },
          { label: 'Non-DB Awaiting QA', value: 23 },
          { label: 'Completed QA Today', value: 71 },
        ],
      },
      {
        key: 'sorting',
        name: 'Sorting',
        target: 110,
        current: 118,
        trend: 5,
        owner: 'Sorting Team',
        queueLabel: 'Items Awaiting Sorting',
        subMetrics: [
          { label: 'Awaiting Sorting', value: 118 },
          { label: 'Sorted This Morning', value: 74 },
          { label: 'QA Output Last Hour', value: 29 },
        ],
      },
    ];

    function trendLabel(value) {
      if (value > 0) return `+${value}%`;
      if (value < 0) return `${value}%`;
      return '0%';
    }

    function clamp(value, min, max) {
      return Math.min(Math.max(value, min), max);
    }

    function asNumber(value) {
      const num = Number(value);
      return Number.isFinite(num) ? num : 0;
    }

    function getSubMetric(section, patterns) {
      const rows = Array.isArray(section.subMetrics) ? section.subMetrics : [];
      for (const row of rows) {
        const label = String(row.label || '').toLowerCase();
        if (patterns.some((p) => p.test(label))) return asNumber(row.value);
      }
      return 0;
    }

    function getDoneCount(section) {
      if (section.key === 'goods_in') {
        return getSubMetric(section, [/booked in today/, /booked and rec/i, /received today/, /^booked in$/]);
      }
      if (section.key === 'ia') {
        return getSubMetric(section, [/completed ia/, /ready for erasure/]);
      }
      if (section.key === 'erasure') {
        return getSubMetric(section, [/erased today/, /processed today/, /completed erasure/]);
      }
      if (section.key === 'qa') {
        return getSubMetric(section, [/completed qa today/, /qa complete/]);
      }
      if (section.key === 'sorting') {
        return getSubMetric(section, [/sorted this morning/, /sorted today/]);
      }
      return 0;
    }

    function getOutstandingCount(section) {
      if (section.key === 'goods_in') {
        return getSubMetric(section, [/total booked in/, /total received \(not booked in\)/, /not booked in/, /awaiting ia/]);
      }
      if (section.key === 'ia') {
        return getSubMetric(section, [/awaiting ia/]);
      }
      if (section.key === 'erasure') {
        return asNumber(section.current);
      }
      if (section.key === 'qa') {
        const db = getSubMetric(section, [/db awaiting qa/]);
        const nonDb = getSubMetric(section, [/non-db awaiting qa/]);
        return db + nonDb || asNumber(section.current);
      }
      if (section.key === 'sorting') {
        return getSubMetric(section, [/awaiting sorting/]) || asNumber(section.current);
      }
      return asNumber(section.current);
    }

    function getCompletionSnapshot(section) {
      const done = Math.max(0, getDoneCount(section));
      const outstanding = Math.max(0, getOutstandingCount(section));
      const total = Math.max(done + outstanding, 1);
      const pct = clamp(Math.round((done / total) * 100), 0, 100);
      return { done, outstanding, total, pct };
    }

    function activityScore(section) {
      const done = getDoneCount(section);
      const queuePenalty = Math.round(asNumber(section.current) * 0.2);
      const trendMod = section.trend < 0 ? Math.abs(section.trend) : Math.round(-section.trend * 0.5);
      return Math.max(0, done + trendMod - queuePenalty);
    }

    function activityText(section) {
      const done = getDoneCount(section);
      if (done > 0) return `${section.name} active with ${done} completed actions.`;
      if (asNumber(section.current) > 0) return `${section.name} has work queued; awaiting completion updates.`;
      return `${section.name} is quiet right now.`;
    }

    function getFallbackSpotlight() {
      return {
        goodsIn: { name: 'Unable to yet', count: 0 },
        ia: { name: 'Unable to yet', count: 0 },
        erasure: { name: '—', count: 0 },
        qa: { name: '—', count: 0 },
        sorting: { name: '—', count: 0 },
      };
    }

    function renderSections(sections) {
      const grid = document.getElementById('overallSectionGrid');
      if (!grid) return;
      grid.innerHTML = sections.map((section) => {
        const trendClass = section.trend > 0 ? 'is-up' : section.trend < 0 ? 'is-down' : 'is-flat';
        const sourceLabel = section.isLive ? 'Live' : 'Mock';
        const sourceClass = section.isLive ? 'live' : 'mock';
        const isAdminViewer = (sessionStorage.getItem('userRole') || 'viewer') === 'admin';
        const queryMsLabel = (isAdminViewer && Number.isFinite(section.queryMs)) ? `${section.queryMs}ms` : '';
        const sourceReason = String(section.sourceReason || '').trim();
        const done = getDoneCount(section);
        let detailRows = '';
        let subMetricClass = 'overall-submetrics';
        if (section.key === 'erasure') {
          const rollers = (section.subMetrics || [])
            .filter((row) => /^Roller\s+\d+\s+Queue$/i.test(row.label))
            .sort((a, b) => {
              const aNum = Number((/^Roller\s+(\d+)/i.exec(a.label) || [])[1] || 0);
              const bNum = Number((/^Roller\s+(\d+)/i.exec(b.label) || [])[1] || 0);
              return aNum - bNum;
            });
          detailRows = `
            <div class="overall-roller-grid">
              ${rollers.map((row) => `<span class="roller-label">${row.label.replace(' Queue', '')}</span>`).join('')}
              ${rollers.map((row) => `<strong class="roller-value">${row.value}</strong>`).join('')}
            </div>
          `;
          subMetricClass = 'overall-submetrics overall-submetrics-erasure';
        } else {
          detailRows = (section.subMetrics || [])
            .map((row) => `
              <div class="overall-submetric-row">
                <span>${row.label}</span>
                <strong>${row.value}</strong>
              </div>
            `)
            .join('');
        }
        return `
          <article class="overall-section-card">
            <div class="overall-card-top">
              <h3>${section.name}</h3>
              <div class="overall-pill-stack">
                <span class="overall-source-pill ${sourceClass}">${sourceLabel}</span>
                ${queryMsLabel ? `<span class="overall-source-pill">${queryMsLabel}</span>` : ''}
              </div>
            </div>
            <div class="overall-metric-row">
              <div class="overall-metric-block">
                <span class="label">Current Queue</span>
                <strong>${section.current}</strong>
              </div>
              <div class="overall-metric-block">
                <span class="label">Done</span>
                <strong>${done}</strong>
              </div>
              <div class="overall-metric-block">
                <span class="label">Trend (1h)</span>
                <strong>${trendLabel(section.trend)}</strong>
              </div>
            </div>
            <div class="overall-queue-label">${section.queueLabel || 'Queue'}</div>
            <div class="${subMetricClass}">${detailRows}</div>
            <div class="overall-metadata-row">
              <span class="owner">${section.owner}</span>
              <span class="trend ${trendClass}">${trendLabel(section.trend)} vs last hour</span>
            </div>
            <p class="overall-action">${activityText(section)}${(isAdminViewer && !section.isLive && sourceReason) ? ` (${sourceReason})` : ''}</p>
          </article>
        `;
      }).join('');
    }

    function renderSummary(sections) {
      const summaryEl = document.getElementById('overallSummaryText');
      const summaryMetaEl = document.getElementById('overallSummaryMeta');
      const bottleneckEl = document.getElementById('overallBottleneck');
      const redCountEl = document.getElementById('overallRedCount');
      const lastUpdateEl = document.getElementById('overallLastUpdate');
      const doneTodayEl = document.getElementById('overallDoneToday');
      const queueTotalEl = document.getElementById('overallQueueTotal');
      const topDoneEl = document.getElementById('overallTopDone');
      const queueLeaderEl = document.getElementById('overallQueueLeader');
      const liveFeedsEl = document.getElementById('overallLiveFeeds');

      const enriched = sections.map((s) => ({ ...s, done: getDoneCount(s) }));
      const activeCount = enriched.filter((s) => s.done > 0).length;
      const queuedTotal = enriched.reduce((sum, s) => sum + asNumber(s.current), 0);
      const doneTotal = enriched.reduce((sum, s) => sum + s.done, 0);
      const bottleneck = enriched.reduce((max, s) => (
        asNumber(s.current) > asNumber(max.current) ? s : max
      ), enriched[0]);
      const topDone = enriched.reduce((max, s) => (s.done > max.done ? s : max), enriched[0]);
      const liveFeeds = enriched.filter((s) => s.isLive).length;

      if (summaryEl) {
        summaryEl.textContent = `${doneTotal} completed actions across ${activeCount}/${enriched.length} active sections today.`;
      }
      if (summaryMetaEl) {
        summaryMetaEl.innerHTML = `
          <span class="overall-summary-chip good">Done Today: ${doneTotal}</span>
          <span class="overall-summary-chip watch">In Queue: ${queuedTotal}</span>
          <span class="overall-summary-chip risk">Active Sections: ${activeCount}</span>
        `;
      }
      if (bottleneckEl) bottleneckEl.textContent = bottleneck ? bottleneck.name : 'None';
      if (redCountEl) redCountEl.textContent = String(activeCount);
      if (lastUpdateEl) lastUpdateEl.textContent = new Date().toLocaleTimeString();
      if (doneTodayEl) doneTodayEl.textContent = String(doneTotal);
      if (queueTotalEl) queueTotalEl.textContent = String(queuedTotal);
      if (topDoneEl) topDoneEl.textContent = topDone ? `${topDone.name} (${topDone.done})` : '—';
      if (queueLeaderEl) queueLeaderEl.textContent = bottleneck ? `${bottleneck.name} (${bottleneck.current})` : '—';
      if (liveFeedsEl) liveFeedsEl.textContent = `${liveFeeds}/${enriched.length}`;
    }

    function renderMissionBoard(sections) {
      const missionEl = document.getElementById('overallMissionBoard');
      if (!missionEl) return;
      const enriched = sections.map((s) => ({ ...s, done: getDoneCount(s) }));
      const doneTotal = enriched.reduce((sum, s) => sum + s.done, 0);
      const queueTotal = enriched.reduce((sum, s) => sum + asNumber(s.current), 0);
      const peak = Math.max(doneTotal, queueTotal, 1);
      const donePct = Math.round((doneTotal / peak) * 100);
      const queuePct = Math.round((queueTotal / peak) * 100);
      const top = [...enriched].sort((a, b) => b.done - a.done)[0];
      const busiest = [...enriched].sort((a, b) => asNumber(b.current) - asNumber(a.current))[0];

      missionEl.innerHTML = `
        <div class="overall-mission-progress">
          <div class="mission-head">
            <span>Live Throughput</span>
            <strong>Done ${doneTotal} / Queue ${queueTotal}</strong>
          </div>
          <div class="mission-track"><div class="mission-fill" style="width:${donePct}%"></div></div>
        </div>
        <div class="mission-objective is-watch">
          Queue load is at ${queuePct}% of today peak volume.
        </div>
        <div class="overall-mission-list">
          <div class="mission-item">
            <span class="mission-label">Most Completed</span>
            <strong class="is-good">${top ? `${top.name} (${top.done})` : '—'}</strong>
          </div>
          <div class="mission-item">
            <span class="mission-label">Largest Queue</span>
            <strong class="is-watch">${busiest ? `${busiest.name} (${busiest.current})` : '—'}</strong>
          </div>
          <div class="mission-item">
            <span class="mission-label">Sections Reporting Done</span>
            <strong class="is-risk">${enriched.filter((s) => s.done > 0).length}</strong>
          </div>
        </div>
        <div class="mission-legend">
          <span><i class="dot good"></i> Completed actions</span>
          <span><i class="dot watch"></i> Current queue load</span>
          <span><i class="dot risk"></i> Active sections</span>
        </div>
      `;
    }

    function renderSpotlight(spotlight) {
      const spotlightEl = document.getElementById('overallSpotlight');
      if (!spotlightEl) return;
      const s = spotlight || getFallbackSpotlight();

      const rows = [
        { section: 'Goods In', name: (s.goodsIn && s.goodsIn.name) || 'Unable to yet', count: (s.goodsIn && s.goodsIn.count) || 0 },
        { section: 'IA', name: (s.ia && s.ia.name) || 'Unable to yet', count: (s.ia && s.ia.count) || 0 },
        { section: 'Erasure', name: (s.erasure && s.erasure.name) || '—', count: (s.erasure && s.erasure.count) || 0 },
        { section: 'QA', name: (s.qa && s.qa.name) || '—', count: (s.qa && s.qa.count) || 0 },
        { section: 'Sorting', name: (s.sorting && s.sorting.name) || '—', count: (s.sorting && s.sorting.count) || 0 },
      ];

      const bestLive = rows
        .filter((r) => r.name !== 'Unable to yet' && r.name !== '—')
        .sort((a, b) => (b.count || 0) - (a.count || 0))[0] || rows[0];

      spotlightEl.innerHTML = `
        <div class="spotlight-main spotlight-main-compact">
          <div class="spotlight-badge">Top Efficiency Right Now</div>
          <div class="spotlight-name">${bestLive.name}</div>
          <div class="spotlight-owner">${bestLive.section}</div>
          <div class="spotlight-score">${bestLive.count} actions today</div>
        </div>
        <div class="spotlight-grid">
          ${rows.map((row) => `
            <div class="spotlight-chip">
              <span class="chip-section">${row.section}</span>
              <strong>${row.name}</strong>
              <span class="chip-score">${row.count}</span>
            </div>
          `).join('')}
        </div>
      `;
    }

    function renderRaceTrack(sections) {
      const raceEl = document.getElementById('overallRaceTrack');
      if (!raceEl) return;
      const MIN_VISIBLE_PROGRESS = 3;

      function getErasureTodayFromDashboard() {
        const el = document.getElementById('totalTodayValue');
        if (!el) return 0;
        const raw = String(el.textContent || '').replace(/,/g, '').trim();
        const parsed = parseInt(raw, 10);
        return Number.isFinite(parsed) ? Math.max(0, parsed) : 0;
      }

      function getRaceTrackDone(section) {
        // Erasure is sourced from the Erasure dashboard donut metric.
        if (section.key === 'erasure') {
          return getErasureTodayFromDashboard();
        }

        // While a section has mock payloads, keep race-track value at zero.
        if (section.isLive !== true) {
          return 0;
        }

        if (section.key === 'qa') {
          return getSubMetric(section, [/completed qa today/, /qa complete/]);
        }
        if (section.key === 'ia') {
          return getSubMetric(section, [/completed ia/, /ready for erasure/]);
        }
        if (section.key === 'sorting') {
          return getSubMetric(section, [/sorted this morning/, /sorted today/]);
        }
        if (section.key === 'goods_in') {
          return getSubMetric(section, [/booked in today/, /^booked in$/]);
        }
        return 0;
      }

      const maxDone = Math.max(...sections.map((s) => getRaceTrackDone(s)), 1);
      const lanes = sections
        .map((s) => ({
          ...s,
          done: getRaceTrackDone(s),
          progress: clamp(Math.round((getRaceTrackDone(s) / maxDone) * 100), 0, 100),
        }))
        .sort((a, b) => b.progress - a.progress);
      const totalDone = lanes.reduce((sum, lane) => sum + lane.done, 0);
      raceEl.innerHTML = `
        <div class="overall-race-meta">
          <span>Completed actions today by section</span>
          <strong>${totalDone}</strong>
        </div>
        <div class="overall-race-lanes">
          ${lanes.map((lane) => {
            const visualProgress = lane.done > 0
              ? Math.max(lane.progress, MIN_VISIBLE_PROGRESS)
              : 0;
            const carLeftPct = clamp(visualProgress, 2, 99);
            return `
              <div class="overall-race-lane">
                <span class="lane-name">${lane.name}</span>
                <div class="lane-track">
                  <div class="lane-fill" style="width:${visualProgress}%"></div>
                  <img class="lane-car" src="assets/F1Car.png" alt="" style="left:calc(${carLeftPct}% - 10px)" />
                </div>
                <span class="lane-value">${lane.done}</span>
              </div>
            `;
          }).join('')}
        </div>
      `;
    }

    function renderTrends(sections) {
      const trendGrid = document.getElementById('overallTrendGrid');
      if (!trendGrid) return;
      trendGrid.innerHTML = sections.map((section) => {
        const snap = getCompletionSnapshot(section);
        return `
          <article class="overall-trend-card">
            <div class="overall-trend-head">
              <span>${section.name}</span>
              <strong>${snap.done}/${snap.total}</strong>
            </div>
            <div class="overall-trend-bar-wrap">
              <div class="overall-trend-bar-bg">
                <div class="overall-trend-bar-fill" style="width:${snap.pct}%"></div>
              </div>
            </div>
            <div class="overall-trend-meta">
              <span>${snap.pct}% completed</span>
              <span>Outstanding ${snap.outstanding}</span>
            </div>
          </article>
        `;
      }).join('');
    }

    function renderChallenge(sections) {
      const challengeEl = document.getElementById('overallChallengeCard');
      if (!challengeEl) return;
      const sorted = sections
        .map((section) => ({
          name: section.name,
          score: activityScore(section),
        }))
        .sort((a, b) => b.score - a.score);
      const leader = sorted[0];
      const second = sorted[1];
      const gap = leader && second ? leader.score - second.score : 0;
      challengeEl.innerHTML = `
        <div class="overall-challenge-main">
          <div class="challenge-title">Section Sprint</div>
          <div class="challenge-leader">${leader ? leader.name : '—'} leads</div>
          <div class="challenge-gap">${leader ? `Ahead by ${gap} pts` : 'Waiting for data'}</div>
        </div>
        <div class="challenge-foot">
          Objective: increase completed actions in the next cycle
        </div>
      `;
    }

    function isValidSection(section) {
      return !!(
        section
        && typeof section.sectionKey === 'string'
        && typeof section.sectionName === 'string'
        && typeof section.targetQueue === 'number'
        && typeof section.currentQueue === 'number'
        && Array.isArray(section.subMetrics)
      );
    }

    function normalizeSection(section) {
      const key = section.sectionKey;
      const subMetrics = Array.isArray(section.subMetrics) ? section.subMetrics : [];
      const normalizedSubMetrics = subMetrics.map((row) => ({
        label: String(row && row.label ? row.label : ''),
        value: row && row.value != null ? row.value : '—',
      }));

      // Keep Goods In wording aligned with what we can actually track.
      if (key === 'goods_in') {
        normalizedSubMetrics.forEach((row) => {
          if (row.label === 'Delivered This Morning') row.label = 'Received Today';
          if (row.label === 'Checked In') row.label = 'Booked In Today';
          if (row.label === 'Awaiting IA') row.label = 'Total Received (Not Booked In)';
        });
      }

      // Always show Roller 1..7 rows for Erasure for stable wallboard layout.
      if (key === 'erasure') {
        const rollerMap = new Map();
        normalizedSubMetrics.forEach((row) => {
          const match = /^Roller\s+(\d+)\s+Queue$/i.exec(row.label);
          if (match) rollerMap.set(Number(match[1]), row.value);
        });
        const rollerRows = [];
        for (let i = 1; i <= 7; i += 1) {
          rollerRows.push({
            label: `Roller ${i} Queue`,
            value: rollerMap.has(i) ? rollerMap.get(i) : '—',
          });
        }
        normalizedSubMetrics.length = 0;
        normalizedSubMetrics.push(...rollerRows);
      }

      return {
        key,
        name: section.sectionName,
        target: section.targetQueue,
        current: section.currentQueue,
        trend: typeof section.trendPctHour === 'number' ? section.trendPctHour : 0,
        owner: section.owner || 'Operations Team',
        queueLabel: section.queueLabel || 'Queue',
        subMetrics: normalizedSubMetrics,
        isLive: section.isLive === true,
        source: section.source || 'mock',
        queryMs: Number.isFinite(Number(section.queryMs)) ? Number(section.queryMs) : null,
        sourceReason: section.sourceReason || '',
      };
    }

    async function load() {
      if (isLoading) return;
      isLoading = true;
      try {
        const [sectionsRes, spotlightRes] = await Promise.all([
          fetch('/overall/sections'),
          fetch('/overall/spotlight').catch(() => null),
        ]);
        if (!sectionsRes.ok) throw new Error(`HTTP ${sectionsRes.status}`);
        const payload = await sectionsRes.json();
        const sections = Array.isArray(payload.sections) ? payload.sections : [];
        const valid = sections.filter(isValidSection).map(normalizeSection);
        if (!valid.length) throw new Error('No valid sections returned');

        let spotlightData = getFallbackSpotlight();
        if (spotlightRes && spotlightRes.ok) {
          const spotlightPayload = await spotlightRes.json();
          spotlightData = {
            goodsIn: spotlightPayload.goodsIn || { name: 'Unable to yet', count: 0 },
            ia: spotlightPayload.ia || { name: 'Unable to yet', count: 0 },
            erasure: spotlightPayload.erasure || { name: '—', count: 0 },
            qa: spotlightPayload.qa || { name: '—', count: 0 },
            sorting: spotlightPayload.sorting || { name: '—', count: 0 },
          };
        }

        renderSections(valid);
        renderSpotlight(spotlightData);
        renderTrends(valid);
        renderRaceTrack(valid);
      } catch (_err) {
        renderSections(mockSections);
        renderSpotlight(getFallbackSpotlight());
        renderTrends(mockSections);
        renderRaceTrack(mockSections);
      } finally {
        isLoading = false;
      }
    }

    return {
      load,
    };
  }

  window.OverallStatsDashboard = {
    init,
  };
})();

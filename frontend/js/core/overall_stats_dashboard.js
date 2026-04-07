// Overall stats dashboard with mock operational data for staffing huddles.
(function () {
  function init() {
    const mockSections = [
      {
        key: 'goods_in',
        name: 'Goods In',
        target: 90,
        current: 128,
        trend: 14,
        owner: 'Inbound Team',
        queueLabel: 'Totes Delivered',
        subMetrics: [
          { label: 'Delivered This Morning', value: 128 },
          { label: 'Checked In', value: 92 },
          { label: 'Awaiting IA', value: 36 },
        ],
      },
      {
        key: 'ia',
        name: 'IA',
        target: 72,
        current: 81,
        trend: 6,
        owner: 'Assessment Team',
        queueLabel: 'Totes Awaiting IA',
        subMetrics: [
          { label: 'Awaiting IA', value: 81 },
          { label: 'Completed IA', value: 59 },
          { label: 'Ready for Erasure', value: 43 },
        ],
      },
      {
        key: 'erasure',
        name: 'Erasure',
        target: 140,
        current: 136,
        trend: -4,
        owner: 'Erasure Team',
        queueLabel: 'Data-Bearing Awaiting Erasure',
        subMetrics: [
          { label: 'Roller 1 Queue', value: 46 },
          { label: 'Roller 2 Queue', value: 39 },
          { label: 'Roller 3 Queue', value: 51 },
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

    function getStatus(current, target) {
      const ratio = target > 0 ? current / target : 0;
      if (ratio <= 1.0) return { key: 'green', label: 'Healthy' };
      if (ratio <= 1.2) return { key: 'amber', label: 'Watch' };
      return { key: 'red', label: 'Struggling' };
    }

    function trendLabel(value) {
      if (value > 0) return `+${value}%`;
      if (value < 0) return `${value}%`;
      return '0%';
    }

    function recommendation(section, statusKey) {
      if (statusKey === 'red') {
        return `Move 1-2 staff to ${section.name} immediately.`;
      }
      if (statusKey === 'amber') {
        return `Monitor ${section.name}; prep cover if trend worsens.`;
      }
      return `${section.name} stable; can lend support if needed.`;
    }

    function clamp(value, min, max) {
      return Math.min(Math.max(value, min), max);
    }

    function progressToTarget(section) {
      if (!section.target || section.target <= 0) return 0;
      const raw = (section.target / Math.max(section.current, 1)) * 100;
      return clamp(Math.round(raw), 0, 100);
    }

    function efficiencyScore(section) {
      const base = progressToTarget(section);
      const trendPenalty = section.trend > 0 ? section.trend : 0;
      const trendBonus = section.trend < 0 ? Math.abs(section.trend) * 1.5 : 0;
      return Math.round(base - trendPenalty + trendBonus);
    }

    function renderSections(sections) {
      const grid = document.getElementById('overallSectionGrid');
      if (!grid) return;
      grid.innerHTML = sections.map((section) => {
        const status = getStatus(section.current, section.target);
        const gap = section.current - section.target;
        const trendClass = section.trend > 0 ? 'is-up' : section.trend < 0 ? 'is-down' : 'is-flat';
        const sourceLabel = section.isLive ? 'Live' : 'Mock';
        const sourceClass = section.isLive ? 'live' : 'mock';
        const detailRows = (section.subMetrics || [])
          .map((row) => `
            <div class="overall-submetric-row">
              <span>${row.label}</span>
              <strong>${row.value}</strong>
            </div>
          `)
          .join('');
        return `
          <article class="overall-section-card status-${status.key}">
            <div class="overall-card-top">
              <h3>${section.name}</h3>
              <div class="overall-pill-stack">
                <span class="overall-source-pill ${sourceClass}">${sourceLabel}</span>
                <span class="overall-status-pill ${status.key}">${status.label}</span>
              </div>
            </div>
            <div class="overall-metric-row">
              <div class="overall-metric-block">
                <span class="label">Current Queue</span>
                <strong>${section.current}</strong>
              </div>
              <div class="overall-metric-block">
                <span class="label">Target Queue</span>
                <strong>${section.target}</strong>
              </div>
              <div class="overall-metric-block">
                <span class="label">Gap</span>
                <strong>${gap >= 0 ? '+' : ''}${gap}</strong>
              </div>
            </div>
            <div class="overall-queue-label">${section.queueLabel || 'Queue'}</div>
            <div class="overall-submetrics">${detailRows}</div>
            <div class="overall-metadata-row">
              <span class="owner">${section.owner}</span>
              <span class="trend ${trendClass}">${trendLabel(section.trend)} vs last hour</span>
            </div>
            <p class="overall-action">${recommendation(section, status.key)}</p>
          </article>
        `;
      }).join('');
    }

    function renderSummary(sections) {
      const summaryEl = document.getElementById('overallSummaryText');
      const bottleneckEl = document.getElementById('overallBottleneck');
      const redCountEl = document.getElementById('overallRedCount');
      const lastUpdateEl = document.getElementById('overallLastUpdate');

      const withStatus = sections.map((s) => ({ ...s, status: getStatus(s.current, s.target) }));
      const red = withStatus.filter((s) => s.status.key === 'red');
      const bottleneck = withStatus.reduce((max, s) => {
        const ratio = s.target > 0 ? s.current / s.target : 0;
        const maxRatio = max.target > 0 ? max.current / max.target : 0;
        return ratio > maxRatio ? s : max;
      }, withStatus[0]);

      if (summaryEl) {
        summaryEl.textContent = red.length > 0
          ? `Focus today: clear red sections before 11:00.`
          : 'No critical bottlenecks right now.';
      }
      if (bottleneckEl) bottleneckEl.textContent = bottleneck ? bottleneck.name : 'None';
      if (redCountEl) redCountEl.textContent = String(red.length);
      if (lastUpdateEl) lastUpdateEl.textContent = new Date().toLocaleTimeString();
    }

    function renderMissionBoard(sections) {
      const missionEl = document.getElementById('overallMissionBoard');
      if (!missionEl) return;

      const statuses = sections.map((s) => ({ ...s, status: getStatus(s.current, s.target) }));
      const healthyCount = statuses.filter((s) => s.status.key === 'green').length;
      const watchCount = statuses.filter((s) => s.status.key === 'amber').length;
      const strugglingCount = statuses.filter((s) => s.status.key === 'red').length;
      const healthPct = Math.round((healthyCount / Math.max(statuses.length, 1)) * 100);

      missionEl.innerHTML = `
        <div class="overall-mission-progress">
          <div class="mission-head">
            <span>Shift Objective</span>
            <strong>${healthyCount}/${statuses.length} sections healthy</strong>
          </div>
          <div class="mission-track"><div class="mission-fill" style="width:${healthPct}%"></div></div>
        </div>
        <div class="overall-mission-list">
          <div class="mission-item">
            <span class="mission-label">Healthy</span>
            <strong class="is-good">${healthyCount}</strong>
          </div>
          <div class="mission-item">
            <span class="mission-label">Watch</span>
            <strong class="is-watch">${watchCount}</strong>
          </div>
          <div class="mission-item">
            <span class="mission-label">Struggling</span>
            <strong class="is-risk">${strugglingCount}</strong>
          </div>
        </div>
      `;
    }

    function renderSpotlight(sections) {
      const spotlightEl = document.getElementById('overallSpotlight');
      if (!spotlightEl) return;
      const ranked = sections
        .map((s) => ({ ...s, score: efficiencyScore(s) }))
        .sort((a, b) => b.score - a.score);
      const winner = ranked[0];
      const runnerUp = ranked[1];
      if (!winner) {
        spotlightEl.innerHTML = '<p class="overall-empty">Waiting for section data...</p>';
        return;
      }

      spotlightEl.innerHTML = `
        <div class="spotlight-main">
          <div class="spotlight-badge">Most Efficient Section</div>
          <div class="spotlight-name">${winner.name}</div>
          <div class="spotlight-owner">${winner.owner}</div>
          <div class="spotlight-score">Efficiency Score ${winner.score}</div>
        </div>
        ${runnerUp ? `
          <div class="spotlight-runner">
            Next up: <strong>${runnerUp.name}</strong> (${runnerUp.score})
          </div>
        ` : ''}
      `;
    }

    function renderRaceTrack(sections) {
      const raceEl = document.getElementById('overallRaceTrack');
      if (!raceEl) return;
      const lanes = sections
        .map((s) => ({ ...s, progress: progressToTarget(s) }))
        .sort((a, b) => b.progress - a.progress);
      raceEl.innerHTML = lanes.map((lane) => `
        <div class="overall-race-lane">
          <span class="lane-name">${lane.name}</span>
          <div class="lane-track">
            <div class="lane-fill" style="width:${lane.progress}%"></div>
          </div>
          <span class="lane-value">${lane.progress}%</span>
        </div>
      `).join('');
    }

    function renderTrends(sections) {
      const trendGrid = document.getElementById('overallTrendGrid');
      if (!trendGrid) return;
      trendGrid.innerHTML = sections.map((section) => {
        const ratioRaw = section.target > 0 ? (section.current / section.target) * 100 : 0;
        const ratio = clamp(Math.round(ratioRaw), 0, 160);
        const fill = Math.min(ratio, 100);
        const status = getStatus(section.current, section.target).key;
        const gap = section.current - section.target;
        return `
          <article class="card overall-trend-card status-${status}">
            <div class="overall-trend-head">
              <span>${section.name}</span>
              <strong>${section.current}/${section.target}</strong>
            </div>
            <div class="overall-trend-bar-wrap">
              <div class="overall-trend-bar-bg">
                <div class="overall-trend-bar-fill" style="width:${fill}%"></div>
              </div>
              ${ratio > 100 ? `<div class="overall-trend-overflow" style="width:${Math.min(ratio - 100, 60)}%"></div>` : ''}
            </div>
            <div class="overall-trend-meta">
              <span>${ratio}% of target</span>
              <span class="${gap > 0 ? 'is-risk' : gap < 0 ? 'is-good' : ''}">Gap ${gap >= 0 ? '+' : ''}${gap}</span>
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
          score: efficiencyScore(section),
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
          Objective: keep 4+ sections healthy for 20 mins
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
      return {
        key: section.sectionKey,
        name: section.sectionName,
        target: section.targetQueue,
        current: section.currentQueue,
        trend: typeof section.trendPctHour === 'number' ? section.trendPctHour : 0,
        owner: section.owner || 'Operations Team',
        queueLabel: section.queueLabel || 'Queue',
        subMetrics: section.subMetrics || [],
        isLive: section.isLive === true,
        source: section.source || 'mock',
      };
    }

    async function load() {
      try {
        const res = await fetch('/overall/sections');
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const payload = await res.json();
        const sections = Array.isArray(payload.sections) ? payload.sections : [];
        const valid = sections.filter(isValidSection).map(normalizeSection);
        if (!valid.length) throw new Error('No valid sections returned');
        renderSections(valid);
        renderSummary(valid);
        renderMissionBoard(valid);
        renderSpotlight(valid);
        renderTrends(valid);
        renderRaceTrack(valid);
        renderChallenge(valid);
      } catch (_err) {
        renderSections(mockSections);
        renderSummary(mockSections);
        renderMissionBoard(mockSections);
        renderSpotlight(mockSections);
        renderTrends(mockSections);
        renderRaceTrack(mockSections);
        renderChallenge(mockSections);
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

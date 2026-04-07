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
      const talkPointsEl = document.getElementById('overallTalkPoints');

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

      if (talkPointsEl) {
        const points = [];
        if (red.length) {
          points.push(`Immediate support: ${red.map((r) => r.name).join(', ')}`);
        }
        points.push(`Largest pressure: ${bottleneck.name} (+${bottleneck.current - bottleneck.target})`);
        points.push('Recheck in 45 mins after reassignment.');
        talkPointsEl.innerHTML = points.map((p) => `<li>${p}</li>`).join('');
      }
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
      } catch (_err) {
        renderSections(mockSections);
        renderSummary(mockSections);
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

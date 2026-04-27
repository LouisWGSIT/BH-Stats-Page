// QA card list and name formatting renderer extracted from qa_dashboard.js.
(function () {
  function init(deps) {
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

    function renderEngineersList(listEl, rows, countKey) {
      if (!listEl) return;
      if (!rows.length) {
        listEl.innerHTML = '<div style="padding: 12px; text-align: center; color: #888;">No data</div>';
        return;
      }

      const maxValue = rows.reduce((max, eng) => {
        const val = Number(eng[countKey] || 0);
        return val > max ? val : max;
      }, 0) || 1;

      listEl.innerHTML = rows.map((eng, index) => {
        const displayName = formatQaName(eng.name);
        const avatarKey = eng.name || displayName || 'QA';
        const avatar = deps.getAvatarDataUri(avatarKey);
        const value = Number(eng[countKey] || 0);
        const widthPct = Math.max(6, Math.round((value / maxValue) * 100));
        return `
          <div class="qa-engineer-item">
            <div class="qa-engineer-left">
              <span class="qa-engineer-rank">${index + 1}</span>
              <span class="qa-engineer-avatar" style="background-image: url(${avatar})"></span>
              <span class="qa-engineer-name">${deps.escapeHtml(displayName)}</span>
            </div>
            <span class="qa-engineer-count">${value.toLocaleString()}</span>
            <span class="qa-engineer-meter"><span class="qa-engineer-meter-fill" style="width:${widthPct}%"></span></span>
          </div>
        `;
      }).join('');
    }

    function populateQACard(totalId, listId, data, type, maxItems) {
      const totalEl = document.getElementById(totalId);
      const listEl = document.getElementById(listId);

      let total = 0;
      let engineers = [];

      if (type === 'qa') {
        total = (data.summary.deQaScans || 0) + (data.summary.nonDeQaScans || 0);
        engineers = (data.technicians || [])
          .filter((tech) => ((tech.deQaScans || 0) + (tech.nonDeQaScans || 0)) > 0)
          .map((tech) => ({
            name: tech.name,
            count: (tech.deQaScans || 0) + (tech.nonDeQaScans || 0),
          }))
          .sort((a, b) => b.count - a.count)
          .slice(0, maxItems);
      } else if (type === 'de') {
        total = data.summary.deQaScans || 0;
        engineers = (data.technicians || [])
          .filter((tech) => (tech.deQaScans || 0) > 0)
          .map((tech) => ({
            name: tech.name,
            count: tech.deQaScans || 0,
          }))
          .sort((a, b) => b.count - a.count)
          .slice(0, maxItems);
      } else if (type === 'non_de') {
        total = data.summary.nonDeQaScans || 0;
        engineers = (data.technicians || [])
          .filter((tech) => (tech.nonDeQaScans || 0) > 0)
          .map((tech) => ({
            name: tech.name,
            count: tech.nonDeQaScans || 0,
          }))
          .sort((a, b) => b.count - a.count)
          .slice(0, maxItems);
      }

      if (totalEl) {
        totalEl.textContent = total.toLocaleString();
      }

      renderEngineersList(listEl, engineers, 'count');
    }

    function populateQAAppCard(totalId, listId, data, maxItems) {
      const totalEl = document.getElementById(totalId);
      const listEl = document.getElementById(listId);

      const qaTotal = data.summary.totalScans || 0;
      if (totalEl) {
        totalEl.textContent = qaTotal.toLocaleString();
      }

      const qaEngineers = (data.technicians || [])
        .filter((tech) => (tech.qaScans || 0) > 0)
        .filter((tech) => (tech.name || '').toLowerCase() !== '(unassigned)')
        .map((tech) => ({
          name: tech.name,
          qaScans: tech.qaScans || 0,
        }))
        .sort((a, b) => b.qaScans - a.qaScans)
        .slice(0, maxItems);

      renderEngineersList(listEl, qaEngineers, 'qaScans');
    }

    return {
      populateQACard,
      populateQAAppCard,
    };
  }

  window.QACardsRenderer = {
    init,
  };
})();

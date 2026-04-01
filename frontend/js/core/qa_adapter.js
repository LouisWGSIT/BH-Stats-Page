// QA dashboard adapter extracted from app.js.
(function () {
  function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  function init(deps) {
    const qaDashboardApi = (window.QADashboard && typeof window.QADashboard.init === 'function')
      ? window.QADashboard.init({
          escapeHtml,
          getAvatarDataUri: deps.getAvatarDataUri,
          renderSVGSparkline: deps.renderSVGSparkline,
        })
      : null;

    async function load(period) {
      if (!qaDashboardApi || typeof qaDashboardApi.load !== 'function') return;
      return qaDashboardApi.load(period || 'this_week');
    }

    return { load, escapeHtml };
  }

  window.QaAdapter = {
    init,
  };
})();

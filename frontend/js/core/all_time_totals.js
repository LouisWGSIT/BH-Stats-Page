// All-time totals refresh extracted from app.js.
(function () {
  function init(deps) {
    async function refreshAllTimeTotals() {
      try {
        const res = await fetch('/metrics/all-time-totals');
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const data = await res.json();
        const allTime = data.allTimeTotal || 0;
        const allTimeEl = document.getElementById('allTimeValue');
        if (allTimeEl) {
          allTimeEl.textContent = allTime;
          deps.animateNumberUpdate('allTimeValue');
        }
      } catch (err) {
        console.error('All Time totals fetch error:', err);
      }
    }

    return {
      refreshAllTimeTotals,
    };
  }

  window.AllTimeTotals = {
    init,
  };
})();

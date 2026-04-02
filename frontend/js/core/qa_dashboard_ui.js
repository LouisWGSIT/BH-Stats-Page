// QA dashboard UI helpers extracted from qa_dashboard.js.
(function () {
  function init() {
    let qaTopFlipIntervalId = null;

    function stop() {
      if (qaTopFlipIntervalId) {
        clearInterval(qaTopFlipIntervalId);
        qaTopFlipIntervalId = null;
      }
    }

    function startQATopFlipRotation() {
      const cards = document.querySelectorAll('.qa-top-flip-card');
      if (!cards.length) return;

      let flipped = false;
      cards.forEach((card) => card.classList.remove('flipped'));

      stop();
      qaTopFlipIntervalId = setInterval(() => {
        flipped = !flipped;
        cards.forEach((card) => card.classList.toggle('flipped', flipped));
      }, 35000);
    }

    function showQAError(message) {
      const deWeeklyEngineers = document.getElementById('deWeeklyEngineers');
      const deAllTimeEngineers = document.getElementById('deAllTimeEngineers');
      const qaWeeklyEngineers = document.getElementById('qaWeeklyEngineers');
      const qaAllTimeEngineers = document.getElementById('qaAllTimeEngineers');

      const errorHtml = `
        <div style="padding: 20px; text-align: center; color: #ff6b6b;">
          <div style="font-size: 14px; font-weight: 600;">⚠️ ${message}</div>
        </div>
      `;

      if (deWeeklyEngineers) deWeeklyEngineers.innerHTML = errorHtml;
      if (deAllTimeEngineers) deAllTimeEngineers.innerHTML = errorHtml;
      if (qaWeeklyEngineers) qaWeeklyEngineers.innerHTML = errorHtml;
      if (qaAllTimeEngineers) qaAllTimeEngineers.innerHTML = errorHtml;
    }

    return {
      startQATopFlipRotation,
      showQAError,
      stop,
    };
  }

  window.QADashboardUI = {
    init,
  };
})();

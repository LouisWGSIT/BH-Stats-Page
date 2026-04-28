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

    function lockQATopCardsToCharts() {
      const cards = document.querySelectorAll('.qa-top-flip-card');
      if (!cards.length) return;
      stop();
      cards.forEach((card) => card.classList.add('flipped'));
    }

    function showQAError(message) {
      const qaTodayEngineers = document.getElementById('qaTodayEngineers');
      const qaWeeklyEngineers = document.getElementById('qaWeeklyEngineers');
      const qaAllTimeEngineers = document.getElementById('qaAllTimeEngineers');
      const qaAppRotatingEngineers = document.getElementById('qaAppRotatingEngineers');
      const qaTopMovers = document.getElementById('qaTopMovers');
      const qaThroughputTimeline = document.getElementById('qaThroughputTimeline');

      const errorHtml = `
        <div style="padding: 20px; text-align: center; color: #ff6b6b;">
          <div style="font-size: 14px; font-weight: 600;">⚠️ ${message}</div>
        </div>
      `;

      if (qaTodayEngineers) qaTodayEngineers.innerHTML = errorHtml;
      if (qaWeeklyEngineers) qaWeeklyEngineers.innerHTML = errorHtml;
      if (qaAllTimeEngineers) qaAllTimeEngineers.innerHTML = errorHtml;
      if (qaAppRotatingEngineers) qaAppRotatingEngineers.innerHTML = errorHtml;
      if (qaTopMovers) qaTopMovers.innerHTML = errorHtml;
      if (qaThroughputTimeline) qaThroughputTimeline.innerHTML = errorHtml;
    }

    return {
      startQATopFlipRotation,
      lockQATopCardsToCharts,
      showQAError,
      stop,
    };
  }

  window.QADashboardUI = {
    init,
  };
})();

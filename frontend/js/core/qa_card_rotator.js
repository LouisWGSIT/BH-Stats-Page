// QA DE/non-DE card rotator extracted from qa_dashboard.js.
(function () {
  function init(deps) {
    let qaRotatorIntervalId = null;

    function stop() {
      if (qaRotatorIntervalId) {
        clearInterval(qaRotatorIntervalId);
        qaRotatorIntervalId = null;
      }
    }

    function startQARotator(todayData, weeklyData, allTimeData) {
      const datasets = [
        { data: todayData, label: "Today's" },
        { data: weeklyData, label: "This Week's" },
        { data: allTimeData, label: 'All Time' },
      ];

      let currentIndex = 0;

      function updateRotatingCards() {
        const current = datasets[currentIndex];

        const dataBearingCard = document.querySelector('#dataBeringToday')?.closest('.qa-de-card');
        const nonDataBearingCard = document.querySelector('#nonDataBeringToday')?.closest('.qa-de-card');

        if (dataBearingCard) {
          dataBearingCard.classList.add('flipping');
          setTimeout(() => dataBearingCard.classList.remove('flipping'), 600);
        }
        if (nonDataBearingCard) {
          nonDataBearingCard.classList.add('flipping');
          setTimeout(() => nonDataBearingCard.classList.remove('flipping'), 600);
        }

        const colorClasses = ['qa-card-today', 'qa-card-week', 'qa-card-alltime'];
        if (dataBearingCard) {
          colorClasses.forEach((cls) => dataBearingCard.classList.remove(cls));
        }
        if (nonDataBearingCard) {
          colorClasses.forEach((cls) => nonDataBearingCard.classList.remove(cls));
        }

        let colorClass = '';
        if (current.label === "Today's") {
          colorClass = 'qa-card-today';
        } else if (current.label === "This Week's") {
          colorClass = 'qa-card-week';
        } else if (current.label === 'All Time') {
          colorClass = 'qa-card-alltime';
        }

        if (dataBearingCard && colorClass) {
          dataBearingCard.classList.add(colorClass);
          if (!dataBearingCard.classList.contains('qa-card-data-bearing')) {
            dataBearingCard.classList.add('qa-card-data-bearing');
          }
        }

        if (nonDataBearingCard && colorClass) {
          nonDataBearingCard.classList.add(colorClass);
          if (!nonDataBearingCard.classList.contains('qa-card-non-data-bearing')) {
            nonDataBearingCard.classList.add('qa-card-non-data-bearing');
          }
        }

        const dataBearingTitle = dataBearingCard?.querySelector('h3');
        if (dataBearingTitle) {
          dataBearingTitle.textContent = `${current.label} Data Bearing`;
        }
        deps.populateQACard('dataBeringToday', 'dataBeringTodayEngineers', current.data, 'de', 4);

        const nonDataBearingTitle = nonDataBearingCard?.querySelector('h3');
        if (nonDataBearingTitle) {
          nonDataBearingTitle.textContent = `${current.label} Non Data Bearing`;
        }
        deps.populateQACard('nonDataBeringToday', 'nonDataBeringTodayEngineers', current.data, 'non_de', 4);

        currentIndex = (currentIndex + 1) % datasets.length;
      }

      updateRotatingCards();
      stop();
      qaRotatorIntervalId = setInterval(updateRotatingCards, 30000);
    }

    return {
      startQARotator,
      stop,
    };
  }

  window.QACardRotator = {
    init,
  };
})();

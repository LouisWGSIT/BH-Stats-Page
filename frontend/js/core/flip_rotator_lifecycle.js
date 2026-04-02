// Flip/rotator timer lifecycle extracted from app.js.
(function () {
  function init() {
    const flipIntervals = new Map();
    const flipTimeouts = new Map();
    const rotatorIntervals = new Map();
    const rotatorTimeouts = new Map();

    function cleanupFlipCards() {
      flipIntervals.forEach((id) => clearInterval(id));
      flipTimeouts.forEach((t) => {
        if (Array.isArray(t)) {
          t.forEach((x) => clearTimeout(x));
        } else {
          clearTimeout(t);
        }
      });
      flipIntervals.clear();
      flipTimeouts.clear();
      const flipCards = document.querySelectorAll('.flip-card');
      flipCards.forEach((card) => {
        card.classList.remove('flipped', 'about-to-flip');
      });
    }

    function setupFlipCards() {
      cleanupFlipCards();
      const flipCards = document.querySelectorAll('.flip-card');
      if (flipCards.length === 0) return;

      const FLIP_INTERVAL = 60000;
      const FLIP_HOLD = 20000;
      const PRE_FLIP_INDICATOR_TIME = 500;

      flipCards.forEach((card, index) => {
        const inner = card.querySelector('.flip-card-inner');
        let isFlipping = false;

        function performFlip() {
          if (isFlipping) return;
          card.classList.add('about-to-flip');
          setTimeout(() => {
            card.classList.remove('about-to-flip');
            isFlipping = true;
            card.classList.toggle('flipped');
          }, PRE_FLIP_INDICATOR_TIME);
        }

        if (inner) {
          inner.addEventListener('transitionend', (e) => {
            if (e.propertyName === 'transform') {
              isFlipping = false;
            }
          });
        }

        const startTimeout = setTimeout(() => {
          performFlip();
          const holdTimeout = setTimeout(() => {
            performFlip();
          }, FLIP_HOLD);

          const recurringSetupTimeout = setTimeout(() => {
            const intervalId = setInterval(() => {
              performFlip();
              setTimeout(performFlip, FLIP_HOLD);
            }, FLIP_INTERVAL);
            flipIntervals.set(index, intervalId);
          }, FLIP_HOLD);

          flipTimeouts.set(index, [startTimeout, holdTimeout, recurringSetupTimeout]);
        }, 2000 + index * 300);
        if (!flipTimeouts.has(index)) flipTimeouts.set(index, startTimeout);
      });
    }

    function cleanupRotatorCards() {
      rotatorIntervals.forEach((id) => clearInterval(id));
      rotatorTimeouts.forEach((id) => clearTimeout(id));
      rotatorIntervals.clear();
      rotatorTimeouts.clear();
    }

    function setupRotatorCards() {
      const cards = document.querySelectorAll('.rotator-card');
      if (!cards.length) return;
      cleanupRotatorCards();

      cards.forEach((card, cardIdx) => {
        if (rotatorIntervals.has(cardIdx)) {
          clearInterval(rotatorIntervals.get(cardIdx));
          rotatorIntervals.delete(cardIdx);
        }
        if (rotatorTimeouts.has(cardIdx)) {
          clearTimeout(rotatorTimeouts.get(cardIdx));
          rotatorTimeouts.delete(cardIdx);
        }

        const panels = Array.from(card.querySelectorAll('.panel'));
        if (panels.length <= 1) return;

        panels.forEach((panel) => {
          panel.classList.remove('active', 'entering', 'exiting', 'about-to-rotate');
        });

        let index = 0;
        let isTransitioning = false;
        const interval = parseInt(card.dataset.interval, 10) || 14000;
        const PRE_ROTATE_INDICATOR_TIME = 400;

        function showPanel(nextIndex) {
          if (isTransitioning) {
            console.warn('Rotator card transition already in progress, skipping');
            return;
          }

          const currentIndex = panels.findIndex((p) => p.classList.contains('active'));
          if (currentIndex === -1) {
            panels.forEach((panel) => panel.classList.remove('active', 'entering', 'exiting', 'about-to-rotate'));
            panels[nextIndex].classList.add('active');
            return;
          }

          panels[currentIndex].classList.add('about-to-rotate');

          setTimeout(() => {
            isTransitioning = true;

            panels.forEach((panel) => {
              panel.classList.remove('entering', 'exiting', 'about-to-rotate');
            });

            panels[currentIndex].classList.remove('active');
            panels[currentIndex].classList.add('exiting');

            const nextPanel = panels[nextIndex];
            nextPanel.classList.add('entering');
            nextPanel.classList.add('active');

            void nextPanel.offsetHeight;

            setTimeout(() => {
              panels[currentIndex].classList.remove('exiting');
              nextPanel.classList.remove('entering');
              isTransitioning = false;
            }, 1200);

            setTimeout(() => {
              if (isTransitioning) {
                console.warn('Rotator card transition took too long, resetting');
                isTransitioning = false;
              }
            }, 3000);
          }, PRE_ROTATE_INDICATOR_TIME);
        }

        showPanel(index);

        const startTimeout = setTimeout(() => {
          const intervalId = setInterval(() => {
            index = (index + 1) % panels.length;
            showPanel(index);
          }, interval);
          rotatorIntervals.set(cardIdx, intervalId);
        }, 3000);
        rotatorTimeouts.set(cardIdx, startTimeout);
      });
    }

    return {
      cleanupFlipCards,
      setupFlipCards,
      cleanupRotatorCards,
      setupRotatorCards,
    };
  }

  window.FlipRotatorLifecycle = {
    init,
  };
})();

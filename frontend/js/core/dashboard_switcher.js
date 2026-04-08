// Dashboard view switching and QA refresh lifecycle.
(function () {
  function createApi(deps) {
    const {
      loadQADashboard,
      loadOverallDashboard,
      setCurrentDashboard,
      getCurrentDashboard,
      onDashboardWillChange,
      onDashboardChanged,
    } = deps;

    let dashboardLocked = false;
    const dashboards = ['erasure', 'qa', 'overall'];
    const dashboardTitles = {
      erasure: 'Erasure Stats',
      qa: 'QA Stats',
      overall: 'Overall Stats',
    };

    function currentDashboard() {
      if (typeof getCurrentDashboard === 'function') {
        return getCurrentDashboard();
      }
      return 0;
    }

    function setDashboard(index) {
      if (typeof setCurrentDashboard === 'function') {
        setCurrentDashboard(index);
      }
    }

    function getDashboardIndexFromHash() {
      const raw = String(window.location.hash || '').replace('#', '').trim().toLowerCase();
      if (!raw) return null;
      const idx = dashboards.indexOf(raw);
      return idx >= 0 ? idx : null;
    }

    function persistDashboardInUrl(dashboardKey) {
      try {
        const url = new URL(window.location.href);
        url.hash = dashboardKey;
        window.history.replaceState({}, '', url.toString());
      } catch (_err) {
        // No-op if URL APIs are unavailable.
      }
    }

    function switchDashboard(index, opts = {}) {
      const erasureView = document.getElementById('erasureStatsView');
      const qaView = document.getElementById('qaStatsView');
      const overallView = document.getElementById('overallStatsView');
      const titleElem = document.getElementById('dashboardTitle');
      const isInitialRestore = !!opts.isInitialRestore;

      if (index < 0 || index >= dashboards.length) {
        return;
      }

      const previousIndex = currentDashboard();
      if (typeof onDashboardWillChange === 'function') {
        onDashboardWillChange(previousIndex, index);
      }

      setDashboard(index);
      const dashboard = dashboards[index];

      function applyViewState(view, isActive, displayMode) {
        if (!view) return;
        view.classList.toggle('is-active', isActive);
        view.hidden = !isActive;
        view.setAttribute('aria-hidden', isActive ? 'false' : 'true');
        view.style.display = isActive ? displayMode : 'none';
      }

      if (dashboard === 'erasure') {
        applyViewState(erasureView, true, 'flex');
        applyViewState(qaView, false, 'none');
        applyViewState(overallView, false, 'none');
        if (titleElem) titleElem.textContent = dashboardTitles.erasure;
      } else if (dashboard === 'qa') {
        applyViewState(erasureView, false, 'none');
        applyViewState(qaView, true, 'flex');
        applyViewState(overallView, false, 'none');

        if (titleElem) titleElem.textContent = dashboardTitles.qa;
        const performersGrid = document.getElementById('qaTopPerformersGrid');
        const techniciansGrid = document.getElementById('qaTechniciansGrid');
        if (performersGrid) {
          performersGrid.innerHTML = '<div style="grid-column: 1 / -1; padding: 24px; text-align: center; color: #999;">Loading QA data...</div>';
        }
        if (techniciansGrid) {
          techniciansGrid.innerHTML = '';
        }

        const periodValue = document.getElementById('dateSelector')?.value || 'this-week';
        const period = periodValue.replace(/-/g, '_');

        if (!isInitialRestore) {
          if (typeof loadQADashboard === 'function') {
            loadQADashboard(period);
          }
        } else {
          if (performersGrid) {
            performersGrid.innerHTML = '<div style="grid-column: 1 / -1; padding: 24px; text-align: center; color: #999;">QA data deferred - click to load</div>';
          }
          const qaViewEl = qaView;
          const oneTimeLoad = () => {
            qaViewEl.removeEventListener('click', oneTimeLoad);
            if (typeof loadQADashboard === 'function') {
              loadQADashboard(period);
            }
          };
          qaViewEl.addEventListener('click', oneTimeLoad);
        }
      } else if (dashboard === 'overall') {
        applyViewState(erasureView, false, 'none');
        applyViewState(qaView, false, 'none');
        applyViewState(overallView, true, 'flex');

        if (titleElem) titleElem.textContent = dashboardTitles.overall;
        if (typeof loadOverallDashboard === 'function') {
          loadOverallDashboard();
        }
      }

      localStorage.setItem('currentDashboard', index);
      persistDashboardInUrl(dashboard);

      if (typeof onDashboardChanged === 'function') {
        onDashboardChanged(previousIndex, index);
      }
    }

    function lockDashboard() {
      dashboardLocked = true;
      localStorage.setItem('dashboardLocked', 'true');
      console.log('Dashboard locked to', dashboards[currentDashboard()]);
    }

    function unlockDashboard() {
      dashboardLocked = false;
      localStorage.removeItem('dashboardLocked');
      console.log('Dashboard unlocked');
    }

    function bindControls() {
      const prevBtn = document.getElementById('prevDashboard');
      const nextBtn = document.getElementById('nextDashboard');

      if (prevBtn) {
        prevBtn.addEventListener('click', () => {
          if (dashboardLocked) return;
          let newIndex = currentDashboard() - 1;
          if (newIndex < 0) {
            newIndex = dashboards.length - 1;
          }
          switchDashboard(newIndex);
        });
      }

      if (nextBtn) {
        nextBtn.addEventListener('click', () => {
          if (dashboardLocked) return;
          let newIndex = currentDashboard() + 1;
          if (newIndex >= dashboards.length) {
            newIndex = 0;
          }
          switchDashboard(newIndex);
        });
      }

      const dateSelector = document.getElementById('dateSelector');
      if (dateSelector) {
        dateSelector.addEventListener('change', (e) => {
          if (currentDashboard() === 1 && typeof loadQADashboard === 'function') {
            const period = e.target.value.replace('-', '_');
            loadQADashboard(period);
          }
        });
      }
    }

    function startQaAutoRefresh() {
      setInterval(() => {
        if (currentDashboard() === 1 && typeof loadQADashboard === 'function') {
          const periodValue = document.getElementById('dateSelector')?.value || 'this-week';
          const period = periodValue.replace(/-/g, '_');
          console.log('Auto-refreshing QA data...');
          loadQADashboard(period);
        }
      }, 2 * 60 * 1000);
    }

    const savedLock = localStorage.getItem('dashboardLocked') === 'true';
    if (savedLock) {
      lockDashboard();
    }

    const hashDashboard = getDashboardIndexFromHash();
    const savedDashboard = parseInt(localStorage.getItem('currentDashboard') || '0', 10);
    const initialDashboard = Number.isInteger(hashDashboard)
      ? hashDashboard
      : (Number.isFinite(savedDashboard) ? savedDashboard : 0);
    switchDashboard(initialDashboard, { isInitialRestore: true });

    bindControls();
    startQaAutoRefresh();

    return {
      switchDashboard,
      lockDashboard,
      unlockDashboard,
    };
  }

  window.DashboardSwitcher = {
    init(deps) {
      return createApi(deps || {});
    },
  };
})();

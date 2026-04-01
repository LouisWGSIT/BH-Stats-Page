// Visibility and role-aware polling helper extracted from app.js.
(function () {
  function create(fn, baseIntervalMs, opts) {
    const options = opts || {};
    const viewerMultiplier = options.viewerMultiplier || 6;
    const hiddenMultiplier = options.hiddenMultiplier || 5;
    let timer = null;
    let stopped = false;

    function roleIsViewer() {
      return (sessionStorage.getItem('userRole') || 'viewer') === 'viewer';
    }

    function effectiveInterval() {
      let iv = baseIntervalMs * (roleIsViewer() ? viewerMultiplier : 1);
      if (document.hidden) iv = Math.max(iv, baseIntervalMs * hiddenMultiplier);
      return iv;
    }

    async function tick() {
      if (stopped) return;
      try {
        await fn();
      } catch (e) {
        console.warn('Adaptive poll error', e);
      }
      schedule();
    }

    function schedule() {
      clearTimeout(timer);
      if (stopped) return;
      timer = setTimeout(tick, effectiveInterval());
    }

    document.addEventListener('visibilitychange', () => {
      clearTimeout(timer);
      if (!stopped) schedule();
    });

    schedule();

    return {
      stop() {
        stopped = true;
        clearTimeout(timer);
      },
      start() {
        if (stopped) {
          stopped = false;
          schedule();
        }
      },
    };
  }

  window.AdaptivePoll = {
    create,
  };
})();

(async function () {
  // Load config
  const cfg = await fetch('config.json').then(r => r.json());

  // Apply theme variables dynamically
  const root = document.documentElement;
  root.style.setProperty('--bg', cfg.theme.bg);
  root.style.setProperty('--text', cfg.theme.text);
  root.style.setProperty('--muted', cfg.theme.muted);
  root.style.setProperty('--ring-primary', cfg.theme.ringPrimary);
  root.style.setProperty('--ring-secondary', cfg.theme.ringSecondary);

  // Targets (use erased as global target for today donut)
  document.getElementById('erasedTarget').textContent = cfg.targets.erased;

  // Charts
  const totalTodayChart = donut('chartTotalToday');
  const successChart    = donut('chartSuccess');

  // State
  let lastUpdated = 0;

  // Refresh function - fetch local metrics
  async function refresh() {
    try {
      const res = await fetch("/metrics/summary");
      if (!res.ok) throw new Error('HTTP ' + res.status);
      const data = await res.json();

      const todayTotal = data.todayTotal || 0;
      const monthTotal = data.monthTotal || 0;
      const successRate = data.successRate || 0;

      document.getElementById('totalTodayValue').textContent = todayTotal;
      document.getElementById('monthTotalValue').textContent = monthTotal;
      document.getElementById('successRateValue').textContent = Math.round(successRate) + '%';

      updateDonut(totalTodayChart, todayTotal, cfg.targets.erased);
      updateDonut(successChart, Math.round(successRate), 100);

      // Meta
      lastUpdated = Date.now();
      document.getElementById('last-updated').textContent =
        'Last updated: ' + new Date(lastUpdated).toLocaleTimeString();
      document.getElementById('stale-indicator').classList.add('hidden');
    } catch (err) {
      console.error('Refresh error:', err);
      document.getElementById('stale-indicator').classList.remove('hidden');
    }
  }

  // Kick off refresh loop
  refresh();
  setInterval(refresh, cfg.refreshSeconds * 1000);

  // Refresh top engineers
  async function refreshEngineers() {
    try {
      const res = await fetch("/metrics/top-engineers");
      if (!res.ok) throw new Error('HTTP ' + res.status);
      const data = await res.json();
      
      const topDEList = document.getElementById('topDE');
      topDEList.innerHTML = '';
      
      if (data.engineers && data.engineers.length > 0) {
        data.engineers.forEach((eng) => {
          const name = (eng.initials || '').toString().trim();
          if (!name) return; // skip empty names to avoid blank row
          const li = document.createElement('li');
          li.innerHTML = `<span>${name}</span><span class="value">${eng.count}</span>`;
          topDEList.appendChild(li);
        });
      }
    } catch (err) {
      console.error('Engineer refresh error:', err);
    }
  }

  // Kick off engineer refresh loop
  refreshEngineers();
  setInterval(refreshEngineers, cfg.refreshSeconds * 1000);
  
    // Populate a top-3 list element with engineers data
    function renderTopList(listId, engineers) {
      const el = document.getElementById(listId);
      el.innerHTML = '';
      if (engineers && engineers.length > 0) {
        engineers.forEach((eng) => {
          const li = document.createElement('li');
          li.innerHTML = `<span>${eng.initials}</span><span class="value">${eng.count}</span>`;
          el.appendChild(li);
        });
      }
    }
  
    async function refreshTopByType(type, listId) {
      try {
        const res = await fetch(`/metrics/engineers/top-by-type?type=${encodeURIComponent(type)}`);
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const data = await res.json();
        renderTopList(listId, data.engineers);
      } catch (err) {
        console.error('Top-by-type refresh error:', type, err);
      }
    }
  
    function refreshAllTopLists() {
      refreshTopByType('laptops_desktops', 'topLD');
      refreshTopByType('servers', 'topServers');
      refreshTopByType('loose_drives', 'topDrives');
    }
  
    refreshAllTopLists();
    setInterval(refreshAllTopLists, cfg.refreshSeconds * 1000);

  function updateDonut(chart, value, target) {
    const remaining = Math.max(target - value, 0);
    chart.data.datasets[0].data = [value, remaining];
    chart.update();
  }

  // Chart factory: ring look and feel
  function donut(canvasId) {
    const ctx = document.getElementById(canvasId);
    const primary = getComputedStyle(document.documentElement)
      .getPropertyValue('--ring-primary').trim();
    const secondary = getComputedStyle(document.documentElement)
      .getPropertyValue('--ring-secondary').trim();

    return new Chart(ctx, {
      type: 'doughnut',
      data: {
        labels: ['Value', 'Remaining'],
        datasets: [{
          data: [0, 0],
          backgroundColor: [secondary, primary],
          borderWidth: 0,
          hoverOffset: 4
        }]
      },
      options: {
        responsive: true,
        cutout: '65%',
        plugins: {
          legend: { display: false },
          tooltip: {
            enabled: true,
            callbacks: {
              label: function(ctx) {
                return ctx.label + ': ' + ctx.raw;
              }
            }
          }
        }
      }
    });
  }
})();

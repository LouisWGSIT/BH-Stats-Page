// Erasure dashboard category card rotation/scope logic.
(function () {
  function createApi(deps) {
    const {
      categories,
      renderTopList,
      truncateInitials,
      getAvatarDataUri,
      setupRotatorCards,
    } = deps;

    function renderTopListWithLabel(listId, engineers, label, total) {
      const el = document.getElementById(listId);
      if (!el) return;
      el.dataset.currentPeriod = label;
      el.style.opacity = 0;
      setTimeout(() => {
        el.innerHTML = '';
        if (engineers && engineers.length > 0) {
          engineers.forEach((eng) => {
            const name = truncateInitials((eng.initials || '').toString().trim());
            if (!name) return;
            const li = document.createElement('li');
            const avatar = getAvatarDataUri(name);
            li.innerHTML = `
            <span class="engineer-chip">
              <span class="engineer-avatar" style="background-image: url(${avatar})"></span>
              <span class="engineer-name">${name}</span>
            </span>
            <span class="value">${eng.count}</span>`;
            el.appendChild(li);
          });
        } else {
          const li = document.createElement('li');
          li.innerHTML = `<span class="no-data">No data yet</span>`;
          el.appendChild(li);
        }
        if (label) {
          const header = el.parentElement.querySelector('.stat-card__header, .card-header, .category-header, .top-row, .card-title-row') || el.parentElement;
          let labelEl = header.querySelector('.category-period-label');
          if (!labelEl) {
            labelEl = document.createElement('span');
            labelEl.className = 'category-period-label';
            labelEl.style = 'font-size:0.95em;color:var(--muted);margin-right:8px;vertical-align:middle;';
            header.insertBefore(labelEl, header.firstChild);
          }
          labelEl.textContent = label;
        }
        const header = el.parentElement.querySelector('.stat-card__header, .card-header, .category-header, .top-row, .card-title-row') || el.parentElement;
        const pill = header.querySelector('.pill');
        if (pill && typeof total === 'number') {
          if (el.dataset.currentPeriod === label) pill.textContent = total;
        }
        setTimeout(() => {
          el.style.opacity = 1;
        }, 200);
      }, 200);
    }

    async function refreshTopByTypeAllScopes(type, listId) {
      const scopes = [
        { key: 'today', label: 'Today' },
        { key: 'month', label: 'This Month' },
        { key: 'all', label: 'All Time' },
      ];
      const results = {};
      for (const scope of scopes) {
        try {
          let url = `/metrics/engineers/top-by-type?type=${encodeURIComponent(type)}`;
          if (scope.key !== 'today') url += `&scope=${scope.key}`;
          const res = await fetch(url);
          const data = await res.json();
          let total = 0;
          try {
            const totalUrl = `/metrics/total-by-type?type=${encodeURIComponent(type)}&scope=${scope.key}`;
            const totalRes = await fetch(totalUrl);
            const totalData = await totalRes.json();
            total = typeof totalData.total === 'number' ? totalData.total : 0;
          } catch (_err) {
            total = (data.engineers || []).reduce((sum, e) => sum + (e.count || 0), 0);
          }
          results[scope.key] = { engineers: data.engineers, label: scope.label, total };
        } catch (_err) {
          results[scope.key] = { engineers: [], label: scope.label, total: 0 };
        }
      }
      if (!results.all) {
        results.all = { engineers: [], label: 'All Time', total: 0 };
      }
      window._categoryFlipData = window._categoryFlipData || {};
      window._categoryFlipData[listId] = results;
      renderTopListWithLabel(listId, results.today.engineers, results.today.label, results.today.total);
    }

    async function refreshCategoryRotatorCards() {
      const categoryMappings = [
        { key: 'laptops_desktops', todayListId: 'topLD', monthListId: 'topLDMonth', allTimeListId: 'topLDAllTime', todayCountId: 'countLD', monthCountId: 'countLDMonth', allTimeCountId: 'countLDAllTime' },
        { key: 'servers', todayListId: 'topServers', monthListId: 'topServersMonth', allTimeListId: 'topServersAllTime', todayCountId: 'countServers', monthCountId: 'countServersMonth', allTimeCountId: 'countServersAllTime' },
        { key: 'macs', todayListId: 'topMacs', monthListId: 'topMacsMonth', allTimeListId: 'topMacsAllTime', todayCountId: 'countMacs', monthCountId: 'countMacsMonth', allTimeCountId: 'countMacsAllTime' },
        { key: 'mobiles', todayListId: 'topMobiles', monthListId: 'topMobilesMonth', allTimeListId: 'topMobilesAllTime', todayCountId: 'countMobiles', monthCountId: 'countMobilesMonth', allTimeCountId: 'countMobilesAllTime' },
      ];

      for (const cat of categoryMappings) {
        try {
          const todayRes = await fetch(`/metrics/engineers/top-by-type?type=${encodeURIComponent(cat.key)}`);
          const todayData = await todayRes.json();
          const todayTotalRes = await fetch(`/metrics/total-by-type?type=${encodeURIComponent(cat.key)}&scope=today`);
          const todayTotalData = await todayTotalRes.json();
          const todayTotal = todayTotalData.total || 0;

          const monthRes = await fetch(`/metrics/engineers/top-by-type?type=${encodeURIComponent(cat.key)}&scope=month`);
          const monthData = await monthRes.json();
          const monthTotalRes = await fetch(`/metrics/total-by-type?type=${encodeURIComponent(cat.key)}&scope=month`);
          const monthTotalData = await monthTotalRes.json();
          const monthTotal = monthTotalData.total || 0;

          const allTimeRes = await fetch(`/metrics/engineers/top-by-type?type=${encodeURIComponent(cat.key)}&scope=all`);
          const allTimeData = await allTimeRes.json();
          const allTimeTotalRes = await fetch(`/metrics/total-by-type?type=${encodeURIComponent(cat.key)}&scope=all`);
          const allTimeTotalData = await allTimeTotalRes.json();
          const allTimeTotal = allTimeTotalData.total || 0;

          renderTopList(cat.todayListId, todayData.engineers);
          const todayCountEl = document.getElementById(cat.todayCountId);
          if (todayCountEl) todayCountEl.textContent = todayTotal;

          renderTopList(cat.monthListId, monthData.engineers);
          const monthCountEl = document.getElementById(cat.monthCountId);
          if (monthCountEl) monthCountEl.textContent = monthTotal;

          renderTopList(cat.allTimeListId, allTimeData.engineers);
          const allTimeCountEl = document.getElementById(cat.allTimeCountId);
          if (allTimeCountEl) allTimeCountEl.textContent = allTimeTotal;
        } catch (_err) {
          // keep best effort; individual card failures should not break dashboard
        }
      }
    }

    function setupCategoryFlipCards() {
      if (!window._categoryFlipData) return;
      if (window._categoryFlipIntervals) {
        window._categoryFlipIntervals.forEach(id => clearInterval(id));
      }
      window._categoryFlipIntervals = [];

      categories.forEach(c => {
        const listId = c.listId;
        const el = document.getElementById(listId);
        if (!el) return;

        const header = el.parentElement.querySelector('.card-header, .category-header, .top-row, .card-title-row') || el.parentElement;
        let label = header.querySelector('.category-period-label');
        if (!label) {
          label = document.createElement('span');
          label.className = 'category-period-label';
          label.style = 'font-size:0.95em;color:var(--muted);margin-right:8px;vertical-align:middle;';
          const pip = header.querySelector('.pip, .pip-count, .pip-value, .pip-number, .pipNum, .pipnum, .pipnumtop, .pipnum-top, .pip-number-top, .pip-number');
          if (pip) {
            header.insertBefore(label, pip);
          } else {
            header.appendChild(label);
          }
        }

        let flipIndex = 0;
        const flipData = window._categoryFlipData[listId];
        const scopes = ['today', 'month', 'all'];

        function performFlip() {
          flipIndex = (flipIndex + 1) % scopes.length;
          const currentEl = document.getElementById(listId);
          if (!currentEl) return;
          currentEl.style.opacity = '0';
          setTimeout(() => {
            let data = flipData[scopes[flipIndex]];
            if (!data) {
              flipIndex = 0;
              data = flipData[scopes[0]];
            }
            renderTopListWithLabel(listId, data.engineers, data.label, data.total);
            void document.body.offsetHeight;
            const elAfterUpdate = document.getElementById(listId);
            if (elAfterUpdate) {
              setTimeout(() => {
                elAfterUpdate.style.opacity = '1';
              }, 50);
            }
          }, 600);
        }

        setTimeout(() => {
          const intervalId = setInterval(performFlip, 20000);
          window._categoryFlipIntervals.push(intervalId);
        }, 2000);
      });

      if (!window._categoryFlipVisibilityHandler) {
        window._categoryFlipVisibilityHandler = function () {
          if (!document.hidden) {
            // no-op; intervals continue naturally
          }
        };
        document.addEventListener('visibilitychange', window._categoryFlipVisibilityHandler);
      }
    }

    function init() {
      window.refreshAllTopLists = function () {
        return refreshCategoryRotatorCards();
      };
      refreshCategoryRotatorCards();
      setTimeout(() => {
        setupRotatorCards();
      }, 2000);
    }

    return {
      init,
      refreshCategoryRotatorCards,
      setupCategoryFlipCards,
      refreshTopByTypeAllScopes,
    };
  }

  window.ErasureCategoryCards = {
    init: createApi,
  };
})();

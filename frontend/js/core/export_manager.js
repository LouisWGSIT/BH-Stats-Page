// Export/download workflow and custom range picker lifecycle.
(function () {
  function createApi(deps) {
    const {
      getCurrentDashboard,
    } = deps;

    let customRangeData = null; // stores {startYear, startMonth, endYear, endMonth}

    function currentDashboard() {
      if (typeof getCurrentDashboard === 'function') {
        return getCurrentDashboard();
      }
      return 0;
    }

    function showExportLoading() {
      const modal = document.getElementById('exportLoadingModal');
      if (modal) modal.classList.remove('hidden');
    }

    function hideExportLoading() {
      const modal = document.getElementById('exportLoadingModal');
      if (modal) modal.classList.add('hidden');
    }

    function populateMonthOptions() {
      const startSelect = document.getElementById('rangeStartMonth');
      const endSelect = document.getElementById('rangeEndMonth');
      if (!startSelect || !endSelect) return;

      const now = new Date();
      const currentYear = now.getFullYear();
      const currentMonth = now.getMonth();
      const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

      const options = [];
      for (let year = currentYear - 2; year <= currentYear; year++) {
        const maxMonth = year === currentYear ? currentMonth : 11;
        for (let month = 0; month <= maxMonth; month++) {
          options.push({ year, month, label: `${months[month]} ${year}` });
        }
      }

      startSelect.innerHTML = options.map(opt =>
        `<option value="${opt.year}-${opt.month}">${opt.label}</option>`
      ).join('');

      endSelect.innerHTML = options.map(opt =>
        `<option value="${opt.year}-${opt.month}">${opt.label}</option>`
      ).join('');

      startSelect.value = `${currentYear}-0`;
      endSelect.value = `${currentYear}-${currentMonth}`;
    }

    function showCustomRangeModal() {
      const modal = document.getElementById('customRangeModal');
      if (!modal) return;
      populateMonthOptions();
      modal.classList.remove('hidden');
    }

    function hideCustomRangeModal(revertSelector = true) {
      const modal = document.getElementById('customRangeModal');
      if (modal) modal.classList.add('hidden');
      if (revertSelector) {
        const selector = document.getElementById('dateSelector');
        if (selector && !customRangeData) {
          selector.value = 'this-week';
        }
      }
    }

    async function downloadExcel() {
      const dateScope = document.getElementById('dateSelector')?.value || 'this-week';

      if (dateScope === 'custom-range' && !customRangeData) {
        showCustomRangeModal();
        return;
      }

      let period = dateScope.replace(/-/g, '_');
      let exportUrl;
      let filename;

      let customParams = '';
      if (dateScope === 'custom-range' && customRangeData) {
        const { startYear, startMonth, endYear, endMonth } = customRangeData;
        customParams = `&start_year=${startYear}&start_month=${startMonth + 1}&end_year=${endYear}&end_month=${endMonth + 1}`;
        period = 'custom_range';
      }

      if (currentDashboard() === 1) {
        if (period === 'last_available') {
          period = 'last_available';
        }
        exportUrl = `/export/qa-stats?period=${period}${customParams}`;
        filename = customRangeData
          ? `qa-stats-${customRangeData.startYear}-${customRangeData.startMonth + 1}-to-${customRangeData.endYear}-${customRangeData.endMonth + 1}.xlsx`
          : `qa-stats-${dateScope}.xlsx`;
      } else {
        if (dateScope === 'last-available') {
          period = 'this_week';
        }
        exportUrl = `/export/engineer-deepdive?period=${period}${customParams}`;
        filename = customRangeData
          ? `engineer-deepdive-${customRangeData.startYear}-${customRangeData.startMonth + 1}-to-${customRangeData.endYear}-${customRangeData.endMonth + 1}.xlsx`
          : `engineer-deepdive-${dateScope}.xlsx`;
      }

      showExportLoading();

      try {
        const existingToken = sessionStorage.getItem('authToken') || localStorage.getItem('deviceToken');
        const response = await fetch(exportUrl, existingToken ? {
          headers: { Authorization: 'Bearer ' + existingToken }
        } : {});

        if (!response.ok) {
          throw new Error(`Export failed: ${response.statusText}`);
        }

        const contentDisposition = response.headers.get('Content-Disposition');
        let serverFilename = null;
        if (contentDisposition) {
          const match = contentDisposition.match(/filename=([^;]+)/);
          if (match) {
            serverFilename = match[1].replace(/"/g, '').trim();
          }
        }

        const blob = await response.blob();
        const downloadUrl = window.URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = downloadUrl;
        link.download = serverFilename || filename;
        document.body.appendChild(link);
        link.click();
        link.remove();
        window.URL.revokeObjectURL(downloadUrl);
      } catch (error) {
        console.error('Export error:', error);
        alert('Failed to download spreadsheet: ' + error.message);
      } finally {
        hideExportLoading();
      }
    }

    function handleCustomRangeConfirm() {
      const startSelect = document.getElementById('rangeStartMonth');
      const endSelect = document.getElementById('rangeEndMonth');
      if (!startSelect || !endSelect) return;

      const [startYear, startMonth] = startSelect.value.split('-').map(Number);
      const [endYear, endMonth] = endSelect.value.split('-').map(Number);

      if (startYear > endYear || (startYear === endYear && startMonth > endMonth)) {
        alert('Start month must be before or equal to end month');
        return;
      }

      customRangeData = { startYear, startMonth, endYear, endMonth };
      hideCustomRangeModal(false);

      const selector = document.getElementById('dateSelector');
      const customOption = selector?.querySelector('option[value="custom-range"]');
      if (customOption) {
        const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
        customOption.textContent = `${months[startMonth]} ${startYear} - ${months[endMonth]} ${endYear}`;
      }

      downloadExcel();
    }

    function bindEvents() {
      document.getElementById('rangeCancel')?.addEventListener('click', () => hideCustomRangeModal(true));
      document.getElementById('rangeConfirm')?.addEventListener('click', handleCustomRangeConfirm);

      document.getElementById('customRangeModal')?.addEventListener('click', (e) => {
        if (e.target.id === 'customRangeModal') hideCustomRangeModal(true);
      });

      document.getElementById('dateSelector')?.addEventListener('change', (e) => {
        if (e.target.value === 'custom-range') {
          showCustomRangeModal();
        }
      });
    }

    bindEvents();

    return {
      downloadExcel,
      showCustomRangeModal,
      hideCustomRangeModal,
    };
  }

  window.ExportManager = {
    init(deps) {
      return createApi(deps || {});
    },
  };
})();

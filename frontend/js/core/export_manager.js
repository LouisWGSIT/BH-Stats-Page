// Export/download workflow and custom range picker lifecycle.
(function () {
  function createApi(deps) {
    const {
      getCurrentDashboard,
      categories,
      SHIFT_HOURS,
      formatTimeAgo,
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

  async function generateCSV() {
    const csvHelpers = window.ExportCsvHelpers || {};
    const dateScope = document.getElementById('dateSelector')?.value || 'this-week';
    const scopeInfo = csvHelpers.resolveScopeContext
      ? csvHelpers.resolveScopeContext(dateScope)
      : {
          isThisWeek: dateScope === 'this-week',
          isLastWeek: dateScope === 'last-week',
          isThisMonth: dateScope === 'this-month',
          isLastMonth: dateScope === 'last-month',
          isMonthlyReport: dateScope === 'this-month' || dateScope === 'last-month',
          isWeeklyReport: dateScope === 'this-week' || dateScope === 'last-week',
          targetDate: new Date(),
          dateRangeStr: new Date().toLocaleDateString('en-GB'),
          currentTime: new Date().toLocaleTimeString('en-GB'),
        };

    const {
      isThisWeek,
      isLastWeek,
      isThisMonth,
      isLastMonth,
      isMonthlyReport,
      isWeeklyReport,
      targetDate,
      dateRangeStr,
      currentTime: time,
    } = scopeInfo;

    const summaryMetrics = csvHelpers.fetchSummaryMetrics
      ? await csvHelpers.fetchSummaryMetrics({ dateScope, targetDate, isWeeklyReport, isMonthlyReport })
      : { todayTotal: '0', monthTotal: '0', target: '500' };
    const { todayTotal, monthTotal, target } = summaryMetrics;

    const engineerData = csvHelpers.fetchEngineerData
      ? await csvHelpers.fetchEngineerData({ dateScope, targetDate, isMonthlyReport, SHIFT_HOURS, formatTimeAgo })
      : { allEngineersRows: [], engineerKPIs: {} };
    const { allEngineersRows, engineerKPIs } = engineerData;

    const categoryRows = csvHelpers.collectCategoryRows
      ? csvHelpers.collectCategoryRows({ categories, isMonthlyReport, isWeeklyReport })
      : [];

    const categoryTopPerformers = csvHelpers.collectCategoryTopPerformers
      ? await csvHelpers.collectCategoryTopPerformers({ categories, isMonthlyReport, isWeeklyReport, targetDate })
      : [];

    // Calculate progress metrics
    let currentDay, daysInMonth, dailyAvg, projectedTotal, daysRemaining, progressPercent, statusIndicator, monthProgressPercent;
    if (isMonthlyReport) {
      daysInMonth = new Date(targetDate.getFullYear(), targetDate.getMonth() + 1, 0).getDate();
      dailyAvg = Math.round(parseInt(monthTotal) / daysInMonth);
      projectedTotal = dailyAvg * daysInMonth;
      daysRemaining = isThisMonth ? daysInMonth - targetDate.getDate() : 0;
      progressPercent = Math.round((parseInt(monthTotal) / (parseInt(target) * daysInMonth)) * 100);
      statusIndicator = progressPercent >= 100 ? 'ON PACE' : progressPercent >= 80 ? 'GOOD PACE' : 'BELOW PACE';
      monthProgressPercent = progressPercent;
    } else {
      currentDay = targetDate.getDate();
      daysInMonth = new Date(targetDate.getFullYear(), targetDate.getMonth() + 1, 0).getDate();
      dailyAvg = Math.round(parseInt(monthTotal) / currentDay);
      projectedTotal = Math.round(dailyAvg * daysInMonth);
      daysRemaining = daysInMonth - currentDay;
      progressPercent = Math.round((parseInt(todayTotal) / parseInt(target)) * 100);
      statusIndicator = progressPercent >= 100 ? 'ON TARGET' : progressPercent >= 80 ? 'APPROACHING' : 'BELOW TARGET';
      monthProgressPercent = Math.round((parseInt(monthTotal) / (parseInt(target) * currentDay)) * 100);
    }
    
    // Build professional report title
    const titles = csvHelpers.buildReportTitles
      ? csvHelpers.buildReportTitles({ isThisMonth, isLastMonth, isThisWeek, isLastWeek, dateRangeStr })
      : {
          reportTitle: 'ITAD & SWAP Services - Date Erasure and QA Stats',
          reportSubtitle: `Current Status - ${dateRangeStr}`,
        };
    const { reportTitle, reportSubtitle } = titles;
    
    let csvRows;
    if (csvHelpers.buildCsvRows) {
      csvRows = await csvHelpers.buildCsvRows({
        reportTitle,
        reportSubtitle,
        time,
        target,
        isMonthlyReport,
        isWeeklyReport,
        isThisMonth,
        isLastMonth,
        isThisWeek,
        isLastWeek,
        dateRangeStr,
        targetDate,
        daysInMonth,
        daysRemaining,
        monthTotal,
        todayTotal,
        dailyAvg,
        projectedTotal,
        progressPercent,
        statusIndicator,
        monthProgressPercent,
        allEngineersRows,
        engineerKPIs,
        categoryRows,
        categoryTopPerformers,
      });
    } else {
      csvRows = [
        [reportTitle],
        [reportSubtitle],
        ['Generated:', new Date().toLocaleDateString('en-GB')],
      ];
    }

    return csvRows.map(row => row.map(cell => `"${cell}"`).join(',')).join('\n');
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
      generateCSV,
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

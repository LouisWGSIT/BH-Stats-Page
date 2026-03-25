// Erasure-specific exports, CSV/XLSX generation and custom range picker.
(function(){
  window.customRangeData = null;

  function renderCSVRowJoin(rows) {
    return rows.map(row => row.map(cell => `"${cell}"`).join(',')).join('\n');
  }

  async function generateCSV() {
    const dateScope = document.getElementById('dateSelector')?.value || 'this-week';
    const isThisWeek = dateScope === 'this-week';
    const isLastWeek = dateScope === 'last-week';
    const isThisMonth = dateScope === 'this-month';
    const isLastMonth = dateScope === 'last-month';
    const isMonthlyReport = isThisMonth || isLastMonth;
    const isWeeklyReport = isThisWeek || isLastWeek;

    // Calculate date range for display and API calls
    let targetDate = new Date();
    let dateRangeStr = '';
    let monthYearStr = '';

    if (isLastWeek) {
      const today = new Date();
      const dayOfWeek = today.getDay();
      const daysToLastSunday = dayOfWeek === 0 ? 1 : dayOfWeek + 1;
      targetDate.setDate(today.getDate() - daysToLastSunday);
      targetDate.setDate(targetDate.getDate() - 6);
      const startDate = new Date(targetDate);
      const endDate = new Date(startDate);
      endDate.setDate(endDate.getDate() + 6);
      dateRangeStr = `${startDate.toLocaleDateString('en-GB')} - ${endDate.toLocaleDateString('en-GB')}`;
    } else if (isThisWeek) {
      const today = new Date();
      const dayOfWeek = today.getDay();
      const daysToMonday = dayOfWeek === 0 ? 6 : dayOfWeek - 1;
      const startDate = new Date(today);
      startDate.setDate(today.getDate() - daysToMonday);
      dateRangeStr = `${startDate.toLocaleDateString('en-GB')} - ${today.toLocaleDateString('en-GB')}`;
    } else if (isLastMonth) {
      targetDate.setMonth(targetDate.getMonth() - 1);
      targetDate.setDate(1);
      monthYearStr = targetDate.toLocaleDateString('en-GB', { month: 'long', year: 'numeric' });
      dateRangeStr = monthYearStr;
    } else if (isThisMonth) {
      targetDate.setDate(1);
      monthYearStr = targetDate.toLocaleDateString('en-GB', { month: 'long', year: 'numeric' });
      dateRangeStr = monthYearStr;
    } else {
      dateRangeStr = targetDate.toLocaleDateString('en-GB');
    }

    const time = new Date().toLocaleTimeString('en-GB');

    // Get current displayed values (only valid for "this-week")
    let todayTotal = '0', monthTotal = '0', target = '500';
    if (!isWeeklyReport && !isMonthlyReport) {
      todayTotal = document.getElementById('totalTodayValue')?.textContent || '0';
      monthTotal = document.getElementById('monthTotalValue')?.textContent || '0';
      target = document.getElementById('erasedTarget')?.textContent || '500';
    } else {
      try {
        if (isMonthlyReport) {
          const monthDate = new Date(targetDate);
          const year = monthDate.getFullYear();
          const month = monthDate.getMonth();
          const firstDay = new Date(year, month, 1).toISOString().split('T')[0];
          const lastDay = new Date(year, month + 1, 0).toISOString().split('T')[0];
          const res = await fetch(`/metrics/summary?startDate=${firstDay}&endDate=${lastDay}`);
          if (res.ok) {
            const data = await res.json();
            monthTotal = data.monthTotal || '0';
          }
        } else {
          const res = await fetch(`/metrics/summary?date=${targetDate.toISOString().split('T')[0]}`);
          if (res.ok) {
            const data = await res.json();
            todayTotal = data.todayTotal || '0';
            monthTotal = data.monthTotal || '0';
          }
        }
      } catch (err) {
        console.error('Failed to fetch summary:', err);
      }
    }

    // For monthly reports, fetch engineer breakdown data
    let allEngineersRows = [];
    let engineerKPIs = {};
    try {
      let apiEndpoint = `/metrics/engineers/leaderboard?scope=${dateScope}&limit=50`;
      const res = await fetch(apiEndpoint);
      if (res.ok) {
        const data = await res.json();
        try {
          let kpiUrl = '/metrics/engineers/kpis/all';
          const kpiRes = await fetch(kpiUrl);
          if (kpiRes.ok) {
            const kpiData = await kpiRes.json();
            engineerKPIs = (kpiData.engineers || []).reduce((acc, kpi) => { acc[kpi.initials] = kpi; return acc; }, {});
          }
        } catch (err) { console.error('Failed to fetch engineer KPIs:', err); }
        allEngineersRows = (data.items || []).map((eng, idx) => {
          let erasures = eng.erasures || 0;
          let avgPerHour = isMonthlyReport ? (erasures / (targetDate.getDate() * SHIFT_HOURS)).toFixed(1) : (erasures / SHIFT_HOURS).toFixed(1);
          let lastActiveDisplay = isMonthlyReport ? 'N/A' : (window.formatTimeAgo ? window.formatTimeAgo(eng.lastActive) : '—');
          const baseRow = [ idx + 1, eng.initials || '', erasures, lastActiveDisplay, avgPerHour ];
          if (engineerKPIs[eng.initials]) {
            const kpi = engineerKPIs[eng.initials];
            return [ ...baseRow, kpi.avg7Day, kpi.avg30Day, kpi.trend, kpi.personalBest, kpi.consistencyScore, kpi.daysActiveMonth ];
          }
          return baseRow;
        });
      }
    } catch (err) { console.error('Failed to fetch engineer data:', err); }

    // Category data
    const categoryRows = [];
    try {
      if (!isMonthlyReport && !isWeeklyReport) {
        categories.forEach(cat => {
          const count = document.getElementById(cat.countId)?.textContent || '0';
          categoryRows.push([cat.label, count]);
        });
      } else {
        console.log('Category breakdown for weekly/monthly reports not yet implemented');
      }
    } catch (err) { console.error('Failed to fetch category data:', err); }

    const categoryTopPerformers = [];
    try {
      if (!isMonthlyReport && !isWeeklyReport) {
        categories.forEach(cat => {
          const listEl = document.getElementById(cat.listId);
          if (listEl) {
            const items = listEl.querySelectorAll('li');
            if (items.length > 0) {
              items.forEach(item => {
                const text = item.textContent.trim();
                const parts = text.match(/(.+?)\\s+(\\d+)$/);
                if (parts) categoryTopPerformers.push([cat.label, parts[1], parts[2]]);
              });
            }
          }
        });
      } else {
        const catOrder = ['laptops_desktops','servers','macs','mobiles'];
        const catNames = { laptops_desktops: 'Laptops/Desktops', servers: 'Servers', macs: 'Macs', mobiles: 'Mobiles' };
        const monthDate = new Date(targetDate);
        const year = monthDate.getFullYear();
        const month = monthDate.getMonth();
        const firstDay = new Date(year, month, 1).toISOString().split('T')[0];
        const lastDay = new Date(year, month + 1, 0).toISOString().split('T')[0];
        const res = await fetch(`/competitions/category-specialists?startDate=${firstDay}&endDate=${lastDay}`);
        if (res.ok) {
          const data = await res.json();
          if (data.specialists) {
            catOrder.forEach(cat => { (data.specialists[cat] || []).slice(0,1).forEach(row => categoryTopPerformers.push([catNames[cat], row.initials || '', row.count || 0])); });
          }
        }
      }
    } catch (err) { console.error('Failed to fetch category top performers:', err); }

    // Calculate progress
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

    let reportTitle, reportSubtitle;
    if (isThisMonth) {
      reportTitle = 'ITAD & SWAP Services - Date Erasure and QA Stats - THIS MONTH';
      reportSubtitle = `Monthly Report for: ${dateRangeStr}`;
    } else if (isLastMonth) {
      reportTitle = 'ITAD & SWAP Services - Date Erasure and QA Stats - LAST MONTH';
      reportSubtitle = `Monthly Report for: ${dateRangeStr}`;
    } else if (isLastWeek) {
      reportTitle = 'ITAD & SWAP Services - Date Erasure and QA Stats - LAST WEEK';
      reportSubtitle = `Weekly Report for: ${dateRangeStr}`;
    } else if (isThisWeek) {
      reportTitle = 'ITAD & SWAP Services - Date Erasure and QA Stats - THIS WEEK';
      reportSubtitle = `Current Week Status - ${dateRangeStr}`;
    } else {
      reportTitle = 'ITAD & SWAP Services - Date Erasure and QA Stats';
      reportSubtitle = `Current Status - ${dateRangeStr}`;
    }

    const csv = [ [reportTitle], [reportSubtitle], ['Generated:', new Date().toLocaleDateString('en-GB', { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' })], ['Time:', time], [], ['EXECUTIVE SUMMARY'], ['Key Metric', 'Value', 'Status/Target', 'Performance'] ];

    if (isMonthlyReport) {
      csv.push(['Monthly Total', monthTotal, `Expected: ~${parseInt(target) * daysInMonth}`, statusIndicator]);
      csv.push(['Daily Average', dailyAvg, `Per day`, `vs ${target} target`]);
      csv.push(['Days in Month', daysInMonth, `Total days`, isThisMonth ? `${daysRemaining} remaining` : 'Complete']);
      csv.push(['Achievement Rate', `${progressPercent}%`, `of monthly expectation`, progressPercent >= 100 ? 'Exceeded Target' : 'Below Target']);
      csv.push(['Days Active', Object.values(engineerKPIs).reduce((sum, kpi) => sum + (kpi.daysActiveMonth || 0), 0), 'Across all engineers', 'Utilization metric']);
    } else if (isWeeklyReport) {
      csv.push(['Weekly Total', todayTotal, `Target: ~${parseInt(target) * 5}`, statusIndicator]);
      csv.push(['Daily Average', dailyAvg, 'Per day', `${dailyAvg > parseInt(target) ? 'Above' : 'Below'} target`]);
      csv.push(['Week Period', dateRangeStr, 'Mon-Sun', isThisWeek ? 'In Progress' : 'Complete']);
    } else {
      csv.push(["Today's Total", todayTotal, `Target: ${target}`, statusIndicator]);
      csv.push(['Month Total', monthTotal, `Avg ${target}/day`, `${monthProgressPercent}% of pace`]);
      csv.push(['Daily Average', dailyAvg, 'Per day', `${dailyAvg > parseInt(target) ? 'Above' : 'Below'} target`]);
      csv.push(['Projected Month', projectedTotal, `of ~${parseInt(target) * daysInMonth} max`, `${Math.round((projectedTotal / (parseInt(target) * daysInMonth)) * 100)}% utilization`]);
      csv.push(['Days Remaining', daysRemaining, `in ${targetDate.toLocaleDateString('en-US', { month: 'long' })}`, '']);
    }
    csv.push([]);

    // Fetch additional metrics in parallel
    if (true) {
      try {
        const [perfTrends, targetAchievement, records, weekly, specialists, consistency] = await Promise.all([
          fetch(`/metrics/performance-trends?target=${target}`).then(r => r.ok ? r.json() : null),
          fetch(`/metrics/target-achievement?target=${target}`).then(r => r.ok ? r.json() : null),
          fetch('/metrics/records').then(r => r.ok ? r.json() : null),
          fetch('/metrics/weekly').then(r => r.ok ? r.json() : null),
          fetch('/competitions/category-specialists').then(r => r.ok ? r.json() : null),
          fetch('/competitions/consistency').then(r => r.ok ? r.json() : null)
        ]);

        if (perfTrends) {
          csv.push(['PERFORMANCE TRENDS']);
          csv.push(['Metric', 'Value', 'Indicator', 'Notes']);
          csv.push(['Week-over-Week Change', `${perfTrends.wowChange > 0 ? '+' : ''}${perfTrends.wowChange}%`, perfTrends.trend, `Current: ${perfTrends.currentWeekTotal}, Previous: ${perfTrends.previousWeekTotal}`]);
          csv.push(['Month-over-Month Change', `${perfTrends.momChange > 0 ? '+' : ''}${perfTrends.momChange}%`, perfTrends.momChange > 0 ? 'Growth' : perfTrends.momChange < 0 ? 'Decline' : 'Flat', `Current: ${perfTrends.currentMonthTotal}, Previous: ${perfTrends.previousMonthTotal}`]);
          csv.push(['Rolling 7-Day Average', perfTrends.rolling7DayAvg, `${perfTrends.vsTargetPct}% of target`, `Target: ${target}/day`]);
          csv.push(['Trend Direction', perfTrends.trend, '', 'Based on last 7 days vs previous 7 days']);
          csv.push([]);
        }

        if (targetAchievement) {
          csv.push(['TARGET ACHIEVEMENT METRICS']);
          csv.push(['Metric', 'Value', 'Details', 'Status']);
          csv.push(['Days Hitting Target', `${targetAchievement.daysHittingTarget} of ${targetAchievement.totalDaysThisMonth}`, `${targetAchievement.hitRatePct}% success rate`, targetAchievement.hitRatePct >= 80 ? 'Excellent' : targetAchievement.hitRatePct >= 60 ? 'Good' : 'Needs Improvement']);
          csv.push(['Current Streak', `${targetAchievement.currentStreak} days ${targetAchievement.streakType} target`, '', targetAchievement.streakType === 'above' ? '[HOT STREAK]' : '[BELOW TARGET]']);
          csv.push(['Projected Month Total', targetAchievement.projectedMonthTotal, `Based on ${dailyAvg}/day average`, targetAchievement.projectedMonthTotal >= targetAchievement.monthlyTarget ? 'On Track' : 'Below Pace']);
          csv.push(['Gap to Monthly Target', Math.abs(targetAchievement.gapToTarget), targetAchievement.gapToTarget <= 0 ? 'Target Exceeded!' : `${targetAchievement.daysRemaining} days remaining`, '']);
          csv.push(['Daily Rate Needed', targetAchievement.gapToTarget > 0 ? targetAchievement.dailyNeeded : 0, `to hit ${targetAchievement.monthlyTarget} target`, targetAchievement.dailyNeeded <= target ? 'Achievable' : 'Challenging']);
          csv.push([]);
        }

        if (records?.bestDay || records?.topEngineer || records?.currentStreak !== undefined) {
          csv.push(['HISTORICAL RECORDS & ACHIEVEMENTS']);
          csv.push(['Metric', 'Value', 'Details']);
          if (records.bestDay) csv.push(['Best Day Ever', records.bestDay.count || 0, `Achieved on ${records.bestDay.date || 'N/A'}`]);
          if (records.topEngineer) csv.push(['Top Engineer (All-Time)', records.topEngineer.initials || '—', `${records.topEngineer.totalCount || 0} total erasures`]);
          if (records.currentStreak !== undefined) csv.push(['Current Streak', `${records.currentStreak || 0} days`, 'above daily target']);
          csv.push([]);
        }

        if (weekly?.weekTotal || weekly?.daysActive) {
          if (weekly.weekStart && weekly.weekEnd) csv.push([`Workweek: ${weekly.weekStart} to ${weekly.weekEnd}`]);
          csv.push(['WEEKLY PERFORMANCE (Workweek Mon–Fri)']);
          csv.push(['Metric', 'Value', 'Comparison', 'Notes']);
          csv.push(['Week Total', weekly.weekTotal || 0, `${Math.round((weekly.weekTotal / (parseInt(target) * 5)) * 100)}% of weekly goal`, '']);
          csv.push(['Best Day', weekly.bestDayOfWeek?.count || 0, `(${weekly.bestDayOfWeek?.date || 'N/A'})`, weekly.bestDayOfWeek?.count >= parseInt(target) ? 'On Target' : 'Below Target']);
          csv.push(['Daily Average', weekly.weekAverage || 0, `vs ${target} target`, weekly.weekAverage >= parseInt(target) ? 'Above Target' : 'Below Target']);
          csv.push(['Days Active', weekly.daysActive || 0, `out of 5 workdays`, '']);
          csv.push([]);
        }

        if (consistency?.leaderboard?.length) {
          csv.push([]);
          csv.push(['CONSISTENCY KINGS/QUEENS', 'Steadiest pace - lowest variability']);
          csv.push(['Rank', 'Engineer', 'Erasures', 'Avg Pace (min)', 'Consistency Score']);
          csv.push(...consistency.leaderboard.map((row, idx) => [ idx + 1, row.initials || '', row.erasures || 0, row.avgGapMinutes || 0, row.consistencyScore || 0 ]));
        }
      } catch (err) { console.error('Failed to fetch detailed metrics:', err); }
    }

    if (!isMonthlyReport && !isWeeklyReport && allEngineersRows.length > 0) {
      csv.push(['TOP 3 ENGINEERS (Daily Leaders)']);
      csv.push(['Rank', 'Engineer', 'Erasures', 'Last Active', 'Status']);
      allEngineersRows.slice(0,3).forEach(row => { const erasures = parseInt(row[2]); let status = erasures >= parseInt(target) ? 'Exceeding Target' : 'On Pace'; csv.push([row[0], row[1], row[2], row[3], status]); });
      if (allEngineersRows.length >= 2) {
        const lead = parseInt(allEngineersRows[0][2]);
        const second = parseInt(allEngineersRows[1][2]);
        const gap = lead - second; const gapPercent = Math.round((gap / (second || 1)) * 100);
        csv.push([]);
        csv.push(['RACE ANALYSIS']);
        csv.push(['Leader', allEngineersRows[0][1]]);
        csv.push(['Lead Margin', `${gap} erasures (${gapPercent}% ahead)`]);
        csv.push(['Second Place', allEngineersRows[1][1]]);
      }
      csv.push([]);
    }

    csv.push([isMonthlyReport ? 'ENGINEER PERFORMANCE - MONTHLY SUMMARY' : isWeeklyReport ? 'ALL ENGINEERS - WEEKLY SUMMARY' : 'ALL ENGINEERS - DETAILED LEADERBOARD WITH KPIs']);
    csv.push(['Rank', 'Engineer', isMonthlyReport ? 'Month Total' : isWeeklyReport ? 'Week Total' : 'Today Total', 'Last Active', 'Per Hour', '% Target', '7-Day Avg', '30-Day Avg', 'Trend', 'Personal Best', 'Consistency', 'Days Active']);
    csv.push(...(allEngineersRows.length > 0 ? allEngineersRows.map(row => {
      const erasures = parseInt(row[2]); const pct = parseInt(target) > 0 ? Math.round((erasures / parseInt(target)) * 100) : 0;
      if (row.length > 5) return [row[0], row[1], row[2], row[3], row[4], `${pct}%`, row[5], row[6], row[7], row[8], row[9], row[10]]; else return ['No data available'];
    }).filter(Boolean) : [['No data available']]));

    // Device specialization
    let hasDeviceRows = false; let deviceRows = [];
    Object.values(engineerKPIs).forEach(kpi => {
      if (kpi.deviceBreakdown && kpi.deviceBreakdown.length > 0) {
        kpi.deviceBreakdown.forEach((device, idx) => {
          const deviceName = device.deviceType === 'laptops_desktops' ? 'Laptops/Desktops' : device.deviceType === 'servers' ? 'Servers' : device.deviceType === 'macs' ? 'Macs' : device.deviceType === 'mobiles' ? 'Mobiles' : device.deviceType;
          const note = idx === 0 ? 'Primary focus' : idx === 1 ? 'Secondary' : '';
          deviceRows.push([kpi.initials, deviceName, device.total, device.avgPerDay, note]);
          hasDeviceRows = true;
        });
      }
    });
    if (hasDeviceRows) { csv.push(['ENGINEER DEVICE SPECIALIZATION (Last 30 Days)']); csv.push(['Engineer', 'Device Type', 'Total Count', 'Avg Per Day', 'Notes']); csv.push(...deviceRows); csv.push([]); }

    if (categoryRows.length > 0) { csv.push(['BREAKDOWN BY CATEGORY']); csv.push(['Category', 'Count']); csv.push(...categoryRows); csv.push([]); }
    if (categoryTopPerformers.length > 0) { csv.push(['TOP PERFORMERS BY CATEGORY']); csv.push(['Category', 'Engineer', 'Count']); csv.push(...categoryTopPerformers); }

    if (isMonthlyReport) {
      try {
        const monthDate = new Date(targetDate); const year = monthDate.getFullYear(); const month = monthDate.getMonth(); const firstDay = new Date(year, month, 1).toISOString().split('T')[0]; const lastDay = new Date(year, month + 1, 0).toISOString().split('T')[0];
        const res = await fetch(`/metrics/engineers/weekly-stats?startDate=${firstDay}&endDate=${lastDay}`);
        if (res.ok) {
          const data = await res.json();
          if (data.engineers && data.engineers.length > 0) {
            csv.push([]); csv.push(['ENGINEER WEEKLY BREAKDOWN']); csv.push(['Engineer', 'Device Type', 'Week 1', 'Week 2', 'Week 3', 'Week 4', 'Week 5', 'Monthly Total']);
            data.engineers.forEach(eng => { const row = [eng.initials, eng.device_type]; for (let week = 1; week <= 5; week++) row.push(eng.weekly_breakdown[week] || 0); row.push(eng.total); csv.push(row); });
          }
        }
      } catch (err) { console.error('Failed to fetch engineer weekly stats:', err); }

      if (isLastMonth) {
        try {
          const currentMonth = new Date(targetDate); const year = currentMonth.getFullYear(); const month = currentMonth.getMonth(); const currentStart = new Date(year, month, 1).toISOString().split('T')[0]; const currentEnd = new Date(year, month + 1, 0).toISOString().split('T')[0];
          const prevMonth = new Date(year, month - 1, 1); const prevStart = prevMonth.toISOString().split('T')[0]; const prevEnd = new Date(prevMonth.getFullYear(), prevMonth.getMonth() + 1, 0).toISOString().split('T')[0];
          const res = await fetch(`/metrics/month-comparison?currentStart=${currentStart}&currentEnd=${currentEnd}&previousStart=${prevStart}&previousEnd=${prevEnd}`);
          if (res.ok) {
            const data = await res.json();
            csv.push([]); csv.push(['MONTH-OVER-MONTH COMPARISON']); csv.push(['Metric', 'Current Month', 'Previous Month', 'Change', 'Trend']); csv.push(['Total Erasures', data.current_month.total, data.previous_month.total, `${data.comparison.change > 0 ? '+' : ''}${data.comparison.change} (${data.comparison.change_percent}%)`, data.comparison.trend]); csv.push([]);
            csv.push(['Top Engineers Comparison']); csv.push(['Rank', 'Current Month', 'Erasures', 'Previous Month', 'Erasures']);
            for (let i = 0; i < 5; i++) {
              const current = data.current_month.top_engineers[i]; const previous = data.previous_month.top_engineers[i];
              csv.push([i + 1, current ? current.initials : '', current ? current.erasures : '', previous ? previous.initials : '', previous ? previous.erasures : '']);
            }
          }
        } catch (err) { console.error('Failed to fetch month comparison:', err); }
      }
    }

    csv.push([]); csv.push(['REPORT INFORMATION']); csv.push(['Report Type', isMonthlyReport ? 'Monthly Warehouse Erasure Statistics' : 'Daily Warehouse Erasure Statistics']); csv.push(['Target', `${target} erasures per day`]); csv.push(['Scope', isThisMonth ? 'Current month (to date)' : isLastMonth ? 'Previous month' : isThisWeek ? 'Current week (Monday to today)' : isLastWeek ? 'Previous week (Mon-Sun)' : 'Current day (real-time)']); csv.push(['Data Freshness', 'Real-time updates every 30 seconds']); csv.push(['Competitions', 'Speed Challenge (AM: 8-12, PM: 13:30-15:45) | Category Specialists | Consistency Kings/Queens']); csv.push([]);

    csv.push(['GLOSSARY & DEFINITIONS']); csv.push(['Term', 'Definition']); csv.push(['Status Indicator', 'ON TARGET (100%+) | APPROACHING (80-99%) | BELOW TARGET (<80%)']); csv.push(['On Pace', 'Engineer is performing at expected rate to meet daily target']); csv.push(['Exceeding Target', 'Engineer has already completed more than daily target']); csv.push(['7-Day Avg', 'Average daily erasures over the last 7 days']); csv.push(['30-Day Avg', 'Average daily erasures over the last 30 days (reflects device mix)']); csv.push(['Trend', 'IMPROVING (>10% increase) | DECLINING (>10% decrease) | STABLE']); csv.push(['Personal Best', 'Highest single-day erasure count achieved']); csv.push(['Consistency Score', 'Standard deviation of daily output (lower = more predictable)']); csv.push(['Days Active', 'Number of days with recorded activity this month']); csv.push(['Device Specialization', 'Shows which device types each engineer primarily works on']); csv.push(['Avg Gap', 'Average time between consecutive erasures (minutes)']); csv.push(['Std Dev', 'Standard Deviation - measure of consistency (lower is more consistent)']); csv.push(['Week Total', 'Sum of all erasures across 7-day period']); csv.push(['Daily Average', 'Total divided by number of days active']); csv.push(['Achievement Rate', 'Percentage of days hitting or exceeding daily target']);

    return csv.map(row => row.map(cell => `"${cell}"`).join(',')).join('\n');
  }

  async function downloadExcel() {
    const dateScope = document.getElementById('dateSelector')?.value || 'this-week';

    // Handle custom range - show modal if not yet selected
    if (dateScope === 'custom-range' && !window.customRangeData) {
      showCustomRangeModal();
      return;
    }

    let period = dateScope.replace(/-/g, '_');

    // Build custom range query params if applicable
    let customParams = '';
    if (dateScope === 'custom-range' && window.customRangeData) {
      const { startYear, startMonth, endYear, endMonth } = window.customRangeData;
      customParams = `&start_year=${startYear}&start_month=${startMonth + 1}&end_year=${endYear}&end_month=${endMonth + 1}`;
      period = 'custom_range';
    }

    let exportUrl, filename;

    if (window.currentDashboard === 1) {
      // QA dashboard export
      exportUrl = `/export/qa-stats?period=${period}${customParams}`;
      filename = window.customRangeData
        ? `qa-stats-${window.customRangeData.startYear}-${window.customRangeData.startMonth + 1}-to-${window.customRangeData.endYear}-${window.customRangeData.endMonth + 1}.xlsx`
        : `qa-stats-${dateScope}.xlsx`;
    } else {
      // Erasure dashboard export (engineer deep dive)
      exportUrl = `/export/engineer-deepdive?period=${period}${customParams}`;
      filename = window.customRangeData
        ? `engineer-deepdive-${window.customRangeData.startYear}-${window.customRangeData.startMonth + 1}-to-${window.customRangeData.endYear}-${window.customRangeData.endMonth + 1}.xlsx`
        : `engineer-deepdive-${dateScope}.xlsx`;
    }

    showExportLoading();

    try {
      const response = await fetch(exportUrl, { headers: { 'Authorization': 'Bearer Gr33n5af3!' } });

      if (!response.ok) {
        throw new Error(`Export failed: ${response.statusText}`);
      }

      const contentDisposition = response.headers.get('Content-Disposition');
      let serverFilename = null;
      if (contentDisposition) {
        const match = contentDisposition.match(/filename=([^;]+)/);
        if (match) serverFilename = match[1].replace(/"/g, '').trim();
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
      alert('Failed to download spreadsheet: ' + (error.message || error));
    } finally {
      hideExportLoading();
    }
  }

  function showExportLoading() { const modal = document.getElementById('exportLoadingModal'); if (modal) modal.classList.remove('hidden'); }
  function hideExportLoading() { const modal = document.getElementById('exportLoadingModal'); if (modal) modal.classList.add('hidden'); }

  function populateMonthOptions() {
    const startSelect = document.getElementById('rangeStartMonth');
    const endSelect = document.getElementById('rangeEndMonth');
    if (!startSelect || !endSelect) return;

    const now = new Date();
    const currentYear = now.getFullYear();
    const currentMonth = now.getMonth();
    const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
    const options = [];
    for (let year = currentYear - 2; year <= currentYear; year++) {
      const maxMonth = year === currentYear ? currentMonth : 11;
      for (let month = 0; month <= maxMonth; month++) options.push({ year, month, label: `${months[month]} ${year}` });
    }
    startSelect.innerHTML = options.map(opt => `<option value="${opt.year}-${opt.month}">${opt.label}</option>`).join('');
    endSelect.innerHTML = options.map(opt => `<option value="${opt.year}-${opt.month}">${opt.label}</option>`).join('');
    startSelect.value = `${currentYear}-0`;
    endSelect.value = `${currentYear}-${currentMonth}`;
  }

  function showCustomRangeModal() { const modal = document.getElementById('customRangeModal'); if (!modal) return; populateMonthOptions(); modal.classList.remove('hidden'); }
  function hideCustomRangeModal(revertSelector = true) { const modal = document.getElementById('customRangeModal'); if (modal) modal.classList.add('hidden'); if (revertSelector) { const selector = document.getElementById('dateSelector'); if (selector && !window.customRangeData) selector.value = 'this-week'; } }

  function handleCustomRangeConfirm() {
    const startSelect = document.getElementById('rangeStartMonth');
    const endSelect = document.getElementById('rangeEndMonth');
    if (!startSelect || !endSelect) return;
    const [startYear, startMonth] = startSelect.value.split('-').map(Number);
    const [endYear, endMonth] = endSelect.value.split('-').map(Number);
    if (startYear > endYear || (startYear === endYear && startMonth > endMonth)) { alert('Start month must be before or equal to end month'); return; }
    window.customRangeData = { startYear, startMonth, endYear, endMonth };
    hideCustomRangeModal(false);
    const selector = document.getElementById('dateSelector');
    const customOption = selector?.querySelector('option[value="custom-range"]');
    if (customOption) {
      const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
      customOption.textContent = `${months[startMonth]} ${startYear} - ${months[endMonth]} ${endYear}`;
    }
    // Trigger download via window API
    if (typeof window.downloadExcel === 'function') window.downloadExcel();
  }

  // Bind modal controls if present
  document.getElementById('rangeCancel')?.addEventListener('click', () => hideCustomRangeModal(true));
  document.getElementById('rangeConfirm')?.addEventListener('click', handleCustomRangeConfirm);
  document.getElementById('customRangeModal')?.addEventListener('click', (e) => { if (e.target.id === 'customRangeModal') hideCustomRangeModal(true); });
  document.getElementById('dateSelector')?.addEventListener('change', (e) => { if (e.target.value === 'custom-range') showCustomRangeModal(); });

  // Expose functions
  window.generateCSV = generateCSV;
  window.downloadExcel = downloadExcel;
  window.showExportLoading = showExportLoading;
  window.hideExportLoading = hideExportLoading;
  window.showCustomRangeModal = showCustomRangeModal;
  window.hideCustomRangeModal = hideCustomRangeModal;
  window.handleCustomRangeConfirm = handleCustomRangeConfirm;
  window.populateMonthOptions = populateMonthOptions;

  // --- Category rotator / top-by-type helpers migrated from app.js ---
  async function refreshTopByTypeAllScopes(type, listId) {
    const scopes = [
      { key: 'today', label: "Today" },
      { key: 'month', label: "This Month" },
      { key: 'all', label: "All Time" }
    ];
    const results = {};
    let monthData = null;
    let allTimeData = null;
    for (const scope of scopes) {
      try {
        let url = `/metrics/engineers/top-by-type?type=${encodeURIComponent(type)}`;
        if (scope.key !== 'today') url += `&scope=${scope.key}`;
        const res = await fetch(url);
        let data = await res.json();
        let total = 0;
        try {
          let totalUrl = `/metrics/total-by-type?type=${encodeURIComponent(type)}&scope=${scope.key}`;
          const totalRes = await fetch(totalUrl);
          const totalData = await totalRes.json();
          total = typeof totalData.total === 'number' ? totalData.total : 0;
        } catch (err) {
          total = (data.engineers || []).reduce((sum, e) => sum + (e.count || 0), 0);
        }
        if (scope.key === 'month') monthData = data.engineers;
        if (scope.key === 'all') allTimeData = data.engineers;
        results[scope.key] = { engineers: data.engineers, label: scope.label, total };
      } catch (err) {
        results[scope.key] = { engineers: [], label: scope.label, total: 0 };
        console.error('Top-by-type refresh error:', type, scope.key, err);
      }
    }
    if (!results.all) results.all = { engineers: [], label: 'All Time', total: 0 };
    window._categoryFlipData = window._categoryFlipData || {};
    window._categoryFlipData[listId] = results;
    renderTopListWithLabel(listId, results.today.engineers, results.today.label, results.today.total);
  }

  function refreshAllTopListsWithFlip() {
    categories.forEach(c => refreshTopByTypeAllScopes(c.key, c.listId));
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
        const todayCountEl = document.getElementById(cat.todayCountId); if (todayCountEl) todayCountEl.textContent = todayTotal;
        renderTopList(cat.monthListId, monthData.engineers);
        const monthCountEl = document.getElementById(cat.monthCountId); if (monthCountEl) monthCountEl.textContent = monthTotal;
        renderTopList(cat.allTimeListId, allTimeData.engineers);
        const allTimeCountEl = document.getElementById(cat.allTimeCountId); if (allTimeCountEl) allTimeCountEl.textContent = allTimeTotal;

      } catch (err) {
        console.error('Category rotator card refresh error:', cat.key, err);
      }
    }
  }

  function setupCategoryFlipCards() {
    if (!window._categoryFlipData) return;
    if (window._categoryFlipIntervals) window._categoryFlipIntervals.forEach(id => clearInterval(id));
    window._categoryFlipIntervals = [];
    categories.forEach(c => {
      const listId = c.listId; const el = document.getElementById(listId); if (!el) return;
      const header = el.parentElement.querySelector('.card-header, .category-header, .top-row, .card-title-row') || el.parentElement;
      let label = header.querySelector('.category-period-label');
      if (!label) {
        label = document.createElement('span');
        label.className = 'category-period-label';
        label.style = 'font-size:0.95em;color:var(--muted);margin-right:8px;vertical-align:middle;';
        const pip = header.querySelector('.pip, .pip-count, .pip-value, .pip-number, .pipNum, .pipnum, .pipnumtop, .pipnum-top, .pip-number-top, .pip-number');
        if (pip) header.insertBefore(label, pip); else header.appendChild(label);
      }
      let flipIndex = 0; const flipData = window._categoryFlipData[listId];
      const scopes = ['today','month','all'];
      function performFlip() {
        flipIndex = (flipIndex + 1) % scopes.length; const currentEl = document.getElementById(listId); if (!currentEl) return;
        currentEl.style.opacity = '0';
        setTimeout(() => {
          let data = flipData[scopes[flipIndex]]; if (!data) { flipIndex = 0; data = flipData[scopes[0]]; }
          renderTopListWithLabel(listId, data.engineers, data.label, data.total);
          void document.body.offsetHeight;
          const elAfterUpdate = document.getElementById(listId); if (elAfterUpdate) setTimeout(() => { elAfterUpdate.style.opacity = '1'; }, 50);
        }, 600);
      }
      setTimeout(() => { const intervalId = setInterval(performFlip, 20000); window._categoryFlipIntervals.push(intervalId); }, 2000);
    });
    if (!window._categoryFlipVisibilityHandler) {
      window._categoryFlipVisibilityHandler = function() { if (!document.hidden) { /* noop: ensures intervals remain */ } };
      document.addEventListener('visibilitychange', window._categoryFlipVisibilityHandler);
    }
  }

  window.refreshTopByTypeAllScopes = refreshTopByTypeAllScopes;
  window.refreshAllTopListsWithFlip = refreshAllTopListsWithFlip;
  window.refreshCategoryRotatorCards = refreshCategoryRotatorCards;
  window.setupCategoryFlipCards = setupCategoryFlipCards;

})();
// Erasure-specific loader/stub for future splitting.
// Placeholder to keep split structure consistent; extend when extracting erasure-specific code.
(function(){
  // No-op for now; erasure features remain in common.js until further extraction.
})();

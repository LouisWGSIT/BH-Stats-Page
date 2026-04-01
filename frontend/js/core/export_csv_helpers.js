// Helpers for export CSV generation to keep export_manager focused on orchestration.
(function () {
  function resolveScopeContext(dateScope) {
    const isThisWeek = dateScope === 'this-week';
    const isLastWeek = dateScope === 'last-week';
    const isThisMonth = dateScope === 'this-month';
    const isLastMonth = dateScope === 'last-month';
    const isMonthlyReport = isThisMonth || isLastMonth;
    const isWeeklyReport = isThisWeek || isLastWeek;

    const targetDate = new Date();
    let dateRangeStr = '';

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
      dateRangeStr = targetDate.toLocaleDateString('en-GB', { month: 'long', year: 'numeric' });
    } else if (isThisMonth) {
      targetDate.setDate(1);
      dateRangeStr = targetDate.toLocaleDateString('en-GB', { month: 'long', year: 'numeric' });
    } else {
      dateRangeStr = targetDate.toLocaleDateString('en-GB');
    }

    return {
      isThisWeek,
      isLastWeek,
      isThisMonth,
      isLastMonth,
      isMonthlyReport,
      isWeeklyReport,
      targetDate,
      dateRangeStr,
      currentTime: new Date().toLocaleTimeString('en-GB'),
    };
  }

  async function fetchSummaryMetrics({ dateScope, targetDate, isWeeklyReport, isMonthlyReport }) {
    let todayTotal = '0';
    let monthTotal = '0';
    let target = '500';

    if (!isWeeklyReport && !isMonthlyReport) {
      todayTotal = document.getElementById('totalTodayValue')?.textContent || '0';
      monthTotal = document.getElementById('monthTotalValue')?.textContent || '0';
      target = document.getElementById('erasedTarget')?.textContent || '500';
      return { todayTotal, monthTotal, target };
    }

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

    return { todayTotal, monthTotal, target };
  }

  async function fetchEngineerData({ dateScope, targetDate, isMonthlyReport, SHIFT_HOURS, formatTimeAgo }) {
    let allEngineersRows = [];
    let engineerKPIs = {};

    try {
      const res = await fetch(`/metrics/engineers/leaderboard?scope=${dateScope}&limit=50`);
      if (res.ok) {
        const data = await res.json();
        try {
          const kpiRes = await fetch('/metrics/engineers/kpis/all');
          if (kpiRes.ok) {
            const kpiData = await kpiRes.json();
            engineerKPIs = (kpiData.engineers || []).reduce((acc, kpi) => {
              acc[kpi.initials] = kpi;
              return acc;
            }, {});
          }
        } catch (err) {
          console.error('Failed to fetch engineer KPIs:', err);
        }

        allEngineersRows = (data.items || []).map((eng, idx) => {
          const erasures = eng.erasures || 0;
          const avgPerHour = isMonthlyReport
            ? (erasures / (targetDate.getDate() * SHIFT_HOURS)).toFixed(1)
            : (erasures / SHIFT_HOURS).toFixed(1);
          const lastActiveDisplay = isMonthlyReport ? 'N/A' : formatTimeAgo(eng.lastActive);
          const baseRow = [idx + 1, eng.initials || '', erasures, lastActiveDisplay, avgPerHour];
          if (engineerKPIs[eng.initials]) {
            const kpi = engineerKPIs[eng.initials];
            return [
              ...baseRow,
              kpi.avg7Day,
              kpi.avg30Day,
              kpi.trend,
              kpi.personalBest,
              kpi.consistencyScore,
              kpi.daysActiveMonth,
            ];
          }
          return baseRow;
        });
      }
    } catch (err) {
      console.error('Failed to fetch engineer data:', err);
    }

    return { allEngineersRows, engineerKPIs };
  }

  function collectCategoryRows({ categories, isMonthlyReport, isWeeklyReport }) {
    const categoryRows = [];
    try {
      if (!isMonthlyReport && !isWeeklyReport) {
        categories.forEach((cat) => {
          const count = document.getElementById(cat.countId)?.textContent || '0';
          categoryRows.push([cat.label, count]);
        });
      }
    } catch (err) {
      console.error('Failed to fetch category data:', err);
    }
    return categoryRows;
  }

  async function collectCategoryTopPerformers({ categories, isMonthlyReport, isWeeklyReport, targetDate }) {
    const categoryTopPerformers = [];
    try {
      if (!isMonthlyReport && !isWeeklyReport) {
        categories.forEach((cat) => {
          const listEl = document.getElementById(cat.listId);
          if (listEl) {
            const items = listEl.querySelectorAll('li');
            items.forEach((item) => {
              const text = item.textContent.trim();
              const parts = text.match(/(.+?)\s+(\d+)$/);
              if (parts) {
                categoryTopPerformers.push([cat.label, parts[1], parts[2]]);
              }
            });
          }
        });
      } else {
        const catOrder = ['laptops_desktops', 'servers', 'macs', 'mobiles'];
        const catNames = {
          laptops_desktops: 'Laptops/Desktops',
          servers: 'Servers',
          macs: 'Macs',
          mobiles: 'Mobiles',
        };
        const year = targetDate.getFullYear();
        const month = targetDate.getMonth();
        const firstDay = new Date(year, month, 1).toISOString().split('T')[0];
        const lastDay = new Date(year, month + 1, 0).toISOString().split('T')[0];
        const res = await fetch(`/competitions/category-specialists?startDate=${firstDay}&endDate=${lastDay}`);
        if (res.ok) {
          const data = await res.json();
          if (data.specialists) {
            catOrder.forEach((cat) => {
              (data.specialists[cat] || []).slice(0, 1).forEach((row) => {
                categoryTopPerformers.push([catNames[cat], row.initials || '', row.count || 0]);
              });
            });
          }
        }
      }
    } catch (err) {
      console.error('Failed to fetch category top performers:', err);
    }
    return categoryTopPerformers;
  }

  function buildReportTitles({ isThisMonth, isLastMonth, isThisWeek, isLastWeek, dateRangeStr }) {
    if (isThisMonth) {
      return {
        reportTitle: 'ITAD & SWAP Services - Date Erasure and QA Stats - THIS MONTH',
        reportSubtitle: `Monthly Report for: ${dateRangeStr}`,
      };
    }
    if (isLastMonth) {
      return {
        reportTitle: 'ITAD & SWAP Services - Date Erasure and QA Stats - LAST MONTH',
        reportSubtitle: `Monthly Report for: ${dateRangeStr}`,
      };
    }
    if (isLastWeek) {
      return {
        reportTitle: 'ITAD & SWAP Services - Date Erasure and QA Stats - LAST WEEK',
        reportSubtitle: `Weekly Report for: ${dateRangeStr}`,
      };
    }
    if (isThisWeek) {
      return {
        reportTitle: 'ITAD & SWAP Services - Date Erasure and QA Stats - THIS WEEK',
        reportSubtitle: `Current Week Status - ${dateRangeStr}`,
      };
    }
    return {
      reportTitle: 'ITAD & SWAP Services - Date Erasure and QA Stats',
      reportSubtitle: `Current Status - ${dateRangeStr}`,
    };
  }

  async function buildCsvRows(params) {
    const {
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
    } = params;

    const csv = [
      [reportTitle],
      [reportSubtitle],
      ['Generated:', new Date().toLocaleDateString('en-GB', { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' })],
      ['Time:', time],
      [],
      ['EXECUTIVE SUMMARY'],
      ['Key Metric', 'Value', 'Status/Target', 'Performance'],
    ];

    if (isMonthlyReport) {
      csv.push(['Monthly Total', monthTotal, `Expected: ~${parseInt(target) * daysInMonth}`, statusIndicator]);
      csv.push(['Daily Average', dailyAvg, 'Per day', `vs ${target} target`]);
      csv.push(['Days in Month', daysInMonth, 'Total days', isThisMonth ? `${daysRemaining} remaining` : 'Complete']);
      csv.push(['Achievement Rate', `${progressPercent}%`, 'of monthly expectation', progressPercent >= 100 ? 'Exceeded Target' : 'Below Target']);
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

    try {
      const [perfTrends, targetAchievement, records, weekly, _specialists, consistency] = await Promise.all([
        fetch(`/metrics/performance-trends?target=${target}`).then((r) => (r.ok ? r.json() : null)),
        fetch(`/metrics/target-achievement?target=${target}`).then((r) => (r.ok ? r.json() : null)),
        fetch('/metrics/records').then((r) => (r.ok ? r.json() : null)),
        fetch('/metrics/weekly').then((r) => (r.ok ? r.json() : null)),
        fetch('/competitions/category-specialists').then((r) => (r.ok ? r.json() : null)),
        fetch('/competitions/consistency').then((r) => (r.ok ? r.json() : null)),
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
        if (records.bestDay) {
          csv.push(['Best Day Ever', records.bestDay.count || 0, `Achieved on ${records.bestDay.date || 'N/A'}`]);
        }
        if (records.topEngineer) {
          csv.push(['Top Engineer (All-Time)', records.topEngineer.initials || '—', `${records.topEngineer.totalCount || 0} total erasures`]);
        }
        if (records.currentStreak !== undefined) {
          csv.push(['Current Streak', `${records.currentStreak || 0} days`, 'above daily target']);
        }
        csv.push([]);
      }

      if (weekly?.weekTotal || weekly?.daysActive) {
        if (weekly.weekStart && weekly.weekEnd) {
          csv.push([`Workweek: ${weekly.weekStart} to ${weekly.weekEnd}`]);
        }
        csv.push(['WEEKLY PERFORMANCE (Workweek Mon–Fri)']);
        csv.push(['Metric', 'Value', 'Comparison', 'Notes']);
        csv.push(['Week Total', weekly.weekTotal || 0, `${Math.round((weekly.weekTotal / (parseInt(target) * 5)) * 100)}% of weekly goal`, '']);
        csv.push(['Best Day', weekly.bestDayOfWeek?.count || 0, `(${weekly.bestDayOfWeek?.date || 'N/A'})`, weekly.bestDayOfWeek?.count >= parseInt(target) ? 'On Target' : 'Below Target']);
        csv.push(['Daily Average', weekly.weekAverage || 0, `vs ${target} target`, weekly.weekAverage >= parseInt(target) ? 'Above Target' : 'Below Target']);
        csv.push(['Days Active', weekly.daysActive || 0, 'out of 5 workdays', '']);
        csv.push([]);
      }

      if (consistency?.leaderboard?.length) {
        csv.push([]);
        csv.push(['CONSISTENCY KINGS/QUEENS', 'Steadiest pace - lowest variability']);
        csv.push(['Rank', 'Engineer', 'Erasures', 'Avg Pace (min)', 'Consistency Score']);
        csv.push(...consistency.leaderboard.map((row, idx) => [
          idx + 1,
          row.initials || '',
          row.erasures || 0,
          row.avgGapMinutes || 0,
          row.consistencyScore || 0,
        ]));
      }
    } catch (err) {
      console.error('Failed to fetch detailed metrics:', err);
    }

    if (!isMonthlyReport && !isWeeklyReport && allEngineersRows.length > 0) {
      csv.push(['TOP 3 ENGINEERS (Daily Leaders)']);
      csv.push(['Rank', 'Engineer', 'Erasures', 'Last Active', 'Status']);
      allEngineersRows.slice(0, 3).forEach((row) => {
        const erasures = parseInt(row[2]);
        const status = erasures >= parseInt(target) ? 'Exceeding Target' : 'On Pace';
        csv.push([row[0], row[1], row[2], row[3], status]);
      });

      if (allEngineersRows.length >= 2) {
        const lead = parseInt(allEngineersRows[0][2]);
        const second = parseInt(allEngineersRows[1][2]);
        const gap = lead - second;
        const gapPercent = Math.round((gap / second) * 100);
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
    csv.push(...(allEngineersRows.length > 0 ? allEngineersRows.map((row) => {
      const erasures = parseInt(row[2]);
      const pct = parseInt(target) > 0 ? Math.round((erasures / parseInt(target)) * 100) : 0;
      if (row.length > 5) {
        return [row[0], row[1], row[2], row[3], row[4], `${pct}%`, row[5], row[6], row[7], row[8], row[9], row[10]];
      }
      return null;
    }).filter(Boolean) : [['No data available']]));

    let hasDeviceRows = false;
    const deviceRows = [];
    Object.values(engineerKPIs).forEach((kpi) => {
      if (kpi.deviceBreakdown && kpi.deviceBreakdown.length > 0) {
        kpi.deviceBreakdown.forEach((device, idx) => {
          const deviceName = device.deviceType === 'laptops_desktops'
            ? 'Laptops/Desktops'
            : device.deviceType === 'servers'
            ? 'Servers'
            : device.deviceType === 'macs'
            ? 'Macs'
            : device.deviceType === 'mobiles'
            ? 'Mobiles'
            : device.deviceType;
          const note = idx === 0 ? 'Primary focus' : idx === 1 ? 'Secondary' : '';
          deviceRows.push([kpi.initials, deviceName, device.total, device.avgPerDay, note]);
          hasDeviceRows = true;
        });
      }
    });

    if (hasDeviceRows) {
      csv.push(['ENGINEER DEVICE SPECIALIZATION (Last 30 Days)']);
      csv.push(['Engineer', 'Device Type', 'Total Count', 'Avg Per Day', 'Notes']);
      csv.push(...deviceRows);
      csv.push([]);
    }

    if (categoryRows.length > 0) {
      csv.push(['BREAKDOWN BY CATEGORY']);
      csv.push(['Category', 'Count']);
      csv.push(...categoryRows);
      csv.push([]);
    }

    if (categoryTopPerformers.length > 0) {
      csv.push(['TOP PERFORMERS BY CATEGORY']);
      csv.push(['Category', 'Engineer', 'Count']);
      csv.push(...categoryTopPerformers);
    }

    if (isMonthlyReport) {
      try {
        const monthDate = new Date(targetDate);
        const year = monthDate.getFullYear();
        const month = monthDate.getMonth();
        const firstDay = new Date(year, month, 1).toISOString().split('T')[0];
        const lastDay = new Date(year, month + 1, 0).toISOString().split('T')[0];

        const res = await fetch(`/metrics/engineers/weekly-stats?startDate=${firstDay}&endDate=${lastDay}`);
        if (res.ok) {
          const data = await res.json();
          if (data.engineers && data.engineers.length > 0) {
            csv.push([]);
            csv.push(['ENGINEER WEEKLY BREAKDOWN']);
            csv.push(['Engineer', 'Device Type', 'Week 1', 'Week 2', 'Week 3', 'Week 4', 'Week 5', 'Monthly Total']);

            data.engineers.forEach((eng) => {
              const row = [eng.initials, eng.device_type];
              for (let week = 1; week <= 5; week++) {
                row.push(eng.weekly_breakdown[week] || 0);
              }
              row.push(eng.total);
              csv.push(row);
            });
          }
        }
      } catch (err) {
        console.error('Failed to fetch engineer weekly stats:', err);
      }

      if (isLastMonth) {
        try {
          const currentMonth = new Date(targetDate);
          const year = currentMonth.getFullYear();
          const month = currentMonth.getMonth();
          const currentStart = new Date(year, month, 1).toISOString().split('T')[0];
          const currentEnd = new Date(year, month + 1, 0).toISOString().split('T')[0];

          const prevMonth = new Date(year, month - 1, 1);
          const prevStart = prevMonth.toISOString().split('T')[0];
          const prevEnd = new Date(prevMonth.getFullYear(), prevMonth.getMonth() + 1, 0).toISOString().split('T')[0];

          const res = await fetch(`/metrics/month-comparison?currentStart=${currentStart}&currentEnd=${currentEnd}&previousStart=${prevStart}&previousEnd=${prevEnd}`);
          if (res.ok) {
            const data = await res.json();
            csv.push([]);
            csv.push(['MONTH-OVER-MONTH COMPARISON']);
            csv.push(['Metric', 'Current Month', 'Previous Month', 'Change', 'Trend']);
            csv.push([
              'Total Erasures',
              data.current_month.total,
              data.previous_month.total,
              `${data.comparison.change > 0 ? '+' : ''}${data.comparison.change} (${data.comparison.change_percent}%)`,
              data.comparison.trend,
            ]);
            csv.push([]);
            csv.push(['Top Engineers Comparison']);
            csv.push(['Rank', 'Current Month', 'Erasures', 'Previous Month', 'Erasures']);
            for (let i = 0; i < 5; i++) {
              const current = data.current_month.top_engineers[i];
              const previous = data.previous_month.top_engineers[i];
              csv.push([
                i + 1,
                current ? current.initials : '',
                current ? current.erasures : '',
                previous ? previous.initials : '',
                previous ? previous.erasures : '',
              ]);
            }
          }
        } catch (err) {
          console.error('Failed to fetch month comparison:', err);
        }
      }
    }

    csv.push([]);
    csv.push(['REPORT INFORMATION']);
    csv.push(['Report Type', isMonthlyReport ? 'Monthly Warehouse Erasure Statistics' : 'Daily Warehouse Erasure Statistics']);
    csv.push(['Target', `${target} erasures per day`]);
    csv.push(['Scope', isThisMonth ? 'Current month (to date)' : isLastMonth ? 'Previous month' : isThisWeek ? 'Current week (Monday to today)' : isLastWeek ? 'Previous week (Mon-Sun)' : 'Current day (real-time)']);
    csv.push(['Data Freshness', 'Real-time updates every 30 seconds']);
    csv.push(['Competitions', 'Speed Challenge (AM: 8-12, PM: 13:30-15:45) | Category Specialists | Consistency Kings/Queens']);

    csv.push([]);
    csv.push(['GLOSSARY & DEFINITIONS']);
    csv.push(['Term', 'Definition']);
    csv.push(['Status Indicator', 'ON TARGET (100%+) | APPROACHING (80-99%) | BELOW TARGET (<80%)']);
    csv.push(['On Pace', 'Engineer is performing at expected rate to meet daily target']);
    csv.push(['Exceeding Target', 'Engineer has already completed more than daily target']);
    csv.push(['7-Day Avg', 'Average daily erasures over the last 7 days']);
    csv.push(['30-Day Avg', 'Average daily erasures over the last 30 days (reflects device mix)']);
    csv.push(['Trend', 'IMPROVING (>10% increase) | DECLINING (>10% decrease) | STABLE']);
    csv.push(['Personal Best', 'Highest single-day erasure count achieved']);
    csv.push(['Consistency Score', 'Standard deviation of daily output (lower = more predictable)']);
    csv.push(['Days Active', 'Number of days with recorded activity this month']);
    csv.push(['Device Specialization', 'Shows which device types each engineer primarily works on']);
    csv.push(['Avg Gap', 'Average time between consecutive erasures (minutes)']);
    csv.push(['Std Dev', 'Standard Deviation - measure of consistency (lower is more consistent)']);
    csv.push(['Week Total', 'Sum of all erasures across 7-day period']);
    csv.push(['Daily Average', 'Total divided by number of days active']);
    csv.push(['Achievement Rate', 'Percentage of days hitting or exceeding daily target']);

    return csv;
  }

  window.ExportCsvHelpers = {
    resolveScopeContext,
    fetchSummaryMetrics,
    fetchEngineerData,
    collectCategoryRows,
    collectCategoryTopPerformers,
    buildReportTitles,
    buildCsvRows,
  };
})();

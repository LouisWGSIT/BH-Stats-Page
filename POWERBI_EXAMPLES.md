# Power BI Examples & Formulas

This document contains ready-to-use Power BI configurations and formulas.

## M Query Examples (Power Query Editor)

### 1. Daily Stats with Automatic Date Range

Use this query to automatically get the last 30 days:

```m
let
    EndDate = Date.From(DateTime.FixedLocalNow()),
    StartDate = Date.AddDays(EndDate, -30),
    StartDateText = Date.ToText(StartDate, "yyyy-MM-dd"),
    EndDateText = Date.ToText(EndDate, "yyyy-MM-dd"),
    URL = "http://your-domain.com/api/powerbi/daily-stats?start_date=" & StartDateText & "&end_date=" & EndDateText,
    Source = Json.Document(Web.Contents(URL)),
    Data = Source[data],
    ToTable = Table.FromList(Data, Splitter.SplitByNothing(), null, null, ExtraValues.Error),
    ExpandedColumns = Table.ExpandRecordColumn(ToTable, "Column1", {"date", "booked_in", "erased", "qa"}, {"date", "booked_in", "erased", "qa"}),
    DateType = Table.TransformColumnTypes(ExpandedColumns, {{"date", type date}, {"booked_in", Int64.Type}, {"erased", Int64.Type}, {"qa", Int64.Type}})
in
    DateType
```

### 2. Erasure Events with Error Tracking

```m
let
    URL = "http://your-domain.com/api/powerbi/erasure-events?start_date=2026-01-01",
    Source = Json.Document(Web.Contents(URL)),
    Data = Source[data],
    ToTable = Table.FromList(Data, Splitter.SplitByNothing(), null, null, ExtraValues.Error),
    Expanded = Table.ExpandRecordColumn(ToTable, "Column1", 
        {"timestamp", "date", "month", "event", "device_type", "initials", "duration_seconds", "error_type", "job_id"},
        {"timestamp", "date", "month", "event", "device_type", "initials", "duration_seconds", "error_type", "job_id"}),
    TypeConversion = Table.TransformColumnTypes(Expanded, {
        {"timestamp", type datetimezone},
        {"date", type date},
        {"event", type text},
        {"device_type", type text},
        {"initials", type text},
        {"duration_seconds", Int64.Type}
    })
in
    TypeConversion
```

### 3. Engineer Stats Leaderboard

```m
let
    URL = "http://your-domain.com/api/powerbi/engineer-stats",
    Source = Json.Document(Web.Contents(URL)),
    Data = Source[data],
    ToTable = Table.FromList(Data, Splitter.SplitByNothing(), null, null, ExtraValues.Error),
    Expanded = Table.ExpandRecordColumn(ToTable, "Column1", {"date", "initials", "count"}, {"date", "initials", "count"}),
    TypeConversion = Table.TransformColumnTypes(Expanded, {{"date", type date}, {"count", Int64.Type}})
in
    TypeConversion
```

## DAX Formulas

### KPIs & Measures

#### Total Erasures (Month to Date)
```dax
Total Erasures MTD = CALCULATE(
    SUM('Daily Stats'[erased]),
    DATESMTD('Daily Stats'[date])
)
```

#### Daily Average
```dax
Daily Average = DIVIDE(
    SUM('Daily Stats'[erased]),
    DISTINCTCOUNT('Daily Stats'[date]),
    0
)
```

#### Target Achievement %
```dax
Target Achievement % = 
VAR Target = 500
VAR Actual = SUM('Daily Stats'[erased])
RETURN
DIVIDE(Actual, Target, 0)
```

#### Days Above Target
```dax
Days Above Target = CALCULATE(
    DISTINCTCOUNT('Daily Stats'[date]),
    FILTER('Daily Stats', 'Daily Stats'[erased] >= 500)
)
```

#### Engineer Rank
```dax
Engineer Rank = RANK(
    SUM('Engineer Stats'[count]),
    CALCULATE(SUM('Engineer Stats'[count]), ALL('Engineer Stats'[initials])),
    0
)
```

#### Success Rate %
```dax
Success Rate = 
VAR SuccessCount = CALCULATE(COUNTROWS('Erasure Events'), 'Erasure Events'[event] = "success")
VAR TotalCount = CALCULATE(COUNTROWS('Erasure Events'))
RETURN
DIVIDE(SuccessCount, TotalCount, 0)
```

#### Average Erasure Duration
```dax
Avg Duration Minutes = DIVIDE(
    CALCULATE(SUM('Erasure Events'[duration_seconds])), 
    COUNTROWS('Erasure Events'), 
    0
) / 60
```

### Comparisons

#### WoW (Week-over-Week) Growth
```dax
WoW Growth % = 
VAR CurrentWeek = CALCULATE(
    SUM('Daily Stats'[erased]),
    FILTER(ALL('Daily Stats'[date]), 
        WEEKNUM('Daily Stats'[date]) = WEEKNUM(TODAY()))
)
VAR PreviousWeek = CALCULATE(
    SUM('Daily Stats'[erased]),
    FILTER(ALL('Daily Stats'[date]), 
        WEEKNUM('Daily Stats'[date]) = WEEKNUM(TODAY()) - 1)
)
RETURN
DIVIDE(CurrentWeek - PreviousWeek, PreviousWeek, 0)
```

#### MoM (Month-over-Month) Growth
```dax
MoM Growth % = 
VAR CurrentMonth = CALCULATE(
    SUM('Daily Stats'[erased]),
    DATESMTD('Daily Stats'[date])
)
VAR PreviousMonth = CALCULATE(
    SUM('Daily Stats'[erased]),
    DATESMTD(DATEADD('Daily Stats'[date], -1, MONTH))
)
RETURN
DIVIDE(CurrentMonth - PreviousMonth, PreviousMonth, 0)
```

## Recommended Dashboard Layout

### Page 1: Executive Summary
- **Top row:** 3 KPI Cards
  - Total Erased (MTD)
  - Daily Average
  - Target Achievement %
  
- **Middle:** Line chart showing 30-day trend

- **Bottom row:**
  - Clustered column chart (daily metrics)
  - Pie chart (by device type)

### Page 2: Detailed Analysis
- **Table:** All erasure events with filtering
  - Filterable by: date, device_type, initials, event
  
- **Scatter plot:** Duration vs Success Rate

- **Card:** Success Rate %

### Page 3: Engineer Performance
- **Table:** Engineer leaderboard (initials, total count, rank)
  
- **Line chart:** Top 5 engineers trend over time

- **Clustered column:** Engineer performance by device type

### Page 4: Status & Insights
- **KPIs:**
  - Days Above Target
  - Avg Duration
  - Success Rate
  - Most Active Engineer
  
- **Gauge chart:** Today's progress toward daily target

- **Text box:** Last 24 hours summary

## Best Practices

1. **Refresh Strategy:**
   - Set up automatic refresh every 15-30 minutes
   - Use Power BI Desktop → Publish to Power BI Service
   - Configure gateway for scheduled refresh

2. **Performance:**
   - Filter data by date range (avoid loading all historical data)
   - Use aggregations in Power BI to speed up large datasets
   - Consider yearly data export to separate file after archival

3. **Filters:**
   - Add slicers for: Date Range, Engineer, Device Type
   - Use parameters for dynamic date ranges
   - Create bookmarks for "Last 7 Days", "This Month", etc.

4. **Naming Convention:**
   - Prefix tables with underscore if they're staging: `_ErasureEvents_Raw`
   - Use friendly names for end users: "Daily Statistics" instead of "daily_stats_api"

## Example: Complete Dashboard Page

Here's a complete configuration for one page:

**Visual Name:** Daily Performance Overview

**Visuals (5 total):**

1. **Card - Today's Erasures**
   - Value: `SUM('Daily Stats'[erased])` filtered to TODAY()
   - Format: Number, thousands separator

2. **KPI - Target Progress**
   - Value: [Target Achievement %]
   - Target: 1 (100%)
   - Trend Axis: Last 7 days

3. **Line Chart - 30-Day Trend**
   - X-Axis: 'Daily Stats'[date]
   - Y-Axis: SUM('Daily Stats'[erased])
   - Legend: None
   - Add reference line at 500

4. **Clustered Column - Daily Metrics**
   - X-Axis: 'Daily Stats'[date]
   - Y-Axis: SUM('Daily Stats'[booked_in]), SUM('Daily Stats'[erased]), SUM('Daily Stats'[qa])
   - Legend: Top

5. **Table - This Week Details**
   - Columns: date, initials, erased, device_type
   - Sorted: date descending
   - Applied filters: Last 7 days

## Troubleshooting Formulas

### "Values do not match expected format"
- Ensure date columns are formatted as Date (YYYY-MM-DD)
- Check that numeric columns aren't text

### "Circular dependency"
- Avoid using calculated columns in formulas that reference themselves
- Use measures instead of calculated columns for aggregations

### Performance Issues
- Filter by date range in your query (add `start_date` parameter)
- Reduce refresh frequency in Power BI Service
- Archive old data to separate tables

---

Ready to build your dashboard! Start with the M queries and adjust for your needs.

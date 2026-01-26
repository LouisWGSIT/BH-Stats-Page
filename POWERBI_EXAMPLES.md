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

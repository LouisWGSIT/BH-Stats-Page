This file is being deleted as it is unnecessary.
# Power BI Integration Guide

This guide explains how to connect your Warehouse Stats application to Microsoft Power BI.

## Overview

Your FastAPI application now has dedicated Power BI endpoints that return data in a format optimized for Power BI's Web API connector. The endpoints support date range filtering for flexible data analysis.

## Available Endpoints

### 1. Daily Statistics
**Endpoint:** `/api/powerbi/daily-stats`

Returns daily aggregated statistics (booked in, erased, QA counts).

**Parameters:**
- `start_date` (optional): YYYY-MM-DD format (defaults to 30 days ago)
- `end_date` (optional): YYYY-MM-DD format (defaults to today)

**Example URL:**
```
http://your-domain.com/api/powerbi/daily-stats?start_date=2026-01-01&end_date=2026-01-22
```

**Response:**
```json
{
  "data": [
    {
      "date": "2026-01-21",
      "booked_in": 150,
      "erased": 520,
      "qa": 180
    },
    {
      "date": "2026-01-22",
      "booked_in": 145,
      "erased": 510,
      "qa": 175
    }
  ]
}
```

### 2. Detailed Erasure Events
**Endpoint:** `/api/powerbi/erasure-events`

Returns detailed erasure event records with timestamps and error information.

**Parameters:**
- `start_date` (optional): YYYY-MM-DD format
- `end_date` (optional): YYYY-MM-DD format
- `device_type` (optional): Filter by device type (laptops_desktops, servers, loose_drives, macs, mobiles)

**Example URL:**
```
http://your-domain.com/api/powerbi/erasure-events?start_date=2026-01-20&device_type=laptops_desktops
```

**Response:**
```json
{
  "data": [
    {
      "timestamp": "2026-01-22T14:30:45",
      "date": "2026-01-22",
      "month": "2026-01",
      "event": "success",
      "device_type": "laptops_desktops",
      "initials": "JD",
      "duration_seconds": 120,
      "error_type": null,
      "job_id": "job-12345"
    }
  ]
}
```

### 3. Engineer Statistics
**Endpoint:** `/api/powerbi/engineer-stats`

Returns engineer performance data aggregated by date.

**Parameters:**
- `start_date` (optional): YYYY-MM-DD format
- `end_date` (optional): YYYY-MM-DD format

**Example URL:**
```
http://your-domain.com/api/powerbi/engineer-stats?start_date=2026-01-01
```

**Response:**
```json
{
  "data": [
    {
      "date": "2026-01-22",
      "initials": "JD",
      "count": 45
    },
    {
      "date": "2026-01-22",
      "initials": "AB",
      "count": 38
    }
  ]
}
```

## Setting Up in Power BI

### Step 1: Open Power BI Desktop

1. Launch Microsoft Power BI Desktop
2. Click **Get Data** in the Home ribbon
3. Search for and select **Web**
4. Click **Connect**

### Step 2: Enter the API URL

In the **Web** dialog:
- **URL:** Enter your endpoint URL, for example:
  ```
  http://your-domain.com/api/powerbi/daily-stats
  ```
  
  Replace `your-domain.com` with your actual domain/server address

### Step 3: Configure Authentication (if needed)

If your API requires authentication:
1. Click **Advanced options**
2. In the HTTP request header parameters (if needed), you can add headers
3. For now, leave it blank unless your API has authentication enabled

**Note:** Your API currently has CORS enabled and allows all origins, so basic access should work.

### Step 4: Load the Data

1. Click **OK** (for standard) or **Invoke** (if you configured headers)
2. Power BI will connect to your API and show a preview of the data
3. The response wrapper has a `data` array - you may need to:
   - Click on the **data** column
   - Click **To Table** to expand the array into rows

### Step 5: Transform and Load

1. Once data is expanded, click **Load** to import it into Power BI
2. The data will appear in your model with proper columns
3. Set appropriate data types (dates, numbers, text)

### Step 6: Create Visualizations

Now you can create Power BI visualizations:

**Daily Stats Dashboard:**
- Card: Total Erased (sum of `erased`)
- Line chart: Erasure trend over time (`date` vs `erased`)
- Clustered column: Daily metrics (`date`, `booked_in`, `erased`, `qa`)

**Erasure Details:**
- Table: All events with filtering by `device_type`, `event`, `initials`
- Duration analysis: Average/Max `duration_seconds`
- Error analysis: Count by `error_type`

**Engineer Performance:**
- Leaderboard: Top engineers by `count`
- Trend: Engineer `count` over time by `initials`
- Combo chart: Multiple engineers' performance trends

## Advanced: Using Parameters for Dynamic Date Ranges

To make your Power BI report interactive with date filtering:

1. In Power BI, create parameters for `start_date` and `end_date`
2. In the Web data source settings, use URL parameters:
   ```
   http://your-domain.com/api/powerbi/daily-stats?start_date=[start_date]&end_date=[end_date]
   ```

3. Configure the parameters to accept date values
4. Power BI will refresh the data based on parameter changes

## Troubleshooting

### "Connection Failed" Error
- Verify your server/domain is accessible from your network
- Check that your API is running and responding
- Ensure firewall/network rules allow outbound HTTPS/HTTP

### "Invalid JSON" Error
- The API response should start with `{ "data": [...]}`
- If you see the data as nested, expand the `data` column in Power BI's query editor
- Right-click the `data` column → **To Table** → **Expand**

### No Data Returned
- Check your date range - default is 30 days if not specified
- Verify data exists in your database for the requested date range
- Test the endpoint in your browser: `http://your-domain.com/api/powerbi/daily-stats`

### Authentication Issues
- Currently, your API has CORS enabled for all origins
- If you add authentication later, you'll need to configure it in Power BI using Custom Headers or OAuth

## Example Power BI Queries

Here are some useful M queries you can use in Power BI Query Editor:

```m
// Daily stats with date filtering
let
    Source = Json.Document(Web.Contents("http://your-domain.com/api/powerbi/daily-stats?start_date=2026-01-01&end_date=2026-01-31")),
    Data = Source[data],
    Expanded = Table.ExpandRecordColumn(Data, "Column1", {"date", "booked_in", "erased", "qa"}),
    DateType = Table.TransformColumnTypes(Expanded, {{"date", type date}})
in
    DateType
```

## API Rate Limiting & Performance

- No rate limiting is currently implemented
- For large date ranges, the API may take longer to respond
- If querying more than 6 months of data, consider querying in chunks

## Security Considerations

⚠️ **Important:** Your API currently allows requests from any origin (CORS: "*")

For production:
1. Configure specific allowed origins in CORS
2. Consider adding API key authentication
3. Use HTTPS instead of HTTP
4. Consider IP whitelisting if only specific Power BI gateways need access

## Support

For questions or issues:
1. Check the API response in your browser first
2. Verify data exists in the SQLite database
3. Check the FastAPI logs for error messages

---

**Last Updated:** January 22, 2026
**API Framework:** FastAPI
**Database:** SQLite3

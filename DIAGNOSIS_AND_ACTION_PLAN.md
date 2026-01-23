# Dashboard Data Issue - Diagnosis & Action Plan

**Date:** January 23, 2026 | **Day 2 of Power BI Learning**

---

## 🔍 ROOT CAUSE ANALYSIS

### Why Your Dashboards Show Empty Data

Looking at your images and code, I've identified **3 critical issues**:

#### 1. **Data Not Being Written to `engineer_stats` Table** ❌
- Your `erasures` table has detailed events with `initials` (engineer codes)
- BUT the `engineer_stats` table (which Power BI uses) is **likely empty**
- **Why?** No code is populating `engineer_stats` when events are recorded

**Evidence:**
```python
# In database.py, the erasures table IS being written to (main.py does this)
db.add_erasure_event(event=event, device_type=device_type, initials=initials, ...)

# BUT engineer_stats is never updated when this happens
# This table is defined but abandoned!
```

#### 2. **Missing Data Aggregation Logic** ❌
- The `/api/powerbi/engineer-stats` endpoint queries `engineer_stats` table
- That table has no function writing to it
- Result: Endpoint returns empty array even if `erasures` has data

#### 3. **HTML Dashboard Pulling from Wrong Tables** ⚠️
- Your stats page (index.html) may be querying endpoints that return empty data
- Your Chart.js visualizations show axes but **no data points**
- This suggests the data exists in `erasures` but not in the aggregated tables the frontend uses

---

## ✅ What's Working

Your data pipeline is partially functional:
- ✅ Webhooks are receiving events correctly
- ✅ Events are being stored in `erasures` table
- ✅ Daily totals in `daily_stats` appear to be updating
- ✅ Power BI API endpoints exist and are properly structured
- ✅ Database schema is good

---

## 🛠️ The Fix (What You Need to Do This Week)

### Week 1 Tasks (Next 7 Days)

#### Task 1: Populate Engineer Stats Table (2 hours)
**When:** Today or tomorrow

```python
# Add this function to database.py (already exists for deduplication pattern)
def sync_engineer_stats_from_erasures():
    """Populate engineer_stats table from erasures table for missing dates"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Get all (date, initials) combos from erasures
    cursor.execute("""
        SELECT DISTINCT date, initials
        FROM erasures
        WHERE initials IS NOT NULL
    """)
    
    date_initials = cursor.fetchall()
    
    for date_str, initials in date_initials:
        # Count erasures for this date+engineer
        cursor.execute("""
            SELECT COUNT(1)
            FROM erasures
            WHERE date = ? AND initials = ? AND event = 'success'
        """, (date_str, initials))
        
        count = cursor.fetchone()[0]
        
        # Insert or update engineer_stats
        cursor.execute("""
            INSERT OR REPLACE INTO engineer_stats (date, initials, count)
            VALUES (?, ?, ?)
        """, (date_str, initials, count))
    
    conn.commit()
    conn.close()

# Call this on startup: db.sync_engineer_stats_from_erasures()
```

**Result:** Engineer stats dashboard will populate with data

---

#### Task 2: Verify API Endpoints Return Data (1 hour)
**When:** After Task 1

Test in your browser:
```
http://localhost:8000/api/powerbi/engineer-stats?start_date=2026-01-15&end_date=2026-01-23
```

You should see:
```json
{
  "data": [
    {"date": "2026-01-23", "initials": "AB", "count": 45},
    {"date": "2026-01-23", "initials": "CD", "count": 38}
  ]
}
```

If it's still empty, your `erasures` table has no data with engineer initials.

---

#### Task 3: Connect Power BI to Real Data (2 hours)
**When:** After Task 2

In Power BI Desktop:
1. Create 3 web queries:
   - `Engineer Daily Stats` → `/api/powerbi/engineer-stats`
   - `Raw Erasure Events` → `/api/powerbi/erasure-events`
   - `Daily Summary` → `/api/powerbi/daily-stats`

2. For each, transform the data:
   - Expand the `data` array column
   - Set date columns to Date type
   - Set count columns to Whole Number type

3. Create relationships:
   - `Engineer Daily Stats` (date, initials) ← → `Raw Erasure Events` (date, initials)

---

#### Task 4: Build Engineer KPI Dashboard (3 hours)
**When:** End of first week

Create 4 visualizations:
1. **Table:** Engineer Daily Leaderboard
   - Columns: Initials, Count, Date
   - Sort: Count DESC

2. **Card Visuals:** (One per top engineer)
   - Shows: Initials + Total Count for current week

3. **Line Chart:** Weekly Trend
   - X-axis: Date
   - Y-axis: Count
   - Legend: Each engineer as separate line

4. **Clustered Bar:** Engineer Comparison
   - X-axis: Initials
   - Y-axis: Sum of Count

---

### Critical Insight for Power BI Success

**Engineer initials must be captured at source:**

Currently your webhook likely receives:
```json
{
  "event": "success",
  "jobId": "12345",
  "deviceType": "laptops_desktops"
  // ← Missing "initials" field!
}
```

Should be:
```json
{
  "event": "success",
  "jobId": "12345",
  "deviceType": "laptops_desktops",
  "initials": "JD"  // ← Add this!
}
```

**Action:** Verify that your erasure system is sending engineer initials in the webhook payload. If it's not, that's why your engineer stats are empty.

---

## 📊 Where Data Should Flow

```
Erasure System
    ↓
POST /hooks/erasure-detail (with initials)
    ↓
database.erasures table ← [Has initials ✓]
    ↓
Manual Sync: sync_engineer_stats_from_erasures()
    ↓
database.engineer_stats table ← [Currently empty ✗]
    ↓
/api/powerbi/engineer-stats
    ↓
Power BI Dashboard ← [Shows empty ✗]
```

---

## 📁 Files to Focus On

### This Week's Files
1. **database.py** - Add `sync_engineer_stats_from_erasures()` function
2. **main.py** - Call sync function on startup
3. **Power BI Desktop** - Create engineer stats queries

### Don't Worry About Yet
- ❌ POWERBI_EXAMPLES.md (Reference only, not urgent)
- ❌ POWERBI_DOCUMENTATION_INDEX.md (Summary, not urgent)
- ❌ app-refactored.js (Old, keep for reference)
- ❌ REFACTORING_NOTES.md (Historical, not urgent)

---

## 🎓 Power BI Learning Path (Day 2 → Day 7)

### By End of Week You Should Know:

**Monday-Tuesday:**
- [ ] How to connect Web API to Power BI
- [ ] How to transform/expand nested JSON arrays
- [ ] Setting proper data types (Date, Number, Text)

**Wednesday-Thursday:**
- [ ] Creating basic visualizations (Table, Card, Line Chart)
- [ ] Using Slicers for filtering
- [ ] Building a dashboard layout

**Friday:**
- [ ] Using parameters for dynamic date ranges
- [ ] Creating simple DAX measures (Sum, Count, Average)
- [ ] Exporting/sharing Power BI reports

**Weekend Study:**
- Read: "Power BI - Engineer KPI Best Practices.md" (I'll create this)
- Watch: Microsoft Power BI 101 videos (30 min)

---

## 🚀 Self-Service Next Week

When you run out of premium requests, you should be able to:

1. **Test your own endpoints** - Check if API returns data
2. **Refresh Power BI queries** - Reload data without re-creating connections
3. **Create new visualizations** - Add KPI cards, charts, filters
4. **Troubleshoot** - Identify if issue is in database, API, or Power BI

**You won't need external help for:**
- Adding new engineers to the dashboard
- Changing date ranges for analysis
- Creating new Power BI visuals
- Testing data flow end-to-end

---

## 📝 Next Steps (Right Now)

### Immediate (Next 30 minutes)
1. [ ] Check if your `erasures` table has data with engineer initials
   ```bash
   # Run in terminal:
   sqlite3 warehouse_stats.db "SELECT COUNT(*) FROM erasures WHERE initials IS NOT NULL;"
   ```

2. [ ] Test a Power BI endpoint in your browser
   ```
   http://localhost:8000/api/powerbi/engineer-stats?start_date=2026-01-23&end_date=2026-01-23
   ```

### This Session (Next 2 hours)
1. [ ] Add the `sync_engineer_stats_from_erasures()` function
2. [ ] Call it on app startup
3. [ ] Verify engineer_stats table now has data
4. [ ] Test the endpoint again

### By End of Day
1. [ ] Create one Power BI query for engineer stats
2. [ ] Expand the data and verify it loads
3. [ ] Create a simple table visualization

---

## 🎯 Success Criteria

**When you see these, you've fixed it:**
- ✅ `http://localhost:8000/api/powerbi/engineer-stats` returns non-empty JSON
- ✅ Power BI shows data in the table visualization
- ✅ You can see engineer initials with their daily counts
- ✅ Charts show trends over time

**Then you're ready to build the full dashboard!**

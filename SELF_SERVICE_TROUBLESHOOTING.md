# Self-Service Troubleshooting Guide for Engineer Stats Dashboard

**Purpose:** Help you solve problems independently when premium requests run out

---

## 🔧 Checklist: Data Flow Diagnosis

When your Power BI dashboard shows empty data, follow this checklist:

### Step 1: Check Data at Source (5 minutes)

**Q: Do we have erasure events recorded?**

```bash
# Open terminal, run:
sqlite3 warehouse_stats.db "SELECT COUNT(*) as total_erasures FROM erasures;"
```

**If result is 0:**
- ❌ No events are being recorded
- 🔧 Solution: Check if webhooks are being sent correctly
- 📖 See: "Webhook Verification" section below

**If result is > 0:**
- ✅ Events are being recorded
- 👉 Go to Step 2

---

### Step 2: Check Engineer Initials Are Captured (5 minutes)

**Q: Are engineer initials being recorded in events?**

```bash
# Check how many events have engineer initials
sqlite3 warehouse_stats.db "SELECT COUNT(*) as with_initials FROM erasures WHERE initials IS NOT NULL;"
```

**If result is 0 or much lower than total:**
- ❌ Engineer initials not being sent in webhook
- 🔧 Solution: Verify webhook payload includes `"initials"` field
- 📖 See: "Fix: Engineer Initials Not Captured" section below

**If result is high (close to total):**
- ✅ Initials are being captured
- 👉 Go to Step 3

---

### Step 3: Check Aggregated Table (5 minutes)

**Q: Is the `engineer_stats` table populated?**

```bash
# Check engineer_stats table
sqlite3 warehouse_stats.db "SELECT COUNT(*) FROM engineer_stats;"
```

**If result is 0:**
- ❌ Aggregation is not happening
- 🔧 Solution: Run the sync function
- 📖 See: "Fix: Populate Engineer Stats Manually" section below

**If result is > 0:**
- ✅ Table is populated
- 👉 Go to Step 4

---

### Step 4: Test API Endpoint (5 minutes)

**Q: Does the API endpoint return data?**

Open your browser and visit:
```
http://localhost:8000/api/powerbi/engineer-stats?start_date=2026-01-20&end_date=2026-01-23
```

**If you see empty array `{"data": []}`:**
- ❌ API endpoint is not returning data
- 🔧 Solution: Run Step 3 fix, or check date range
- 📖 See: "Fix: Populate Engineer Stats Manually" section below

**If you see data with initials and counts:**
- ✅ API is working correctly
- 👉 Go to Step 5

---

### Step 5: Test Power BI Connection (10 minutes)

**Q: Is Power BI connecting to the API?**

In Power BI Desktop:
1. Go to **Home** → **Get Data** → **Web**
2. Enter: `http://localhost:8000/api/powerbi/engineer-stats`
3. Click **Load**
4. Check if data appears

**If Power BI shows "Connection Error":**
- ❌ Network or API issue
- 🔧 Solution: Check API is running, firewall rules
- 📖 See: "Fix: Power BI Connection Issues" section below

**If Power BI loads but shows no rows:**
- ❌ Query is successful but returns empty
- 🔧 Solution: Check Steps 1-4 above
- 📖 See: "Fix: Populate Engineer Stats Manually" section below

**If Power BI loads with data:**
- ✅ Everything is working!
- 👉 Issue is likely in your visualization/dashboard setup
- 📖 See: "Fix: Visualization Issues" section below

---

## 🛠️ Common Fixes

### Fix #1: Populate Engineer Stats Manually

**If your `engineer_stats` table is empty but `erasures` has data:**

**Option A: Using Python (Recommended)**

Run this in your terminal:

```bash
cd "c:\Users\Louisw\Documents\BH Stats Page"
source .venv/Scripts/activate
python3 << 'EOF'
import sqlite3
from pathlib import Path

DB_PATH = str(Path(__file__).parent / "warehouse_stats.db")
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

# Get all (date, initials) combos from erasures
cursor.execute("""
    SELECT DISTINCT date, initials
    FROM erasures
    WHERE initials IS NOT NULL
""")

date_initials = cursor.fetchall()
print(f"Found {len(date_initials)} unique (date, initials) combinations")

for date_str, initials in date_initials:
    # Count successful erasures for this date+engineer
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
print(f"Inserted/updated {len(date_initials)} records")
conn.close()
EOF
```

**Option B: Using SQL directly**

```bash
sqlite3 warehouse_stats.db << 'EOF'
DELETE FROM engineer_stats;

INSERT INTO engineer_stats (date, initials, count)
SELECT date, initials, COUNT(1) as count
FROM erasures
WHERE initials IS NOT NULL AND event = 'success'
GROUP BY date, initials;

SELECT 'Sync complete. Inserted ' || COUNT(*) || ' records' FROM engineer_stats;
EOF
```

**Verification:** Run Step 3 again to confirm table now has data.

---

### Fix #2: Engineer Initials Not Captured

**If your erasure system is not sending engineer initials:**

**Check your webhook payload:**

The webhook being sent to `/hooks/erasure-detail` must include initials. It should look like:

```json
{
  "event": "success",
  "jobId": "JOB-12345",
  "deviceType": "laptops_desktops",
  "initials": "JD",
  "timestamp": "2026-01-23T14:30:00Z"
}
```

**Acceptable field name variations** (the code handles these):
- `"initials"` ✅
- `"Engineer Initials"` ✅
- `"Engineer Initals"` ✅ (misspelled version)

**If your system sends initials under a different field name:**

Edit `main.py` line 167-168:
```python
# Find this line:
initials_raw = payload.get("initials") or payload.get("Engineer Initals") or payload.get("Engineer Initials") or ""

# Change to add your field name:
initials_raw = payload.get("YourFieldName") or payload.get("initials") or payload.get("Engineer Initals") or ""
```

**Restart the app:**
```bash
# In your FastAPI terminal, press Ctrl+C then restart
# Or kill and restart the process
```

**Verify:** Send a test webhook and check the erasures table:
```bash
sqlite3 warehouse_stats.db "SELECT initials, COUNT(*) FROM erasures WHERE date = date('now') GROUP BY initials;"
```

---

### Fix #3: Power BI Connection Issues

**Symptom:** "Connection error" when adding Web data source

**Cause #1: FastAPI not running**
```bash
# Check if it's running
curl http://localhost:8000/metrics/today

# If no response, restart:
cd "c:\Users\Louisw\Documents\BH Stats Page"
python main.py
```

**Cause #2: Firewall blocking port**
```bash
# Windows Firewall - Allow Python through:
# Settings → Privacy & Security → Firewall → Allow an app through firewall
# Find "Python" or "pythonXX.exe" → Allow
```

**Cause #3: Wrong URL**
- Check spelling of domain/IP address
- Ensure it matches where FastAPI is running
- Test in browser first:
  ```
  http://localhost:8000/api/powerbi/daily-stats
  ```

---

### Fix #4: Visualization Issues

**Symptom:** Data loads in Power BI but dashboard shows wrong data or blank visuals

**Common causes:**

1. **Date filter is wrong**
   - Check the date range in your visual filters
   - Your data must fall within the filtered dates
   - Test with "Last 30 days" filter

2. **Column not expanded**
   - When you load data, the `data` column might be nested
   - Right-click the `data` column → **Expand**
   - Select all fields to expand

3. **Data type is wrong**
   - Dates must be `Date` type, not `Text`
   - Numbers must be `Whole Number` or `Decimal Number`, not `Text`
   - Edit column types in Power BI's Power Query Editor

4. **Visual is using wrong aggregation**
   - For engineer counts, use **Sum** or **Max**
   - Not **Average** or **Count of** (those count rows, not values)

**Test your Power BI visual:**
1. Create a **Table** visual
2. Add columns: `date`, `initials`, `count`
3. Check if data appears
4. If yes, the issue is with your other visuals (fix their settings)
5. If no, the issue is earlier in the pipeline (run Steps 1-4 above)

---

## 🔍 Database Inspection Commands

Use these to understand your data:

```bash
# Quick look at erasure events
sqlite3 warehouse_stats.db "SELECT date, initials, COUNT(*) FROM erasures GROUP BY date, initials LIMIT 10;"

# Check today's data
sqlite3 warehouse_stats.db "SELECT * FROM engineer_stats WHERE date = date('now');"

# Find engineers with most erasures
sqlite3 warehouse_stats.db "SELECT initials, COUNT(*) FROM erasures WHERE event='success' GROUP BY initials ORDER BY COUNT(*) DESC LIMIT 5;"

# Check daily stats
sqlite3 warehouse_stats.db "SELECT * FROM daily_stats WHERE date >= date('now', '-7 days');"

# See all tables
sqlite3 warehouse_stats.db ".tables"

# See table structure
sqlite3 warehouse_stats.db ".schema engineer_stats"
```

---

## 🚨 Emergency: Complete Data Reset

**Only do this if everything is corrupted and you want to start fresh:**

```bash
# Stop FastAPI (press Ctrl+C)

# Delete the database
rm warehouse_stats.db

# Restart FastAPI - it will create a fresh database
python main.py

# Start sending events again
```

---

## 📝 When to Ask for Help

You should be able to solve most issues with this guide. **Ask for help only if:**

- [ ] You've completed all 5 diagnostic steps
- [ ] You've tried at least 2 of the fixes
- [ ] You've verified step-by-step with the database commands
- [ ] You can provide the output of those commands
- [ ] You've checked the error messages carefully

**Prepare a problem report like this:**
```
Problem: Engineer stats showing as empty in Power BI
Step 1: erasures table has 0 records
Step 2: N/A (no records)
Step 3: engineer_stats table has 0 records
API Test: Returns {"data": []} 
Error Message: None

Actions Taken:
- Restarted FastAPI
- Checked firewall
- Sent test webhook

Suspicion: Engineer initials not being sent in webhook payload
```

---

## 📚 Knowledge You're Building

By using this guide, you're learning:
- ✅ Database queries and inspection
- ✅ API testing (in browser)
- ✅ Troubleshooting data pipelines
- ✅ Power BI data connection issues
- ✅ Webhook payload verification

**These skills are transferable to any data integration project!**

---

## Next: Power BI Learning Resources

Once data is flowing, focus on:
1. **DAX Formulas** - Create calculated columns (new engineer KPI metrics)
2. **Report Design** - Layout, colors, filtering best practices
3. **Parameters** - Dynamic date ranges, engineer filters
4. **Refresh Strategy** - Automatic vs manual data refresh

**Resources:**
- Microsoft Learn: "Power BI Fundamentals" (free)
- YouTube: Microsoft Power BI Channel (watch 5-minute tutorials)
- Book: "Power BI Basics" by Rob Collie (PDF available online)

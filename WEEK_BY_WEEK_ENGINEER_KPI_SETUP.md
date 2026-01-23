# Engineer KPI Dashboard - Week-by-Week Setup Guide

**Your Goal:** By end of Week 1, have a working engineer performance dashboard in Power BI  
**Your Focus:** Making weekly data appear on stats page → Updating Power BI with that data

---

## 📅 Week 1: Data Foundation & First Dashboard

### Monday (Today)

**Goal:** Understand why dashboards are empty + Have a plan

**Time:** 3 hours

**Tasks:**
- [ ] Read `DIAGNOSIS_AND_ACTION_PLAN.md` (key insight: engineer_stats table is empty)
- [ ] Run diagnostic check:
  ```bash
  sqlite3 warehouse_stats.db "SELECT COUNT(*) FROM engineer_stats;"
  ```
- [ ] Check if erasures have initials:
  ```bash
  sqlite3 warehouse_stats.db "SELECT COUNT(*) FROM erasures WHERE initials IS NOT NULL;"
  ```

**Decision Point:** 
- If erasures have initials → Engineer initials ARE being captured ✅
- If erasures don't have initials → Fix webhook payload ⚠️

**Deliverable:** Understand where the data gap is

**Quick Win:**
```bash
# See what engineer initials you have
sqlite3 warehouse_stats.db "SELECT DISTINCT initials FROM erasures LIMIT 10;"
```

---

### Tuesday-Wednesday

**Goal:** Populate engineer_stats table + Verify API returns data

**Time:** 4 hours total (2 per day)

**Tuesday Tasks:**
1. Add sync function to `database.py`
2. Call it on app startup
3. Verify engineer_stats table is populated

**Code to Add to database.py:**

```python
def sync_engineer_stats_from_erasures(date_str: str = None):
    """Populate engineer_stats from erasures for a date (or all recent dates if None)"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    if date_str:
        # Just one date
        cursor.execute("""
            SELECT DISTINCT initials FROM erasures WHERE date = ? AND initials IS NOT NULL
        """, (date_str,))
    else:
        # All recent dates with data
        cursor.execute("""
            SELECT DISTINCT date, initials FROM erasures 
            WHERE initials IS NOT NULL AND date >= date('now', '-30 days')
        """)
    
    records = cursor.fetchall()
    
    for record in records:
        if date_str:
            initials = record[0]
            target_date = date_str
        else:
            target_date, initials = record
        
        cursor.execute("""
            SELECT COUNT(1) FROM erasures 
            WHERE date = ? AND initials = ? AND event = 'success'
        """, (target_date, initials))
        
        count = cursor.fetchone()[0]
        cursor.execute("""
            INSERT OR REPLACE INTO engineer_stats (date, initials, count)
            VALUES (?, ?, ?)
        """, (target_date, initials, count))
    
    conn.commit()
    conn.close()
    print(f"Synced {len(records)} engineer_stats records")
```

**In main.py, add to startup:**

```python
@app.on_event("startup")
async def startup_event():
    """Start the background reset task"""
    # Add this line:
    db.sync_engineer_stats_from_erasures()
    asyncio.create_task(check_daily_reset())
```

**Wednesday Tasks:**
1. Test the API endpoint:
   ```
   http://localhost:8000/api/powerbi/engineer-stats?start_date=2026-01-15&end_date=2026-01-23
   ```
2. Verify it returns your engineer data
3. Take a screenshot of the response

**Deliverable:** Working API endpoint that returns engineer stats

---

### Thursday-Friday

**Goal:** Create first Power BI dashboard with engineer data

**Time:** 5 hours total (2.5 per day)

**Thursday Tasks:**
1. Open Power BI Desktop
2. Create new blank report
3. Add Web data source for engineer stats:
   - URL: `http://localhost:8000/api/powerbi/engineer-stats?start_date=2026-01-15&end_date=2026-01-23`
   - Expand the `data` array column
   - Set data types (date = Date, count = Whole Number)
   - Load into Power BI

4. Create your first visual: **Table**
   - Columns: date, initials, count
   - Sorting: count descending

**Friday Tasks:**
1. Add Card visualizations (one per top engineer):
   - Display engineer initials (large text)
   - Display count (large number)
   - Filter by engineer name

2. Add Line Chart:
   - X-axis: date
   - Y-axis: count
   - Legend: initials (each engineer as separate line)

3. Save Power BI file: `Engineer_KPI_Dashboard.pbix`

**Deliverable:** 3-visual dashboard showing engineer performance over time

---

### Friday Evening - Weekend Study

**Goal:** Understand Power BI fundamentals deeper

**Study Time:** 3 hours

**Watch:**
- [ ] Microsoft: "Power BI For Beginners" (30 min)
- [ ] YouTube: "Working with Web APIs in Power BI" (20 min)
- [ ] YouTube: "Creating KPI Dashboards in Power BI" (25 min)

**Read:**
- [ ] `POWERBI_EXAMPLES.md` - DAX formula examples (focus on measures)
- [ ] `POWERBI_SETUP.md` - Advanced section on parameters

**Practice:**
- [ ] Try adding a slicer to filter by date range
- [ ] Try adding a column chart (different from line chart)
- [ ] Experiment with colors and themes

---

## 📅 Week 2: Advanced Features & Integration

### Monday-Tuesday

**Goal:** Add interactive filters + Create parameter-based queries

**Time:** 4 hours

**Tasks:**
1. Add Slicer for date range selection
2. Make the Web data source use parameters:
   ```
   http://localhost:8000/api/powerbi/engineer-stats
   ?start_date=[StartDate]&end_date=[EndDate]
   ```

3. Create filters for specific engineers
4. Test that dashboard refreshes with different filters

**Deliverable:** Interactive dashboard - users can filter by date and engineer

---

### Wednesday-Thursday

**Goal:** Add device type breakdown to engineer stats

**Motivation:** Understand which engineers are specialists in which device categories

**Approach:**
1. Add new API endpoint to main.py:
   ```python
   @app.get("/api/powerbi/engineer-stats-by-type")
   async def engineer_stats_by_type(start_date: str = None, end_date: str = None):
       """Engineer stats broken down by device type"""
       # Query erasures grouped by date, initials, device_type
   ```

2. In Power BI, create new visual:
   - Clustered bar chart: Engineer vs Count, separate series per device type
   - This shows: "Who specializes in servers vs laptops?"

**Deliverable:** Device type breakdown in dashboard

---

### Friday

**Goal:** Create summary metrics + Weekly overview

**Tasks:**
1. Add Power BI measures:
   ```DAX
   Total Engineers = DISTINCTCOUNT(engineer_stats[initials])
   Avg Per Engineer = AVERAGE(engineer_stats[count])
   Top Engineer This Week = MAXX(VALUES(engineer_stats[initials]), CALCULATE(SUM(engineer_stats[count])))
   ```

2. Create "KPI Cards" showing:
   - Total erasures this week
   - Number of active engineers
   - Average per engineer
   - Top performer name

3. Create weekly comparison: Compare this week to last week

**Deliverable:** Full KPI dashboard with summary metrics + trends

---

## 🎯 Success Criteria by Week End

### Week 1 - Minimum (you can do this!)
- ✅ API endpoint returns engineer stats data
- ✅ Power BI connects successfully
- ✅ Dashboard shows table with: date, initials, count
- ✅ You understand the data flow

### Week 1 - Bonus (if you have time)
- ✅ Dashboard has 3+ visualizations
- ✅ Date filter works
- ✅ Engineer filter works

### Week 2 - Minimum
- ✅ Device type breakdown visible
- ✅ Summary KPI cards showing
- ✅ Weekly comparison metrics

---

## 🔧 Daily Checklist Template

Use this each day:

```
Date: Jan [XX], 2026
Task: [What you're working on]
Time Spent: [X hours]

✅ Completed:
- [ ] Item 1
- [ ] Item 2

⚠️ Blockers:
- [ ] Issue 1?
- [ ] Issue 2?

📊 Progress Photo:
[Screenshot of dashboard or terminal output]

Next Session Goal:
[What comes next]

Questions/Notes:
[Anything to remember]
```

---

## 📚 Learning Resources by Week

### Week 1
- **Microsoft Docs:** Power BI Web connector
- **Video:** YouTube - "Power BI Table Visualizations" (15 min)
- **Community:** Stack Overflow - Search "Power BI Web API"

### Week 2
- **Microsoft Docs:** DAX fundamentals
- **Video:** YouTube - "Power BI Measures and KPIs" (20 min)
- **Practice:** Try 3 different DAX formulas

---

## 🚀 After Week 2: What's Next

Once you have the engineer KPI dashboard working:

1. **Add Department Breakdown** (Week 3)
   - Group engineers by department
   - Show team performance vs individual

2. **Predictive Analytics** (Week 4)
   - Trend analysis: who's improving, who's declining
   - Forecasting: predict weekly totals based on daily pace

3. **Automated Refresh** (Week 2-3)
   - Set up Power BI Gateway for automatic daily refreshes
   - No manual refreshing needed

4. **Share & Collaborate** (Week 3)
   - Publish to Power BI Service
   - Share with team
   - Set up row-level security (if needed)

---

## 💡 Pro Tips for This Week

**Tip 1:** Keep a screenshot log
- Take before/after screenshots of each visual you create
- Helps you see progress and remember how you built things

**Tip 2:** Test endpoints in browser first
- Before Power BI, always test the API in your browser
- It's faster to diagnose issues this way

**Tip 3:** Save frequently**
- Power BI Desktop doesn't auto-save
- Ctrl+S after each visual change

**Tip 4:** Use Power Query Editor for practice
- It's the "backstage" of Power BI
- Learn how data flows through it
- You'll understand transformations better

**Tip 5:** Join Power BI community forums
- Microsoft Power BI Community (reddit)
- Microsoft Learn forums
- People solve your exact problems there

---

## 🆘 If You Get Stuck

**Stuck on API data?** → Run SELF_SERVICE_TROUBLESHOOTING.md step-by-step  
**Stuck on Power BI visual?** → Google "{your problem} Power BI" or YouTube search  
**Stuck on DAX formula?** → Microsoft Docs has formula library with examples  
**Completely lost?** → Re-read DIAGNOSIS_AND_ACTION_PLAN.md context section

**Rule:** Never spend more than 20 minutes on one problem before:
1. Taking a break
2. Checking documentation
3. Searching for the error message online
4. Asking in community forums

---

## 📞 Weekly Check-In Questions

Ask yourself these each Friday:

1. Can I test the API endpoint from my browser? ✅
2. Can I connect to the API from Power BI? ✅
3. Do I understand the data flow (erasures → engineer_stats → API → Power BI)? ✅
4. Have I created at least one working visualization? ✅
5. Do I know how to add a new engineer to the dashboard manually? ✅

**If "yes" to 4/5 → You're on track!**

---

## 🎓 Skills You'll Have By Week End

- ✅ Setting up Power BI Web data sources
- ✅ Transforming JSON data for analysis
- ✅ Creating interactive dashboards
- ✅ Writing basic DAX formulas
- ✅ Troubleshooting data pipeline issues
- ✅ Understanding your own data (erasures → engineer stats)
- ✅ Confidence to build your own dashboards

**These are highly valuable skills for any data role!**

---

## Final Notes

- Day 2 of Power BI is early - give yourself grace to learn
- This is a realistic, achievable plan
- By Friday, you'll have a functional dashboard
- By week 2, you'll have insights your team can use
- You're learning the right way (understanding data flow first, fancy visuals second)

**You've got this! 💪**

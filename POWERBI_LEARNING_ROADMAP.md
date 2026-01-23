# Power BI for Engineer KPI - Learning Roadmap

**Level:** Beginner (Day 2)  
**Goal:** Build engineer performance dashboards  
**Timeline:** 2 weeks to proficiency

---

## 🎯 Your Power BI Learning Path

### Week 1: Fundamentals
**Goal:** Understand the basics and build your first dashboard

#### Day 1-2: Core Concepts (2 hours)
**What to Learn:**
- What is Power BI (ecosystem overview)
- Desktop vs Service vs Report Builder
- Data models (tables, columns, relationships)
- Visualization basics (tables, cards, charts)

**Resources:**
- Microsoft Learn (free): ["Power BI Fundamentals"](https://learn.microsoft.com/en-us/training/modules/get-started-with-power-bi/)
- Time: 1 hour video + 30 min hands-on
- **Focus:** Getting data in → Visualizing data out

**Key Concepts to Know:**
- Columns = Fields (engineers, dates, counts)
- Rows = Records (each erasure event)
- Tables = Related data grouped together
- Visualizations = Charts/tables showing your data

**Practice:**
```
1. Create blank report
2. Add Table visual
3. Drag engineer initials and count to it
4. See data appear
5. Celebrate! 🎉
```

---

#### Day 3-4: Web Data Source (2 hours)
**What to Learn:**
- Using Web API connector in Power BI
- JSON data transformation
- Expanding nested arrays
- Handling date columns

**Resources:**
- Docs: [Power BI Web Connector](https://learn.microsoft.com/en-us/power-bi/connectors/connector-web)
- YouTube: "Power BI Web API in 5 minutes" (search this)
- Time: 30 min video + hands-on setup

**Key Concepts to Know:**
- Web.Contents() = Function to fetch URLs
- JSON = JavaScript Object Notation (data format from APIs)
- Expand = Convert nested arrays to rows
- Data Type = Tell Power BI if something is text, number, or date

**Practice:**
```
1. Get Data > Web
2. Paste: http://localhost:8000/api/powerbi/engineer-stats
3. Find "data" column with arrow icon
4. Click arrow > Select "Create new column from this data"
5. Now you have individual rows with date, initials, count
6. Set types: date=Date, count=Whole Number
7. Load into model
```

**Success:** Power BI shows a table with engineer data ✅

---

#### Day 5: Visualizations (2 hours)
**What to Learn:**
- Creating different chart types
- Adding fields to visualizations
- Changing colors and styling
- Filtering and slicing

**Resources:**
- Microsoft: [Power BI Visualizations](https://learn.microsoft.com/en-us/power-bi/visuals/)
- YouTube: "Power BI Visualization Types Explained" (15 min)
- Time: 1 hour learning + 1 hour hands-on

**Visualizations You'll Use for Engineer KPI:**

1. **Table**
   - Shows: All engineer data in rows
   - Use for: Detailed leaderboard
   - When: Need to see every engineer's count

2. **Card**
   - Shows: One number, big
   - Use for: Top engineer, total erasures
   - When: Want to highlight a single metric

3. **Line Chart**
   - Shows: Trend over time
   - Use for: Engineer performance week-by-week
   - When: Want to see if they're improving/declining

4. **Clustered Column (Bar Chart)**
   - Shows: Engineer comparison
   - Use for: Side-by-side engineer performance
   - When: Want to compare multiple engineers

5. **Clustered Bar Chart**
   - Shows: Multiple categories per engineer
   - Use for: Device type specialization (who does servers best?)
   - When: Want to segment by category

**Practice:**
```
Build these in order:
1. Create a Table (easiest)
   - Columns: initials, count, date
   
2. Create a Card (single metric)
   - Field: SUM(count) - shows total erasures

3. Create a Line Chart (trending)
   - X: date
   - Y: count
   - Legend: initials

4. Create a Bar Chart (comparison)
   - Y: initials
   - X: SUM(count)
   - Sort: descending by count

You just made 4 visualizations! 🎉
```

**Success:** Dashboard has multiple working visualizations ✅

---

#### Day 6-7: Interactivity (2 hours)
**What to Learn:**
- Slicers (filter buttons)
- Cross-filtering (click one visual, others update)
- Drill-through (detail views)
- Report filters

**Resources:**
- Docs: [Slicers in Power BI](https://learn.microsoft.com/en-us/power-bi/visuals/power-bi-visualization-slicers)
- YouTube: "Power BI Slicers and Filters" (10 min)
- Time: 1 hour learning + 1 hour hands-on

**Key Concepts to Know:**
- Slicer = Button/dropdown that filters all visuals
- Cross-filter = When one visual affects others
- Page filter = Filter for entire page
- Report filter = Filter across all pages

**Practice:**
```
Add to your dashboard:
1. Add Slicer (List) for Engineer Initials
   - Drag initials to a new "Slicer" visual
   - Click engineer names to filter all charts
   - Note: All other charts update automatically!

2. Add Slicer (Date Range) for dates
   - Drag date to new Slicer
   - Change type to "Between"
   - Drag the slider to filter by date

3. Save and test:
   - Pick engineer "JD"
   - Pick dates "Jan 15-23"
   - All visuals update to show just JD's data for those dates!
```

**Success:** Dashboard is interactive with filters ✅

---

### Week 2: Intermediate Power BI

#### Day 1-2: DAX (Formulas) Basics (3 hours)
**What to Learn:**
- What is DAX (Data Analysis eXpressions)
- Creating calculated columns
- Creating measures
- Common functions (SUM, AVG, COUNT, IF)

**Resources:**
- Microsoft Learn: [DAX Fundamentals](https://learn.microsoft.com/en-us/training/modules/dax-power-bi/)
- YouTube: "DAX Formulas for Beginners" (20 min)
- Time: 1 hour video + 2 hours hands-on

**Key Concepts:**
- Measure = Calculated value across many rows (e.g., average erasures)
- Column = Calculated value per row (e.g., engineer's name in CAPS)
- Context = What rows am I calculating for?
- Aggregation = Combining multiple rows into one number

**Common DAX Formulas for Engineer KPI:**

```DAX
-- Total engineers this week
Total Engineers = 
    DISTINCTCOUNT(engineer_stats[initials])

-- Average erasures per engineer
Average Per Engineer = 
    AVERAGE(engineer_stats[count])

-- Top engineer (name) - *Advanced*
Top Engineer = 
    MAXX(TOPN(1, SUMMARIZE(engineer_stats, engineer_stats[initials], "Total", SUM(engineer_stats[count])), [Total], DESC), engineer_stats[initials])

-- Running total (cumulative)
Running Total = 
    CALCULATE(SUM(engineer_stats[count]), 
              FILTER(ALL(engineer_stats), 
                     engineer_stats[date] <= MAX(engineer_stats[date])))
```

**Practice (Easier to Start):**
```
1. Create simple measures first:

Measure: Total Erasures This Period
Total Count = SUM(engineer_stats[count])

Measure: Average Per Engineer
Average Count = AVERAGE(engineer_stats[count])

Measure: Number of Engineers Active
Engineer Count = DISTINCTCOUNT(engineer_stats[initials])

2. Add these to your dashboard:
   - 3 Card visuals, one for each measure
   - Shows: Total | Average | # Engineers
```

**Success:** You have KPI cards showing summary metrics ✅

---

#### Day 3-4: Data Modeling (3 hours)
**What to Learn:**
- Creating relationships between tables
- Star schema (fact + dimension tables)
- Cardinality (one-to-many, many-to-one)
- Best practices for modeling

**Resources:**
- Docs: [Data Modeling in Power BI](https://learn.microsoft.com/en-us/power-bi/connect-data/service-datasets-understand)
- YouTube: "Power BI Data Modeling for KPIs" (20 min)
- Time: 1 hour learning + 2 hours hands-on

**For Your Engineer KPI Scenario:**

Your data naturally forms this structure:
```
engineer_stats (FACT table - the measurements)
├── date (Date field)
├── initials (Text - links to engineer)
└── count (Number - the measurement)

engineers (DIMENSION table - optional, to create later)
├── initials (Primary key)
├── name
├── department
└── start_date
```

**Why this matters:**
- Fact table = What happened (engineer did 45 erasures)
- Dimension table = Context about what (engineer is "John")
- Relationships = Link them together (initials = initials)

**When you add dimension table later:**
```
1. Create new query for engineers list
2. Add relationship: 
   engineer_stats[initials] ← → engineers[initials]
3. Now you can show engineer NAMES instead of initials
4. Sort/filter by engineer properties
```

**For now (stick with simple model):**
```
Just use engineer_stats table as-is
Add it multiple times if needed for different parts of dashboard
This is totally fine for Week 1-2!
```

---

#### Day 5-6: Advanced Visuals (2 hours)
**What to Learn:**
- Gauge charts (for targets/KPIs)
- Maps (if you track by location)
- Combo charts (mix line + bar)
- Conditional formatting (color by value)

**For Engineer KPI, focus on:**

1. **Gauge Chart**
   - Use: Show progress to target
   - Example: "45/50 erasures this week" with visual gauge
   - Setup: Field (count), Min (0), Max (target like 500 per week)

2. **Combo Chart**
   - Use: Show two metrics together
   - Example: Engineer count (line) + Daily average (bar)
   - Setup: X-axis (date), Line (avg), Column (count)

3. **Matrix/Heat Map**
   - Use: Engineer × Week performance grid
   - Example: Each cell shows engineer's weekly total
   - Setup: Rows (engineer), Columns (week), Values (sum of count)

---

#### Day 7: Putting It Together (3 hours)
**Create Your Final Week 2 Dashboard:**

Layout:
```
┌─────────────────────────────────────────┐
│ Engineer KPI Dashboard | Week of Jan 20 │
├─────────────────┬───────────────────────┤
│  Slicer:        │ Total Erasures: 2,450 │
│  Pick Week  ▼   │ Avg Per Engineer: 306 │
│  Pick Engineer▼ │ Active Engineers: 8   │
├─────────────────┴───────────────────────┤
│                                         │
│  Leaderboard (Table)                    │
│  ┌──────────────────────────────────┐  │
│  │ Rank │ Engineer │ Count │ Trend  │  │
│  │  1   │   JD     │  450  │   ↑    │  │
│  │  2   │   AB     │  380  │   →    │  │
│  │  3   │   CD     │  320  │   ↓    │  │
│  └──────────────────────────────────┘  │
│                                         │
│  Weekly Trend (Line Chart)              │
│  ┌──────────────────────────────────┐  │
│  │ Each engineer as separate line   │  │
│  │ Over 4-week period               │  │
│  └──────────────────────────────────┘  │
│                                         │
│  Engineer Comparison (Bar Chart)        │
│  ┌──────────────────────────────────┐  │
│  │ Sorted by highest count first    │  │
│  └──────────────────────────────────┘  │
└─────────────────────────────────────────┘
```

**Code to Create This:**

In Power BI, arrange these visuals:
1. 3 KPI Cards (top right)
2. Date Range Slicer (top left)
3. Table visual (middle)
4. Line Chart (bottom left)
5. Bar Chart (bottom right)

---

## 📚 Resources by Topic

### Getting Data
- [Power BI Web Connector](https://learn.microsoft.com/en-us/power-bi/connectors/connector-web)
- [Connecting to APIs](https://learn.microsoft.com/en-us/power-bi/connect-data/service-gateway-onprem)
- [JSON Transformation](https://learn.microsoft.com/en-us/power-bi/fundamentals/power-bi-service-overview)

### Creating Visuals
- [Visualization Types](https://learn.microsoft.com/en-us/power-bi/visuals/)
- [Table Visual](https://learn.microsoft.com/en-us/power-bi/visuals/power-bi-visualization-tables)
- [Line Chart](https://learn.microsoft.com/en-us/power-bi/visuals/power-bi-visualization-line-charts)
- [Bar & Column Charts](https://learn.microsoft.com/en-us/power-bi/visuals/power-bi-visualization-bar-charts)

### Data Analysis (DAX)
- [DAX Fundamentals](https://learn.microsoft.com/en-us/training/modules/dax-power-bi/)
- [DAX Function Library](https://learn.microsoft.com/en-us/dax/dax-function-reference)
- [Common DAX Formulas](https://learn.microsoft.com/en-us/power-bi/guidance/dax-sample-model)

### Dashboard Best Practices
- [Design a Dashboard](https://learn.microsoft.com/en-us/power-bi/create-reports/service-dashboards)
- [Dashboard Composition](https://learn.microsoft.com/en-us/power-bi/visuals/power-bi-visualization-best-practices)
- [KPI Dashboards](https://learn.microsoft.com/en-us/power-bi/create-reports/sample-customer-profitability)

### Community & Help
- [Microsoft Power BI Community](https://community.powerbi.com/)
- [Microsoft Learn Forums](https://learn.microsoft.com/en-us/answers/)
- [YouTube: Microsoft Power BI Channel](https://www.youtube.com/@MSPowerBI)

---

## 💡 Learning Tips

### Tip 1: Always Start with Data
- Before building visualizations, understand your data
- Print out sample data to see what you're working with
- Know: How many engineers? Date range? Count range?

### Tip 2: Learn by Doing
- Watch 5 min video
- Build it yourself (not copy-paste)
- Break it intentionally to understand
- Fix it yourself

### Tip 3: One Concept at a Time
- Don't learn DAX and visualizations simultaneously
- Master visualizations first (week 1)
- Learn DAX second (week 2)

### Tip 4: Save Frequently
- Power BI Desktop doesn't auto-save
- Ctrl+S after each change
- Version your file: `Engineer_KPI_v1.pbix`, `v2.pbix`, etc.

### Tip 5: Test Your Connections
- Always test API endpoint in browser first
- Verify data loads before building visuals
- Use [RequestBin](https://webhook.site) to test webhooks

---

## 🎓 Exercises

### Exercise 1: Basic Table (30 min)
**Goal:** Get data from API into Power BI as a table

```
1. Create new Power BI report
2. Get Data > Web
3. Enter: http://localhost:8000/api/powerbi/engineer-stats
4. Expand the 'data' column
5. Create Table visual with: date, initials, count
6. Success: You see engineer data in table form
```

### Exercise 2: Multiple Visuals (1 hour)
**Goal:** Create 4 different chart types

```
Using same data source, create:
1. Table (all data)
2. Card (total erasures)
3. Line Chart (trends)
4. Bar Chart (comparison)

Arrange them on one page
```

### Exercise 3: Add Interactivity (1 hour)
**Goal:** Make your dashboard filterable

```
Add slicers for:
1. Engineer initials (list slicer)
2. Date range (between slicer)

Test: Click engineer, all charts update
Test: Drag date slider, all charts update
```

### Exercise 4: Create KPI Measures (1.5 hours)
**Goal:** Write your first DAX formulas

```
Create measures for:
1. Total Count = SUM of all count values
2. Average Count = AVERAGE of count values
3. Engineer Count = DISTINCTCOUNT of initials

Add Card visuals showing each measure
```

---

## 🚀 After Week 2

You'll be ready to:
- [ ] Connect any REST API to Power BI
- [ ] Transform JSON data for analysis
- [ ] Create multi-visual dashboards
- [ ] Write basic DAX formulas
- [ ] Publish reports to Power BI Service
- [ ] Share dashboards with team
- [ ] Schedule automatic refreshes

---

## 📊 Self-Assessment

**By end of Week 1, you should answer "yes" to:**
- [ ] I can connect to a Web API from Power BI
- [ ] I can transform JSON arrays into Power BI tables
- [ ] I can create 5 different visualization types
- [ ] I understand what a slicer does
- [ ] I can arrange visuals in a dashboard layout

**By end of Week 2, you should answer "yes" to:**
- All of above, plus:
- [ ] I can write a basic DAX formula (SUM, AVERAGE)
- [ ] I can create KPI cards
- [ ] I can create a measure that calculates something complex
- [ ] I understand data modeling basics
- [ ] I can troubleshoot "blank data" issues

**If yes to 80%+, you've mastered the fundamentals! 🎉**

---

## 🆘 If You Get Stuck

**"How do I...?"** → Search: "[your question] Power BI site:microsoft.com"
**"Why doesn't my visual show data?"** → Read SELF_SERVICE_TROUBLESHOOTING.md
**"I don't understand DAX"** → Go back to simpler formulas, build up complexity
**"My API returns blank"** → Run database diagnostic commands (see guide)
**"I'm confused overall"** → Take a break, re-read WEEK_BY_WEEK_ENGINEER_KPI_SETUP.md

---

## 🎯 Final Note

Power BI is used in 90% of enterprise data teams. Learning it well opens doors:
- Better career opportunities
- More control over your data analysis
- Ability to build tools others depend on
- Understanding of modern analytics stacks

You're building genuine, valuable skills. Stick with it! 💪

**You've got this. Your Day 2 → Day 7 plan is realistic and doable.**

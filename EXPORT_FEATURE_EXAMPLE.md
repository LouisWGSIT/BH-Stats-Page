# Spreadsheet Export Feature Example

## Option 1: Simple CSV Export (No Libraries)

### Step 1: Add Download Button to HTML
Add this button to `index.html` (perhaps in the header):

```html
<div class="meta">
  <button id="downloadBtn" class="download-btn" title="Download stats as CSV">
    📥 Export
  </button>
  <span id="last-updated">Last updated: --</span>
  <span id="stale-indicator" class="stale hidden">Stale</span>
</div>
```

### Step 2: Add Button Styling to CSS
Add to `styles.css`:

```css
.download-btn {
  background: linear-gradient(145deg, rgba(140, 240, 74, 0.2), rgba(140, 240, 74, 0.1));
  border: 1px solid rgba(140, 240, 74, 0.4);
  color: #8cf04a;
  padding: 6px 12px;
  border-radius: 6px;
  font-weight: 700;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.3s ease;
  margin-right: 12px;
}

.download-btn:hover {
  background: linear-gradient(145deg, rgba(140, 240, 74, 0.3), rgba(140, 240, 74, 0.15));
  box-shadow: 0 4px 12px rgba(140, 240, 74, 0.2);
}

.download-btn:active {
  transform: scale(0.98);
}
```

### Step 3: Add Export Function to app.js

Add this function to your `app.js` (can go in the utilities section):

```javascript
function generateCSV() {
  const today = new Date().toLocaleDateString('en-GB');
  const todayTotal = DOM.totalTodayValue?.textContent || '0';
  const monthTotal = DOM.monthTotalValue?.textContent || '0';
  const target = DOM.erasedTarget?.textContent || '500';
  
  // Get leaderboard data
  const leaderboardRows = [];
  const rows = DOM.leaderboardBody?.querySelectorAll('tr') || [];
  rows.forEach((row, idx) => {
    const cells = row.querySelectorAll('td');
    if (cells.length >= 2) {
      const engineer = cells[0].textContent.trim();
      const erasures = cells[1].textContent.trim();
      leaderboardRows.push([idx + 1, engineer, erasures]);
    }
  });

  // Get category data
  const categoryRows = [];
  categories.forEach(cat => {
    const count = document.getElementById(cat.countId)?.textContent || '0';
    categoryRows.push([cat.label, count]);
  });

  // Build CSV
  const csv = [
    ['Warehouse Erasure Stats Report'],
    ['Generated:', today],
    [],
    ['SUMMARY'],
    ['Metric', 'Value'],
    ['Today Total', todayTotal],
    ['Month Total', monthTotal],
    ['Daily Target', target],
    [],
    ['TOP ENGINEERS (TODAY)'],
    ['Rank', 'Engineer', 'Erasures'],
    ...leaderboardRows,
    [],
    ['BREAKDOWN BY CATEGORY'],
    ['Category', 'Count'],
    ...categoryRows,
  ]
    .map(row => row.map(cell => `"${cell}"`).join(','))
    .join('\n');

  return csv;
}

function downloadCSV() {
  const csv = generateCSV();
  const filename = `warehouse-stats-${new Date().toISOString().split('T')[0]}.csv`;
  
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
  const link = document.createElement('a');
  const url = URL.createObjectURL(blob);
  
  link.setAttribute('href', url);
  link.setAttribute('download', filename);
  link.style.visibility = 'hidden';
  
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
}

// Add button listener (add near bottom of init code)
document.getElementById('downloadBtn')?.addEventListener('click', downloadCSV);
```

---

## Option 2: Excel Export (Using SheetJS Library)

More professional with formatting!

### Step 1: Add Script to HTML
```html
<script src="https://cdnjs.cloudflare.com/ajax/libs/xlsx/0.18.5/xlsx.min.js"></script>
```

### Step 2: Export Function
```javascript
function downloadExcel() {
  const today = new Date().toLocaleDateString('en-GB');
  const todayTotal = DOM.totalTodayValue?.textContent || '0';
  const monthTotal = DOM.monthTotalValue?.textContent || '0';

  // Create workbook
  const wb = XLSX.utils.book_new();

  // Sheet 1: Summary
  const summaryData = [
    ['Warehouse Erasure Stats'],
    ['Generated', today],
    [],
    ['Metric', 'Value'],
    ['Today Total', todayTotal],
    ['Month Total', monthTotal],
    ['Daily Target', DOM.erasedTarget?.textContent || '500'],
  ];
  const ws1 = XLSX.utils.aoa_to_sheet(summaryData);
  XLSX.utils.book_append_sheet(wb, ws1, 'Summary');

  // Sheet 2: Leaderboard
  const leaderboardData = [['Top Engineers (Today)']];
  leaderboardData.push(['Rank', 'Engineer', 'Erasures']);
  const rows = DOM.leaderboardBody?.querySelectorAll('tr') || [];
  rows.forEach((row, idx) => {
    const cells = row.querySelectorAll('td');
    leaderboardData.push([
      idx + 1,
      cells[0]?.textContent.trim() || '',
      cells[1]?.textContent.trim() || ''
    ]);
  });
  const ws2 = XLSX.utils.aoa_to_sheet(leaderboardData);
  XLSX.utils.book_append_sheet(wb, ws2, 'Leaderboard');

  // Sheet 3: Categories
  const categoryData = [['Category Breakdown']];
  categoryData.push(['Category', 'Count']);
  categories.forEach(cat => {
    categoryData.push([
      cat.label,
      document.getElementById(cat.countId)?.textContent || '0'
    ]);
  });
  const ws3 = XLSX.utils.aoa_to_sheet(categoryData);
  XLSX.utils.book_append_sheet(wb, ws3, 'Categories');

  // Download
  const filename = `warehouse-stats-${new Date().toISOString().split('T')[0]}.xlsx`;
  XLSX.writeFile(wb, filename);
}

document.getElementById('downloadBtn')?.addEventListener('click', downloadExcel);
```

---

## What The Output Looks Like

### CSV Example:
```
"Warehouse Erasure Stats Report"
"Generated:","14/01/2026"

"SUMMARY"
"Metric","Value"
"Today Total","63"
"Month Total","326"
"Daily Target","500"

"TOP ENGINEERS (TODAY)"
"Rank","Engineer","Erasures"
"1","KS","7"
"2","MS","14"
"3","MT","8"

"BREAKDOWN BY CATEGORY"
"Category","Count"
"Laptops / Desktops","63"
"Servers","0"
"Macs","0"
"Mobiles","9"
```

### Excel Example:
Multiple sheets:
- **Summary** - Key metrics
- **Leaderboard** - Top engineers ranked
- **Categories** - Breakdown by device type

---

## Which Should You Use?

| Feature | CSV | Excel |
|---------|-----|-------|
| Setup Time | 2 minutes | 5 minutes |
| File Size | Tiny | Small |
| Formatting | Plain text | Styled sheets |
| Multiple Sheets | No | Yes ✅ |
| External Libraries | No | Yes (CDN) |
| Browser Support | All | All |

**CSV** = Quick & simple
**Excel** = Professional & feature-rich

---

## Implementation Steps

1. Copy the button code into `index.html` header
2. Copy the CSS into `styles.css`
3. Copy the function into `app.js`
4. Add the event listener at the bottom of your init code
5. Test the download!

The button will appear in the header, and when clicked, it downloads a file with today's date like `warehouse-stats-2026-01-14.csv` or `.xlsx`

Want me to add this to your project?

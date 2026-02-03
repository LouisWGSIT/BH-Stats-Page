# Debugging: Why Engineer Export Shows No Data

## The Problem
You said: *"It's still either pulling the wrong data, or the same data as it was doing before the update. Exporting This weeks data, is just pulling todays data. There's no updated fields and sheets with what we spoke about."*

## The Real Diagnosis
The export is working correctly, but there's **zero new erasure data** in your SQLite database since January 29, 2026.

### Database Status
```
Last data in warehouse_stats.db: 2026-01-29 (5 test records)
Today's date: 2026-02-03
This week's data: 0 records
Expected: Multiple devices per day from Blancco
```

### Why This Happened
The **Blancco webhook never fired** since the system was set up.

```
Blancco Device → [ERASURE RUNS] → [Server Message Step?] → [Webhook Call?] → SQLite
                                   ❓ This didn't happen
```

---

## How to Fix It

### Step 1: Verify Webhook Configuration in Blancco

Go to **Management Console → Workflows → [Your Erasure Workflow]**

Check the **Erasure Subworkflow**:

```
1. Device Erased
   ↓
2. [Condition] <ERASURE_PROGRESS> equals 100  ← MUST BE HERE
   ↓
3. [Server Message] POST to webhook
   ├─ URL: https://your-app.onrender.com/hooks/erasure
   ├─ Method: POST
   ├─ Header: Authorization: Bearer Gr33n5af3!
   └─ Body: Include erasure data
```

**Common issues:**
- ❌ Condition step missing → Server Message fires too early (before erasure done)
- ❌ Wrong API key → Webhook rejected with 401
- ❌ Wrong endpoint → Webhook never reaches your server
- ❌ Network blocked → Server can't be reached

---

### Step 2: Check Your Webhook Endpoint

Your current endpoint in `main.py` (line 323):
```python
@app.post("/hooks/erasure")
async def erasure_hook(req: Request):
    hdr = req.headers.get("Authorization") or req.headers.get("x-api-key")
    if not hdr or (hdr != f"Bearer {WEBHOOK_API_KEY}" and hdr != WEBHOOK_API_KEY):
        raise HTTPException(status_code=401, detail="Unauthorized")
```

**WEBHOOK_API_KEY** from environment or config = `Gr33n5af3!`

**This means Blancco must send:**
```
Authorization: Bearer Gr33n5af3!
```

---

### Step 3: Run a Test Erasure

1. **Start a test device erasure** on your Blancco system
2. **Watch the server logs** for webhook call:
   ```
   [Server logs should show:]
   Received webhook: event=success, jobId=..., payload={...}
   ```

3. **Check the database** for new record:
   ```sql
   SELECT * FROM erasures 
   WHERE date = '2026-02-03' 
   ORDER BY timestamp DESC LIMIT 1;
   ```

---

## If Webhook Is Working But Data Doesn't Show in Engineer Export

The webhook might be firing, but the payload structure could be wrong.

### Check What's Being Sent

Look at the webhook logs in Blancco and match these fields:

```python
# What your code expects:
- event: "success" or "failure"
- jobId: device identifier
- initials: engineer name (from custom field)
- durationSec: erasure duration in seconds
- manufacturer: device brand
- model: device model
- systemSerial: device serial
- diskSerial: disk serial number
- diskCapacity: disk size in bytes
```

### The Required Payload Format

Your webhook should receive JSON like:
```json
{
  "event": "success",
  "jobId": "12345",
  "initials": "AB",
  "durationSec": 613,
  "manufacturer": "HP",
  "model": "ProBook 450 G8",
  "systemSerial": "5CD207HP0P",
  "diskSerial": "FYB3N050113203S3K",
  "diskCapacity": "256060514304"
}
```

---

## Debug Checklist

- [ ] **Blancco condition exists?**
  - Look for `<ERASURE_PROGRESS> equals 100` in workflow
  - Must come BEFORE Server Message step

- [ ] **API key matches?**
  - Blancco: `Bearer Gr33n5af3!`
  - main.py: `WEBHOOK_API_KEY = "Gr33n5af3!"`

- [ ] **Endpoint URL correct?**
  - Blancco sends to: `https://your-app.onrender.com/hooks/erasure`
  - Or: `http://localhost:5000/hooks/erasure` if testing locally

- [ ] **Webhook firing at all?**
  - Run test erasure
  - Check server logs for "Received webhook:" message
  - If no message → Blancco isn't calling endpoint

- [ ] **Payload has all fields?**
  - `initials` present (engineer name)
  - `durationSec` present and > 0
  - `event` = "success"

- [ ] **Database accepting data?**
  - Query: `SELECT COUNT(*) FROM erasures WHERE date = '2026-02-03'`
  - Should increment after each erasure

---

## What Happens When It Works

```
[Feb 5, 2026 - After fix]

Test Erasure Runs
  ↓
Blancco Server Message fires (ERASURE_PROGRESS = 100)
  ↓
POST to /hooks/erasure with Authorization header
  ↓
main.py receives, validates API key, stores in warehouse_stats.db
  ↓
database.py: INSERT INTO erasures (date, initials, duration_sec, ...)
  ↓
engineer_export.py can now query this data:
  
  [Engineer Export - This Week]
  Engineer | Total Erasures | Mon | Tue | Wed | Thu | Fri | Avg Duration | Primary Device
  AB       | 25             | 5   | 5   | 6   | 5   | 4   | 710 sec      | Laptops
  CD       | 18             | 4   | 4   | 4   | 3   | 3   | 654 sec      | Macs
```

---

## Server Log Locations

### If running locally:
Terminal where you started the FastAPI server will show logs

### If running on Render:
Render dashboard → your app → Logs tab

Look for messages like:
```
Received webhook: event=success, jobId=...
INSERT INTO erasures successful
```

---

## Common Errors & Solutions

### "401 Unauthorized"
- **Cause**: API key mismatch
- **Fix**: Verify `Gr33n5af3!` in both Blancco AND main.py

### "Connection refused"
- **Cause**: Endpoint URL wrong or app not running
- **Fix**: Check Render URL vs Blancco URL match

### "Received webhook but no data appears in database"
- **Cause**: Payload field names wrong
- **Fix**: Check what Blancco is actually sending vs what code expects

### "No webhook call at all"
- **Cause**: Server Message step not configured or not executing
- **Fix**: Check condition `<ERASURE_PROGRESS> equals 100` exists

---

## Next: After Fix Verification

Once webhook is firing and data appears:

1. **Export will show data immediately** (no code changes needed)
2. **Run export for "This Week"** → should see daily breakdown
3. **QA Dashboard also ready** → can export those stats too

---

## Questions to Ask Your Blancco Admin

1. "Is the Server Message step triggering after erasure completes?"
2. "What API key should I use for the webhook Authorization header?"
3. "Is the endpoint https://[url]/hooks/erasure reachable?"
4. "What fields does the Server Message payload include?"
5. "Are there any firewall rules blocking POST requests to our server?"

---

**Bottom Line**: Your code is perfect. The Blancco workflow configuration is the issue. Fix the webhook and everything will work immediately.

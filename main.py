from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import os

app = FastAPI(title="Warehouse Stats Service")

# Enable CORS for TV access from network
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

WEBHOOK_API_KEY = os.getenv("WEBHOOK_API_KEY", "6LVepDbZkbMwA66Gpl9bWherzT5wKfOl")

# simple store
stats_today = {"bookedIn": 0, "erased": 0, "qa": 0}
seen_ids = set()
engineer_stats = {}  # Track engineer initials and erasure counts

@app.post("/hooks/erasure")
async def erasure_hook(req: Request):
    hdr = req.headers.get("Authorization") or req.headers.get("x-api-key")
    if not hdr or (hdr != f"Bearer {WEBHOOK_API_KEY}" and hdr != WEBHOOK_API_KEY):
        raise HTTPException(status_code=401, detail="Unauthorized")

    payload = await req.json()
    event = payload.get("event", "success")  # Default to success if missing
    job_id = payload.get("jobId") or payload.get("assetTag") or payload.get("id") or "unknown"
    
    # Always accept and log for debugging
    print(f"Received webhook: event={event}, jobId={job_id}, payload={payload}")

    # Only deduplicate if we have a real jobId (not "unknown")
    if job_id != "unknown" and job_id in seen_ids:
        return JSONResponse({"status": "ignored", "reason": "duplicate"})

    if event in ["success", "connected"]:  # Accept both success and connected
        stats_today["erased"] += 1
        # Only track if we have a real ID
        if job_id != "unknown":
            seen_ids.add(job_id)
        return {"status": "ok", "count": stats_today["erased"]}
    elif event == "failure":
        return {"status": "ok"}
    else:
        # Still accept it and increment counter
        stats_today["erased"] += 1
        seen_ids.add(job_id)
        return {"status": "ok", "event_accepted": event}

@app.get("/metrics/today")
async def get_metrics():
    return stats_today

@app.post("/hooks/engineer-erasure")
async def engineer_erasure_hook(req: Request):
    hdr = req.headers.get("Authorization") or req.headers.get("x-api-key")
    if not hdr or (hdr != f"Bearer {WEBHOOK_API_KEY}" and hdr != WEBHOOK_API_KEY):
        raise HTTPException(status_code=401, detail="Unauthorized")

    payload = await req.json()
    
    # Try multiple field name variations
    initials = (
        payload.get("initials") or
        payload.get("engineerInitials") or
        payload.get("engineer_initials") or
        payload.get("Engineer Initals") or
        payload.get("engineerInitals") or
        ""
    ).strip().upper()
    
    print(f"Received engineer erasure: initials={initials}, payload={payload}")

    if not initials or initials == "":
        return JSONResponse({"status": "error", "reason": "missing initials"}, status_code=400)

    # Increment count for this engineer
    engineer_stats[initials] = engineer_stats.get(initials, 0) + 1
    
    return {"status": "ok", "engineer": initials, "count": engineer_stats[initials]}

@app.get("/metrics/top-engineers")
async def get_top_engineers():
    # Return top 3 engineers by erasure count
    sorted_engineers = sorted(engineer_stats.items(), key=lambda x: x[1], reverse=True)
    top_3 = sorted_engineers[:3]
    return {"engineers": [{"initials": eng[0], "count": eng[1]} for eng in top_3]}

# Serve static files (HTML, CSS, JS)
app.mount("/", StaticFiles(directory=".", html=True), name="static")

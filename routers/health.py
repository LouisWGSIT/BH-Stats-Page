from fastapi import APIRouter
from fastapi.responses import JSONResponse

import qa_export

router = APIRouter()


@router.get("/health")
async def health():
    """Liveness check used by deploy/ops automation."""
    return {"status": "ok"}


@router.get("/health/db")
async def health_db():
    """Quick read-only health check against MariaDB to fail fast if DB is unreachable."""
    try:
        conn = qa_export.get_mariadb_connection()
        if not conn:
            return JSONResponse(status_code=503, content={"status": "fail", "detail": "MariaDB connection failed"})
        try:
            cur = conn.cursor()
            cur.execute("SELECT 1")
            row = cur.fetchone()
            cur.close()
            conn.close()
            if row and row[0] == 1:
                return JSONResponse(status_code=200, content={"status": "ok", "db": "ok"})
            return JSONResponse(status_code=503, content={"status": "fail", "detail": "unexpected db result"})
        except Exception as e:
            try:
                conn.close()
            except Exception:
                pass
            print(f"[HealthDB] query failed: {e}")
            return JSONResponse(status_code=503, content={"status": "fail", "detail": "query failed"})
    except Exception as e:
        print(f"[HealthDB] unexpected error: {e}")
        return JSONResponse(status_code=500, content={"status": "error", "detail": "internal error"})

from typing import Callable

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse


def create_admin_diagnostics_router(
    *,
    require_admin: Callable[[Request], None],
    get_mariadb_connection: Callable[[], object | None],
) -> APIRouter:
    router = APIRouter()

    @router.get("/admin/db-processlist")
    def admin_db_processlist(request: Request, limit: int = 100):
        """Admin-only diagnostic: return SHOW FULL PROCESSLIST from MariaDB."""
        require_admin(request)
        conn = None
        try:
            conn = get_mariadb_connection()
            if not conn:
                return JSONResponse(status_code=503, content={"status": "fail", "detail": "MariaDB connection failed"})
            cur = conn.cursor()
            cur.execute("SHOW FULL PROCESSLIST")
            rows = cur.fetchall()
            cur.close()
            conn.close()
            processlist = []
            for row in rows[:limit]:
                try:
                    processlist.append(
                        {
                            "Id": row[0],
                            "User": row[1],
                            "Host": row[2],
                            "db": row[3],
                            "Command": row[4],
                            "Time": row[5],
                            "State": row[6],
                            "Info": row[7],
                        }
                    )
                except Exception:
                    processlist.append({"raw": row})
            return {"processlist": processlist}
        except Exception as exc:
            try:
                if conn:
                    conn.close()
            except Exception:
                pass
            raise HTTPException(status_code=500, detail=str(exc))

    return router

from contextlib import closing
from datetime import UTC, datetime
from typing import Callable

from fastapi import APIRouter, HTTPException, Request


def create_admin_initials_router(
    *,
    require_admin: Callable[[Request], None],
    db_module,
) -> APIRouter:
    router = APIRouter()

    @router.get("/admin/initials-list")
    async def admin_get_initials_list(req: Request):
        """Get all unique initials in the database with their counts."""
        require_admin(req)

        with closing(db_module.sqlite3.connect(db_module.DB_PATH)) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT
                    COALESCE(NULLIF(TRIM(initials), ''), '(unassigned)') as initials_group,
                    COUNT(*) as count
                FROM erasures
                GROUP BY COALESCE(NULLIF(TRIM(initials), ''), '(unassigned)')
                ORDER BY count DESC
                """
            )
            rows = cursor.fetchall()

        result = [{"initials": row[0], "count": row[1]} for row in rows]
        return {
            "status": "ok",
            "total_records": sum(r["count"] for r in result),
            "initials": result,
        }

    @router.post("/admin/assign-unassigned")
    async def admin_assign_unassigned(req: Request):
        """Assign all erasures with NULL/empty initials to a specific engineer."""
        require_admin(req)

        body = {}
        try:
            body = await req.json()
        except Exception:
            pass

        to_initials = (body.get("to") if isinstance(body, dict) else None) or req.query_params.get("to")
        if not to_initials or not isinstance(to_initials, str) or len(to_initials.strip()) == 0:
            raise HTTPException(status_code=400, detail="'to' parameter required with engineer initials")
        to_initials = to_initials.strip().upper()

        with db_module.sqlite_transaction() as (_, cursor):
            cursor.execute(
                """
                UPDATE erasures
                SET initials = ?
                WHERE initials IS NULL OR TRIM(COALESCE(initials, '')) = ''
                """,
                (to_initials,),
            )
            affected = cursor.rowcount

        return {
            "status": "ok",
            "action": "assign_unassigned",
            "to_initials": to_initials,
            "affected_records": affected,
        }

    @router.post("/admin/fix-initials")
    async def admin_fix_initials(req: Request):
        """Change all erasures with old initials to new initials."""
        require_admin(req)

        body = {}
        try:
            body = await req.json()
        except Exception:
            pass

        from_initials = body.get("from") if isinstance(body, dict) else None
        to_initials = (body.get("to") if isinstance(body, dict) else None) or req.query_params.get("to")
        limit = body.get("limit") if isinstance(body, dict) else None
        if limit is None or limit == "":
            limit = None
        else:
            try:
                limit = int(limit)
            except (TypeError, ValueError):
                limit = None

        if from_initials is None:
            raise HTTPException(status_code=400, detail="'from' parameter required")
        if not to_initials or not isinstance(to_initials, str) or len(to_initials.strip()) == 0:
            raise HTTPException(status_code=400, detail="'to' parameter required with engineer initials")

        to_initials = to_initials.strip().upper()
        if isinstance(from_initials, str):
            from_initials = from_initials.strip().upper()

        with db_module.sqlite_transaction() as (_, cursor):
            if from_initials == "" or from_initials is None:
                cursor.execute(
                    """
                    SELECT rowid, initials
                    FROM erasures
                    WHERE initials IS NULL OR TRIM(COALESCE(initials, '')) = ''
                    ORDER BY rowid ASC
                    """
                )
                rows = cursor.fetchall()
                available_count = len(rows)
                if limit is not None:
                    limit = max(0, min(int(limit), available_count))
                    rows = rows[:limit]
                from_display = "(blank/unassigned)"
            else:
                if from_initials == to_initials:
                    return {"status": "error", "message": "from and to initials must be different"}
                cursor.execute(
                    """
                    SELECT rowid, initials
                    FROM erasures
                    WHERE initials = ?
                    ORDER BY rowid ASC
                    """,
                    (from_initials,),
                )
                rows = cursor.fetchall()
                available_count = len(rows)
                if limit is not None:
                    limit = max(0, min(int(limit), available_count))
                    rows = rows[:limit]
                from_display = from_initials

        if not rows:
            return {
                "status": "ok",
                "action": "fix_initials",
                "from_initials": from_display,
                "to_initials": to_initials,
                "affected_records": 0,
                "available_records": available_count,
            }

        with db_module.sqlite_transaction() as (_, cursor2):
            cursor2.execute(
                "INSERT INTO admin_actions (action, from_initials, to_initials, created_at, affected) VALUES (?, ?, ?, ?, ?)",
                ("fix_initials", from_display, to_initials, datetime.now(UTC).isoformat().replace("+00:00", "Z"), len(rows)),
            )
            action_id = cursor2.lastrowid
            cursor2.executemany(
                "INSERT INTO admin_action_rows (action_id, rowid, old_initials) VALUES (?, ?, ?)",
                [(action_id, row_id, old_initials) for row_id, old_initials in rows],
            )
            cursor2.executemany(
                "UPDATE erasures SET initials = ? WHERE rowid = ?",
                [(to_initials, row_id) for row_id, _ in rows],
            )
            affected = len(rows)

        return {
            "status": "ok",
            "action": "fix_initials",
            "from_initials": from_display,
            "to_initials": to_initials,
            "affected_records": affected,
            "available_records": available_count,
        }

    @router.post("/admin/undo-last-initials")
    async def admin_undo_last_initials(req: Request):
        """Undo the most recent initials change."""
        require_admin(req)
        with db_module.sqlite_transaction() as (_, cursor):
            cursor.execute(
                """
                SELECT id, action, from_initials, to_initials, affected
                FROM admin_actions
                WHERE action = 'fix_initials'
                ORDER BY id DESC
                LIMIT 1
                """
            )
            action = cursor.fetchone()
            if not action:
                return {"status": "ok", "undone": 0, "message": "No undo history"}

            action_id, _, from_initials, to_initials, _ = action
            cursor.execute("SELECT rowid, old_initials FROM admin_action_rows WHERE action_id = ?", (action_id,))
            rows = cursor.fetchall()

            cursor.executemany(
                "UPDATE erasures SET initials = ? WHERE rowid = ?",
                [(old_initials, row_id) for row_id, old_initials in rows],
            )
            cursor.execute("DELETE FROM admin_action_rows WHERE action_id = ?", (action_id,))
            cursor.execute("DELETE FROM admin_actions WHERE id = ?", (action_id,))

        return {
            "status": "ok",
            "undone": len(rows),
            "from_initials": from_initials,
            "to_initials": to_initials,
        }

    return router

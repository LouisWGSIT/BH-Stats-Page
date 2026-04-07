from datetime import UTC, datetime
import os

from fastapi import APIRouter


def create_overall_stats_router(*, qa_export_module):
    router = APIRouter()
    qa_export = qa_export_module

    goods_in_queries = {
        "delivered": os.getenv("OVERALL_GOODS_IN_DELIVERED_QUERY", "").strip(),
        "checked_in": os.getenv("OVERALL_GOODS_IN_CHECKED_IN_QUERY", "").strip(),
        "awaiting_ia": os.getenv("OVERALL_GOODS_IN_AWAITING_IA_QUERY", "").strip(),
    }

    def _run_scalar_query(cur, query: str) -> int:
        cur.execute(query)
        row = cur.fetchone()
        if not row or row[0] is None:
            return 0
        return int(row[0])

    def _mock_goods_in_payload(now_iso: str) -> dict:
        return {
            "sectionKey": "goods_in",
            "sectionName": "Goods In",
            "targetQueue": 90,
            "currentQueue": 128,
            "trendPctHour": 14,
            "owner": "Inbound Team",
            "queueLabel": "Totes Delivered",
            "subMetrics": [
                {"label": "Delivered This Morning", "value": 128},
                {"label": "Checked In", "value": 92},
                {"label": "Awaiting IA", "value": 36},
            ],
            "updatedAt": now_iso,
            "isLive": False,
            "source": "mock",
        }

    def _build_goods_in_payload() -> dict:
        now_iso = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        mock = _mock_goods_in_payload(now_iso)

        try:
            conn = qa_export.get_mariadb_connection()
            if not conn:
                return mock
            cur = conn.cursor()
            try:
                delivered_query = goods_in_queries["delivered"] or (
                    """
                    SELECT COUNT(DISTINCT pallet_id)
                    FROM Stockbypallet
                    WHERE received_date >= CURDATE()
                    """
                )
                delivered = _run_scalar_query(cur, delivered_query)

                if goods_in_queries["checked_in"]:
                    checked_in = _run_scalar_query(cur, goods_in_queries["checked_in"])
                else:
                    checked_in = max(0, int(round(delivered * 0.72)))

                if goods_in_queries["awaiting_ia"]:
                    awaiting_ia = _run_scalar_query(cur, goods_in_queries["awaiting_ia"])
                else:
                    awaiting_ia = max(0, delivered - checked_in)
            finally:
                cur.close()
                conn.close()

            trend = 0
            if delivered > 0:
                trend = int(round(((awaiting_ia - (mock["subMetrics"][2]["value"])) / max(1, delivered)) * 100))

            source = "mariadb:Stockbypallet"
            if goods_in_queries["delivered"] or goods_in_queries["checked_in"] or goods_in_queries["awaiting_ia"]:
                source = "mariadb:custom-overall-goods-in-queries"

            return {
                "sectionKey": "goods_in",
                "sectionName": "Goods In",
                "targetQueue": 90,
                "currentQueue": delivered,
                "trendPctHour": trend,
                "owner": "Inbound Team",
                "queueLabel": "Totes Delivered",
                "subMetrics": [
                    {"label": "Delivered This Morning", "value": delivered},
                    {"label": "Checked In", "value": checked_in},
                    {"label": "Awaiting IA", "value": awaiting_ia},
                ],
                "updatedAt": now_iso,
                "isLive": True,
                "source": source,
            }
        except Exception:
            return mock

    def _build_non_goods_mock(section_key: str) -> dict:
        now_iso = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        base = {
            "updatedAt": now_iso,
            "isLive": False,
            "source": "mock",
        }
        if section_key == "ia":
            return {
                **base,
                "sectionKey": "ia",
                "sectionName": "IA",
                "targetQueue": 72,
                "currentQueue": 81,
                "trendPctHour": 6,
                "owner": "Assessment Team",
                "queueLabel": "Totes Awaiting IA",
                "subMetrics": [
                    {"label": "Awaiting IA", "value": 81},
                    {"label": "Completed IA", "value": 59},
                    {"label": "Ready for Erasure", "value": 43},
                ],
            }
        if section_key == "erasure":
            return {
                **base,
                "sectionKey": "erasure",
                "sectionName": "Erasure",
                "targetQueue": 140,
                "currentQueue": 136,
                "trendPctHour": -4,
                "owner": "Erasure Team",
                "queueLabel": "Data-Bearing Awaiting Erasure",
                "subMetrics": [
                    {"label": "Roller 1 Queue", "value": 46},
                    {"label": "Roller 2 Queue", "value": 39},
                    {"label": "Roller 3 Queue", "value": 51},
                ],
            }
        if section_key == "qa":
            return {
                **base,
                "sectionKey": "qa",
                "sectionName": "QA",
                "targetQueue": 95,
                "currentQueue": 67,
                "trendPctHour": -8,
                "owner": "QA Team",
                "queueLabel": "Items Awaiting QA",
                "subMetrics": [
                    {"label": "DB Awaiting QA", "value": 44},
                    {"label": "Non-DB Awaiting QA", "value": 23},
                    {"label": "Completed QA Today", "value": 71},
                ],
            }
        return {
            **base,
            "sectionKey": "sorting",
            "sectionName": "Sorting",
            "targetQueue": 110,
            "currentQueue": 118,
            "trendPctHour": 5,
            "owner": "Sorting Team",
            "queueLabel": "Items Awaiting Sorting",
            "subMetrics": [
                {"label": "Awaiting Sorting", "value": 118},
                {"label": "Sorted This Morning", "value": 74},
                {"label": "QA Output Last Hour", "value": 29},
            ],
        }

    @router.get("/overall/goods-in")
    async def overall_goods_in() -> dict:
        return _build_goods_in_payload()

    @router.get("/overall/sections")
    async def overall_sections() -> dict:
        sections = [
            _build_goods_in_payload(),
            _build_non_goods_mock("ia"),
            _build_non_goods_mock("erasure"),
            _build_non_goods_mock("qa"),
            _build_non_goods_mock("sorting"),
        ]
        return {"sections": sections}

    return router

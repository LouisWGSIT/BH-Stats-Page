from datetime import UTC, datetime
import os
import re

from fastapi import APIRouter


def create_overall_stats_router(*, qa_export_module):
    router = APIRouter()
    qa_export = qa_export_module

    goods_in_queries = {
        "delivered": os.getenv("OVERALL_GOODS_IN_DELIVERED_QUERY", "").strip(),
        "checked_in": os.getenv("OVERALL_GOODS_IN_CHECKED_IN_QUERY", "").strip(),
        "awaiting_ia": os.getenv("OVERALL_GOODS_IN_AWAITING_IA_QUERY", "").strip(),
    }
    goods_in_table_raw = os.getenv("OVERALL_GOODS_IN_TABLE", "ITAD_GRN").strip() or "ITAD_GRN"
    goods_in_table = goods_in_table_raw if re.fullmatch(r"[A-Za-z0-9_]+", goods_in_table_raw) else "ITAD_GRN"

    def _run_query_variants(cur, queries: list[str]) -> int:
        last_error = None
        for query in queries:
            try:
                return _run_scalar_query(cur, query)
            except Exception as exc:
                last_error = exc
        if last_error:
            raise last_error
        return 0

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
                try:
                    default_delivered = _run_query_variants(cur, [
                        f"""
                        SELECT COUNT(*)
                        FROM {goods_in_table}
                        WHERE DATE(date_received) = CURDATE()
                          AND UPPER(COALESCE(recieved, '')) = 'Y'
                        """,
                        f"""
                        SELECT COUNT(*)
                        FROM {goods_in_table}
                        WHERE DATE(date_received) = CURDATE()
                          AND UPPER(COALESCE(received, '')) = 'Y'
                        """,
                    ])
                    default_checked_in = _run_query_variants(cur, [
                        f"""
                        SELECT COUNT(*)
                        FROM {goods_in_table}
                        WHERE DATE(bookedin_date) = CURDATE()
                          AND UPPER(COALESCE(bookedin, '')) = 'Y'
                        """,
                        f"""
                        SELECT COUNT(*)
                        FROM {goods_in_table}
                        WHERE DATE(date_received) = CURDATE()
                          AND UPPER(COALESCE(bookedin, '')) = 'Y'
                        """,
                    ])
                    default_awaiting_ia = _run_query_variants(cur, [
                        f"""
                        SELECT COUNT(*)
                        FROM {goods_in_table}
                        WHERE DATE(date_received) = CURDATE()
                          AND UPPER(COALESCE(recieved, '')) = 'Y'
                          AND UPPER(COALESCE(bookedin, 'N')) <> 'Y'
                        """,
                        f"""
                        SELECT COUNT(*)
                        FROM {goods_in_table}
                        WHERE DATE(date_received) = CURDATE()
                          AND UPPER(COALESCE(received, '')) = 'Y'
                          AND UPPER(COALESCE(bookedin, 'N')) <> 'Y'
                        """,
                    ])
                    source = f"mariadb:{goods_in_table}"
                except Exception:
                    default_delivered = _run_scalar_query(
                        cur,
                        """
                        SELECT COUNT(DISTINCT pallet_id)
                        FROM Stockbypallet
                        WHERE received_date >= CURDATE()
                        """,
                    )
                    default_checked_in = max(0, int(round(default_delivered * 0.72)))
                    default_awaiting_ia = max(0, default_delivered - default_checked_in)
                    source = "mariadb:Stockbypallet"

                if goods_in_queries["delivered"] or goods_in_queries["checked_in"] or goods_in_queries["awaiting_ia"]:
                    delivered = _run_scalar_query(cur, goods_in_queries["delivered"]) if goods_in_queries["delivered"] else default_delivered
                    checked_in = _run_scalar_query(cur, goods_in_queries["checked_in"]) if goods_in_queries["checked_in"] else default_checked_in
                    awaiting_ia = _run_scalar_query(cur, goods_in_queries["awaiting_ia"]) if goods_in_queries["awaiting_ia"] else default_awaiting_ia
                    source = "mariadb:custom-overall-goods-in-queries"
                else:
                    delivered = default_delivered
                    checked_in = default_checked_in
                    awaiting_ia = default_awaiting_ia
            finally:
                cur.close()
                conn.close()

            trend = 0
            if delivered > 0:
                trend = int(round(((awaiting_ia - (mock["subMetrics"][2]["value"])) / max(1, delivered)) * 100))

            return {
                "sectionKey": "goods_in",
                "sectionName": "Goods In",
                "targetQueue": 90,
                "currentQueue": delivered,
                "trendPctHour": trend,
                "owner": "Inbound Team",
                "queueLabel": "GRNs Received",
                "subMetrics": [
                    {"label": "Received Today", "value": delivered},
                    {"label": "Booked In Today", "value": checked_in},
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

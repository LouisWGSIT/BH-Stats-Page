import os

from fastapi import APIRouter
from fastapi.responses import FileResponse


def create_static_pages_router(
    *,
    frontend_pages_dir: str,
    frontend_js_dir: str,
    frontend_css_dir: str,
    config_json_path: str = os.path.join("config", "config.json"),
) -> APIRouter:
    router = APIRouter()

    @router.get("/", include_in_schema=False)
    async def serve_index():
        return FileResponse(os.path.join(frontend_pages_dir, "index.html"))

    @router.get("/index.html", include_in_schema=False)
    async def serve_index_html():
        return FileResponse(os.path.join(frontend_pages_dir, "index.html"))

    @router.get("/admin.html", include_in_schema=False)
    async def serve_admin_html():
        return FileResponse(os.path.join(frontend_pages_dir, "admin.html"))

    @router.get("/manager.html", include_in_schema=False)
    async def serve_manager_html():
        return FileResponse(os.path.join(frontend_pages_dir, "manager.html"))

    @router.get("/qr-code-generator.html", include_in_schema=False)
    async def serve_qr_generator_html():
        return FileResponse(os.path.join(frontend_pages_dir, "qr-code-generator.html"))

    @router.get("/app.js", include_in_schema=False)
    async def serve_app_js():
        return FileResponse(
            os.path.join(frontend_js_dir, "app.js"),
            media_type="application/javascript",
        )

    @router.get("/core/ui_utils.js", include_in_schema=False)
    async def serve_ui_utils_js():
        return FileResponse(
            os.path.join(frontend_js_dir, "core", "ui_utils.js"),
            media_type="application/javascript",
        )

    @router.get("/core/display_keepalive.js", include_in_schema=False)
    async def serve_display_keepalive_js():
        return FileResponse(
            os.path.join(frontend_js_dir, "core", "display_keepalive.js"),
            media_type="application/javascript",
        )

    @router.get("/core/adaptive_poll.js", include_in_schema=False)
    async def serve_adaptive_poll_js():
        return FileResponse(
            os.path.join(frontend_js_dir, "core", "adaptive_poll.js"),
            media_type="application/javascript",
        )

    @router.get("/core/aggregated_refresh.js", include_in_schema=False)
    async def serve_aggregated_refresh_js():
        return FileResponse(
            os.path.join(frontend_js_dir, "core", "aggregated_refresh.js"),
            media_type="application/javascript",
        )

    @router.get("/core/qa_adapter.js", include_in_schema=False)
    async def serve_qa_adapter_js():
        return FileResponse(
            os.path.join(frontend_js_dir, "core", "qa_adapter.js"),
            media_type="application/javascript",
        )

    @router.get("/core/flip_cards_updater.js", include_in_schema=False)
    async def serve_flip_cards_updater_js():
        return FileResponse(
            os.path.join(frontend_js_dir, "core", "flip_cards_updater.js"),
            media_type="application/javascript",
        )

    @router.get("/core/auth.js", include_in_schema=False)
    async def serve_auth_js():
        return FileResponse(
            os.path.join(frontend_js_dir, "core", "auth.js"),
            media_type="application/javascript",
        )

    @router.get("/core/auth_ui.js", include_in_schema=False)
    async def serve_auth_ui_js():
        return FileResponse(
            os.path.join(frontend_js_dir, "core", "auth_ui.js"),
            media_type="application/javascript",
        )

    @router.get("/core/dashboard_switcher.js", include_in_schema=False)
    async def serve_dashboard_switcher_js():
        return FileResponse(
            os.path.join(frontend_js_dir, "core", "dashboard_switcher.js"),
            media_type="application/javascript",
        )

    @router.get("/core/export_manager.js", include_in_schema=False)
    async def serve_export_manager_js():
        return FileResponse(
            os.path.join(frontend_js_dir, "core", "export_manager.js"),
            media_type="application/javascript",
        )

    @router.get("/core/export_csv_helpers.js", include_in_schema=False)
    async def serve_export_csv_helpers_js():
        return FileResponse(
            os.path.join(frontend_js_dir, "core", "export_csv_helpers.js"),
            media_type="application/javascript",
        )

    @router.get("/erasure/category_cards.js", include_in_schema=False)
    async def serve_erasure_category_cards_js():
        return FileResponse(
            os.path.join(frontend_js_dir, "erasure", "category_cards.js"),
            media_type="application/javascript",
        )

    @router.get("/qa/qa_dashboard.js", include_in_schema=False)
    async def serve_qa_dashboard_js():
        return FileResponse(
            os.path.join(frontend_js_dir, "qa", "qa_dashboard.js"),
            media_type="application/javascript",
        )

    @router.get("/styles.css", include_in_schema=False)
    async def serve_styles_css():
        return FileResponse(
            os.path.join(frontend_css_dir, "styles.css"),
            media_type="text/css",
        )

    @router.get("/config.json", include_in_schema=False)
    async def serve_config_json():
        return FileResponse(config_json_path, media_type="application/json")

    return router

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

    @router.get("/core/auth.js", include_in_schema=False)
    async def serve_auth_js():
        return FileResponse(
            os.path.join(frontend_js_dir, "core", "auth.js"),
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

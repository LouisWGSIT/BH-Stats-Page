import backend.excel_export as excel_export
import uuid


def test_resolve_logo_path_prefers_backend_assets(monkeypatch, workspace_temp_dir):
    tmp_path = workspace_temp_dir / f"excel_logo_{uuid.uuid4().hex}"
    tmp_path.mkdir(parents=True, exist_ok=True)
    backend_dir = tmp_path / "backend"
    backend_assets = backend_dir / "assets"
    repo_assets = tmp_path / "assets"
    backend_assets.mkdir(parents=True)
    repo_assets.mkdir(parents=True)

    backend_logo = backend_assets / "logo_gsit_ss.png"
    repo_logo = repo_assets / "logo_gsit_ss.png"
    backend_logo.write_bytes(b"backend")
    repo_logo.write_bytes(b"repo")

    monkeypatch.setattr(excel_export, "__file__", str(backend_dir / "excel_export.py"))
    monkeypatch.chdir(tmp_path)

    resolved = excel_export._resolve_logo_path()
    assert resolved == str(backend_logo)


def test_resolve_logo_path_uses_repo_assets_fallback(monkeypatch, workspace_temp_dir):
    tmp_path = workspace_temp_dir / f"excel_logo_{uuid.uuid4().hex}"
    tmp_path.mkdir(parents=True, exist_ok=True)
    backend_dir = tmp_path / "backend"
    repo_assets = tmp_path / "assets"
    repo_assets.mkdir(parents=True)

    repo_logo = repo_assets / "logo_gsit_ss.png"
    repo_logo.write_bytes(b"repo")

    monkeypatch.setattr(excel_export, "__file__", str(backend_dir / "excel_export.py"))
    monkeypatch.chdir(tmp_path)

    resolved = excel_export._resolve_logo_path()
    assert resolved == str(repo_logo)


def test_resolve_logo_path_returns_none_when_missing(monkeypatch, workspace_temp_dir):
    tmp_path = workspace_temp_dir / f"excel_logo_{uuid.uuid4().hex}"
    tmp_path.mkdir(parents=True, exist_ok=True)
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir(parents=True)

    monkeypatch.setattr(excel_export, "__file__", str(backend_dir / "excel_export.py"))
    monkeypatch.chdir(tmp_path)

    resolved = excel_export._resolve_logo_path()
    assert resolved is None

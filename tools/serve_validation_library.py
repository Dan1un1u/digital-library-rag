"""Serve this checkout against an explicitly isolated local validation library."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.catalog_batch import code_identity
from dlrag.shared.config import Settings
from dlrag.api.main import create_app
from dlrag.api.services import assemble


def validation_settings(env_file, data_dir):
    original = Settings(_env_file=env_file)
    target = data_dir.resolve()
    protected = [original.data_dir, original.db_path.parent, original.files_dir, original.index_dir]
    # Relative production paths belong to the config directory, not this tool's cwd.
    from dotenv import dotenv_values
    values = dotenv_values(env_file)
    base = env_file.resolve().parent
    configured = Path(values.get("DATA_DIR") or (Path("data") / original.app_mode))
    configured = configured if configured.is_absolute() else base / configured
    protected.append(configured)
    for name, fallback in (("DB_PATH", configured / "library.sqlite"),
                           ("FILES_DIR", configured / "raw"), ("INDEX_DIR", configured / "indexes")):
        path = Path(values.get(name) or fallback)
        path = path if path.is_absolute() else base / path
        protected.append(path.parent if name == "DB_PATH" else path)
    if any(target == p.resolve() or target.is_relative_to(p.resolve()) or p.resolve().is_relative_to(target)
           for p in protected):
        raise ValueError("Validation data must be disjoint from production storage")
    marker = target / "validation-environment.json"
    if target.exists() and any(target.iterdir()) and not marker.exists():
        raise ValueError("Nonempty storage has no validation marker")
    return Settings(**{**original.model_dump(), "data_dir": target, "db_path": target / "library.sqlite",
                       "files_dir": target / "raw", "index_dir": target / "indexes"}, _env_file=None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--port", type=int, default=19000)
    parser.add_argument("--initialize-empty-index", action="store_true")
    args = parser.parse_args()
    if args.port in {8000, 8501, 18000, 18001, 18501, 18502} or not 1024 <= args.port <= 65535:
        parser.error("Choose a separate local validation port")
    settings = validation_settings(args.env_file, args.data_dir)
    identity = {"validation_only": True, "code": code_identity(),
                "storage_identity": hashlib.sha256(str(settings.data_dir).encode()).hexdigest()}
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    marker = settings.data_dir / "validation-environment.json"
    if marker.exists():
        previous = json.loads(marker.read_text(encoding="utf-8"))
        if previous["storage_identity"] != identity["storage_identity"]:
            raise ValueError("Storage marker differs")
    marker.write_bytes((json.dumps(identity, indent=2) + "\n").encode())
    services = assemble(settings)
    if args.initialize_empty_index and not services.manifest():
        if services.library.list_documents(include_nonready=True):
            raise ValueError("Only a new empty validation corpus may be initialized")
        services.rebuild()
    app = create_app(services=services)
    @app.get("/validation/environment")
    def environment():
        return identity
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=args.port, workers=1)


if __name__ == "__main__":
    main()

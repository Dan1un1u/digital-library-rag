"""真实模式导入：按 manifest.json 把一批 PDF 经 A 入库，最后一次性由 B 建索引（需嵌入密钥）。
用法：python scripts/seed_real.py --source data/arxiv_src   （先停止后端；.env 须 APP_MODE=real）"""
import argparse
import json
from pathlib import Path
from dlrag.api.services import assemble
from dlrag.shared.config import Settings


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", type=Path, required=True, help="含 manifest.json 与 PDF 的目录")
    p.add_argument("--data-dir", type=Path)
    a = p.parse_args(argv)
    settings = Settings(app_mode="real", **({"data_dir": a.data_dir} if a.data_dir else {}))
    services = assemble(settings)
    store = services.require("library")
    results = []
    with services.lock:
        for item in json.loads((a.source / "manifest.json").read_text(encoding="utf-8")):
            doc = store.ingest_pdf(str(a.source / item["file"]), item["metadata"], settings.chunking_config.model_dump())
            results.append({"file": item["file"], "doc_id": doc["doc_id"], "status": doc["status"],
                            "error_code": doc.get("error_code")})
        manifest = services.rebuild()
        for result in results:
            current = store.get_document(result["doc_id"])
            result.update(status=current["status"], error_code=current.get("error_code"))
    print(json.dumps({"documents": results, "manifest": manifest}, ensure_ascii=False, indent=2))
    return 0 if all(r["status"] != "failed" for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())

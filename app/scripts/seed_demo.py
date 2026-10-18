"""合成 PDF → A 入库 → B 建索引；不会用固定问答冒充真实 C。"""
import argparse
import json
from pathlib import Path

from dlrag.api.services import assemble
from dlrag.shared.config import Settings

DEMO_PAGES = [
    ("synthetic_keyword", ["SYNTHETIC TEST MATERIAL - NOT A RESEARCH PAPER\n\nPage 1. Keyword search matches query terms. BM25 is a lexical ranking example.",
                            "SYNTHETIC TEST MATERIAL - NOT A RESEARCH PAPER\n\nPage 2. Evidence must retain the PDF file page number. This is a synthetic citation example."]),
    ("synthetic_semantic", ["SYNTHETIC TEST MATERIAL - NOT A RESEARCH PAPER\n\nPage 1. Semantic search uses vector representations. This text is only a pipeline fixture."]),
]


def create_pdf(path, pages):
    import pymupdf
    doc = pymupdf.open()
    for text in pages:
        page = doc.new_page()
        page.insert_textbox(pymupdf.Rect(55, 55, 540, 780), text, fontsize=12)
    doc.set_metadata({"title": "Synthetic test material", "author": "Synthetic fixture"})
    doc.save(str(path))
    doc.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["real", "mock"])
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--rebuild-only", action="store_true", help="仅对现有 indexing/ready 文献重建；先停止后端")
    args = parser.parse_args(argv)
    options = {k: v for k, v in {"app_mode": args.mode, "data_dir": args.data_dir}.items() if v is not None}
    settings = Settings(**options)
    services = assemble(settings)
    try:
        if args.rebuild_only:
            manifest = services.rebuild()
        else:
            folder = settings.data_dir / "demo_sources"
            folder.mkdir(parents=True, exist_ok=True)
            for n, (name, pages) in enumerate(DEMO_PAGES):
                path = folder / (name + ".pdf")
                if not path.exists():
                    create_pdf(path, pages)
                services.ingest(str(path), {"title": f"合成测试资料 {n + 1}（非论文）", "authors": [],
                                           "year": 2024 + n, "topics": ["合成测试"], "language": "en",
                                           "rights_note": "本项目生成的合成测试资料"})
            manifest = services.manifest()
        print(json.dumps({"mode": settings.app_mode, "synthetic": True, "manifest": manifest,
                          "qa_real_verified": False}, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({"error": {"code": getattr(exc, "code", "INTERNAL_ERROR"),
                                    "message": "导入/重建未完成。请检查模型配置、模块依赖及管理视图。"}}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

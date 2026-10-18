"""独立索引构建、三种检索、重载及评估入口。"""

import argparse
import json
import sys
from pathlib import Path

from .embeddings import FakeHashEmbedding, SiliconFlowEmbedding
from .errors import ProjectError
from .evaluation import evaluate, read_questions
from .retriever import Retriever


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def synthetic_chunks():
    records = [
        ("BM25 ranks keyword matches.", 2020, ["信息检索"]),
        ("Dense retrieval represents queries and passages as vectors.", 2021, ["信息检索"]),
        ("中文语义检索按含义匹配文献。", 2024, ["信息检索"]),
        ("RRF combines ranking positions from multiple retrieval branches.", 2023, ["混合检索"]),
        ("PDF evidence must preserve the original page number.", 2024, ["证据引用"]),
        ("A digital library organizes documents and their metadata.", None, ["数字图书馆"]),
        ("Naive string matches cannot translate a Chinese query into English.", 2022, ["跨语言检索"]),
        ("检索向量需要使用同一模型编码。", 2024, ["信息检索"]),
        ("Filtering by publication year excludes unknown years.", None, ["元数据"]),
        ("Synthetic overlap text can contain a different evidence point.", 2023, ["证据引用"]),
    ]
    chunks = []
    for i, (text, year, topics) in enumerate(records, 1):
        chunks.append({"chunk_id": f"c_synthetic_{i:02d}", "doc_id": f"d_synthetic_{i:02d}",
                       "pdf_page": 1, "printed_page": None, "section": None, "text": text,
                       "page_char_start": 0, "page_char_end": len(text), "token_count": None,
                       "document": {"title": f"合成测试资料 {i}", "authors": [], "year": year,
                                    "topics": topics, "language": "mixed"}})
    return chunks


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["build", "search", "manifest", "evaluate", "demo"])
    parser.add_argument("--index-dir", required=True)
    parser.add_argument("--backend", choices=["siliconflow", "fake"], default="siliconflow")
    parser.add_argument("--env-file")
    parser.add_argument("--model")
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--settings")
    parser.add_argument("--chunking-config")
    parser.add_argument("--chunks")
    parser.add_argument("--db")
    parser.add_argument("--files")
    parser.add_argument("--query")
    parser.add_argument("--mode", choices=["keyword", "vector", "hybrid"], default="hybrid")
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--year-from", type=int)
    parser.add_argument("--year-to", type=int)
    parser.add_argument("--topic", action="append", default=[])
    parser.add_argument("--questions")
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    try:
        settings = read_json(args.settings) if args.settings else {}
        if args.chunking_config:
            settings["chunking_config"] = read_json(args.chunking_config)
        if args.backend == "fake":
            backend = FakeHashEmbedding()
        else:
            overrides = {"batch_size": args.batch_size, "timeout": args.timeout}
            if args.model:
                overrides["model"] = args.model
            backend = SiliconFlowEmbedding.from_env(args.env_file, **overrides)
        if args.command == "demo":
            if args.backend != "fake":
                raise ProjectError("INVALID_REQUEST", "独立合成演示须显式选择 --backend fake")
            settings["chunking_config"] = {"count_mode": "character", "tokenizer_name": None,
                                          "tokenizer_revision": None, "max_tokens": 400,
                                          "overlap_tokens": 50, "max_chars": 1200, "overlap_chars": 150}
        chunks = None
        if args.command == "build":
            if args.chunks:
                chunks = read_json(args.chunks)
            elif args.db and args.files:
                try:
                    from dlrag.ingestion import LibraryStore
                except ImportError:
                    raise ProjectError("INVALID_REQUEST", "A 模块未在导入路径中，请设置 PYTHONPATH 或使用 --chunks") from None
                store = LibraryStore(args.db, args.files)
                chunks = store.list_chunks(include_indexing=True)
                configs = [doc["chunking_config"] for doc in store.list_documents(include_nonready=True)
                           if doc["status"] in ("ready", "indexing")]
                if configs:
                    if any(config != configs[0] for config in configs):
                        raise ProjectError("INVALID_REQUEST", "A 库中存在不同切块配置")
                    if settings.get("chunking_config") is not None and settings["chunking_config"] != configs[0]:
                        raise ProjectError("INVALID_REQUEST", "指定配置与 A 的实际切块配置不同")
                    settings["chunking_config"] = configs[0]
            else:
                raise ProjectError("INVALID_REQUEST", "构建须提供 --chunks，或同时提供 --db 和 --files")
        retriever = Retriever(args.index_dir, backend, settings)
        if args.command == "build":
            result = retriever.build(chunks)
        elif args.command == "demo":
            manifest = retriever.build(synthetic_chunks())
            retriever.load()
            result = {"mode": "fake", "manifest": manifest,
                      "hits": retriever.search(args.query or "BM25", mode=args.mode, top_k=args.top_k)}
        else:
            retriever.load()
            if args.command == "manifest":
                result = retriever.get_manifest()
            elif args.command == "search":
                filters = {"year_from": args.year_from, "year_to": args.year_to, "topics": args.topic}
                result = {"hits": retriever.search(args.query, filters, args.mode, args.top_k),
                          "index_version": retriever.get_manifest()["index_version"]}
            else:
                if not args.questions or not args.output:
                    raise ProjectError("INVALID_REQUEST", "评估须提供 --questions 和 --output")
                if args.top_k < 10:
                    raise ProjectError("INVALID_REQUEST", "评估 Recall@10 须设置 top_k ≥ 10")
                result = evaluate(retriever, read_questions(args.questions), args.output, args.top_k)
        rendered = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)
        if args.output and args.command != "evaluate":
            output = Path(args.output)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(rendered, encoding="utf-8")
            print(json.dumps({"output": str(output)}, ensure_ascii=False))
        else:
            print(rendered)
        return 0
    except (ProjectError, OSError, ValueError, TypeError, KeyError) as error:
        code = getattr(error, "code", "INVALID_REQUEST")
        message = error.message if isinstance(error, ProjectError) else "输入文件或参数不正确"
        print(json.dumps({"error": {"code": code, "message": message}}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

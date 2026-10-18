"""PowerShell: $env:PYTHONPATH='src'; python -m dlrag.qa.cli --help."""
import argparse
import json
from pathlib import Path
from .demo import FakeRetriever, demo_outputs
from .engine import QAEngine
from .errors import ProjectError
from .evaluation import evaluate, summarize_review
from .llm_client import ScriptedMockLLM, SiliconFlowLLM


def main(argv=None):
    parser = argparse.ArgumentParser(description="C 单轮证据问答；real 不自动切换 mock")
    subs = parser.add_subparsers(dest="command", required=True)
    demo = subs.add_parser("demo")
    demo.add_argument("--scenario", choices=["answered", "clarify", "empty", "invalid"], default="answered")
    demo.add_argument("--question", default="BM25 是什么？")
    for name in ("ask", "evaluate"):
        sub = subs.add_parser(name)
        sub.add_argument("--index-dir", required=True)
        sub.add_argument("--retrieval-mode", choices=["keyword", "vector", "hybrid"], default="hybrid")
        sub.add_argument("--baseline", action="store_true")
        if name == "ask":
            sub.add_argument("--question", required=True)
            sub.add_argument("--filters", default="{}", help="Filters JSON")
            sub.add_argument("--output")
        else:
            sub.add_argument("--questions", required=True)
            sub.add_argument("--output-dir", required=True)
    review = subs.add_parser("summarize-review")
    review.add_argument("--run-dir", required=True)
    review.add_argument("--review", required=True)
    review.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "demo":
            engine = QAEngine(FakeRetriever(empty=args.scenario == "empty"),
                              ScriptedMockLLM(demo_outputs(args.question, args.scenario)), {})
            result = {"mode": "mock", "synthetic": True, "response": engine.ask({"question": args.question})}
        elif args.command == "summarize-review":
            result = summarize_review(args.run_dir, args.review, args.output)
        else:
            from dlrag.retrieval import Retriever
            from dlrag.retrieval.embeddings import SiliconFlowEmbedding
            llm = SiliconFlowLLM.from_env()
            # B validates backend identity on load even for keyword mode; no key
            # is needed until an actual embedding request is made.
            backend = SiliconFlowEmbedding.from_env()
            retriever = Retriever(args.index_dir, backend, {})
            retriever.load()
            engine = QAEngine(retriever, llm, {"planning_enabled": not args.baseline,
                "retrieval_mode": args.retrieval_mode, "max_output_tokens": llm.max_output_tokens,
                "context_window_tokens": llm.context_window_tokens})
            if args.command == "ask":
                result = engine.ask({"question": args.question, "filters": json.loads(args.filters), "history": []})
                if args.output:
                    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            else:
                questions = [json.loads(line) for line in Path(args.questions).read_text(encoding="utf-8-sig").splitlines() if line.strip()]
                result = evaluate(engine, questions, args.output_dir, "baseline" if args.baseline else "full")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if isinstance(result, dict) and (result.get("status") == "error" or result.get("response", {}).get("status") == "error") else 0
    except (ProjectError, ValueError, OSError) as error:
        print(json.dumps({"error": {"code": getattr(error, "code", "INVALID_REQUEST"),
                                     "message": "命令失败，请检查输入、索引与模型配置"}}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

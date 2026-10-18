"""Real A/B/C development smoke through HTTP; does not grade semantic quality.

The caller explicitly supplies the data directory and process-local model keys.
Only selected question/evidence content reaches the configured model services.
"""
import argparse
import json
from pathlib import Path
from time import perf_counter

from fastapi.testclient import TestClient

from dlrag.api.main import create_app
from dlrag.shared.config import Settings
from dlrag.shared.models import AnswerResponse
if __package__:
    from .run_evaluation import provenance
else:
    from run_evaluation import provenance


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--question", action="append", help="Optional development smoke question; repeat to add more")
    args = parser.parse_args(argv)
    if args.output.exists():
        parser.error("output already exists; use a new path to preserve prior records")
    questions = args.question or [
        "有没有不用准确关键词也能找到论文的方法？",
        "Sentence-BERT 论文指出，在一万句话中寻找最相似句对，直接使用 BERT 大约需要多少次推理和多长时间？",
        "那个系统怎么样？",
        "这些论文里有没有讲量子计算机的硬件实现？",
    ]
    settings = Settings(app_mode="real", data_dir=args.data_dir)
    app = create_app(settings=settings)
    records, searches = [], []
    with TestClient(app, raise_server_exceptions=False) as client:
        health = client.get("/health").json()
        if health["status"] != "ready" or health["mode"] != "real":
            parser.error("real services are not ready; inspect /health and configuration")
        for mode in ("keyword", "vector", "hybrid"):
            started = perf_counter()
            response = client.post("/search", json={"query": "BM25", "mode": mode, "top_k": 5})
            searches.append(dict(mode=mode, http_status=response.status_code,
                                 elapsed_ms=(perf_counter() - started) * 1000, response=response.json()))
        for question in questions:
            started = perf_counter()
            response = client.post("/ask", json={"question": question, "filters": {}, "history": []})
            answer = response.json()
            AnswerResponse.model_validate(answer)
            checks = []
            for evidence in answer["evidence"]:
                chunk = client.get("/chunks/" + evidence["chunk_id"]).json()["chunk"]
                file_response = client.get(evidence["file_url"].split("#")[0])
                checks.append(dict(chunk_id=evidence["chunk_id"],
                    exact_quote=chunk["text"] == evidence["quote"],
                    same_page=chunk["pdf_page"] == evidence["pdf_page"],
                    same_document=chunk["doc_id"] == evidence["doc_id"],
                    file_status=file_response.status_code,
                    pdf_header=file_response.content.startswith(b"%PDF")))
            records.append(dict(question=question, http_status=response.status_code,
                                elapsed_ms=(perf_counter() - started) * 1000,
                                answer=answer, citation_checks=checks))
        result = dict(mode="real", kind="development_smoke_not_formal_evaluation", health=health,
            environment=provenance(settings, app.state.services, Path("evaluation/dataset/questions.jsonl")),
            searches=searches, questions=records, human_semantic_metrics=None,
            browser_pdf_page_navigation_verified=False)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    failed = any(row["http_status"] != 200 for row in searches)
    failed |= any(row["answer"]["status"] == "error" for row in records)
    failed |= any(not all((c["exact_quote"], c["same_page"], c["same_document"],
                          c["file_status"] == 200, c["pdf_header"])) for r in records for c in r["citation_checks"])
    print(json.dumps(dict(output=str(args.output), mode="real", transport_checks_passed=not failed,
                         statuses=[r["answer"]["status"] for r in records]), ensure_ascii=False))
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())

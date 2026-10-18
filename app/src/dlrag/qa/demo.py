"""Synthetic fixtures, explicitly separate from real library evidence."""
import copy
from .planner import original_plan


def demo_chunk():
    text = "Synthetic demo: BM25 is a lexical retrieval scoring function."
    return dict(chunk_id="c_demo_p0001_0001", doc_id="d_demo", pdf_page=1,
                printed_page=None, section=None, text=text, page_char_start=0,
                page_char_end=len(text), token_count=None, char_count=len(text),
                document=dict(title="Synthetic demo only", authors=[], year=None, topics=["IR"], language="en"))


class FakeRetriever:
    def __init__(self, chunks=None, empty=False):
        self.chunks = [demo_chunk()] if chunks is None else chunks
        self.empty = empty
        self.calls = []

    def get_manifest(self):
        return {"index_version": "idx_synthetic_demo"}

    def search(self, query, filters=None, mode="hybrid", top_k=20):
        self.calls.append((query, copy.deepcopy(filters), mode, top_k))
        return [] if self.empty else [dict(rank=i + 1, chunk=copy.deepcopy(c),
            scores=dict(bm25=1.0, cosine=None, rrf=None, rerank=None), matched_by=["keyword"],
            index_version="idx_synthetic_demo") for i, c in enumerate(self.chunks[:top_k])]


def demo_outputs(question, scenario):
    plan = original_plan(question)
    answer = {"status": "answered", "claims": [{"text": "演示资料将 BM25 描述为词法检索评分函数。",
              "evidence_chunk_ids": ["c_demo_p0001_0001"]}], "limitations": ["合成测试资料，不能用于语义效果成绩"]}
    if scenario == "clarify":
        plan.update(intent="clarify", needs_clarification=True,
                    clarification_question="你希望了解检索方法，还是文献整理方法？",
                    clarification_options=["检索方法", "文献整理方法"])
    if scenario == "invalid":
        answer["claims"][0]["evidence_chunk_ids"] = ["fabricated"]
        return [plan, answer, answer]
    return [plan, answer]

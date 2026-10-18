"""D 的脚本问答替身。只允许显式 mock；不实现真实查询规划或回答算法。"""
from time import perf_counter
from dlrag.shared.models import error_answer


class ScriptedQA:
    def __init__(self, retriever):
        self.retriever = retriever

    def ask(self, request):
        start = perf_counter()
        question = request["question"]
        answer = error_answer(question, "MOCK", "脚本测试状态")
        answer.update(status="insufficient_evidence", error=None,
                      limitations=["模拟问答只验证界面与接口，不用于真实回答或实验评分。"])
        if "超时" in question or "timeout" in question.lower():
            return error_answer(question, "MODEL_TIMEOUT", "模拟模型超时；请稍后重试。")
        if ("澄清" in question or "那个系统" in question) and "补充选择：" not in question:
            options = ["了解检索方式", "了解证据问答"]
            answer.update(status="needs_clarification", clarification_question="你希望了解哪一部分？（模拟追问）",
                          clarification_options=options)
            answer["query_plan"].update(intent="clarify", needs_clarification=True,
                                        clarification_question=answer["clarification_question"], clarification_options=options)
        elif "不足" not in question and "unanswerable" not in question.lower():
            if self.retriever is None or self.retriever.get_manifest() is None:
                return error_answer(question, "INDEX_NOT_READY", "先运行 seed_demo.py 准备合成演示资料。")
            hits = self.retriever.search(question, request["filters"], "hybrid", 3)
            answer["index_version"] = self.retriever.get_manifest()["index_version"]
            if hits:
                chunk = hits[0]["chunk"]
                doc = chunk["document"]
                answer.update(status="answered", claims=[{"claim_id": "cl_1", "text": "模拟展示：请展开引用核对以下合成资料原文。",
                                                          "evidence_ids": ["ev_1"]}],
                              evidence=[{"evidence_id": "ev_1", "chunk_id": chunk["chunk_id"], "doc_id": chunk["doc_id"],
                                         "title": doc["title"], "authors": doc["authors"], "year": doc["year"],
                                         "pdf_page": chunk["pdf_page"], "printed_page": chunk["printed_page"], "quote": chunk["text"],
                                         "file_url": f"/documents/{chunk['doc_id']}/file#page={chunk['pdf_page']}"}],
                              related_documents=[{"doc_id": chunk["doc_id"], "title": doc["title"]}])
        answer["timings_ms"]["total"] = (perf_counter() - start) * 1000
        return answer

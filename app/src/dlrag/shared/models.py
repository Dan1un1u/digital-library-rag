"""共同契约 1.0。请求拒绝未知字段；输出保留各组公开扩展字段。"""
from __future__ import annotations

from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Text = Annotated[str, StringConstraints(min_length=1)]
Query = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
Year = Annotated[int, Field(strict=True)]
Mode = Literal["keyword", "vector", "hybrid"]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Output(BaseModel):
    model_config = ConfigDict(extra="allow", allow_inf_nan=False)


class ChunkingConfig(Input):
    count_mode: Literal["token", "character"] = "character"
    tokenizer_name: str | None = None
    tokenizer_revision: str | None = None
    max_tokens: Annotated[int, Field(strict=True, gt=0)] = 400
    overlap_tokens: Annotated[int, Field(strict=True, ge=0)] = 50
    max_chars: Annotated[int, Field(strict=True, gt=0)] = 1200
    overlap_chars: Annotated[int, Field(strict=True, ge=0)] = 150

    @model_validator(mode="after")
    def check(self):
        maximum, overlap = ((self.max_tokens, self.overlap_tokens) if self.count_mode == "token"
                            else (self.max_chars, self.overlap_chars))
        if overlap >= maximum:
            raise ValueError("重叠长度必须小于文本块长度")
        if self.count_mode == "token" and not self.tokenizer_name:
            raise ValueError("token 模式需要真实 tokenizer 标识")
        if self.count_mode == "character" and (self.tokenizer_name or self.tokenizer_revision):
            raise ValueError("字符模式 tokenizer 字段必须为 null")
        return self


class Metadata(Input):
    title: Text | None = None
    authors: list[Text] = Field(default_factory=list)
    year: Year | None = None
    topics: list[Text] = Field(default_factory=list)
    language: Literal["zh", "en", "mixed", "unknown"] = "unknown"
    source_url: Text | None = None
    rights_note: Text = "待人工确认"


class Filters(Input):
    year_from: Year | None = None
    year_to: Year | None = None
    topics: list[Text] = Field(default_factory=list)

    @model_validator(mode="after")
    def check(self):
        if self.year_from is not None and self.year_to is not None and self.year_from > self.year_to:
            raise ValueError("起始年份不能大于结束年份")
        return self


class Document(Output):
    doc_id: Text
    title: Text
    authors: list[Text]
    year: Year | None
    topics: list[Text]
    language: Literal["zh", "en", "mixed", "unknown"]
    source_url: str | None
    rights_note: Text
    file_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    status: Literal["uploaded", "parsing", "indexing", "ready", "failed"]
    error_code: str | None
    error_message: str | None
    page_count: Annotated[int, Field(ge=0)] | None


class DocumentSnapshot(Output):
    title: Text
    authors: list[Text]
    year: Year | None
    topics: list[Text]
    language: Literal["zh", "en", "mixed", "unknown"]


class Chunk(Output):
    chunk_id: Text
    doc_id: Text
    pdf_page: Annotated[int, Field(strict=True, ge=1)]
    printed_page: str | None
    section: str | None
    text: Text
    page_char_start: Annotated[int, Field(strict=True, ge=0)]
    page_char_end: Annotated[int, Field(strict=True, gt=0)]
    token_count: Annotated[int, Field(strict=True, ge=0)] | None
    char_count: Annotated[int, Field(strict=True, ge=0)] | None = None
    document: DocumentSnapshot

    @model_validator(mode="after")
    def check(self):
        if self.page_char_end - self.page_char_start != len(self.text):
            raise ValueError("文本长度与页内半开偏移不一致")
        if self.token_count is None and self.char_count != len(self.text):
            raise ValueError("字符模式必须提供实际 char_count")
        return self


class Scores(Output):
    bm25: float | None
    cosine: float | None
    rrf: float | None
    rerank: float | None


class RetrievalHit(Output):
    rank: Annotated[int, Field(strict=True, ge=1)]
    chunk: Chunk
    scores: Scores
    matched_by: list[Literal["keyword", "vector"]]
    index_version: Text


class SearchRequest(Input):
    query: Query
    filters: Filters = Field(default_factory=Filters)
    mode: Mode = "hybrid"
    top_k: Annotated[int, Field(strict=True, ge=1, le=50)] = 20


class AskRequest(Input):
    question: Query
    filters: Filters = Field(default_factory=Filters)
    history: list = Field(default_factory=list)


class QueryPlan(Output):
    original_query: str
    intent: Literal["find", "explain", "compare", "clarify"]
    rewritten_query: str
    keywords: list[str]
    needs_clarification: bool
    clarification_question: str | None
    clarification_options: list[str]


class Highlight(Output):
    start: Annotated[int, Field(strict=True, ge=0)]
    end: Annotated[int, Field(strict=True, gt=0)]
    text: Text


class Citation(Output):
    evidence_id: Text
    highlights: Annotated[list[Highlight], Field(min_length=1, max_length=6)]


class Claim(Output):
    claim_id: Text
    text: Text
    evidence_ids: Annotated[list[Text], Field(min_length=1)]
    citations: list[Citation] = Field(default_factory=list)


class Evidence(Output):
    evidence_id: Text
    chunk_id: Text
    doc_id: Text
    title: Text
    authors: list[Text]
    year: Year | None
    pdf_page: Annotated[int, Field(strict=True, ge=1)]
    printed_page: str | None
    quote: Text
    file_url: Text

    @model_validator(mode="after")
    def check(self):
        if self.file_url != f"/documents/{self.doc_id}/file#page={self.pdf_page}":
            raise ValueError("证据链接必须指向服务端文献 ID 与 PDF 文件页码")
        return self


class RelatedDocument(Output):
    doc_id: Text
    title: Text


class ErrorInfo(Output):
    code: Text
    message: Text


class Timings(Output):
    planning: Annotated[float, Field(ge=0)]
    retrieval: Annotated[float, Field(ge=0)]
    generation: Annotated[float, Field(ge=0)]
    total: Annotated[float, Field(ge=0)]


class AnswerSection(Output):
    heading: Annotated[str, Field(max_length=80)] = ""
    claim_ids: Annotated[list[Text], Field(min_length=1)]


class AnswerResponse(Output):
    request_id: Text
    status: Literal["answered", "needs_clarification", "insufficient_evidence", "error"]
    query_plan: QueryPlan
    claims: list[Claim]
    answer_sections: list[AnswerSection] = Field(default_factory=list)
    evidence: list[Evidence]
    related_documents: list[RelatedDocument]
    limitations: list[str]
    clarification_question: str | None
    clarification_options: list[str]
    index_version: str | None
    timings_ms: Timings
    error: ErrorInfo | None

    @model_validator(mode="after")
    def check(self):
        ids = [e.evidence_id for e in self.evidence]
        if len(set(ids)) != len(ids) or len({c.claim_id for c in self.claims}) != len(self.claims):
            raise ValueError("引用或结论 ID 重复")
        if self.status == "answered":
            if not self.claims or not self.index_version or self.error:
                raise ValueError("answered 需要结论、索引版本且不能含错误")
            if any(not set(c.evidence_ids) <= set(ids) for c in self.claims):
                raise ValueError("结论包含无法解析的引用")
            sources = {e.evidence_id: e.quote for e in self.evidence}
            for claim in self.claims:
                if claim.citations and (len({c.evidence_id for c in claim.citations}) != len(claim.citations)
                        or {c.evidence_id for c in claim.citations} != set(claim.evidence_ids)):
                    raise ValueError("句子定位必须覆盖结论的所有引用")
                for citation in claim.citations:
                    for span in citation.highlights:
                        if span.end <= span.start or sources[citation.evidence_id][span.start:span.end] != span.text:
                            raise ValueError("高亮文字必须为对应原文的精确子串")
        elif self.claims:
            raise ValueError("非 answered 状态的 claims 必须为空")
        if self.answer_sections:
            used = [cid for section in self.answer_sections for cid in section.claim_ids]
            if sorted(used) != sorted(c.claim_id for c in self.claims) or self.status != "answered":
                raise ValueError("回答段落须完整、不重复地引用本次结论")
        if self.status == "needs_clarification" and not self.clarification_question:
            raise ValueError("澄清状态需要追问")
        if self.status == "insufficient_evidence" and not self.limitations:
            raise ValueError("证据不足需要说明原因")
        if (self.status == "error") != (self.error is not None):
            raise ValueError("error 只用于错误状态")
        return self


class IndexManifest(Output):
    index_version: Text
    contract_version: Literal["1.0"]
    built_at: Text
    embedding_model: Text
    embedding_revision: str | None
    dimension: Annotated[int, Field(gt=0)]
    normalized: bool
    chunking_config: ChunkingConfig | None
    tokenizer: dict | None
    document_count: Annotated[int, Field(ge=0)]
    chunk_count: Annotated[int, Field(ge=0)]
    corpus_hash: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]

    @model_validator(mode="after")
    def check_time(self):
        from datetime import datetime
        stamp = datetime.fromisoformat(self.built_at)
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            raise ValueError("built_at 必须是带时区的 ISO 8601 时间")
        return self


class Feedback(Input):
    request_id: Text
    rating: Literal["useful", "not_useful"]
    comment: Annotated[str, Field(max_length=2000)] = ""


def error_answer(question: str, code: str, message: str) -> dict:
    from uuid import uuid4
    return AnswerResponse(
        request_id="q_" + uuid4().hex, status="error",
        query_plan=QueryPlan(original_query=question, intent="explain", rewritten_query=question,
                             keywords=[], needs_clarification=False, clarification_question=None,
                             clarification_options=[]),
        claims=[], evidence=[], related_documents=[], limitations=[], clarification_question=None,
        clarification_options=[], index_version=None,
        timings_ms=Timings(planning=0, retrieval=0, generation=0, total=0),
        error=ErrorInfo(code=code, message=message),
    ).model_dump()

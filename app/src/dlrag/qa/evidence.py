"""Select whole, traceable chunks, preserving rank and document diversity."""
import copy
from urllib.parse import quote
from .errors import ProjectError
from .llm_client import input_upper_bound
from .validation import nonempty, strings


def validate_hits(hits):
    if not isinstance(hits, list):
        raise ProjectError("INDEX_NOT_READY", "检索结果不是片段列表")
    versions, ids = set(), {}
    for hit in hits:
        try:
            c = hit["chunk"]
            d = c["document"]
            valid = (nonempty(hit["index_version"])
                     and all(nonempty(c[k]) for k in ("chunk_id", "doc_id", "text"))
                     and type(c["pdf_page"]) is int and c["pdf_page"] > 0
                     and (c.get("printed_page") is None or isinstance(c["printed_page"], str))
                     and nonempty(d["title"]) and strings(d["authors"])
                     and (d["year"] is None or type(d["year"]) is int)
                     and (c["chunk_id"] not in ids or ids[c["chunk_id"]] == c))
            if not valid:
                raise ValueError()
            ids[c["chunk_id"]] = c
            versions.add(hit["index_version"])
        except (ValueError, KeyError, TypeError):
            raise ProjectError("INDEX_NOT_READY", "检索片段缺少可靠的引用元数据或编号冲突") from None
    if len(versions) > 1:
        raise ProjectError("INDEX_NOT_READY", "单次检索混用了多个索引版本")
    return next(iter(versions), None)


def payload_for(question, plan, chunks):
    from .sentences import annotated_text
    aliases = evidence_aliases(chunks)
    documents = {doc: f'doc_{i}' for i, doc in enumerate(dict.fromkeys(c['doc_id'] for c in chunks), 1)}
    return {"question": question, "intent": plan["intent"], "answer_format":"full", "citation_mode":"model_sentence_selection", "answer_requirements": plan.get("answer_requirements", []), "evidence": [
        {"chunk_id": aliases[c["chunk_id"]], "doc_id": documents[c["doc_id"]],
         "title": c["document"]["title"], "text": annotated_text(c["text"])} for c in chunks]}


def evidence_aliases(chunks):
    ids = {c['chunk_id'] for c in chunks}
    result = {}
    for i, chunk in enumerate(chunks, 1):
        alias = f'source_{i}'
        while alias in ids:
            alias = '_' + alias
        result[chunk['chunk_id']] = alias
    return result


def restore_references(value, chunks):
    """Model uses short request-local aliases; public references always use real chunk IDs."""
    aliases = {alias: cid for cid, alias in evidence_aliases(chunks).items()}
    value = copy.deepcopy(value)
    if not isinstance(value, dict) or not isinstance(value.get('claims'), list):
        return value
    for claim in value['claims']:
        if not isinstance(claim, dict):
            continue
        if isinstance(claim.get('evidence_chunk_ids'), list):
            claim['evidence_chunk_ids'] = [aliases.get(cid,cid) if isinstance(cid,str) else cid for cid in claim['evidence_chunk_ids']]
        if isinstance(claim.get('evidence_sentences'), dict):
            remapped = {}
            for cid, sids in claim['evidence_sentences'].items():
                actual = aliases.get(cid,cid)
                if actual in remapped:
                    raise ProjectError('OUTPUT_VALIDATION_FAILED','同一证据不能重复使用别名与原编号')
                remapped[actual] = sids
            claim['evidence_sentences'] = remapped
    return value


def select_evidence(hits, question, plan, settings, systems):
    candidates, seen, candidate_hits = [], set(), {}
    for hit in hits:
        c = hit["chunk"]
        # Normalize only for duplicate detection; quotes always retain original text.
        key = (c["doc_id"], " ".join(c["text"].split()))
        if key not in seen:
            candidates.append(c)
            candidate_hits[c["chunk_id"]] = hit
            seen.add(key)
    # Legacy mode is retained as an explicit ablation, not the production default.
    first, rest, docs = [], [], set()
    for c in candidates:
        (first if c["doc_id"] not in docs else rest).append(c)
        docs.add(c["doc_id"])
    selected = []
    remaining = candidates[:] if settings.get("evidence_rerank_enabled", True) else first + rest
    while remaining:
        if len(selected) >= settings["max_evidence_chunks"]:
            break
        if settings.get("evidence_rerank_enabled", True):
            def utility(chunk):
                hit = candidate_hits[chunk["chunk_id"]]
                base = hit.get("local_rerank", {}).get("score", 1 / (60 + hit["rank"]))
                same_doc = sum(c["doc_id"] == chunk["doc_id"] for c in selected)
                # Diversity is a soft preference; relevant same-document content
                # is allowed to beat irrelevant content from a different paper.
                semantic = 'semantic_relevance' in hit
                penalty = (.02 if plan["intent"] == "compare" else .005) * same_doc if semantic else (.16 if plan["intent"] == "compare" else .04) * same_doc
                linked = set(hit.get("neighbor_of", [])) & {c["chunk_id"] for c in selected}
                bonus = (.03 if semantic else .20) if linked and not hit.get("local_rerank", {}).get("reference_like", False) else 0
                overlap = 0.0
                for previous in selected:
                    if previous["doc_id"] == chunk["doc_id"] and previous["pdf_page"] == chunk["pdf_page"]:
                        shared = max(0, min(previous["page_char_end"], chunk["page_char_end"]) - max(previous["page_char_start"], chunk["page_char_start"]))
                        overlap = max(overlap, shared / max(1, len(chunk["text"])))
                coverage_gain = 0.0
                for aspect, relevance in hit.get('aspect_scores',{}).items():
                    already = max((candidate_hits[c['chunk_id']].get('aspect_scores',{}).get(aspect,0) for c in selected),default=0)
                    coverage_gain += max(0,relevance-already)
                return base + bonus + .35 * coverage_gain - penalty - .25 * overlap
            c = max(remaining, key=utility)
        else:
            c = remaining[0]
        remaining.remove(c)
        trial = selected + [c]
        payload = payload_for(question, plan, trial)
        # Reserve the largest repair prompt and a fixed validation-error envelope.
        repair_payload = {**payload, "validation_error": "验" * 100}
        size = max(input_upper_bound(system, repair_payload) for system in systems)
        if size <= settings["context_budget_tokens"] and size + settings["max_output_tokens"] <= settings["context_window_tokens"]:
            selected.append(copy.deepcopy(c))
    return selected


def public_answer(value, chunks):
    from .sentences import sentence_spans
    by_id = {c["chunk_id"]: c for c in chunks}
    evidence, mapping, claims = [], {}, []
    for claim in value["claims"]:
        refs = []
        for cid in dict.fromkeys(claim["evidence_chunk_ids"]):
            if cid not in mapping:
                c = by_id[cid]
                d = c["document"]
                eid = "ev_" + str(len(evidence) + 1)
                mapping[cid] = eid
                evidence.append(dict(evidence_id=eid, chunk_id=cid, doc_id=c["doc_id"],
                    title=d["title"], authors=copy.deepcopy(d["authors"]), year=d["year"],
                    pdf_page=c["pdf_page"], printed_page=c.get("printed_page"), quote=c["text"],
                    file_url=f'/documents/{quote(c["doc_id"], safe="")}/file#page={c["pdf_page"]}'))
            refs.append(mapping[cid])
        citations = []
        for cid, sentence_ids in claim.get("evidence_sentences", {}).items():
            spans = {s["sentence_id"]: s for s in sentence_spans(by_id[cid]["text"])}
            citations.append(dict(evidence_id=mapping[cid], highlights=[
                {k: spans[sid][k] for k in ("start", "end", "text")} for sid in dict.fromkeys(sentence_ids)]))
        claims.append(dict(claim_id="cl_" + str(len(claims) + 1), text=claim["text"], evidence_ids=refs, citations=citations))
    return claims, evidence


def related_documents(chunks):
    result, seen = [], set()
    for c in chunks:
        if c["doc_id"] not in seen:
            result.append({"doc_id": c["doc_id"], "title": c["document"]["title"]})
            seen.add(c["doc_id"])
    return result

"""v1.0 local evidence reranking, not a neural semantic reranking service."""
import copy
import re
from functools import lru_cache
from dlrag.retrieval.lexical import BM25, tokenize

STOP_WORDS = set("a an the and or of in on to for with by from is are was were be been being do does did how what which when where why can could would should this that these those it its as at using use uses".split())


@lru_cache(maxsize=8192)
def reference_features(text):
    """Detect bibliography-like structure, not ordinary parenthesized citations."""
    heading = bool(re.search(r"(?:^|\n)\s*(?:\d+[.\s]*)?(?:references|bibliography|参考文献)\s*(?:\n|$)", text, re.I))
    years = len(re.findall(r"\b(?:19|20)\d{2}[a-z]?\.\s+[A-Z]", text))
    years += len(re.findall(r",\s*(?:19|20)\d{2}[a-z]?\.\s*(?:\d+(?:[,\s–-]+\d+)*\.?)?\s*$", text, re.M))
    numbered = len(re.findall(r"(?:^|\n)\s*\[\d+\]\s+[A-Z]", text))
    paragraph_entries = len(re.findall(r'(?:^|\n\n)[^\n]{0,240}?\b(?:19|20)\d{2}[a-z]?\.\s+[A-Z]', text))
    is_reference = years >= 3 or numbered >= 3 or paragraph_entries >= 2 or (heading and (years >= 1 or numbered >= 1))
    return is_reference, years, numbered, heading


def rerank(hits, question, plan, settings):
    if not hits:
        return []
    texts = [h["chunk"]["text"] for h in hits]
    query = " ".join([question, plan["rewritten_query"], plan.get("english_query") or "", plan.get('mechanism_query') or '', *plan["keywords"]])
    body_query = " ".join(term for term in tokenize(query) if term not in STOP_WORDS)
    body = BM25([tokenize(text) for text in texts]).scores(body_query, list(range(len(texts))))
    top_body = max(body.values(), default=1.0)
    prior = [h.get("query_fusion_score", 1.0 / (60 + h["rank"])) for h in hits]
    max_prior = max(prior, default=1.0) or 1.0
    result = []
    for i, hit in enumerate(hits):
        item = copy.deepcopy(hit)
        is_ref, years, numbered, heading = reference_features(texts[i])
        body_score = body.get(i, 0.0) / top_body
        score = .45 * prior[i] / max_prior + .55 * body_score
        penalty = .80 if settings["reference_penalty_enabled"] and is_ref else 0.0
        item["local_rerank"] = dict(score=score - penalty, body_bm25=body.get(i, 0.0),
            normalized_body_bm25=body_score, reference_penalty=penalty, reference_like=is_ref,
            reference_signals=dict(year_entries=years, numbered_entries=numbered, heading=heading),
            neighbor_of=copy.deepcopy(hit.get("neighbor_of", [])))
        item["scores"]["rerank"] = score - penalty
        result.append(item)
    return sorted(result, key=lambda h: (-h["local_rerank"]["score"], h["rank"], h["chunk"]["chunk_id"]))


def expand_neighbors(retriever, ranked, filters, version, settings):
    lookup = getattr(retriever, "get_neighbors", None)
    if not settings["neighbor_expansion_enabled"] or not callable(lookup):
        return ranked, 0
    result = copy.deepcopy(ranked)
    by_id = {h["chunk"]["chunk_id"]: h for h in result}
    anchors = [h for h in ranked if not h.get("local_rerank", {}).get("reference_like", False)][:settings["neighbor_seed_k"]]
    calls = 0
    for anchor in anchors:
        cid = anchor["chunk"]["chunk_id"]
        neighbors = lookup(cid, radius=settings["neighbor_radius"], filters=filters, expected_index_version=version)
        calls += 1
        for neighbor in neighbors:
            nid = neighbor["chunk"]["chunk_id"]
            if nid not in by_id:
                item = copy.deepcopy(neighbor)
                item["rank"] = len(result) + 1
                item["query_fusion_score"] = 0.0
                item["neighbor_of"] = []
                result.append(item)
                by_id[nid] = item
            if cid not in by_id[nid].setdefault("neighbor_of", []):
                by_id[nid]["neighbor_of"].append(cid)
    return result, calls

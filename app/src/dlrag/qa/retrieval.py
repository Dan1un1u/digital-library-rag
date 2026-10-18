"""Fuse query-language branches without adding incompatible raw scores."""
import copy
from .evidence import validate_hits


def fuse_queries(groups, rrf_k=60):
    all_hits = [hit for group in groups for hit in group]
    validate_hits(all_hits)  # Reject snapshot changes even when chunk IDs overlap.
    merged, values = {}, {}
    for query_index, hits in enumerate(groups):
        seen = set()
        for rank, hit in enumerate(hits, 1):
            cid = hit["chunk"]["chunk_id"]
            if cid in seen:
                continue
            seen.add(cid)
            if cid not in merged:
                merged[cid] = copy.deepcopy(hit)
                merged[cid]["query_matches"] = []
            target = merged[cid]
            target["query_matches"].append(dict(query_index=query_index, rank=rank,
                                                  scores=copy.deepcopy(hit["scores"])))
            target["matched_by"] = sorted(set(target["matched_by"]) | set(hit["matched_by"]))
            # A representative branch's original scores are kept untouched.
            values[cid] = values.get(cid, 0.0) + 1.0 / (rrf_k + rank)
    ranked = sorted(merged, key=lambda cid: (-values[cid], cid))
    result = []
    for rank, cid in enumerate(ranked, 1):
        hit = merged[cid]
        hit["rank"], hit["query_fusion_score"] = rank, values[cid]
        result.append(hit)
    return result

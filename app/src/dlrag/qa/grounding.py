"""Select exact support sentences with a reranker instead of asking the LLM to copy offsets."""
import copy
from .sentences import sentence_spans


def ground_sentences(value, chunks, reranker):
    value = copy.deepcopy(value)
    by_id = {c['chunk_id']:c for c in chunks}
    tasks = []
    for claim in value['claims']:
        refs = list(dict.fromkeys(claim['evidence_chunk_ids']))
        candidates, lookup = [], {}
        quota = max(1,60 // len(refs))
        for cid in refs:
            for span in sentence_spans(by_id[cid]['text'])[:quota]:
                sid = f"sentence_{len(candidates)+1}"
                lookup[sid] = (cid,span['sentence_id'])
                candidates.append({'rank':len(candidates)+1,'chunk':{'chunk_id':sid,'text':span['text']},'scores':{}})
        tasks.append((claim, refs, candidates, lookup))
    ranked_tasks = (reranker.rerank_many([(claim['text'], candidates) for claim, _, candidates, _ in tasks])
                    if callable(getattr(reranker, 'rerank_many', None)) else
                    [reranker.rerank(claim['text'], candidates) for claim, _, candidates, _ in tasks])
    for (claim, refs, _, lookup), ranked in zip(tasks, ranked_tasks):
        positions = {}
        for hit in ranked:
            cid,sid = lookup[hit['chunk']['chunk_id']]
            # One strongest support sentence for each cited source, with a close
            # second when both independently rank highly for the complete claim.
            selected = positions.setdefault(cid,[])
            if not selected:
                selected.append((sid,hit['semantic_relevance']))
            elif len(selected)==1 and hit['semantic_relevance'] >= max(.65,selected[0][1]-.08):
                selected.append((sid,hit['semantic_relevance']))
        claim['evidence_sentences'] = {cid:[sid for sid,_ in positions[cid]] for cid in refs}
    return value

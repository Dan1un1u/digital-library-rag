"""Bounded SiliconFlow cross-encoder reranking; no generation or hidden retries."""
import copy
import math
from urllib.parse import urlparse
import requests
from .errors import ProjectError


class SiliconFlowReranker:
    method = 'semantic_cross_encoder'
    def __init__(self, api_key, model='BAAI/bge-reranker-v2-m3', base_url='https://api.siliconflow.cn/v1', timeout=20, session=None):
        parsed = urlparse(base_url)
        if parsed.scheme != 'https' or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ProjectError('INVALID_REQUEST', '重排服务地址非法')
        self.key, self.model, self.url = api_key, model, base_url.rstrip('/') + '/rerank'
        self.timeout, self.session = timeout, session or requests.Session()

    def rerank(self, query, hits):
        if not self.key:
            raise ProjectError('MODEL_NOT_CONFIGURED', '语义重排未配置')
        candidates = hits[:60]
        if not candidates:
            return []
        try:
            payload = {'model':self.model, 'query':query, 'documents':[h['chunk']['text'] for h in candidates],
                       'top_n':len(candidates), 'return_documents':False}
            if self.model.startswith('Qwen/Qwen3-Reranker-'):
                payload['instruction'] = ('Rank passages that directly answer the user question. For how or why questions, '
                    'prefer explanations of the process, mechanism, conditions and limitations over generic topic mentions, '
                    'titles, bibliographies and figure legends. Judge only what each passage actually explains.')
            response = self.session.post(self.url, headers={'Authorization':'Bearer ' + self.key},
                json=payload, timeout=self.timeout, allow_redirects=False)
            response.raise_for_status()
            rows = response.json()['results']
            if not isinstance(rows, list) or len(rows) != len(candidates):
                raise ValueError()
            result, seen = [], set()
            for row in rows:
                i, score = row['index'], row['relevance_score']
                if (type(i) is not int or i not in range(len(candidates)) or i in seen
                        or type(score) not in (int,float) or not math.isfinite(score) or not 0 <= score <= 1):
                    raise ValueError()
                seen.add(i)
                item = copy.deepcopy(candidates[i])
                local = item.get('local_rerank', {})
                # Keep reference suppression, but let semantic relevance dominate lexical frequency.
                combined = .90 * score + .10 * max(0, local.get('score', 0)) - local.get('reference_penalty', 0)
                item['semantic_relevance'] = score
                item.setdefault('local_rerank', {}).update(score=combined, semantic_relevance=score)
                item['scores']['rerank'] = combined
                result.append(item)
            return sorted(result, key=lambda h:(-h['scores']['rerank'],h['rank']))
        except (requests.RequestException, KeyError, ValueError, TypeError, IndexError):
            raise ProjectError('MODEL_UNAVAILABLE', '语义重排服务不可用或输出非法') from None


def rank_question_and_mechanism(reranker, question, mechanism, hits):
    primary = reranker.rerank(question,hits)
    if not mechanism:
        return primary
    technical = reranker.rerank('Find explanations of the following mechanisms: ' + mechanism,hits)
    by_id = {h['chunk']['chunk_id']:h for h in technical}
    result = []
    for hit in primary:
        other = by_id[hit['chunk']['chunk_id']]
        item = copy.deepcopy(hit)
        scores = {'question':hit['semantic_relevance'],'mechanism':other['semantic_relevance']}
        item['aspect_scores'] = scores
        item['semantic_relevance'] = max(scores.values())
        item['scores']['rerank'] = max(hit['scores']['rerank'],other['scores']['rerank'])
        item['local_rerank'].update(score=item['scores']['rerank'],semantic_relevance=item['semantic_relevance'],aspect_scores=scores)
        result.append(item)
    return sorted(result,key=lambda h:(-h['scores']['rerank'],h['rank']))

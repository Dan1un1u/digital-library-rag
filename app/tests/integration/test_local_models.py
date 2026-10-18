"""Protocol, provenance, malformed results and batching at the new service boundaries."""
import copy
import json
from types import SimpleNamespace
import pytest
from dlrag.qa.errors import ProjectError as QAError
from dlrag.qa.llm_client import CLIProxyLLM, ScriptedMockLLM, SiliconFlowLLM
from dlrag.qa.semantic_reranker import LLMReranker
from dlrag.retrieval.embeddings import LocalBGEEmbedding
from dlrag.retrieval.errors import ProjectError as RetrievalError

REVISION = '5617a9f61b028005a4858fdac845db406aefb181'


class Response:
    status_code = 200
    def __init__(self, payload):
        self.payload = payload
    def json(self):
        return self.payload


class Session:
    def __init__(self, health=None):
        self.health = health or {'status': 'ready', 'dtype': 'float16', 'device': 'cuda:0',
            'model': 'BAAI/bge-m3', 'dimension': 2, 'source_revision': REVISION,
            'pooling': 'CLS', 'normalization': 'L2'}
        self.calls = []
    def get(self, url, **kwargs):
        self.calls.append(('get', url, kwargs))
        return Response(self.health)
    def post(self, url, **kwargs):
        self.calls.append(('post', url, kwargs))
        return Response({'model': 'BAAI/bge-m3', 'data': [{'index': 0, 'embedding': [1., 0.]}]})


def test_local_embedding_no_cloud_key_and_pinned_identity():
    session = Session()
    backend = LocalBGEEmbedding(revision=REVISION, dimension=2, session=session)
    assert backend.encode(['metadata quality']).tolist() == [[1., 0.]]
    assert session.calls[0][1] == 'http://127.0.0.1:18080/health'
    assert session.calls[1][2]['headers'] == {}
    assert session.trust_env is False
    assert backend.get_config()['revision_pinned']
    assert backend.get_config()['provider'] == 'local-bge-fp16'


@pytest.mark.parametrize('changed', [{'dtype': 'float32'}, {'source_revision': 'different'},
    {'dimension': 1024}, {'pooling': 'mean'}, {'device': 'cpu'}, {'status': 'loading'}])
def test_local_embedding_rejects_mismatched_runtime(changed):
    session = Session()
    session.health.update(changed)
    with pytest.raises(RetrievalError):
        LocalBGEEmbedding(revision=REVISION, dimension=2, session=session).encode(['test'])
    assert len(session.calls) == 1


@pytest.mark.parametrize('url', ['http://external.example/v1', 'http://127.0.0.1.evil/v1',
    'http://user:secret@127.0.0.1/v1', 'http://127.0.0.1/v1?secret=x'])
def test_loopback_adapters_reject_external_or_credential_urls(url):
    with pytest.raises(QAError):
        CLIProxyLLM(base_url=url)
    with pytest.raises(RetrievalError):
        LocalBGEEmbedding(base_url=url, revision=REVISION)


def test_cloud_adapter_still_rejects_plaintext_transport():
    with pytest.raises(QAError):
        SiliconFlowLLM(base_url='http://127.0.0.1:8317/v1')


def test_luna_request_uses_openai_parameters_and_preserves_images():
    client = CLIProxyLLM(api_key='private', model='gpt-6-luna', base_url='http://127.0.0.1:8317/v1')
    messages = [{'role': 'user', 'content': [{'type': 'image_url', 'image_url': {'url': 'data:image/jpeg;base64,abc'}}]}]
    payload = client.build_request(messages)
    assert payload['messages'] == messages
    assert payload['reasoning_effort'] == 'none'
    assert payload['max_completion_tokens'] == 1000
    assert not {'temperature', 'enable_thinking', 'max_tokens'} & payload.keys()
    assert 'private' not in json.dumps(client.get_config())


def hits():
    return [{'rank': i + 1, 'chunk': {'chunk_id': str(i), 'text': text}, 'scores': {}}
            for i, text in enumerate(['metadata quality rules', 'unrelated photosynthesis'])]


def outputs(rows):
    return {'tasks': [{'task': 0, 'results': rows}]}


def test_llm_reranking_cache_preserves_current_source_and_penalty():
    client = ScriptedMockLLM([outputs([{'index': 1, 'relevance_score': .1}, {'index': 0, 'relevance_score': .9}])])
    client.model = 'gpt-6-luna'
    reranker = LLMReranker(client)
    candidates = hits()
    original = copy.deepcopy(candidates)
    ranked = reranker.rerank('metadata', candidates)
    assert ranked[0]['chunk']['chunk_id'] == '0' and candidates == original
    candidates[0]['local_rerank'] = {'reference_penalty': 1}
    reranked = reranker.rerank('metadata', candidates)
    assert reranked[0]['chunk']['chunk_id'] == '1'
    assert len(client.calls) == 1


@pytest.mark.parametrize('rows', [[], [{'index': 0, 'relevance_score': .9}] * 2,
    [{'index': 0, 'relevance_score': True}, {'index': 1, 'relevance_score': .2}],
    [{'index': 0, 'relevance_score': float('nan')}, {'index': 1, 'relevance_score': .2}],
    [{'index': 0, 'relevance_score': 1.5}, {'index': 1, 'relevance_score': .2}]])
def test_llm_reranker_rejects_missing_duplicate_and_invalid_scores(rows):
    client = ScriptedMockLLM([outputs(rows)])
    client.model = 'gpt-6-luna'
    with pytest.raises(QAError):
        LLMReranker(client).rerank('metadata', hits())


def test_llm_reranker_batches_tasks_and_restores_task_order():
    rows = [{'index': 0, 'relevance_score': .9}, {'index': 1, 'relevance_score': .2}]
    client = ScriptedMockLLM([{'tasks': [{'task': 1, 'results': list(reversed(rows))}, {'task': 0, 'results': rows}]}])
    client.model = 'gpt-6-luna'
    ranked = LLMReranker(client).rerank_many([('metadata', hits()), ('rules', hits())])
    assert len(client.calls) == 1 and len(ranked) == 2
    assert all(group[0]['chunk']['chunk_id'] == '0' for group in ranked)

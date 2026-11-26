import copy
import pytest
import requests
from dlrag.qa import QAEngine, ScriptedMockLLM, ProjectError
from dlrag.qa.demo import FakeRetriever, demo_outputs
from dlrag.qa.coverage import validate_coverage
from dlrag.qa.planner import original_plan, validate_plan
from dlrag.qa.semantic_reranker import SiliconFlowReranker


class Response:
    def __init__(self, rows): self.rows = rows
    def raise_for_status(self): pass
    def json(self): return {'results':self.rows}


class Session:
    def __init__(self, rows): self.rows, self.calls = rows, []
    def post(self,*args,**kwargs):
        self.calls.append(kwargs)
        return Response(self.rows)


def test_cross_encoder_reorders_keyword_prior_and_preserves_source():
    retriever = FakeRetriever()
    hits = retriever.search('query')
    duplicate = copy.deepcopy(hits[0])
    duplicate['chunk']['chunk_id'] = 'mechanism'
    duplicate['chunk']['text'] = 'Relevant mechanism.'
    duplicate['rank'] = 2
    hits.append(duplicate)
    before=copy.deepcopy(hits)
    session=Session([{'index':1,'relevance_score':.95},{'index':0,'relevance_score':.02}])
    output=SiliconFlowReranker('secret', session=session).rerank('mechanism',hits)
    assert output[0]['chunk']['chunk_id']=='mechanism'
    assert hits==before and output[1]['semantic_relevance']==.02
    assert session.calls[0]['json']['return_documents'] is False
    assert session.calls[0]['timeout']==20


@pytest.mark.parametrize('rows',[
    [],[{'index':True,'relevance_score':.1}],[{'index':5,'relevance_score':.1}],
    [{'index':0,'relevance_score':float('nan')}],[{'index':0,'relevance_score':True}],
    [{'index':0,'relevance_score':1.1}]])
def test_reranker_rejects_malformed_results(rows):
    with pytest.raises(ProjectError,match='语义重排'):
        SiliconFlowReranker('secret',session=Session(rows)).rerank('query',FakeRetriever().search('query'))


def test_reference_penalty_survives_semantic_rerank():
    hits=FakeRetriever().search('query')
    hits[0]['local_rerank']={'score':.1,'reference_penalty':.8}
    output=SiliconFlowReranker('secret',session=Session([{'index':0,'relevance_score':.8}])).rerank('query',hits)
    assert output[0]['scores']['rerank']<0


def test_question_requirements_are_preserved_and_bounded():
    plan={**original_plan('如何工作'), 'answer_requirements':['处理流程是什么？','有哪些限制？']}
    assert validate_plan(plan,'如何工作')['answer_requirements']==plan['answer_requirements']
    plan['answer_requirements']*=3
    with pytest.raises(ProjectError):validate_plan(plan,'如何工作')


def test_unaccounted_facets_trigger_single_existing_repair():
    plan, good=demo_outputs('BM25','answered')
    plan['answer_requirements']=['是什么？','有什么限制？']
    good['coverage']=[{'requirement':'是什么？','claim_indices':[1],'gap':''},
                      {'requirement':'有什么限制？','claim_indices':[],'gap':'原文没有提供限制。'}]
    bad=copy.deepcopy(good);bad['coverage']=bad['coverage'][:1]
    llm=ScriptedMockLLM([plan,bad,good])
    result=QAEngine(FakeRetriever(),llm,{}).ask({'question':'BM25'})
    assert result['status']=='answered' and len(llm.calls)==3
    assert result['coverage']==good['coverage']
    assert result['diagnostics']['selected_chunks']==1
    assert result['diagnostics']['cited_chunks']==1


@pytest.mark.parametrize('coverage',[
    [{'requirement':'如何工作','claim_indices':[],'gap':''}],
    [{'requirement':'如何工作','claim_indices':[99],'gap':''}],
    [{'requirement':'如何工作','claim_indices':[],'gap':'缺口'}],
    [{'requirement':'other','claim_indices':[1],'gap':''}]])
def test_coverage_cannot_silently_omit_answer_or_question(coverage):
    answer=demo_outputs('BM25','answered')[1];answer['coverage']=coverage
    with pytest.raises(ProjectError):validate_coverage(answer,['如何工作'])


def test_semantic_failure_is_visible_and_uses_local_fallback():
    class Broken:
        model='broken'
        def rerank(self,query,hits):raise ProjectError('MODEL_UNAVAILABLE','private provider body')
    engine=QAEngine(FakeRetriever(),ScriptedMockLLM(demo_outputs('BM25','answered')),{},reranker=Broken())
    result=engine.ask({'question':'BM25'})
    assert result['status']=='answered'
    assert result['diagnostics']['semantic_rerank_status']=='fallback_local'
    assert any('语义重排暂不可用' in s for s in result['limitations'])
    assert 'private provider' not in str(result)


def test_mechanism_query_uses_same_filters_and_one_extra_search():
    plan, answer=demo_outputs('如何处理长文本','answered')
    plan.update(english_query='How to process long texts',mechanism_query='long text processing attention mechanism')
    retriever=FakeRetriever()
    filters={'year_from':2020,'year_to':2025,'topics':['IR']}
    result=QAEngine(retriever,ScriptedMockLLM([plan,answer]),{}).ask({'question':plan['original_query'],'filters':filters})
    assert result['status']=='answered' and len(retriever.calls)==3
    assert retriever.calls[-1][0]==plan['mechanism_query']
    assert all(call[1]==filters for call in retriever.calls)
    assert result['diagnostics']['model_calls']==2


def test_disabling_bilingual_skips_english_mechanism_branch():
    plan, answer=demo_outputs('如何处理长文本','answered')
    plan.update(english_query='How to process long texts',mechanism_query='attention mechanism')
    retriever=FakeRetriever()
    result=QAEngine(retriever,ScriptedMockLLM([plan,answer]),{'bilingual_retrieval_enabled':False}).ask({'question':plan['original_query']})
    assert result['status']=='answered' and len(retriever.calls)==1


def test_thinking_can_be_explicitly_disabled_for_supported_models():
    from dlrag.qa.llm_client import SiliconFlowLLM
    class FakeResponse:
        status_code=200
        def json(self):return {'choices':[{'finish_reason':'stop','message':{'content':'{"ok":true}'}}]}
    class FakeSession:
        def post(self,*args,**kwargs):
            assert kwargs['json']['enable_thinking'] is False
            return FakeResponse()
    assert SiliconFlowLLM('secret',session=FakeSession(),enable_thinking=False).generate_json('JSON',{})=={'ok':True}


def test_semantic_neighbor_bonus_does_not_outweigh_direct_relevance():
    from dlrag.qa.evidence import select_evidence
    from dlrag.qa.engine import DEFAULTS
    hits=FakeRetriever().search('query')
    seed=hits[0];seed['local_rerank']={'score':.95};seed['semantic_relevance']=.95
    direct=copy.deepcopy(seed);direct['chunk']['chunk_id']='direct';direct['chunk']['text']='Direct explanation.';direct['local_rerank']['score']=.90
    neighbor=copy.deepcopy(seed);neighbor['chunk']['chunk_id']='neighbor';neighbor['chunk']['text']='Generic background.';neighbor['local_rerank']['score']=.75;neighbor['neighbor_of']=[seed['chunk']['chunk_id']]
    chosen=select_evidence([seed,direct,neighbor],'query',original_plan('query'),{**DEFAULTS,'max_evidence_chunks':2},['JSON'])
    assert [c['chunk_id'] for c in chosen]==[seed['chunk']['chunk_id'],'direct']


def test_short_model_ids_resolve_to_exact_public_citations():
    from dlrag.qa.evidence import payload_for
    chunks=FakeRetriever().chunks
    plan,answer=demo_outputs('BM25','answered')
    alias=payload_for('BM25',plan,chunks)['evidence'][0]['chunk_id']
    assert len(alias)<len(chunks[0]['chunk_id'])
    answer['claims'][0]['evidence_chunk_ids']=[alias]
    answer['claims'][0]['evidence_sentences']={alias:['s1']}
    output=QAEngine(FakeRetriever(),ScriptedMockLLM([plan,answer]),{'sentence_citations_required':True}).ask({'question':'BM25'})
    assert output['status']=='answered'
    assert output['evidence'][0]['chunk_id']==chunks[0]['chunk_id']
    assert output['claims'][0]['citations'][0]['highlights'][0]['text']==chunks[0]['text']


def test_short_id_namespace_does_not_collide_with_existing_id():
    from dlrag.qa.evidence import evidence_aliases,restore_references
    chunks=FakeRetriever().chunks
    chunks[0]['chunk_id']='source_1'
    assert evidence_aliases(chunks)=={'source_1':'_source_1'}
    value={'claims':[{'evidence_chunk_ids':['_source_1'],'evidence_sentences':{'_source_1':['s1']}}]}
    assert restore_references(value,chunks)['claims'][0]['evidence_chunk_ids']==['source_1']


def test_server_sentence_grounding_selects_exact_source_per_claim():
    from dlrag.qa.grounding import ground_sentences
    chunk=FakeRetriever().chunks[0]
    chunk['text']='Lexical search matches words. Semantic search uses vectors.'
    value={'claims':[{'text':'Lexical matching','evidence_chunk_ids':[chunk['chunk_id']]},
                     {'text':'Semantic vectors','evidence_chunk_ids':[chunk['chunk_id']]}]}
    class Ranker:
        def rerank(self,query,hits):
            result=copy.deepcopy(hits)
            word='Lexical' if query.startswith('Lexical') else 'Semantic'
            for h in result:h['semantic_relevance']=.99 if word in h['chunk']['text'] else .1
            return sorted(result,key=lambda h:-h['semantic_relevance'])
    output=ground_sentences(value,[chunk],Ranker())
    assert output['claims'][0]['evidence_sentences']=={chunk['chunk_id']:['s1']}
    assert output['claims'][1]['evidence_sentences']=={chunk['chunk_id']:['s2']}
    assert 'evidence_sentences' not in value['claims'][0]


def test_server_grounding_keeps_answer_when_provider_unavailable():
    class Ranker:
        model='test'
        def rerank(self,query,hits):
            raise ProjectError('MODEL_UNAVAILABLE','provider secret')
    plan,value=demo_outputs('BM25','answered')
    response=QAEngine(FakeRetriever(),ScriptedMockLLM([plan,value]),{'sentence_citations_required':True},reranker=Ranker()).ask({'question':'BM25'})
    assert response['status']=='answered'
    assert response['diagnostics']['sentence_grounding_status']=='unavailable'
    assert response['claims'][0]['citations']==[]
    assert any('句子定位' in s for s in response['limitations'])
    assert 'provider secret' not in str(response)


def test_question_and_mechanism_rankings_preserve_both_kinds_of_relevance():
    from dlrag.qa.semantic_reranker import rank_question_and_mechanism
    hits=FakeRetriever().search('query')
    tech=copy.deepcopy(hits[0]);tech['chunk']['chunk_id']='technical';hits.append(tech)
    class Ranker:
        def __init__(self):self.calls=[]
        def rerank(self,query,rows):
            self.calls.append(query);technical=query.startswith('Find explanations')
            result=copy.deepcopy(rows)
            for row in result:
                score=.95 if (row['chunk']['chunk_id']=='technical')==technical else .1
                row.update(semantic_relevance=score,local_rerank={'score':score})
                row['scores']['rerank']=score
            return sorted(result,key=lambda h:-h['semantic_relevance'])
    ranker=Ranker();rows=rank_question_and_mechanism(ranker,'main question','input representation',hits)
    assert len(ranker.calls)==2
    assert all(h['semantic_relevance']==.95 for h in rows)
    assert next(h for h in rows if h['chunk']['chunk_id']=='technical')['aspect_scores']=={'question':.1,'mechanism':.95}


def test_two_bibliography_paragraphs_are_not_mistaken_for_mechanism_body():
    from dlrag.qa.reranking import reference_features
    refs='Alice Smith and Bob Jones. 2020. Attention and tokens. In Proceedings.\n\nCarol Davis. 2021. Positional encoding for language models. In Proceedings.'
    body='We use the Transformer (Smith et al., 2020) to process inputs.\n\nThe attention mechanism combines values according to query-key similarities (Davis et al., 2021).'
    assert reference_features(refs)[0] is True
    assert reference_features(body)[0] is False


class RecordingReranker:
    model = "test"

    def __init__(self):
        self.calls = []
        self.batches = []

    @staticmethod
    def rank(hits):
        result = copy.deepcopy(hits)
        for hit in result:
            hit["semantic_relevance"] = .9
            hit.setdefault("local_rerank", {})["score"] = .9
            hit["scores"]["rerank"] = .9
        return result

    def rerank(self, query, hits):
        self.calls.append((query, len(hits)))
        return self.rank(hits)

    def rerank_many(self, tasks):
        self.batches.append([(query, len(hits)) for query, hits in tasks])
        return [self.rank(hits) for _, hits in tasks]


def test_generation_preserves_partial_scope_without_another_model_call():
    plan, value = demo_outputs("BM25", "answered")
    requirement = "BM25 和一般向量量化如何工作？"
    plan["answer_requirements"] = [requirement]
    scope = {"requirement": requirement, "claim_indices": [1],
             "gap": "本次证据只解释 BM25，缺少一般向量量化的流程。"}
    value["coverage"] = [scope]
    ranker, stages = RecordingReranker(), []
    llm = ScriptedMockLLM([plan, value])
    result = QAEngine(FakeRetriever(), llm, {"sentence_citations_required": True},
                      reranker=ranker).ask({"question": "BM25"}, progress=stages.append)

    assert result["status"] == "answered" and len(llm.calls) == 2
    assert llm.calls[1][1]["answer_format"] == "simple"
    assert result["coverage"] == [scope]
    assert result["claims"][0]["citations"][0]["highlights"]
    assert "coverage_check" not in stages and len(ranker.batches) == 1  # The grounding batch.


@pytest.mark.parametrize("coverage", [None, [{"requirement": "如何工作？", "claim_indices": [2], "gap": ""}]])
def test_missing_or_invalid_optional_scope_keeps_the_grounded_answer(coverage):
    plan, value = demo_outputs("BM25", "answered")
    plan["answer_requirements"] = ["如何工作？"]
    if coverage is not None:
        value["coverage"] = coverage
    llm = ScriptedMockLLM([plan, value])
    ranker = RecordingReranker()
    result = QAEngine(FakeRetriever(), llm, {"sentence_citations_required": True},
                      reranker=ranker).ask({"question": "BM25"})

    assert result["status"] == "answered" and result["coverage"] == []
    assert len(llm.calls) == 2 and len(ranker.batches) == 1
    assert result["claims"][0]["citations"][0]["highlights"]


def test_question_and_mechanism_share_one_batch_when_supported():
    from dlrag.qa.semantic_reranker import rank_question_and_mechanism

    ranker = RecordingReranker()
    hits = FakeRetriever().search("question")
    result = rank_question_and_mechanism(ranker, "question", "mechanism", hits)

    assert ranker.calls == []
    assert ranker.batches == [[("question", 1), ("Find explanations of the following mechanisms: mechanism", 1)]]
    assert result[0]["aspect_scores"] == {"question": .9, "mechanism": .9}


@pytest.mark.parametrize("intent,expected", [("explain", 4), ("compare", 8)])
def test_semantic_shortlist_uses_local_ranking_without_truncating_comparisons(intent, expected):
    from dlrag.qa.demo import demo_chunk

    question = "BM25 如何工作？"

    class DistinctQueries(FakeRetriever):
        def search(self, query, filters=None, mode="hybrid", top_k=20):
            hits = super().search(query, filters, mode, top_k)
            if query != question:
                for hit in hits:
                    hit["chunk"]["chunk_id"] += "_other"
                    hit["chunk"]["doc_id"] += "_other"
            return hits

    chunks = []
    for n in range(4):
        chunk = demo_chunk()
        chunk.update(chunk_id=f"test_{n}", pdf_page=n + 1, text=f"BM25 explanation number {n}.")
        chunk.update(page_char_end=len(chunk["text"]), char_count=len(chunk["text"]))
        chunks.append(chunk)
    plan, value = demo_outputs(question, "answered")
    plan.update(intent=intent, english_query="lexical matching scoring")
    value["claims"][0]["evidence_chunk_ids"] = ["source_1"]
    ranker = RecordingReranker()
    response = QAEngine(DistinctQueries(chunks), ScriptedMockLLM([plan, value]),
                        {"retrieval_top_k": 4, "max_evidence_chunks": 2}, reranker=ranker).ask({"question": question})

    assert response["status"] == "answered"
    assert response["diagnostics"]["retrieved_unique_chunks"] == 8
    assert ranker.calls[0][1] == expected
    assert response["diagnostics"]["selected_chunks"] == 2

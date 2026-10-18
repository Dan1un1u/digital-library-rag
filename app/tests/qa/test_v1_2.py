import copy
import pytest
from dlrag.qa import QAEngine, ScriptedMockLLM, ProjectError
from dlrag.qa.demo import FakeRetriever, demo_chunk, demo_outputs
from dlrag.qa.sentences import sentence_spans, annotated_text
from dlrag.qa.validation import validate_answer
from dlrag.shared.models import AnswerResponse
from dlrag.ui.citations import claim_html, marked_text


def sample():
    chunk = demo_chunk()
    chunk['text'] = 'BM25 uses lexical matching. Vectors support semantic matching.'
    chunk['char_count'] = chunk['page_char_end'] = len(chunk['text'])
    answer = dict(status='answered', limitations=[], claims=[
        dict(text='BM25 使用词法匹配。', evidence_chunk_ids=[chunk['chunk_id']], evidence_sentences={chunk['chunk_id']: ['s1']}),
        dict(text='向量支持语义匹配。', evidence_chunk_ids=[chunk['chunk_id']], evidence_sentences={chunk['chunk_id']: ['s2']})])
    return chunk, answer


def test_same_source_different_claim_links_target_different_exact_sentences():
    chunk, output = sample()
    engine = QAEngine(FakeRetriever([chunk]), ScriptedMockLLM([demo_outputs('BM25', 'answered')[0], output]),
                      {'sentence_citations_required': True})
    answer = engine.ask({'question':'BM25'})
    assert answer['status'] == 'answered'
    AnswerResponse.model_validate(answer)
    spans = [c['citations'][0]['highlights'][0] for c in answer['claims']]
    assert spans[0]['text'] == 'BM25 uses lexical matching.'
    assert spans[1]['text'] == 'Vectors support semantic matching.'
    assert len(answer['evidence']) == 1
    html = [claim_html(c, answer['evidence'], {'ev_1':1}, 'http://127.0.0.1:8000', answer['index_version']) for c in answer['claims']]
    assert 'span=0%3A27' in html[0] and 'span=28%3A62' in html[1]
    assert '<sup><a ' in html[0] and '#source-text' in html[0]


@pytest.mark.parametrize('positions', [{}, {'foreign':['s1']}, {'c_demo_p0001_0001':['s99']}, {'c_demo_p0001_0001':[]}])
def test_invalid_or_incomplete_sentence_selection_rejected(positions):
    chunk, answer = sample()
    answer['claims'][0]['evidence_sentences'] = positions
    with pytest.raises(ProjectError):
        validate_answer(answer, [chunk], require_sentence_refs=True)


def test_missing_selection_repairs_and_obeys_existing_call_limit():
    chunk, good = sample()
    bad = copy.deepcopy(good)
    del bad['claims'][0]['evidence_sentences']
    llm = ScriptedMockLLM([demo_outputs('BM25','answered')[0], bad, good])
    answer = QAEngine(FakeRetriever([chunk]), llm, {'sentence_citations_required':True}).ask({'question':'BM25'})
    assert answer['status'] == 'answered' and len(llm.calls) == 3


def test_xss_is_text_and_fabricated_highlight_is_not_rendered():
    text = '<script>alert(1)</script> 原文。'
    spans = sentence_spans(text)
    html = marked_text(text, spans)
    assert '<script>' not in html and '&lt;script&gt;' in html and '<mark ' in html
    assert '<mark ' not in marked_text(text, [{'start':0,'end':3,'text':'伪造'}])
    claim = {'text':'<img src=x onerror=alert(1)>','evidence_ids':['e']}
    html = claim_html(claim, [{'evidence_id':'e','chunk_id':'c'}], {'e':1}, 'http://127.0.0.1:8000', 'idx')
    assert '<img' not in html and '&lt;img' in html


def test_sentence_offsets_preserve_whitespace_chinese_and_decimal():
    text = '  第一条。\n第二条！  Value is 3.14. Next fact. '
    spans = sentence_spans(text)
    assert [s['text'] for s in spans] == ['第一条。','第二条！','Value is 3.14.','Next fact.']
    assert all(text[s['start']:s['end']] == s['text'] for s in spans)
    assert '[s1] 第一条。' in annotated_text(text)


def test_public_schema_rejects_forged_highlight_text():
    chunk, output = sample()
    answer = QAEngine(FakeRetriever([chunk]), ScriptedMockLLM([demo_outputs('BM25','answered')[0], output]), {}).ask({'question':'BM25'})
    answer['claims'][0]['citations'][0]['highlights'][0]['text'] = '伪造的原文'
    with pytest.raises(ValueError):
        AnswerResponse.model_validate(answer)

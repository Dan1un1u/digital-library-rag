from dlrag.qa.sentences import sentence_spans
from dlrag.api.sources import read_source, pdf_preview


def source(client):
    hit = client.post('/search', json={'query':'BM25','mode':'keyword','top_k':5}).json()['hits'][0]
    span = sentence_spans(hit['chunk']['text'])[-1]
    return hit, span, {'span': f"{span['start']}:{span['end']}", 'index_version':hit['index_version']}


def test_source_view_highlights_exact_sentence_and_pdf_page(client, imported, services):
    import hashlib
    hit, span, params = source(client)
    path = services.file_path(hit['chunk']['doc_id'])
    original_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    response = client.get('/sources/'+hit['chunk']['chunk_id'],params=params)
    assert response.status_code == 200
    assert '<mark ' in response.text and span['text'] in response.text
    assert 'data:image/png;base64,' in response.text and '#page=1' in response.text
    assert 'script-src' not in response.headers['content-security-policy']
    chunk, selected, path = read_source(services,hit['chunk']['chunk_id'],[params['span']],hit['index_version'])
    image, matched = pdf_preview(path,chunk['pdf_page'],selected)
    assert image.startswith(b'\x89PNG') and matched == 1
    assert hashlib.sha256(path.read_bytes()).hexdigest() == original_hash


def test_invalid_spans_stale_version_and_missing_source(client, imported):
    hit, span, params = source(client)
    url = '/sources/'+hit['chunk']['chunk_id']
    assert client.get(url, params={**params,'span':'1:2'}).status_code == 422
    assert client.get(url, params={**params,'span':'bad'}).status_code == 422
    assert client.get(url, params={**params,'index_version':'old-index'}).status_code == 503
    assert client.get('/sources/missing').status_code == 404
    assert client.get(url,params=[('span',params['span'])]*7).status_code == 422


def test_legacy_source_explicitly_reports_missing_sentence_selection(client, imported):
    hit, _, _ = source(client)
    response = client.get('/sources/'+hit['chunk']['chunk_id'])
    assert response.status_code == 200
    assert '未包含句子定位信息' in response.text
    assert '<mark ' not in response.text

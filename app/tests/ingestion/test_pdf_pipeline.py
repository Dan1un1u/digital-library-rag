import json
import os
import subprocess
import sys
import fitz
import pytest
from dlrag.ingestion import LibraryStore, ProjectError
from dlrag.ingestion.chunker import normalize_config, chunk_pages, TokenCounter
from dlrag.ingestion.parser import parse_pdf
from dlrag.ingestion.reports import export_reports, candidate_templates

CONFIG={'count_mode':'character','max_chars':120,'overlap_chars':20}


def make_pdf(path, texts):
    pdf=fitz.open()
    for i,text in enumerate(texts):
        page=pdf.new_page()
        page.insert_text((50,30),'SYNTHETIC HEADER',fontsize=10)
        if text:
            page.insert_textbox(fitz.Rect(50,100,540,730),text,fontsize=10)
        page.insert_text((50,815),f'Page {i+1}',fontsize=10)
    pdf.save(path)
    pdf.close()
    return path


@pytest.fixture
def store(tmp_path):
    return LibraryStore(str(tmp_path/'data/library.sqlite'),str(tmp_path/'data/raw'))


def test_real_pdf_import_and_dedup(store,tmp_path):
    path=make_pdf(tmp_path/'source.pdf',['Alpha evidence. '*80,'Second page evidence.'])
    doc=store.ingest_pdf(str(path),{'title':'Synthetic'},CONFIG)
    assert doc['page_count']==2 and doc['status']=='indexing'
    chunks=store.list_chunks(include_indexing=True)
    assert store.ingest_pdf(str(path),{'title':'Synthetic'},CONFIG)==doc
    assert store.list_chunks(include_indexing=True)==chunks
    assert {c['pdf_page'] for c in chunks}=={1,2}
    for c in chunks:
        p=store.get_page(doc['doc_id'],c['pdf_page'])
        assert p['normalized_text'][c['page_char_start']:c['page_char_end']]==c['text']
        assert len(c['text'])<=120 and c['token_count'] is None
        assert 'SYNTHETIC HEADER' not in c['text']
    assert 'SYNTHETIC HEADER' in store.get_page(doc['doc_id'],1)['raw_text']
    with pytest.raises(ProjectError) as error:
        store.ingest_pdf(str(path),{},dict(CONFIG,max_chars=150))
    assert error.value.code=='CHUNK_CONFIG_MISMATCH'


@pytest.mark.parametrize('kind',['bad','blank','scan'])
def test_failed_pdf_record_and_explicit_retry(store,tmp_path,kind):
    path=tmp_path/'source.pdf'
    if kind=='bad':
        path.write_bytes(b'not a PDF')
    else:
        pdf=fitz.open()
        page=pdf.new_page()
        if kind=='scan':
            pix=fitz.Pixmap(fitz.csRGB,fitz.IRect(0,0,20,20),False)
            pix.clear_with(255)
            page.insert_image(fitz.Rect(50,50,250,250),pixmap=pix)
        pdf.save(path)
        pdf.close()
    with pytest.raises(ProjectError) as error:
        store.ingest_pdf(str(path),{},CONFIG)
    assert error.value.code==('INVALID_PDF' if kind=='bad' else 'NO_EXTRACTABLE_TEXT')
    doc=store.list_documents(include_nonready=True)[0]
    assert doc['status']=='failed' and doc['error_code']==error.value.code
    assert store.list_chunks(include_indexing=True)==[]
    with pytest.raises(ProjectError,match='retry_document'):
        store.ingest_pdf(str(path),{},CONFIG)
    with pytest.raises(ProjectError):
        store.retry_document(doc['doc_id'],CONFIG)


def test_failed_tokenizer_can_retry_character_mode(store,tmp_path):
    path=make_pdf(tmp_path/'source.pdf',['Actual text.'])
    with pytest.raises(ProjectError):
        store.ingest_pdf(str(path),{},dict(count_mode='token',tokenizer_name='tiktoken:no_such_encoding'))
    doc=store.list_documents(include_nonready=True)[0]
    assert store.retry_document(doc['doc_id'],CONFIG)['status']=='indexing'


def test_character_overlap_stable_ids_and_coverage():
    config=normalize_config(dict(count_mode='character',max_chars=20,overlap_chars=5))
    pages=[dict(pdf_page=1,normalized_text='abcdefghij'*10),dict(pdf_page=2,normalized_text='短页')]
    chunks=chunk_pages('d_fixed',pages,config)
    assert chunks==chunk_pages('d_fixed',pages,config)
    first=[c for c in chunks if c['pdf_page']==1]
    assert first[0]['page_char_start']==0 and first[-1]['page_char_end']==100
    for prev,next_ in zip(first,first[1:]):
        assert prev['page_char_end']-next_['page_char_start']==5
    assert chunks[-1]['text']=='短页'


def test_real_token_counts_unicode_and_budget():
    pytest.importorskip('tiktoken')
    config=normalize_config(dict(count_mode='token',tokenizer_name='tiktoken:cl100k_base',max_tokens=12,overlap_tokens=3))
    text='中文检索与证据验证。 English retrieval 🧪! '*20
    chunks=chunk_pages('d_token',[dict(pdf_page=1,normalized_text=text)],config)
    counter=TokenCounter(config['tokenizer_name'])
    assert chunks[0]['page_char_start']==0 and chunks[-1]['page_char_end']==len(text)
    for c in chunks:
        assert c['token_count']==counter.count(c['text'])<=12
        assert c['text']==text[c['page_char_start']:c['page_char_end']]
    for a,b in zip(chunks,chunks[1:]):
        assert b['page_char_start']<=a['page_char_end']


def test_multi_column_and_empty_page_diagnostics(tmp_path):
    path=tmp_path/'columns.pdf'
    pdf=fitz.open()
    page=pdf.new_page()
    page.insert_textbox(fitz.Rect(40,100,250,300),'Left column\nSecond line',fontsize=10)
    page.insert_textbox(fitz.Rect(330,100,550,300),'Right column\nSecond line',fontsize=10)
    pdf.new_page()
    pdf.save(path)
    pdf.close()
    pages=parse_pdf(path)
    assert 'MULTI_COLUMN_REVIEW_REQUIRED' in pages[0]['diagnostics']
    assert 'EMPTY_PAGE' in pages[1]['diagnostics']


def test_reports_and_candidate_templates(store,tmp_path):
    doc=store.ingest_pdf(str(make_pdf(tmp_path/'a.pdf',['Text evidence.'])),{},CONFIG)
    output=tmp_path/'report'
    assert export_reports(store,output)['documents']==1
    assert 'pending_human_review' in (output/'parsing_quality.csv').read_text(encoding='utf-8-sig')
    questions=tmp_path/'questions.jsonl'
    candidate_templates(questions)
    items=[json.loads(line) for line in questions.read_text().splitlines()]
    assert len(items)==15
    assert sum(q['category']=='exact' for q in items)==10
    assert all(not q['relevant_chunk_ids'] and not q['usable_for_evaluation'] for q in items)


def test_cli_batch_errors_and_offline_rebuild(tmp_path):
    source=make_pdf(tmp_path/'source.pdf',['CLI evidence.'])
    options=tmp_path/'options.json'
    options.write_text(json.dumps(CONFIG))
    manifest=tmp_path/'manifest.json'
    manifest.write_text(json.dumps([{'file':'source.pdf','metadata':{}},{'file':'missing.pdf','metadata':{}}]))
    base=[sys.executable,'-m','dlrag.ingestion.cli']
    common=['--db',str(tmp_path/'library.sqlite'),'--files',str(tmp_path/'raw'),'--manifest',str(manifest),'--options',str(options)]
    result=subprocess.run(base+['batch']+common,capture_output=True,text=True)
    assert result.returncode==1
    items=json.loads(result.stdout)
    assert items[0]['document']['status']=='indexing' and items[1]['error']['code']=='FILE_NOT_FOUND'
    result=subprocess.run(base+['rebuild']+common,capture_output=True,text=True)
    assert result.returncode==1 and 'new database' in result.stderr
    manifest.write_text(json.dumps([{'file':'source.pdf','metadata':{}}]))
    common[1]=str(tmp_path/'new.sqlite')
    result=subprocess.run(base+['rebuild']+common,capture_output=True,text=True)
    assert result.returncode==0, result.stderr


def test_configuration_and_missing_source_errors(store,tmp_path):
    for options in ({},{'count_mode':'invalid'},dict(CONFIG,max_chars=20,overlap_chars=20)):
        with pytest.raises(ProjectError):
            normalize_config(options)
    with pytest.raises(ProjectError) as error:
        store.ingest_pdf(str(tmp_path/'missing.pdf'),{},CONFIG)
    assert error.value.code=='FILE_NOT_FOUND'


def test_config_consistency_across_documents(store,tmp_path):
    store.ingest_pdf(str(make_pdf(tmp_path/'first.pdf',['First source.'])),{},CONFIG)
    with pytest.raises(ProjectError) as error:
        store.ingest_pdf(str(make_pdf(tmp_path/'second.pdf',['Second source.'])),{},dict(CONFIG,max_chars=200))
    assert error.value.code=='CHUNK_CONFIG_MISMATCH'
    failed=[d for d in store.list_documents(include_nonready=True) if d['status']=='failed'][0]
    assert store.get_page(failed['doc_id'],1) is None
    assert store.retry_document(failed['doc_id'],CONFIG)['status']=='indexing'


def test_partial_write_rollback_keeps_existing_library(store,tmp_path,monkeypatch):
    from dlrag.ingestion import library
    first=store.ingest_pdf(str(make_pdf(tmp_path/'first.pdf',['Preserved evidence.'])),{},CONFIG)
    old_chunks=store.list_chunks(include_indexing=True)
    real=store.save_parsed_content
    def broken(*args,**kwargs):
        raise RuntimeError('simulated storage failure')
    monkeypatch.setattr(store,'save_parsed_content',broken)
    with pytest.raises(ProjectError) as error:
        store.ingest_pdf(str(make_pdf(tmp_path/'second.pdf',['New evidence.'])),{},CONFIG)
    assert error.value.code=='INGESTION_FAILED'
    assert store.get_document(first['doc_id'])['status']=='indexing'
    assert store.list_chunks(include_indexing=True)==old_chunks


def test_controlled_filename_and_external_path_rejection(store,tmp_path):
    path=make_pdf(tmp_path/'strange name.pdf',['Controlled file.'])
    doc=store.ingest_pdf(str(path),{},CONFIG)
    assert store.get_file_path(doc['doc_id']).endswith(doc['doc_id']+'.pdf')
    with store._connect() as db:
        db.execute('UPDATE documents SET file_relpath=? WHERE doc_id=?',('../outside.pdf',doc['doc_id']))
    with pytest.raises(ProjectError):
        store.get_file_path(doc['doc_id'])


def test_metadata_unknown_fields_and_encrypted_pdf(store,tmp_path):
    path=make_pdf(tmp_path/'source.pdf',['Content.'])
    with pytest.raises(ProjectError):
        store.ingest_pdf(str(path),{'doc_id':'injected'},CONFIG)
    pdf=fitz.open(path)
    encrypted=tmp_path/'encrypted.pdf'
    pdf.save(encrypted,encryption=fitz.PDF_ENCRYPT_AES_256,user_pw='secret',owner_pw='owner')
    pdf.close()
    with pytest.raises(ProjectError) as error:
        store.ingest_pdf(str(encrypted),{},CONFIG)
    assert error.value.code=='INVALID_PDF'


def test_paragraph_boundaries_and_cross_page_sentence():
    config=normalize_config(dict(count_mode='character',max_chars=20,overlap_chars=5))
    pages=[{'pdf_page':1,'normalized_text':'Short paragraph.\n\nThis sentence continues'},
           {'pdf_page':2,'normalized_text':'on the next page.'}]
    chunks=chunk_pages('d_page',pages,config)
    assert chunks[0]['text']=='Short paragraph.\n\n'
    assert chunks[-1]['pdf_page']==2 and chunks[-1]['page_char_start']==0
    assert not any('continueson' in c['text'] for c in chunks)


def test_pdf_null_characters_cleaned_before_sqlite_storage(store,tmp_path,monkeypatch):
    from dlrag.ingestion import parser
    assert parser.normalize('A\x00 term.\nSecond line.')=='A term. Second line.'
    source=make_pdf(tmp_path/'null.pdf',['Valid PDF.'])
    monkeypatch.setattr(parser,'parse_pdf',lambda _: [{'pdf_page':1,'raw_text':'A\x00 term.',
        'normalized_text':parser.normalize('A\x00 term.'),'diagnostics':['NULL_CHARACTERS_REMOVED']}])
    doc=store.ingest_pdf(str(source),{},CONFIG)
    chunk=store.list_chunks(include_indexing=True)[0]
    assert doc['status']=='indexing'
    assert chunk['text']=='A term.' and chunk['char_count']==7

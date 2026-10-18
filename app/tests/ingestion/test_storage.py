import shutil
import sqlite3
import pytest
from dlrag.ingestion import LibraryStore, ProjectError


@pytest.fixture
def store(tmp_path):
    return LibraryStore(str(tmp_path/'data/library.sqlite'), str(tmp_path/'data/raw'))


def register(store, tmp_path, payload=b'parser-input', year=2024):
    source = tmp_path/'input.pdf'
    source.write_bytes(payload)
    return store.register_document(str(source), {'title':'Example','year':year,'topics':['IR'],'authors':['A']})


def parsed(store, doc, broken=False):
    text = 'Evidence on page one.'
    pages = [{'pdf_page':1,'raw_text':text,'normalized_text':text}]
    chunks = [{'chunk_id':'c_'+doc['doc_id'][2:]+'_p0001_0001','pdf_page':1,'chunk_order':1,
               'text':'wrong' if broken else text,'page_char_start':0,'page_char_end':len(text),'token_count':None}]
    store.save_parsed_content(doc['doc_id'],pages,chunks,{'count_mode':'character','max_chars':1200},'test-parser')
    return chunks[0]['chunk_id']


def test_roundtrip_states_and_offsets(store,tmp_path):
    doc = register(store,tmp_path)
    assert doc['status']=='uploaded'
    cid = parsed(store,doc)
    assert store.get_document(doc['doc_id'])['status']=='indexing'
    assert store.list_documents()==[]
    assert store.list_chunks()==[]
    chunk = store.list_chunks(include_indexing=True)[0]
    page = store.get_page(doc['doc_id'],1)
    assert page['normalized_text'][chunk['page_char_start']:chunk['page_char_end']]==chunk['text']
    assert chunk['document']['topics']==['IR']
    assert store.get_chunk(cid)==chunk
    store.set_document_status(doc['doc_id'],'ready')
    assert len(store.list_documents())==1
    assert len(store.list_chunks())==1
    reopened = LibraryStore(str(store.db_path),str(store.files_dir))
    assert reopened.get_chunk(cid)==chunk


def test_dedup_preserves_metadata(store,tmp_path):
    doc=register(store,tmp_path)
    parsed(store,doc)
    source=tmp_path/'input.pdf'
    with pytest.warns(UserWarning):
        same=store.register_document(str(source),{'title':'changed'})
    assert same['doc_id']==doc['doc_id']
    assert same['title']=='Example'
    assert len(store.list_chunks(include_indexing=True))==1
    assert len(list(store.files_dir.iterdir()))==1


def test_validation_and_transaction_rollback(store,tmp_path):
    doc=register(store,tmp_path)
    with pytest.raises(ProjectError):
        parsed(store,doc,broken=True)
    assert store.get_page(doc['doc_id'],1) is None
    text='abc'
    chunks=[{'chunk_id':'duplicate','pdf_page':1,'chunk_order':i,'text':text,
             'page_char_start':0,'page_char_end':3} for i in (1,2)]
    with pytest.raises(sqlite3.IntegrityError):
        store.save_parsed_content(doc['doc_id'],[{'pdf_page':1,'raw_text':text,'normalized_text':text}],
                                  chunks,{'count_mode':'character'},'test')
    assert store.get_page(doc['doc_id'],1) is None
    assert store.get_document(doc['doc_id'])['status']=='uploaded'
    store.set_document_status(doc['doc_id'],'failed',{'code':'INVALID_PDF','message':'Test failure'})
    assert store.list_documents(include_nonready=True)[0]['error_code']=='INVALID_PDF'
    with pytest.raises(ProjectError):
        store.set_document_status(doc['doc_id'],'ready')


def test_filters(store,tmp_path):
    for payload,year in [(b'one',2024),(b'two',None)]:
        doc=register(store,tmp_path,payload,year)
        parsed(store,doc)
        store.set_document_status(doc['doc_id'],'ready')
    assert len(store.list_documents({'year_from':2024,'year_to':2024,'topics':['IR']}))==1
    assert store.list_chunks({'topics':['other']})==[]
    with pytest.raises(ProjectError):
        store.list_documents({'year_from':2025,'year_to':2024})


def test_moved_library_and_foreign_keys(store,tmp_path):
    doc=register(store,tmp_path)
    parsed(store,doc)
    moved=tmp_path/'moved'
    shutil.copytree(store.db_path.parent,moved)
    reopened=LibraryStore(str(moved/'library.sqlite'),str(moved/'raw'))
    assert reopened.get_file_path(doc['doc_id']).startswith(str(moved))
    with reopened._connect() as db:
        assert db.execute('PRAGMA foreign_key_check').fetchall()==[]
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO document_topics VALUES ('absent','IR')")


def test_missing_and_config_change(store,tmp_path):
    assert store.get_document('missing') is None
    assert store.get_chunk('missing') is None
    assert store.get_file_path('missing') is None
    doc=register(store,tmp_path)
    parsed(store,doc)
    with pytest.raises(ProjectError) as error:
        store.save_parsed_content(doc['doc_id'],[{'pdf_page':1,'raw_text':'a','normalized_text':'a'}],
            [{'chunk_id':'new','pdf_page':1,'chunk_order':1,'text':'a','page_char_start':0,'page_char_end':1}],
            {'count_mode':'character','max_chars':99},'test')
    assert error.value.code=='CHUNK_CONFIG_MISMATCH'

"""Run and record a ten-paper local import trial; never mark indexed/ready."""
import json
import hashlib
from pathlib import Path
from collections import Counter
from dlrag.ingestion import LibraryStore, ProjectError
from dlrag.ingestion.reports import export_reports

root=Path(__file__).resolve().parents[3]
source=root/'data/arxiv_trial/source'
output=root/'evaluation/ingestion/arxiv_trial'
store=LibraryStore(str(root/'data/arxiv_trial/library.sqlite'),str(root/'data/arxiv_trial/raw'))
config=json.loads((root/'handoff/A/chunking_character.json').read_text())
records=json.loads((source/'manifest.json').read_text())
results=[]
for item in records:
    try:
        digest=hashlib.sha256((source/item['file']).read_bytes()).hexdigest()
        existing=store.get_document('d_'+digest)
        if existing and existing['status']=='failed':
            doc=store.retry_document(existing['doc_id'],config)
        else:
            doc=store.ingest_pdf(str(source/item['file']),item['metadata'],config)
        chunks=[c for c in store.list_chunks(include_indexing=True) if c['doc_id']==doc['doc_id']]
        diagnostics=Counter()
        for number in range(1,doc['page_count']+1):
            page=store.get_page(doc['doc_id'],number)
            diagnostics.update(json.loads(page['diagnostics_json']))
            for c in [c for c in chunks if c['pdf_page']==number]:
                assert page['normalized_text'][c['page_char_start']:c['page_char_end']]==c['text']
                assert c['char_count']<=config['max_chars'] and c['token_count'] is None
        before=len(store.list_chunks(include_indexing=True))
        repeated=store.ingest_pdf(str(source/item['file']),item['metadata'],config)
        assert repeated['doc_id']==doc['doc_id'] and len(store.list_chunks(include_indexing=True))==before
        result={'file':item['file'],'doc_id':doc['doc_id'],'title':doc['title'],'source_url':doc['source_url'],
                'status':doc['status'],'pages':doc['page_count'],'chunks':len(chunks),'diagnostics':dict(diagnostics),
                'offset_check':'pass','duplicate_check':'pass','max_chunk_chars':max(c['char_count'] for c in chunks)}
    except Exception as exc:
        result={'file':item['file'],'error':{'code':getattr(exc,'code','TRIAL_FAILED'),'message':str(exc)}}
    results.append(result)
    print(json.dumps(result,ensure_ascii=False),flush=True)
(output/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
export_reports(store,output)
summary={'requested':10,'downloaded':len(records),'imported':sum('error' not in r for r in results),
         'pages':sum(r.get('pages',0) for r in results),'chunks':sum(r.get('chunks',0) for r in results),
         'count_mode':'character','max_chars':1200,'overlap_chars':150,'human_reading_order_review':'not_executed'}
(output/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
print('SUMMARY',summary)

"""Read-only real SiliconFlow/Crossref validation of HU25's journal issue year."""
import argparse, copy, hashlib, json, sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from dlrag.ingestion import metadata_api
from dlrag.shared.config import Settings
from tools.catalog_batch import code_identity, LocalAPI, digest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pdf',type=Path,required=True)
    parser.add_argument('--env-file',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    import dlrag
    assert Path(next(iter(dlrag.__path__))).resolve()==ROOT/'app/src/dlrag'
    identity=code_identity();assert not identity['dirty']
    ref=next(r for r in json.loads((ROOT/'docs/validation/COL-002/catalog.json').read_text())['items'] if r['item_id']=='HU25')
    assert hashlib.sha256(args.pdf.read_bytes()).hexdigest()==ref['source_sha256']
    args.output.mkdir(parents=True,exist_ok=False)
    settings=Settings(_env_file=args.env_file);settings.metadata_lookup_timeout_seconds=20
    assert settings.app_mode=='real' and settings.metadata_api_enabled and settings.metadata_lookup_enabled
    protected={p:LocalAPI('http://127.0.0.1:'+str(p)) for p in [18000,19000,19010]}
    before={p:api.snapshot() for p,api in protected.items()}
    original=metadata_api.request_candidates;captured=[]
    def traced(*a):
        value=original(*a);captured.append(copy.deepcopy(value));return value
    report={'code':identity,'scope':'actual HU25 PDF; live SiliconFlow + Crossref; shadow preview only, no import',
            'sha256':ref['source_sha256'],'provider':settings.metadata_api_provider,'model':settings.metadata_api_model,'passed':False}
    try:
        metadata_api.request_candidates=traced
        result=metadata_api.recognize_metadata(args.pdf,settings,assist=True,lookup=True)
        report.update(result=result,raw_model_year=captured[0].get('year') if captured else None)
        assert result['api_assistance']['status']=='completed' and result['metadata']['year']==2009
        assert result['field_sources']['year']['date_type']=='issue'
        audit=result['bibliographic_enrichment']
        assert audit['status']=='completed' and 'year' not in audit['filled_fields']
        assert audit['candidates'][0]['doi']=='10.63744/au56n57rd75j'
        assert any(d['year']==2010 for d in audit['candidates'][0]['dates'])
        report['passed']=True
    finally:
        metadata_api.request_candidates=original
        report['protected_libraries_unchanged']=before=={p:api.snapshot() for p,api in protected.items()}
        report['protected_snapshot_sha256']={str(p):digest(s) for p,s in before.items()}
        report['worktree_dirty_after']=code_identity()['dirty']
        report['passed']=report['passed'] and report['protected_libraries_unchanged'] and not report['worktree_dirty_after']
        (args.output/'result.json').write_bytes((json.dumps(report,ensure_ascii=False,indent=2)+'\n').encode())
    print(json.dumps({'passed':report['passed'],'year':report.get('result',{}).get('metadata',{}).get('year')}))
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())

"""Same-corpus real BGE comparison: original 50 title queries, three modes, top5.

The historical index is read only (including its documented bad-text negative).
Only the candidate's independent index is built; this is not a corpus re-import.
"""
import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from dlrag.retrieval.embeddings import LocalBGEEmbedding
from dlrag.retrieval.retriever import Retriever, VECTOR_TEXT_POLICY
from tools.catalog_batch import code_identity, LocalAPI, digest


class MemoEncoder:
    """Reuse exactly the same real query vectors across both representations."""
    def __init__(self, backend):
        self.backend=backend;self.cache={};self.encoded=0
    def get_config(self):return self.backend.get_config()
    def encode(self,texts):
        pending=list(dict.fromkeys(t for t in texts if t not in self.cache))
        for start in range(0,len(pending),16):
            batch=pending[start:start+16];vectors=self.backend.encode(batch)
            self.cache.update(zip(batch,vectors));self.encoded+=len(batch)
            if start==0 or start%256==0:
                print('real BGE inputs encoded: '+str(self.encoded),flush=True)
        return np.asarray([self.cache[t] for t in texts],dtype=np.float32)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--historical-index',type=Path,required=True)
    parser.add_argument('--plan',type=Path,required=True)
    parser.add_argument('--baseline-ref',required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    import dlrag
    assert Path(next(iter(dlrag.__path__))).resolve()==ROOT/'app/src/dlrag'
    identity=code_identity();assert not identity['dirty']
    assert not args.output.resolve().is_relative_to(args.historical_index.resolve())
    args.output.mkdir(parents=True,exist_ok=False)
    pointer=json.loads((args.historical_index/'current.json').read_text())
    source_dir=args.historical_index/pointer['index_version']
    manifest=json.loads((source_dir/'manifest.json').read_text())
    assert manifest['document_count']==50 and manifest['chunk_count']==3262
    archived=json.loads((ROOT/'docs/validation/COL-002/verification.json').read_text())['before_manifest']
    assert manifest==archived, 'Historical input changed; do not change the benchmark corpus'
    protected={p:LocalAPI('http://127.0.0.1:'+str(p)) for p in [18000,19000,19010]}
    before={p:api.snapshot() for p,api in protected.items()}
    source_hashes={n:hashlib.sha256((source_dir/n).read_bytes()).hexdigest()
                   for n in ['manifest.json','chunks.json','vectors.npy','lexical.json']}
    backend=LocalBGEEmbedding(base_url=manifest['embedding_backend']['base_url'],
        model=manifest['embedding_model'],revision=manifest['embedding_revision'],dimension=manifest['dimension'],
        batch_size=16,timeout=60,max_retries=0)
    memo=MemoEncoder(backend);assert memo.get_config()==manifest['embedding_backend']
    source=subprocess.check_output(['git','show',args.baseline_ref+':app/src/dlrag/retrieval/retriever.py'],cwd=ROOT)
    baseline_file=args.output/'baseline_retriever.py';baseline_file.write_bytes(source)
    spec=importlib.util.spec_from_file_location('dlrag.retrieval._ret001_baseline',baseline_file)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    settings={**manifest['retrieval_config'],'chunking_config':manifest['chunking_config']}
    old=module.Retriever(str(args.historical_index),memo,settings);assert old.load()==manifest
    chunks=json.loads((source_dir/'chunks.json').read_text())
    plan=json.loads(args.plan.read_text())['items'];assert len(plan)==50
    assert {r['expected_doc_id'] for r in plan}=={c['doc_id'] for c in chunks}
    report={'code':identity,'baseline_ref':args.baseline_ref,'baseline_source_sha256':hashlib.sha256(source).hexdigest(),
       'scope':'same historical 50 documents/3262 chunks; actual local BGE FP16; no import, OCR, LLM or existing-index write',
       'metric':'50 original title queries x keyword/vector/hybrid; fixed top5, not general QA accuracy',
       'historical_bad_text_negative_retained':'HU08; a title hit cannot certify its body; ING-002 handles new ingestion',
       'historical_manifest':manifest,'historical_artifact_sha256':source_hashes,'candidate_policy':VECTOR_TEXT_POLICY,
       'results':{},'body_controls':{},'passed':False}
    def save():
        (args.output/'result.json').write_bytes((json.dumps(report,ensure_ascii=False,indent=2)+'\n').encode())
    def evaluate(engine):
        rows=[]
        for item in plan:
            query=item['metadata']['title'];target=item['expected_doc_id']
            assert query==next(c['document']['title'] for c in chunks if c['doc_id']==target)
            for mode in ['keyword','vector','hybrid']:
                hits=engine.search(query,mode=mode,top_k=5)
                rows.append({'item_id':item['item_id'],'query':query,'mode':mode,'expected_doc_id':target,
                    'found_in_top_5':any(h['chunk']['doc_id']==target for h in hits),
                    'hits':[{'rank':h['rank'],'doc_id':h['chunk']['doc_id'],'chunk_id':h['chunk']['chunk_id'],
                             'scores':h['scores']} for h in hits]})
        return {'counts':{m:sum(r['found_in_top_5'] for r in rows if r['mode']==m) for m in ['keyword','vector','hybrid']},'rows':rows}
    def body_controls(engine):
        rows=[]
        for ident in ['SS01','SS03','SS20','HU01','HU11']:
            target=next(r['expected_doc_id'] for r in plan if r['item_id']==ident)
            own=[c for c in chunks if c['doc_id']==target and len(c['text'])>=300]
            selected=own[len(own)//2];query=selected['text'][:120]
            hits=engine.search(query,mode='vector',top_k=5)
            rows.append({'item_id':ident,'query_sha256':hashlib.sha256(query.encode()).hexdigest(),
                         'source_chunk_id':selected['chunk_id'],'found_in_top_5':any(h['chunk']['doc_id']==target for h in hits)})
        return rows
    try:
        print('baseline: fixed 50-title top5 check',flush=True)
        report['results']['baseline']=evaluate(old)
        report['body_controls']['baseline']=body_controls(old);save()
        assert report['results']['baseline']['counts']=={'keyword':50,'vector':48,'hybrid':50}
        print('candidate: building a separate title-context index',flush=True)
        candidate=Retriever(str(args.output/'candidate-index'),memo,settings)
        report['candidate_manifest']=candidate.build(copy.deepcopy(chunks));save()
        assert report['candidate_manifest']['corpus_hash']==manifest['corpus_hash']
        assert report['candidate_manifest']['chunk_count']==manifest['chunk_count']
        report['results']['candidate']=evaluate(candidate)
        report['body_controls']['candidate']=body_controls(candidate);save()
        assert report['results']['candidate']['counts']=={'keyword':50,'vector':50,'hybrid':50}
        assert all(not old_row['found_in_top_5'] or new_row['found_in_top_5'] for old_row,new_row in zip(
            report['body_controls']['baseline'],report['body_controls']['candidate']))
        reload=Retriever(str(args.output/'candidate-index'),memo,settings)
        assert reload.load()==report['candidate_manifest']
        report['candidate_reload_verified']=True;report['passed']=True
    finally:
        report['protected_libraries_unchanged']=before=={p:api.snapshot() for p,api in protected.items()}
        report['protected_snapshot_sha256']={str(p):digest(s) for p,s in before.items()}
        report['historical_files_unchanged']=source_hashes=={n:hashlib.sha256((source_dir/n).read_bytes()).hexdigest() for n in source_hashes}
        report['worktree_dirty_after']=code_identity()['dirty'];report['real_encoded_inputs']=memo.encoded
        report['passed']=report['passed'] and report['protected_libraries_unchanged'] and report['historical_files_unchanged'] and not report['worktree_dirty_after']
        save()
    print(json.dumps({'passed':report['passed'],'counts':{k:r['counts'] for k,r in report['results'].items()}}))
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())

"""Standalone PDF ingestion, inspection and reports."""
import argparse
import json
import sys
from pathlib import Path
from .library import LibraryStore, ProjectError


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['init','documents','chunks','ingest','batch','retry','report','questions','rebuild'])
    parser.add_argument('--db',required=True)
    parser.add_argument('--files',required=True)
    for field in ('pdf','metadata','options','manifest','doc-id','output'):
        parser.add_argument('--'+field)
    args = parser.parse_args()
    try:
        if args.command in ('ingest','retry','batch','rebuild') and not args.options:
            parser.error('--options required: counting units must be explicit')
        required = {'ingest':['pdf','metadata'],'batch':['manifest'],'retry':['doc_id'],
                    'report':['output'],'questions':['output'],'rebuild':['manifest']}
        for name in required.get(args.command,[]):
            if not getattr(args,name):
                parser.error('--'+name.replace('_','-')+' is required')
        if args.command == 'rebuild' and Path(args.db).exists():
            raise ProjectError('INVALID_REQUEST','Offline rebuild requires a new database path')
        store = LibraryStore(args.db,args.files)
        if args.command == 'init':
            result = {'schema_version':1,'initialized':True}
        elif args.command == 'documents':
            result = store.list_documents(include_nonready=True)
        elif args.command == 'chunks':
            result = store.list_chunks(include_indexing=True)
        elif args.command == 'ingest':
            result = store.ingest_pdf(args.pdf,read_json(args.metadata),read_json(args.options))
        elif args.command == 'retry':
            result = store.retry_document(args.doc_id,read_json(args.options))
        elif args.command in ('batch','rebuild'):
            manifest = Path(args.manifest).resolve()
            records = read_json(manifest)
            if not isinstance(records,list):
                raise ProjectError('INVALID_REQUEST','Manifest must be an array')
            options = read_json(args.options)
            result, failed = [], False
            for record in records:
                try:
                    source = manifest.parent / record['file']
                    result.append({'file':record['file'],'document':store.ingest_pdf(str(source),record['metadata'],options)})
                except (ProjectError,KeyError,TypeError) as exc:
                    failed = True
                    result.append({'file':record.get('file') if isinstance(record,dict) else None,
                                   'error':{'code':getattr(exc,'code','INVALID_REQUEST'),'message':str(exc)}})
            print(json.dumps(result,ensure_ascii=False,indent=2))
            return 1 if failed else 0
        elif args.command == 'report':
            from .reports import export_reports
            result = export_reports(store,args.output)
        else:
            from .reports import candidate_templates
            result = candidate_templates(args.output)
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 0
    except (ProjectError,OSError,ValueError) as exc:
        print(json.dumps({'error':{'code':getattr(exc,'code','INVALID_REQUEST'),'message':str(exc)}},ensure_ascii=False),file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

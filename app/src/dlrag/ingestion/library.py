"""PDF ingestion and SQLite persistence with exact page provenance."""
import hashlib
import json
import sqlite3
import warnings
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from .errors import ProjectError


class LibraryStore:
    def __init__(self, db_path: str, files_dir: str):
        self.db_path = Path(db_path).resolve()
        self.files_dir = Path(files_dir).resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.files_dir.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            version = db.execute('PRAGMA user_version').fetchone()[0]
            if version not in (0, 1):
                raise ProjectError('SCHEMA_VERSION_UNSUPPORTED', str(version))
            if version == 0:
                db.executescript(Path(__file__).with_name('schema.sql').read_text())
                db.execute('PRAGMA user_version = 1')

    def ingest_pdf(self, file_path: str, metadata: dict, options: dict) -> dict:
        from .chunker import normalize_config
        config = normalize_config(options)
        document = self.register_document(file_path, metadata)
        doc_id = document['doc_id']
        if document['chunking_config'] is not None:
            if document['chunking_config'] != config:
                raise ProjectError('CHUNK_CONFIG_MISMATCH', 'Duplicate import cannot change chunking; rebuild into a new database')
            return document
        if document['status'] == 'failed':
            raise ProjectError(document['error_code'] or 'INVALID_PDF',
                               (document['error_message'] or 'Previous import failed') + '; use retry_document(doc_id, options)')
        return self._parse_document(doc_id, config)

    def retry_document(self, doc_id: str, options: dict) -> dict:
        from .chunker import normalize_config
        document = self.get_document(doc_id)
        if document is None:
            raise ProjectError('NOT_FOUND', doc_id)
        if document['status'] != 'failed' or document['chunking_config'] is not None:
            raise ProjectError('INVALID_REQUEST', 'Retry is only for failed parsing without saved content')
        return self._parse_document(doc_id, normalize_config(options))

    def _parse_document(self, doc_id, config):
        from .parser import parse_pdf, PARSER_VERSION
        from .chunker import chunk_pages
        from .fulltext import require_complete_text
        self.set_document_status(doc_id, 'parsing')
        try:
            file_path = self.get_file_path(doc_id)
            if file_path is None:
                raise ProjectError('FILE_NOT_FOUND', 'Stored source PDF is missing')
            pages = parse_pdf(file_path)
            require_complete_text(pages)
            chunks = chunk_pages(doc_id, pages, config)
            self.save_parsed_content(doc_id, pages, chunks, config, PARSER_VERSION)
        except Exception as exc:
            error = exc if isinstance(exc, ProjectError) else ProjectError('INGESTION_FAILED', str(exc))
            self.set_document_status(doc_id, 'failed', {'code':error.code, 'message':error.message})
            if error is exc:
                raise
            raise error from exc
        return self.get_document(doc_id)

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.db_path)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys = ON')
        try:
            with db:
                yield db
        finally:
            db.close()

    def _document(self, db, row):
        if row is None:
            return None
        result = dict(row)
        result['authors'] = json.loads(result.pop('authors_json'))
        result['topics'] = [r[0] for r in db.execute(
            'SELECT topic FROM document_topics WHERE doc_id=? ORDER BY topic',
            (result['doc_id'],))]
        result['chunking_config'] = json.loads(result.pop('chunking_config_json') or 'null')
        result.pop('file_relpath')
        return result

    def register_document(self, file_path: str, metadata: dict) -> dict:
        """Register/copy a source file; parsing subsequently fills pages/chunks."""
        allowed = {'title', 'authors', 'year', 'topics', 'language', 'source_url', 'rights_note'}
        if not isinstance(metadata, dict) or set(metadata) - allowed:
            raise ProjectError('INVALID_REQUEST', 'Unsupported metadata fields')
        path = Path(file_path)
        if not path.is_file():
            raise ProjectError('FILE_NOT_FOUND', str(path))
        for key in ('authors', 'topics'):
            value = metadata.get(key, [])
            if not isinstance(value, list) or any(not isinstance(x, str) or not x.strip() for x in value):
                raise ProjectError('INVALID_REQUEST', f'{key} must be a list of nonempty strings')
        year = metadata.get('year')
        if year is not None and (not isinstance(year, int) or isinstance(year, bool)):
            raise ProjectError('INVALID_REQUEST', 'year must be an integer or null')
        for key in ('title', 'source_url', 'rights_note'):
            if key in metadata and metadata[key] is not None and not isinstance(metadata[key], str):
                raise ProjectError('INVALID_REQUEST', f'{key} must be a string')
        title = metadata.get('title') or path.stem + '（待核验）'
        if not title.strip():
            raise ProjectError('INVALID_REQUEST', 'title must be nonempty')
        language = metadata.get('language', 'unknown')
        if language not in ('zh', 'en', 'mixed', 'unknown'):
            raise ProjectError('INVALID_REQUEST', 'Invalid language')
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        # Full hashes avoid truncated-ID collisions.
        doc_id = 'd_' + digest
        relative = doc_id + '.pdf'
        target = self.files_dir / relative
        copied = False
        try:
            with self._connect() as db:
                db.execute('BEGIN IMMEDIATE')
                existing = db.execute('SELECT * FROM documents WHERE file_sha256=?', (digest,)).fetchone()
                if existing:
                    result = self._document(db, existing)
                    if any(result.get(k) != v for k, v in metadata.items()):
                        warnings.warn('Duplicate PDF: existing metadata retained', stacklevel=2)
                    return result
                if target.exists():
                    if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                        raise ProjectError('FILE_CONFLICT', 'Stored file hash differs')
                else:
                    with target.open('xb') as output:
                        copied = True
                        output.write(data)
                now = datetime.now(timezone.utc).isoformat()
                db.execute('''INSERT INTO documents
                    (doc_id,file_sha256,file_relpath,title,authors_json,year,language,
                     source_url,rights_note,created_at,updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
                    (doc_id,digest,relative,title,json.dumps(metadata.get('authors', [])),year,
                     language,metadata.get('source_url'),metadata.get('rights_note') or '待人工确认',now,now))
                db.executemany('INSERT INTO document_topics VALUES (?,?)',
                               [(doc_id, t) for t in sorted(set(metadata.get('topics', [])))])
                return self._document(db, db.execute('SELECT * FROM documents WHERE doc_id=?', (doc_id,)).fetchone())
        except Exception:
            if copied:
                target.unlink(missing_ok=True)
            raise

    def save_parsed_content(self, doc_id, pages, chunks, chunking_config, parser_version):
        """Atomically store parser output; failed validation leaves old data intact."""
        from .fulltext import require_complete_text
        require_complete_text(pages)
        if chunking_config.get('count_mode') not in ('token', 'character'):
            raise ProjectError('INVALID_REQUEST', 'Explicit count_mode required')
        page_map = {p['pdf_page']: p for p in pages}
        if not pages or len(page_map) != len(pages) or sorted(page_map) != list(range(1, len(pages)+1)):
            raise ProjectError('INVALID_REQUEST', 'Pages must be consecutive starting at 1')
        if not chunks:
            raise ProjectError('NO_EXTRACTABLE_TEXT', 'No chunks supplied')
        for chunk in chunks:
            page = page_map.get(chunk['pdf_page'])
            start, end = chunk['page_char_start'], chunk['page_char_end']
            if (page is None or not isinstance(start, int) or not isinstance(end, int)
                    or not 0 <= start < end <= len(page['normalized_text'])
                    or page['normalized_text'][start:end] != chunk['text']):
                raise ProjectError('INVALID_REQUEST', 'Chunk text does not match page offsets')
            count = chunk.get('token_count')
            if chunking_config['count_mode'] == 'character' and count is not None:
                raise ProjectError('INVALID_REQUEST', 'Character mode requires null token_count')
            if chunking_config['count_mode'] == 'token' and (not isinstance(count, int) or count < 0):
                raise ProjectError('INVALID_REQUEST', 'Token mode requires actual token_count')
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM documents WHERE doc_id=?', (doc_id,)).fetchone()
            if row is None:
                raise ProjectError('NOT_FOUND', doc_id)
            if row['chunking_config_json'] is not None:
                if json.loads(row['chunking_config_json']) != chunking_config:
                    raise ProjectError('CHUNK_CONFIG_MISMATCH', 'Use a separate database for offline rebuild')
                raise ProjectError('CONTENT_ALREADY_STORED', 'Do not overwrite stored pages')
            for other in db.execute('SELECT chunking_config_json FROM documents WHERE chunking_config_json IS NOT NULL'):
                if json.loads(other[0]) != chunking_config:
                    raise ProjectError('CHUNK_CONFIG_MISMATCH', 'One library must use a single chunking configuration')
            db.executemany('''INSERT INTO pages VALUES (?,?,?,?,?,?)''',
                [(doc_id,p['pdf_page'],p.get('printed_page'),p['raw_text'],p['normalized_text'],
                  json.dumps(p.get('diagnostics', []))) for p in pages])
            db.executemany('''INSERT INTO chunks VALUES (?,?,?,?,?,?,?,?,?,?)''',
                [(c['chunk_id'],doc_id,c['pdf_page'],c['chunk_order'],c.get('section'),c['text'],
                  c['page_char_start'],c['page_char_end'],c.get('token_count'),len(c['text'])) for c in chunks])
            db.execute('''UPDATE documents SET page_count=?,parser_version=?,chunking_config_json=?,
                status='indexing',error_code=NULL,error_message=NULL,updated_at=? WHERE doc_id=?''',
                (len(pages),parser_version,json.dumps(chunking_config,sort_keys=True),
                 datetime.now(timezone.utc).isoformat(),doc_id))

    def get_document(self, doc_id):
        with self._connect() as db:
            return self._document(db, db.execute('SELECT * FROM documents WHERE doc_id=?', (doc_id,)).fetchone())

    def list_documents(self, filters=None, include_nonready=False):
        filters = filters or {}
        lo, hi = filters.get('year_from'), filters.get('year_to')
        for value in (lo, hi):
            if value is not None and (not isinstance(value, int) or isinstance(value, bool)):
                raise ProjectError('INVALID_REQUEST', 'Year bounds must be integers')
        topics = filters.get('topics', [])
        if not isinstance(topics, list) or any(not isinstance(t, str) for t in topics):
            raise ProjectError('INVALID_REQUEST', 'topics must be a string list')
        if lo is not None and hi is not None and lo > hi:
            raise ProjectError('INVALID_REQUEST', 'Invalid year range')
        clauses, params = [], []
        if not include_nonready:
            clauses.append("status='ready'")
        for value, operator in ((lo, '>='), (hi, '<=')):
            if value is not None:
                clauses.append('year ' + operator + ' ?')
                params.append(value)
        if topics:
            clauses.append('EXISTS (SELECT 1 FROM document_topics t WHERE t.doc_id=documents.doc_id AND t.topic IN (' + ','.join('?' for _ in topics) + '))')
            params.extend(topics)
        with self._connect() as db:
            sql = 'SELECT * FROM documents' + (' WHERE ' + ' AND '.join(clauses) if clauses else '') + ' ORDER BY doc_id'
            return [self._document(db,r) for r in db.execute(sql,params).fetchall()]

    def _chunk(self, db, row):
        if row is None:
            return None
        result = dict(row)
        page = db.execute('SELECT printed_page FROM pages WHERE doc_id=? AND pdf_page=?',
                          (row['doc_id'],row['pdf_page'])).fetchone()
        result['printed_page'] = page[0]
        document = self._document(db,db.execute('SELECT * FROM documents WHERE doc_id=?', (row['doc_id'],)).fetchone())
        result['document'] = {k: document[k] for k in ('title','authors','year','topics','language')}
        return result

    def get_chunk(self, chunk_id):
        with self._connect() as db:
            return self._chunk(db,db.execute('SELECT * FROM chunks WHERE chunk_id=?', (chunk_id,)).fetchone())

    def list_chunks(self, filters=None, include_indexing=False):
        documents = self.list_documents(filters, include_nonready=include_indexing)
        ids = {d['doc_id'] for d in documents if d['status'] in ('ready','indexing')}
        with self._connect() as db:
            return [self._chunk(db,r) for r in db.execute('SELECT * FROM chunks ORDER BY doc_id,pdf_page,chunk_order').fetchall() if r['doc_id'] in ids]

    def get_page(self, doc_id, pdf_page):
        with self._connect() as db:
            row = db.execute('SELECT * FROM pages WHERE doc_id=? AND pdf_page=?', (doc_id,pdf_page)).fetchone()
            return dict(row) if row else None

    def get_file_path(self, doc_id):
        with self._connect() as db:
            row = db.execute('SELECT file_relpath FROM documents WHERE doc_id=?', (doc_id,)).fetchone()
        if row is None:
            return None
        path = (self.files_dir / row[0]).resolve()
        if not path.is_relative_to(self.files_dir):
            raise ProjectError('INVALID_REQUEST', 'File path escapes controlled directory')
        return str(path) if path.is_file() else None

    def set_document_status(self, doc_id, status, error=None):
        if status not in ('uploaded','parsing','indexing','ready','failed'):
            raise ProjectError('INVALID_REQUEST', 'Invalid status')
        with self._connect() as db:
            if status in ('ready','indexing') and not db.execute('SELECT 1 FROM chunks WHERE doc_id=?', (doc_id,)).fetchone():
                raise ProjectError('INVALID_REQUEST', 'Cannot serve a document without chunks')
            cursor = db.execute('UPDATE documents SET status=?,error_code=?,error_message=?,updated_at=? WHERE doc_id=?',
                (status,(error or {}).get('code'),(error or {}).get('message'),datetime.now(timezone.utc).isoformat(),doc_id))
            if cursor.rowcount != 1:
                raise ProjectError('NOT_FOUND', doc_id)

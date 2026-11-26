BEGIN IMMEDIATE;
CREATE TABLE IF NOT EXISTS metadata_revisions (
    revision_id INTEGER PRIMARY KEY,
    doc_id TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    before_json TEXT NOT NULL,
    after_json TEXT NOT NULL,
    evidence_page INTEGER,
    note TEXT NOT NULL,
    reviewed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS metadata_revisions_document ON metadata_revisions(doc_id, revision_id DESC);
PRAGMA user_version = 2;
COMMIT;

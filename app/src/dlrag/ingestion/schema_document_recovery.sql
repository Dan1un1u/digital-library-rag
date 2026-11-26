BEGIN IMMEDIATE;
CREATE TABLE IF NOT EXISTS document_fulltext_reviews (
    doc_id TEXT PRIMARY KEY REFERENCES documents(doc_id) ON DELETE CASCADE,
    review_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS document_replacements (
    replacement_doc_id TEXT PRIMARY KEY REFERENCES documents(doc_id),
    original_doc_id TEXT NOT NULL REFERENCES documents(doc_id),
    submitted_at TEXT NOT NULL,
    CHECK (replacement_doc_id <> original_doc_id)
);
CREATE INDEX IF NOT EXISTS document_replacements_original
    ON document_replacements(original_doc_id, submitted_at, replacement_doc_id);
PRAGMA user_version = 3;
COMMIT;

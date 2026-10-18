-- LibraryStore schema version 1.
-- Enable foreign keys on every connection.
PRAGMA foreign_keys = ON;

CREATE TABLE documents (
    doc_id TEXT PRIMARY KEY,
    file_sha256 TEXT NOT NULL UNIQUE CHECK(length(file_sha256) = 64),
    file_relpath TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL CHECK(length(trim(title)) > 0),
    authors_json TEXT NOT NULL DEFAULT '[]',
    year INTEGER,
    language TEXT NOT NULL DEFAULT 'unknown'
        CHECK(language IN ('zh','en','mixed','unknown')),
    source_url TEXT,
    rights_note TEXT NOT NULL DEFAULT '待人工确认',
    status TEXT NOT NULL DEFAULT 'uploaded'
        CHECK(status IN ('uploaded','parsing','indexing','ready','failed')),
    error_code TEXT,
    error_message TEXT,
    page_count INTEGER NOT NULL DEFAULT 0 CHECK(page_count >= 0),
    parser_version TEXT,
    chunking_config_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE document_topics (
    doc_id TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    topic TEXT NOT NULL CHECK(length(trim(topic)) > 0),
    PRIMARY KEY (doc_id, topic)
);

CREATE TABLE pages (
    doc_id TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    pdf_page INTEGER NOT NULL CHECK(pdf_page >= 1),
    printed_page TEXT,
    raw_text TEXT NOT NULL,
    normalized_text TEXT NOT NULL,
    diagnostics_json TEXT NOT NULL DEFAULT '[]',
    PRIMARY KEY (doc_id, pdf_page)
);

CREATE TABLE chunks (
    chunk_id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL,
    pdf_page INTEGER NOT NULL,
    chunk_order INTEGER NOT NULL CHECK(chunk_order >= 1),
    section TEXT,
    text TEXT NOT NULL CHECK(length(text) > 0),
    page_char_start INTEGER NOT NULL CHECK(page_char_start >= 0),
    page_char_end INTEGER NOT NULL CHECK(page_char_end > page_char_start),
    token_count INTEGER CHECK(token_count >= 0),
    char_count INTEGER NOT NULL CHECK(char_count = length(text)),
    UNIQUE(doc_id, pdf_page, chunk_order),
    FOREIGN KEY(doc_id, pdf_page) REFERENCES pages(doc_id, pdf_page)
        ON DELETE CASCADE
);

CREATE INDEX idx_documents_status_year ON documents(status, year);
CREATE INDEX idx_topics_topic ON document_topics(topic, doc_id);
-- UNIQUE(doc_id, pdf_page, chunk_order) also indexes page/chunk lookup.

-- The ingestion code must verify:
-- chunk.text == normalized_page_text[start:end] (Python character offsets).
-- Parse/store pages and chunks atomically; rollback partial output on failure.
-- JSON fields and relative file paths are validated by LibraryStore.
-- token_count is NULL in character mode; chunking configuration records units.

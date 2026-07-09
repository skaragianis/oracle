CREATE TABLE chunks (
    id INTEGER PRIMARY KEY,
    doc_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    text TEXT NOT NULL,
    page_number INTEGER,
    paragraph_start INTEGER,
    paragraph_end INTEGER,
    char_start INTEGER,
    char_end INTEGER
);

CREATE INDEX idx_chunks_doc_id ON chunks(doc_id);

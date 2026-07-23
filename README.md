# Oracle

A project to experiment with Retrieval Augmented Generation (RAG).

So far it supports vector embeddings and BM25 for similarity searches. Search
results are combined using recipricol rank fusion. Offers a CLI and web
application operating on the same data. Not multi-user; local personal use 
only.

## Technologies

- Python, Typescript, FastAPI, Sqlite, ChromaDB, TikToken, FastEmbed, VueJS

## Approach

Documents are copied into the ORACLE_UPLOADS_DIR under a generated name,
whether provided by the web or cli ux. An entry is created in the sqlite
documents table with status pending. An existing document can be replaced and
re-processed by providing again.

Documents are in the processing, ready or failed state. The cli processes
inline; the server returns 202 and runs it as a background task, and resumes
anything left in pending at startup in the same way.

Chunking accumulates paragraphs until CHUNK_TARGET_TOKENS tokens by tiktoken,
carrying over an overlap of CHUNK_OVERLAP_TOKENS tokens, and stores them in
the sqlite chunks table. PDF's and docx files are supported.

There is a trigger on the chunks table after insert, to insert into a virtual
chunks_fts table that calculates FTS5 for each inserted chunk.

Embedding iterates a document's chunks in batches of EMBED_BATCH_SIZE,
creating text embeddings using fastembed that are stored in chromadb.

Search takes the top 10 matches using BM25 based on dropping stop words and
OR'ing the resulting terms, and the top 10 vector matches in chromadb for the
embedded query. Either index can be used on its own, and only chunks of ready
documents are included. It then does a reciprocal rank fusion to produce a top
5 relevant results that skews to document chunks appearing in both results
(k of 60).

## Prequisites

- Docker

### Development Prequisites

- uv
- pnpm

## Web Usage (docker)

```sh
make up
```

Available at http://localhost:8080

## CLI Usage

```sh
make cli-run ARGS="--help"
```

## Development Usage

### Install dependencies

```sh
make setup
```

### Review targets

```sh
make
```

## License

MIT

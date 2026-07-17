# Oracle

A project to experiment with Retrieval Augmented Generation (RAG).

So far it supports vector embeddings and BM25 for similarity searches. Search
results are combined using recipricol rank fusion. Offers a CLI and web
application operating on the same data. Not multi-user; local personal use 
only.

## Technologies

- Python, Typescript, FastAPI, Sqlite, ChromaDB, FastEmbed, VueJS

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

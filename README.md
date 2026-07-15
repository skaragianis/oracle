# Oracle

Upload documents then search using vector embeddings combined with BM25.
Offers a CLI and web interface for the same backend data. Pipe your question
and search results into your LLM of choice.

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

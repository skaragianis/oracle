import mimetypes
import shutil
import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path

import fitz
import tiktoken

from oracle.common.chunks import create_chunk, delete_chunks_for_document
from oracle.common.documents import (
    create_document,
    find_document_by_filename,
    mark_document_ready,
    replace_document_upload,
)

SUPPORTED_SUFFIXES = {".pdf", ".docx"}

DEFAULT_UPLOADS_DIR = Path(__file__).resolve().parents[3] / "data" / "uploads"

CHUNK_ENCODING_NAME = "o200k_base"
CHUNK_TARGET_TOKENS = 800
CHUNK_OVERLAP_TOKENS = 100


class UnsupportedFileTypeError(ValueError):
    pass


@dataclass
class IngestResult:
    doc_id: int
    destination_path: Path
    replaced: bool


def ingest_file(
    conn: sqlite3.Connection,
    source_path: str | Path,
    uploads_dir: Path = DEFAULT_UPLOADS_DIR,
) -> IngestResult:
    source_path = Path(source_path)

    if source_path.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise UnsupportedFileTypeError(
            f"Unsupported file type {source_path.suffix!r}; expected one of {sorted(SUPPORTED_SUFFIXES)}"
        )

    if not source_path.is_file():
        raise FileNotFoundError(source_path)

    existing = find_document_by_filename(conn, source_path.name)

    uploads_dir.mkdir(parents=True, exist_ok=True)
    destination_path = uploads_dir / f"{uuid.uuid4()}{source_path.suffix.lower()}"
    shutil.copy2(source_path, destination_path)

    mime_type, _ = mimetypes.guess_type(source_path.name)

    if existing is not None:
        doc_id, previous_stored_filename = existing
        delete_chunks_for_document(conn, doc_id)
        replace_document_upload(
            conn,
            doc_id,
            stored_filename=destination_path.name,
            mime_type=mime_type or "application/octet-stream",
            size_bytes=destination_path.stat().st_size,
        )
        (uploads_dir / previous_stored_filename).unlink(missing_ok=True)
    else:
        doc_id = create_document(
            conn,
            filename=source_path.name,
            stored_filename=destination_path.name,
            mime_type=mime_type or "application/octet-stream",
            size_bytes=destination_path.stat().st_size,
        )

    # Only PDFs are chunked so far; anything else is stored but stays 'pending'
    # because it has no chunks and so cannot be searched yet.
    if destination_path.suffix.lower() == ".pdf":
        chunk_pdf(conn, doc_id, destination_path)
        mark_document_ready(conn, doc_id)

    return IngestResult(
        doc_id=doc_id, destination_path=destination_path, replaced=existing is not None
    )


@dataclass
class _BufferedLine:
    text: str
    page_number: int
    paragraph_index: int
    char_start: int
    token_count: int


def chunk_pdf(
    conn: sqlite3.Connection,
    doc_id: int,
    pdf_path: str | Path,
    *,
    encoding_name: str = CHUNK_ENCODING_NAME,
    target_tokens: int = CHUNK_TARGET_TOKENS,
    overlap_tokens: int = CHUNK_OVERLAP_TOKENS,
) -> int:
    encoding = tiktoken.get_encoding(encoding_name)
    seq = 0
    char_offset = 0
    paragraph_index = -1
    buffer: list[_BufferedLine] = []
    buffer_tokens = 0
    buffer_has_new_content = False

    def flush() -> None:
        nonlocal seq, buffer, buffer_tokens, buffer_has_new_content
        if not buffer_has_new_content:
            return

        first, last = buffer[0], buffer[-1]
        create_chunk(
            conn,
            doc_id=doc_id,
            seq=seq,
            text="".join(line.text for line in buffer),
            page_number=first.page_number,
            paragraph_start=first.paragraph_index,
            paragraph_end=last.paragraph_index,
            char_start=first.char_start,
            char_end=last.char_start + len(last.text),
        )
        seq += 1

        overlap: list[_BufferedLine] = []
        overlap_tokens_used = 0
        for line in reversed(buffer):
            if overlap and overlap_tokens_used + line.token_count > overlap_tokens:
                break
            overlap.insert(0, line)
            overlap_tokens_used += line.token_count
            if overlap_tokens_used >= overlap_tokens:
                break

        buffer = overlap
        buffer_tokens = overlap_tokens_used
        buffer_has_new_content = False

    with fitz.open(pdf_path) as doc:
        for page_number, page in enumerate(doc, start=1):
            for block in page.get_text("blocks"):
                block_text = block[4]
                if not block_text.strip():
                    continue
                paragraph_index += 1

                for raw_line in block_text.splitlines():
                    line_text = raw_line + "\n"
                    token_count = len(encoding.encode(line_text))

                    buffer.append(
                        _BufferedLine(
                            text=line_text,
                            page_number=page_number,
                            paragraph_index=paragraph_index,
                            char_start=char_offset,
                            token_count=token_count,
                        )
                    )
                    buffer_tokens += token_count
                    buffer_has_new_content = True
                    char_offset += len(line_text)

                    if buffer_tokens >= target_tokens:
                        flush()

    flush()
    return seq


def remove_document_uploads():
    for item in DEFAULT_UPLOADS_DIR.iterdir():
        item.unlink()

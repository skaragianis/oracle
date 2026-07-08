import shutil
import uuid
from pathlib import Path

SUPPORTED_SUFFIXES = {".pdf", ".docx"}

DEFAULT_UPLOADS_DIR = Path(__file__).resolve().parents[3] / "data" / "uploads"


class UnsupportedFileTypeError(ValueError):
    pass


def ingest_file(
    source_path: str | Path, uploads_dir: Path = DEFAULT_UPLOADS_DIR
) -> Path:
    source_path = Path(source_path)

    if source_path.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise UnsupportedFileTypeError(
            f"Unsupported file type {source_path.suffix!r}; expected one of {sorted(SUPPORTED_SUFFIXES)}"
        )

    if not source_path.is_file():
        raise FileNotFoundError(source_path)

    uploads_dir.mkdir(parents=True, exist_ok=True)
    destination_path = uploads_dir / f"{uuid.uuid4()}{source_path.suffix.lower()}"
    shutil.copy2(source_path, destination_path)

    return destination_path

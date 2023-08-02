import os
import csv
from pathlib import Path
from functools import cache
from typing import Optional, Generator, TextIO, Union, TYPE_CHECKING
import shutil

from zavod.logs import get_logger
from google.cloud.storage import Client, Bucket, Blob  # type: ignore
from nomenklatura.statement import Statement
from nomenklatura.statement.serialize import unpack_row

from zavod import settings

if TYPE_CHECKING:
    from zavod.meta.dataset import Dataset

log = get_logger(__name__)
StatementGen = Generator[Statement, None, None]
PathLike = Union[str, os.PathLike[str]]
BLOB_CHUNK = 40 * 1024 * 1024
STATEMENTS_FILE = "statements.pack"
ISSUES_LOG = "issues.log"
ISSUES_FILE = "issues.json"
RESOURCES_FILE = "resources.json"
INDEX_FILE = "index.json"


class ConfigurationException(Exception):
    def __init__(self, message):
        self.message = message

class CloudStorageBackend():
    def __init__(self):
        if settings.ARCHIVE_BUCKET is None:
            raise ConfigurationException("No backfill bucket configured")
        client = Client()
        self.bucket = client.get_bucket(settings.ARCHIVE_BUCKET)

    def get_blob(name):
        return self.bucket.get_blob(name)

# Other than being a bit icky, there's no real demand for abstracting away
# the Google Cloud Storage API right now, so this is a blatant mirror for now.
class FileSystemBlob():
    def __init__(self, base_path, name):
        self.path = base_path / name
        self.name = name

    def open(self, mode, chunk_size):
        log.info(f"Opening {self.path}")
        return open(self.path, mode, buffering=chunk_size)

    def download_to_filename(self, dst):
        log.info(f"Copying file {self.path} to {dst}")
        shutil.copyfile(self.path, dst)

    def reload(self):
        pass


class FilesystemBackend():
    def __init__(self):
        if settings.ARCHIVE_PATH is None:
            raise ConfigurationException("No archive path configured.")
        self.base_path = Path(settings.ARCHIVE_PATH)

    def get_blob(self, name):
        path = self.base_path / name
        if os.path.isfile(path):
            return FileSystemBlob(self.base_path, name)
        else:
            log.info(f"File {path} doesn't exist.")


backends = {
    "CloudStorageBackend": CloudStorageBackend,
    "FilesystemBackend": FilesystemBackend,
}

@cache
def get_archive_backend():
    if settings.ARCHIVE_BACKEND is None:
        return None
    try:
        return backends[settings.ARCHIVE_BACKEND]()
    except ConfigurationException as error:
        log.warn(error.message)


def get_backfill_blob(dataset_name: str, resource: PathLike) -> Optional[Blob]:
    backend = get_archive_backend()
    if backend is None:
        return None
    blob_name = f"datasets/{settings.BACKFILL_RELEASE}/{dataset_name}/{resource}"
    return backend.get_blob(blob_name)


def backfill_resource(
    dataset_name: str, resource: PathLike, path: Path
) -> Optional[Path]:
    blob = get_backfill_blob(dataset_name, resource)
    if blob is not None:
        log.info(
            "Backfilling dataset resource...",
            dataset=dataset_name,
            resource=resource,
            blob_name=blob.name,
        )
        blob.download_to_filename(path)
        return path
    return None


def datasets_path() -> Path:
    return settings.DATA_PATH / "datasets"


def _state_path() -> Path:
    return settings.DATA_PATH / "state"


def dataset_path(dataset_name: str) -> Path:
    path = datasets_path() / dataset_name
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def dataset_state_path(dataset_name: str) -> Path:
    """The state directory is outside the main data directory and is used for temporary
    processing artifacts (like the materialised graph, and the timestamp index)."""
    path = _state_path() / dataset_name
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def dataset_resource_path(dataset_name: str, resource: PathLike) -> Path:
    dataset_path_ = dataset_path(dataset_name)
    return dataset_path_.joinpath(resource)


def get_dataset_resource(
    dataset: "Dataset",
    resource: PathLike,
    backfill: bool = True,
    force_backfill: bool = False,
) -> Optional[Path]:
    path = dataset_resource_path(dataset.name, resource)
    if path.exists() and not force_backfill:
        return path
    if backfill or force_backfill:
        return backfill_resource(dataset.name, resource, path)
    return None


def get_dataset_index(dataset_name: str, backfill: bool = True) -> Optional[Path]:
    path: Optional[Path] = dataset_resource_path(dataset_name, INDEX_FILE)
    if path is not None and not path.exists() and backfill:
        path = backfill_resource(dataset_name, INDEX_FILE, path)
    if path is not None and path.exists():
        return path
    return None


def _read_fh_statements(fh: TextIO, external: bool) -> StatementGen:
    for cells in csv.reader(fh):
        stmt = unpack_row(cells, Statement)
        if not external and stmt.external:
            continue
        yield stmt


def iter_dataset_statements(dataset: "Dataset", external: bool = True) -> StatementGen:
    """Create a generator that yields all statements in the given dataset."""
    for scope in dataset.leaves:
        yield from _iter_scope_statements(scope, external=external)


def _iter_scope_statements(dataset: "Dataset", external: bool = True) -> StatementGen:
    path = dataset_resource_path(dataset.name, STATEMENTS_FILE)
    if path.exists():
        with open(path, "r") as fh:
            yield from _read_fh_statements(fh, external)
        return

    backfill_blob = get_backfill_blob(dataset.name, STATEMENTS_FILE)
    if backfill_blob is not None:
        log.info(
            "Streaming backfilled statements...",
            backfill_dataset=dataset.name,
        )
        backfill_blob.reload()
        with backfill_blob.open("r", chunk_size=BLOB_CHUNK) as fh:
            yield from _read_fh_statements(fh, external)
        return
    raise ValueError(f"Cannot load statements for: {dataset.name}")


def iter_previous_statements(dataset: "Dataset", external: bool = True) -> StatementGen:
    """Load the statements from the previous release of the dataset by streaming them
    from the data archive."""
    for scope in dataset.leaves:
        backfill_blob = get_backfill_blob(scope.name, STATEMENTS_FILE)
        if backfill_blob is not None:
            log.info(
                "Streaming backfilled statements...",
                dataset=scope.name,
            )
            backfill_blob.reload()
            with backfill_blob.open("r", chunk_size=BLOB_CHUNK) as fh:
                yield from _read_fh_statements(fh, external)

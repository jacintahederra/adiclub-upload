"""Storage abstraction for adiClub uploads.

Provides an abstract ``StorageBackend`` with two implementations:

- ``LocalStorageBackend``  — writes files to a local folder (default, no creds).
- ``AzureBlobStorageBackend`` — writes files to Azure Blob Storage using
  environment variables (no hardcoded credentials).

Metadata for every upload is appended to a JSON-lines registry stored next to
the uploaded content, so uploads can be listed/audited later.
"""

from __future__ import annotations

import json
import os
import uuid
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


@dataclass
class UploadMetadata:
    """Metadata recorded for each uploaded file."""

    member: str
    original_filename: str
    stored_filename: str
    content_type: str
    media_type: str  # "image" or "video"
    size_bytes: int
    timestamp: str

    @staticmethod
    def create(
        member: str,
        original_filename: str,
        stored_filename: str,
        content_type: str,
        media_type: str,
        size_bytes: int,
    ) -> "UploadMetadata":
        return UploadMetadata(
            member=member,
            original_filename=original_filename,
            stored_filename=stored_filename,
            content_type=content_type,
            media_type=media_type,
            size_bytes=size_bytes,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )


def build_stored_filename(original_filename: str) -> str:
    """Return a collision-free filename: ``<uuid4><original extension>``."""

    ext = Path(original_filename).suffix.lower()
    return f"{uuid.uuid4().hex}{ext}"


class StorageBackend(ABC):
    """Abstract storage layer for saving and retrieving uploaded media."""

    @abstractmethod
    def save(self, data: bytes, stored_filename: str, metadata: UploadMetadata) -> str:
        """Persist ``data`` and its ``metadata``.

        Returns a reference (path or blob URL) to the stored object.
        """

    @abstractmethod
    def get(self, stored_filename: str) -> Optional[bytes]:
        """Return the bytes for ``stored_filename`` or ``None`` if not found."""

    @abstractmethod
    def list_uploads(self) -> list["UploadMetadata"]:
        """Return metadata for all uploads, newest first."""

    @abstractmethod
    def name(self) -> str:
        """Human-readable backend name (for UI display)."""


class LocalStorageBackend(StorageBackend):
    """Store uploads in a local directory. Works with zero credentials."""

    def __init__(self, base_dir: str = "uploads") -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.registry_path = self.base_dir / "metadata.jsonl"

    def save(self, data: bytes, stored_filename: str, metadata: UploadMetadata) -> str:
        target = self.base_dir / stored_filename
        with open(target, "wb") as fh:
            fh.write(data)
        self._append_metadata(metadata)
        return str(target)

    def get(self, stored_filename: str) -> Optional[bytes]:
        target = self.base_dir / stored_filename
        if not target.exists():
            return None
        with open(target, "rb") as fh:
            return fh.read()

    def name(self) -> str:
        return f"Local ({self.base_dir})"

    def list_uploads(self) -> list[UploadMetadata]:
        if not self.registry_path.exists():
            return []
        uploads: list[UploadMetadata] = []
        with open(self.registry_path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    uploads.append(UploadMetadata(**json.loads(line)))
                except (json.JSONDecodeError, TypeError):
                    continue
        uploads.sort(key=lambda m: m.timestamp, reverse=True)
        return uploads

    def _append_metadata(self, metadata: UploadMetadata) -> None:
        with open(self.registry_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(asdict(metadata)) + "\n")


class AzureBlobStorageBackend(StorageBackend):
    """Store uploads in Azure Blob Storage.

    Configuration comes from environment variables (no hardcoded secrets):

    - ``AZURE_STORAGE_CONNECTION_STRING`` — the storage account connection string.
    - ``AZURE_STORAGE_CONTAINER``         — the target container name.

    Metadata is stored as a sibling ``.json`` blob for each upload.
    """

    def __init__(
        self,
        connection_string: Optional[str] = None,
        container: Optional[str] = None,
    ) -> None:
        connection_string = connection_string or os.getenv(
            "AZURE_STORAGE_CONNECTION_STRING"
        )
        container = container or os.getenv("AZURE_STORAGE_CONTAINER")

        if not connection_string:
            raise ValueError(
                "AZURE_STORAGE_CONNECTION_STRING is required for the Azure backend."
            )
        if not container:
            raise ValueError(
                "AZURE_STORAGE_CONTAINER is required for the Azure backend."
            )

        # Imported lazily so the local backend has no hard dependency on azure.
        from azure.storage.blob import BlobServiceClient

        self._service = BlobServiceClient.from_connection_string(connection_string)
        self._container_name = container
        self._container = self._service.get_container_client(container)
        try:
            self._container.create_container()
        except Exception:
            # Container already exists (or no permission to create) — continue.
            pass

    def save(self, data: bytes, stored_filename: str, metadata: UploadMetadata) -> str:
        blob = self._container.get_blob_client(stored_filename)
        blob.upload_blob(data, overwrite=True)

        meta_blob = self._container.get_blob_client(stored_filename + ".json")
        meta_blob.upload_blob(
            json.dumps(asdict(metadata)).encode("utf-8"), overwrite=True
        )
        return blob.url

    def get(self, stored_filename: str) -> Optional[bytes]:
        blob = self._container.get_blob_client(stored_filename)
        if not blob.exists():
            return None
        return blob.download_blob().readall()

    def name(self) -> str:
        return f"Azure Blob ({self._container_name})"

    def list_uploads(self) -> list[UploadMetadata]:
        uploads: list[UploadMetadata] = []
        for blob in self._container.list_blobs():
            if not blob.name.endswith(".json"):
                continue
            client = self._container.get_blob_client(blob.name)
            try:
                raw = client.download_blob().readall()
                uploads.append(UploadMetadata(**json.loads(raw)))
            except Exception:
                continue
        uploads.sort(key=lambda m: m.timestamp, reverse=True)
        return uploads


def get_storage_backend() -> StorageBackend:
    """Select a backend based on the ``STORAGE_BACKEND`` env var.

    ``LOCAL`` (default) requires no credentials so the app runs out of the box.
    ``AZURE`` uses Azure Blob Storage via environment variables.
    """

    backend = os.getenv("STORAGE_BACKEND", "LOCAL").strip().upper()
    if backend == "AZURE":
        return AzureBlobStorageBackend()
    return LocalStorageBackend(os.getenv("LOCAL_STORAGE_DIR", "uploads"))

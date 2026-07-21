"""Storage abstraction for adiClub uploads.

Provides an abstract ``StorageBackend`` with three implementations:

- ``LocalStorageBackend`` — writes files to a local folder (default, no creds).
- ``AzureBlobStorageBackend`` — writes files to Azure Blob Storage.
- ``CloudinaryStorageBackend`` — writes files to Cloudinary for public hosting.

Metadata for every upload is stored alongside the uploaded media so uploads can
be listed and reviewed later from the admin gallery.
"""

from __future__ import annotations

import io
import json
import os
import uuid
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.request import urlopen


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
    storage_url: str | None = None

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
    """Store uploads in Azure Blob Storage."""

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

        from azure.storage.blob import BlobServiceClient

        self._service = BlobServiceClient.from_connection_string(connection_string)
        self._container_name = container
        self._container = self._service.get_container_client(container)
        try:
            self._container.create_container()
        except Exception:
            pass

    def save(self, data: bytes, stored_filename: str, metadata: UploadMetadata) -> str:
        blob = self._container.get_blob_client(stored_filename)
        blob.upload_blob(data, overwrite=True)
        metadata.storage_url = blob.url

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


class CloudinaryStorageBackend(StorageBackend):
    """Store uploads and metadata in Cloudinary."""

    def __init__(
        self,
        cloud_name: Optional[str] = None,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        folder: Optional[str] = None,
    ) -> None:
        cloud_name = cloud_name or os.getenv("CLOUDINARY_CLOUD_NAME")
        api_key = api_key or os.getenv("CLOUDINARY_API_KEY")
        api_secret = api_secret or os.getenv("CLOUDINARY_API_SECRET")
        folder = folder or os.getenv("CLOUDINARY_FOLDER", "adiclub-upload")

        if not cloud_name:
            raise ValueError(
                "CLOUDINARY_CLOUD_NAME is required for the Cloudinary backend."
            )
        if not api_key:
            raise ValueError(
                "CLOUDINARY_API_KEY is required for the Cloudinary backend."
            )
        if not api_secret:
            raise ValueError(
                "CLOUDINARY_API_SECRET is required for the Cloudinary backend."
            )

        import cloudinary
        import cloudinary.api
        import cloudinary.uploader

        cloudinary.config(
            cloud_name=cloud_name,
            api_key=api_key,
            api_secret=api_secret,
            secure=True,
        )

        self._api = cloudinary.api
        self._uploader = cloudinary.uploader
        self._folder = folder.strip("/")
        self._metadata_prefix = f"{self._folder}/metadata/"

    def save(self, data: bytes, stored_filename: str, metadata: UploadMetadata) -> str:
        stem = Path(stored_filename).stem
        ext = Path(stored_filename).suffix.lstrip(".").lower()
        media_public_id = f"{self._folder}/media/{stem}"
        metadata_public_id = f"{self._folder}/metadata/{stored_filename}.json"

        upload_result = self._uploader.upload(
            io.BytesIO(data),
            resource_type="auto",
            public_id=media_public_id,
            format=ext,
            overwrite=True,
            use_filename=False,
            unique_filename=False,
        )
        metadata.storage_url = upload_result["secure_url"]

        self._uploader.upload(
            io.BytesIO(json.dumps(asdict(metadata)).encode("utf-8")),
            resource_type="raw",
            public_id=metadata_public_id,
            overwrite=True,
            use_filename=False,
            unique_filename=False,
        )
        return metadata.storage_url

    def get(self, stored_filename: str) -> Optional[bytes]:
        metadata = self._get_metadata(stored_filename)
        if metadata is None or not metadata.storage_url:
            return None
        with urlopen(metadata.storage_url) as response:
            return response.read()

    def name(self) -> str:
        return f"Cloudinary ({self._folder})"

    def list_uploads(self) -> list[UploadMetadata]:
        uploads: list[UploadMetadata] = []
        next_cursor: str | None = None

        while True:
            kwargs = {
                "resource_type": "raw",
                "type": "upload",
                "prefix": self._metadata_prefix,
                "max_results": 500,
            }
            if next_cursor:
                kwargs["next_cursor"] = next_cursor
            result = self._api.resources(**kwargs)

            for resource in result.get("resources", []):
                try:
                    with urlopen(resource["secure_url"]) as response:
                        uploads.append(
                            UploadMetadata(**json.loads(response.read().decode("utf-8")))
                        )
                except Exception:
                    continue

            next_cursor = result.get("next_cursor")
            if not next_cursor:
                break

        uploads.sort(key=lambda m: m.timestamp, reverse=True)
        return uploads

    def _get_metadata(self, stored_filename: str) -> UploadMetadata | None:
        try:
            resource = self._api.resource(
                f"{self._folder}/metadata/{stored_filename}.json",
                resource_type="raw",
                type="upload",
            )
            with urlopen(resource["secure_url"]) as response:
                return UploadMetadata(**json.loads(response.read().decode("utf-8")))
        except Exception:
            return None


def get_storage_backend() -> StorageBackend:
    """Select a backend based on the ``STORAGE_BACKEND`` env var."""

    backend = os.getenv("STORAGE_BACKEND", "LOCAL").strip().upper()
    if backend == "AZURE":
        return AzureBlobStorageBackend()
    if backend == "CLOUDINARY":
        return CloudinaryStorageBackend()
    return LocalStorageBackend(os.getenv("LOCAL_STORAGE_DIR", "uploads"))

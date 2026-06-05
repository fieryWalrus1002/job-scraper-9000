"""Shared fixtures for ingest CLI tests.

The azurite_conn_str fixture spins up the official Microsoft Azure Storage
emulator (mcr.microsoft.com/azure-storage/azurite) at session scope.
Docker-dependent tests are marked pytest.mark.docker and skip automatically
when Docker is unavailable.

Run just the Docker tests:
    uv run pytest -m docker tests/ingest/test_cli.py -v
"""

from __future__ import annotations

import subprocess
import time
import uuid

import pytest

_AZURITE_IMAGE = "mcr.microsoft.com/azure-storage/azurite"
_HOST_BLOB_PORT = 20010

# Well-known Azurite development account (public, from Azurite source constants.js)
AZURITE_CONN_STR = (
    "DefaultEndpointsProtocol=http;"
    "AccountName=devstoreaccount1;"
    "AccountKey=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw==;"
    f"BlobEndpoint=http://127.0.0.1:{_HOST_BLOB_PORT}/devstoreaccount1;"
)


def _docker_available() -> bool:
    try:
        return (
            subprocess.run(
                ["docker", "info"], capture_output=True, timeout=5
            ).returncode
            == 0
        )
    except Exception:
        return False


@pytest.fixture(scope="session")
def azurite_conn_str():
    """Start Azurite blob emulator in Docker; yield its connection string for the session."""
    if not _docker_available():
        pytest.skip("Docker not available")

    name = f"azurite-ingest-{uuid.uuid4().hex[:8]}"
    subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            name,
            "-p",
            f"{_HOST_BLOB_PORT}:10000",
            _AZURITE_IMAGE,
            "azurite-blob",
            "--blobHost",
            "0.0.0.0",
            "--skipApiVersionCheck",
        ],
        check=True,
        capture_output=True,
    )

    from azure.storage.blob import BlobServiceClient

    deadline = time.monotonic() + 20.0
    while time.monotonic() < deadline:
        try:
            list(
                BlobServiceClient.from_connection_string(
                    AZURITE_CONN_STR
                ).list_containers()
            )
            break
        except Exception:
            time.sleep(0.5)
    else:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)
        raise RuntimeError("Azurite blob service did not become ready within 20 s")

    yield AZURITE_CONN_STR

    subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=15)


@pytest.fixture
def clean_blob_storage(azurite_conn_str):
    """Create pending/processed/failed containers and empty them before each test."""
    from azure.storage.blob import BlobServiceClient

    svc = BlobServiceClient.from_connection_string(azurite_conn_str)
    containers = {}
    for name in ("pending", "processed", "failed"):
        c = svc.get_container_client(name)
        try:
            c.create_container()
        except Exception:
            pass
        for blob in c.list_blobs():
            c.delete_blob(blob.name)
        containers[name] = c
    return containers

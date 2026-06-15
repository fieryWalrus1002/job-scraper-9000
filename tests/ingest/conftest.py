"""Shared fixtures for ingest CLI tests.

The azurite_conn_str fixture spins up the official Microsoft Azure Storage
emulator (mcr.microsoft.com/azure-storage/azurite) at session scope.
Docker-dependent tests are marked pytest.mark.docker and skip automatically
when Docker is unavailable.

Run just the Docker tests:
    uv run pytest -m docker tests/ingest/test_cli.py -v
"""

from __future__ import annotations

import socket
import subprocess
import time
import uuid

import pytest

# Pinned to a digest, not :latest, for reproducible runs (#257). MCR
# intermittently 401s anonymous pulls of the mutable :latest tag; a digest is
# immutable and dodges that class of failure. To refresh: pull the new image
# and read `docker inspect --format '{{index .RepoDigests 0}}' <image>`.
_AZURITE_IMAGE = (
    "mcr.microsoft.com/azure-storage/azurite"
    "@sha256:647c63a91102a9d8e8000aab803436e1fc85fbb285e7ce830a82ee5d6661cf37"
)
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


def _port_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


# Timeouts so a wedged Docker daemon/socket fails loudly instead of hanging
# test setup forever (matches _docker_available's timeout=5).
_INSPECT_TIMEOUT_S = 10
_PULL_TIMEOUT_S = 120


def _image_present(image: str) -> bool:
    """True if ``image`` is already cached locally (no registry contact).

    A timeout on this fast local op means the Docker daemon is wedged — raise
    immediately with the real cause rather than misclassify it as a cache miss
    and grind through ~3×120s of pull retries with a misleading error.
    """
    try:
        return (
            subprocess.run(
                ["docker", "image", "inspect", image],
                capture_output=True,
                timeout=_INSPECT_TIMEOUT_S,
            ).returncode
            == 0
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"`docker image inspect {image}` timed out after {_INSPECT_TIMEOUT_S}s "
            "— the Docker daemon appears wedged."
        ) from exc


def _ensure_image(image: str, *, attempts: int = 3, base_delay: float = 2.0) -> None:
    """Make sure ``image`` is available locally, pulling with backoff if not.

    The azurite image lives on MCR, which intermittently 401s anonymous pulls
    (#257). We only pull when the image is missing — a cached image keeps
    working offline and doesn't newly depend on the registry — and retry a
    needed pull so a transient blip becomes a slow success instead of a hard
    failure. Fails loud if every attempt is exhausted: never skip, or CI would
    go green without exercising the ingest path at all.
    """
    if _image_present(image):
        return
    last_err = "(no output)"
    for attempt in range(1, attempts + 1):
        try:
            result = subprocess.run(
                ["docker", "pull", image],
                capture_output=True,
                text=True,
                timeout=_PULL_TIMEOUT_S,
            )
            if result.returncode == 0:
                return
            last_err = (
                f"exit {result.returncode}\n"
                f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
            )
        except subprocess.TimeoutExpired:
            last_err = f"timed out after {_PULL_TIMEOUT_S}s"
        if attempt < attempts:
            time.sleep(base_delay * 2 ** (attempt - 1))
    raise RuntimeError(
        f"docker pull {image!r} failed after {attempts} attempts; last error:\n{last_err}"
    )


@pytest.fixture(scope="session")
def azurite_conn_str():
    """Start Azurite blob emulator in Docker; yield its connection string for the session."""
    if not _docker_available():
        pytest.skip("Docker not available")
    if not _port_available(_HOST_BLOB_PORT):
        pytest.skip(f"Port {_HOST_BLOB_PORT} is already in use")

    # Pull (with retry) before `docker run` so a flaky registry surfaces as a
    # clear error here rather than a cryptic `docker run` exit 125.
    _ensure_image(_AZURITE_IMAGE)

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
    from azure.core.exceptions import ResourceExistsError
    from azure.storage.blob import BlobServiceClient

    svc = BlobServiceClient.from_connection_string(azurite_conn_str)
    containers = {}
    for name in ("pending", "processed", "failed"):
        c = svc.get_container_client(name)
        try:
            c.create_container()
        except ResourceExistsError:
            pass
        for blob in c.list_blobs():
            c.delete_blob(blob.name)
        containers[name] = c
    return containers

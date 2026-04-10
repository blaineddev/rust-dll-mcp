import sys
from pathlib import Path

import httpx


MANIFEST_URL = "https://raw.githubusercontent.com/blaineddev/rust-dll-mcp/main/manifest.json"
BUILD_ID_FILE = "build_id.txt"
CURRENT_DB_FILE = "rust_dlls_current.db"
PREVIOUS_DB_FILE = "rust_dlls_previous.db"


async def fetch_manifest() -> dict:
	async with httpx.AsyncClient() as client:
		response = await client.get(MANIFEST_URL)
	if response.status_code != 200:
		raise RuntimeError(f"Failed to fetch manifest: HTTP {response.status_code}")
	return response.json()


async def download_file(url: str, destination: Path) -> None:
	"""Stream-download url to destination, printing progress to stderr."""
	destination.parent.mkdir(parents=True, exist_ok=True)
	print(f"Downloading {url} ...", file=sys.stderr, flush=True)
	async with httpx.AsyncClient(follow_redirects=True) as client:
		async with client.stream("GET", url) as response:
			response.raise_for_status()
			total = int(response.headers.get("content-length", 0))
			downloaded = 0
			with destination.open("wb") as file_handle:
				async for chunk in response.aiter_bytes(chunk_size=65536):
					file_handle.write(chunk)
					downloaded += len(chunk)
					if total:
						percent = downloaded * 100 // total
						print(f"\r  {percent}% ({downloaded}/{total} bytes)", file=sys.stderr, end="", flush=True)
	print(file=sys.stderr, flush=True)


def get_current_build_id(cache_dir: Path) -> str:
	build_id_path = cache_dir / BUILD_ID_FILE
	if build_id_path.exists():
		return build_id_path.read_text().strip()
	return ""


def save_build_id(cache_dir: Path, build_id: str) -> None:
	cache_dir.mkdir(parents=True, exist_ok=True)
	(cache_dir / BUILD_ID_FILE).write_text(build_id)


async def ensure_current_db(cache_dir: Path) -> Path:
	"""Return path to current DB, downloading if stale or missing."""
	manifest = await fetch_manifest()
	remote_build_id = manifest["buildId"]
	local_build_id = get_current_build_id(cache_dir)
	db_path = cache_dir / CURRENT_DB_FILE

	if local_build_id == remote_build_id and db_path.exists():
		print("Local DB is up to date.", file=sys.stderr, flush=True)
		return db_path

	print(f"Updating DB (local={local_build_id!r}, remote={remote_build_id!r})", file=sys.stderr, flush=True)
	await download_file(manifest["releaseUrl"], db_path)
	save_build_id(cache_dir, remote_build_id)
	return db_path


async def ensure_previous_db(cache_dir: Path) -> Path | None:
	"""Return path to previous wipe DB, downloading on demand. Returns None if unavailable."""
	manifest = await fetch_manifest()
	previous_url = manifest.get("previousReleaseUrl", "")
	if not previous_url:
		return None

	db_path = cache_dir / PREVIOUS_DB_FILE
	if not db_path.exists():
		await download_file(previous_url, db_path)
	return db_path

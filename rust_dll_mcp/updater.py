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


async def sync_databases(cache_dir: Path) -> tuple[Path, Path | None]:
	"""Ensure the cached databases match the latest manifest.

	On a new build, stale caches are deleted and the current (and previous) wipe
	databases are re-downloaded fresh, so we never serve outdated data. Returns
	(current_db_path, previous_db_path_or_None).
	"""
	manifest = await fetch_manifest()
	remote_build_id = manifest["buildId"]
	local_build_id = get_current_build_id(cache_dir)
	current_path = cache_dir / CURRENT_DB_FILE
	previous_path = cache_dir / PREVIOUS_DB_FILE

	if local_build_id == remote_build_id and current_path.exists():
		print("rust-dll-mcp: database is up to date.", file=sys.stderr, flush=True)
	else:
		print(
			f"rust-dll-mcp: new build (local={local_build_id!r}, remote={remote_build_id!r}); "
			"clearing cache and downloading.",
			file=sys.stderr,
			flush=True,
		)
		current_path.unlink(missing_ok=True)
		previous_path.unlink(missing_ok=True)
		await download_file(manifest["releaseUrl"], current_path)
		save_build_id(cache_dir, remote_build_id)

	previous_url = manifest.get("previousReleaseUrl", "")
	if previous_url and not previous_path.exists():
		await download_file(previous_url, previous_path)

	return current_path, (previous_path if previous_path.exists() else None)

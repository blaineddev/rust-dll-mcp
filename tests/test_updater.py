import json
import pytest
import respx
import httpx
from pathlib import Path
from rust_dll_mcp.updater import fetch_manifest, download_file, get_current_build_id, save_build_id

MANIFEST_URL = "https://raw.githubusercontent.com/blaineddev/rust-dll-mcp/main/manifest.json"
FAKE_MANIFEST = {
	"buildId": "20260403120000",
	"wipeDate": "2026-04-03",
	"releaseUrl": "https://github.com/blaineddev/rust-dll-mcp/releases/download/wipe-2026-04-03/rust_dlls.db",
	"previousReleaseUrl": "https://github.com/blaineddev/rust-dll-mcp/releases/download/wipe-2026-03-06/rust_dlls.db",
}


@pytest.mark.asyncio
async def test_fetch_manifest_returns_dict():
	with respx.mock:
		respx.get(MANIFEST_URL).mock(return_value=httpx.Response(200, json=FAKE_MANIFEST))
		manifest = await fetch_manifest()
	assert manifest["buildId"] == "20260403120000"
	assert manifest["wipeDate"] == "2026-04-03"


@pytest.mark.asyncio
async def test_fetch_manifest_raises_on_error():
	with respx.mock:
		respx.get(MANIFEST_URL).mock(return_value=httpx.Response(404))
		with pytest.raises(RuntimeError, match="Failed to fetch manifest"):
			await fetch_manifest()


@pytest.mark.asyncio
async def test_download_file_writes_content(tmp_path):
	destination = tmp_path / "test.db"
	with respx.mock:
		respx.get("https://example.com/test.db").mock(
			return_value=httpx.Response(200, content=b"fake db content")
		)
		await download_file("https://example.com/test.db", destination)
	assert destination.read_bytes() == b"fake db content"


def test_save_and_get_build_id(tmp_path):
	save_build_id(tmp_path, "20260403120000")
	assert get_current_build_id(tmp_path) == "20260403120000"


def test_get_build_id_returns_empty_when_missing(tmp_path):
	assert get_current_build_id(tmp_path) == ""

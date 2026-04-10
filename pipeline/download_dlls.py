"""
Download the RustDedicated managed DLL depot via SteamCMD.

App ID:   258550 (RustDedicated)
Depot ID: 258552 (Windows managed DLLs)

Usage:
	python pipeline/download_dlls.py --output-dir work/dlls
"""
import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


STEAM_APP_ID = "258550"
STEAM_DEPOT_ID = "258552"
STEAMCMD_URL_LINUX = "https://steamcdn-a.akamaihd.net/client/installer/steamcmd_linux.tar.gz"
STEAMCMD_URL_WINDOWS = "https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip"


def install_steamcmd(install_dir: Path) -> Path:
	install_dir.mkdir(parents=True, exist_ok=True)
	system = platform.system()

	if system == "Linux":
		archive = install_dir / "steamcmd_linux.tar.gz"
		subprocess.run(
			["curl", "-sSL", "-o", str(archive), STEAMCMD_URL_LINUX],
			check=True,
		)
		subprocess.run(["tar", "-xzf", str(archive), "-C", str(install_dir)], check=True)
		steamcmd_executable = install_dir / "steamcmd.sh"
	elif system == "Windows":
		archive = install_dir / "steamcmd.zip"
		subprocess.run(
			["curl", "-sSL", "-o", str(archive), STEAMCMD_URL_WINDOWS],
			check=True,
		)
		shutil.unpack_archive(str(archive), str(install_dir))
		steamcmd_executable = install_dir / "steamcmd.exe"
	else:
		print(f"Unsupported platform: {system}", file=sys.stderr)
		sys.exit(1)

	return steamcmd_executable


def download_depot(steamcmd_executable: Path, output_dir: Path) -> None:
	output_dir.mkdir(parents=True, exist_ok=True)
	subprocess.run(
		[
			str(steamcmd_executable),
			"+@NoPromptForPassword", "1",
			"+login", "anonymous",
			"+download_depot", STEAM_APP_ID, STEAM_DEPOT_ID,
			"+quit",
		],
		check=True,
	)

	# SteamCMD downloads depot relative to its own install directory.
	# Linux: {steamcmd_dir}/linux32/steamapps/content/app_{id}/depot_{id}
	# Windows: {steamcmd_dir}/steamapps/content/app_{id}/depot_{id}
	# Fallback: ~/.steam/steamapps/content/... (older SteamCMD behaviour)
	steamcmd_dir = steamcmd_executable.parent
	depot_relative = Path("steamapps") / "content" / f"app_{STEAM_APP_ID}" / f"depot_{STEAM_DEPOT_ID}"

	candidates = [
		steamcmd_dir / "linux32" / depot_relative,
		steamcmd_dir / depot_relative,
		Path.home() / ".steam" / depot_relative,
		Path(os.environ.get("LOCALAPPDATA", "")) / "Steam" / depot_relative,
	]

	steam_download_path = next((path for path in candidates if path.exists()), None)

	if steam_download_path is None:
		checked = "\n  ".join(str(path) for path in candidates)
		print(f"ERROR: Could not find downloaded depot. Checked:\n  {checked}", file=sys.stderr)
		sys.exit(1)

	dll_files = list(steam_download_path.rglob("*.dll"))
	print(f"Copying {len(dll_files)} DLLs to {output_dir}", flush=True)
	for dll_file in dll_files:
		shutil.copy2(dll_file, output_dir / dll_file.name)

	print(f"Done. {len(dll_files)} DLLs in {output_dir}", flush=True)


if __name__ == "__main__":
	argument_parser = argparse.ArgumentParser(description="Download RustDedicated managed DLLs via SteamCMD")
	argument_parser.add_argument("--output-dir", type=Path, default=Path("work/dlls"))
	argument_parser.add_argument("--steamcmd-dir", type=Path, default=Path("work/steamcmd"))
	args = argument_parser.parse_args()

	steamcmd_executable = install_steamcmd(args.steamcmd_dir)
	download_depot(steamcmd_executable, args.output_dir)

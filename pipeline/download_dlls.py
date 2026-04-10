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

	# SteamCMD downloads to a fixed path; copy to output_dir
	steam_download_path = Path.home() / ".steam" / "steamapps" / "content" / f"app_{STEAM_APP_ID}" / f"depot_{STEAM_DEPOT_ID}"
	if not steam_download_path.exists():
		# Fallback Windows path
		steam_download_path = Path(os.environ.get("LOCALAPPDATA", "")) / "Steam" / "steamapps" / "content" / f"app_{STEAM_APP_ID}" / f"depot_{STEAM_DEPOT_ID}"

	if not steam_download_path.exists():
		print(f"ERROR: Could not find downloaded depot at {steam_download_path}", file=sys.stderr)
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

"""
Decompile all .dll files in a directory to .cs source files using ilspycmd.

Usage:
	python pipeline/decompile.py --dlls-dir work/dlls --output-dir work/source
"""
import argparse
import subprocess
import sys
from pathlib import Path


def install_ilspycmd() -> None:
	result = subprocess.run(
		["dotnet", "tool", "install", "--global", "ilspycmd"],
		capture_output=True,
		text=True,
	)
	# exit code 1 with "already installed" message is acceptable
	if result.returncode != 0 and "already installed" not in result.stderr:
		print(result.stderr, file=sys.stderr)
		sys.exit(1)
	print("ilspycmd ready", flush=True)


def decompile_dll(dll_path: Path, output_dir: Path) -> bool:
	"""Decompile a single DLL to a .cs file. Returns True on success."""
	result = subprocess.run(
		["ilspycmd", "--outputdir", str(output_dir), str(dll_path)],
		capture_output=True,
		text=True,
		timeout=120,
	)
	if result.returncode != 0:
		print(
			f"  WARNING: failed to decompile {dll_path.name}: {result.stderr[:200]}",
			file=sys.stderr,
			flush=True,
		)
		return False
	return True


def decompile_all(dlls_dir: Path, output_dir: Path) -> None:
	output_dir.mkdir(parents=True, exist_ok=True)
	dll_files = list(dlls_dir.glob("*.dll"))
	print(f"Decompiling {len(dll_files)} DLLs", flush=True)

	success_count = 0
	failure_count = 0

	for dll_file in dll_files:
		if decompile_dll(dll_file, output_dir):
			success_count += 1
		else:
			failure_count += 1

	print(f"Done. {success_count} succeeded, {failure_count} failed.", flush=True)


if __name__ == "__main__":
	argument_parser = argparse.ArgumentParser(description="Decompile DLLs to C# source using ilspycmd")
	argument_parser.add_argument("--dlls-dir", type=Path, default=Path("work/dlls"))
	argument_parser.add_argument("--output-dir", type=Path, default=Path("work/source"))
	argument_parser.add_argument("--skip-install", action="store_true")
	args = argument_parser.parse_args()

	if not args.skip_install:
		install_ilspycmd()

	decompile_all(args.dlls_dir, args.output_dir)

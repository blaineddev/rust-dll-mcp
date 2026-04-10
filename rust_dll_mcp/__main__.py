import asyncio

from rust_dll_mcp.server import run


def main() -> None:
	asyncio.run(run())


if __name__ == "__main__":
	main()

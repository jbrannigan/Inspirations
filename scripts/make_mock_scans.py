import base64
from pathlib import Path


TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNgYAAAAAMAASsJTYQAAAAASUVORK5CYII="
)


def main() -> None:
    inbox = Path("imports/scans/inbox")
    inbox.mkdir(parents=True, exist_ok=True)
    (inbox / "mock_scan_1.png").write_bytes(TINY_PNG)
    print(f"Wrote {inbox / 'mock_scan_1.png'}")


if __name__ == "__main__":
    main()


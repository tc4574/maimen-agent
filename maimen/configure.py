"""Store a locally entered MCP credential without putting it in command arguments."""
import getpass
import os
from pathlib import Path


def save_token(token, path=Path(".env")):
    token = token.strip()
    if not token or any(c.isspace() for c in token) or len(token) > 4096:
        raise ValueError("Invalid credential format")
    path = Path(path)
    if path.is_symlink():
        raise ValueError("Credential file must not be a symbolic link")
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else ["MAIMEN_MODE=demo"]
    lines = [line for line in lines if line.partition("=")[0].strip() != "MCD_MCP_TOKEN"]
    lines.append("MCD_MCP_TOKEN=" + token)
    # Do not change project mode when a credential is added.
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(lines) + "\n")


def main():
    token = getpass.getpass("MCP Token (hidden): ")
    save_token(token)
    print("MCP credential saved to local .env; demo mode unchanged.")


if __name__ == "__main__":
    main()

"""Generate an agent key offline; authorize its public address in the exchange UI."""
import argparse
import json
import os
from pathlib import Path
from .config import outside_git


def prepare_key(output):
    # Never ask for or process the master wallet key.
    from eth_account import Account
    path = outside_git(output)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    info = path.parent.stat()
    if info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError("Key directory must be private and owned by you")
    # Reserve before generating; cannot overwrite an existing key or follow a link.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as handle:
        wallet = Account.create()
        handle.write("0x" + wallet.key.hex().removeprefix("0x") + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return wallet.address


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, help="New private .key file outside Git")
    args = parser.parse_args(argv)
    try:
        address = prepare_key(Path(args.output))
        print(json.dumps({"agent_address": address, "approval": "NOT_AUTHORIZED", "next_action": "Authorize this public address in the exchange API-wallet UI for your chosen network"}))
        return 0
    except Exception:
        print("Agent preparation failed; check private path, existing file and optional dependencies.")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

"""Write latest.json, the file the in-app updater reads from the newest GitHub release.

Usage: python tools/make_manifest.py <path-to-DataMapperX.exe> <output latest.json>

* ``version``       comes from datamapperx/_version.py
* ``sha256``/``size`` are measured from the exe that is about to be published
* ``min_supported`` comes from the MIN_SUPPORTED_VERSION file: any installed copy older than this is
                    required to update before it can be used (see README, "Forcing an update")
* ``notes``         is this version's section of CHANGELOG.md
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from datamapperx._version import __version__  # noqa: E402


def changelog_section(version: str) -> str:
    """Text under '## [1.2.0] ...' up to the next '## ' heading."""
    path = ROOT / "CHANGELOG.md"
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8")
    match = re.search(rf"^## \[?v?{re.escape(version)}\]?[^\n]*\n(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
    return match.group(1).strip() if match else ""


def min_supported() -> str:
    path = ROOT / "MIN_SUPPORTED_VERSION"
    if not path.exists():
        return ""
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            return line
    return ""


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    exe, output = Path(sys.argv[1]), Path(sys.argv[2])
    data = exe.read_bytes()

    notes = changelog_section(__version__)
    if not notes:
        raise SystemExit(f"CHANGELOG.md has no '## [{__version__}]' section. Add release notes before tagging.")

    manifest = {
        "version": __version__,
        "min_supported": min_supported(),
        "asset": exe.name,
        "sha256": hashlib.sha256(data).hexdigest(),
        "size": len(data),
        "published_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "notes": notes,
    }
    output.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {output}: v{__version__}, {len(data):,} bytes, sha256 {manifest['sha256'][:12]}…")


if __name__ == "__main__":
    main()

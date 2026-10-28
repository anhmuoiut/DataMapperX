"""Write version_info.txt so DataMapperX.exe shows its version in Explorer > Properties > Details.

Usage: python tools/make_version_info.py [output_path]
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from datamapperx._version import __version__  # noqa: E402
from datamapperx.config import APP_TITLE  # noqa: E402

TEMPLATE = """# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({major}, {minor}, {patch}, 0),
    prodvers=({major}, {minor}, {patch}, 0),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '040904B0',
        [StringStruct('CompanyName', ''),
         StringStruct('FileDescription', '{title} - test log to Excel collector'),
         StringStruct('FileVersion', '{version}'),
         StringStruct('InternalName', '{title}'),
         StringStruct('OriginalFilename', '{title}.exe'),
         StringStruct('ProductName', '{title}'),
         StringStruct('ProductVersion', '{version}')])
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


def main() -> None:
    match = re.match(r"(\d+)\.(\d+)\.(\d+)", __version__)
    if not match:
        raise SystemExit(f"__version__ must look like 1.2.3, got {__version__!r}")
    major, minor, patch = match.groups()
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "version_info.txt"
    output.write_text(
        TEMPLATE.format(major=major, minor=minor, patch=patch, version=__version__, title=APP_TITLE), encoding="utf-8"
    )
    print(f"Wrote {output} for version {__version__}")


if __name__ == "__main__":
    main()

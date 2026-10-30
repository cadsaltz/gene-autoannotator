from __future__ import annotations

import re
from pathlib import Path

from annotationxlsx.errors import AnnotationXlsxError

DATE_TOKEN = re.compile(r'(\d{8})')


def select_tbrucei_zip(downloads_dir: Path) -> Path:
    downloads_dir = Path(downloads_dir)
    candidates = list(downloads_dir.glob('tbrucei*.zip'))
    if not candidates:
        raise AnnotationXlsxError(f'no tbrucei*.zip found in {downloads_dir}')
    dated = []
    for path in candidates:
        tokens = DATE_TOKEN.findall(path.name)
        if tokens:
            dated.append((max(tokens), path))
    if dated:
        dated.sort(key=lambda item: item[0])
        return dated[-1][1]
    return max(candidates, key=lambda path: path.stat().st_mtime)

from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from annotationxlsx.errors import AnnotationXlsxError


@dataclass
class LoadResult:
    annotations: dict[str, dict] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def load_annotations(path: Path) -> LoadResult:
    path = Path(path)
    if not path.exists():
        raise AnnotationXlsxError(f'input path does not exist: {path}')
    result = LoadResult()
    if path.is_dir():
        for json_path in sorted(path.rglob('*.json')):
            _load_text(result, json_path.read_text(encoding='utf8'), source=str(json_path))
    elif path.suffix.lower() == '.zip':
        with zipfile.ZipFile(path) as handle:
            for name in handle.namelist():
                if name.endswith('/') or not name.lower().endswith('.json'):
                    continue
                _load_text(result, handle.read(name).decode('utf8'), source=f'{path}:{name}')
    else:
        _load_text(result, path.read_text(encoding='utf8'), source=str(path))
    if not result.annotations:
        raise AnnotationXlsxError(f'no annotation JSON with gene_id found in {path}')
    return result


def _load_text(result: LoadResult, text: str, *, source: str) -> None:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        result.warnings.append(f'skip invalid JSON {source}: {exc}')
        return
    if not isinstance(payload, dict) or not payload.get('gene_id'):
        result.warnings.append(f'skip {source}: not an annotation object with gene_id')
        return
    gene_id = str(payload['gene_id'])
    if gene_id in result.annotations:
        result.warnings.append(f'duplicate gene_id {gene_id} from {source}; last wins')
    result.annotations[gene_id] = payload

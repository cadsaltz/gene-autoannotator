from __future__ import annotations

import argparse
import sys
from pathlib import Path

from annotationxlsx.errors import AnnotationXlsxError
from annotationxlsx.json_source import load_annotations
from annotationxlsx.schema import annotation_to_row
from annotationxlsx.tritrypdb import fetch_rows
from annotationxlsx.workbook import gene_ids_from_sheet, require_xlsx, write_sheet
from annotationxlsx.zip_select import select_tbrucei_zip

DEFAULT_WORKBOOK = 'annotation_comparison.xlsx'


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='annotationxlsx')
    sub = parser.add_subparsers(dest='command', required=True)

    json_p = sub.add_parser('json', help='Write a sheet from generated annotation JSON')
    json_p.add_argument('--input', required=True, help='JSON file, directory, or zip')
    json_p.add_argument('--workbook', default=DEFAULT_WORKBOOK)
    json_p.add_argument('--sheet', default='generated')

    veupath_p = sub.add_parser('veupath', help='Write a sheet from TriTrypDB gene records')
    veupath_p.add_argument('--workbook', default=DEFAULT_WORKBOOK)
    veupath_p.add_argument('--sheet', default='veupathdb')
    veupath_p.add_argument('--zip', dest='zip_path', default=None)
    veupath_p.add_argument('--order-from-sheet', default='generated')
    return parser


def _emit_warnings(warnings: list[str]) -> None:
    for warning in warnings:
        print(warning, file=sys.stderr)


def cmd_json(args: argparse.Namespace) -> int:
    workbook = Path(args.workbook)
    require_xlsx(workbook)
    loaded = load_annotations(Path(args.input))
    _emit_warnings(loaded.warnings)
    rows = [annotation_to_row(loaded.annotations[gene_id]) for gene_id in sorted(loaded.annotations)]
    write_warnings: list[str] = []
    write_sheet(workbook, args.sheet, rows, warnings=write_warnings)
    _emit_warnings(write_warnings)
    return 0


def cmd_veupath(args: argparse.Namespace) -> int:
    workbook = Path(args.workbook)
    require_xlsx(workbook)
    gene_ids = gene_ids_from_sheet(workbook, args.order_from_sheet) if workbook.exists() else None
    warnings: list[str] = []
    if not gene_ids:
        zip_path = Path(args.zip_path) if args.zip_path else select_tbrucei_zip(Path.home() / 'Downloads')
        loaded = load_annotations(zip_path)
        warnings.extend(loaded.warnings)
        gene_ids = sorted(loaded.annotations)
    if not gene_ids:
        raise AnnotationXlsxError('no gene ids for veupath (no generated sheet and no tbrucei zip)')
    rows = fetch_rows(gene_ids)
    write_warnings: list[str] = []
    write_sheet(workbook, args.sheet, rows, warnings=write_warnings)
    _emit_warnings(warnings + write_warnings)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == 'json':
            return cmd_json(args)
        return cmd_veupath(args)
    except AnnotationXlsxError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

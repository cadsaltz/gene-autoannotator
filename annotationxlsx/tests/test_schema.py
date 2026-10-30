from annotationxlsx.schema import (
    COLUMNS,
    EXCEL_CELL_LIMIT,
    annotation_to_row,
    empty_row,
    format_go_terms,
    format_string,
    format_string_list,
    truncate_cell,
)


def test_columns_order():
    assert COLUMNS == (
        'gene_id',
        'name',
        'function',
        'functional_category',
        'drug_susc_impact',
        'infection_impact',
        'go_terms',
    )


def test_null_and_missing_become_empty():
    assert format_string(None) == ''
    assert format_string('null') == ''
    assert format_string_list(None) == ''
    assert format_string_list([]) == ''
    assert format_go_terms(None) == ''
    assert format_go_terms([]) == ''


def test_string_list_joins_with_semicolon_space():
    assert format_string_list(['mitochondrial protein', 'sirtuin activity']) == (
        'mitochondrial protein; sirtuin activity'
    )


def test_go_terms_sorted_unique_skip_not():
    value = [
        {'id': 'GO:0005634', 'name': 'nucleus'},
        {'go_id': '0005739', 'go_term_name': 'mitochondrion'},
        {'id': 'GO:0005634', 'name': 'nucleus duplicate'},
        {'go_id': 'GO:0008150', 'go_term_name': 'biological_process', 'is_not': True},
        {'id': 'GO:0016787', 'name': 'hydrolase activity'},
    ]
    assert format_go_terms(value) == (
        'GO:0005634 nucleus; GO:0005739 mitochondrion; GO:0016787 hydrolase activity'
    )


def test_annotation_to_row_reads_biology_fields_only():
    row = annotation_to_row({
        'gene_id': 'Tb927.4.2520',
        'name': 'SIR2rp3',
        'function': 'a sirtuin',
        'functional_category': ['mitochondrial protein', 'sirtuin activity'],
        'drug_susc_impact': None,
        'infection_impact': None,
        'go_terms': [{'id': 'GO:0005739', 'name': 'mitochondrion'}],
        'annotation_notes': 'ignore me',
        'annotation_metadata': {'profile_id': 'tbrucei-treu927'},
    })
    assert row['gene_id'] == 'Tb927.4.2520'
    assert row['name'] == 'SIR2rp3'
    assert row['function'] == 'a sirtuin'
    assert row['functional_category'] == 'mitochondrial protein; sirtuin activity'
    assert row['drug_susc_impact'] == ''
    assert row['infection_impact'] == ''
    assert row['go_terms'] == 'GO:0005739 mitochondrion'
    assert list(row) == list(COLUMNS)


def test_empty_row_has_only_gene_id():
    row = empty_row('Tb927.1.100')
    assert row['gene_id'] == 'Tb927.1.100'
    assert all(row[key] == '' for key in COLUMNS if key != 'gene_id')


def test_truncate_cell_notes_overflow():
    text, truncated = truncate_cell('a' * (EXCEL_CELL_LIMIT + 10))
    assert truncated is True
    assert len(text) == EXCEL_CELL_LIMIT

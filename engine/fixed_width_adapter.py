import io
import json
import logging

from .base_adapter import BaseFormatAdapter
from .adapter_registry import register_adapter

_logger = logging.getLogger(__name__)


def _parse_column_definitions(options):
    """Extract column definitions from options.

    Accepts either:
      - options['column_definitions']: already a list of dicts, OR
      - options['fixed_width_definition']: a JSON string to parse.

    Each column dict must have keys: name, start, width.
    Optional key: type (default 'str').
    """
    col_defs = options.get('column_definitions')
    if col_defs and isinstance(col_defs, str):
        col_defs = json.loads(col_defs)
    if not col_defs:
        raw = options.get('fixed_width_definition', '')
        if isinstance(raw, str) and raw.strip():
            col_defs = json.loads(raw)
        elif isinstance(raw, list):
            col_defs = raw
    if not col_defs:
        raise ValueError(
            "Fixed-width adapter requires 'column_definitions' or "
            "'fixed_width_definition' in options."
        )
    # Normalise
    normalised = []
    for cd in col_defs:
        normalised.append({
            'name': str(cd['name']),
            'start': int(cd['start']),
            'width': int(cd['width']),
            'type': cd.get('type', 'str'),
        })
    return normalised


def _extract_fields(line, col_defs):
    """Extract field values from a fixed-width text line."""
    row = {}
    for cd in col_defs:
        start = cd['start']
        width = cd['width']
        raw = line[start:start + width] if start + width <= len(line) else line[start:]
        value = raw.strip()
        col_type = cd.get('type', 'str')
        if col_type in ('int', 'integer') and value:
            try:
                value = int(value)
            except ValueError:
                pass
        elif col_type in ('float', 'decimal', 'number') and value:
            try:
                value = float(value)
            except ValueError:
                pass
        row[cd['name']] = value
    return row


@register_adapter
class FixedWidthAdapter(BaseFormatAdapter):

    FORMAT_KEY = 'fixed'
    DISPLAY_NAME = 'Fixed-Width Columns'
    FILE_EXTENSIONS = ['.txt', '.dat', '.fw']
    MIME_TYPES = ['text/plain']
    PYTHON_DEPENDENCIES = []

    def parse(self, file_data, options):
        encoding = options.get('encoding', 'utf-8')
        has_header = bool(options.get('has_header', False))
        col_defs = _parse_column_definitions(options)

        text = file_data.decode(encoding)
        lines = text.splitlines()

        start_idx = 1 if has_header else 0
        for line in lines[start_idx:]:
            if not line.strip():
                continue
            yield _extract_fields(line, col_defs)

    def write(self, records, fields, options):
        encoding = options.get('encoding', 'utf-8')
        col_defs = _parse_column_definitions(options)

        # Build a lookup from field name to column definition
        def_by_name = {cd['name']: cd for cd in col_defs}

        output = io.StringIO()

        # Write header line
        header_parts = []
        for field in fields:
            cd = def_by_name.get(field)
            width = cd['width'] if cd else len(field) + 2
            header_parts.append(field.ljust(width)[:width])
        output.write(''.join(header_parts))
        output.write('\n')

        # Write data lines
        for record in records:
            parts = []
            for field in fields:
                cd = def_by_name.get(field)
                width = cd['width'] if cd else 20
                col_type = cd.get('type', 'str') if cd else 'str'
                value = record.get(field, '')
                value_str = str(value) if value is not None else ''

                if col_type in ('int', 'integer', 'float', 'decimal', 'number'):
                    # Right-align (left-pad) numbers
                    parts.append(value_str.rjust(width)[:width])
                else:
                    # Left-align (right-pad) strings
                    parts.append(value_str.ljust(width)[:width])
            output.write(''.join(parts))
            output.write('\n')

        return output.getvalue().encode(encoding)

    def detect_columns(self, file_data, options):
        col_defs = _parse_column_definitions(options)
        return [cd['name'] for cd in col_defs]

import io
import logging
from collections import OrderedDict

from .base_adapter import BaseFormatAdapter
from .adapter_registry import register_adapter

_logger = logging.getLogger(__name__)

try:
    import pyexcel_ods3
    _HAS_PYEXCEL_ODS3 = True
except ImportError:
    _HAS_PYEXCEL_ODS3 = False


def _get_sheet_data(file_data, sheet_name):
    """Return the rows of the requested sheet (or the first sheet)."""
    data = pyexcel_ods3.get_data(io.BytesIO(file_data))
    if sheet_name and sheet_name in data:
        return data[sheet_name]
    # Fall back to first sheet
    for name in data:
        return data[name]
    return []


@register_adapter
class OdsAdapter(BaseFormatAdapter):

    FORMAT_KEY = 'ods'
    DISPLAY_NAME = 'LibreOffice Calc (.ods)'
    FILE_EXTENSIONS = ['.ods']
    MIME_TYPES = [
        'application/vnd.oasis.opendocument.spreadsheet',
    ]
    PYTHON_DEPENDENCIES = ['pyexcel_ods3']

    def parse(self, file_data, options):
        if not _HAS_PYEXCEL_ODS3:
            raise ImportError("pyexcel_ods3 is required to parse ODS files")

        sheet_name = options.get('sheet_name')
        header_row = int(options.get('header_row', 1))
        data_start_row = int(options.get('data_start_row', header_row + 1))

        rows = _get_sheet_data(file_data, sheet_name)

        if not rows or len(rows) < header_row:
            return

        # Extract headers (1-based index -> 0-based list index)
        raw_headers = rows[header_row - 1]
        headers = []
        for i, val in enumerate(raw_headers):
            h = str(val).strip() if val is not None and val != '' else f'col_{i}'
            headers.append(h)

        # Yield data rows
        for row_idx in range(data_start_row - 1, len(rows)):
            row = rows[row_idx]
            # Pad row to header length if needed
            values = list(row) + [''] * max(0, len(headers) - len(row))

            # Skip entirely empty rows
            if not any(v is not None and v != '' for v in values):
                continue

            row_dict = {}
            for i, header in enumerate(headers):
                value = values[i] if i < len(values) else ''
                row_dict[header] = value if value is not None else ''
            yield row_dict

    def write(self, records, fields, options):
        if not _HAS_PYEXCEL_ODS3:
            raise ImportError("pyexcel_ods3 is required to write ODS files")

        sheet_name = options.get('sheet_name', 'Sheet1')

        sheet_rows = [fields]
        for record in records:
            sheet_rows.append([record.get(f, '') for f in fields])

        data = OrderedDict()
        data[sheet_name] = sheet_rows

        output = io.BytesIO()
        pyexcel_ods3.save_data(output, data)
        return output.getvalue()

    def detect_columns(self, file_data, options):
        if not _HAS_PYEXCEL_ODS3:
            raise ImportError("pyexcel_ods3 is required to read ODS files")

        sheet_name = options.get('sheet_name')
        header_row = int(options.get('header_row', 1))

        rows = _get_sheet_data(file_data, sheet_name)
        if not rows or len(rows) < header_row:
            return []

        raw_headers = rows[header_row - 1]
        headers = []
        for i, val in enumerate(raw_headers):
            h = str(val).strip() if val is not None and val != '' else f'col_{i}'
            headers.append(h)
        return headers

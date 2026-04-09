import csv
import io
import logging

from .base_adapter import BaseFormatAdapter
from .adapter_registry import register_adapter

_logger = logging.getLogger(__name__)

# Common BOM bytes for encoding detection
_BOM_MAP = {
    b'\xef\xbb\xbf': 'utf-8-sig',
    b'\xff\xfe': 'utf-16-le',
    b'\xfe\xff': 'utf-16-be',
}


def _detect_encoding(file_data, configured_encoding):
    """Detect encoding from BOM, fallback to configured."""
    for bom, enc in _BOM_MAP.items():
        if file_data.startswith(bom):
            return enc
    return configured_encoding or 'utf-8'


@register_adapter
class CsvAdapter(BaseFormatAdapter):

    FORMAT_KEY = 'csv'
    DISPLAY_NAME = 'CSV'
    FILE_EXTENSIONS = ['.csv', '.tsv', '.txt']
    MIME_TYPES = ['text/csv', 'text/plain', 'text/tab-separated-values']
    PYTHON_DEPENDENCIES = []

    def parse(self, file_data, options):
        encoding = _detect_encoding(file_data, options.get('encoding', 'utf-8'))
        delimiter = options.get('delimiter', ',')
        quotechar = options.get('quotechar', '"')
        has_header = options.get('has_header', True)

        text = file_data.decode(encoding)
        reader = csv.reader(io.StringIO(text), delimiter=delimiter, quotechar=quotechar)

        headers = None
        for row_num, row in enumerate(reader, 1):
            if not any(cell.strip() for cell in row):
                continue
            if has_header and headers is None:
                headers = [h.strip() for h in row]
                continue
            if headers is None:
                headers = [f'col_{i}' for i in range(len(row))]

            row_dict = {}
            for i, value in enumerate(row):
                key = headers[i] if i < len(headers) else f'col_{i}'
                row_dict[key] = value.strip()
            yield row_dict

    def write(self, records, fields, options):
        encoding = options.get('encoding', 'utf-8')
        delimiter = options.get('delimiter', ',')
        quotechar = options.get('quotechar', '"')

        output = io.StringIO()
        writer = csv.writer(output, delimiter=delimiter, quotechar=quotechar,
                            quoting=csv.QUOTE_MINIMAL)

        writer.writerow(fields)
        for record in records:
            writer.writerow([record.get(f, '') for f in fields])

        return output.getvalue().encode(encoding)

    def detect_columns(self, file_data, options):
        encoding = _detect_encoding(file_data, options.get('encoding', 'utf-8'))
        delimiter = options.get('delimiter', ',')
        quotechar = options.get('quotechar', '"')
        has_header = options.get('has_header', True)

        text = file_data.decode(encoding)
        reader = csv.reader(io.StringIO(text), delimiter=delimiter, quotechar=quotechar)

        for row in reader:
            if not any(cell.strip() for cell in row):
                continue
            if has_header:
                return [h.strip() for h in row]
            return [f'col_{i}' for i in range(len(row))]
        return []

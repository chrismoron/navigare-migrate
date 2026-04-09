import io
import json
import logging

from .base_adapter import BaseFormatAdapter
from .adapter_registry import register_adapter

_logger = logging.getLogger(__name__)


def _resolve_path(data, path):
    """Walk a dot-notation path into a nested dict/list structure.

    Example: _resolve_path({"data": {"items": [...]}}, "data.items") -> [...]
    """
    if not path:
        return data
    for part in path.split('.'):
        if isinstance(data, dict):
            data = data.get(part)
        elif isinstance(data, list) and part.isdigit():
            data = data[int(part)]
        else:
            return None
        if data is None:
            return None
    return data


def _flatten_dict(d, parent_key='', sep='.'):
    """Flatten a nested dict using *sep* as key separator.

    >>> _flatten_dict({'a': {'b': 1, 'c': 2}})
    {'a.b': 1, 'a.c': 2}
    """
    items = []
    for k, v in d.items():
        new_key = f'{parent_key}{sep}{k}' if parent_key else k
        if isinstance(v, dict):
            items.extend(_flatten_dict(v, new_key, sep).items())
        elif isinstance(v, list):
            # Store lists as JSON strings to keep a flat structure
            items.append((new_key, json.dumps(v, ensure_ascii=False)))
        else:
            items.append((new_key, v))
    return dict(items)


def _nest_path(root_path, array):
    """Rebuild a nested structure from a dot-notation root_path.

    Given root_path="data.items" and an array, returns:
        {"data": {"items": array}}
    """
    if not root_path:
        return array
    parts = root_path.split('.')
    result = current = {}
    for part in parts[:-1]:
        current[part] = {}
        current = current[part]
    current[parts[-1]] = array
    return result


def _is_jsonl(file_data):
    """Heuristic: JSONL if the trimmed content does not start with [ or {."""
    stripped = file_data.lstrip()
    if not stripped:
        return False
    # JSONL files consist of independent JSON values per line.
    # A quick heuristic: if the first non-whitespace char is '[' it is a JSON
    # array; if '{' it *could* be either a single object or JSONL.  We treat it
    # as JSONL when the second non-blank line also starts with '{'.
    first_char = chr(stripped[0])
    if first_char == '[':
        return False
    if first_char == '{':
        lines = [l for l in stripped.split(b'\n') if l.strip()]
        return len(lines) > 1
    return False


@register_adapter
class JsonAdapter(BaseFormatAdapter):

    FORMAT_KEY = 'json'
    DISPLAY_NAME = 'JSON'
    FILE_EXTENSIONS = ['.json', '.jsonl']
    MIME_TYPES = ['application/json', 'application/x-ndjson']
    PYTHON_DEPENDENCIES = []

    def parse(self, file_data, options):
        encoding = options.get('encoding', 'utf-8')
        root_path = options.get('root_path', '')
        flatten_nested = bool(options.get('flatten_nested', False))

        text = file_data.decode(encoding)

        # JSONL mode — one JSON object per line
        if _is_jsonl(file_data):
            for line_no, line in enumerate(text.splitlines(), 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError as exc:
                    _logger.warning("Skipping invalid JSON on line %d: %s", line_no, exc)
                    continue
                if not isinstance(obj, dict):
                    obj = {'value': obj}
                if flatten_nested:
                    obj = _flatten_dict(obj)
                yield obj
            return

        # Standard JSON mode
        data = json.loads(text)

        # Navigate to the target array via root_path
        if root_path:
            data = _resolve_path(data, root_path)
            if data is None:
                _logger.error("root_path '%s' did not resolve to a value", root_path)
                return

        # Normalise to list
        if isinstance(data, dict):
            data = [data]
        if not isinstance(data, list):
            _logger.error("Expected a JSON array; got %s", type(data).__name__)
            return

        for item in data:
            if not isinstance(item, dict):
                item = {'value': item}
            if flatten_nested:
                item = _flatten_dict(item)
            yield item

    def write(self, records, fields, options):
        encoding = options.get('encoding', 'utf-8')
        root_path = options.get('root_path', '')

        rows = []
        for record in records:
            row = {}
            for field in fields:
                row[field] = record.get(field, '')
            rows.append(row)

        output = _nest_path(root_path, rows)
        return json.dumps(output, ensure_ascii=False, indent=2).encode(encoding)

    def detect_columns(self, file_data, options):
        # Parse just the first record and extract its keys
        for row in self.parse(file_data, options):
            return list(row.keys())
        return []

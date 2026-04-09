import logging
import math
import re
from datetime import date, datetime

_logger = logging.getLogger(__name__)

# Restricted builtins for expression evaluation
_SAFE_BUILTINS = {
    'str': str, 'int': int, 'float': float, 'bool': bool,
    'len': len, 'min': min, 'max': max, 'round': round,
    'abs': abs, 'sum': sum, 'sorted': sorted, 'list': list,
    'dict': dict, 'tuple': tuple, 'set': set, 'enumerate': enumerate,
    'zip': zip, 'map': map, 'filter': filter, 'range': range,
    'True': True, 'False': False, 'None': None,
    'isinstance': isinstance, 'type': type,
}

_BLOCKED_NAMES = frozenset({
    '__import__', 'eval', 'exec', 'compile', 'open',
    'os', 'sys', 'subprocess', 'importlib', 'globals', 'locals',
    'getattr', 'setattr', 'delattr', '__builtins__',
})


def apply_transform(value, mapping, source_row=None):
    """Apply a field mapping transformation to a value.

    Args:
        value: Raw source value.
        mapping: Dict-like with transform config keys:
            transform_type, type_cast_to, value_map_id, expression,
            default_value, date_source_format, truncate_length,
            regex_pattern, concatenate_fields, concatenate_separator
        source_row (dict): Full source row for expression context.

    Returns:
        Transformed value.
    """
    if source_row is None:
        source_row = {}

    transform_type = mapping.get('transform_type', 'none')

    # Apply default if value is empty
    if _is_empty(value) and mapping.get('default_value'):
        value = mapping['default_value']

    if transform_type == 'none':
        return value

    if transform_type == 'type_cast':
        return cast_value(value, mapping.get('type_cast_to', 'str'))

    if transform_type == 'value_map':
        return apply_value_map(value, mapping)

    if transform_type == 'expression':
        return apply_expression(value, mapping.get('expression', ''), source_row)

    if transform_type == 'default':
        return mapping.get('default_value', '') if _is_empty(value) else value

    if transform_type == 'date_format':
        return apply_date_format(value, mapping.get('date_source_format', ''))

    if transform_type == 'truncate':
        max_len = mapping.get('truncate_length', 0)
        if max_len > 0 and isinstance(value, str):
            return value[:max_len]
        return value

    if transform_type == 'regex':
        return apply_regex(value, mapping.get('regex_pattern', ''))

    if transform_type == 'concatenate':
        fields_str = mapping.get('concatenate_fields', '')
        separator = mapping.get('concatenate_separator', ' ')
        return apply_concatenate(source_row, fields_str, separator)

    _logger.warning("Unknown transform type: %s", transform_type)
    return value


def cast_value(value, target_type):
    """Type-cast a value.

    Args:
        value: Value to cast.
        target_type (str): One of 'str', 'int', 'float', 'bool', 'date', 'datetime'.

    Returns:
        Cast value.
    """
    if _is_empty(value):
        return None if target_type in ('int', 'float', 'date', 'datetime') else value

    value_str = str(value).strip()

    if target_type == 'str':
        return value_str

    if target_type == 'int':
        # Handle floats like "123.0"
        return int(float(value_str))

    if target_type == 'float':
        # Handle comma as decimal separator
        cleaned = value_str.replace(' ', '').replace('\xa0', '')
        if ',' in cleaned and '.' not in cleaned:
            cleaned = cleaned.replace(',', '.')
        elif ',' in cleaned and '.' in cleaned:
            cleaned = cleaned.replace(',', '')
        return float(cleaned)

    if target_type == 'bool':
        return value_str.lower() in ('1', 'true', 'yes', 'tak', 'y', 't', 'on')

    if target_type == 'date':
        return _parse_date(value_str)

    if target_type == 'datetime':
        return _parse_datetime(value_str)

    return value


def apply_expression(value, expression, source_row):
    """Evaluate a restricted Python expression.

    Available context: value, record (source_row), datetime, date, re, math.

    Args:
        value: Current field value.
        expression (str): Python expression string.
        source_row (dict): Full source row.

    Returns:
        Result of expression evaluation.

    Raises:
        ValueError: If expression contains blocked names or fails.
    """
    if not expression:
        return value

    for blocked in _BLOCKED_NAMES:
        if blocked in expression:
            raise ValueError(f"Expression contains blocked name: '{blocked}'")

    context = {
        '__builtins__': _SAFE_BUILTINS,
        'value': value,
        'record': source_row,
        'row': source_row,
        'datetime': datetime,
        'date': date,
        're': re,
        'math': math,
    }

    try:
        compiled = compile(expression, '<migrate_expression>', 'eval')
        return eval(compiled, context)  # noqa: S307
    except Exception as e:
        raise ValueError(f"Expression error: {e}\nExpression: {expression}\nValue: {value!r}") from e


def apply_date_format(value, source_format):
    """Parse a date string using the specified strptime format.

    Args:
        value: Date string.
        source_format (str): strptime format, e.g. "%d/%m/%Y".

    Returns:
        date or datetime object.
    """
    if _is_empty(value):
        return None
    value_str = str(value).strip()
    if not source_format:
        return _parse_date(value_str)
    try:
        dt = datetime.strptime(value_str, source_format)
        if '%H' in source_format or '%M' in source_format or '%S' in source_format:
            return dt
        return dt.date()
    except ValueError as e:
        raise ValueError(f"Cannot parse date '{value_str}' with format '{source_format}': {e}") from e


def apply_regex(value, pattern):
    """Extract first capture group from regex match.

    Args:
        value: String value.
        pattern (str): Regex with at least one capture group.

    Returns:
        str: First capture group or original value if no match.
    """
    if _is_empty(value) or not pattern:
        return value
    match = re.search(pattern, str(value))
    if match and match.groups():
        return match.group(1)
    return str(value)


def apply_concatenate(source_row, fields_str, separator=' '):
    """Concatenate multiple source columns.

    Args:
        source_row (dict): Full source row.
        fields_str (str): Comma-separated source column names.
        separator (str): Join separator.

    Returns:
        str: Concatenated string.
    """
    if not fields_str:
        return ''
    field_names = [f.strip() for f in fields_str.split(',')]
    parts = []
    for fname in field_names:
        val = source_row.get(fname, '')
        if val and str(val).strip():
            parts.append(str(val).strip())
    return separator.join(parts)


def apply_value_map(value, mapping):
    """Apply value mapping from a migrate.value.map record.

    When called from the import engine, mapping should contain
    'value_map_data': list of (source_value, target_value) tuples
    and 'value_map_default' and 'value_map_case_sensitive'.

    Args:
        value: Source value.
        mapping (dict): Mapping config with value_map_data.

    Returns:
        Mapped value or default.
    """
    map_data = mapping.get('value_map_data', [])
    case_sensitive = mapping.get('value_map_case_sensitive', False)
    default = mapping.get('value_map_default', value)

    value_str = str(value).strip() if value else ''

    for src, tgt in map_data:
        if case_sensitive:
            if value_str == src:
                return tgt
        else:
            if value_str.lower() == str(src).lower():
                return tgt

    return default


def _is_empty(value):
    """Check if value is empty/None/blank string."""
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    return False


def _parse_date(value_str):
    """Try common date formats."""
    formats = [
        '%Y-%m-%d', '%d/%m/%Y', '%d.%m.%Y', '%m/%d/%Y',
        '%Y/%m/%d', '%d-%m-%Y', '%m-%d-%Y',
    ]
    for fmt in formats:
        try:
            return datetime.strptime(value_str, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Cannot parse date '{value_str}'. Tried formats: {', '.join(formats)}")


def _parse_datetime(value_str):
    """Try common datetime formats."""
    formats = [
        '%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%dT%H:%M:%SZ',
        '%d/%m/%Y %H:%M:%S', '%d.%m.%Y %H:%M:%S', '%m/%d/%Y %H:%M:%S',
        '%Y-%m-%d %H:%M', '%d/%m/%Y %H:%M',
    ]
    for fmt in formats:
        try:
            return datetime.strptime(value_str, fmt)
        except ValueError:
            continue
    # Fallback: try date-only
    return datetime.combine(_parse_date(value_str), datetime.min.time())

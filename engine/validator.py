import logging
import re

_logger = logging.getLogger(__name__)


class RowValidator:
    """Pre-import validation engine.

    Validates mapped rows against field mapping rules before ORM write.
    """

    def __init__(self, field_mappings):
        """Initialize validator.

        Args:
            field_mappings (list[dict]): Field mapping configurations, each with keys:
                field_name, field_type, required, unique, validation_regex
        """
        self.mappings = field_mappings
        self._unique_cache = {}  # field_name -> set of seen values

    def validate(self, row, row_number):
        """Validate a single mapped row.

        Args:
            row (dict): Mapped row with Odoo field names as keys.
            row_number (int): 1-based row number for error messages.

        Returns:
            list[str]: Error messages (empty means valid).
        """
        errors = []
        for mapping in self.mappings:
            field_name = mapping.get('field_name')
            if not field_name:
                continue

            value = row.get(field_name)
            is_empty = value is None or (isinstance(value, str) and not value.strip())

            # Required check
            if mapping.get('required') and is_empty:
                errors.append(
                    f"Row {row_number}: Field '{field_name}' is required but empty"
                )
                continue

            if is_empty:
                continue

            # Type compatibility
            field_type = mapping.get('field_type')
            type_error = self._check_type(value, field_type, field_name, row_number)
            if type_error:
                errors.append(type_error)

            # Regex validation
            regex = mapping.get('validation_regex')
            if regex:
                if not re.match(regex, str(value)):
                    errors.append(
                        f"Row {row_number}: Field '{field_name}' value '{value}' "
                        f"does not match pattern '{regex}'"
                    )

            # Uniqueness
            if mapping.get('unique'):
                cache_key = field_name
                if cache_key not in self._unique_cache:
                    self._unique_cache[cache_key] = set()
                val_str = str(value).strip()
                if val_str in self._unique_cache[cache_key]:
                    errors.append(
                        f"Row {row_number}: Field '{field_name}' value '{value}' "
                        f"is not unique within this import batch"
                    )
                else:
                    self._unique_cache[cache_key].add(val_str)

        return errors

    def _check_type(self, value, field_type, field_name, row_number):
        """Check basic type compatibility."""
        if not field_type:
            return None

        value_str = str(value).strip()

        if field_type in ('integer',):
            try:
                int(float(value_str))
            except (ValueError, TypeError):
                return (f"Row {row_number}: Field '{field_name}' expects integer, "
                        f"got '{value}'")

        elif field_type in ('float', 'monetary'):
            try:
                cleaned = value_str.replace(' ', '').replace('\xa0', '')
                if ',' in cleaned and '.' not in cleaned:
                    cleaned = cleaned.replace(',', '.')
                float(cleaned)
            except (ValueError, TypeError):
                return (f"Row {row_number}: Field '{field_name}' expects number, "
                        f"got '{value}'")

        elif field_type in ('date',):
            from .transform import _parse_date
            try:
                _parse_date(value_str)
            except ValueError:
                return (f"Row {row_number}: Field '{field_name}' expects date, "
                        f"got '{value}'")

        elif field_type in ('datetime',):
            from .transform import _parse_datetime
            try:
                _parse_datetime(value_str)
            except ValueError:
                return (f"Row {row_number}: Field '{field_name}' expects datetime, "
                        f"got '{value}'")

        return None

    def reset(self):
        """Reset uniqueness cache for a new validation run."""
        self._unique_cache.clear()

import abc
import logging

_logger = logging.getLogger(__name__)


class BaseFormatAdapter(abc.ABC):
    """Abstract base class for all format adapters.

    Every adapter must implement parse(), write(), detect_columns().
    """

    FORMAT_KEY = None
    DISPLAY_NAME = None
    FILE_EXTENSIONS = []
    MIME_TYPES = []
    PYTHON_DEPENDENCIES = []

    @abc.abstractmethod
    def parse(self, file_data, options):
        """Parse file bytes into an iterator of row dicts.

        Args:
            file_data (bytes): Raw file bytes.
            options (dict): Format-specific options from the profile
                (delimiter, encoding, sheet_name, root_path, etc.)

        Yields:
            dict: Row with string keys (column names) and raw values.
        """

    @abc.abstractmethod
    def write(self, records, fields, options):
        """Write records to file format.

        Args:
            records (Iterator[dict]): Dicts of field_name -> value.
            fields (list[str]): Ordered field names to export.
            options (dict): Format-specific options from the profile.

        Returns:
            bytes: Generated file content.
        """

    @abc.abstractmethod
    def detect_columns(self, file_data, options):
        """Parse just the headers/column names from a file.

        Args:
            file_data (bytes): Raw file bytes.
            options (dict): Format-specific options.

        Returns:
            list[str]: Column names detected in the file.
        """

    def preview(self, file_data, options, max_rows=20):
        """Parse headers + first N rows for preview display.

        Args:
            file_data (bytes): Raw file bytes.
            options (dict): Format-specific options.
            max_rows (int): Maximum rows to return.

        Returns:
            tuple: (headers: list[str], rows: list[list[str]])
        """
        headers = self.detect_columns(file_data, options)
        rows = []
        for i, row in enumerate(self.parse(file_data, options)):
            if i >= max_rows:
                break
            rows.append([str(row.get(h, '')) for h in headers])
        return headers, rows

    @classmethod
    def check_dependencies(cls):
        """Check if required Python packages are installed.

        Returns:
            tuple: (available: bool, error_message: str)
        """
        for dep in cls.PYTHON_DEPENDENCIES:
            try:
                __import__(dep)
            except ImportError:
                return False, f"Python package '{dep}' is not installed. Install with: pip install {dep}"
        return True, ''

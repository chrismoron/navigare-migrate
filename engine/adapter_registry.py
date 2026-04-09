import logging

_logger = logging.getLogger(__name__)

_adapters = {}


def register_adapter(adapter_cls):
    """Register a format adapter class.

    Can be used as a decorator or called directly.

    Args:
        adapter_cls: Subclass of BaseFormatAdapter.

    Returns:
        The adapter class (for decorator usage).
    """
    key = adapter_cls.FORMAT_KEY
    if key is None:
        raise ValueError(f"Adapter {adapter_cls.__name__} has no FORMAT_KEY defined")
    _adapters[key] = adapter_cls
    _logger.debug("Registered format adapter: %s (%s)", key, adapter_cls.DISPLAY_NAME)
    return adapter_cls


def get_adapter(format_key):
    """Instantiate and return an adapter for the given format key.

    Args:
        format_key (str): Format key (e.g. 'csv', 'xlsx').

    Returns:
        BaseFormatAdapter: Adapter instance.

    Raises:
        KeyError: If format_key is not registered.
    """
    if format_key not in _adapters:
        raise KeyError(f"No adapter registered for format '{format_key}'. "
                        f"Available: {', '.join(_adapters.keys())}")
    return _adapters[format_key]()


def get_available_formats():
    """Return list of registered format adapters with availability status.

    Returns:
        list[dict]: Each dict has keys: key, name, extensions, available, error.
    """
    result = []
    for key, cls in sorted(_adapters.items(), key=lambda x: x[0]):
        available, error = cls.check_dependencies()
        result.append({
            'key': key,
            'name': cls.DISPLAY_NAME or key,
            'extensions': cls.FILE_EXTENSIONS,
            'mime_types': cls.MIME_TYPES,
            'available': available,
            'error': error,
        })
    return result

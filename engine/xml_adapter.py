import io
import logging
import xml.etree.ElementTree as ET

from .base_adapter import BaseFormatAdapter
from .adapter_registry import register_adapter

_logger = logging.getLogger(__name__)


def _element_to_dict(element, use_attributes):
    """Convert an XML element to a flat dict.

    If *use_attributes* is True the dict is built from element attributes.
    Otherwise it is built from the text content of direct child elements.
    """
    row = {}
    if use_attributes:
        for attr_name, attr_value in element.attrib.items():
            row[attr_name] = attr_value
    else:
        for child in element:
            # Strip namespace prefix if present
            tag = child.tag
            if '}' in tag:
                tag = tag.split('}', 1)[1]
            row[tag] = (child.text or '').strip()
    return row


@register_adapter
class XmlAdapter(BaseFormatAdapter):

    FORMAT_KEY = 'xml'
    DISPLAY_NAME = 'XML'
    FILE_EXTENSIONS = ['.xml']
    MIME_TYPES = ['application/xml', 'text/xml']
    PYTHON_DEPENDENCIES = []

    def parse(self, file_data, options):
        record_element = options.get('record_element', 'record')
        use_attributes = bool(options.get('use_attributes', False))

        # Use iterparse for streaming to keep memory low on large files
        stream = io.BytesIO(file_data)
        context = ET.iterparse(stream, events=('end',))

        for event, elem in context:
            tag = elem.tag
            if '}' in tag:
                tag = tag.split('}', 1)[1]

            if tag == record_element:
                yield _element_to_dict(elem, use_attributes)
                # Free memory for processed elements
                elem.clear()

    def write(self, records, fields, options):
        root_element = options.get('root_element', 'records')
        record_element = options.get('record_element', 'record')
        use_attributes = bool(options.get('use_attributes', False))
        encoding = options.get('encoding', 'utf-8')

        root = ET.Element(root_element)

        for record in records:
            rec_elem = ET.SubElement(root, record_element)
            if use_attributes:
                for field in fields:
                    value = record.get(field, '')
                    rec_elem.set(field, str(value) if value is not None else '')
            else:
                for field in fields:
                    child = ET.SubElement(rec_elem, field)
                    value = record.get(field, '')
                    child.text = str(value) if value is not None else ''

        # Pretty-print with indentation
        ET.indent(root, space='  ')

        output = io.BytesIO()
        tree = ET.ElementTree(root)
        tree.write(output, encoding='unicode' if encoding == 'utf-8' else encoding,
                   xml_declaration=True)

        # ET.write with encoding='unicode' returns str; we need bytes
        raw = output.getvalue()
        if isinstance(raw, str):
            return raw.encode(encoding)
        return raw

    def detect_columns(self, file_data, options):
        record_element = options.get('record_element', 'record')
        use_attributes = bool(options.get('use_attributes', False))

        stream = io.BytesIO(file_data)
        context = ET.iterparse(stream, events=('end',))

        for event, elem in context:
            tag = elem.tag
            if '}' in tag:
                tag = tag.split('}', 1)[1]

            if tag == record_element:
                if use_attributes:
                    return list(elem.attrib.keys())
                columns = []
                for child in elem:
                    child_tag = child.tag
                    if '}' in child_tag:
                        child_tag = child_tag.split('}', 1)[1]
                    columns.append(child_tag)
                return columns

        return []

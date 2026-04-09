# Part of Navigare Migrate. See LICENSE file for full copyright and licensing details.
# Copyright 2025 Navigare Space Ltd
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).

import base64
import logging

from odoo import fields

from . import adapter_registry

_logger = logging.getLogger(__name__)


class ExportEngine:
    """Orchestrates the data export pipeline.

    Reads Odoo records, applies export mappings and formatting, then writes
    the result through a format adapter.
    """

    def __init__(self, env, profile, operation):
        """Initialise the export engine.

        Args:
            env: Odoo Environment.
            profile: ``migrate.profile`` record.
            operation: ``migrate.operation`` record.
        """
        self.env = env
        self.profile = profile
        self.operation = operation
        self.adapter = adapter_registry.get_adapter(profile.format_type)
        self.mappings = [
            m._to_engine_dict()
            for m in profile.field_mapping_ids.filtered('active')
        ]
        self.model_name = profile.model_name
        self.format_options = profile._get_format_options()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self, domain=None, record_ids=None):
        """Execute the export pipeline.

        Args:
            domain (list|None): Odoo search domain.  Ignored if *record_ids*
                is supplied.
            record_ids (list[int]|None): Explicit list of record IDs to
                export.

        Returns:
            bytes: Generated file content.
        """
        op = self.operation
        op.write({
            'state': 'running',
            'date_start': fields.Datetime.now(),
        })
        op._append_log("Export started")

        Model = self.env[self.model_name]

        try:
            # -- 1. Fetch records ------------------------------------------
            if record_ids:
                records = Model.browse(record_ids).exists()
            else:
                records = Model.search(domain or [])

            total = len(records)
            op.write({'total_rows': total})
            op._append_log(f"Exporting {total} record(s)")

            if not records:
                op.write({
                    'state': 'done',
                    'date_end': fields.Datetime.now(),
                    'processed_rows': 0,
                })
                op._append_log("No records to export")
                return b''

            # -- 2. Build export field list --------------------------------
            field_names = []
            export_labels = []
            for mapping in self.mappings:
                fname = mapping.get('field_name')
                if fname:
                    field_names.append(fname)
                    export_labels.append(
                        mapping.get('export_label') or fname
                    )

            # -- 3. Read and transform records -----------------------------
            export_rows = []
            errors = 0
            for idx, record in enumerate(records, start=1):
                try:
                    row = self._read_record(record, field_names, export_labels)
                    export_rows.append(row)
                except Exception as e:
                    _logger.warning(
                        "Export error on record %s (id=%s): %s",
                        record.display_name, record.id, e,
                    )
                    errors += 1

                # Periodic progress update
                if idx % 500 == 0:
                    op.write({'processed_rows': idx})

            # -- 4. Write through adapter ----------------------------------
            file_bytes = self.adapter.write(
                export_rows, export_labels, self.format_options,
            )

            # -- 5. Attach result to operation -----------------------------
            ext = self._get_extension()
            filename = f'{op.name}_export{ext}'
            op.write({
                'result_file': base64.b64encode(file_bytes),
                'result_filename': filename,
            })

            # -- 6. Finalise -----------------------------------------------
            state = 'done' if errors == 0 else 'partial'
            op.write({
                'state': state,
                'date_end': fields.Datetime.now(),
                'processed_rows': total,
                'created_count': len(export_rows),
                'error_count': errors,
            })
            op._append_log(
                f"Export finished: {len(export_rows)} exported, "
                f"{errors} error(s)"
            )

            return file_bytes

        except Exception as e:
            _logger.exception("Export engine fatal error: %s", e)
            op._append_log(f"Fatal error: {e}", level='error')
            op.write({
                'state': 'error',
                'date_end': fields.Datetime.now(),
            })
            raise

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _read_record(self, record, field_names, export_labels):
        """Read a single record and apply export transforms.

        Args:
            record: Odoo record.
            field_names (list[str]): Odoo field names to read.
            export_labels (list[str]): Corresponding export column names.

        Returns:
            dict: Row keyed by export labels.
        """
        row = {}
        for fname, label, mapping in zip(
            field_names, export_labels, self.mappings,
        ):
            value = record[fname]

            # Handle relational fields
            if hasattr(value, 'id'):
                # Many2one -> use display_name
                value = value.display_name or ''
            elif hasattr(value, 'ids'):
                # Many2many / One2many -> comma separated display names
                value = ', '.join(
                    r.display_name or str(r.id) for r in value
                )

            # Apply export format string if present
            export_format = mapping.get('export_format')
            if export_format and value is not None and value != '':
                try:
                    value = export_format.format(value)
                except (ValueError, TypeError, IndexError):
                    value = str(value)
            elif value is not None:
                value = str(value)
            else:
                value = ''

            row[label] = value

        return row

    def _get_extension(self):
        """Return the file extension for the current format."""
        extensions = self.adapter.FILE_EXTENSIONS
        if extensions:
            return extensions[0]
        return '.dat'

# Part of Navigare Migrate. See LICENSE file for full copyright and licensing details.
# Copyright 2025 Navigare Space Ltd
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).

import base64
import csv
import io
import json
import logging
from datetime import datetime

from odoo import _, fields
from odoo.exceptions import UserError

from . import adapter_registry
from .transform import apply_transform
from .validator import RowValidator

_logger = logging.getLogger(__name__)


class ImportEngine:
    """Orchestrates the data import pipeline.

    Parses a source file through a format adapter, applies field mappings and
    transformations, validates rows, resolves relational fields, and writes
    records into the Odoo database in configurable batches.
    """

    def __init__(self, env, profile, operation):
        """Initialise the import engine.

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
        self.validator = RowValidator(self.mappings)
        self.relation_cache = {}  # (model, field, value) -> id
        self.model_name = profile.model_name
        self.batch_size = profile.batch_size or 500
        self.on_existing = profile.on_existing or 'update'
        self.use_external_ids = profile.use_external_ids
        self.external_id_prefix = profile.external_id_prefix or 'migrate_'
        self.match_fields = [f.name for f in profile.match_field_ids]
        self.format_options = profile._get_format_options()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self, file_data, dry_run=False):
        """Execute the full import pipeline.

        Args:
            file_data (bytes): Raw source file bytes.
            dry_run (bool): If True, validate and preview without committing.

        Returns:
            dict: ``{created, updated, skipped, errors, total}``
        """
        op = self.operation
        op.write({
            'state': 'running',
            'date_start': fields.Datetime.now(),
            'is_dry_run': dry_run,
        })
        op._append_log(f"Import started (dry_run={dry_run})")

        counts = {
            'created': 0,
            'updated': 0,
            'skipped': 0,
            'errors': 0,
            'total': 0,
        }
        error_rows = []

        try:
            # -- 1. Parse rows -------------------------------------------------
            raw_rows = list(self.adapter.parse(file_data, self.format_options))
            counts['total'] = len(raw_rows)
            op.write({'total_rows': counts['total']})
            op._append_log(f"Parsed {counts['total']} row(s) from source file")

            if not raw_rows:
                op.write({'state': 'done', 'date_end': fields.Datetime.now()})
                op._append_log("No rows to process")
                return counts

            # -- 2. Map, validate, resolve ------------------------------------
            prepared_rows = []
            self.validator.reset()

            for idx, raw_row in enumerate(raw_rows, start=1):
                try:
                    mapped = self._apply_mappings(raw_row)
                    errors = self._validate_row(mapped, idx)
                    if errors:
                        for err in errors:
                            error_rows.append(self._error_line_vals(
                                idx, err, raw_row,
                            ))
                        counts['errors'] += 1
                        continue

                    resolved = self._resolve_relations(mapped)
                    prepared_rows.append((idx, raw_row, resolved))

                except Exception as e:
                    _logger.debug("Row %d mapping error: %s", idx, e)
                    error_rows.append(self._error_line_vals(
                        idx, str(e), raw_row,
                    ))
                    counts['errors'] += 1

            op._append_log(
                f"Mapping complete: {len(prepared_rows)} valid, "
                f"{counts['errors']} errors"
            )

            # -- 3. Batch processing ------------------------------------------
            batches = [
                prepared_rows[i:i + self.batch_size]
                for i in range(0, len(prepared_rows), self.batch_size)
            ]

            for batch_num, batch in enumerate(batches, start=1):
                try:
                    batch_counts, batch_errors = self._process_batch(
                        batch, dry_run,
                    )
                    counts['created'] += batch_counts.get('created', 0)
                    counts['updated'] += batch_counts.get('updated', 0)
                    counts['skipped'] += batch_counts.get('skipped', 0)
                    counts['errors'] += batch_counts.get('errors', 0)
                    error_rows.extend(batch_errors)

                    processed = sum(
                        counts[k] for k in ('created', 'updated', 'skipped')
                    )
                    op.write({'processed_rows': processed + counts['errors']})

                except Exception as e:
                    _logger.exception("Batch %d failed: %s", batch_num, e)
                    op._append_log(
                        f"Batch {batch_num} failed: {e}", level='error',
                    )
                    # Retry row-by-row to isolate the failing record
                    for row_idx, raw_row, vals in batch:
                        try:
                            rc, re_ = self._process_single_row(
                                row_idx, raw_row, vals, dry_run,
                            )
                            counts['created'] += rc.get('created', 0)
                            counts['updated'] += rc.get('updated', 0)
                            counts['skipped'] += rc.get('skipped', 0)
                            counts['errors'] += rc.get('errors', 0)
                            error_rows.extend(re_)
                        except Exception as row_exc:
                            counts['errors'] += 1
                            error_rows.append(self._error_line_vals(
                                row_idx, str(row_exc), raw_row,
                            ))

        except Exception as e:
            _logger.exception("Import engine fatal error: %s", e)
            op._append_log(f"Fatal error: {e}", level='error')
            op.write({
                'state': 'error',
                'date_end': fields.Datetime.now(),
            })
            raise

        # -- 4. Create error lines & error file ----------------------------
        if error_rows:
            self.env['migrate.operation.line'].create(error_rows)
            self._generate_error_file(error_rows)

        # -- 5. Finalise operation -----------------------------------------
        state = 'done'
        if dry_run:
            state = 'dry_run'
        elif counts['errors'] and counts['created'] + counts['updated'] > 0:
            state = 'partial'
        elif counts['errors'] and counts['created'] + counts['updated'] == 0:
            state = 'error'

        op.write({
            'state': state,
            'date_end': fields.Datetime.now(),
            'created_count': counts['created'],
            'updated_count': counts['updated'],
            'skipped_count': counts['skipped'],
            'error_count': counts['errors'],
            'processed_rows': counts['total'],
            'can_rollback': self.use_external_ids and counts['created'] > 0,
        })
        op._append_log(
            f"Import finished: {counts['created']} created, "
            f"{counts['updated']} updated, {counts['skipped']} skipped, "
            f"{counts['errors']} errors"
        )

        return counts

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _apply_mappings(self, raw_row):
        """Map and transform a raw source row to Odoo field values.

        Args:
            raw_row (dict): Raw row from adapter.

        Returns:
            dict: Mapped values keyed by Odoo field name.
        """
        result = {}
        for mapping in self.mappings:
            field_name = mapping.get('field_name')
            if not field_name:
                continue
            source_col = mapping.get('source_column', '')
            value = raw_row.get(source_col)
            try:
                value = apply_transform(value, mapping, raw_row)
            except Exception as e:
                raise ValueError(
                    f"Transform error on column '{source_col}' -> "
                    f"field '{field_name}': {e}"
                ) from e
            result[field_name] = value
        return result

    def _validate_row(self, mapped_row, row_number):
        """Validate a mapped row and return error messages."""
        return self.validator.validate(mapped_row, row_number)

    def _resolve_relations(self, mapped_row):
        """Resolve Many2one and Many2many values to record IDs.

        Uses a cache to avoid repeated lookups.

        Args:
            mapped_row (dict): Mapped values.

        Returns:
            dict: Values with relational fields resolved to IDs.
        """
        result = dict(mapped_row)
        for mapping in self.mappings:
            field_name = mapping.get('field_name')
            field_type = mapping.get('field_type')
            if not field_name or field_name not in result:
                continue

            value = result[field_name]
            if value is None or (isinstance(value, str) and not value.strip()):
                if field_type in ('many2one',):
                    result[field_name] = False
                elif field_type in ('many2many',):
                    result[field_name] = [(5, 0, 0)]
                continue

            relation = mapping.get('field_relation')
            match_field = mapping.get('relation_match_field', 'name')

            if field_type == 'many2one' and relation:
                result[field_name] = self._resolve_many2one(
                    relation, match_field, value,
                )

            elif field_type == 'many2many' and relation:
                result[field_name] = self._resolve_many2many(
                    relation, match_field, value,
                )

        return result

    def _resolve_many2one(self, model_name, match_field, value):
        """Resolve a single Many2one value to a record ID."""
        value_str = str(value).strip()
        cache_key = (model_name, match_field, value_str)
        if cache_key in self.relation_cache:
            return self.relation_cache[cache_key]

        try:
            rec = self.env[model_name].search(
                [(match_field, '=', value_str)], limit=1,
            )
            rec_id = rec.id if rec else False
        except Exception:
            rec_id = False

        self.relation_cache[cache_key] = rec_id
        if not rec_id:
            _logger.debug(
                "Many2one lookup failed: %s.%s = %r",
                model_name, match_field, value_str,
            )
        return rec_id

    def _resolve_many2many(self, model_name, match_field, value):
        """Resolve comma-separated values to Many2many command."""
        if isinstance(value, (list, tuple)):
            parts = [str(v).strip() for v in value]
        else:
            parts = [v.strip() for v in str(value).split(',') if v.strip()]

        ids = []
        for part in parts:
            rec_id = self._resolve_many2one(model_name, match_field, part)
            if rec_id:
                ids.append(rec_id)

        return [(6, 0, ids)] if ids else [(5, 0, 0)]

    def _process_batch(self, batch, dry_run):
        """Process a batch of prepared rows within a savepoint.

        Args:
            batch: List of ``(row_idx, raw_row, vals)`` tuples.
            dry_run (bool): Rollback savepoint if True.

        Returns:
            tuple: (counts_dict, error_line_vals_list)
        """
        counts = {'created': 0, 'updated': 0, 'skipped': 0, 'errors': 0}
        error_rows = []
        cr = self.env.cr

        with cr.savepoint() as sp:
            for row_idx, raw_row, vals in batch:
                try:
                    action = self._write_record(vals)
                    if action:
                        counts[action] = counts.get(action, 0) + 1
                except Exception as e:
                    counts['errors'] += 1
                    error_rows.append(self._error_line_vals(
                        row_idx, str(e), raw_row,
                    ))

            if dry_run:
                sp.rollback()

        return counts, error_rows

    def _process_single_row(self, row_idx, raw_row, vals, dry_run):
        """Process a single row in its own savepoint (retry fallback)."""
        counts = {'created': 0, 'updated': 0, 'skipped': 0, 'errors': 0}
        error_rows = []
        cr = self.env.cr

        try:
            with cr.savepoint() as sp:
                action = self._write_record(vals)
                if action:
                    counts[action] = counts.get(action, 0) + 1
                if dry_run:
                    sp.rollback()
        except Exception as e:
            counts['errors'] += 1
            error_rows.append(self._error_line_vals(
                row_idx, str(e), raw_row,
            ))

        return counts, error_rows

    def _write_record(self, vals):
        """Create or update a single record.

        Returns:
            str: 'created', 'updated', or 'skipped'.
        """
        Model = self.env[self.model_name]

        # Try to find existing record
        existing = self._find_existing(self.model_name, vals)
        if existing:
            if self.on_existing == 'skip':
                return 'skipped'
            elif self.on_existing == 'error':
                raise UserError(
                    _("Record already exists: %s", existing.display_name)
                )
            elif self.on_existing == 'update':
                # Filter out empty values to avoid overwriting with blanks
                update_vals = {
                    k: v for k, v in vals.items()
                    if v is not None and v is not False
                }
                if update_vals:
                    existing.write(update_vals)
                return 'updated'
        else:
            # Create new record
            record = Model.create(vals)

            # Create external ID for rollback support
            if self.use_external_ids and record:
                xid = f'{self.external_id_prefix}{self.model_name.replace(".", "_")}_{record.id}'
                self.env['ir.model.data'].create({
                    'name': xid,
                    'module': '__migrate__',
                    'model': self.model_name,
                    'res_id': record.id,
                    'noupdate': True,
                })
            return 'created'

    def _find_existing(self, model_name, vals):
        """Search for an existing record using match fields or external ID.

        Args:
            model_name (str): Odoo model technical name.
            vals (dict): Record values to match against.

        Returns:
            recordset: Matching record or empty recordset.
        """
        Model = self.env[model_name]

        # Match by configured match fields
        if self.match_fields:
            domain = []
            for field_name in self.match_fields:
                if field_name in vals and vals[field_name]:
                    domain.append((field_name, '=', vals[field_name]))
            if domain:
                return Model.search(domain, limit=1)

        return Model.browse()

    def _error_line_vals(self, row_number, message, raw_row):
        """Build vals dict for a ``migrate.operation.line`` error record."""
        source_data = ''
        try:
            source_data = json.dumps(raw_row, ensure_ascii=False, default=str)
        except Exception:
            source_data = str(raw_row)

        return {
            'operation_id': self.operation.id,
            'row_number': row_number,
            'state': 'error',
            'error_message': str(message),
            'source_data': source_data,
        }

    def _generate_error_file(self, error_rows):
        """Generate a CSV error file and attach it to the operation."""
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Row', 'Error', 'Source Data'])
        for line_vals in error_rows:
            writer.writerow([
                line_vals.get('row_number', ''),
                line_vals.get('error_message', ''),
                line_vals.get('source_data', ''),
            ])

        file_bytes = output.getvalue().encode('utf-8')
        filename = f'{self.operation.name}_errors.csv'
        self.operation.write({
            'error_file': base64.b64encode(file_bytes),
            'error_filename': filename,
        })

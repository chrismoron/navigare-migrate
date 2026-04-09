# Part of Navigare Migrate. See LICENSE file for full copyright and licensing details.
# Copyright 2025 Navigare Space Ltd
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).

import base64
import logging
from difflib import SequenceMatcher

from odoo import http, fields
from odoo.http import request

from ..engine import adapter_registry

_logger = logging.getLogger(__name__)


class MigrateController(http.Controller):

    @http.route('/navigare_migrate/dashboard_data', type='json', auth='user')
    def dashboard_data(self):
        """Return summary statistics for the migration dashboard."""
        env = request.env
        Operation = env['migrate.operation']
        Schedule = env['migrate.schedule']

        today_start = fields.Datetime.to_string(
            fields.Datetime.start_of(fields.Datetime.now(), 'day')
        )

        # Operations today
        operations_today = Operation.search_count([
            ('date_start', '>=', today_start),
        ])

        # Success rate (last 30 days)
        thirty_days_ago = fields.Datetime.subtract(fields.Datetime.now(), days=30)
        recent_ops = Operation.search([
            ('date_start', '>=', fields.Datetime.to_string(thirty_days_ago)),
            ('state', 'in', ('done', 'partial', 'error')),
        ])
        total_recent = len(recent_ops)
        successful = len(recent_ops.filtered(lambda o: o.state == 'done'))
        success_rate = round(
            (successful / total_recent * 100) if total_recent else 0, 1
        )

        # Total records processed (all time)
        all_ops = Operation.search([('state', 'in', ('done', 'partial'))])
        total_processed = sum(all_ops.mapped('created_count')) + sum(
            all_ops.mapped('updated_count')
        )

        # Active schedules
        active_schedules = Schedule.search_count([
            ('active', '=', True),
            ('cron_id', '!=', False),
        ])

        # Recent operations (last 10)
        recent_operations = []
        for op in Operation.search([], limit=10, order='id desc'):
            recent_operations.append({
                'id': op.id,
                'name': op.name,
                'profile_name': op.profile_id.name,
                'direction': op.direction,
                'state': op.state,
                'total_rows': op.total_rows,
                'created_count': op.created_count,
                'error_count': op.error_count,
                'date_start': fields.Datetime.to_string(op.date_start)
                if op.date_start else '',
                'duration': op.duration,
                'user_name': op.user_id.name,
            })

        # Daily stats (last 7 days)
        daily_stats = []
        for i in range(7):
            day = fields.Datetime.subtract(fields.Datetime.now(), days=i)
            day_start = fields.Datetime.start_of(day, 'day')
            day_end = fields.Datetime.end_of(day, 'day')
            day_ops = Operation.search([
                ('date_start', '>=', fields.Datetime.to_string(day_start)),
                ('date_start', '<=', fields.Datetime.to_string(day_end)),
            ])
            daily_stats.append({
                'date': day_start.strftime('%Y-%m-%d'),
                'count': len(day_ops),
                'created': sum(day_ops.mapped('created_count')),
                'errors': sum(day_ops.mapped('error_count')),
            })

        return {
            'operations_today': operations_today,
            'success_rate': success_rate,
            'total_processed': total_processed,
            'active_schedules': active_schedules,
            'recent_operations': recent_operations,
            'daily_stats': list(reversed(daily_stats)),
        }

    @http.route('/navigare_migrate/preview_file', type='json', auth='user')
    def preview_file(self, file_data_b64, format_type, options=None):
        """Decode a base64 file and return preview data.

        Args:
            file_data_b64 (str): Base64-encoded file content.
            format_type (str): Format key (csv, xlsx, etc.).
            options (dict|None): Format-specific options.

        Returns:
            dict: ``{columns, rows, total_rows}``
        """
        if options is None:
            options = {}

        file_bytes = base64.b64decode(file_data_b64)
        adapter = adapter_registry.get_adapter(format_type)
        columns, rows = adapter.preview(file_bytes, options, max_rows=20)

        # Count total rows (parse all)
        total_rows = sum(1 for _ in adapter.parse(file_bytes, options))

        return {
            'columns': columns,
            'rows': rows,
            'total_rows': total_rows,
        }

    @http.route('/navigare_migrate/auto_map', type='json', auth='user')
    def auto_map(self, model_name, columns):
        """Match file column names to Odoo model fields.

        Uses exact name matching, label matching, and fuzzy string matching.

        Args:
            model_name (str): Technical model name.
            columns (list[str]): Column names from the source file.

        Returns:
            list[dict]: ``{source, field_name, field_label, confidence}``
        """
        env = request.env
        model_fields = env['ir.model.fields'].search([
            ('model', '=', model_name),
            ('store', '=', True),
        ])

        field_by_name = {}
        field_by_label = {}
        for f in model_fields:
            field_by_name[f.name] = f
            label = (f.field_description or '').strip().lower()
            if label:
                field_by_label[label] = f

        results = []
        for col in columns:
            col_clean = col.strip()
            col_norm = col_clean.lower().replace(' ', '_').replace('-', '_')
            match = None
            confidence = 0.0

            # Exact name match
            if col_norm in field_by_name:
                match = field_by_name[col_norm]
                confidence = 1.0

            # Label match
            if not match and col_clean.lower() in field_by_label:
                match = field_by_label[col_clean.lower()]
                confidence = 0.95

            # Fuzzy match
            if not match:
                best_ratio = 0.0
                for fname, frec in field_by_name.items():
                    ratio = SequenceMatcher(
                        None, col_norm, fname
                    ).ratio()
                    if ratio > best_ratio:
                        best_ratio = ratio
                        if ratio >= 0.7:
                            match = frec
                            confidence = round(ratio, 2)

                # Also try against labels
                for flabel, frec in field_by_label.items():
                    ratio = SequenceMatcher(
                        None, col_clean.lower(), flabel
                    ).ratio()
                    if ratio > confidence and ratio >= 0.7:
                        match = frec
                        confidence = round(ratio, 2)

            results.append({
                'source': col_clean,
                'field_name': match.name if match else None,
                'field_label': match.field_description if match else None,
                'confidence': confidence,
            })

        return results

    @http.route('/navigare_migrate/model_fields', type='json', auth='user')
    def model_fields(self, model_name):
        """Return fields list for a given model.

        Args:
            model_name (str): Technical model name.

        Returns:
            list[dict]: ``{name, label, type, relation, required}``
        """
        env = request.env
        ir_fields = env['ir.model.fields'].search([
            ('model', '=', model_name),
            ('store', '=', True),
        ], order='name')

        return [
            {
                'name': f.name,
                'label': f.field_description or f.name,
                'type': f.ttype,
                'relation': f.relation or '',
                'required': f.required,
            }
            for f in ir_fields
        ]

    @http.route(
        '/navigare_migrate/operation_progress', type='json', auth='user',
    )
    def operation_progress(self, operation_id):
        """Return current progress of an operation.

        Args:
            operation_id (int): Operation record ID.

        Returns:
            dict: ``{state, progress, processed, total, created, updated,
                      errors, log_tail}``
        """
        op = request.env['migrate.operation'].browse(int(operation_id))
        if not op.exists():
            return {'error': 'Operation not found'}

        log_text = op.log_text or ''
        log_lines = log_text.strip().split('\n')
        log_tail = '\n'.join(log_lines[-20:]) if log_lines else ''

        return {
            'state': op.state,
            'progress': op.progress,
            'processed': op.processed_rows,
            'total': op.total_rows,
            'created': op.created_count,
            'updated': op.updated_count,
            'errors': op.error_count,
            'log_tail': log_tail,
        }

    @http.route(
        '/navigare_migrate/available_formats', type='json', auth='user',
    )
    def available_formats(self):
        """Return list of registered format adapters.

        Returns:
            list[dict]: Each dict has keys: key, name, extensions, available,
                error.
        """
        return adapter_registry.get_available_formats()

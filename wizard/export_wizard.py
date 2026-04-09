# Part of Navigare Migrate. See LICENSE file for full copyright and licensing details.
# Copyright 2025 Navigare Space Ltd
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).

import ast
import base64
import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError

from ..engine.export_engine import ExportEngine

_logger = logging.getLogger(__name__)


class MigrateExportWizard(models.TransientModel):
    _name = 'migrate.export.wizard'
    _description = 'Export Wizard'

    # ------------------------------------------------------------------
    # Fields
    # ------------------------------------------------------------------
    profile_id = fields.Many2one(
        'migrate.profile',
        string='Profile',
        required=True,
        domain=[('direction', '=', 'export')],
    )
    model_id = fields.Many2one(
        related='profile_id.model_id',
        string='Model',
        readonly=True,
    )
    format_type = fields.Selection(
        related='profile_id.format_type',
        string='Format',
        readonly=True,
    )

    domain_text = fields.Text(
        string='Filter Domain',
        default='[]',
        help='Odoo search domain in Python syntax, e.g. [(\'active\', \'=\', True)].',
    )
    date_from = fields.Date(
        string='Date From',
        help='Filter records created on or after this date.',
    )
    date_to = fields.Date(
        string='Date To',
        help='Filter records created on or before this date.',
    )
    limit = fields.Integer(
        string='Limit',
        default=0,
        help='Maximum number of records to export (0 = no limit).',
    )

    result_file = fields.Binary(
        string='Result File',
        readonly=True,
    )
    result_filename = fields.Char(
        string='Result Filename',
        readonly=True,
    )
    operation_id = fields.Many2one(
        'migrate.operation',
        string='Operation',
        readonly=True,
    )
    record_count = fields.Integer(
        string='Records Exported',
        readonly=True,
    )

    state = fields.Selection(
        [
            ('config', 'Configure'),
            ('done', 'Done'),
        ],
        string='State',
        default='config',
        required=True,
    )

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def action_export(self):
        """Run the ExportEngine and advance to done state."""
        self.ensure_one()
        profile = self.profile_id
        if not profile:
            raise UserError(_('Please select an export profile.'))

        # Parse domain
        domain = []
        if self.domain_text and self.domain_text.strip() != '[]':
            try:
                domain = ast.literal_eval(self.domain_text)
            except (ValueError, SyntaxError) as e:
                raise UserError(
                    _('Invalid domain syntax: %s', str(e))
                )

        # Add date filters
        if self.date_from:
            domain.append(('create_date', '>=', fields.Datetime.to_string(
                fields.Datetime.start_of(
                    fields.Datetime.to_datetime(self.date_from), 'day',
                )
            )))
        if self.date_to:
            domain.append(('create_date', '<=', fields.Datetime.to_string(
                fields.Datetime.end_of(
                    fields.Datetime.to_datetime(self.date_to), 'day',
                )
            )))

        # Apply limit
        if self.limit and self.limit > 0:
            records = self.env[profile.model_name].search(
                domain, limit=self.limit,
            )
            record_ids = records.ids
        else:
            record_ids = None

        # Create operation
        operation = self.env['migrate.operation'].create({
            'profile_id': profile.id,
        })

        try:
            engine = ExportEngine(self.env, profile, operation)
            file_bytes = engine.run(
                domain=domain if record_ids is None else None,
                record_ids=record_ids,
            )
        except Exception as e:
            _logger.exception("Export wizard error: %s", e)
            operation.write({
                'state': 'error',
                'date_end': fields.Datetime.now(),
            })
            operation._append_log(f'Fatal error: {e}', level='error')
            raise UserError(_('Export failed: %s', str(e)))

        # Build filename from operation
        ext_map = {
            'csv': '.csv', 'xlsx': '.xlsx', 'xml': '.xml',
            'json': '.json', 'fixed': '.txt', 'ods': '.ods',
            'sqlite': '.sqlite3',
        }
        ext = ext_map.get(profile.format_type, '.dat')
        filename = f'{operation.name}_export{ext}'

        self.write({
            'state': 'done',
            'operation_id': operation.id,
            'result_file': base64.b64encode(file_bytes) if file_bytes else False,
            'result_filename': filename,
            'record_count': operation.created_count,
        })

        return self._reopen_wizard()

    def action_open_operation(self):
        """Open the linked operation record."""
        self.ensure_one()
        if not self.operation_id:
            raise UserError(_('No operation to open.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Operation'),
            'res_model': 'migrate.operation',
            'res_id': self.operation_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _reopen_wizard(self):
        """Return action to reopen this wizard at current state."""
        return {
            'type': 'ir.actions.act_window',
            'name': _('Export Data'),
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

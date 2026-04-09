# Part of Navigare Migrate. See LICENSE file for full copyright and licensing details.
# Copyright 2025 Navigare Space Ltd
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).

import base64
import csv
import io
import logging
from datetime import datetime

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

OPERATION_STATES = [
    ('draft', 'Draft'),
    ('validating', 'Validating'),
    ('running', 'Running'),
    ('done', 'Done'),
    ('partial', 'Partial'),
    ('error', 'Error'),
    ('cancelled', 'Cancelled'),
    ('dry_run', 'Dry Run'),
]


class MigrateOperation(models.Model):
    _name = 'migrate.operation'
    _description = 'Migration Operation'
    _inherit = ['mail.thread']
    _order = 'id desc'

    # ------------------------------------------------------------------
    # Identification
    # ------------------------------------------------------------------
    name = fields.Char(
        string='Reference',
        readonly=True,
        default='New',
        copy=False,
    )
    profile_id = fields.Many2one(
        'migrate.profile',
        string='Profile',
        required=True,
        readonly=True,
        ondelete='restrict',
    )
    direction = fields.Selection(
        related='profile_id.direction',
        string='Direction',
        store=True,
        readonly=True,
    )
    model_name = fields.Char(
        related='profile_id.model_name',
        string='Model',
        store=True,
        readonly=True,
    )
    format_type = fields.Selection(
        related='profile_id.format_type',
        string='Format',
        store=True,
        readonly=True,
    )

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------
    state = fields.Selection(
        OPERATION_STATES,
        string='Status',
        default='draft',
        tracking=True,
        readonly=True,
        copy=False,
    )

    # ------------------------------------------------------------------
    # Files
    # ------------------------------------------------------------------
    source_file = fields.Binary(
        string='Source File',
        attachment=True,
    )
    source_filename = fields.Char(string='Source Filename')
    result_file = fields.Binary(
        string='Result File',
        attachment=True,
        readonly=True,
    )
    result_filename = fields.Char(string='Result Filename', readonly=True)
    error_file = fields.Binary(
        string='Error File',
        attachment=True,
        readonly=True,
    )
    error_filename = fields.Char(string='Error Filename', readonly=True)

    # ------------------------------------------------------------------
    # Counters
    # ------------------------------------------------------------------
    total_rows = fields.Integer(string='Total Rows', readonly=True)
    processed_rows = fields.Integer(string='Processed Rows', readonly=True)
    created_count = fields.Integer(string='Created', readonly=True)
    updated_count = fields.Integer(string='Updated', readonly=True)
    skipped_count = fields.Integer(string='Skipped', readonly=True)
    error_count = fields.Integer(string='Errors', readonly=True)

    # ------------------------------------------------------------------
    # Progress & timing
    # ------------------------------------------------------------------
    progress = fields.Float(
        string='Progress (%)',
        compute='_compute_progress',
        store=True,
        readonly=True,
    )
    date_start = fields.Datetime(string='Started', readonly=True)
    date_end = fields.Datetime(string='Finished', readonly=True)
    duration = fields.Float(
        string='Duration (s)',
        compute='_compute_duration',
        store=True,
        readonly=True,
    )

    # ------------------------------------------------------------------
    # Options & flags
    # ------------------------------------------------------------------
    is_dry_run = fields.Boolean(
        string='Dry Run',
        readonly=True,
    )
    can_rollback = fields.Boolean(
        string='Can Rollback',
        readonly=True,
    )
    rollback_done = fields.Boolean(
        string='Rollback Done',
        readonly=True,
    )

    # ------------------------------------------------------------------
    # Relations
    # ------------------------------------------------------------------
    line_ids = fields.One2many(
        'migrate.operation.line',
        'operation_id',
        string='Lines',
    )

    # ------------------------------------------------------------------
    # Other
    # ------------------------------------------------------------------
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        readonly=True,
    )
    user_id = fields.Many2one(
        'res.users',
        string='Executed By',
        default=lambda self: self.env.user,
        readonly=True,
    )
    log_text = fields.Text(
        string='Execution Log',
        readonly=True,
    )

    # ------------------------------------------------------------------
    # Compute methods
    # ------------------------------------------------------------------
    @api.depends('total_rows', 'processed_rows')
    def _compute_progress(self):
        for op in self:
            if op.total_rows:
                op.progress = min(
                    (op.processed_rows / op.total_rows) * 100.0,
                    100.0,
                )
            else:
                op.progress = 0.0

    @api.depends('date_start', 'date_end')
    def _compute_duration(self):
        for op in self:
            if op.date_start and op.date_end:
                delta = op.date_end - op.date_start
                op.duration = delta.total_seconds()
            else:
                op.duration = 0.0

    # ------------------------------------------------------------------
    # CRUD overrides
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'migrate.operation',
                ) or 'New'
        return super().create(vals_list)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def action_rollback(self):
        """Rollback created/updated records using stored external IDs."""
        self.ensure_one()
        if not self.can_rollback:
            raise UserError(_('This operation cannot be rolled back.'))
        if self.rollback_done:
            raise UserError(_('Rollback has already been performed.'))

        created_lines = self.line_ids.filtered(
            lambda l: l.state == 'created' and l.record_ref
        )
        if not created_lines:
            raise UserError(_('No created records to rollback.'))

        prefix = self.profile_id.external_id_prefix or 'migrate_'
        module = '__migrate__'
        deleted = 0
        for line in created_lines:
            xml_id = f'{module}.{prefix}{line.record_ref}'
            rec = self.env.ref(xml_id, raise_if_not_found=False)
            if rec:
                try:
                    rec.unlink()
                    deleted += 1
                except Exception as e:
                    self._append_log(
                        f'Rollback failed for {xml_id}: {e}', level='error',
                    )

        self.write({
            'rollback_done': True,
        })
        self._append_log(f'Rollback complete: {deleted} record(s) deleted.')
        return True

    def action_retry_errors(self):
        """Re-queue error lines for another processing attempt."""
        self.ensure_one()
        if self.state not in ('partial', 'error'):
            raise UserError(_('Only operations in error or partial state can be retried.'))

        error_lines = self.line_ids.filtered(lambda l: l.state == 'error')
        if not error_lines:
            raise UserError(_('No error lines to retry.'))

        # Reset counters for the lines that will be retried
        self._append_log(
            f'Retry requested for {len(error_lines)} error line(s).',
        )
        return True

    def action_download_errors(self):
        """Generate a CSV file containing only the error rows."""
        self.ensure_one()
        error_lines = self.line_ids.filtered(lambda l: l.state == 'error')
        if not error_lines:
            raise UserError(_('No error lines to download.'))

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Row', 'Error', 'Source Data'])
        for line in error_lines.sorted('row_number'):
            writer.writerow([
                line.row_number,
                line.error_message or '',
                line.source_data or '',
            ])

        file_data = output.getvalue().encode('utf-8')
        filename = f'{self.name}_errors.csv'

        self.write({
            'error_file': base64.b64encode(file_data),
            'error_filename': filename,
        })
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{self._name}/{self.id}/error_file/{filename}?download=true',
            'target': 'self',
        }

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # Cron
    # ------------------------------------------------------------------
    @api.model
    def _cron_cleanup(self):
        """Delete operations older than 90 days.

        Called by the scheduled action ``navigare_migrate.cron_cleanup``.
        """
        cutoff = fields.Datetime.subtract(fields.Datetime.now(), days=90)
        old_ops = self.search([
            ('date_start', '<', cutoff),
            ('state', 'in', ('done', 'error', 'cancelled', 'dry_run')),
        ])
        if old_ops:
            count = len(old_ops)
            old_ops.unlink()
            _logger.info('Cron cleanup: deleted %d operation(s) older than 90 days.', count)

    def _append_log(self, message, level='info'):
        """Append a timestamped message to the execution log.

        Args:
            message (str): Log message.
            level (str): Log level ('info', 'warning', 'error').
        """
        self.ensure_one()
        timestamp = fields.Datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        prefix = level.upper() if level != 'info' else 'INFO'
        entry = f'[{timestamp}] {prefix}: {message}\n'
        current = self.log_text or ''
        self.write({'log_text': current + entry})

        log_func = getattr(_logger, level, _logger.info)
        log_func('Operation %s: %s', self.name, message)

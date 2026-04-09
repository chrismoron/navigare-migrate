# Part of Navigare Migrate. See LICENSE file for full copyright and licensing details.
# Copyright 2025 Navigare Space Ltd
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).

import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

SOURCE_TYPES = [
    ('file_path', 'File Path'),
    ('attachment', 'Attachment'),
    ('url', 'URL'),
    ('sftp', 'SFTP'),
]

INTERVAL_TYPES = [
    ('minutes', 'Minutes'),
    ('hours', 'Hours'),
    ('days', 'Days'),
    ('weeks', 'Weeks'),
    ('months', 'Months'),
]


class MigrateSchedule(models.Model):
    _name = 'migrate.schedule'
    _description = 'Scheduled Migration'
    _order = 'name'

    # ------------------------------------------------------------------
    # Core
    # ------------------------------------------------------------------
    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    profile_id = fields.Many2one(
        'migrate.profile',
        string='Profile',
        required=True,
        ondelete='cascade',
    )
    cron_id = fields.Many2one(
        'ir.cron',
        string='Scheduled Action',
        readonly=True,
        ondelete='set null',
    )

    # ------------------------------------------------------------------
    # Source configuration
    # ------------------------------------------------------------------
    source_type = fields.Selection(
        SOURCE_TYPES,
        string='Source Type',
        default='attachment',
    )
    source_path = fields.Char(
        string='Source Path / URL',
        help='File system path, HTTP URL, or SFTP URI depending on source type.',
    )
    source_attachment = fields.Binary(
        string='Source Attachment',
        attachment=True,
    )
    source_attachment_name = fields.Char(
        string='Attachment Filename',
    )

    # ------------------------------------------------------------------
    # Export destination
    # ------------------------------------------------------------------
    export_path = fields.Char(
        string='Export Path',
        help='File system path or directory for export output.',
    )
    export_email = fields.Char(
        string='Export Email',
        help='E-mail address to send the export file to.',
    )

    # ------------------------------------------------------------------
    # Scheduling
    # ------------------------------------------------------------------
    interval_number = fields.Integer(
        string='Interval',
        default=1,
    )
    interval_type = fields.Selection(
        INTERVAL_TYPES,
        string='Interval Unit',
        default='days',
    )
    next_run = fields.Datetime(
        string='Next Run',
        related='cron_id.nextcall',
        readonly=True,
    )
    last_run = fields.Datetime(
        string='Last Run',
        readonly=True,
    )
    last_state = fields.Char(
        string='Last State',
        readonly=True,
    )

    # ------------------------------------------------------------------
    # Retry & notification
    # ------------------------------------------------------------------
    max_retries = fields.Integer(
        string='Max Retries',
        default=0,
    )
    notify_on_error = fields.Boolean(
        string='Notify on Error',
        default=True,
    )
    notify_user_ids = fields.Many2many(
        'res.users',
        string='Notify Users',
        help='Users to notify when an error occurs.',
    )

    # ------------------------------------------------------------------
    # Other
    # ------------------------------------------------------------------
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
    )

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def action_activate(self):
        """Create (or reactivate) an ir.cron record for this schedule."""
        self.ensure_one()
        if self.cron_id:
            self.cron_id.write({'active': True})
            return True

        cron = self.env['ir.cron'].sudo().create({
            'name': _('Migrate: %s', self.name),
            'model_id': self.env['ir.model']._get_id(self._name),
            'state': 'code',
            'code': f'model._cron_execute({self.id})',
            'interval_number': self.interval_number,
            'interval_type': self.interval_type,
            'numbercall': -1,
            'active': True,
            'user_id': self.env.user.id,
        })
        self.write({'cron_id': cron.id})
        return True

    def action_deactivate(self):
        """Deactivate the linked cron job."""
        self.ensure_one()
        if self.cron_id:
            self.cron_id.write({'active': False})
        return True

    def action_run_now(self):
        """Execute the scheduled migration immediately."""
        self.ensure_one()
        self._cron_execute(self.id)
        return True

    # ------------------------------------------------------------------
    # Cron entry point
    # ------------------------------------------------------------------
    @api.model
    def _cron_execute(self, schedule_id):
        """Entry point called by ir.cron.

        Creates a new :class:`migrate.operation` linked to the schedule's
        profile and triggers the import or export.

        Args:
            schedule_id (int): ID of the ``migrate.schedule`` record.
        """
        schedule = self.browse(schedule_id).exists()
        if not schedule:
            _logger.warning('Schedule %s no longer exists, skipping.', schedule_id)
            return

        profile = schedule.profile_id
        retries_left = schedule.max_retries or 0
        attempt = 0
        last_error = None

        while attempt <= retries_left:
            attempt += 1
            try:
                op_vals = {
                    'profile_id': profile.id,
                }
                # Attach source file if available
                if schedule.source_type == 'attachment' and schedule.source_attachment:
                    op_vals['source_file'] = schedule.source_attachment
                    op_vals['source_filename'] = schedule.source_attachment_name

                operation = self.env['migrate.operation'].create(op_vals)
                _logger.info(
                    'Schedule %s: created operation %s (attempt %d)',
                    schedule.name, operation.name, attempt,
                )

                schedule.write({
                    'last_run': fields.Datetime.now(),
                    'last_state': 'done',
                })
                return

            except Exception as e:
                last_error = str(e)
                _logger.exception(
                    'Schedule %s attempt %d failed: %s',
                    schedule.name, attempt, e,
                )

        # All attempts exhausted
        schedule.write({
            'last_run': fields.Datetime.now(),
            'last_state': 'error',
        })

        if schedule.notify_on_error and schedule.notify_user_ids:
            schedule._send_error_notification(last_error)

    def _send_error_notification(self, error_message):
        """Send an internal notification to the configured users."""
        self.ensure_one()
        body = _(
            'Scheduled migration "%(name)s" failed.\n\nError: %(error)s',
            name=self.name,
            error=error_message or _('Unknown error'),
        )
        for user in self.notify_user_ids:
            user.partner_id.message_post(
                body=body,
                message_type='notification',
                subtype_xmlid='mail.mt_note',
            )

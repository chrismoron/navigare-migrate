# Part of Navigare Migrate. See LICENSE file for full copyright and licensing details.
# Copyright 2025 Navigare Space Ltd
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).

import base64
import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError

from ..engine import adapter_registry
from ..engine.import_engine import ImportEngine

_logger = logging.getLogger(__name__)


class MigrateImportWizard(models.TransientModel):
    _name = 'migrate.import.wizard'
    _description = 'Import Wizard'

    # ------------------------------------------------------------------
    # Fields
    # ------------------------------------------------------------------
    profile_id = fields.Many2one(
        'migrate.profile',
        string='Profile',
        domain=[('direction', '=', 'import')],
    )
    create_new_profile = fields.Boolean(
        string='Create New Profile',
        default=False,
    )
    model_id = fields.Many2one(
        'ir.model',
        string='Target Model',
        domain=[('transient', '=', False)],
    )
    format_type = fields.Selection(
        [
            ('csv', 'CSV'),
            ('xlsx', 'Excel (.xlsx)'),
            ('xml', 'XML'),
            ('json', 'JSON'),
            ('fixed', 'Fixed-Width'),
            ('ods', 'ODS (LibreOffice)'),
            ('sqlite', 'SQLite'),
        ],
        string='File Format',
        default='csv',
    )

    file_data = fields.Binary(
        string='File',
        required=True,
    )
    file_name = fields.Char(string='Filename')

    preview_html = fields.Html(
        string='Preview',
        readonly=True,
        sanitize=False,
    )
    detected_columns = fields.Text(
        string='Detected Columns',
        readonly=True,
    )

    is_dry_run = fields.Boolean(
        string='Dry Run',
        default=False,
        help='Validate data without actually creating records.',
    )
    batch_size = fields.Integer(
        string='Batch Size',
        default=500,
    )

    operation_id = fields.Many2one(
        'migrate.operation',
        string='Operation',
        readonly=True,
    )
    result_html = fields.Html(
        string='Result',
        readonly=True,
        sanitize=False,
    )

    state = fields.Selection(
        [
            ('upload', 'Upload'),
            ('preview', 'Preview'),
            ('running', 'Running'),
            ('done', 'Done'),
        ],
        string='State',
        default='upload',
        required=True,
    )

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def action_upload(self):
        """Parse headers, generate preview, advance to preview state."""
        self.ensure_one()
        if not self.file_data:
            raise UserError(_('Please select a file to import.'))

        profile = self.profile_id
        if not profile:
            raise UserError(_('Please select an import profile.'))

        file_bytes = base64.b64decode(self.file_data)
        adapter = adapter_registry.get_adapter(profile.format_type)
        options = profile._get_format_options()

        try:
            headers, rows = adapter.preview(file_bytes, options, max_rows=20)
        except Exception as e:
            raise UserError(_('Error reading file: %s', str(e)))

        # Detect columns
        columns_text = '\n'.join(headers) if headers else ''

        # Build HTML preview table
        html_parts = ['<table class="table table-sm table-striped">']
        if headers:
            html_parts.append('<thead><tr>')
            for h in headers:
                html_parts.append(f'<th>{h}</th>')
            html_parts.append('</tr></thead>')
        html_parts.append('<tbody>')
        for row in rows[:20]:
            html_parts.append('<tr>')
            for cell in row:
                html_parts.append(f'<td>{cell}</td>')
            html_parts.append('</tr>')
        html_parts.append('</tbody></table>')

        self.write({
            'state': 'preview',
            'detected_columns': columns_text,
            'preview_html': ''.join(html_parts),
        })

        return self._reopen_wizard()

    def action_run(self):
        """Create operation, run ImportEngine, advance to done state."""
        self.ensure_one()
        profile = self.profile_id
        if not profile:
            raise UserError(_('No profile selected.'))
        if not self.file_data:
            raise UserError(_('No file to import.'))

        file_bytes = base64.b64decode(self.file_data)

        # Override batch size if specified
        if self.batch_size and self.batch_size != profile.batch_size:
            profile = profile.with_context(
                wizard_batch_size=self.batch_size,
            )

        # Create operation record
        operation = self.env['migrate.operation'].create({
            'profile_id': profile.id,
            'source_file': self.file_data,
            'source_filename': self.file_name,
        })

        self.write({'state': 'running'})

        try:
            engine = ImportEngine(self.env, profile, operation)
            if self.batch_size:
                engine.batch_size = self.batch_size
            counts = engine.run(file_bytes, dry_run=self.is_dry_run)
        except Exception as e:
            _logger.exception("Import wizard run error: %s", e)
            operation.write({
                'state': 'error',
                'date_end': fields.Datetime.now(),
            })
            operation._append_log(f'Fatal error: {e}', level='error')
            counts = {
                'created': 0, 'updated': 0, 'skipped': 0,
                'errors': 1, 'total': 0,
            }

        # Build result HTML
        result_html = self._build_result_html(counts)

        self.write({
            'state': 'done',
            'operation_id': operation.id,
            'result_html': result_html,
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
            'name': _('Import Data'),
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def _build_result_html(self, counts):
        """Build an HTML summary of import results."""
        dry = ' (DRY RUN)' if self.is_dry_run else ''
        return (
            f'<div class="alert alert-info">'
            f'<h4>Import Complete{dry}</h4>'
            f'<table class="table table-sm">'
            f'<tr><td><strong>Total rows</strong></td><td>{counts.get("total", 0)}</td></tr>'
            f'<tr><td><strong>Created</strong></td><td>{counts.get("created", 0)}</td></tr>'
            f'<tr><td><strong>Updated</strong></td><td>{counts.get("updated", 0)}</td></tr>'
            f'<tr><td><strong>Skipped</strong></td><td>{counts.get("skipped", 0)}</td></tr>'
            f'<tr><td><strong>Errors</strong></td><td>{counts.get("errors", 0)}</td></tr>'
            f'</table></div>'
        )

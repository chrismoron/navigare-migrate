# Part of Navigare Migrate. See LICENSE file for full copyright and licensing details.
# Copyright 2025 Navigare Space Ltd
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).

import json
import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

TEMPLATE_CATEGORIES = [
    ('erp_migration', 'ERP Migration'),
    ('data_sync', 'Data Synchronisation'),
    ('bulk_update', 'Bulk Update'),
    ('initial_setup', 'Initial Setup'),
    ('accounting', 'Accounting'),
    ('inventory', 'Inventory'),
    ('hr', 'Human Resources'),
]

TEMPLATE_DIRECTION = [
    ('import', 'Import'),
    ('export', 'Export'),
    ('both', 'Both'),
]

TEMPLATE_FORMAT = [
    ('csv', 'CSV'),
    ('xlsx', 'Excel (.xlsx)'),
    ('json', 'JSON'),
    ('xml', 'XML'),
    ('any', 'Any Format'),
]


class MigrateTemplate(models.Model):
    _name = 'migrate.template'
    _description = 'Migration Template'
    _order = 'sequence, name'

    name = fields.Char(
        required=True,
        translate=True,
    )
    sequence = fields.Integer(default=10)
    category = fields.Selection(
        TEMPLATE_CATEGORIES,
        string='Category',
        required=True,
    )
    description = fields.Text(
        translate=True,
    )
    icon = fields.Char(
        string='Icon',
        default='fa fa-exchange',
    )
    model_id = fields.Many2one(
        'ir.model',
        string='Target Model',
        required=True,
        ondelete='cascade',
    )
    direction = fields.Selection(
        TEMPLATE_DIRECTION,
        string='Direction',
        default='import',
    )
    format_type = fields.Selection(
        TEMPLATE_FORMAT,
        string='Format',
        default='csv',
    )
    mapping_data = fields.Text(
        string='Mapping Data',
        help='JSON array of field mapping definitions.',
    )
    profile_defaults = fields.Text(
        string='Profile Defaults',
        help='JSON object with default profile field values.',
    )
    sample_file = fields.Binary(
        string='Sample File',
        attachment=True,
    )
    sample_filename = fields.Char(
        string='Sample Filename',
    )

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def action_create_profile(self):
        """Create a new migrate.profile pre-configured from this template."""
        self.ensure_one()

        direction = self.direction if self.direction != 'both' else 'import'
        format_type = self.format_type if self.format_type != 'any' else 'csv'

        profile_vals = {
            'name': _('%s (from template)', self.name),
            'model_id': self.model_id.id,
            'direction': direction,
            'format_type': format_type,
            'template_id': self.id,
        }

        # Merge profile defaults from JSON
        if self.profile_defaults:
            try:
                defaults = json.loads(self.profile_defaults)
                if isinstance(defaults, dict):
                    profile_vals.update(defaults)
            except (json.JSONDecodeError, TypeError):
                _logger.warning(
                    'Template %s: invalid profile_defaults JSON', self.name,
                )

        profile = self.env['migrate.profile'].create(profile_vals)

        # Create field mappings from mapping_data JSON
        if self.mapping_data:
            try:
                mappings = json.loads(self.mapping_data)
                if isinstance(mappings, list):
                    MappingModel = self.env['migrate.field.mapping']
                    for seq, mdef in enumerate(mappings, start=1):
                        if not isinstance(mdef, dict):
                            continue
                        mapping_vals = {
                            'profile_id': profile.id,
                            'sequence': mdef.get('sequence', seq * 10),
                            'source_column': mdef.get('source_column', ''),
                        }
                        # Resolve field by name
                        field_name = mdef.get('field_name')
                        if field_name:
                            ir_field = self.env['ir.model.fields'].search([
                                ('model_id', '=', self.model_id.id),
                                ('name', '=', field_name),
                            ], limit=1)
                            if ir_field:
                                mapping_vals['field_id'] = ir_field.id
                        # Copy simple scalar values
                        for key in (
                            'transform_type', 'type_cast_to', 'expression',
                            'default_value', 'date_source_format',
                            'truncate_length', 'regex_pattern',
                            'concatenate_fields', 'concatenate_separator',
                            'required', 'unique', 'validation_regex',
                            'export_label', 'relation_match_field',
                        ):
                            if key in mdef:
                                mapping_vals[key] = mdef[key]
                        MappingModel.create(mapping_vals)
            except (json.JSONDecodeError, TypeError):
                _logger.warning(
                    'Template %s: invalid mapping_data JSON', self.name,
                )

        return {
            'type': 'ir.actions.act_window',
            'name': _('Migration Profile'),
            'res_model': 'migrate.profile',
            'res_id': profile.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_download_sample(self):
        """Download the sample file attached to this template."""
        self.ensure_one()
        if not self.sample_file:
            raise UserError(_('No sample file is attached to this template.'))
        return {
            'type': 'ir.actions.act_url',
            'url': (
                f'/web/content/{self._name}/{self.id}'
                f'/sample_file/{self.sample_filename or "sample"}?download=true'
            ),
            'target': 'self',
        }

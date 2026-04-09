# Part of Navigare Migrate. See LICENSE file for full copyright and licensing details.
# Copyright 2025 Navigare Space Ltd
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).

import logging

from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)

FORMAT_TYPES = [
    ('csv', 'CSV'),
    ('xlsx', 'Excel (.xlsx)'),
    ('xml', 'XML'),
    ('json', 'JSON'),
    ('fixed', 'Fixed-Width'),
    ('ods', 'ODS (LibreOffice)'),
    ('sqlite', 'SQLite'),
]

DELIMITER_SELECTION = [
    (',', 'Comma (,)'),
    (';', 'Semicolon (;)'),
    ('\t', 'Tab'),
    ('|', 'Pipe (|)'),
]

ENCODING_SELECTION = [
    ('utf-8', 'UTF-8'),
    ('utf-8-sig', 'UTF-8 with BOM'),
    ('cp1250', 'Windows-1250 (Central European)'),
    ('cp1252', 'Windows-1252 (Western European)'),
    ('iso-8859-1', 'ISO-8859-1 (Latin-1)'),
    ('iso-8859-2', 'ISO-8859-2 (Latin-2)'),
]

ON_EXISTING_SELECTION = [
    ('skip', 'Skip'),
    ('update', 'Update'),
    ('error', 'Raise Error'),
]


class MigrateProfile(models.Model):
    _name = 'migrate.profile'
    _description = 'Migration Profile'
    _inherit = ['mail.thread']
    _order = 'name'

    # ------------------------------------------------------------------
    # Core fields
    # ------------------------------------------------------------------
    name = fields.Char(required=True, tracking=True)
    active = fields.Boolean(default=True)
    direction = fields.Selection(
        [('import', 'Import'), ('export', 'Export')],
        required=True,
        default='import',
        tracking=True,
    )
    format_type = fields.Selection(
        FORMAT_TYPES,
        string='File Format',
        required=True,
        default='csv',
        tracking=True,
    )
    model_id = fields.Many2one(
        'ir.model',
        string='Target Model',
        required=True,
        ondelete='cascade',
        domain=[('transient', '=', False)],
    )
    model_name = fields.Char(
        related='model_id.model',
        string='Model Name',
        store=True,
        readonly=True,
    )

    # ------------------------------------------------------------------
    # CSV options
    # ------------------------------------------------------------------
    csv_delimiter = fields.Selection(
        DELIMITER_SELECTION,
        string='Delimiter',
        default=',',
    )
    csv_encoding = fields.Selection(
        ENCODING_SELECTION,
        string='Encoding',
        default='utf-8',
    )
    csv_quotechar = fields.Char(
        string='Quote Character',
        default='"',
        size=1,
    )
    csv_has_header = fields.Boolean(
        string='Has Header Row',
        default=True,
    )

    # ------------------------------------------------------------------
    # Excel / ODS options
    # ------------------------------------------------------------------
    sheet_name = fields.Char(
        string='Sheet Name',
        help='Leave empty to use the first sheet.',
    )
    header_row = fields.Integer(
        string='Header Row',
        default=1,
        help='Row number (1-based) that contains column headers.',
    )
    data_start_row = fields.Integer(
        string='Data Start Row',
        default=2,
        help='Row number (1-based) where data begins.',
    )

    # ------------------------------------------------------------------
    # XML options
    # ------------------------------------------------------------------
    xml_root_element = fields.Char(
        string='Root Element',
        default='records',
    )
    xml_record_element = fields.Char(
        string='Record Element',
        default='record',
    )
    xml_use_attributes = fields.Boolean(
        string='Use Attributes',
        help='Map values from XML attributes rather than text content.',
    )

    # ------------------------------------------------------------------
    # JSON options
    # ------------------------------------------------------------------
    json_root_path = fields.Char(
        string='Root Path',
        help='JSONPath expression to the array of records, e.g. "data.items".',
    )
    json_flatten_nested = fields.Boolean(
        string='Flatten Nested Objects',
        default=True,
    )

    # ------------------------------------------------------------------
    # Fixed-width options
    # ------------------------------------------------------------------
    fixed_width_definition = fields.Text(
        string='Column Definitions',
        help='JSON array of objects: [{"name": "col", "start": 0, "width": 10, "type": "str"}, ...]',
    )

    # ------------------------------------------------------------------
    # SQLite options
    # ------------------------------------------------------------------
    sqlite_table_name = fields.Char(
        string='Table Name',
    )

    # ------------------------------------------------------------------
    # Behaviour options
    # ------------------------------------------------------------------
    on_existing = fields.Selection(
        ON_EXISTING_SELECTION,
        string='On Existing Record',
        default='update',
        help='What to do when a matching record already exists.',
    )
    match_field_ids = fields.Many2many(
        'ir.model.fields',
        string='Match Fields',
        help='Fields used to detect existing records during import.',
    )
    batch_size = fields.Integer(
        string='Batch Size',
        default=500,
        help='Number of records processed per database commit.',
    )
    use_external_ids = fields.Boolean(
        string='Use External IDs',
        default=True,
    )
    external_id_prefix = fields.Char(
        string='External ID Prefix',
        default='migrate_',
    )

    # ------------------------------------------------------------------
    # Relations
    # ------------------------------------------------------------------
    field_mapping_ids = fields.One2many(
        'migrate.field.mapping',
        'profile_id',
        string='Field Mappings',
        copy=True,
    )
    operation_ids = fields.One2many(
        'migrate.operation',
        'profile_id',
        string='Operations',
    )
    schedule_ids = fields.One2many(
        'migrate.schedule',
        'profile_id',
        string='Schedules',
    )
    template_id = fields.Many2one(
        'migrate.template',
        string='Template',
    )

    # ------------------------------------------------------------------
    # Computed fields
    # ------------------------------------------------------------------
    operation_count = fields.Integer(
        string='Operations',
        compute='_compute_operation_stats',
    )
    last_operation_date = fields.Datetime(
        string='Last Operation',
        compute='_compute_operation_stats',
    )

    # ------------------------------------------------------------------
    # Other fields
    # ------------------------------------------------------------------
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
    )
    notes = fields.Text()

    # ------------------------------------------------------------------
    # Compute methods
    # ------------------------------------------------------------------
    @api.depends('operation_ids')
    def _compute_operation_stats(self):
        for profile in self:
            operations = profile.operation_ids
            profile.operation_count = len(operations)
            if operations:
                profile.last_operation_date = max(
                    operations.mapped('create_date')
                )
            else:
                profile.last_operation_date = False

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def action_run_import(self):
        """Open the import wizard pre-filled with this profile."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Import Data'),
            'res_model': 'migrate.import.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_profile_id': self.id,
            },
        }

    def action_run_export(self):
        """Open the export wizard pre-filled with this profile."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Export Data'),
            'res_model': 'migrate.export.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_profile_id': self.id,
            },
        }

    def action_auto_map_fields(self):
        """Attempt to automatically map source columns to model fields.

        Looks for exact or normalised name matches between existing
        source_column values in the field mappings and fields of the
        target model.
        """
        self.ensure_one()
        if not self.model_id:
            return
        model_fields = self.env['ir.model.fields'].search([
            ('model_id', '=', self.model_id.id),
            ('store', '=', True),
        ])
        field_by_name = {f.name: f for f in model_fields}
        field_by_desc = {
            (f.field_description or '').strip().lower(): f
            for f in model_fields
        }
        mapped_count = 0
        for mapping in self.field_mapping_ids.filtered(lambda m: not m.field_id):
            col = (mapping.source_column or '').strip()
            col_norm = col.lower().replace(' ', '_').replace('-', '_')
            # Exact name match
            if col_norm in field_by_name:
                mapping.field_id = field_by_name[col_norm].id
                mapped_count += 1
                continue
            # Match by field description / label
            if col.lower() in field_by_desc:
                mapping.field_id = field_by_desc[col.lower()].id
                mapped_count += 1
                continue
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Auto-Map Complete'),
                'message': _('%d field(s) mapped automatically.', mapped_count),
                'type': 'info',
                'sticky': False,
            },
        }

    def action_open_operations(self):
        """Open the list of operations linked to this profile."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Operations'),
            'res_model': 'migrate.operation',
            'view_mode': 'list,form',
            'domain': [('profile_id', '=', self.id)],
            'context': {
                'default_profile_id': self.id,
            },
        }

    # ------------------------------------------------------------------
    # Business helpers
    # ------------------------------------------------------------------
    def _get_format_options(self):
        """Return a dict of format-specific options ready for the engine.

        The keys match what the format adapters expect in their *options*
        argument.
        """
        self.ensure_one()
        opts = {}
        fmt = self.format_type

        if fmt == 'csv':
            opts.update({
                'delimiter': self.csv_delimiter or ',',
                'encoding': self.csv_encoding or 'utf-8',
                'quotechar': self.csv_quotechar or '"',
                'has_header': self.csv_has_header,
            })
        elif fmt in ('xlsx', 'ods'):
            opts.update({
                'sheet_name': self.sheet_name or None,
                'header_row': self.header_row or 1,
                'data_start_row': self.data_start_row or 2,
            })
        elif fmt == 'xml':
            opts.update({
                'root_element': self.xml_root_element or 'records',
                'record_element': self.xml_record_element or 'record',
                'use_attributes': self.xml_use_attributes,
            })
        elif fmt == 'json':
            opts.update({
                'root_path': self.json_root_path or None,
                'flatten_nested': self.json_flatten_nested,
            })
        elif fmt == 'fixed':
            opts.update({
                'definition': self.fixed_width_definition or '[]',
            })
        elif fmt == 'sqlite':
            opts.update({
                'table_name': self.sqlite_table_name or None,
            })

        return opts

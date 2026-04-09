# Part of Navigare Migrate. See LICENSE file for full copyright and licensing details.
# Copyright 2025 Navigare Space Ltd
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).

import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

TRANSFORM_TYPES = [
    ('none', 'None'),
    ('type_cast', 'Type Cast'),
    ('value_map', 'Value Map'),
    ('expression', 'Expression'),
    ('default', 'Default Value'),
    ('date_format', 'Date Format'),
    ('truncate', 'Truncate'),
    ('regex', 'Regex Extract'),
    ('concatenate', 'Concatenate'),
]

TYPE_CAST_TARGETS = [
    ('str', 'String'),
    ('int', 'Integer'),
    ('float', 'Float'),
    ('bool', 'Boolean'),
    ('date', 'Date'),
    ('datetime', 'Datetime'),
]


class MigrateFieldMapping(models.Model):
    _name = 'migrate.field.mapping'
    _description = 'Profile Field Mapping'
    _order = 'sequence, id'

    # ------------------------------------------------------------------
    # Core
    # ------------------------------------------------------------------
    profile_id = fields.Many2one(
        'migrate.profile',
        string='Profile',
        required=True,
        ondelete='cascade',
        index=True,
    )
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    # ------------------------------------------------------------------
    # Source
    # ------------------------------------------------------------------
    source_column = fields.Char(
        string='Source Column',
        required=True,
        help='Column header name (or element/path) in the source file.',
    )
    source_index = fields.Integer(
        string='Source Index',
        help='0-based column index.  Used when the file has no header row.',
    )

    # ------------------------------------------------------------------
    # Target (Odoo field)
    # ------------------------------------------------------------------
    field_id = fields.Many2one(
        'ir.model.fields',
        string='Target Field',
        domain="[('model_id', '=', parent.model_id)]",
    )
    field_name = fields.Char(
        related='field_id.name',
        string='Field Name',
        store=True,
        readonly=True,
    )
    field_type = fields.Selection(
        related='field_id.ttype',
        string='Field Type',
        store=True,
        readonly=True,
    )
    field_relation = fields.Char(
        related='field_id.relation',
        string='Field Relation',
        store=True,
        readonly=True,
    )
    relation_match_field = fields.Char(
        string='Relation Match Field',
        default='name',
        help='Field on the related model used to look up records (e.g. "name", "code").',
    )

    # ------------------------------------------------------------------
    # Transformation
    # ------------------------------------------------------------------
    transform_type = fields.Selection(
        TRANSFORM_TYPES,
        string='Transform',
        default='none',
    )
    type_cast_to = fields.Selection(
        TYPE_CAST_TARGETS,
        string='Cast To',
    )
    value_map_id = fields.Many2one(
        'migrate.value.map',
        string='Value Map',
    )
    expression = fields.Text(
        string='Expression',
        help='Restricted Python expression.  Available variables: value, record, row, datetime, date, re, math.',
    )
    default_value = fields.Char(
        string='Default Value',
        help='Value to use when the source cell is empty.',
    )
    date_source_format = fields.Char(
        string='Date Source Format',
        help='strptime format string, e.g. "%%d/%%m/%%Y".',
    )
    truncate_length = fields.Integer(
        string='Truncate Length',
    )
    regex_pattern = fields.Char(
        string='Regex Pattern',
        help='Regular expression with at least one capture group.  The first group is extracted.',
    )
    concatenate_fields = fields.Char(
        string='Concatenate Fields',
        help='Comma-separated list of source column names to concatenate.',
    )
    concatenate_separator = fields.Char(
        string='Concatenate Separator',
        default=' ',
    )

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------
    required = fields.Boolean(
        string='Required',
        help='Rows with an empty value for this field will be rejected.',
    )
    unique = fields.Boolean(
        string='Unique',
        help='Values must be unique within the import batch.',
    )
    validation_regex = fields.Char(
        string='Validation Regex',
        help='Regex pattern that the value must match after transformation.',
    )

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------
    export_label = fields.Char(
        string='Export Header',
        help='Column header to use in the exported file.  Falls back to field name.',
    )
    export_format = fields.Char(
        string='Export Format',
        help='Python format string for export, e.g. "{:.2f}".',
    )

    # ------------------------------------------------------------------
    # Other
    # ------------------------------------------------------------------
    notes = fields.Char()

    # ------------------------------------------------------------------
    # Business methods
    # ------------------------------------------------------------------
    def _to_engine_dict(self):
        """Convert this mapping record into a plain dict for the engine.

        The returned dict is compatible with :func:`engine.transform.apply_transform`
        and :class:`engine.validator.RowValidator`.
        """
        self.ensure_one()
        vals = {
            'source_column': self.source_column,
            'source_index': self.source_index,
            'field_name': self.field_name,
            'field_type': self.field_type,
            'field_relation': self.field_relation,
            'relation_match_field': self.relation_match_field or 'name',
            'transform_type': self.transform_type or 'none',
            'type_cast_to': self.type_cast_to,
            'expression': self.expression,
            'default_value': self.default_value,
            'date_source_format': self.date_source_format,
            'truncate_length': self.truncate_length or 0,
            'regex_pattern': self.regex_pattern,
            'concatenate_fields': self.concatenate_fields,
            'concatenate_separator': self.concatenate_separator or ' ',
            'required': self.required,
            'unique': self.unique,
            'validation_regex': self.validation_regex,
            'export_label': self.export_label or self.source_column,
            'export_format': self.export_format,
        }
        # Pre-resolve value map data so the engine does not need ORM access
        if self.transform_type == 'value_map' and self.value_map_id:
            vmap = self.value_map_id
            vals['value_map_data'] = [
                (line.source_value, line.target_value)
                for line in vmap.line_ids.sorted('sequence')
            ]
            vals['value_map_default'] = vmap.default_value or None
            vals['value_map_case_sensitive'] = vmap.case_sensitive
        return vals

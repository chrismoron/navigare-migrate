# Part of Navigare Migrate. See LICENSE file for full copyright and licensing details.
# Copyright 2025 Navigare Space Ltd
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).

import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class MigrateValueMap(models.Model):
    _name = 'migrate.value.map'
    _description = 'Value Mapping Table'
    _order = 'name'

    name = fields.Char(required=True)
    line_ids = fields.One2many(
        'migrate.value.map.line',
        'map_id',
        string='Mapping Lines',
        copy=True,
    )
    default_value = fields.Char(
        string='Default Value',
        help='Value to return when no mapping line matches the source value.',
    )
    case_sensitive = fields.Boolean(
        string='Case Sensitive',
        default=False,
        help='If enabled, source values are matched case-sensitively.',
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
    )

    def translate(self, value):
        """Look up *value* in the mapping lines and return the target value.

        The search respects the ``case_sensitive`` flag.  When no line matches
        the ``default_value`` of the map is returned (which may be ``False``).

        Args:
            value: The source value to translate.

        Returns:
            str | False: Matched target value or the map default.
        """
        self.ensure_one()
        value_str = str(value).strip() if value else ''
        for line in self.line_ids.sorted('sequence'):
            src = line.source_value or ''
            if self.case_sensitive:
                if value_str == src:
                    return line.target_value
            else:
                if value_str.lower() == src.lower():
                    return line.target_value
        return self.default_value or False


class MigrateValueMapLine(models.Model):
    _name = 'migrate.value.map.line'
    _description = 'Value Mapping Line'
    _order = 'sequence, id'

    map_id = fields.Many2one(
        'migrate.value.map',
        string='Value Map',
        required=True,
        ondelete='cascade',
        index=True,
    )
    sequence = fields.Integer(default=10)
    source_value = fields.Char(string='Source Value', required=True)
    target_value = fields.Char(string='Target Value', required=True)

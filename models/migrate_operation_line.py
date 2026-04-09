# Part of Navigare Migrate. See LICENSE file for full copyright and licensing details.
# Copyright 2025 Navigare Space Ltd
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).

from odoo import fields, models

LINE_STATES = [
    ('created', 'Created'),
    ('updated', 'Updated'),
    ('skipped', 'Skipped'),
    ('error', 'Error'),
]


class MigrateOperationLine(models.Model):
    _name = 'migrate.operation.line'
    _description = 'Migration Operation Line'
    _order = 'row_number'

    operation_id = fields.Many2one(
        'migrate.operation',
        string='Operation',
        required=True,
        ondelete='cascade',
        index=True,
    )
    row_number = fields.Integer(
        string='Row',
        required=True,
    )
    state = fields.Selection(
        LINE_STATES,
        string='Status',
        required=True,
    )
    record_id = fields.Integer(
        string='Record ID',
        help='Database ID of the created or updated record.',
    )
    record_ref = fields.Char(
        string='Record Reference',
        help='External ID or display name of the affected record.',
    )
    error_message = fields.Text(
        string='Error Message',
    )
    source_data = fields.Text(
        string='Source Data',
        help='JSON representation of the original source row.',
    )

# Part of Navigare Migrate. See LICENSE file for full copyright and licensing details.
# Copyright 2025 Navigare Space Ltd
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).

from odoo import fields, models


class MigrateDependency(models.Model):
    _name = 'migrate.dependency'
    _description = 'Model Migration Dependency'
    _order = 'priority, id'
    _rec_name = 'model_id'

    model_id = fields.Many2one(
        'ir.model',
        string='Model',
        required=True,
        ondelete='cascade',
        index=True,
    )
    model_name = fields.Char(
        related='model_id.model',
        string='Model Name',
        store=True,
        readonly=True,
    )
    depends_on_model_id = fields.Many2one(
        'ir.model',
        string='Depends On',
        required=True,
        ondelete='cascade',
        index=True,
        help='The model that must be migrated before this one.',
    )
    depends_on_model_name = fields.Char(
        related='depends_on_model_id.model',
        string='Depends On Model',
        store=True,
        readonly=True,
    )
    priority = fields.Integer(
        default=10,
        help='Lower numbers are processed first.',
    )
    notes = fields.Char()

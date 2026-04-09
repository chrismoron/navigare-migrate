# Part of Navigare Migrate. See LICENSE file for full copyright and licensing details.
# Copyright 2025 Navigare Space Ltd
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).

from odoo.tests.common import TransactionCase


class TestFieldMapping(TransactionCase):
    """ORM tests for migrate.field.mapping and migrate.profile helpers."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner_model = cls.env['ir.model'].search(
            [('model', '=', 'res.partner')], limit=1,
        )
        cls.name_field = cls.env['ir.model.fields'].search([
            ('model_id', '=', cls.partner_model.id),
            ('name', '=', 'name'),
        ], limit=1)
        cls.profile = cls.env['migrate.profile'].create({
            'name': 'Test Profile',
            'direction': 'import',
            'format_type': 'csv',
            'model_id': cls.partner_model.id,
        })

    # ------------------------------------------------------------------
    # _to_engine_dict
    # ------------------------------------------------------------------

    def test_to_engine_dict(self):
        mapping = self.env['migrate.field.mapping'].create({
            'profile_id': self.profile.id,
            'source_column': 'Name',
            'field_id': self.name_field.id,
            'transform_type': 'none',
            'default_value': 'Unknown',
            'required': True,
            'unique': False,
        })
        d = mapping._to_engine_dict()

        # All expected keys must be present
        expected_keys = {
            'source_column', 'source_index', 'field_name', 'field_type',
            'field_relation', 'relation_match_field', 'transform_type',
            'type_cast_to', 'expression', 'default_value',
            'date_source_format', 'truncate_length', 'regex_pattern',
            'concatenate_fields', 'concatenate_separator', 'required',
            'unique', 'validation_regex', 'export_label', 'export_format',
        }
        self.assertTrue(expected_keys.issubset(set(d.keys())))

        self.assertEqual(d['source_column'], 'Name')
        self.assertEqual(d['field_name'], 'name')
        self.assertEqual(d['transform_type'], 'none')
        self.assertEqual(d['default_value'], 'Unknown')
        self.assertTrue(d['required'])
        self.assertFalse(d['unique'])
        self.assertEqual(d['relation_match_field'], 'name')
        self.assertEqual(d['truncate_length'], 0)
        self.assertEqual(d['concatenate_separator'], ' ')
        # export_label falls back to source_column when not set
        self.assertEqual(d['export_label'], 'Name')

    # ------------------------------------------------------------------
    # action_auto_map_fields
    # ------------------------------------------------------------------

    def test_auto_map_fields(self):
        """Create unmapped field_mapping rows and run auto-map."""
        profile = self.env['migrate.profile'].create({
            'name': 'Auto Map Test',
            'direction': 'import',
            'format_type': 'csv',
            'model_id': self.partner_model.id,
        })
        # Create mappings that simulate detected source columns
        for col in ['name', 'email', 'phone']:
            self.env['migrate.field.mapping'].create({
                'profile_id': profile.id,
                'source_column': col,
            })

        result = profile.action_auto_map_fields()
        # Should return a notification action
        self.assertEqual(result.get('type'), 'ir.actions.client')

        mapped = profile.field_mapping_ids.filtered(lambda m: m.field_id)
        # 'name', 'email', 'phone' are all stored fields on res.partner
        self.assertGreaterEqual(len(mapped), 1)
        # At minimum 'name' should be mapped
        name_mapping = profile.field_mapping_ids.filtered(
            lambda m: m.source_column == 'name'
        )
        self.assertTrue(name_mapping.field_id, "Expected 'name' to be auto-mapped")

    # ------------------------------------------------------------------
    # _get_format_options
    # ------------------------------------------------------------------

    def test_profile_format_options(self):
        profile = self.env['migrate.profile'].create({
            'name': 'CSV Options Test',
            'direction': 'import',
            'format_type': 'csv',
            'model_id': self.partner_model.id,
            'csv_delimiter': ';',
            'csv_encoding': 'cp1250',
            'csv_quotechar': '"',
            'csv_has_header': True,
        })
        opts = profile._get_format_options()
        self.assertEqual(opts['delimiter'], ';')
        self.assertEqual(opts['encoding'], 'cp1250')
        self.assertEqual(opts['quotechar'], '"')
        self.assertTrue(opts['has_header'])

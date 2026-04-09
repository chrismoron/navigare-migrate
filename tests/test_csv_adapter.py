# Part of Navigare Migrate. See LICENSE file for full copyright and licensing details.
# Copyright 2025 Navigare Space Ltd
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).

from odoo.tests.common import BaseCase

from ..engine.csv_adapter import CsvAdapter


class TestCsvAdapter(BaseCase):
    """Pure-Python tests for CsvAdapter – no Odoo ORM required."""

    def setUp(self):
        super().setUp()
        self.adapter = CsvAdapter()
        self.default_opts = {
            'encoding': 'utf-8',
            'delimiter': ',',
            'quotechar': '"',
            'has_header': True,
        }

    # ------------------------------------------------------------------
    # parse
    # ------------------------------------------------------------------

    def test_parse_basic(self):
        data = b"name,email\nJan,jan@test.pl\nAnna,anna@test.pl\n"
        rows = list(self.adapter.parse(data, self.default_opts))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0], {'name': 'Jan', 'email': 'jan@test.pl'})
        self.assertEqual(rows[1], {'name': 'Anna', 'email': 'anna@test.pl'})

    def test_parse_semicolon_delimiter(self):
        data = b"name;email\nJan;jan@test.pl\n"
        opts = dict(self.default_opts, delimiter=';')
        rows = list(self.adapter.parse(data, opts))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0], {'name': 'Jan', 'email': 'jan@test.pl'})

    def test_parse_no_header(self):
        data = b"Jan,jan@test.pl\nAnna,anna@test.pl\n"
        opts = dict(self.default_opts, has_header=False)
        rows = list(self.adapter.parse(data, opts))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0], {'col_0': 'Jan', 'col_1': 'jan@test.pl'})
        self.assertEqual(rows[1], {'col_0': 'Anna', 'col_1': 'anna@test.pl'})

    def test_parse_empty_rows(self):
        data = b"name,email\nJan,jan@test.pl\n\n  ,  \nAnna,anna@test.pl\n"
        rows = list(self.adapter.parse(data, self.default_opts))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['name'], 'Jan')
        self.assertEqual(rows[1]['name'], 'Anna')

    def test_parse_utf8_bom(self):
        bom = b'\xef\xbb\xbf'
        data = bom + b"name,email\nJan,jan@test.pl\n"
        rows = list(self.adapter.parse(data, self.default_opts))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['name'], 'Jan')

    def test_parse_cp1250(self):
        header = "name,city\n"
        row = "Łukasz,Łódź\n"
        data = (header + row).encode('cp1250')
        opts = dict(self.default_opts, encoding='cp1250')
        rows = list(self.adapter.parse(data, opts))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['name'], 'Łukasz')
        self.assertEqual(rows[0]['city'], 'Łódź')

    # ------------------------------------------------------------------
    # write
    # ------------------------------------------------------------------

    def test_write_basic(self):
        records = [
            {'name': 'Jan', 'email': 'jan@test.pl'},
            {'name': 'Anna', 'email': 'anna@test.pl'},
        ]
        result = self.adapter.write(records, ['name', 'email'], self.default_opts)
        text = result.decode('utf-8')
        lines = text.strip().splitlines()
        self.assertEqual(len(lines), 3)  # header + 2 data rows
        self.assertIn('name', lines[0])
        self.assertIn('Jan', lines[1])
        self.assertIn('Anna', lines[2])

    # ------------------------------------------------------------------
    # detect_columns
    # ------------------------------------------------------------------

    def test_detect_columns(self):
        data = b"name,email,phone\nJan,jan@test.pl,123\n"
        cols = self.adapter.detect_columns(data, self.default_opts)
        self.assertEqual(cols, ['name', 'email', 'phone'])

    # ------------------------------------------------------------------
    # preview
    # ------------------------------------------------------------------

    def test_preview(self):
        data = b"name,email\nJan,jan@test.pl\nAnna,anna@test.pl\nMaria,maria@test.pl\n"
        headers, rows = self.adapter.preview(data, self.default_opts, max_rows=2)
        self.assertEqual(headers, ['name', 'email'])
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0], ['Jan', 'jan@test.pl'])
        self.assertEqual(rows[1], ['Anna', 'anna@test.pl'])

    # ------------------------------------------------------------------
    # roundtrip
    # ------------------------------------------------------------------

    def test_roundtrip(self):
        original = [
            {'name': 'Jan', 'email': 'jan@test.pl'},
            {'name': 'Anna', 'email': 'anna@test.pl'},
        ]
        field_list = ['name', 'email']
        written = self.adapter.write(original, field_list, self.default_opts)
        parsed = list(self.adapter.parse(written, self.default_opts))
        self.assertEqual(len(parsed), len(original))
        for orig, back in zip(original, parsed):
            self.assertEqual(orig['name'], back['name'])
            self.assertEqual(orig['email'], back['email'])

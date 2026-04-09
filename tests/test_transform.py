# Part of Navigare Migrate. See LICENSE file for full copyright and licensing details.
# Copyright 2025 Navigare Space Ltd
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).

from datetime import date, datetime

from odoo.tests.common import BaseCase

from ..engine.transform import (
    apply_concatenate,
    apply_date_format,
    apply_expression,
    apply_regex,
    apply_transform,
    apply_value_map,
    cast_value,
)


class TestCastValue(BaseCase):
    """Tests for the cast_value helper."""

    def test_cast_str(self):
        self.assertEqual(cast_value(123, 'str'), '123')
        self.assertEqual(cast_value('hello', 'str'), 'hello')

    def test_cast_int(self):
        self.assertEqual(cast_value('123', 'int'), 123)
        self.assertEqual(cast_value('123.7', 'int'), 123)

    def test_cast_float(self):
        self.assertAlmostEqual(cast_value('1 234,56', 'float'), 1234.56)
        self.assertAlmostEqual(cast_value('1,234.56', 'float'), 1234.56)

    def test_cast_bool(self):
        for truthy in ('true', 'True', 'yes', 'Yes', 'tak', '1', 'on'):
            self.assertTrue(cast_value(truthy, 'bool'), msg=f"Expected True for {truthy!r}")
        for falsy in ('false', 'False', 'no', 'No', '0', 'off', ''):
            self.assertFalse(cast_value(falsy, 'bool'), msg=f"Expected False for {falsy!r}")

    def test_cast_date(self):
        self.assertEqual(cast_value('2024-01-15', 'date'), date(2024, 1, 15))
        self.assertEqual(cast_value('15/01/2024', 'date'), date(2024, 1, 15))
        self.assertEqual(cast_value('15.01.2024', 'date'), date(2024, 1, 15))

    def test_cast_datetime(self):
        result = cast_value('2024-01-15 10:30:00', 'datetime')
        self.assertEqual(result, datetime(2024, 1, 15, 10, 30, 0))

    def test_cast_empty(self):
        self.assertIsNone(cast_value(None, 'int'))
        self.assertIsNone(cast_value('', 'float'))
        self.assertIsNone(cast_value('  ', 'date'))
        self.assertIsNone(cast_value(None, 'datetime'))


class TestExpression(BaseCase):
    """Tests for apply_expression."""

    def test_expression_basic(self):
        result = apply_expression('hello', 'value.upper()', {})
        self.assertEqual(result, 'HELLO')

    def test_expression_with_record(self):
        row = {'first': 'Jan', 'last': 'Kowalski'}
        result = apply_expression('', "record['first'] + ' ' + record['last']", row)
        self.assertEqual(result, 'Jan Kowalski')

    def test_expression_math(self):
        result = apply_expression('100', 'round(float(value) * 1.23, 2)', {})
        self.assertAlmostEqual(result, 123.0)

    def test_expression_blocked(self):
        with self.assertRaises(ValueError):
            apply_expression('x', "__import__('os')", {})

    def test_expression_blocked_os(self):
        with self.assertRaises(ValueError):
            apply_expression('x', "os.system('echo hi')", {})


class TestDateFormat(BaseCase):
    """Tests for apply_date_format."""

    def test_date_format(self):
        result = apply_date_format('15/01/2024', '%d/%m/%Y')
        self.assertEqual(result, date(2024, 1, 15))


class TestRegex(BaseCase):
    """Tests for apply_regex."""

    def test_regex_extract(self):
        result = apply_regex('ABC-123-456', r'(\d{3})-(\d{3})')
        self.assertEqual(result, '123')


class TestConcatenate(BaseCase):
    """Tests for apply_concatenate."""

    def test_concatenate(self):
        row = {'first_name': 'Jan', 'last_name': 'Kowalski'}
        result = apply_concatenate(row, 'first_name,last_name', ' ')
        self.assertEqual(result, 'Jan Kowalski')


class TestValueMap(BaseCase):
    """Tests for apply_value_map."""

    def test_value_map(self):
        mapping = {
            'value_map_data': [('M', 'male'), ('F', 'female')],
            'value_map_case_sensitive': False,
            'value_map_default': 'other',
        }
        self.assertEqual(apply_value_map('M', mapping), 'male')
        self.assertEqual(apply_value_map('f', mapping), 'female')
        self.assertEqual(apply_value_map('X', mapping), 'other')


class TestApplyTransform(BaseCase):
    """Tests for the top-level apply_transform dispatcher."""

    def test_apply_transform_none(self):
        mapping = {'transform_type': 'none'}
        result = apply_transform('hello', mapping)
        self.assertEqual(result, 'hello')

    def test_apply_transform_default(self):
        mapping = {'transform_type': 'default', 'default_value': 'N/A'}
        result = apply_transform('', mapping)
        self.assertEqual(result, 'N/A')
        # Non-empty value should pass through
        result2 = apply_transform('real', mapping)
        self.assertEqual(result2, 'real')

    def test_apply_transform_truncate(self):
        mapping = {'transform_type': 'truncate', 'truncate_length': 5}
        result = apply_transform('Hello World', mapping)
        self.assertEqual(result, 'Hello')
        # Short string stays intact
        result2 = apply_transform('Hi', mapping)
        self.assertEqual(result2, 'Hi')

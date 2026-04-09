{
    'name': 'Navigare Migrate',
    'version': '19.0.1.0.0',
    'summary': 'Mass data import/export: CSV, Excel, XML, JSON, Fixed-Width, ODS, SQLite',
    'description': """
Navigare Migrate - Enterprise-grade data migration toolkit for Odoo 19.

Supports 7 file formats for mass import and export:
- CSV (configurable delimiters, encoding)
- Excel .xlsx (sheet selection, header row config)
- XML (element/attribute mapping)
- JSON (flat + nested, JSONPath)
- Fixed-Width Columns (positional field definitions)
- LibreOffice Calc .ods (native ODS format)
- SQLite (portable migration database container)

Features:
- Reusable import/export profiles with field mapping
- Data transformations (type cast, value map, expressions, regex)
- Batch processing with progress tracking
- Dry-run / preview mode
- Rollback capability via external IDs
- Scheduled automated operations (ir.cron)
- Pre-built migration templates
- OWL Dashboard with execution statistics
- Multi-company support
    """,
    'category': 'Tools',
    'author': 'Navigare Space Ltd',
    'company': 'Navigare Space Ltd',
    'website': 'https://navigare.space',
    'license': 'LGPL-3',
    'depends': ['base', 'web', 'mail'],
    'external_dependencies': {
        'python': ['openpyxl'],
    },
    'data': [
        # Security
        'security/security_groups.xml',
        'security/ir.model.access.csv',
        'security/record_rules.xml',
        # Data
        'data/sequence.xml',
        'data/cron_cleanup.xml',
        'data/templates.xml',
        # Views & Actions (actions before menus that reference them)
        'views/dashboard_action.xml',
        'views/value_map_views.xml',
        'views/profile_views.xml',
        'views/operation_views.xml',
        'views/schedule_views.xml',
        'views/template_views.xml',
        # Menus (after all actions are defined)
        'views/migrate_menus.xml',
        # Wizards
        'wizard/import_wizard_views.xml',
        'wizard/export_wizard_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'navigare_migrate/static/src/js/dashboard.js',
            'navigare_migrate/static/src/xml/dashboard.xml',
            'navigare_migrate/static/src/css/migrate.css',
        ],
    },
    'installable': True,
    'auto_install': False,
    'application': True,
}

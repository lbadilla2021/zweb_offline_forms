{
    'name': 'Website Offline Forms',
    'version': '18.0.1.0.0',
    'summary': 'Reusable offline form engine for Odoo Website and Portal forms',
    'category': 'Website',
    'author': 'Apex SpA',
    'license': 'LGPL-3',
    'depends': ['base', 'web', 'website'],
    'data': [
        'security/ir.model.access.csv',
        'views/offline_form_views.xml',
        'views/templates.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'zweb_offline_forms/static/src/js/offline_db.js',
            'zweb_offline_forms/static/src/js/offline_forms.js',
            'zweb_offline_forms/static/src/js/offline_sync.js',
        ],
    },
    'installable': True,
    'application': False,
}

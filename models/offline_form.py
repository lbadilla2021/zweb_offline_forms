from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class ZWebOfflineForm(models.Model):
    _name = 'zweb.offline.form'
    _description = 'Offline-capable Website Form'
    _order = 'name'

    name = fields.Char(required=True)
    code = fields.Char(required=True, index=True)
    active = fields.Boolean(default=True)
    target_model = fields.Char(
        required=True,
        help='Technical model name that will receive synchronized submissions. Example: zhr.leave.request.portal'
    )
    require_login = fields.Boolean(default=True)
    allowed_group_ids = fields.Many2many(
        'res.groups',
        'zweb_offline_form_group_rel',
        'form_id',
        'group_id',
        string='Allowed Groups',
        help='If empty, any authenticated user can submit when login is required.'
    )
    allowed_fields = fields.Text(
        help='Optional comma-separated allowlist of payload fields. If empty, all submitted payload keys are accepted.'
    )
    allow_attachments = fields.Boolean(default=False)
    version = fields.Integer(default=1, required=True)
    description = fields.Text()

    _sql_constraints = [
        ('code_unique', 'unique(code)', 'The form code must be unique.'),
    ]

    @api.constrains('code')
    def _check_code(self):
        for rec in self:
            if rec.code and not rec.code.replace('_', '').replace('-', '').isalnum():
                raise ValidationError(_('The code may contain only letters, numbers, hyphens and underscores.'))

    def get_allowed_field_names(self):
        self.ensure_one()
        if not self.allowed_fields:
            return []
        return [x.strip() for x in self.allowed_fields.split(',') if x.strip()]

    def check_submit_access(self):
        self.ensure_one()
        user = self.env.user
        if self.require_login and user._is_public():
            return False
        if self.allowed_group_ids:
            user_group_ids = set(user.groups_id.ids)
            if not user_group_ids.intersection(set(self.allowed_group_ids.ids)):
                return False
        return True

from odoo import fields, models, _
from odoo.exceptions import ValidationError


class ZWebOfflineFormTokenWizard(models.TransientModel):
    _name = 'zweb.offline.form.token.wizard'
    _description = 'Set External User Password'

    token_user_id = fields.Many2one(
        'zweb.offline.form.token.user',
        required=True,
        readonly=True,
    )
    password = fields.Char(required=True)
    password_confirm = fields.Char(required=True)

    def action_set_password(self):
        self.ensure_one()
        if self.password != self.password_confirm:
            raise ValidationError(_('Passwords do not match.'))
        if len(self.password or '') < 8:
            raise ValidationError(_('The password must contain at least 8 characters.'))
        self.token_user_id.set_password(self.password)
        return {'type': 'ir.actions.act_window_close'}

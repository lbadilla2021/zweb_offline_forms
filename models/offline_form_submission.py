import json
import logging

from odoo import fields, models, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class ZWebOfflineFormSubmission(models.Model):
    _name = 'zweb.offline.form.submission'
    _description = 'Offline Form Submission'
    _order = 'create_date desc'

    name = fields.Char(default=lambda self: _('Offline Submission'), required=True)
    local_uuid = fields.Char(required=True, index=True)
    form_id = fields.Many2one('zweb.offline.form', required=True, ondelete='restrict')
    user_id = fields.Many2one('res.users', default=lambda self: self.env.user, index=True)
    partner_id = fields.Many2one('res.partner', related='user_id.partner_id', store=True, readonly=True)
    external_user_id = fields.Many2one(
        'zweb.offline.form.token.user',
        string='External User',
        readonly=True,
        copy=False,
        index=True,
    )
    external_login_snapshot = fields.Char(readonly=True, copy=False)
    auth_method = fields.Selection([
        ('odoo_user', 'Odoo User'),
        ('external_token', 'External Token'),
    ], default='odoo_user', required=True, readonly=True, copy=False)
    remote_addr = fields.Char(readonly=True, copy=False)
    user_agent = fields.Char(readonly=True, copy=False)
    payload_json = fields.Text(required=True)
    target_model = fields.Char(related='form_id.target_model', store=True, readonly=True)
    target_res_id = fields.Integer(readonly=True)
    state = fields.Selection([
        ('received', 'Received'),
        ('done', 'Done'),
        ('error', 'Error'),
    ], default='received', required=True, index=True)
    error_message = fields.Text(readonly=True)
    submitted_at = fields.Datetime(default=fields.Datetime.now, required=True)
    processed_at = fields.Datetime(readonly=True)

    _sql_constraints = [
        ('local_uuid_form_unique', 'unique(local_uuid, form_id)', 'This local submission was already received.'),
    ]

    def _prepare_target_values(self, payload):
        self.ensure_one()
        allowed = self.form_id.get_allowed_field_names()
        if allowed:
            payload = {k: v for k, v in payload.items() if k in allowed}
        return dict(payload)

    def process_submission(self):
        for rec in self:
            try:
                payload = json.loads(rec.payload_json or '{}')
                if not isinstance(payload, dict):
                    raise ValidationError(_('Payload must be a JSON object.'))

                target_model = rec.form_id.target_model
                model = rec.env[target_model].sudo()
                vals = rec._prepare_target_values(payload)

                # Safety defaults for traceability when target model supports these fields.
                if 'x_offline_local_uuid' in model._fields:
                    vals['x_offline_local_uuid'] = rec.local_uuid
                if 'x_offline_submission_id' in model._fields:
                    vals['x_offline_submission_id'] = rec.id
                if 'external_token_user_id' in model._fields and rec.external_user_id:
                    vals['external_token_user_id'] = rec.external_user_id.id
                if 'external_login_snapshot' in model._fields and rec.external_login_snapshot:
                    vals['external_login_snapshot'] = rec.external_login_snapshot
                if 'offline_auth_method' in model._fields:
                    vals['offline_auth_method'] = rec.auth_method

                created = model.create(vals)
                rec.write({
                    'target_res_id': created.id,
                    'state': 'done',
                    'error_message': False,
                    'processed_at': fields.Datetime.now(),
                })
            except Exception as exc:  # noqa: BLE001 - keep error visible in audit table
                _logger.exception('Offline form submission failed')
                rec.write({
                    'state': 'error',
                    'error_message': str(exc),
                    'processed_at': fields.Datetime.now(),
                })
        return True

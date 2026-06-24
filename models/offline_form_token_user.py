import base64
import hashlib
import hmac
import json
import secrets
import time
from datetime import datetime

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class ZWebOfflineFormTokenUser(models.Model):
    _name = 'zweb.offline.form.token.user'
    _description = 'External Token User for Offline Website Forms'
    _order = 'name, login'

    name = fields.Char(required=True)
    login = fields.Char(required=True, index=True)
    active = fields.Boolean(default=True)
    token_hash = fields.Char(copy=False, readonly=True)
    form_ids = fields.Many2many(
        'zweb.offline.form',
        'zweb_offline_form_token_user_rel',
        'token_user_id',
        'form_id',
        string='Allowed Forms',
        help='Forms this external user can access. Leave empty to deny access until explicitly configured.',
    )
    expires_at = fields.Datetime(
        string='Expires At',
        help='Optional expiration date for this external credential.',
    )
    last_login_at = fields.Datetime(readonly=True, copy=False)
    last_used_at = fields.Datetime(readonly=True, copy=False)
    notes = fields.Text()

    _sql_constraints = [
        ('login_unique', 'unique(login)', 'The external login must be unique.'),
    ]

    @api.model
    def _normalize_login(self, login):
        return login.strip() if isinstance(login, str) else login

    @api.model
    def _auth_result(self, ok=False, error_code=None, message=None, form=None, token_user=None):
        return {
            'ok': ok,
            'error_code': error_code,
            'message': message,
            'form': form or self.env['zweb.offline.form'],
            'token_user': token_user or self.env['zweb.offline.form.token.user'],
        }

    @api.model
    def _get_auth_secret(self):
        Param = self.env['ir.config_parameter'].sudo()
        secret = Param.get_param('zweb_offline_forms.external_auth_secret')
        if not secret:
            secret = secrets.token_urlsafe(48)
            Param.set_param('zweb_offline_forms.external_auth_secret', secret)
        return secret

    @api.model
    def _get_auth_token_ttl(self):
        ttl = self.env['ir.config_parameter'].sudo().get_param(
            'zweb_offline_forms.external_auth_ttl_seconds',
            '43200',
        )
        try:
            return max(300, int(ttl))
        except (TypeError, ValueError):
            return 43200

    @api.model
    def _base64url_encode(self, data):
        return base64.urlsafe_b64encode(data).decode('ascii').rstrip('=')

    @api.model
    def _base64url_decode(self, data):
        padding = '=' * (-len(data) % 4)
        return base64.urlsafe_b64decode((data + padding).encode('ascii'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if 'login' in vals:
                vals['login'] = self._normalize_login(vals.get('login'))
        return super().create(vals_list)

    def write(self, vals):
        if 'login' in vals:
            vals = dict(vals, login=self._normalize_login(vals.get('login')))
        return super().write(vals)

    @api.constrains('login')
    def _check_login(self):
        for rec in self:
            if rec.login and not rec.login.strip():
                raise ValidationError(_('The external login cannot be empty.'))

    @api.constrains('expires_at')
    def _check_expires_at(self):
        now = fields.Datetime.now()
        for rec in self:
            if rec.expires_at and rec.expires_at <= now:
                raise ValidationError(_('The expiration date must be in the future.'))

    @api.model
    def generate_plain_token(self):
        """Return a new plain token. The caller must show it once and store only its hash."""
        return secrets.token_urlsafe(32)

    @api.model
    def _hash_token(self, token, salt=None):
        if not token:
            raise ValidationError(_('A password is required.'))
        salt = salt or secrets.token_bytes(16)
        if isinstance(salt, str):
            salt = base64.urlsafe_b64decode(salt.encode('ascii'))
        digest = hashlib.pbkdf2_hmac(
            'sha256',
            token.encode('utf-8'),
            salt,
            200000,
        )
        return '%s$%s' % (
            base64.urlsafe_b64encode(salt).decode('ascii'),
            base64.urlsafe_b64encode(digest).decode('ascii'),
        )

    def set_plain_token(self, token):
        for rec in self:
            rec.token_hash = self._hash_token(token)
        return True

    def set_password(self, password):
        return self.set_plain_token(password)

    def generate_and_set_token(self):
        self.ensure_one()
        token = self.generate_plain_token()
        self.set_plain_token(token)
        return token

    def action_generate_token(self):
        self.ensure_one()
        token = self.generate_and_set_token()
        wizard = self.env['zweb.offline.form.token.wizard'].create({
            'token_user_id': self.id,
            'plain_token': token,
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Generated Token'),
            'res_model': 'zweb.offline.form.token.wizard',
            'view_mode': 'form',
            'res_id': wizard.id,
            'target': 'new',
        }

    def action_set_password(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Set Password'),
            'res_model': 'zweb.offline.form.token.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_token_user_id': self.id,
            },
        }

    def check_plain_token(self, token):
        self.ensure_one()
        if not token or not self.token_hash:
            return False
        try:
            salt, expected_digest = self.token_hash.split('$', 1)
            candidate_hash = self._hash_token(token, salt=salt)
            candidate_digest = candidate_hash.split('$', 1)[1]
        except Exception:
            return False
        return hmac.compare_digest(candidate_digest, expected_digest)

    @api.model
    def _sign_auth_payload(self, payload):
        encoded_payload = self._base64url_encode(
            json.dumps(payload, separators=(',', ':'), sort_keys=True).encode('utf-8')
        )
        signature = hmac.new(
            self._get_auth_secret().encode('utf-8'),
            encoded_payload.encode('ascii'),
            hashlib.sha256,
        ).digest()
        return '%s.%s' % (encoded_payload, self._base64url_encode(signature))

    @api.model
    def _decode_auth_token(self, access_token):
        if not access_token or '.' not in access_token:
            return None
        encoded_payload, signature = access_token.split('.', 1)
        expected_signature = hmac.new(
            self._get_auth_secret().encode('utf-8'),
            encoded_payload.encode('ascii'),
            hashlib.sha256,
        ).digest()
        try:
            received_signature = self._base64url_decode(signature)
        except Exception:
            return None
        if not hmac.compare_digest(received_signature, expected_signature):
            return None
        try:
            return json.loads(self._base64url_decode(encoded_payload).decode('utf-8'))
        except Exception:
            return None

    def make_access_token(self, form, ttl_seconds=None):
        self.ensure_one()
        form.ensure_one()
        now = int(time.time())
        ttl_seconds = ttl_seconds or self._get_auth_token_ttl()
        expires_at = now + ttl_seconds
        payload = {
            'external_user_id': self.id,
            'form_code': form.code,
            'iat': now,
            'exp': expires_at,
            'nonce': secrets.token_urlsafe(12),
        }
        return {
            'access_token': self._sign_auth_payload(payload),
            'expires_at': fields.Datetime.to_string(datetime.utcfromtimestamp(expires_at)),
            'expires_in': ttl_seconds,
        }

    @api.model
    def get_access_token_auth_result(self, access_token, form_code=None, mark_used=False):
        payload = self._decode_auth_token(access_token)
        if not isinstance(payload, dict):
            return self._auth_result(
                error_code='invalid_access_token',
                message=_('Invalid access token.'),
            )

        try:
            expires_at = int(payload.get('exp') or 0)
            external_user_id = int(payload.get('external_user_id') or 0)
        except (TypeError, ValueError):
            return self._auth_result(
                error_code='invalid_access_token',
                message=_('Invalid access token.'),
            )

        if expires_at <= int(time.time()):
            return self._auth_result(
                error_code='expired_access_token',
                message=_('Expired access token.'),
            )

        payload_form_code = payload.get('form_code')
        if form_code and payload_form_code != form_code:
            return self._auth_result(
                error_code='form_mismatch',
                message=_('Access token does not match this form.'),
            )

        form = self.env['zweb.offline.form'].sudo().search([
            ('code', '=', payload_form_code),
            ('active', '=', True),
        ], limit=1)
        token_user = self.sudo().browse(external_user_id)
        if not form or not token_user.exists():
            return self._auth_result(
                error_code='invalid_access_token',
                message=_('Invalid access token.'),
            )

        if not token_user.is_valid_for_form(form):
            return self._auth_result(
                error_code='access_denied',
                message=_('Access denied.'),
                form=form,
                token_user=token_user,
            )

        if mark_used:
            token_user.mark_used()

        return self._auth_result(
            ok=True,
            message=_('Access token accepted.'),
            form=form,
            token_user=token_user,
        )

    @api.model
    def get_external_token_auth_result(
        self,
        form_code,
        login,
        token,
        mark_login=False,
        mark_used=False,
    ):
        """Validate external credentials against a configured offline form.

        This helper is intended for public controllers, so it performs its
        searches with sudo but only returns success when the credential is
        active, unexpired, token-matched, and explicitly allowed for the form.
        """
        form_code = (form_code or '').strip()
        login = self._normalize_login(login or '')

        if not form_code:
            return self._auth_result(
                error_code='missing_form_code',
                message=_('Missing form code.'),
            )
        if not login or not token:
            return self._auth_result(
                error_code='missing_credentials',
                message=_('Missing login or password.'),
            )

        form = self.env['zweb.offline.form'].sudo().search([
            ('code', '=', form_code),
            ('active', '=', True),
        ], limit=1)
        if not form:
            return self._auth_result(
                error_code='unknown_form',
                message=_('Unknown or inactive form.'),
            )

        token_user = self.sudo().search([('login', '=', login)], limit=1)
        if not token_user or not token_user.check_plain_token(token):
            return self._auth_result(
                error_code='invalid_credentials',
                message=_('Invalid credentials.'),
                form=form,
            )

        if not token_user.active:
            return self._auth_result(
                error_code='inactive_credentials',
                message=_('Inactive credentials.'),
                form=form,
                token_user=token_user,
            )

        if token_user.expires_at and token_user.expires_at <= fields.Datetime.now():
            return self._auth_result(
                error_code='expired_credentials',
                message=_('Expired credentials.'),
                form=form,
                token_user=token_user,
            )

        if form.id not in token_user.form_ids.ids:
            return self._auth_result(
                error_code='form_not_allowed',
                message=_('Credentials are not allowed for this form.'),
                form=form,
                token_user=token_user,
            )

        if mark_login:
            token_user.mark_login()
        if mark_used:
            token_user.mark_used()

        return self._auth_result(
            ok=True,
            message=_('Credentials accepted.'),
            form=form,
            token_user=token_user,
        )

    @api.model
    def validate_external_token(self, form_code, login, token, mark_login=False, mark_used=False):
        result = self.get_external_token_auth_result(
            form_code,
            login,
            token,
            mark_login=mark_login,
            mark_used=mark_used,
        )
        return result['token_user'] if result['ok'] else self.browse()

    def is_valid_for_form(self, form):
        self.ensure_one()
        form.ensure_one()
        if not self.active:
            return False
        if self.expires_at and self.expires_at <= fields.Datetime.now():
            return False
        return form.id in self.form_ids.ids

    def mark_login(self):
        self.write({'last_login_at': fields.Datetime.now()})
        return True

    def mark_used(self):
        self.write({'last_used_at': fields.Datetime.now()})
        return True

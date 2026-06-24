import json

from odoo import http
from odoo.http import request


class ZWebOfflineFormsController(http.Controller):

    def _get_bearer_token(self):
        auth_header = request.httprequest.headers.get('Authorization', '')
        if auth_header.lower().startswith('bearer '):
            return auth_header[7:].strip()
        return None

    def _get_request_access_token(self, **values):
        return (
            values.get('external_access_token')
            or values.get('access_token')
            or self._get_bearer_token()
        )

    def _get_jsonrpc_params(self, values):
        params = values.get('params')
        return params if isinstance(params, dict) else {}

    def _auth_error_response(self, result):
        return {
            'ok': False,
            'error_code': result.get('error_code'),
            'error': result.get('message') or 'Authentication failed',
        }

    def _auth_success_response(self, result, token_data=None):
        token_user = result['token_user']
        form = result['form']
        response = {
            'ok': True,
            'form_code': form.code,
            'external_user': {
                'login': token_user.login,
                'name': token_user.name,
            },
        }
        if token_data:
            response.update(token_data)
        return response

    @http.route('/offline/auth/login', type='json', auth='public', methods=['POST'], csrf=False)
    def offline_auth_login(self, form_code=None, login=None, token=None, password=None, **kwargs):
        params = self._get_jsonrpc_params(kwargs)
        form_code = form_code or kwargs.get('form_code') or params.get('form_code')
        login = login or kwargs.get('login') or params.get('login')
        token = (
            token
            or password
            or kwargs.get('token')
            or kwargs.get('password')
            or params.get('token')
            or params.get('password')
        )

        TokenUser = request.env['zweb.offline.form.token.user'].sudo()
        result = TokenUser.get_external_token_auth_result(
            form_code,
            login,
            token,
            mark_login=True,
        )
        if not result['ok']:
            return self._auth_error_response(result)

        token_data = result['token_user'].make_access_token(result['form'])
        return self._auth_success_response(result, token_data=token_data)

    @http.route('/offline/auth/check', type='json', auth='public', methods=['POST'], csrf=False)
    def offline_auth_check(self, access_token=None, form_code=None, **kwargs):
        params = self._get_jsonrpc_params(kwargs)
        access_token = (
            access_token
            or kwargs.get('access_token')
            or params.get('access_token')
            or self._get_bearer_token()
        )
        form_code = form_code or kwargs.get('form_code') or params.get('form_code')

        result = request.env['zweb.offline.form.token.user'].sudo().get_access_token_auth_result(
            access_token,
            form_code=form_code,
        )
        if not result['ok']:
            return self._auth_error_response(result)
        return self._auth_success_response(result)

    @http.route('/offline/auth/logout', type='json', auth='public', methods=['POST'], csrf=False)
    def offline_auth_logout(self, **kwargs):
        return {'ok': True}

    @http.route('/offline/form/<string:form_code>', type='http', auth='user', website=True)
    def offline_form_demo(self, form_code, **kwargs):
        """Generic demo renderer.

        In production, most forms should be rendered by their own module/template.
        This route is useful to test the offline engine with a configured form code.
        """
        form = request.env['zweb.offline.form'].sudo().search([
            ('code', '=', form_code),
            ('active', '=', True),
        ], limit=1)
        if not form:
            return request.not_found()
        if not form.with_user(request.env.user).check_submit_access():
            return request.redirect('/web/login')

        return request.render('zweb_offline_forms.generic_form_page', {
            'offline_form': form,
        })

    @http.route('/offline/form/submit', type='json', auth='user', methods=['POST'], csrf=False)
    def submit_offline_form(self, form_code=None, local_uuid=None, payload=None, **kwargs):
        # En Odoo 18 con type='json', los parámetros del JSON-RPC llegan como args de la función.
        payload = payload or kwargs.get('payload') or {}
        access_token = self._get_request_access_token(**kwargs)

        if not form_code or not local_uuid:
            return {'ok': False, 'error': 'Missing form_code or local_uuid'}
        if not isinstance(payload, dict):
            return {'ok': False, 'error': 'Payload must be an object'}

        form = request.env['zweb.offline.form'].sudo().search([
            ('code', '=', form_code),
            ('active', '=', True),
        ], limit=1)
        if not form:
            return {'ok': False, 'error': 'Unknown or inactive form'}
        if not form.with_user(request.env.user).check_submit_access():
            return {'ok': False, 'error': 'Access denied'}

        auth_values = {
            'auth_method': 'odoo_user',
            'remote_addr': request.httprequest.remote_addr,
            'user_agent': request.httprequest.headers.get('User-Agent'),
        }
        if access_token:
            access_result = request.env['zweb.offline.form.token.user'].sudo().get_access_token_auth_result(
                access_token,
                form_code=form_code,
                mark_used=True,
            )
            if not access_result['ok']:
                return self._auth_error_response(access_result)
            auth_values.update({
                'auth_method': 'external_token',
                'external_user_id': access_result['token_user'].id,
                'external_login_snapshot': access_result['token_user'].login,
            })

        Submission = request.env['zweb.offline.form.submission'].sudo()
        existing = Submission.search([
            ('form_id', '=', form.id),
            ('local_uuid', '=', local_uuid),
        ], limit=1)
        if existing:
            return {
                'ok': existing.state == 'done',
                'duplicate': True,
                'submission_id': existing.id,
                'state': existing.state,
                'target_model': existing.target_model,
                'target_res_id': existing.target_res_id,
                'error': existing.error_message,
            }

        submission = Submission.create({
            'name': '%s / %s' % (form.name, local_uuid),
            'local_uuid': local_uuid,
            'form_id': form.id,
            'user_id': request.env.user.id,
            'payload_json': json.dumps(payload, ensure_ascii=False),
            'state': 'received',
            **auth_values,
        })
        submission.process_submission()

        return {
            'ok': submission.state == 'done',
            'submission_id': submission.id,
            'state': submission.state,
            'target_model': submission.target_model,
            'target_res_id': submission.target_res_id,
            'error': submission.error_message,
        }

    @http.route('/offline/form/status', type='json', auth='user', methods=['POST'], csrf=False)
    def offline_form_status(self, form_code=None, local_uuid=None, **kwargs):
        # En Odoo 18 con type='json', los parámetros del JSON-RPC llegan como args de la función.
        form = request.env['zweb.offline.form'].sudo().search([('code', '=', form_code)], limit=1)
        if not form:
            return {'ok': False, 'error': 'Unknown form'}
        submission = request.env['zweb.offline.form.submission'].sudo().search([
            ('form_id', '=', form.id),
            ('local_uuid', '=', local_uuid),
            ('user_id', '=', request.env.user.id),
        ], limit=1)
        if not submission:
            return {'ok': True, 'exists': False}
        return {
            'ok': True,
            'exists': True,
            'state': submission.state,
            'target_model': submission.target_model,
            'target_res_id': submission.target_res_id,
            'error': submission.error_message,
        }

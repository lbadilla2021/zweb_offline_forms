import json

from odoo import http
from odoo.http import request


class ZWebOfflineFormsController(http.Controller):

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

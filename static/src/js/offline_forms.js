(function () {
    'use strict';

    function serializeForm(form) {
        const payload = {};
        const data = new FormData(form);
        for (const [key, value] of data.entries()) {
            if (value instanceof File) {
                // Attachments are intentionally deferred for v1.
                continue;
            }
            // Skip CSRF token — it is ephemeral and must not be stored offline.
            if (key === 'csrf_token') {
                continue;
            }
            if (payload[key] !== undefined) {
                if (!Array.isArray(payload[key])) {
                    payload[key] = [payload[key]];
                }
                payload[key].push(value);
            } else {
                payload[key] = value;
            }
        }
        return payload;
    }

    function showMessage(form, message, level) {
        let box = form.querySelector('.z-offline-message');
        if (!box) {
            box = document.createElement('div');
            box.className = 'z-offline-message alert mt-2';
            form.insertAdjacentElement('afterend', box);
        }
        box.className = 'z-offline-message alert mt-2 alert-' + (level || 'info');
        box.textContent = message;
    }

    async function savePending(form) {
        if (!window.ZOfflineDB) {
            throw new Error('ZOfflineDB no está disponible.');
        }
        const formCode = form.dataset.formCode;
        if (!formCode) {
            throw new Error('El formulario no tiene data-form-code definido.');
        }
        const endpoint = form.dataset.syncEndpoint || '/offline/form/submit';
        const record = {
            local_uuid: crypto.randomUUID(),
            form_code: formCode,
            sync_endpoint: endpoint,
            payload: serializeForm(form),
            status: 'pending',
            created_at: new Date().toISOString(),
            synced_at: null,
            server_response: null,
        };
        await window.ZOfflineDB.put(record);
        return record;
    }

    async function handleSubmit(event) {
        const form = event.target;
        if (!form.matches('form[data-offline-form="true"]')) {
            return;
        }

        // Only intercept when offline; when online let the form submit normally.
        if (navigator.onLine) {
            return;
        }

        event.preventDefault();
        try {
            const record = await savePending(form);
            showMessage(form, 'Sin conexión: datos guardados localmente. Se sincronizarán al recuperar la conexión.', 'warning');
            form.dispatchEvent(new CustomEvent('z-offline-saved', { detail: record, bubbles: true }));
        } catch (err) {
            console.error('[ZOfflineForms] Error al guardar localmente:', err);
            showMessage(form, 'No se pudo guardar localmente: ' + err.message, 'danger');
        }
    }

    // Show a persistent offline banner on forms that support offline mode.
    function updateOfflineBanner() {
        document.querySelectorAll('form[data-offline-form="true"]').forEach(function (form) {
            let banner = form.previousElementSibling;
            if (!banner || !banner.classList.contains('z-offline-status-banner')) {
                banner = document.createElement('div');
                banner.className = 'z-offline-status-banner alert mb-2';
                form.insertAdjacentElement('beforebegin', banner);
            }
            if (navigator.onLine) {
                banner.className = 'z-offline-status-banner alert alert-success mb-2';
                banner.textContent = 'Conectado — los datos se enviarán directamente al servidor.';
            } else {
                banner.className = 'z-offline-status-banner alert alert-warning mb-2';
                banner.textContent = 'Sin conexión — los datos se guardarán localmente y se sincronizarán al reconectarse.';
            }
        });
    }

    document.addEventListener('submit', handleSubmit, true);
    document.addEventListener('DOMContentLoaded', updateOfflineBanner);
    window.addEventListener('online', updateOfflineBanner);
    window.addEventListener('offline', updateOfflineBanner);
})();

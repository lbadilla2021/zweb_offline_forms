(function () {
    'use strict';

    async function postJSON(url, body) {
        const response = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'same-origin',
            body: JSON.stringify(body),
        });
        if (!response.ok) {
            throw new Error('HTTP ' + response.status);
        }
        const data = await response.json();
        // Odoo JSON-RPC routes wrap the return value in {result: ...}.
        return data.result !== undefined ? data.result : data;
    }

    async function syncRecord(record) {
        if (!record || !record.payload || typeof record.payload !== 'object') {
            throw new Error('Registro offline inválido: falta payload.');
        }
        const endpoint = record.sync_endpoint || '/offline/form/submit';
        const result = await postJSON(endpoint, {
            form_code: record.form_code,
            local_uuid: record.local_uuid,
            payload: record.payload,
        });
        record.server_response = result;
        record.last_sync_attempt_at = new Date().toISOString();
        if (result && result.ok) {
            record.status = 'synced';
            record.synced_at = new Date().toISOString();
            record.error_message = null;
            // Notify the page about the successful sync.
            window.dispatchEvent(new CustomEvent('z-offline-synced', { detail: record }));
        } else {
            record.status = 'error';
            record.error_message = (result && result.error) ? result.error : 'Error desconocido del servidor';
        }
        await window.ZOfflineDB.put(record);
        return record;
    }

    async function syncPending() {
        if (!navigator.onLine) {
            return [];
        }
        if (!window.ZOfflineDB) {
            console.warn('[ZOfflineSync] ZOfflineDB no disponible aún.');
            return [];
        }
        let pending;
        try {
            pending = await window.ZOfflineDB.getAllByStatus('pending');
        } catch (err) {
            console.error('[ZOfflineSync] Error leyendo IndexedDB:', err);
            return [];
        }
        const results = [];
        for (const record of pending) {
            try {
                results.push(await syncRecord(record));
            } catch (err) {
                console.warn('[ZOfflineSync] Falló sync de', record.local_uuid, ':', err.message);
                // Mark the record as error but keep it in DB for inspection.
                try {
                    record.status = 'error';
                    record.error_message = err.message;
                    record.last_sync_attempt_at = new Date().toISOString();
                    await window.ZOfflineDB.put(record);
                } catch (_) { /* ignore secondary write error */ }
            }
        }
        return results;
    }

    window.addEventListener('online', function () {
        console.log('[ZOfflineSync] Conexión restaurada — sincronizando formularios pendientes…');
        syncPending().then(function (results) {
            var synced = results.filter(function (r) { return r.status === 'synced'; });
            if (synced.length) {
                console.log('[ZOfflineSync]', synced.length, 'formulario(s) sincronizado(s).');
            }
        });
    });

    document.addEventListener('DOMContentLoaded', function () {
        if (navigator.onLine) {
            syncPending();
        }
    });

    window.ZOfflineSync = {
        syncPending,
        syncRecord,
    };
})();

(function () {
    'use strict';

    const KEY_PREFIX = 'zweb_offline_auth:';

    function storageKey(formCode) {
        return KEY_PREFIX + formCode;
    }

    function cookieName(formCode) {
        return 'zweb_offline_auth_' + encodeURIComponent(formCode).replace(/[^A-Za-z0-9_]/g, '_');
    }

    function parseOdooDate(value) {
        if (!value) {
            return null;
        }
        return new Date(String(value).replace(' ', 'T') + 'Z');
    }

    function isExpired(authData) {
        const expiresAt = parseOdooDate(authData && authData.expires_at);
        if (!expiresAt || Number.isNaN(expiresAt.getTime())) {
            return true;
        }
        return expiresAt.getTime() <= Date.now() + 60000;
    }

    async function postJSON(url, body, accessToken) {
        const headers = { 'Content-Type': 'application/json' };
        if (accessToken) {
            headers.Authorization = 'Bearer ' + accessToken;
        }
        const response = await fetch(url, {
            method: 'POST',
            headers,
            credentials: 'same-origin',
            body: JSON.stringify({
                jsonrpc: '2.0',
                method: 'call',
                params: body || {},
            }),
        });
        if (!response.ok) {
            throw new Error('HTTP ' + response.status);
        }
        const data = await response.json();
        return data.result !== undefined ? data.result : data;
    }

    function isExternalAuthRequired(form) {
        if (!form || !form.dataset) {
            return false;
        }
        return form.dataset.authMode === 'external_token' || form.dataset.externalAuth === 'true';
    }

    function getAuthData(formCode) {
        if (!formCode) {
            return null;
        }
        try {
            const raw = window.localStorage.getItem(storageKey(formCode));
            return raw ? JSON.parse(raw) : null;
        } catch (_) {
            return null;
        }
    }

    function setAuthData(formCode, authData) {
        if (!formCode || !authData || !authData.access_token) {
            throw new Error('Datos de autenticacion invalidos.');
        }
        window.localStorage.setItem(storageKey(formCode), JSON.stringify(authData));
        document.cookie = cookieName(formCode) + '=' + encodeURIComponent(authData.access_token) + '; path=/; SameSite=Lax';
        return authData;
    }

    function clearAuthData(formCode) {
        if (formCode) {
            window.localStorage.removeItem(storageKey(formCode));
            document.cookie = cookieName(formCode) + '=; path=/; max-age=0; SameSite=Lax';
        }
    }

    async function login(formCode, loginValue, password) {
        const result = await postJSON('/offline/auth/login', {
            form_code: formCode,
            login: loginValue,
            password,
        });
        if (!result || !result.ok) {
            throw new Error((result && result.error) || 'No se pudo autenticar.');
        }
        return setAuthData(formCode, result);
    }

    async function check(formCode) {
        const authData = getAuthData(formCode);
        if (!authData || !authData.access_token) {
            return null;
        }
        if (isExpired(authData)) {
            clearAuthData(formCode);
            return null;
        }
        if (!navigator.onLine) {
            return authData;
        }
        const result = await postJSON('/offline/auth/check', {
            form_code: formCode,
            access_token: authData.access_token,
        }, authData.access_token);
        if (!result || !result.ok) {
            clearAuthData(formCode);
            return null;
        }
        return authData;
    }

    async function logout(formCode) {
        const authData = getAuthData(formCode);
        clearAuthData(formCode);
        if (navigator.onLine) {
            try {
                await postJSON('/offline/auth/logout', {}, authData && authData.access_token);
            } catch (_) { /* Stateless logout; local removal is enough. */ }
        }
        return true;
    }

    async function ensureAuthenticated(form) {
        if (!isExternalAuthRequired(form)) {
            return null;
        }
        const formCode = form.dataset.formCode;
        if (!formCode) {
            throw new Error('El formulario no tiene data-form-code definido.');
        }
        const authData = await check(formCode);
        if (!authData) {
            throw new Error('Debe autenticarse antes de usar este formulario.');
        }
        return authData;
    }

    window.ZOfflineAuth = {
        login,
        check,
        logout,
        getAuthData,
        setAuthData,
        clearAuthData,
        isExpired,
        isExternalAuthRequired,
        ensureAuthenticated,
    };
})();

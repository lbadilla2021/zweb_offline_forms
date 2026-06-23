(function () {
    'use strict';

    const DB_NAME = 'zweb_offline_forms';
    const DB_VERSION = 1;
    const STORE = 'submissions';

    // Singleton DB connection — avoids opening a new connection on every operation.
    let _dbPromise = null;

    function openDB() {
        if (_dbPromise) return _dbPromise;
        _dbPromise = new Promise((resolve, reject) => {
            const req = indexedDB.open(DB_NAME, DB_VERSION);

            req.onupgradeneeded = function (event) {
                const db = event.target.result;
                if (!db.objectStoreNames.contains(STORE)) {
                    const store = db.createObjectStore(STORE, { keyPath: 'local_uuid' });
                    store.createIndex('status', 'status', { unique: false });
                    store.createIndex('form_code', 'form_code', { unique: false });
                    store.createIndex('created_at', 'created_at', { unique: false });
                }
            };

            req.onsuccess = () => resolve(req.result);
            req.onerror = () => {
                _dbPromise = null; // allow retry on next call
                reject(req.error);
            };
        });
        return _dbPromise;
    }

    function txStore(db, mode) {
        return db.transaction(STORE, mode).objectStore(STORE);
    }

    async function put(record) {
        if (!record || typeof record.local_uuid === 'undefined') {
            throw new Error('ZOfflineDB.put: record must have a local_uuid');
        }
        const db = await openDB();
        return new Promise((resolve, reject) => {
            const req = txStore(db, 'readwrite').put(record);
            req.onsuccess = () => resolve(record);
            req.onerror = () => reject(req.error);
        });
    }

    async function getAllByStatus(status) {
        const db = await openDB();
        return new Promise((resolve, reject) => {
            const req = txStore(db, 'readonly').index('status').getAll(status);
            req.onsuccess = () => resolve(req.result || []);
            req.onerror = () => reject(req.error);
        });
    }

    async function deleteRecord(local_uuid) {
        const db = await openDB();
        return new Promise((resolve, reject) => {
            const req = txStore(db, 'readwrite').delete(local_uuid);
            req.onsuccess = () => resolve();
            req.onerror = () => reject(req.error);
        });
    }

    window.ZOfflineDB = {
        openDB,
        put,
        getAllByStatus,
        deleteRecord,
    };
})();

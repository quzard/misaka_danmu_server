import { apiFetch } from '../api.js';

// DOM Elements
// These are now initialized only when the view is first shown.
let danmakuOutputForm, limitInput, aggregationToggle, saveMessage;
let isListenerAttached = false; // Flag to prevent adding the same listener multiple times

function initializeElements() {
    danmakuOutputForm = document.getElementById('danmaku-output-form');
    limitInput = document.getElementById('danmaku-limit-input');
    aggregationToggle = document.getElementById('danmaku-aggregation-toggle');
    saveMessage = document.getElementById('danmaku-control-save-message');
}

async function loadSettings() {
    // The elements are initialized before this is called, but we add a check for robustness.
    if (!saveMessage) {
        // This check prevents errors if the view somehow fails to initialize.
        console.error("Cannot load settings because the view elements are not available.");
        return;
    }
    saveMessage.textContent = '';
    saveMessage.className = 'message';
    
    try {
        const [limitData, aggregationData] = await Promise.all([
            apiFetch('/api/ui/config/danmaku_output_limit_per_source'),
            apiFetch('/api/ui/config/danmaku_aggregation_enabled')
        ]);

        limitInput.value = limitData.value || '-1';
        aggregationToggle.checked = (aggregationData.value || 'true').toLowerCase() === 'true';

    } catch (error) {
        saveMessage.textContent = `加载设置失败: ${error.message}`;
        saveMessage.classList.add('error');
    }
}

async function handleSaveSettings(e) {
    e.preventDefault();
    // Re-check elements in case of any unexpected state change.
    if (!danmakuOutputForm) {
        console.error("Cannot save settings because the form element is not available.");
        return;
    }
    saveMessage.textContent = '保存中...';
    saveMessage.className = 'message';

    const saveBtn = danmakuOutputForm.querySelector('button[type="submit"]');
    saveBtn.disabled = true;
    saveBtn.textContent = '保存中...';

    const limitPayload = { value: limitInput.value };
    const aggregationPayload = { value: aggregationToggle.checked.toString() };

    try {
        await Promise.all([
            apiFetch('/api/ui/config/danmaku_output_limit_per_source', {
                method: 'PUT',
                body: JSON.stringify(limitPayload)
            }),
            apiFetch('/api/ui/config/danmaku_aggregation_enabled', {
                method: 'PUT',
                body: JSON.stringify(aggregationPayload)
            })
        ]);
        saveMessage.textContent = '设置已成功保存！';
        saveMessage.classList.add('success');
    } catch (error) {
        saveMessage.textContent = `保存失败: ${error.message}`;
        saveMessage.classList.add('error');
    } finally {
        saveBtn.disabled = false;
        saveBtn.textContent = '保存设置';
    }
}

export function setupDanmakuControlEventsListeners() {
    // This function is called once on page load. It sets up a listener
    // that will initialize the view's elements and event handlers
    // the first time the view is shown.
    document.addEventListener('viewchange', (e) => {
        if (e.detail.viewId === 'danmaku-control-view') {
            // Initialize elements and attach listener only once.
            if (!isListenerAttached) {
                initializeElements();
                if (danmakuOutputForm) {
                    danmakuOutputForm.addEventListener('submit', handleSaveSettings);
                    isListenerAttached = true;
                }
            }
            loadSettings();
        }
    });
}

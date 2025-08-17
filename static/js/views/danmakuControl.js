import { apiFetch } from '../api.js';

// DOM Elements
let danmakuOutputForm, limitInput, aggregationToggle, saveMessage;
let isListenerAttached = false; // Flag to prevent adding the same listener multiple times

function initializeElements() {
    danmakuOutputForm = document.getElementById('danmaku-output-form');
    limitInput = document.getElementById('danmaku-limit-input');
    aggregationToggle = document.getElementById('danmaku-aggregation-toggle');
    saveMessage = document.getElementById('danmaku-control-save-message');
}

async function loadSettings() {
    // Defensive check in case the view is not fully rendered
    if (!saveMessage || !limitInput || !aggregationToggle) {
        console.error("Danmaku control view elements not found. Cannot load settings.");
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
    // Defensive check
    if (!danmakuOutputForm || !saveMessage || !limitInput || !aggregationToggle) {
        console.error("Danmaku control view elements not found. Cannot save settings.");
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
    // This function is called once on page load.
    // We set up a listener that will initialize elements and attach event handlers
    // only when the specific view is shown.
    document.addEventListener('viewchange', (e) => {
        if (e.detail.viewId === 'danmaku-control-view') {
            initializeElements();

            // Add the submit listener only once to avoid duplicates.
            if (danmakuOutputForm && !isListenerAttached) {
                danmakuOutputForm.addEventListener('submit', handleSaveSettings);
                isListenerAttached = true;
            }

            loadSettings();
        }
    });
}

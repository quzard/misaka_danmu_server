import { apiFetch } from '../api.js';

// DOM Elements
let danmakuOutputForm, limitInput, aggregationToggle, saveMessage;

function initializeElements() {
    danmakuOutputForm = document.getElementById('danmaku-output-form');
    limitInput = document.getElementById('danmaku-limit-input');
    aggregationToggle = document.getElementById('danmaku-aggregation-toggle');
    saveMessage = document.getElementById('danmaku-control-save-message');
}

async function loadSettings() {
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
    initializeElements();
    // 确保元素存在后再添加事件监听，防止在页面加载异常时报错
    if (danmakuOutputForm) { 
        danmakuOutputForm.addEventListener('submit', handleSaveSettings);
    }
    document.addEventListener('viewchange', (e) => {
        if (e.detail.viewId === 'danmaku-control-view') {
            loadSettings();
        }
    });
}

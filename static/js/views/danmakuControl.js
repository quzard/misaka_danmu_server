import { apiFetch } from '../api.js';

// DOM Elements
let danmakuOutputForm, limitInput, aggregationToggle, saveMessage;
let danmakuControlSubNav, danmakuControlSubViews;

function initializeElements() {
    danmakuControlSubNav = document.querySelector('#danmaku-control-view .settings-sub-nav');
    danmakuControlSubViews = document.querySelectorAll('#danmaku-control-view .settings-subview');

    danmakuOutputForm = document.getElementById('danmaku-output-form');
    limitInput = document.getElementById('danmaku-limit-input');
    aggregationToggle = document.getElementById('danmaku-aggregation-toggle');
    saveMessage = document.getElementById('danmaku-control-save-message');
}

function handleSubNavClick(e) {
    const subNavBtn = e.target.closest('.sub-nav-btn');
    if (!subNavBtn || !danmakuControlSubNav) return;

    const subViewId = subNavBtn.getAttribute('data-subview');
    if (!subViewId) return;

    danmakuControlSubNav.querySelectorAll('.sub-nav-btn').forEach(btn => btn.classList.remove('active'));
    subNavBtn.classList.add('active');

    if (danmakuControlSubViews) {
        danmakuControlSubViews.forEach(view => view.classList.add('hidden'));
    }
    const targetSubView = document.getElementById(subViewId);
    if (targetSubView) {
        targetSubView.classList.remove('hidden');
    }

    if (subViewId === 'output-control-subview') {
        loadSettings();
    }
}

async function loadSettings() {
    if (!saveMessage || !limitInput || !aggregationToggle) {
        console.error("Danmaku control view elements not found when trying to load settings.");
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
    if (!danmakuOutputForm || !saveMessage || !limitInput || !aggregationToggle) {
        console.error("Cannot save settings because the view elements are not available.");
        return;
    }
    saveMessage.textContent = '保存中...';
    saveMessage.className = 'message';

    const saveBtn = danmakuOutputForm.querySelector('button[type="submit"]');
    if (saveBtn) {
        saveBtn.disabled = true;
        saveBtn.textContent = '保存中...';
    }

    const limitPayload = { value: limitInput.value };
    const aggregationPayload = { value: aggregationToggle.checked.toString() };

    try {
        await apiFetch('/api/ui/config/danmaku_output_limit_per_source', { method: 'PUT', body: JSON.stringify(limitPayload) });
        await apiFetch('/api/ui/config/danmaku_aggregation_enabled', { method: 'PUT', body: JSON.stringify(aggregationPayload) });
        saveMessage.textContent = '设置已成功保存！';
        saveMessage.classList.add('success');
    } catch (error) {
        saveMessage.textContent = `保存失败: ${error.message}`;
        saveMessage.classList.add('error');
    } finally {
        if (saveBtn) {
            saveBtn.disabled = false;
            saveBtn.textContent = '保存设置';
        }
    }
}

export function setupDanmakuControlEventsListeners() {
    initializeElements();

    if (danmakuControlSubNav) danmakuControlSubNav.addEventListener('click', handleSubNavClick);
    if (danmakuOutputForm) danmakuOutputForm.addEventListener('submit', handleSaveSettings);

    document.addEventListener('viewchange', (e) => {
        if (e.detail.viewId === 'danmaku-control-view') {
            const firstSubNavBtn = danmakuControlSubNav ? danmakuControlSubNav.querySelector('.sub-nav-btn') : null;
            if (firstSubNavBtn) {
                firstSubNavBtn.click();
            }
        }
    });
}

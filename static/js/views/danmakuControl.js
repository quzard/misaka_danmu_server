import { apiFetch } from '../api.js';

/**
 * Sets up all event listeners and logic for the Danmaku Control view.
 * This function is designed to be robust by initializing elements and listeners
 * only when the view is first accessed, avoiding race conditions on page load.
 */
export function setupDanmakuControlEventsListeners() {
    let isInitialized = false;

    // DOM elements are scoped to this setup function and initialized lazily.
    let danmakuOutputForm, limitInput, aggregationToggle, saveMessage;
    let danmakuControlSubNav;

    /**
     * Finds all necessary DOM elements and attaches the primary event listeners.
     * This is called only once when the view is first shown.
     */
    function initializeAndAttachListeners() {
        danmakuControlSubNav = document.querySelector('#danmaku-control-view .settings-sub-nav');
        danmakuOutputForm = document.getElementById('danmaku-output-form');
        limitInput = document.getElementById('danmaku-limit-input');
        aggregationToggle = document.getElementById('danmaku-aggregation-toggle');
        saveMessage = document.getElementById('danmaku-control-save-message');

        if (!danmakuControlSubNav || !danmakuOutputForm) {
            console.error("Danmaku control view is missing essential elements. Initialization failed.");
            return;
        }

        danmakuControlSubNav.addEventListener('click', handleSubNavClick);
        danmakuOutputForm.addEventListener('submit', handleSaveSettings);
        
        isInitialized = true;
    }

    /**
     * Handles clicks on the sub-navigation tabs.
     * Currently, there's only one tab, but this structure allows for future expansion.
     */
    function handleSubNavClick(e) {
        const subNavBtn = e.target.closest('.sub-nav-btn');
        if (!subNavBtn) return;

        const subViewId = subNavBtn.getAttribute('data-subview');
        if (!subViewId) return;

        danmakuControlSubNav.querySelectorAll('.sub-nav-btn').forEach(btn => btn.classList.remove('active'));
        subNavBtn.classList.add('active');
        
        document.querySelectorAll('#danmaku-control-view .settings-subview').forEach(view => {
            view.classList.toggle('hidden', view.id !== subViewId);
        });

        if (subViewId === 'output-control-subview') {
            loadSettings();
        }
    }

    /**
     * Fetches the current settings from the backend and populates the form.
     */
    async function loadSettings() {
        if (!saveMessage || !limitInput || !aggregationToggle) {
            console.error("Cannot load settings: required elements are not available.");
            return;
        }
        saveMessage.textContent = '';
        saveMessage.className = 'message';

        try {
            const [limitData, aggregationData] = await Promise.all([
                apiFetch('/api/ui/config/danmaku_output_limit_per_source'),
                apiFetch('/api/ui/config/danmaku_aggregation_enabled')
            ]);
            limitInput.value = limitData.value ?? '-1';
            aggregationToggle.checked = (aggregationData.value ?? 'true').toLowerCase() === 'true';
        } catch (error) {
            saveMessage.textContent = `加载设置失败: ${error.message}`;
            saveMessage.classList.add('error');
        }
    }

    /**
     * Handles the form submission to save the settings.
     */
    async function handleSaveSettings(e) {
        e.preventDefault();
        if (!danmakuOutputForm || !saveMessage || !limitInput || !aggregationToggle) {
            console.error("Cannot save settings: required elements are not available.");
            return;
        }
        saveMessage.textContent = '保存中...';
        saveMessage.className = 'message';

        const saveBtn = danmakuOutputForm.querySelector('button[type="submit"]');
        if (saveBtn) {
            saveBtn.disabled = true;
            saveBtn.textContent = '保存中...';
        }

        try {
            const limitPayload = { value: limitInput.value };
            await apiFetch('/api/ui/config/danmaku_output_limit_per_source', { method: 'PUT', body: JSON.stringify(limitPayload) });

            const aggregationPayload = { value: aggregationToggle.checked.toString() };
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

    // The main event listener that orchestrates the view's lifecycle.
    document.addEventListener('viewchange', (e) => {
        if (e.detail.viewId === 'danmaku-control-view') {
            // Initialize only once.
            if (!isInitialized) {
                initializeAndAttachListeners();
            }
            
            // Always trigger the data load when the view is shown by simulating a click.
            const firstSubNavBtn = danmakuControlSubNav ? danmakuControlSubNav.querySelector('.sub-nav-btn') : null;
            if (firstSubNavBtn) {
                firstSubNavBtn.click();
            }
        }
    });
}

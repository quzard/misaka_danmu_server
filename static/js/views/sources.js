import { apiFetch } from '../api.js';

// DOM Elements
let sourcesSubNav, sourcesSubViews;
let danmakuSourcesList, saveDanmakuSourcesBtn, toggleDanmakuSourceBtn, moveDanmakuSourceUpBtn, moveDanmakuSourceDownBtn;
let metadataSourcesList, saveMetadataSourcesBtn, moveMetadataSourceUpBtn, moveMetadataSourceDownBtn;

function initializeElements() {
    sourcesSubNav = document.querySelector('#sources-view .settings-sub-nav');
    sourcesSubViews = document.querySelectorAll('#sources-view .settings-subview');

    danmakuSourcesList = document.getElementById('danmaku-sources-list');
    saveDanmakuSourcesBtn = document.getElementById('save-danmaku-sources-btn');
    toggleDanmakuSourceBtn = document.getElementById('toggle-danmaku-source-btn');
    moveDanmakuSourceUpBtn = document.getElementById('move-danmaku-source-up-btn');
    moveDanmakuSourceDownBtn = document.getElementById('move-danmaku-source-down-btn');

    metadataSourcesList = document.getElementById('metadata-sources-list');
    saveMetadataSourcesBtn = document.getElementById('save-metadata-sources-btn');
    moveMetadataSourceUpBtn = document.getElementById('move-metadata-source-up-btn');
    moveMetadataSourceDownBtn = document.getElementById('move-metadata-source-down-btn');
}

function handleSourcesSubNav(e) {
    const subNavBtn = e.target.closest('.sub-nav-btn');
    if (!subNavBtn) return;

    const subViewId = subNavBtn.getAttribute('data-subview');
    if (!subViewId) return;

    sourcesSubNav.querySelectorAll('.sub-nav-btn').forEach(btn => btn.classList.remove('active'));
    subNavBtn.classList.add('active');

    sourcesSubViews.forEach(view => view.classList.add('hidden'));
    const targetSubView = document.getElementById(subViewId);
    if (targetSubView) targetSubView.classList.remove('hidden');

    if (subViewId === 'danmaku-sources-subview') loadDanmakuSources();
    if (subViewId === 'metadata-sources-subview') loadMetadataSources();
}

async function loadDanmakuSources() {
    if (!danmakuSourcesList) return;
    danmakuSourcesList.innerHTML = '<li>加载中...</li>';
    try {
        const settings = await apiFetch('/api/ui/scrapers');
        renderDanmakuSources(settings);
    } catch (error) {
        danmakuSourcesList.innerHTML = `<li class="error">加载失败: ${(error.message || error)}</li>`;
    }
}

function renderDanmakuSources(settings) {
    danmakuSourcesList.innerHTML = '';
    settings.forEach(setting => {
        const li = document.createElement('li');
        li.dataset.providerName = setting.provider_name;
        li.dataset.isEnabled = setting.is_enabled;

        const nameSpan = document.createElement('span');
        nameSpan.className = 'source-name';
        nameSpan.textContent = setting.provider_name;
        li.appendChild(nameSpan);

        // 如果源有可配置字段或支持日志记录，则显示配置按钮
        if ((setting.configurable_fields && Object.keys(setting.configurable_fields).length > 0) || setting.is_loggable) {
            const configBtn = document.createElement('button');
            configBtn.className = 'action-btn config-btn';
            configBtn.title = `配置 ${setting.provider_name}`;
            configBtn.textContent = '⚙️';
            configBtn.dataset.action = 'configure';
            configBtn.dataset.providerName = setting.provider_name;
            // 将字段信息存储为JSON字符串以便后续使用
            configBtn.dataset.fields = JSON.stringify(setting.configurable_fields);
            configBtn.dataset.isLoggable = setting.is_loggable;
            li.appendChild(configBtn);
        }

        const statusIcon = document.createElement('span');
        statusIcon.className = 'status-icon';
        statusIcon.textContent = setting.is_enabled ? '✅' : '❌';
        li.appendChild(statusIcon);

        li.addEventListener('click', (e) => {
            // 如果点击的是配置按钮，则不触发选中事件
            if (e.target.closest('.config-btn')) return;
            danmakuSourcesList.querySelectorAll('li').forEach(item => item.classList.remove('selected'));
            li.classList.add('selected');
        });
        danmakuSourcesList.appendChild(li);
    });
}

async function handleSaveDanmakuSources() {
    const settingsToSave = [];
    danmakuSourcesList.querySelectorAll('li').forEach((li, index) => {
        settingsToSave.push({
            provider_name: li.dataset.providerName,
            is_enabled: li.dataset.isEnabled === 'true',
            display_order: index + 1,
        });
    });
    try {
        saveDanmakuSourcesBtn.disabled = true;
        saveDanmakuSourcesBtn.textContent = '保存中...';
        await apiFetch('/api/ui/scrapers', {
            method: 'PUT',
            body: JSON.stringify(settingsToSave),
        });
        alert('搜索源设置已保存！');
        loadDanmakuSources();
    } catch (error) {
        alert(`保存失败: ${(error.message || error)}`);
    } finally {
        saveDanmakuSourcesBtn.disabled = false;
        saveDanmakuSourcesBtn.textContent = '保存设置';
    }
}

function handleToggleDanmakuSource() {
    const selected = danmakuSourcesList.querySelector('li.selected');
    if (!selected) return;
    const isEnabled = selected.dataset.isEnabled === 'true';
    selected.dataset.isEnabled = !isEnabled;
    selected.querySelector('.status-icon').textContent = !isEnabled ? '✅' : '❌';
}

function handleMoveDanmakuSource(direction) {
    const selected = danmakuSourcesList.querySelector('li.selected');
    if (!selected) return;
    if (direction === 'up' && selected.previousElementSibling) {
        danmakuSourcesList.insertBefore(selected, selected.previousElementSibling);
    } else if (direction === 'down' && selected.nextElementSibling) {
        danmakuSourcesList.insertBefore(selected.nextElementSibling, selected);
    }
}

async function loadMetadataSources() {
    if (!metadataSourcesList) return;
    metadataSourcesList.innerHTML = '<li>加载中...</li>';
    try {
        // This should be a new endpoint in the future, for now we hardcode it
        const sources = [
            { name: 'TMDB', status: '已配置' },
            { name: 'Bangumi', status: '已授权' }
        ];
        renderMetadataSources(sources);
    } catch (error) {
        metadataSourcesList.innerHTML = `<li class="error">加载失败: ${(error.message || error)}</li>`;
    }
}

function renderMetadataSources(sources) {
    metadataSourcesList.innerHTML = '';
    sources.forEach(source => {
        const li = document.createElement('li');
        li.dataset.sourceName = source.name;
        li.textContent = source.name;
        const statusIcon = document.createElement('span');
        statusIcon.className = 'status-icon';
        statusIcon.textContent = source.status;
        li.appendChild(statusIcon);
        li.addEventListener('click', () => {
            metadataSourcesList.querySelectorAll('li').forEach(item => item.classList.remove('selected'));
            li.classList.add('selected');
        });
        metadataSourcesList.appendChild(li);
    });
}

function handleMoveMetadataSource(direction) {
    const selected = metadataSourcesList.querySelector('li.selected');
    if (!selected) return;
    if (direction === 'up' && selected.previousElementSibling) {
        metadataSourcesList.insertBefore(selected, selected.previousElementSibling);
    } else if (direction === 'down' && selected.nextElementSibling) {
        metadataSourcesList.insertBefore(selected.nextElementSibling, selected);
    }
}

function handleSaveMetadataSources() {
    // In the future, this would save the order to the backend.
    alert('元信息搜索源的排序功能暂未实现后端保存。');
}

async function handleDanmakuSourceAction(e) {
    const button = e.target.closest('.config-btn');
    if (!button || button.dataset.action !== 'configure') return;

    const providerName = button.dataset.providerName;
    const isLoggable = button.dataset.isLoggable === 'true';
    const fields = JSON.parse(button.dataset.fields);
    
    showScraperConfigModal(providerName, fields, isLoggable);
}

let currentProviderForModal = null;

function showScraperConfigModal(providerName, fields, isLoggable) {
    currentProviderForModal = providerName;
    const modal = document.getElementById('generic-modal');
    const modalTitle = document.getElementById('modal-title');
    const modalBody = document.getElementById('modal-body');

    modalTitle.textContent = `配置: ${providerName}`;
    modalBody.innerHTML = '<p>加载中...</p>';
    modal.classList.remove('hidden');

    apiFetch(`/api/ui/scrapers/${providerName}/config`)
        .then(currentConfig => {
            modalBody.innerHTML = ''; // 清空加载提示

            // 渲染文本字段（如果存在）
            if (fields && Object.keys(fields).length > 0) {
                const helpText = document.createElement('p');
                helpText.className = 'modal-help-text';
                if (providerName === 'gamer') {
                    helpText.innerHTML = `仅当无法正常搜索时才需要填写。请先尝试清空配置并保存，如果问题依旧，再从 <a href="https://ani.gamer.com.tw/" target="_blank" rel="noopener noreferrer">巴哈姆特动画疯</a> 获取最新的 User-Agent 和 Cookie。`;
                } else {
                    helpText.textContent = `请为 ${providerName} 源填写以下配置信息。`;
                }
                modalBody.appendChild(helpText);

                Object.entries(fields).forEach(([key, label]) => {
                    const value = currentConfig[key] || '';
                    const formRow = document.createElement('div');
                    formRow.className = 'form-row';
                    
                    const labelEl = document.createElement('label');
                    labelEl.htmlFor = `config-input-${key}`;
                    labelEl.textContent = label;
                    
                    const isCookie = key.toLowerCase().includes('cookie');
                    const inputEl = document.createElement(isCookie ? 'textarea' : 'input');
                    if (!isCookie) inputEl.type = 'text';
                    inputEl.id = `config-input-${key}`;
                    inputEl.name = key;
                    inputEl.value = value;
                    if (isCookie) inputEl.rows = 4;
                    
                    formRow.appendChild(labelEl);
                    formRow.appendChild(inputEl);
                    modalBody.appendChild(formRow);
                });
            }

            // 渲染日志开关（如果支持）
            if (isLoggable) {
                const logKey = `scraper_${providerName}_log_responses`;
                const isEnabled = currentConfig[logKey] === 'true';

                const logSection = document.createElement('div');
                logSection.className = 'form-row';
                logSection.style.marginTop = '20px';
                logSection.style.paddingTop = '15px';
                logSection.style.borderTop = '1px solid var(--border-color)';

                const labelEl = document.createElement('label');
                labelEl.htmlFor = 'config-input-log-responses';
                labelEl.textContent = '记录原始响应';
                
                const inputEl = document.createElement('input');
                inputEl.type = 'checkbox';
                inputEl.id = 'config-input-log-responses';
                inputEl.name = logKey;
                inputEl.checked = isEnabled;
                
                const helpText = document.createElement('p');
                helpText.className = 'modal-help-text';
                helpText.style.margin = '0 0 0 15px';
                helpText.style.padding = '5px 10px';
                helpText.textContent = '启用后，此源的所有API请求的原始响应将被记录到 config/logs/scraper_responses.log 文件中，用于调试。';

                logSection.appendChild(labelEl);
                logSection.appendChild(inputEl);
                logSection.appendChild(helpText);
                modalBody.appendChild(logSection);
            }

            // 如果是Bilibili，添加登录部分
            if (providerName === 'bilibili') {
                // 修正：调整HTML结构以实现垂直居中布局
                const biliLoginSectionHTML = `
                    <div id="bili-login-section" style="text-align: center;">
                        <div id="bili-login-status">正在检查登录状态...</div>
                        <div id="bili-login-controls"> <!-- 新增容器用于居中 -->
                            <button type="button" id="bili-login-btn" class="secondary-btn">扫码登录</button>
                            <div id="bili-qrcode-container"></div>
                        </div>
                    </div>
                `;
                modalBody.insertAdjacentHTML('beforeend', biliLoginSectionHTML);
            }
        })
        .catch(error => {
            modalBody.innerHTML = `<p class="error">加载配置失败: ${error.message}</p>`;
        })
        .finally(() => {
            // 在所有内容加载完毕后，为Bilibili登录按钮绑定事件
            if (providerName === 'bilibili') setupBiliLoginListeners();
        });
}

function hideScraperConfigModal() {
    document.getElementById('generic-modal').classList.add('hidden');
    currentProviderForModal = null;
}

async function handleSaveScraperConfig() {
    if (!currentProviderForModal) return;
    const payload = {};
    // 获取文本字段的值
    document.getElementById('modal-body').querySelectorAll('input[type="text"], textarea').forEach(input => {
        payload[input.name] = input.value.trim();
    });
    // 获取日志开关的值
    const logCheckbox = document.getElementById('config-input-log-responses');
    if (logCheckbox) {
        payload[logCheckbox.name] = logCheckbox.checked ? 'true' : 'false';
    }

    await apiFetch(`/api/ui/scrapers/${currentProviderForModal}/config`, { method: 'PUT', body: JSON.stringify(payload) });
    hideScraperConfigModal();
    alert('配置已保存！');
}

let biliPollInterval = null;

function stopBiliPolling() {
    if (biliPollInterval) {
        clearInterval(biliPollInterval);
        biliPollInterval = null;
    }
}

async function checkBiliLoginStatus() {
    const statusDiv = document.getElementById('bili-login-status');
    if (!statusDiv) return;
    statusDiv.textContent = '正在检查登录状态...';
    statusDiv.className = '';
    try {
        const info = await apiFetch('/api/ui/scrapers/bilibili/actions/get_login_info', { method: 'POST' });
        if (info.isLogin) {
            statusDiv.textContent = `已登录: ${info.uname} (Lv.${info.level})`;
            statusDiv.classList.add('success');
            document.getElementById('bili-login-btn').textContent = '注销';
        } else {
            statusDiv.textContent = '当前未登录。';
            document.getElementById('bili-login-btn').textContent = '扫码登录';
        }
    } catch (error) {
        statusDiv.textContent = `检查状态失败: ${error.message}`;
        statusDiv.classList.add('error');
    }
}

async function handleBiliLoginClick() {
    const loginBtn = document.getElementById('bili-login-btn');
    const statusDiv = document.getElementById('bili-login-status');
    const qrContainer = document.getElementById('bili-qrcode-container');
    if (!loginBtn || !statusDiv || !qrContainer) return;

    // 检查当前是登录还是注销
    if (loginBtn.textContent === '注销') {
        if (confirm('确定要注销当前的Bilibili登录吗？')) {
            await apiFetch('/api/ui/scrapers/bilibili/actions/logout', { method: 'POST' });
            await checkBiliLoginStatus(); // 刷新状态
            loadDanmakuSources(); // 重新加载源列表以更新主视图中的状态
        }
        return;
    }

    // --- 以下是登录流程 ---
    stopBiliPolling();
    loginBtn.disabled = true;
    statusDiv.textContent = '正在获取二维码...';
    qrContainer.innerHTML = '';

    try {
        const qrData = await apiFetch('/api/ui/scrapers/bilibili/actions/generate_qrcode', { method: 'POST' });

        // 使用本地库生成二维码，避免外部依赖和网络问题
        new QRCode(qrContainer, {
            text: qrData.url,
            width: 180,
            height: 180,
            colorDark: "#000000",
            colorLight: "#ffffff",
            correctLevel: QRCode.CorrectLevel.H
        });

        // 新增：添加一个刷新按钮
        const refreshBtn = document.createElement('button');
        refreshBtn.className = 'secondary-btn';
        refreshBtn.textContent = '刷新二维码';
        refreshBtn.addEventListener('click', handleBiliLoginClick); // 点击时重新调用此函数
        qrContainer.appendChild(refreshBtn);

        statusDiv.textContent = '请使用Bilibili手机客户端扫描二维码。';

        biliPollInterval = setInterval(async () => {
            try {
                const pollPayload = { qrcode_key: qrData.qrcode_key };
                const pollRes = await apiFetch('/api/ui/scrapers/bilibili/actions/poll_login', { method: 'POST', body: JSON.stringify(pollPayload) });
                if (pollRes.code === 0) { // 登录成功
                    stopBiliPolling();
                    statusDiv.textContent = '登录成功！';
                    statusDiv.classList.add('success');
                    qrContainer.innerHTML = '';
                    setTimeout(() => { hideScraperConfigModal(); loadDanmakuSources(); }, 1500);
                } else if (pollRes.code === 86038) { // 二维码失效
                    stopBiliPolling();
                    statusDiv.textContent = '二维码已失效，请重新获取。';
                    statusDiv.classList.add('error');
                    // 使过期的二维码变暗，提示用户刷新
                    const qrImgEl = qrContainer.querySelector('img');
                    if (qrImgEl) {
                        qrImgEl.classList.add('expired');
                    }
                } else if (pollRes.code === 86090) { // 已扫描，待确认
                    statusDiv.textContent = '已扫描，请在手机上确认登录。';
                }
            } catch (pollError) {
                stopBiliPolling();
                statusDiv.textContent = `轮询失败: ${pollError.message}`;
                statusDiv.classList.add('error');
            }
        }, 2000);
    } catch (error) {
        statusDiv.textContent = `获取二维码失败: ${error.message}`;
        statusDiv.classList.add('error');
    } finally {
        loginBtn.disabled = false;
    }
}

function setupBiliLoginListeners() {
    const loginBtn = document.getElementById('bili-login-btn');
    if (loginBtn) {
        loginBtn.addEventListener('click', handleBiliLoginClick);
        checkBiliLoginStatus();
    }
    // 确保在弹窗关闭时停止轮询
    document.getElementById('modal-close-btn').addEventListener('click', stopBiliPolling);
    document.getElementById('modal-cancel-btn').addEventListener('click', stopBiliPolling);
}

export function setupSourcesEventListeners() {
    initializeElements();
    sourcesSubNav.addEventListener('click', handleSourcesSubNav);

    danmakuSourcesList.addEventListener('click', handleDanmakuSourceAction);
    saveDanmakuSourcesBtn.addEventListener('click', handleSaveDanmakuSources);
    toggleDanmakuSourceBtn.addEventListener('click', handleToggleDanmakuSource);
    moveDanmakuSourceUpBtn.addEventListener('click', () => handleMoveDanmakuSource('up'));
    moveDanmakuSourceDownBtn.addEventListener('click', () => handleMoveDanmakuSource('down'));

    saveMetadataSourcesBtn.addEventListener('click', handleSaveMetadataSources);
    moveMetadataSourceUpBtn.addEventListener('click', () => handleMoveMetadataSource('up'));
    moveMetadataSourceDownBtn.addEventListener('click', () => handleMoveMetadataSource('down'));

    // Modal event listeners
    document.getElementById('modal-close-btn').addEventListener('click', hideScraperConfigModal);
    document.getElementById('modal-cancel-btn').addEventListener('click', hideScraperConfigModal);
    document.getElementById('modal-save-btn').addEventListener('click', handleSaveScraperConfig);

    document.addEventListener('viewchange', (e) => {
        if (e.detail.viewId === 'sources-view') {
            const firstSubNavBtn = sourcesSubNav.querySelector('.sub-nav-btn');
            if (firstSubNavBtn) firstSubNavBtn.click();
        }
    });
}

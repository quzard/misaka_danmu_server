import { checkLogin, setupAuthEventListeners } from './auth.js';
import { setupHomeEventListeners } from './views/home.js';
import { setupLibraryEventListeners } from './views/library.js';
import { setupEditAnimeEventListeners } from './views/editAnime.js';
import { setupTasksEventListeners } from './views/tasks.js';
import { setupTokensEventListeners } from './views/tokens.js';
import { setupSourcesEventListeners } from './views/sources.js';
import { setupSettingsEventListeners } from './views/settings.js';
import { switchView, setActiveSidebar } from './ui.js';
import { apiFetch } from './api.js';

let logRefreshInterval = null;

async function refreshServerLogs() {
    const logOutput = document.getElementById('log-output');
    if (!localStorage.getItem('danmu_api_token') || !logOutput) return;
    try {
        const logs = await apiFetch('/api/ui/logs');
        logOutput.textContent = logs.join('\n');
    } catch (error) {
        console.error("刷新日志失败:", error.message);
    }
}

function startLogRefresh() {
    refreshServerLogs();
    if (logRefreshInterval) clearInterval(logRefreshInterval);
    logRefreshInterval = setInterval(refreshServerLogs, 3000);
}

function stopLogRefresh() {
    if (logRefreshInterval) clearInterval(logRefreshInterval);
    logRefreshInterval = null;
}

document.addEventListener('DOMContentLoaded', () => {
    // Setup all event listeners from different modules
    setupAuthEventListeners();
    setupHomeEventListeners();
    setupLibraryEventListeners();
    setupEditAnimeEventListeners();
    setupTasksEventListeners();
    setupTokensEventListeners();
    setupSourcesEventListeners();
    setupSettingsEventListeners();

    // Sidebar navigation
    document.getElementById('sidebar').addEventListener('click', (e) => {
        const navLink = e.target.closest('.nav-link');
        if (!navLink) return;
        
        e.preventDefault();
        const viewId = navLink.getAttribute('data-view');
        if (!viewId) return;

        setActiveSidebar(viewId);
        switchView(viewId);

        // Trigger data loading for the new view
        // This uses a custom event system for loose coupling
        document.dispatchEvent(new CustomEvent('viewchange', { detail: { viewId } }));
    });

    // Initial load
    checkLogin();
});

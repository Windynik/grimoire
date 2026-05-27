// API Base URL
const API_BASE = '/api';

// State
let currentJobId = null;
let cacheStatus = null;

// DOM Elements
const views = {
    dashboard: document.getElementById('dashboard-view'),
    cache: document.getElementById('cache-view'),
    process: document.getElementById('process-view'),
    settings: document.getElementById('settings-view')
};

// Initialize app
document.addEventListener('DOMContentLoaded', () => {
    setupNavigation();
    setupCacheManagement();
    setupFileUpload();
    checkCacheStatus();
});

// Navigation
function setupNavigation() {
    const navItems = document.querySelectorAll('.nav-item');

    navItems.forEach(item => {
        item.addEventListener('click', () => {
            const viewName = item.dataset.view;
            switchView(viewName);

            // Update active nav item
            navItems.forEach(nav => nav.classList.remove('active'));
            item.classList.add('active');
        });
    });
}

function switchView(viewName) {
    Object.values(views).forEach(view => view.classList.remove('active'));
    views[viewName].classList.add('active');
}

// Cache Management
function setupCacheManagement() {
    document.getElementById('quick-download').addEventListener('click', downloadCache);
    document.getElementById('download-cache').addEventListener('click', downloadCache);
    document.getElementById('clear-cache').addEventListener('click', clearCache);
}

async function checkCacheStatus() {
    try {
        const response = await fetch(`${API_BASE}/cache/status`);
        cacheStatus = await response.json();

        updateCacheStatusUI(cacheStatus);
    } catch (error) {
        showToast('Error checking cache status', 'error');
    }
}

function updateCacheStatusUI(status) {
    const isReady = status.status === 'ready';

    // Update dashboard
    const statusDot = document.querySelector('.status-dot');
    const statusText = document.querySelector('.status-text');
    const cardCount = document.getElementById('card-count');
    const lastUpdated = document.getElementById('last-updated');
    const quickProcess = document.getElementById('quick-process');

    if (isReady) {
        statusDot.classList.add('ready');
        statusText.textContent = 'Ready';
        cardCount.textContent = status.card_count?.toLocaleString() || '-';
        lastUpdated.textContent = formatDate(status.download_date);
        quickProcess.disabled = false;
    } else {
        statusDot.classList.remove('ready');
        statusText.textContent = 'Cache Missing';
        cardCount.textContent = '-';
        lastUpdated.textContent = '-';
        quickProcess.disabled = true;
    }
}

async function downloadCache() {
    const progressContainer = document.getElementById('download-progress');
    const progressFill = document.getElementById('download-progress-fill');
    const progressText = document.getElementById('download-progress-text');

    progressContainer.style.display = 'block';

    try {
        const response = await fetch(`${API_BASE}/cache/download`, {
            method: 'POST'
        });

        const reader = response.body.getReader();
        const decoder = new TextDecoder();

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            const text = decoder.decode(value);
            const lines = text.split('\n');

            for (const line of lines) {
                if (line.startsWith('data: ')) {
                    const data = JSON.parse(line.substring(6));

                    if (data.percentage !== undefined) {
                        progressFill.style.width = `${data.percentage}%`;
                        progressText.textContent = `${data.percentage}%`;
                    }

                    if (data.status === 'complete') {
                        showToast('Bulk data downloaded successfully!', 'success');
                        await checkCacheStatus();
                        progressContainer.style.display = 'none';
                    }

                    if (data.error) {
                        showToast(data.error, 'error');
                        progressContainer.style.display = 'none';
                    }
                }
            }
        }
    } catch (error) {
        showToast('Error downloading bulk data', 'error');
        progressContainer.style.display = 'none';
    }
}

async function clearCache() {
    if (!confirm('Are you sure you want to clear the cache?')) return;

    try {
        const response = await fetch(`${API_BASE}/cache`, {
            method: 'DELETE'
        });

        if (response.ok) {
            showToast('Cache cleared successfully', 'success');
            await checkCacheStatus();
        }
    } catch (error) {
        showToast('Error clearing cache', 'error');
    }
}

// File Upload and Processing
function setupFileUpload() {
    const uploadZone = document.getElementById('upload-zone');
    const fileInput = document.getElementById('file-input');
    const processAnother = document.getElementById('process-another');
    const downloadResult = document.getElementById('download-result');

    uploadZone.addEventListener('click', () => fileInput.click());
    fileInput.addEventListener('change', handleFileSelect);
    processAnother.addEventListener('click', resetUploadUI);
    downloadResult.addEventListener('click', downloadProcessedFile);

    // Drag and drop
    uploadZone.addEventListener('dragover', (e) => {
        e.preventDefault();
        uploadZone.classList.add('dragover');
    });

    uploadZone.addEventListener('dragleave', () => {
        uploadZone.classList.remove('dragover');
    });

    uploadZone.addEventListener('drop', (e) => {
        e.preventDefault();
        uploadZone.classList.remove('dragover');

        const files = e.dataTransfer.files;
        if (files.length > 0) {
            handleFile(files[0]);
        }
    });
}

function handleFileSelect(e) {
    const file = e.target.files[0];
    if (file) {
        handleFile(file);
    }
}

async function handleFile(file) {
    if (!file.name.endsWith('.csv')) {
        showToast('Please select a CSV file', 'error');
        return;
    }

    // Hide upload zone, show processing
    document.getElementById('upload-zone').style.display = 'none';
    document.getElementById('processing-display').style.display = 'block';

    const formData = new FormData();
    formData.append('file', file);

    try {
        const response = await fetch(`${API_BASE}/process`, {
            method: 'POST',
            body: formData
        });

        const result = await response.json();

        if (response.ok) {
            currentJobId = result.job_id;
            displayResults(result);
        } else {
            showToast('Error processing CSV: ' + result.detail, 'error');
            resetUploadUI();
        }
    } catch (error) {
        showToast('Error uploading file', 'error');
        resetUploadUI();
    }
}

function displayResults(result) {
    document.getElementById('processing-display').style.display = 'none';
    document.getElementById('results-display').style.display = 'block';

    document.getElementById('total-processed').textContent = result.total_processed;
    document.getElementById('success-count').textContent = result.success_count;
    document.getElementById('final-error-count').textContent = result.error_count;
}

function resetUploadUI() {
    document.getElementById('upload-zone').style.display = 'block';
    document.getElementById('processing-display').style.display = 'none';
    document.getElementById('results-display').style.display = 'none';
    document.getElementById('file-input').value = '';
    currentJobId = null;
}

function downloadProcessedFile() {
    if (currentJobId) {
        window.location.href = `${API_BASE}/download/${currentJobId}`;
    }
}

// Utilities
function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;

    container.appendChild(toast);

    setTimeout(() => {
        toast.remove();
    }, 3000);
}

function formatDate(dateString) {
    if (!dateString) return '-';
    const date = new Date(dateString);
    return date.toLocaleDateString() + ' ' + date.toLocaleTimeString();
}

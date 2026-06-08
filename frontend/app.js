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
    viewer: document.getElementById('viewer-view'),
    settings: document.getElementById('settings-view')
};

// Initialize app
document.addEventListener('DOMContentLoaded', () => {
    setupNavigation();
    setupCacheManagement();
    setupFileUpload();
    setupCollectionViewer();
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

    // Auto-load collection when switching to viewer
    if (viewName === 'viewer') {
        // If no current job, try to load from localStorage
        if (!currentJobId) {
            currentJobId = localStorage.getItem('lastJobId');
        }

        if (currentJobId) {
            loadCollectionViewer(currentJobId);
        } else {
            // No collection available
            displayCardGrid([]);
            showToast('No collection found. Process a CSV first!', 'info');
        }
    }
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

    // Update cache management tab details
    const cacheDetails = document.getElementById('cache-details');
    if (cacheDetails) {
        if (isReady) {
            const fileSizeMB = status.file_size_mb || 0;
            cacheDetails.innerHTML = `
                <div class="cache-info">
                    <p><strong>Status:</strong> <span style="color: var(--success)">✓ Ready</span></p>
                    <p><strong>Total Cards:</strong> ${status.card_count?.toLocaleString() || 'N/A'}</p>
                    <p><strong>File Size:</strong> ${fileSizeMB.toFixed(2)} MB</p>
                    <p><strong>Last Downloaded:</strong> ${formatDate(status.download_date)}</p>
                </div>
            `;
        } else {
            cacheDetails.innerHTML = `
                <div class="cache-info">
                    <p><strong>Status:</strong> <span style="color: var(--warning)">⚠ Not Downloaded</span></p>
                    <p>Click "Download Bulk Data" below to download Scryfall card data (~100MB). This only needs to be done once.</p>
                </div>
            `;
        }
    }
}

async function downloadCache() {
    const progressContainer = document.getElementById('download-progress');
    const progressFill = document.getElementById('download-progress-fill');
    const progressText = document.getElementById('download-progress-text');

    progressContainer.style.display = 'block';
    progressFill.style.width = '0%';
    progressText.textContent = '0%';

    try {
        const response = await fetch(`${API_BASE}/cache/download`, {
            method: 'POST'
        });

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
            const { done, value } = await reader.read();

            if (value) {
                buffer += decoder.decode(value, { stream: true });

                // Process complete SSE messages (ending with \n\n)
                const messages = buffer.split('\n\n');
                // Keep the last incomplete message in buffer
                buffer = messages.pop() || '';

                for (const message of messages) {
                    const lines = message.split('\n');
                    for (const line of lines) {
                        if (line.startsWith('data: ')) {
                            try {
                                const data = JSON.parse(line.substring(6));

                                if (data.percentage !== undefined) {
                                    progressFill.style.width = `${data.percentage}%`;
                                    progressText.textContent = `${data.percentage}%`;

                                    // Update aria attributes for accessibility
                                    const progressBar = document.querySelector('#download-progress .progress-bar');
                                    if (progressBar) {
                                        progressBar.setAttribute('aria-valuenow', data.percentage);
                                    }
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
                            } catch (e) {
                                console.error('Error parsing SSE data:', e, line);
                            }
                        }
                    }
                }
            }

            if (done) break;
        }
    } catch (error) {
        console.error('Download error:', error);
        showToast('Error downloading bulk data: ' + error.message, 'error');
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
            // Save to localStorage for persistence
            localStorage.setItem('lastJobId', currentJobId);
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

    // Add View Collection button if it doesn't exist
    const resultsDisplay = document.getElementById('results-display');
    const actionsDiv = resultsDisplay.querySelector('.actions');
    let viewCollectionBtn = document.getElementById('view-collection-btn');

    if (!viewCollectionBtn) {
        viewCollectionBtn = document.createElement('button');
        viewCollectionBtn.id = 'view-collection-btn';
        viewCollectionBtn.className = 'btn btn-secondary';
        viewCollectionBtn.textContent = 'View Collection';
        viewCollectionBtn.addEventListener('click', () => {
            switchView('viewer');
            // Update active nav
            document.querySelectorAll('.nav-item').forEach(nav => nav.classList.remove('active'));
            document.querySelector('[data-view="viewer"]').classList.add('active');
        });
        actionsDiv.insertBefore(viewCollectionBtn, actionsDiv.firstChild);
    }
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

// Collection Viewer Functions
function setupCollectionViewer() {
    const searchInput = document.getElementById('viewer-search');
    const toggleBtns = document.querySelectorAll('.toggle-btn');
    const modal = document.getElementById('card-modal');
    const modalClose = document.querySelector('.modal-close');

    if (searchInput) {
        searchInput.addEventListener('input', debounce(searchCollection, 300));
    }

    toggleBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            toggleBtns.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');

            const mode = btn.dataset.mode;
            if (mode === 'grid') {
                document.getElementById('card-grid').style.display = 'grid';
                document.getElementById('card-list').style.display = 'none';
            } else {
                document.getElementById('card-grid').style.display = 'none';
                document.getElementById('card-list').style.display = 'block';
            }
        });
    });

    if (modalClose) {
        modalClose.addEventListener('click', () => {
            modal.classList.remove('active');
        });
    }

    // Close modal on background click
    modal.addEventListener('click', (e) => {
        if (e.target === modal) {
            modal.classList.remove('active');
        }
    });
}

async function loadCollectionViewer(jobId) {
    console.log('Loading collection viewer for job:', jobId);

    if (jobId) {
        // Collection mode: Load user's collection
        try {
            currentJobId = jobId;
            localStorage.setItem('lastJobId', jobId);

            const response = await fetch(`${API_BASE}/collection/${jobId}/random?limit=30`);

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            const data = await response.json();
            displayCardGrid(data.cards);
            console.log(`Loaded ${data.cards.length} random cards from collection`);

            try {
                const fullResponse = await fetch(`${API_BASE}/collection/${jobId}`);
                const fullData = await fullResponse.json();
                showToast(`Showing 30 random cards from your ${fullData.total} card collection`, 'success');
            } catch (countError) {
                console.warn('Could not fetch total count:', countError);
                showToast(`Loaded ${data.cards.length} cards from your collection`, 'success');
            }
        } catch (error) {
            console.error('Error loading collection:', error);
            // Fall back to browse mode
            await loadBrowseMode();
        }
    } else {
        // Browse mode: Show random cards from all Scryfall data
        await loadBrowseMode();
    }
}

async function loadBrowseMode() {
    console.log('Loading browse mode - showing random cards from Scryfall database');
    currentJobId = null;

    try {
        const response = await fetch(`${API_BASE}/cards/random?limit=30`);

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        const data = await response.json();
        displayCardGrid(data.cards);
        console.log(`Loaded ${data.cards.length} random cards from Scryfall database`);
        showToast('Browse mode: Showing random cards. Search to find specific cards!', 'info');
    } catch (error) {
        console.error('Error loading browse mode:', error);
        displayCardGrid([]);
        showToast('Error loading cards. Please download cache first!', 'error');
    }
}

async function searchCollection() {
    const query = document.getElementById('viewer-search').value.trim();

    // Try to get job_id if not set
    let jobId = currentJobId || localStorage.getItem('lastJobId');

    try {
        let url;
        let mode = jobId ? 'collection' : 'browse';

        if (query) {
            // Search by query
            if (jobId) {
                // Collection mode: Search within user's collection
                url = `${API_BASE}/collection/${jobId}/search?q=${encodeURIComponent(query)}`;
                console.log(`Searching collection for: "${query}"`);
            } else {
                // Browse mode: Search all cards
                url = `${API_BASE}/cards/search?q=${encodeURIComponent(query)}&limit=30`;
                console.log(`Searching Scryfall database for: "${query}"`);
            }
        } else {
            // Show random cards when search is cleared
            if (jobId) {
                url = `${API_BASE}/collection/${jobId}/random?limit=30`;
                console.log('Loading random cards from collection');
            } else {
                url = `${API_BASE}/cards/random?limit=30`;
                console.log('Loading random cards from Scryfall database');
            }
        }

        const response = await fetch(url);

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        const data = await response.json();
        displayCardGrid(data.cards);
        console.log(`Displayed ${data.cards.length} cards in ${mode} mode`);

        // Show helpful message if no results
        if (query && data.cards.length === 0) {
            if (jobId) {
                showToast(`No cards in your collection matching "${query}"`, 'info');
            } else {
                showToast(`No cards found matching "${query}"`, 'info');
            }
        }
    } catch (error) {
        console.error('Search error:', error);
        showToast('Error searching: ' + error.message, 'error');
        displayCardGrid([]);
    }
}

function displayCardGrid(cards) {
    const grid = document.getElementById('card-grid');
    grid.innerHTML = '';

    if (cards.length === 0) {
        grid.innerHTML = '<p style="grid-column: 1/-1; text-align: center;">No cards found</p>';
        return;
    }

    cards.forEach(card => {
        const cardEl = document.createElement('div');
        cardEl.className = 'card-item';

        // Format price
        const priceText = card.price ? `$${parseFloat(card.price).toFixed(2)}` : 'N/A';

        // Owned badge
        const ownedBadge = card.owned && card.quantity > 0
            ? `<div class="owned-badge">Owned: ${card.quantity}</div>`
            : '';

        cardEl.innerHTML = `
            <div class="card-image-wrapper">
                ${ownedBadge}
                <img src="${card.image_url}" alt="${card.name}" loading="lazy">
                <div class="card-hover-preview">
                    <p><strong>Type:</strong> ${card.type_line || 'N/A'}</p>
                    <p><strong>Mana Cost:</strong> ${card.mana_cost || 'N/A'}</p>
                    <p><strong>Oracle Text:</strong> ${card.oracle_text || 'N/A'}</p>
                    ${card.quantity > 0 ? `<p><strong>Quantity:</strong> ${card.quantity}</p>` : ''}
                </div>
            </div>
            <div class="card-info">
                <p class="card-name">${card.name}</p>
                <p class="card-price">${priceText}</p>
            </div>
        `;
        cardEl.addEventListener('click', () => showCardDetail(card));
        grid.appendChild(cardEl);
    });
}

function showCardDetail(card) {
    const modal = document.getElementById('card-modal');
    const details = document.getElementById('modal-card-details');

    details.innerHTML = `
        <img src="${card.image_url}" alt="${card.name}" style="width: 100%; border-radius: 0.5rem; margin-bottom: 1rem;">
        <h3>${card.name}</h3>
        <p><strong>Mana Cost:</strong> ${card.mana_cost || 'N/A'}</p>
        <p><strong>Type:</strong> ${card.type_line || 'N/A'}</p>
        <p><strong>Oracle Text:</strong> ${card.oracle_text || 'N/A'}</p>
        <p><strong>Quantity:</strong> ${card.quantity || 1}</p>
    `;

    modal.classList.add('active');
}

function debounce(func, wait) {
    let timeout;
    return function(...args) {
        clearTimeout(timeout);
        timeout = setTimeout(() => func.apply(this, args), wait);
    };
}

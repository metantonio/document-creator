// APP STATE
let currentConfig = null;
let currentChatId = null;
let activeDocumentPath = null;
let currentDocData = null;
let isViewerOpen = true;
let currentViewerTab = 'preview';

// INITIALIZATION
document.addEventListener('DOMContentLoaded', async () => {
    await fetchConfig();
    await fetchChats();
    await fetchDocuments();
    
    // Auto-select latest chat or create new
    const chats = await (await fetch('/api/chats')).json();
    if (chats.chats && chats.chats.length > 0) {
        selectChat(chats.chats[0].id);
    } else {
        createNewChat();
    }

    // Auto-resize chat textarea
    const chatInput = document.getElementById('chatInput');
    chatInput.addEventListener('input', () => {
        chatInput.style.height = 'auto';
        chatInput.style.height = (chatInput.scrollHeight) + 'px';
    });

    chatInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });
});

// --- CONFIG & PROVIDER ---
async function fetchConfig() {
    try {
        const res = await fetch('/api/config');
        currentConfig = await res.json();
        updateProviderUI();
        populateConfigModal();
    } catch (e) {
        console.error('Error fetching config:', e);
    }
}

function updateProviderUI() {
    if (!currentConfig) return;
    const provider = currentConfig.active_provider || 'local';
    
    const badge = document.getElementById('activeProviderBadge');
    const btnLocal = document.getElementById('btnProviderLocal');
    const btnCloud = document.getElementById('btnProviderCloud');
    const infoText = document.getElementById('providerInfoText');

    badge.innerText = provider.toUpperCase();
    if (provider === 'local') {
        btnLocal.classList.add('active');
        btnCloud.classList.remove('active');
        const lcfg = currentConfig.local_config || {};
        infoText.innerText = `${lcfg.model || 'Local Model'} (${lcfg.base_url || 'localhost'})`;
    } else {
        btnCloud.classList.add('active');
        btnLocal.classList.remove('active');
        const ccfg = currentConfig.cloud_config || {};
        infoText.innerText = `${ccfg.model || 'Cloud Model'} (${ccfg.base_url || 'api.openai.com'})`;
    }
}

async function switchProvider(provider) {
    if (!currentConfig) return;
    currentConfig.active_provider = provider;
    updateProviderUI();
    
    await fetch('/api/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ active_provider: provider })
    });
}


// --- CHATS MANAGEMENT ---
async function fetchChats() {
    try {
        const res = await fetch('/api/chats');
        const data = await res.json();
        renderChatsList(data.chats || []);
    } catch (e) {
        console.error('Error loading chats:', e);
    }
}

function renderChatsList(chats) {
    const list = document.getElementById('chatsList');
    list.innerHTML = '';

    chats.forEach(chat => {
        const item = document.createElement('div');
        item.className = `chat-item ${chat.id === currentChatId ? 'active' : ''}`;
        item.onclick = () => selectChat(chat.id);
        
        item.innerHTML = `
            <div class="item-left">
                <i class="fa-regular fa-message"></i>
                <span class="item-title">${escapeHtml(chat.title)}</span>
            </div>
            <button class="btn-icon-sm" onclick="event.stopPropagation(); deleteChat('${chat.id}')" title="Delete Chat">
                <i class="fa-solid fa-trash-can"></i>
            </button>
        `;
        list.appendChild(item);
    });
}

async function createNewChat() {
    try {
        const res = await fetch('/api/chats', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title: 'New Conversation' })
        });
        const chat = await res.json();
        await fetchChats();
        selectChat(chat.id);
    } catch (e) {
        console.error('Error creating chat:', e);
    }
}

async function selectChat(chatId) {
    currentChatId = chatId;
    await fetchChats(); // update active class
    
    try {
        const res = await fetch(`/api/chats/${chatId}`);
        const chat = await res.json();
        
        document.getElementById('currentChatTitle').innerText = chat.title || 'Conversation';
        activeDocumentPath = chat.active_doc_path;
        
        updateActiveDocBadge();
        renderMessages(chat.messages || []);
        
        if (activeDocumentPath) {
            loadDocumentContent(activeDocumentPath);
        } else {
            clearViewer();
        }
    } catch (e) {
        console.error('Error selecting chat:', e);
    }
}

async function deleteChat(chatId) {
    if (!confirm('Are you sure you want to delete this chat conversation?')) return;
    try {
        await fetch(`/api/chats/${chatId}`, { method: 'DELETE' });
        if (currentChatId === chatId) {
            currentChatId = null;
        }
        await fetchChats();
        const chats = await (await fetch('/api/chats')).json();
        if (chats.chats && chats.chats.length > 0) {
            selectChat(chats.chats[0].id);
        } else {
            createNewChat();
        }
    } catch (e) {
        console.error('Error deleting chat:', e);
    }
}

function updateActiveDocBadge() {
    const badge = document.getElementById('activeDocBadge');
    const nameSpan = document.getElementById('activeDocName');
    
    if (activeDocumentPath) {
        const filename = activeDocumentPath.split(/[/\\]/).pop();
        nameSpan.innerText = filename;
        badge.style.display = 'flex';
    } else {
        badge.style.display = 'none';
    }
}

function renderMessages(messages) {
    const container = document.getElementById('messagesContainer');
    document.getElementById('emptyState').style.display = 'none';
    container.innerHTML = '';

    messages.forEach(msg => {
        const row = document.createElement('div');
        row.className = `message-row ${msg.sender}`;
        
        const avatarIcon = msg.sender === 'user' ? 'fa-user' : 'fa-robot';
        let parsedText = typeof marked !== 'undefined' ? marked.parse(msg.text) : escapeHtml(msg.text);

        let contentHtml = `
            <div class="avatar"><i class="fa-solid ${avatarIcon}"></i></div>
            <div class="message-content">
                <div>${parsedText}</div>
        `;

        // If onboarding greeting message, attach interactive choice buttons!
        if (msg.is_onboarding && !activeDocumentPath) {
            contentHtml += `
                <div class="onboarding-actions">
                    <button class="btn btn-primary" onclick="openCreateDocModal()">
                        <i class="fa-solid fa-file-circle-plus"></i> Start New Document
                    </button>
                    <button class="btn btn-secondary" onclick="openSelectDocModal()">
                        <i class="fa-solid fa-folder-open"></i> Edit Existing Document
                    </button>
                </div>
            `;
        }

        // If document update info attached
        if (msg.doc_update_info) {
            const doc = msg.doc_update_info;
            contentHtml += `
                <div class="doc-update-card">
                    <i class="fa-solid fa-circle-check"></i> Updated file: <strong>${escapeHtml(doc.filename)}</strong>
                    <br><small class="text-subtle">${doc.headings ? doc.headings.length : 0} section headings in document</small>
                </div>
            `;
        }

        contentHtml += `</div>`;
        row.innerHTML = contentHtml;
        container.appendChild(row);
    });

    container.scrollTop = container.scrollHeight;
}

async function sendMessage() {
    const chatInput = document.getElementById('chatInput');
    const text = chatInput.value.trim();
    if (!text || !currentChatId) return;

    chatInput.value = '';
    chatInput.style.height = 'auto';

    // Optimistically render user message
    const container = document.getElementById('messagesContainer');
    const userRow = document.createElement('div');
    userRow.className = 'message-row user';
    userRow.innerHTML = `
        <div class="avatar"><i class="fa-solid fa-user"></i></div>
        <div class="message-content">${escapeHtml(text)}</div>
    `;
    container.appendChild(userRow);
    container.scrollTop = container.scrollHeight;

    // Show assistant thinking state
    const thinkingRow = document.createElement('div');
    thinkingRow.id = 'thinkingRow';
    thinkingRow.className = 'message-row assistant';
    thinkingRow.innerHTML = `
        <div class="avatar"><i class="fa-solid fa-robot"></i></div>
        <div class="message-content"><i class="fa-solid fa-spinner fa-spin"></i> Analyzing document structure and processing update...</div>
    `;
    container.appendChild(thinkingRow);
    container.scrollTop = container.scrollHeight;

    try {
        const res = await fetch(`/api/chats/${currentChatId}/messages`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text: text })
        });
        const data = await res.json();
        
        // Refresh full chat history
        selectChat(currentChatId);
    } catch (e) {
        console.error('Error sending message:', e);
        if (document.getElementById('thinkingRow')) {
            document.getElementById('thinkingRow').remove();
        }
    }
}


// --- DOCUMENTS LIBRARY & VIEWER ---
async function fetchDocuments() {
    try {
        const res = await fetch('/api/documents');
        const data = await res.json();
        renderQuickDocs(data.documents || []);
    } catch (e) {
        console.error('Error fetching documents:', e);
    }
}

function renderQuickDocs(docs) {
    const list = document.getElementById('docsQuickList');
    list.innerHTML = '';

    if (docs.length === 0) {
        list.innerHTML = '<span class="text-subtle" style="font-size:12px; padding:4px;">No documents created yet.</span>';
        return;
    }

    docs.forEach(doc => {
        const item = document.createElement('div');
        item.className = `doc-item ${doc.filepath === activeDocumentPath ? 'active' : ''}`;
        item.onclick = () => {
            loadDocumentContent(doc.filepath);
            if (currentChatId) {
                setChatDocument(doc.filepath);
            }
        };
        
        const icon = doc.format === 'docx' ? 'fa-file-word' : doc.format === 'md' ? 'fa-file-code' : 'fa-file-lines';

        item.innerHTML = `
            <div class="item-left">
                <i class="fa-solid ${icon}"></i>
                <span class="item-title">${escapeHtml(doc.filename)}</span>
            </div>
            <span class="badge badge-format">${doc.format.toUpperCase()}</span>
        `;
        list.appendChild(item);
    });
}

async function loadDocumentContent(filepath) {
    activeDocumentPath = filepath;
    updateActiveDocBadge();
    
    try {
        const res = await fetch(`/api/documents/content?filepath=${encodeURIComponent(filepath)}`);
        currentDocData = await res.json();
        
        renderViewer();
    } catch (e) {
        console.error('Error loading doc content:', e);
    }
}

function renderViewer() {
    if (!currentDocData) return;

    document.getElementById('viewerMeta').style.display = 'flex';
    document.getElementById('vFileName').innerText = currentDocData.filename;
    document.getElementById('vFileFormat').innerText = currentDocData.format.toUpperCase();
    document.getElementById('vFilePath').innerText = currentDocData.filepath;

    const contentDiv = document.getElementById('viewerContent');
    
    if (currentViewerTab === 'preview') {
        if (typeof marked !== 'undefined') {
            contentDiv.innerHTML = marked.parse(currentDocData.full_text);
        } else {
            contentDiv.innerHTML = `<pre>${escapeHtml(currentDocData.full_text)}</pre>`;
        }
    } else { // Outline
        let treeHtml = '<h4>Document Heading Tree</h4><ul style="list-style:none; padding-left:0; margin-top:10px;">';
        if (currentDocData.headings && currentDocData.headings.length > 0) {
            currentDocData.headings.forEach(h => {
                const indent = (h.level - 1) * 16;
                treeHtml += `<li style="padding-left:${indent}px; margin-bottom:8px;">
                    <i class="fa-solid fa-heading" style="font-size:12px; color:var(--accent-primary);"></i>
                    <strong>H${h.level}:</strong> ${escapeHtml(h.title)}
                </li>`;
            });
        } else {
            treeHtml += '<li class="text-subtle">No headings detected.</li>';
        }
        treeHtml += '</ul>';
        contentDiv.innerHTML = treeHtml;
    }
}

function clearViewer() {
    currentDocData = null;
    document.getElementById('viewerMeta').style.display = 'none';
    document.getElementById('viewerContent').innerHTML = `
        <div class="empty-viewer">
            <i class="fa-solid fa-file-contract"></i>
            <p>No document loaded in viewer.</p>
            <p class="text-subtle">Select an active document in chat or pick one from library.</p>
        </div>
    `;
}

function toggleViewerPanel() {
    const panel = document.getElementById('viewerPanel');
    const text = document.getElementById('toggleViewerText');
    isViewerOpen = !isViewerOpen;
    
    if (isViewerOpen) {
        panel.classList.remove('hidden');
        text.innerText = 'Hide Document Viewer';
    } else {
        panel.classList.add('hidden');
        text.innerText = 'Show Document Viewer';
    }
}

function switchViewerTab(tab) {
    currentViewerTab = tab;
    document.getElementById('tabDocPreview').classList.toggle('active', tab === 'preview');
    document.getElementById('tabDocOutline').classList.toggle('active', tab === 'outline');
    renderViewer();
}

async function setChatDocument(filepath) {
    if (!currentChatId) return;
    try {
        await fetch(`/api/chats/${currentChatId}/set-document`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ filepath: filepath })
        });
        selectChat(currentChatId);
    } catch (e) {
        console.error('Error setting chat document:', e);
    }
}

function changeActiveDocument() {
    openSelectDocModal();
}


// --- MODALS ACTIONS ---

function openModal(id) {
    document.getElementById(id).classList.add('active');
}

function closeModal(id) {
    document.getElementById(id).classList.remove('active');
}

function openCreateDocModal() {
    document.getElementById('newDocTitle').value = '';
    document.getElementById('newDocContent').value = '';
    openModal('createDocModal');
}

async function submitCreateDocument() {
    const format = document.querySelector('input[name="docFormat"]:checked').value;
    const title = document.getElementById('newDocTitle').value.trim();
    const content = document.getElementById('newDocContent').value.trim();

    if (!title) {
        alert('Please enter a document title');
        return;
    }

    try {
        const res = await fetch('/api/documents/create', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                chat_id: currentChatId,
                format: format,
                title: title,
                content: content
            })
        });
        const data = await res.json();
        closeModal('createDocModal');
        await fetchDocuments();
        if (currentChatId) {
            selectChat(currentChatId);
        }
    } catch (e) {
        console.error('Error creating document:', e);
    }
}

async function openSelectDocModal() {
    try {
        const res = await fetch('/api/documents');
        const data = await res.json();
        const grid = document.getElementById('docsModalGrid');
        grid.innerHTML = '';

        if (!data.documents || data.documents.length === 0) {
            grid.innerHTML = '<p class="text-subtle">No documents found. Please create or upload one first.</p>';
        } else {
            data.documents.forEach(doc => {
                const card = document.createElement('div');
                card.className = 'doc-select-card';
                card.onclick = () => {
                    setChatDocument(doc.filepath);
                    closeModal('selectDocModal');
                };
                card.innerHTML = `
                    <div>
                        <strong>${escapeHtml(doc.filename)}</strong>
                        <br><small class="text-subtle">${escapeHtml(doc.filepath)}</small>
                    </div>
                    <span class="badge badge-format">${doc.format.toUpperCase()}</span>
                `;
                grid.appendChild(card);
            });
        }
        openModal('selectDocModal');
    } catch (e) {
        console.error('Error fetching doc list:', e);
    }
}

function openUploadModal() {
    document.getElementById('uploadFileName').innerText = '';
    document.getElementById('fileInput').value = '';
    openModal('uploadModal');
}

function handleFileSelect(e) {
    const file = e.target.files[0];
    if (file) {
        document.getElementById('uploadFileName').innerText = `Selected: ${file.name}`;
    }
}

async function submitUploadFile() {
    const fileInput = document.getElementById('fileInput');
    if (!fileInput.files || fileInput.files.length === 0) {
        alert('Please select a file to upload');
        return;
    }

    const formData = new FormData();
    formData.append('file', fileInput.files[0]);
    if (currentChatId) {
        formData.append('chat_id', currentChatId);
    }

    try {
        const res = await fetch('/api/documents/upload', {
            method: 'POST',
            body: formData
        });
        await res.json();
        closeModal('uploadModal');
        await fetchDocuments();
        if (currentChatId) {
            selectChat(currentChatId);
        }
    } catch (e) {
        console.error('Error uploading file:', e);
    }
}


// --- CONFIG MODAL & PERSISTENCE ---

function openConfigModal() {
    populateConfigModal();
    openModal('configModal');
}

function populateConfigModal() {
    if (!currentConfig) return;
    const lcfg = currentConfig.local_config || {};
    const ccfg = currentConfig.cloud_config || {};

    document.getElementById('cfgLocalBaseUrl').value = lcfg.base_url || 'http://localhost:11434/v1';
    document.getElementById('cfgLocalModel').value = lcfg.model || 'llama3';
    document.getElementById('cfgLocalApiKey').value = lcfg.api_key || 'ollama';
    document.getElementById('cfgLocalTemp').value = lcfg.temperature || 0.3;
    document.getElementById('cfgLocalMaxTokens').value = lcfg.max_tokens || 4096;

    document.getElementById('cfgCloudBaseUrl').value = ccfg.base_url || 'https://api.openai.com/v1';
    document.getElementById('cfgCloudModel').value = ccfg.model || 'gpt-4o';
    document.getElementById('cfgCloudApiKey').value = ccfg.api_key || '';
    document.getElementById('cfgCloudTemp').value = ccfg.temperature || 0.3;
    document.getElementById('cfgCloudMaxTokens').value = ccfg.max_tokens || 4096;

    renderDocumentPathsList(currentConfig.document_paths || []);
}

function renderDocumentPathsList(paths) {
    const list = document.getElementById('pathsList');
    list.innerHTML = '';
    paths.forEach((p, idx) => {
        const div = document.createElement('div');
        div.className = 'doc-select-card';
        div.style.marginBottom = '6px';
        div.innerHTML = `
            <span><i class="fa-solid fa-folder"></i> ${escapeHtml(p)}</span>
            ${paths.length > 1 ? `<button class="btn-icon-sm" onclick="removeDocumentPath(${idx})"><i class="fa-solid fa-xmark"></i></button>` : ''}
        `;
        list.appendChild(div);
    });
}

function addDocumentPath() {
    const input = document.getElementById('newFolderPath');
    const pathVal = input.value.trim();
    if (pathVal) {
        if (!currentConfig.document_paths) currentConfig.document_paths = [];
        currentConfig.document_paths.push(pathVal);
        input.value = '';
        renderDocumentPathsList(currentConfig.document_paths);
    }
}

function removeDocumentPath(index) {
    if (currentConfig.document_paths && currentConfig.document_paths.length > 1) {
        currentConfig.document_paths.splice(index, 1);
        renderDocumentPathsList(currentConfig.document_paths);
    }
}

function switchConfigTab(tab) {
    document.getElementById('cfgTabLocal').classList.toggle('active', tab === 'local');
    document.getElementById('cfgTabCloud').classList.toggle('active', tab === 'cloud');
    document.getElementById('cfgTabPaths').classList.toggle('active', tab === 'paths');

    document.getElementById('cfgPaneLocal').style.display = tab === 'local' ? 'block' : 'none';
    document.getElementById('cfgPaneCloud').style.display = tab === 'cloud' ? 'block' : 'none';
    document.getElementById('cfgPanePaths').style.display = tab === 'paths' ? 'block' : 'none';
}

async function saveConfiguration() {
    const payload = {
        document_paths: currentConfig.document_paths,
        local_config: {
            base_url: document.getElementById('cfgLocalBaseUrl').value.trim(),
            model: document.getElementById('cfgLocalModel').value.trim(),
            api_key: document.getElementById('cfgLocalApiKey').value.trim(),
            temperature: parseFloat(document.getElementById('cfgLocalTemp').value),
            max_tokens: parseInt(document.getElementById('cfgLocalMaxTokens').value)
        },
        cloud_config: {
            base_url: document.getElementById('cfgCloudBaseUrl').value.trim(),
            model: document.getElementById('cfgCloudModel').value.trim(),
            api_key: document.getElementById('cfgCloudApiKey').value.trim(),
            temperature: parseFloat(document.getElementById('cfgCloudTemp').value),
            max_tokens: parseInt(document.getElementById('cfgCloudMaxTokens').value)
        }
    };

    try {
        const res = await fetch('/api/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const data = await res.json();
        currentConfig = data.config;
        updateProviderUI();
        closeModal('configModal');
        await fetchDocuments();
    } catch (e) {
        console.error('Error saving config:', e);
    }
}

// UTILS
function escapeHtml(text) {
    if (!text) return '';
    return text.replace(/&/g, "&amp;")
               .replace(/</g, "&lt;")
               .replace(/>/g, "&gt;")
               .replace(/"/g, "&quot;")
               .replace(/'/g, "&#039;");
}

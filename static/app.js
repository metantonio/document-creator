// APP STATE
let currentConfig = null;
let currentChatId = null;
let activeDocumentPath = null;
let currentDocData = null;
let isViewerOpen = true;
let currentViewerTab = 'preview';
const activeGeneratingTasks = {}; // Tracks active background AI generation tasks by chatId

// INITIALIZATION
document.addEventListener('DOMContentLoaded', async () => {
    // Configure marked to convert single newlines into <br> line breaks
    if (typeof marked !== 'undefined') {
        marked.setOptions({
            breaks: true,
            gfm: true
        });
    }

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

    // Auto-resize chat textarea on input & paste
    const chatInput = document.getElementById('chatInput');
    if (chatInput) {
        const resizeTextarea = () => {
            chatInput.style.height = 'auto';
            chatInput.style.height = Math.min(chatInput.scrollHeight, 200) + 'px';
        };
        
        chatInput.addEventListener('input', resizeTextarea);
        chatInput.addEventListener('paste', () => {
            setTimeout(resizeTextarea, 10);
        });

        chatInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendMessage();
            }
        });
    }
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

    if (badge) badge.innerText = provider.toUpperCase();
    if (provider === 'local') {
        if (btnLocal) btnLocal.classList.add('active');
        if (btnCloud) btnCloud.classList.remove('active');
        const lcfg = currentConfig.local_config || {};
        if (infoText) infoText.innerText = `${lcfg.model || 'Local Model'} (${lcfg.base_url || 'localhost'})`;
    } else {
        if (btnCloud) btnCloud.classList.add('active');
        if (btnLocal) btnLocal.classList.remove('active');
        const ccfg = currentConfig.cloud_config || {};
        if (infoText) infoText.innerText = `${ccfg.model || 'Cloud Model'} (${ccfg.base_url || 'api.openai.com'})`;
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
    if (!list) return;
    list.innerHTML = '';

    chats.forEach(chat => {
        const item = document.createElement('div');
        item.className = `chat-item ${chat.id === currentChatId ? 'active' : ''}`;
        item.setAttribute('data-chat-id', chat.id);
        item.onclick = () => selectChat(chat.id);
        
        const isGenerating = activeGeneratingTasks[chat.id];
        const statusBadge = isGenerating ? 
            `<span class="badge-generating" title="${escapeHtml(isGenerating.message || 'Procesando con IA...')}"><i class="fa-solid fa-circle-notch fa-spin"></i> IA</span>` : '';

        item.innerHTML = `
            <div class="item-left">
                <i class="fa-regular fa-message"></i>
                <span class="item-title">${escapeHtml(chat.title)}</span>
                ${statusBadge}
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
        if (chat && chat.id) {
            await fetchChats();
            selectChat(chat.id);
        }
    } catch (e) {
        console.error('Error creating chat:', e);
    }
}

async function selectChat(chatId) {
    if (!chatId) return;
    currentChatId = chatId;

    // Immediately highlight active chat in sidebar DOM
    document.querySelectorAll('.chat-item').forEach(item => {
        const itemChatId = item.getAttribute('data-chat-id');
        item.classList.toggle('active', itemChatId === chatId);
    });
    
    try {
        const res = await fetch(`/api/chats/${chatId}`);
        if (!res.ok) {
            console.error(`Failed to fetch chat ${chatId}`);
            return;
        }
        const chat = await res.json();
        
        const titleEl = document.getElementById('currentChatTitle');
        if (titleEl) titleEl.innerText = chat.title || 'Conversation';
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
    if (activeGeneratingTasks[chatId]) {
        alert('⚠️ Esta conversación tiene una tarea de IA en progreso. Por favor espere a que finalice antes de eliminarla.');
        return;
    }
    if (!confirm('Are you sure you want to delete this chat conversation?')) return;
    try {
        await fetch(`/api/chats/${chatId}`, { method: 'DELETE' });
        if (currentChatId === chatId) {
            currentChatId = null;
        }
        await fetchChats();
        const res = await fetch('/api/chats');
        const data = await res.json();
        if (data.chats && data.chats.length > 0) {
            selectChat(data.chats[0].id);
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
    
    if (badge && nameSpan) {
        if (activeDocumentPath) {
            const filename = activeDocumentPath.split(/[/\\]/).pop();
            nameSpan.innerText = filename;
            badge.style.display = 'flex';
        } else {
            badge.style.display = 'none';
        }
    }
}

function formatMessageContent(text) {
    if (!text) return '';
    try {
        if (typeof marked !== 'undefined') {
            let html = marked.parse(String(text));
            return html.replace(/>\s*\n\s*</g, '><').trim();
        }
        return escapeHtml(String(text)).replace(/\n/g, '<br>');
    } catch (e) {
        console.error('Error formatting message text:', e);
        return escapeHtml(String(text)).replace(/\n/g, '<br>');
    }
}

function renderMessages(messages) {
    const container = document.getElementById('messagesContainer');
    const emptyState = document.getElementById('emptyState');
    if (!container) return;

    container.innerHTML = '';

    if (!messages || messages.length === 0) {
        if (emptyState) emptyState.style.display = 'flex';
    } else {
        if (emptyState) emptyState.style.display = 'none';

        messages.forEach(msg => {
            try {
                const row = document.createElement('div');
                row.className = `message-row ${msg.sender}`;
                
                const avatarIcon = msg.sender === 'user' ? 'fa-user' : 'fa-robot';
                let parsedText = formatMessageContent(msg.text);

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
                            <button class="btn btn-secondary" onclick="openRepoModal()">
                                <i class="fa-solid fa-bolt" style="color:var(--accent-warning);"></i> Analyze Repository Wiki
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
            } catch (e) {
                console.error('Error rendering individual message:', e, msg);
            }
        });
    }

    // Re-attach active stage thinking card if active generation in progress for this chat
    if (currentChatId && activeGeneratingTasks[currentChatId]) {
        const taskInfo = activeGeneratingTasks[currentChatId];
        const thinkingRow = document.createElement('div');
        thinkingRow.id = `thinkingRow_${currentChatId}`;
        thinkingRow.className = 'message-row assistant thinking-card';
        thinkingRow.innerHTML = `
            <div class="avatar"><i class="fa-solid fa-robot"></i></div>
            <div class="message-content">
                <div class="thinking-stage-item" id="stageText_${currentChatId}">
                    <i class="fa-solid fa-circle-notch fa-spin"></i> <span>${escapeHtml(taskInfo.message || 'Procesando con la IA...')}</span>
                </div>
            </div>
        `;
        container.appendChild(thinkingRow);
    }

    container.scrollTop = container.scrollHeight;
}

async function sendMessage() {
    const chatInput = document.getElementById('chatInput');
    const text = chatInput.value.trim();
    if (!text || !currentChatId) return;

    const targetChatId = currentChatId;

    chatInput.value = '';
    chatInput.style.height = 'auto';

    // Register active background task
    activeGeneratingTasks[targetChatId] = {
        status: 'generating',
        stage: 'analyzing',
        message: '⚡ Paso 1/4: Analizando insumos y estructura del documento...'
    };
    fetchChats();

    // Optimistically render user message
    const container = document.getElementById('messagesContainer');
    const userRow = document.createElement('div');
    userRow.className = 'message-row user';
    userRow.innerHTML = `
        <div class="avatar"><i class="fa-solid fa-user"></i></div>
        <div class="message-content"><div>${formatMessageContent(text)}</div></div>
    `;
    container.appendChild(userRow);

    // Show dynamic multi-stage thinking card
    const thinkingRow = document.createElement('div');
    thinkingRow.id = `thinkingRow_${targetChatId}`;
    thinkingRow.className = 'message-row assistant thinking-card';
    thinkingRow.innerHTML = `
        <div class="avatar"><i class="fa-solid fa-robot"></i></div>
        <div class="message-content">
            <div class="thinking-stage-item" id="stageText_${targetChatId}">
                <i class="fa-solid fa-circle-notch fa-spin"></i> <span>⚡ Paso 1/4: Analizando insumos y estructura del documento...</span>
            </div>
        </div>
    `;
    container.appendChild(thinkingRow);
    container.scrollTop = container.scrollHeight;

    try {
        const response = await fetch(`/api/chats/${targetChatId}/messages/stream`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text: text })
        });

        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder('utf-8');
        let buffer = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop();

            for (const line of lines) {
                const trimmed = line.trim();
                if (trimmed.startsWith('data:')) {
                    const jsonStr = trimmed.substring(5).trim();
                    if (!jsonStr) continue;
                    try {
                        const event = JSON.parse(jsonStr);
                        if (event.type === 'stage') {
                            activeGeneratingTasks[targetChatId] = {
                                status: 'generating',
                                stage: event.stage,
                                message: event.message
                            };
                            if (currentChatId === targetChatId) {
                                const stageEl = document.getElementById(`stageText_${targetChatId}`);
                                if (stageEl) {
                                    stageEl.innerHTML = `<i class="fa-solid fa-circle-notch fa-spin"></i> <span>${escapeHtml(event.message)}</span>`;
                                }
                            }
                            fetchChats();
                        } else if (event.type === 'done') {
                            delete activeGeneratingTasks[targetChatId];
                            fetchChats();

                            if (currentChatId === targetChatId && event.chat) {
                                activeDocumentPath = event.chat.active_doc_path;
                                updateActiveDocBadge();
                                renderMessages(event.chat.messages || []);
                                if (activeDocumentPath) {
                                    await loadDocumentContent(activeDocumentPath);
                                }
                            }
                        }
                    } catch (err) {
                        console.error('Error parsing SSE payload:', err);
                    }
                }
            }
        }
    } catch (e) {
        console.error('Error sending message:', e);
        delete activeGeneratingTasks[targetChatId];
        fetchChats();
        if (currentChatId === targetChatId) {
            const thinkingEl = document.getElementById(`thinkingRow_${targetChatId}`);
            if (thinkingEl) thinkingEl.remove();
            alert(`Communication Error: ${e.message}`);
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

    const vMeta = document.getElementById('viewerMeta');
    const vFileName = document.getElementById('vFileName');
    const vFileFormat = document.getElementById('vFileFormat');
    const vFilePath = document.getElementById('vFilePath');
    const contentDiv = document.getElementById('viewerContent');

    if (vMeta) vMeta.style.display = 'flex';
    if (vFileName) vFileName.innerText = currentDocData.filename || '';
    if (vFileFormat) vFileFormat.innerText = (currentDocData.format || '').toUpperCase();
    if (vFilePath) vFilePath.innerText = currentDocData.filepath || '';

    if (contentDiv) {
        if (currentViewerTab === 'preview') {
            if (typeof marked !== 'undefined' && currentDocData.full_text) {
                contentDiv.innerHTML = marked.parse(currentDocData.full_text);
                
                // Render visual Mermaid architecture diagrams
                if (typeof mermaid !== 'undefined') {
                    setTimeout(() => {
                        const codeBlocks = contentDiv.querySelectorAll('pre code.language-mermaid, pre code.lang-mermaid');
                        codeBlocks.forEach(block => {
                            const pre = block.parentElement;
                            const graphDef = block.innerText;
                            const dDiv = document.createElement('div');
                            dDiv.className = 'mermaid';
                            dDiv.innerText = graphDef;
                            pre.replaceWith(dDiv);
                        });
                        try {
                            mermaid.run({ nodes: contentDiv.querySelectorAll('.mermaid') });
                        } catch (mErr) {
                            console.error('Mermaid render error:', mErr);
                        }
                    }, 50);
                }
            } else {
                contentDiv.innerHTML = `<pre>${escapeHtml(currentDocData.full_text || '')}</pre>`;
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
}

function clearViewer() {
    currentDocData = null;
    const vMeta = document.getElementById('viewerMeta');
    const vContent = document.getElementById('viewerContent');
    if (vMeta) vMeta.style.display = 'none';
    if (vContent) {
        vContent.innerHTML = `
            <div class="empty-viewer">
                <i class="fa-solid fa-file-contract"></i>
                <p>No document loaded in viewer.</p>
                <p class="text-subtle">Select an active document in chat or pick one from library.</p>
            </div>
        `;
    }
}

function toggleViewerPanel() {
    const panel = document.getElementById('viewerPanel');
    const text = document.getElementById('toggleViewerText');
    isViewerOpen = !isViewerOpen;
    
    if (panel) {
        if (isViewerOpen) {
            panel.classList.remove('hidden');
            if (text) text.innerText = 'Hide Document Viewer';
        } else {
            panel.classList.add('hidden');
            if (text) text.innerText = 'Show Document Viewer';
        }
    }
}

function switchViewerTab(tab) {
    currentViewerTab = tab;
    const tabPrev = document.getElementById('tabDocPreview');
    const tabOut = document.getElementById('tabDocOutline');
    if (tabPrev) tabPrev.classList.toggle('active', tab === 'preview');
    if (tabOut) tabOut.classList.toggle('active', tab === 'outline');
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


function openModal(id) {
    const el = document.getElementById(id);
    if (el) el.classList.add('active');
}

function closeModal(id) {
    const el = document.getElementById(id);
    if (el) el.classList.remove('active');
}

function openCreateDocModal() {
    const title = document.getElementById('newDocTitle');
    const content = document.getElementById('newDocContent');
    if (title) title.value = '';
    if (content) content.value = '';
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

    const setVal = (id, val) => {
        const el = document.getElementById(id);
        if (el) el.value = val;
    };

    setVal('cfgLocalBaseUrl', lcfg.base_url || 'http://localhost:11434/v1');
    setVal('cfgLocalModel', lcfg.model || 'llama3');
    setVal('cfgLocalApiKey', lcfg.api_key || 'ollama');
    setVal('cfgLocalTemp', lcfg.temperature !== undefined ? lcfg.temperature : 0.3);
    setVal('cfgLocalMaxTokens', lcfg.max_tokens !== undefined && lcfg.max_tokens !== null ? lcfg.max_tokens : 0);

    setVal('cfgCloudBaseUrl', ccfg.base_url || 'https://api.openai.com/v1');
    setVal('cfgCloudModel', ccfg.model || 'gpt-4o');
    setVal('cfgCloudApiKey', ccfg.api_key || '');
    setVal('cfgCloudTemp', ccfg.temperature !== undefined ? ccfg.temperature : 0.3);
    setVal('cfgCloudMaxTokens', ccfg.max_tokens !== undefined && ccfg.max_tokens !== null ? ccfg.max_tokens : 32768);

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
    const localMT = parseInt(document.getElementById('cfgLocalMaxTokens').value);
    const cloudMT = parseInt(document.getElementById('cfgCloudMaxTokens').value);

    const payload = {
        document_paths: currentConfig.document_paths,
        local_config: {
            base_url: document.getElementById('cfgLocalBaseUrl').value.trim(),
            model: document.getElementById('cfgLocalModel').value.trim(),
            api_key: document.getElementById('cfgLocalApiKey').value.trim(),
            temperature: parseFloat(document.getElementById('cfgLocalTemp').value),
            max_tokens: isNaN(localMT) ? 0 : localMT
        },
        cloud_config: {
            base_url: document.getElementById('cfgCloudBaseUrl').value.trim(),
            model: document.getElementById('cfgCloudModel').value.trim(),
            api_key: document.getElementById('cfgCloudApiKey').value.trim(),
            temperature: parseFloat(document.getElementById('cfgCloudTemp').value),
            max_tokens: isNaN(cloudMT) ? 32768 : cloudMT
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

async function openRepoModal() {
    const src = document.getElementById('repoSourceInput');
    const title = document.getElementById('repoNewTitle');
    const loading = document.getElementById('repoLoadingState');
    const btn = document.getElementById('btnSubmitRepo');

    if (src) src.value = '';
    if (title) title.value = '';
    if (loading) loading.style.display = 'none';
    if (btn) btn.disabled = false;
    
    // Populate existing docs select
    try {
        const res = await fetch('/api/documents');
        const data = await res.json();
        const select = document.getElementById('repoSelectExisting');
        if (select) {
            select.innerHTML = '';
            
            if (data.documents && data.documents.length > 0) {
                data.documents.forEach(doc => {
                    const opt = document.createElement('option');
                    opt.value = doc.filepath;
                    opt.innerText = `${doc.filename} (${doc.format.toUpperCase()})`;
                    select.appendChild(opt);
                });
            } else {
                select.innerHTML = '<option value="">No existing documents available</option>';
            }
        }
    } catch (e) {
        console.error('Error fetching docs for repo modal:', e);
    }
    
    toggleRepoDocFields();
    openModal('repoModal');
}

function toggleRepoDocFields() {
    const opt = document.querySelector('input[name="repoDocOpt"]:checked').value;
    document.getElementById('repoNewDocFields').style.display = opt === 'new' ? 'block' : 'none';
    document.getElementById('repoExistingDocFields').style.display = opt === 'existing' ? 'block' : 'none';
}

async function submitRepoAnalysis() {
    const repoSource = document.getElementById('repoSourceInput').value.trim();
    if (!repoSource) {
        alert('Please enter a local repository folder path or GitHub URL.');
        return;
    }

    const docOpt = document.querySelector('input[name="repoDocOpt"]:checked').value;
    const newTitle = document.getElementById('repoNewTitle').value.trim();
    const newFormat = document.getElementById('repoNewFormat').value;
    const existingFilepath = document.getElementById('repoSelectExisting').value;

    if (docOpt === 'existing' && !existingFilepath) {
        alert('Please select an existing target document.');
        return;
    }

    // UI Loading state
    document.getElementById('repoLoadingState').style.display = 'block';
    document.getElementById('btnSubmitRepo').disabled = true;

    try {
        const res = await fetch('/api/repository/analyze', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                repo_source: repoSource,
                chat_id: currentChatId,
                doc_option: docOpt,
                target_filepath: existingFilepath,
                format: newFormat,
                new_title: newTitle
            })
        });

        const data = await res.json();
        
        if (res.ok) {
            closeModal('repoModal');
            await fetchDocuments();
            if (currentChatId) {
                await selectChat(currentChatId);
            } else if (data.document) {
                await loadDocumentContent(data.document.filepath);
            }
        } else {
            alert(`Analysis Error: ${data.detail || 'Failed to analyze repository'}`);
        }
    } catch (e) {
        console.error('Error submitting repo analysis:', e);
        alert(`An error occurred: ${e.message}`);
    } finally {
        const loading = document.getElementById('repoLoadingState');
        const btn = document.getElementById('btnSubmitRepo');
        if (loading) loading.style.display = 'none';
        if (btn) btn.disabled = false;
    }
}

// --- MICROSOFT TEAMS INTEGRATION UI ---
async function openTeamsModal() {
    try {
        const res = await fetch('/api/teams/config');
        const cfg = await res.json();
        
        document.getElementById('teamsTenantId').value = cfg.tenant_id || '';
        document.getElementById('teamsClientId').value = cfg.client_id || '';
        document.getElementById('teamsClientSecret').value = cfg.client_secret || '';
        document.getElementById('teamsDefaultTeamId').value = cfg.default_team_id || '';
        document.getElementById('teamsDefaultChannelId').value = cfg.default_channel_id || '';
        
        document.getElementById('teamsImportTeamId').value = cfg.default_team_id || '';
        document.getElementById('teamsImportChannelId').value = cfg.default_channel_id || '';
        
        document.getElementById('teamsConnectionStatus').innerText = '';
        document.getElementById('teamsSaveStatus').innerText = '';
        document.getElementById('teamsImportLoading').style.display = 'none';
        document.getElementById('btnSubmitTeamsAction').disabled = false;
        
        switchTeamsTab('import');
        openModal('teamsModal');
    } catch (e) {
        console.error('Error opening Teams modal:', e);
    }
}

function switchTeamsTab(tab) {
    document.querySelectorAll('#teamsModal .cfg-tab-btn').forEach(btn => btn.classList.remove('active'));
    
    const tabDesktop = document.getElementById('teamsTabDesktop');
    const tabImport = document.getElementById('teamsTabImport');
    const tabConfig = document.getElementById('teamsTabConfig');
    
    const paneDesktop = document.getElementById('teamsPaneDesktop');
    const paneImport = document.getElementById('teamsPaneImport');
    const paneConfig = document.getElementById('teamsPaneConfig');

    if (tab === 'desktop') {
        if (tabDesktop) tabDesktop.classList.add('active');
        if (paneDesktop) paneDesktop.style.display = 'block';
        if (paneImport) paneImport.style.display = 'none';
        if (paneConfig) paneConfig.style.display = 'none';
        document.getElementById('btnSubmitTeamsAction').innerHTML = '<i class="fa-solid fa-desktop"></i> Capture & Add to Document';
        scanTeamsDesktopWindows();
    } else if (tab === 'import') {
        if (tabImport) tabImport.classList.add('active');
        if (paneDesktop) paneDesktop.style.display = 'none';
        if (paneImport) paneImport.style.display = 'block';
        if (paneConfig) paneConfig.style.display = 'none';
        document.getElementById('btnSubmitTeamsAction').innerHTML = '<i class="fa-solid fa-cloud-arrow-down"></i> Fetch Graph API Messages';
    } else {
        if (tabConfig) tabConfig.classList.add('active');
        if (paneDesktop) paneDesktop.style.display = 'none';
        if (paneImport) paneImport.style.display = 'none';
        if (paneConfig) paneConfig.style.display = 'block';
        document.getElementById('btnSubmitTeamsAction').innerHTML = '<i class="fa-solid fa-floppy-disk"></i> Save Azure Config';
    }
}

async function scanTeamsDesktopWindows() {
    const select = document.getElementById('teamsDesktopWindowSelect');
    if (!select) return;
    select.innerHTML = '<option value="">Scanning desktop for open Teams windows...</option>';
    
    try {
        const res = await fetch('/api/teams/desktop/windows');
        const data = await res.json();
        const windows = data.windows || [];
        
        select.innerHTML = '<option value="">Auto-detect active Teams window</option>';
        if (windows.length === 0) {
            const opt = document.createElement('option');
            opt.value = "";
            opt.innerText = "No explicit Teams window title detected (Will search active window)";
            select.appendChild(opt);
        } else {
            windows.forEach(w => {
                const opt = document.createElement('option');
                opt.value = w.title;
                opt.innerText = `💻 ${w.title}`;
                select.appendChild(opt);
            });
        }
    } catch (e) {
        select.innerHTML = '<option value="">Auto-detect active Teams window</option>';
    }
}

async function captureTeamsDesktopChat() {
    if (!currentChatId) {
        alert('Please select or create an active chat session first.');
        return;
    }
    
    const loadingDiv = document.getElementById('teamsDesktopLoading');
    const loadingText = document.getElementById('teamsDesktopLoadingText');
    const submitBtn = document.getElementById('btnSubmitTeamsAction');
    const winSelect = document.getElementById('teamsDesktopWindowSelect');
    const delaySelect = document.getElementById('teamsDesktopDelaySelect');
    
    const delaySecs = parseInt(delaySelect ? delaySelect.value : "5") || 0;
    
    if (loadingDiv) loadingDiv.style.display = 'block';
    if (submitBtn) submitBtn.disabled = true;

    // Interactive Countdown Loop
    if (delaySecs > 0) {
        for (let i = delaySecs; i > 0; i--) {
            if (loadingText) {
                loadingText.innerHTML = `<span style="font-size: 1.05rem; color: #818cf8;">⏳ <strong>CAMBIA A LA VENTANA DE TEAMS AHORA!</strong></span><br>Capturando chat en <strong>${i}</strong> segundos...`;
            }
            await new Promise(r => setTimeout(r, 1000));
        }
    }
    
    if (loadingText) {
        loadingText.innerHTML = `<i class="fa-solid fa-cloud-arrow-up"></i> Capturando chat de Teams y generando documento...`;
    }

    const scrollCheckbox = document.getElementById('teamsDesktopAutoScroll');
    const autoScrollUp = scrollCheckbox ? scrollCheckbox.checked : true;
    const depthSelect = document.getElementById('teamsDesktopDepthSelect');
    const scrollDepth = depthSelect ? depthSelect.value : "standard";

    const payload = {
        chat_id: currentChatId,
        window_title: winSelect ? winSelect.value : "",
        delay_seconds: 0,
        auto_scroll_up: autoScrollUp,
        scroll_depth: scrollDepth,
        provider: currentConfig ? currentConfig.active_provider : 'local'
    };
    
    try {
        const res = await fetch('/api/teams/desktop/capture', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (!res.ok) {
            alert(`Teams Desktop Capture: ${data.detail || 'Could not capture Teams window.'}`);
        } else {
            closeModal('teamsModal');
            await selectChat(currentChatId);
        }
    } catch (e) {
        alert(`Capture Error: ${e.message}`);
    } finally {
        if (loadingDiv) loadingDiv.style.display = 'none';
        if (submitBtn) submitBtn.disabled = false;
    }
}

function toggleTeamsImportFields(type) {
    document.getElementById('teamsChannelFields').style.display = type === 'channel' ? 'block' : 'none';
    document.getElementById('teamsChatFields').style.display = type === 'chat' ? 'block' : 'none';
}

async function testTeamsConnection() {
    const statusSpan = document.getElementById('teamsConnectionStatus');
    statusSpan.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Testing Azure AD connection...';
    
    const payload = {
        tenant_id: document.getElementById('teamsTenantId').value.trim(),
        client_id: document.getElementById('teamsClientId').value.trim(),
        client_secret: document.getElementById('teamsClientSecret').value.trim()
    };
    
    try {
        const res = await fetch('/api/teams/test-connection', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (data.connected) {
            statusSpan.innerHTML = `<span style="color:var(--accent-success);"><i class="fa-solid fa-circle-check"></i> ${data.detail}</span>`;
        } else {
            statusSpan.innerHTML = `<span style="color:#ef4444;"><i class="fa-solid fa-circle-xmark"></i> ${data.detail}</span>`;
        }
    } catch (e) {
        statusSpan.innerHTML = `<span style="color:#ef4444;"><i class="fa-solid fa-circle-xmark"></i> Connection error: ${e.message}</span>`;
    }
}

async function submitTeamsAction() {
    const paneDesktop = document.getElementById('teamsPaneDesktop');
    const paneImport = document.getElementById('teamsPaneImport');
    
    if (paneDesktop && paneDesktop.style.display !== 'none') {
        return captureTeamsDesktopChat();
    }
    
    if (paneImport && paneImport.style.display === 'none') {
        // Save Azure AD config
        const payload = {
            tenant_id: document.getElementById('teamsTenantId').value.trim(),
            client_id: document.getElementById('teamsClientId').value.trim(),
            client_secret: document.getElementById('teamsClientSecret').value.trim(),
            default_team_id: document.getElementById('teamsDefaultTeamId').value.trim(),
            default_channel_id: document.getElementById('teamsDefaultChannelId').value.trim()
        };
        
        try {
            await fetch('/api/teams/config', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            document.getElementById('teamsSaveStatus').innerHTML = '<span style="color:var(--accent-success);">Saved Azure config!</span>';
            setTimeout(() => switchTeamsTab('import'), 600);
        } catch (e) {
            console.error('Error saving Teams config:', e);
        }
        return;
    }

    // Import messages
    if (!currentChatId) {
        alert('Please select or start a chat session first.');
        return;
    }

    const importType = document.querySelector('input[name="teamsImportType"]:checked').value;
    const teamId = document.getElementById('teamsImportTeamId').value.trim();
    const channelId = document.getElementById('teamsImportChannelId').value.trim();
    const chatMsgId = document.getElementById('teamsImportChatId').value.trim();
    const limit = parseInt(document.getElementById('teamsImportLimit').value) || 20;

    if (importType === 'channel' && (!teamId || !channelId)) {
        alert('Please provide Team ID and Channel ID.');
        return;
    }
    if (importType === 'chat' && !chatMsgId) {
        alert('Please provide Teams Chat ID.');
        return;
    }

    document.getElementById('teamsImportLoading').style.display = 'block';
    document.getElementById('btnSubmitTeamsAction').disabled = true;

    try {
        const res = await fetch('/api/teams/import', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                chat_id: currentChatId,
                target_type: importType,
                team_id: teamId,
                channel_id: channelId,
                teams_chat_id: chatMsgId,
                limit: limit
            })
        });

        const data = await res.json();
        if (res.ok) {
            closeModal('teamsModal');
            await selectChat(currentChatId);
        } else {
            alert(`Teams Import Error: ${data.detail || 'Failed to import messages'}`);
        }
    } catch (e) {
        console.error('Error importing Teams messages:', e);
        alert(`An error occurred during Teams import: ${e.message}`);
    } finally {
        document.getElementById('teamsImportLoading').style.display = 'none';
        document.getElementById('btnSubmitTeamsAction').disabled = false;
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

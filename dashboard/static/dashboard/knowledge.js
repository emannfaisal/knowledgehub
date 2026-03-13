function getCSRFToken(){
    return document.cookie.split(';').find(row => row.trim().startsWith('csrftoken=')).split('=')[1];
}

document.addEventListener("DOMContentLoaded", () => {
    loadFolders();
    setupEventListeners();
});

function setupEventListeners() {
    // Enter key to create folder
    const folderInput = document.getElementById('folder-name');
    if (folderInput) {
        folderInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') createFolder();
        });
    }

    // File input handling
    const fileInput = document.getElementById('document-file');
    const dropZone = document.getElementById('drop-zone');
    
    if (dropZone) {
        // Click to browse
        dropZone.addEventListener('click', () => fileInput.click());
        
        // Drag and drop
        dropZone.addEventListener('dragover', (e) => {
            e.preventDefault();
            dropZone.classList.add('border-indigo-500', 'bg-indigo-50');
        });
        
        dropZone.addEventListener('dragleave', () => {
            dropZone.classList.remove('border-indigo-500', 'bg-indigo-50');
        });
        
        dropZone.addEventListener('drop', (e) => {
            e.preventDefault();
            dropZone.classList.remove('border-indigo-500', 'bg-indigo-50');
            const files = e.dataTransfer.files;
            if (files.length > 0) {
                fileInput.files = files;
                uploadDocument();
            }
        });
        
        // Auto-upload on file select
        fileInput.addEventListener('change', uploadDocument);
    }
}

async function createFolder(){
    const folderNameInput = document.getElementById('folder-name');
    const folderName = folderNameInput.value.trim();
    
    if (!folderName) {
        alert('Please enter a folder name');
        return;
    }
    
    try {
        const res = await fetch('/knowledge/folders/', {
            method: 'POST',
            headers: {
                'X-CSRFToken': getCSRFToken(),
                'Content-Type': 'application/x-www-form-urlencoded'
            },
            body: `name=${encodeURIComponent(folderName)}`
        });
        
        const data = await res.json();
        
        if (!res.ok) {
            alert(data.error || 'Failed to create folder');
            return;
        }
        
        folderNameInput.value = '';
        await loadFolders();
    } catch (error) {
        alert('Error creating folder: ' + error.message);
    }
}

async function loadFolders(){
    try {
        const res = await fetch('/knowledge/folders/');
        const data = await res.json();
        const list = document.getElementById('folder-list');
        list.innerHTML = '';
      
        if (data.folders.length === 0) {
            list.innerHTML = '<li class="text-gray-400 italic text-sm p-2">No folders yet. Create one above.</li>';
            return;
        }
        data.folders.forEach(folder => {
            const li = document.createElement('li');
            li.className = 'p-3 hover:bg-indigo-50 cursor-pointer rounded transition flex items-center justify-between group';
            li.innerHTML = `
                <span onclick="loadDocuments('${folder.id}', '${folder.name}')" class="flex-1 flex items-center gap-2 font-medium text-gray-700">
                    <i class="fas fa-folder text-indigo-600"></i>
                    ${folder.name}
                </span>
                <button onclick="deleteFolder('${folder.id}')" class="text-red-500 text-sm hover:text-red-700 opacity-0 group-hover:opacity-100 transition" title="Delete folder">
                    <i class="fas fa-trash"></i>
                </button>
            `;
            list.appendChild(li);
        });
    } catch (error) {
        console.error('Error loading folders:', error);
        alert('Error loading folders');
    }
}

let currentFolderId = null;

async function loadDocuments(folderId, folderName){
    currentFolderId = folderId;
    document.getElementById('current-folder-title').innerText = folderName;
    document.getElementById('folder-description').innerHTML = `<i class="fas fa-folder mr-2 text-indigo-600"></i>${folderName}`;
    document.getElementById('upload-section').classList.remove('hidden');
    
    try {
        const res = await fetch(`/knowledge/folders/${folderId}`);
        const data = await res.json();
        const list = document.getElementById("document-list");
        
        list.innerHTML = '';
        
        if (data.documents.length === 0) {
            list.innerHTML = '<li class="text-gray-400 italic text-sm p-2">No documents in this folder yet. Upload one above.</li>';
            return;
        }
        
        data.documents.forEach(doc => {
            const li = document.createElement('li');
            li.className = 'p-3 hover:bg-gray-50 rounded transition flex items-center justify-between group border-b border-gray-100 last:border-b-0';
            
            // Determine file icon based on extension
            let icon = 'fa-file';
            if (doc.name.endsWith('.pdf')) icon = 'fa-file-pdf text-red-500';
            else if (doc.name.endsWith('.txt')) icon = 'fa-file-lines text-blue-500';
            else if (doc.name.endsWith('.docx')) icon = 'fa-file-word text-blue-600';
            
            li.innerHTML = `
                <span class="flex-1 flex items-center gap-3 text-gray-700">
                    <i class="fas ${icon}"></i>
                    <span class="text-sm font-medium">${escapeHtml(doc.name)}</span>
                </span>
                <button onclick="deleteDocument('${doc.id}')" class="text-red-500 text-sm hover:text-red-700 opacity-0 group-hover:opacity-100 transition" title="Delete document">
                    <i class="fas fa-trash"></i>
                </button>
            `;
            list.appendChild(li);
        });
    } catch (error) {
        console.error('Error loading documents:', error);
        alert('Error loading documents');
    }
}

async function uploadDocument(){
    if (!currentFolderId){
        alert('Please select a folder first');
        return;
    }
    
    const fileInput = document.getElementById('document-file');
    const file = fileInput.files[0];
    
    if (!file) {
        return;
    }

    // Validate file type
    const validTypes = ['.pdf', '.txt', '.docx'];
    const fileName = file.name.toLowerCase();
    const isValid = validTypes.some(ext => fileName.endsWith(ext));
    
    if (!isValid) {
        alert('Please upload a PDF, TXT, or DOCX file');
        fileInput.value = '';
        return;
    }
    
    const formData = new FormData();
    formData.append('file', file);

    try {
        const dropZone = document.getElementById('drop-zone');
        const originalHTML = dropZone.innerHTML;
        dropZone.innerHTML = '<div class="text-center"><i class="fas fa-spinner fa-spin text-indigo-600 text-2xl mb-2"></i><p class="text-sm text-gray-700">Uploading...</p></div>';
        
        const res = await fetch(`/knowledge/folders/${currentFolderId}/documents/`, {
            method: 'POST',
            headers: {
                'X-CSRFToken': getCSRFToken()
            },
            body: formData
        });

        if (!res.ok) {
            const data = await res.json();
            throw new Error(data.error || 'Upload failed');
        }

        fileInput.value = '';
        dropZone.innerHTML = originalHTML;
        await loadDocuments(currentFolderId, document.getElementById('current-folder-title').innerText);
        
    } catch (error) {
        alert('Error uploading document: ' + error.message);
        const dropZone = document.getElementById('drop-zone');
        dropZone.innerHTML = '<div class="text-center"><i class="fas fa-cloud-arrow-up text-3xl text-gray-400 mb-3"></i><p class="text-sm font-medium text-gray-700 mb-1">Drag documents here or click to browse</p><p class="text-xs text-gray-500">Supported: PDF, TXT, DOCX</p></div>';
        fileInput.value = '';
    }
}

async function deleteDocument(documentId) {
    if (!confirm('Delete this document?')) return;
    
    try {
        const res = await fetch(`/knowledge/documents/${documentId}/`, {
            method: 'DELETE',
            headers: {
                'X-CSRFToken': getCSRFToken()
            }
        });

        if (!res.ok) throw new Error('Delete failed');
        
        await loadDocuments(currentFolderId, document.getElementById('current-folder-title').innerText);
    } catch (error) {
        alert('Error deleting document: ' + error.message);
    }
}

async function deleteFolder(folderId) {
    if (!confirm('Delete this folder and all documents?')) return;
    
    try {
        const res = await fetch(`/knowledge/folders/${folderId}/`, {
            method: 'DELETE',
            headers: {
                'X-CSRFToken': getCSRFToken()
            }
        });

        if (!res.ok) throw new Error('Delete failed');
        
        await loadFolders();
        document.getElementById('current-folder-title').innerText = 'Select a folder';
        document.getElementById('folder-description').innerText = 'Choose a folder from the left to view and upload documents';
        document.getElementById('upload-section').classList.add('hidden');
        document.getElementById('document-list').innerHTML = '<li class="text-gray-400 italic text-sm p-2">No documents in this folder</li>';
        currentFolderId = null;
    } catch (error) {
        alert('Error deleting folder: ' + error.message);
    }
}

function escapeHtml(text) {
    const map = {
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#039;'
    };
    return text.replace(/[&<>"']/g, m => map[m]);
}


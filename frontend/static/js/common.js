/**
 * ملف JavaScript مشترك لتحسينات واجهة المستخدم
 */

// ============================================
// Toast Notifications
// ============================================
function showToast(message, type = 'info', duration = 5000) {
    const toastContainer = getOrCreateToastContainer();
    
    const toast = document.createElement('div');
    toast.className = `alert alert-${type} alert-dismissible fade show toast-notification`;
    toast.setAttribute('role', 'alert');
    toast.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        z-index: 9999;
        min-width: 300px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.15);
        animation: slideInRight 0.3s ease-out;
    `;
    
    toast.innerHTML = `
        <strong>${getToastTitle(type)}</strong> ${message}
        <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
    `;
    
    toastContainer.appendChild(toast);
    
    // إزالة تلقائية بعد المدة المحددة
    setTimeout(() => {
        toast.classList.remove('show');
        setTimeout(() => toast.remove(), 300);
    }, duration);
    
    return toast;
}

function getOrCreateToastContainer() {
    let container = document.getElementById('toast-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'toast-container';
        container.style.cssText = 'position: fixed; top: 20px; right: 20px; z-index: 9999;';
        document.body.appendChild(container);
    }
    return container;
}

function getToastTitle(type) {
    const titles = {
        'success': '✅ نجح:',
        'error': '❌ خطأ:',
        'warning': '⚠️ تحذير:',
        'info': 'ℹ️ معلومات:'
    };
    return titles[type] || '';
}

// ============================================
// Loading States
// ============================================
function setLoading(elementId, isLoading, loadingText = 'جاري التحميل...') {
    const element = document.getElementById(elementId);
    if (!element) return;
    
    if (isLoading) {
        element.disabled = true;
        element.dataset.originalText = element.innerHTML;
        element.innerHTML = `
            <span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>
            ${loadingText}
        `;
    } else {
        element.disabled = false;
        element.innerHTML = element.dataset.originalText || element.innerHTML;
    }
}

// ============================================
// Error Handling
// ============================================
async function fetchWithErrorHandling(url, options = {}) {
    try {
        const response = await fetch(url, {
            ...options,
            credentials: 'include',
            headers: {
                'Content-Type': 'application/json',
                ...options.headers
            }
        });
        
        if (!response.ok) {
            let errorMessage = 'حدث خطأ غير معروف';
            try {
                const errorData = await response.json();
                errorMessage = errorData.message || errorMessage;
            } catch (e) {
                errorMessage = `HTTP ${response.status}: ${response.statusText}`;
            }
            throw new Error(errorMessage);
        }
        
        return await response.json();
    } catch (error) {
        console.error('Fetch error:', error);
        showToast(error.message || 'حدث خطأ أثناء الاتصال', 'error');
        throw error;
    }
}

// ============================================
// Debounce Function
// ============================================
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

// ============================================
// Form Validation
// ============================================
function validateForm(formId) {
    const form = document.getElementById(formId);
    if (!form) return false;
    
    const inputs = form.querySelectorAll('input[required], select[required], textarea[required]');
    let isValid = true;
    
    inputs.forEach(input => {
        if (!input.value.trim()) {
            input.classList.add('is-invalid');
            isValid = false;
        } else {
            input.classList.remove('is-invalid');
        }
    });
    
    return isValid;
}

// ============================================
// Confirmation Dialog
// ============================================
function confirmAction(message, onConfirm, onCancel = null) {
    if (confirm(message)) {
        if (onConfirm) onConfirm();
    } else {
        if (onCancel) onCancel();
    }
}

// ============================================
// Table Utilities
// ============================================
function sortTable(tableId, columnIndex, isNumeric = false) {
    const table = document.getElementById(tableId);
    if (!table) return;
    
    const tbody = table.querySelector('tbody');
    if (!tbody) return;
    
    const rows = Array.from(tbody.querySelectorAll('tr'));
    const isAscending = table.dataset.sortDirection !== 'asc';
    
    rows.sort((a, b) => {
        const aText = a.cells[columnIndex].textContent.trim();
        const bText = b.cells[columnIndex].textContent.trim();
        
        if (isNumeric) {
            return isAscending ? 
                parseFloat(aText) - parseFloat(bText) : 
                parseFloat(bText) - parseFloat(aText);
        } else {
            return isAscending ? 
                aText.localeCompare(bText, 'ar') : 
                bText.localeCompare(aText, 'ar');
        }
    });
    
    rows.forEach(row => tbody.appendChild(row));
    table.dataset.sortDirection = isAscending ? 'asc' : 'desc';
}

// ============================================
// Search/Filter
// ============================================
function filterTable(tableId, searchInputId) {
    const searchInput = document.getElementById(searchInputId);
    const table = document.getElementById(tableId);
    
    if (!searchInput || !table) return;
    
    const filter = searchInput.value.toLowerCase();
    const rows = table.querySelectorAll('tbody tr');
    
    rows.forEach(row => {
        const text = row.textContent.toLowerCase();
        row.style.display = text.includes(filter) ? '' : 'none';
    });
}

// ============================================
// Auto-save
// ============================================
function setupAutoSave(formId, saveFunction, interval = 30000) {
    const form = document.getElementById(formId);
    if (!form) return;
    
    let autoSaveTimer;
    
    form.addEventListener('input', debounce(() => {
        clearTimeout(autoSaveTimer);
        autoSaveTimer = setTimeout(() => {
            if (saveFunction) {
                saveFunction();
                showToast('تم الحفظ التلقائي', 'success', 2000);
            }
        }, interval);
    }, 1000));
}

// ============================================
// Copy to Clipboard
// ============================================
async function copyToClipboard(text) {
    try {
        await navigator.clipboard.writeText(text);
        showToast('تم النسخ إلى الحافظة', 'success', 2000);
        return true;
    } catch (err) {
        console.error('Failed to copy:', err);
        showToast('فشل النسخ إلى الحافظة', 'error');
        return false;
    }
}

// ============================================
// Format Numbers
// ============================================
function formatNumber(num, decimals = 2) {
    return new Intl.NumberFormat('ar-SA', {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals
    }).format(num);
}

// ============================================
// Format Date
// ============================================
function formatDate(date, format = 'ar-SA') {
    return new Intl.DateTimeFormat(format, {
        year: 'numeric',
        month: 'long',
        day: 'numeric'
    }).format(new Date(date));
}

// ============================================
// CSS Animation
// ============================================
const style = document.createElement('style');
style.textContent = `
    @keyframes slideInRight {
        from {
            transform: translateX(100%);
            opacity: 0;
        }
        to {
            transform: translateX(0);
            opacity: 1;
        }
    }
    
    .toast-notification {
        animation: slideInRight 0.3s ease-out;
    }
`;
document.head.appendChild(style);


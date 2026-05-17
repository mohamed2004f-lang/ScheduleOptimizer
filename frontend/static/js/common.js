/**
 * ملف JavaScript مشترك لتحسينات واجهة المستخدم
 */

// ============================================
// CSRF: attach token to unsafe fetch requests
// ============================================
(function initCsrfFetchPatch(){
    try {
        const SAFE_METHODS = new Set(['GET','HEAD','OPTIONS']);
        const originalFetch = window.fetch.bind(window);

        function getToken(){
            const meta = document.querySelector('meta[name="csrf-token"]');
            return meta ? (meta.getAttribute('content') || '') : '';
        }

        function isSameOrigin(url){
            try {
                const u = new URL(url, window.location.href);
                return u.origin === window.location.origin;
            } catch (e) {
                return true; // relative URLs
            }
        }

        window.fetch = function(input, init){
            const cfg = init ? { ...init } : {};
            const method = (cfg.method || 'GET').toString().toUpperCase();

            // Only attach to same-origin unsafe methods
            const url = (typeof input === 'string') ? input : (input && input.url) ? input.url : '';
            if (!SAFE_METHODS.has(method) && isSameOrigin(url)) {
                const token = getToken();
                const headers = new Headers(cfg.headers || (typeof input !== 'string' && input && input.headers) || {});
                if (token && !headers.has('X-CSRFToken') && !headers.has('X-CSRF-Token')) {
                    headers.set('X-CSRFToken', token);
                }
                cfg.headers = headers;
            }
            return originalFetch(input, cfg);
        };
    } catch (e) {
        // do nothing - keep fetch behavior unchanged if patch fails
        console.warn('CSRF fetch patch failed', e);
    }
})();

// ============================================
// Theme (Dark Mode)
// ============================================
const THEME_STORAGE_KEY = 'scheduleOptimizerTheme';

function normalizeToastType(type) {
    const t = String(type || 'info').toLowerCase();
    if (t === 'error' || t === 'err') return 'danger';
    if (t === 'warn') return 'warning';
    if (['success', 'danger', 'warning', 'info', 'primary'].includes(t)) return t;
    return 'info';
}

function getThemePreference() {
    try {
        return localStorage.getItem(THEME_STORAGE_KEY) || 'light';
    } catch (_e) {
        return 'light';
    }
}

function applyTheme(theme) {
    const t = theme === 'dark' ? 'dark' : 'light';
    document.documentElement.setAttribute('data-theme', t);
    try { localStorage.setItem(THEME_STORAGE_KEY, t); } catch (_e) { /* ignore */ }
    const btn = document.getElementById('themeToggleBtn');
    if (btn) {
        const isDark = t === 'dark';
        btn.setAttribute('aria-pressed', isDark ? 'true' : 'false');
        btn.title = isDark ? 'الوضع الفاتح' : 'الوضع الليلي';
        btn.innerHTML = isDark
            ? '<i class="fa-solid fa-sun" aria-hidden="true"></i>'
            : '<i class="fa-solid fa-moon" aria-hidden="true"></i>';
    }
}

function toggleTheme() {
    applyTheme(getThemePreference() === 'dark' ? 'light' : 'dark');
}

function initTheme() {
    let theme = getThemePreference();
    if (theme !== 'dark' && theme !== 'light' && window.matchMedia) {
        theme = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    }
    applyTheme(theme);
    const btn = document.getElementById('themeToggleBtn');
    if (btn && !btn.dataset.bound) {
        btn.dataset.bound = '1';
        btn.addEventListener('click', toggleTheme);
    }
}

// ============================================
// Toast Notifications (موحّد — Bootstrap)
// ============================================
function getToastContainer() {
    return document.getElementById('toastContainer')
        || document.getElementById('toast-container');
}

function showToast(message, type = 'info', duration = 5000) {
    const kind = normalizeToastType(type);
    const container = getToastContainer();
    if (!container) {
        console.warn('toastContainer missing', message);
        return null;
    }

    const icons = {
        success: 'check-circle',
        danger: 'exclamation-circle',
        warning: 'exclamation-triangle',
        info: 'info-circle',
        primary: 'bell'
    };
    const titles = {
        success: 'نجح',
        danger: 'خطأ',
        warning: 'تحذير',
        info: 'معلومة',
        primary: 'تنبيه'
    };
    const bgClass = {
        success: 'text-bg-success',
        danger: 'text-bg-danger',
        warning: 'text-bg-warning',
        info: 'text-bg-primary',
        primary: 'text-bg-primary'
    }[kind] || 'text-bg-primary';

    const toast = document.createElement('div');
    toast.className = `toast align-items-center border-0 ${bgClass}`;
    toast.setAttribute('role', 'alert');
    toast.setAttribute('aria-live', 'assertive');
    toast.setAttribute('aria-atomic', 'true');
    const safeMsg = String(message == null ? '' : message)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
    toast.innerHTML = `
        <div class="d-flex">
            <div class="toast-body">
                <i class="fa-solid fa-${icons[kind] || 'info-circle'} me-2" aria-hidden="true"></i>
                <strong class="me-1">${titles[kind] || 'معلومة'}:</strong>${safeMsg}
            </div>
            <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="إغلاق"></button>
        </div>`;
    container.appendChild(toast);

    if (window.bootstrap && typeof window.bootstrap.Toast !== 'undefined') {
        const bsToast = window.bootstrap.Toast.getOrCreateInstance(toast, { delay: duration });
        bsToast.show();
        toast.addEventListener('hidden.bs.toast', () => toast.remove());
    } else {
        toast.classList.add('show');
        setTimeout(() => toast.remove(), duration);
    }
    return toast;
}

window.showToast = showToast;
window.initTheme = initTheme;
window.toggleTheme = toggleTheme;

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
// API Helper Functions (Enhanced)
// ============================================

/**
 * فئة خطأ API مخصصة
 */
class ApiError extends Error {
    constructor(message, code, status) {
        super(message);
        this.code = code;
        this.status = status;
        this.name = 'ApiError';
    }
}

/**
 * إرسال طلب API مع معالجة الأخطاء
 */
async function apiRequest(url, options = {}) {
    const defaultOptions = {
        credentials: 'include',
        headers: {
            'Content-Type': 'application/json',
            ...options.headers
        }
    };
    
    try {
        const response = await fetch(url, { ...defaultOptions, ...options });
        const data = await response.json();
        
        if (!response.ok) {
            throw new ApiError(data.message || 'حدث خطأ غير متوقع', data.code, response.status);
        }
        
        return data;
    } catch (error) {
        if (error instanceof ApiError) {
            throw error;
        }
        throw new ApiError('فشل الاتصال بالخادم', 'NETWORK_ERROR', 0);
    }
}

/** إرسال طلب GET */
async function apiGet(url) {
    return apiRequest(url, { method: 'GET' });
}

/** إرسال طلب POST */
async function apiPost(url, data) {
    return apiRequest(url, {
        method: 'POST',
        body: JSON.stringify(data)
    });
}

/** إرسال طلب PUT */
async function apiPut(url, data) {
    return apiRequest(url, {
        method: 'PUT',
        body: JSON.stringify(data)
    });
}

/** إرسال طلب DELETE */
async function apiDelete(url) {
    return apiRequest(url, { method: 'DELETE' });
}

// ============================================
// Error Handling (Legacy)
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

function getCsrfToken() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? (meta.getAttribute('content') || '') : '';
}

/** رؤوس JSON + CSRF لطلبات fetch الصريحة */
function jsonApiHeaders(extra = {}) {
    const headers = { 'Content-Type': 'application/json', ...extra };
    const token = getCsrfToken();
    if (token) headers['X-CSRFToken'] = token;
    return headers;
}

/** بحث فوري في جدول HTML مع ترتيب بالنقر على رأس العمود */
function initInteractiveTable(tableId, options = {}) {
    const table = document.getElementById(tableId);
    if (!table) return;
    const enableSearch = options.search !== false;
    const placeholder = options.placeholder || 'بحث في الجدول…';
    const toolbarId = options.toolbarId || `${tableId}-toolbar`;

    let toolbar = document.getElementById(toolbarId);
    if (enableSearch && !toolbar) {
        toolbar = document.createElement('div');
        toolbar.id = toolbarId;
        toolbar.className = 'table-toolbar';
        toolbar.innerHTML = `
            <input type="search" class="form-control form-control-sm table-search" id="${tableId}-search"
                   placeholder="${placeholder}" autocomplete="off" aria-label="بحث">`;
        table.parentNode.insertBefore(toolbar, table);
    }

    table.classList.add('table-sortable');
    if (enableSearch) {
        const searchInput = document.getElementById(`${tableId}-search`);
        const filterRows = () => {
            const q = (searchInput && searchInput.value || '').trim().toLowerCase();
            table.querySelectorAll('tbody tr').forEach(row => {
                const text = (row.textContent || '').toLowerCase();
                row.style.display = !q || text.includes(q) ? '' : 'none';
            });
        };
        if (searchInput && !searchInput.dataset.bound) {
            searchInput.dataset.bound = '1';
            searchInput.addEventListener('input', debounce(filterRows, 200));
        }
    }

    table.querySelectorAll('thead th').forEach((th, colIndex) => {
        if (th.dataset.sortCol != null) return;
        th.dataset.sortCol = String(colIndex);
        th.addEventListener('click', () => {
            const tbody = table.querySelector('tbody');
            if (!tbody) return;
            const rows = Array.from(tbody.querySelectorAll('tr')).filter(r => r.style.display !== 'none');
            const asc = th.dataset.sortDir !== 'asc';
            const numeric = th.dataset.sortNumeric === '1';
            rows.sort((a, b) => {
                const aText = (a.cells[colIndex] && a.cells[colIndex].textContent || '').trim();
                const bText = (b.cells[colIndex] && b.cells[colIndex].textContent || '').trim();
                if (numeric) {
                    return asc ? (parseFloat(aText) || 0) - (parseFloat(bText) || 0)
                        : (parseFloat(bText) || 0) - (parseFloat(aText) || 0);
                }
                return asc ? aText.localeCompare(bText, 'ar') : bText.localeCompare(aText, 'ar');
            });
            rows.forEach(r => tbody.appendChild(r));
            table.querySelectorAll('thead th[data-sort-dir]').forEach(h => {
                if (h !== th) delete h.dataset.sortDir;
            });
            th.dataset.sortDir = asc ? '▲' : '▼';
        });
    });
}

/** بحث في قائمة (ul/li أو عناصر مخصّصة) */
function initListSearch(containerId, options = {}) {
    const container = document.getElementById(containerId);
    if (!container) return;
    const itemSelector = options.itemSelector || 'li';
    const inputId = options.inputId || `${containerId}-search`;
    let input = document.getElementById(inputId);
    if (!input) {
        input = document.createElement('input');
        input.type = 'search';
        input.id = inputId;
        input.className = 'form-control form-control-sm mb-2';
        input.placeholder = options.placeholder || 'بحث…';
        input.style.maxWidth = options.maxWidth || '320px';
        container.parentNode.insertBefore(input, container);
    }
    if (input.dataset.bound) return;
    input.dataset.bound = '1';
    input.addEventListener('input', debounce(() => {
        const q = input.value.trim().toLowerCase();
        container.querySelectorAll(itemSelector).forEach(item => {
            const text = (item.textContent || '').toLowerCase();
            item.style.display = !q || text.includes(q) ? '' : 'none';
        });
    }, 200));
}

window.getCsrfToken = getCsrfToken;
window.jsonApiHeaders = jsonApiHeaders;
window.initInteractiveTable = initInteractiveTable;
window.initListSearch = initListSearch;

document.addEventListener('DOMContentLoaded', () => {
    initTheme();
});

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
// Published schedule display (non-editor UIs)
// تنسيق موحّد: اسم المقرر (ق الغرفة) — الأستاذ
// ============================================
window.SCHEDULE_DAYS = ['السبت', 'الأحد', 'الإثنين', 'الثلاثاء', 'الأربعاء', 'الخميس'];

/**
 * يوحّد تهجئة اليوم كما في SCHEDULE_DAYS حتى تظهر الحصص في الشبكة حتى لو الجدول خزّن «الاثنين» بدل «الإثنين».
 * @param {string} dayStr
 * @returns {string}
 */
function canonicalScheduleDayForGrid(dayStr) {
    const raw = String(dayStr || '').trim();
    if (!raw) return '';
    const days = window.SCHEDULE_DAYS || [];
    if (days.includes(raw)) return raw;
    const alias = {
        'الاثنين': 'الإثنين',
        'إثنين': 'الإثنين',
        'الثلاثا': 'الثلاثاء',
        'الاربعاء': 'الأربعاء',
        'الأربعا': 'الأربعاء',
        'اربعاء': 'الأربعاء',
        'الخميس': 'الخميس',
    };
    if (alias[raw]) return alias[raw];
    const fold = (s) => String(s).replace(/\u0640/g, '').replace(/\s/g, '');
    const rf = fold(raw);
    for (const d of days) {
        if (fold(d) === rf) return d;
    }
    return raw;
}

function escapeHtmlSchedule(s) {
    return String(s ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

function escapeAttrSchedule(s) {
    return String(s ?? '')
        .replace(/&/g, '&amp;')
        .replace(/"/g, '&quot;');
}

/**
 * @param {{ course_name?: string, room?: string, instructor?: string }} row
 * @returns {string}
 */
function formatPublishedScheduleCell(row) {
    const name = row && row.course_name != null ? String(row.course_name).trim() : '';
    const room = row && row.room != null ? String(row.room).trim() : '';
    const instructor = row && row.instructor != null ? String(row.instructor).trim() : '';
    let s = name;
    if (room) s += ` (ق ${room})`;
    if (instructor) s += (s ? ' — ' : '') + instructor;
    return s;
}

/**
 * @param {Array<Record<string, unknown>>} scheduleRows
 * @param {{ compact?: boolean }} opts
 * @returns {string}
 */
function buildPublishedTimetableHtml(scheduleRows, opts) {
    opts = opts || {};
    const compactClass = opts.compact ? ' is-compact' : '';
    const DAYS = window.SCHEDULE_DAYS || [];
    const rows = Array.isArray(scheduleRows) ? scheduleRows.filter(r => r && String(r.day || '').trim() && String(r.time || '').trim()) : [];
    if (!rows.length) {
        return '<div class="alert alert-info p-2 mb-0">لا توجد حصص في الجدول لهذا العرض.</div>';
    }
    const timeSet = new Set();
    rows.forEach(r => {
        timeSet.add(String(r.time).trim());
    });
    const timeSlots = Array.from(timeSet).sort((a, b) => a.localeCompare(b, 'ar'));
    const slotsMap = {};
    rows.forEach(row => {
        const d = canonicalScheduleDayForGrid(row.day);
        const t = String(row.time || '').trim();
        const key = `${d}|${t}`;
        if (!slotsMap[key]) slotsMap[key] = [];
        slotsMap[key].push(row);
    });
    let html = `<table class="timetable timetable--cols3${compactClass}"><thead><tr><th rowspan="2" class="day-header">اليوم</th>`;
    timeSlots.forEach(time => {
        html += `<th colspan="3" class="time-header" data-time-slot="${escapeAttrSchedule(time)}">`;
        html += `<div class="th-time-label">${escapeHtmlSchedule(time)}</div>`;
        html += '</th>';
    });
    html += '</tr><tr>';
    for (let i = 0; i < timeSlots.length; i++) {
        html += '<th class="sub-time-header">المقرر</th><th class="sub-time-header">الأستاذ</th><th class="sub-time-header">القاعة</th>';
    }
    html += '</tr></thead><tbody>';
    DAYS.forEach(day => {
        const dAttr = escapeAttrSchedule(day);
        html += `<tr><th class="day-header">${escapeHtmlSchedule(day)}</th>`;
        timeSlots.forEach(time => {
            const key = `${day}|${time}`;
            const courses = slotsMap[key] || [];
            const tAttr = escapeAttrSchedule(time);
            html += `<td colspan="3" class="time-slot-cell slot-slot-block" data-slot-day="${dAttr}" data-slot-time="${tAttr}">`;
            html += '<div class="slot-aligned-rows">';
            if (!courses.length) {
                html += '<div class="slot-course-record slot-course-record--empty">';
                html += '<div class="slot-cell slot-cell--course"><span class="slot-placeholder">—</span></div>';
                html += '<div class="slot-cell slot-cell--inst"><span class="slot-placeholder">—</span></div>';
                html += '<div class="slot-cell slot-cell--room"><span class="slot-placeholder">—</span></div>';
                html += '</div>';
            } else {
                courses.forEach((c, idx) => {
                    if (idx > 0) html += '<div class="slot-record-fullsep"></div>';
                    html += '<div class="slot-course-record">';
                    html += `<div class="slot-cell slot-cell--course"><span class="course-pub-label">${escapeHtmlSchedule(c.course_name)}</span></div>`;
                    html += `<div class="slot-cell slot-cell--inst"><span class="slot-text">${escapeHtmlSchedule(c.instructor)}</span></div>`;
                    html += `<div class="slot-cell slot-cell--room"><span class="slot-text">${escapeHtmlSchedule(c.room)}</span></div>`;
                    html += '</div>';
                });
            }
            html += '</div></td>';
        });
        html += '</tr>';
    });
    html += '</tbody></table>';
    return html;
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


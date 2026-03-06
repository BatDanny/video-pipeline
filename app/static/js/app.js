/**
 * VideoPipe — Global JavaScript Utilities
 */

/** Escape HTML special characters to prevent XSS */
function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

/** Format duration in seconds to human-readable */
function formatDuration(sec) {
    if (sec == null) return '—';
    if (sec < 60) return sec.toFixed(1) + 's';
    const m = Math.floor(sec / 60);
    const s = Math.floor(sec % 60);
    return `${m}:${s.toString().padStart(2, '0')}`;
}

/** Format ISO date string */
function formatDate(iso) {
    if (!iso) return '—';
    return new Date(iso).toLocaleDateString('en-US', {
        month: 'short', day: 'numeric', year: 'numeric',
        hour: '2-digit', minute: '2-digit'
    });
}

/** Simple toast notification */
function showToast(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    toast.style.cssText = `
        position: fixed; bottom: 24px; right: 24px; padding: 12px 20px;
        border-radius: 8px; font-size: 0.85rem; font-weight: 500; z-index: 9999;
        animation: slideInToast 0.3s ease;
        background: ${type === 'error' ? 'var(--color-red-dim)' : type === 'success' ? 'var(--color-green-dim)' : 'var(--bg-surface)'};
        color: ${type === 'error' ? 'var(--color-red)' : type === 'success' ? 'var(--color-green)' : 'var(--text-primary)'};
        border: 1px solid ${type === 'error' ? 'rgba(248,113,113,0.3)' : type === 'success' ? 'rgba(52,211,153,0.3)' : 'var(--border-subtle)'};
    `;
    document.body.appendChild(toast);
    setTimeout(() => { toast.style.opacity = '0'; setTimeout(() => toast.remove(), 300); }, 3000);
}

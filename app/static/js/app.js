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

/* ================================================
   System Status Widget — Live polling (GPU, CPU, RAM, Pipeline)
   ================================================ */
async function refreshSystemStatus() {
    try {
        const resp = await fetch('/api/gpu/status');
        if (!resp.ok) return;
        const sys = await resp.json();

        // --- CPU & RAM ---
        const cpuVal = document.getElementById('sys-cpu');
        const cpuBar = document.getElementById('sys-cpu-bar');
        const ramVal = document.getElementById('sys-ram');
        const ramBar = document.getElementById('sys-ram-bar');

        if (cpuVal) {
            cpuVal.textContent = sys.cpu_pct + '%';
            cpuBar.style.width = Math.min(100, sys.cpu_pct) + '%';
            if (sys.cpu_pct >= 80) cpuBar.style.background = 'var(--color-red)';
            else if (sys.cpu_pct >= 50) cpuBar.style.background = 'var(--color-orange)';
            else cpuBar.style.background = 'var(--color-blue)';
        }

        if (ramVal) {
            ramVal.textContent = sys.ram_used_gb + '/' + sys.ram_total_gb + ' GB';
            ramBar.style.width = sys.ram_pct + '%';
            if (sys.ram_pct >= 85) ramBar.style.background = 'var(--color-red)';
            else if (sys.ram_pct >= 60) ramBar.style.background = 'var(--color-orange)';
            else ramBar.style.background = 'var(--color-green)';
        }

        // --- Pipeline Banner (Sidebar & Dashboard) ---
        const banner = document.getElementById('pipeline-banner');
        const modelEl = document.getElementById('pipeline-model');
        const msgEl = document.getElementById('pipeline-message');

        const dashBanner = document.getElementById('dashboard-live-status');
        const dashModel = document.getElementById('live-banner-model');
        const dashMsg = document.getElementById('live-banner-message');
        const dashProgress = document.getElementById('live-banner-progress');
        const dashFile = document.getElementById('live-banner-file');
        const dashPct = document.getElementById('live-banner-pct');

        if (sys.pipeline) {
            const p = sys.pipeline;
            if (p.active) {
                if (banner) {
                    banner.classList.add('active');
                    modelEl.textContent = p.active_model || p.stage || 'Processing';
                    msgEl.textContent = p.message || '';
                }

                // Dashboard Giant Banner
                if (dashBanner) {
                    dashBanner.style.display = 'block';
                    dashModel.textContent = p.active_model || p.stage || 'Pipeline Active';
                    dashMsg.textContent = p.message || 'Processing video data...';
                    dashProgress.style.width = (p.progress_pct || 0) + '%';
                    const fileName = p.file_name ? `Working on: ${p.file_name}` : 'Initializing...';
                    dashFile.textContent = fileName;
                    dashPct.textContent = Math.round(p.progress_pct || 0) + '%';
                }
            } else {
                if (banner) {
                    banner.classList.remove('active');
                    modelEl.textContent = 'Idle — No active pipeline';
                    msgEl.textContent = '';
                }
                if (dashBanner) {
                    dashBanner.style.display = 'none';
                }
            }
        }

        // --- GPU ---
        const dot = document.getElementById('gpu-dot');
        const name = document.getElementById('gpu-name');
        const tempVal = document.getElementById('gpu-temp');
        const utilVal = document.getElementById('gpu-util');
        const memVal = document.getElementById('gpu-mem');
        const powerVal = document.getElementById('gpu-power');
        const tempBar = document.getElementById('gpu-temp-bar');
        const utilBar = document.getElementById('gpu-util-bar');
        const memBar = document.getElementById('gpu-mem-bar');
        const powerBar = document.getElementById('gpu-power-bar');

        if (!dot) return;

        const shortName = sys.name.replace('NVIDIA GeForce ', '').replace('NVIDIA ', '');
        name.textContent = sys.available ? shortName : 'GPU Offline';
        dot.className = 'gpu-widget-dot status-' + sys.status;

        // Temperature
        tempVal.textContent = sys.temperature_c + '°C';
        const tempPct = Math.min(100, (sys.temperature_c / 90) * 100);
        tempBar.style.width = tempPct + '%';
        if (sys.temperature_c >= 80) tempBar.style.background = 'var(--color-red)';
        else if (sys.temperature_c >= 55) tempBar.style.background = 'var(--color-orange)';
        else tempBar.style.background = 'var(--color-green)';

        // GPU Utilization
        utilVal.textContent = sys.utilization_pct + '%';
        utilBar.style.width = sys.utilization_pct + '%';

        // VRAM
        const memGB = (sys.memory_used_mib / 1024).toFixed(1);
        const memTotalGB = (sys.memory_total_mib / 1024).toFixed(0);
        memVal.textContent = memGB + '/' + memTotalGB + ' GB';
        // Enforce minimum 3% width so 600MB/24GB (2.5%) doesn't look totally empty
        const visualMemPct = sys.memory_used_mib > 100 ? Math.max(3, sys.memory_pct) : sys.memory_pct;
        memBar.style.width = visualMemPct + '%';

        // Power
        powerVal.textContent = Math.round(sys.power_draw_w) + '/' + Math.round(sys.power_limit_w) + 'W';
        powerBar.style.width = sys.power_pct + '%';
        if (sys.power_pct >= 70) powerBar.style.background = 'var(--color-red)';
        else if (sys.power_pct >= 30) powerBar.style.background = 'var(--color-orange)';
        else powerBar.style.background = 'var(--color-green)';

    } catch (e) {
        // Silently fail — widget just stays stale
    }
}

// Start system status polling on page load
document.addEventListener('DOMContentLoaded', () => {
    refreshSystemStatus();
    setInterval(refreshSystemStatus, 3000);
});


// Global Application Script for Classroom Tracker

// Toast Notification Utility
function showToast(message, type = 'info') {
  let container = document.getElementById('toast-container');
  if (!container) {
    container = document.createElement('div');
    container.id = 'toast-container';
    document.body.appendChild(container);
  }

  const toast = document.createElement('div');
  toast.className = `toast-item p-4 rounded-xl shadow-xl border flex items-center justify-between text-sm font-medium transition-all transform translate-y-2 opacity-0 ${
    type === 'success' 
      ? 'bg-emerald-50 dark:bg-emerald-950/80 border-emerald-300 dark:border-emerald-800 text-emerald-900 dark:text-emerald-200' 
      : type === 'warning'
      ? 'bg-amber-50 dark:bg-amber-950/80 border-amber-300 dark:border-amber-800 text-amber-900 dark:text-amber-200'
      : type === 'danger'
      ? 'bg-rose-50 dark:bg-rose-950/80 border-rose-300 dark:border-rose-800 text-rose-900 dark:text-rose-200'
      : 'bg-indigo-50 dark:bg-indigo-950/80 border-indigo-300 dark:border-indigo-800 text-indigo-900 dark:text-indigo-200'
  }`;

  toast.innerHTML = `
    <div class="flex items-center space-x-3">
      <span>${message}</span>
    </div>
    <button onclick="this.parentElement.remove()" class="ml-3 opacity-60 hover:opacity-100 focus:outline-none">&times;</button>
  `;

  container.appendChild(toast);
  requestAnimationFrame(() => {
    toast.classList.remove('translate-y-2', 'opacity-0');
  });

  setTimeout(() => {
    toast.classList.add('opacity-0', 'translate-y-2');
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}

// Assignment Toggle via AJAX
async function toggleAssignment(assignmentId, buttonEl) {
  if (!assignmentId || !buttonEl) return;

  const originalHtml = buttonEl.innerHTML;
  buttonEl.disabled = true;
  buttonEl.classList.add('opacity-75');

  try {
    const res = await fetch(`/api/assignments/${assignmentId}/toggle`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Requested-With': 'XMLHttpRequest'
      }
    });

    const data = await res.json();
    if (data.success) {
      const isCompleted = data.is_completed;
      showToast(data.message, isCompleted ? 'success' : 'info');

      // Update button state & styling
      if (isCompleted) {
        buttonEl.innerHTML = `
          <svg class="w-5 h-5 text-white check-animate" fill="currentColor" viewBox="0 0 20 20">
            <path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd"/>
          </svg>
          <span class="ml-2 font-medium">Completed</span>
        `;
        buttonEl.className = buttonEl.className
          .replace(/bg-slate-[0-9]+/g, '')
          .replace(/hover:bg-[a-z0-9-]+/g, '')
          .replace(/text-[a-z0-9-]+/g, '')
          .replace(/border-[a-z0-9-]+/g, '') + ' bg-emerald-600 hover:bg-emerald-700 text-white border-transparent';
      } else {
        buttonEl.innerHTML = `
          <div class="w-5 h-5 rounded-full border-2 border-slate-400 dark:border-slate-500"></div>
          <span class="ml-2 font-medium">Mark as Done</span>
        `;
        buttonEl.className = buttonEl.className
          .replace(/bg-emerald-[0-9]+/g, '')
          .replace(/hover:bg-[a-z0-9-]+/g, '')
          .replace(/text-white/g, '') + ' bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-750 text-slate-700 dark:text-slate-300 border-slate-300 dark:border-slate-700';
      }

      // Update card badge if present
      const card = document.getElementById(`assignment-card-${assignmentId}`);
      if (card) {
        const badge = card.querySelector('.status-badge');
        if (badge) {
          if (isCompleted) {
            badge.className = 'status-badge inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300';
            badge.textContent = 'Completed';
          } else {
            badge.className = 'status-badge inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300';
            badge.textContent = 'Pending';
          }
        }
      }

      // Reload smoothly if we are in a strictly filtered tab (e.g. view only incomplete, so the card disappears after a moment)
      const currentUrl = new URL(window.location.href);
      const currentFilter = currentUrl.searchParams.get('filter');
      if (currentFilter && (currentFilter === 'completed' || currentFilter === 'incomplete' || currentFilter === 'overdue')) {
        setTimeout(() => window.location.reload(), 600);
      }
    } else {
      showToast(data.message || 'Error updating status', 'danger');
      buttonEl.innerHTML = originalHtml;
    }
  } catch (err) {
    console.error(err);
    showToast('Failed to connect to server.', 'danger');
    buttonEl.innerHTML = originalHtml;
  } finally {
    buttonEl.disabled = false;
    buttonEl.classList.remove('opacity-75');
  }
}

// Live Admin Notification Poller (runs every 15s if admin is logged in)
function initAdminNotifier() {
  const bellBadge = document.getElementById('admin-bell-badge');
  if (!bellBadge) return; // Not an admin or bell badge absent

  async function checkNotifications() {
    try {
      const res = await fetch('/api/admin/notifications/unread-count');
      if (res.ok) {
        const data = await res.json();
        if (data.unread_count > 0) {
          bellBadge.textContent = data.unread_count > 99 ? '99+' : data.unread_count;
          bellBadge.classList.remove('hidden');
        } else {
          bellBadge.classList.add('hidden');
        }
      }
    } catch (e) {
      // quiet fail for network interruption
    }
  }

  setInterval(checkNotifications, 15000);
}

// Deadline Countdown Formatter
function updateCountdowns() {
  const elements = document.querySelectorAll('[data-deadline]');
  const now = new Date().getTime();

  elements.forEach(el => {
    const deadlineStr = el.getAttribute('data-deadline');
    if (!deadlineStr) return;

    const deadline = new Date(deadlineStr).getTime();
    const diff = deadline - now;
    const isCompleted = el.getAttribute('data-completed') === 'true';

    if (isCompleted) {
      // Completed, no countdown warning needed
      return;
    }

    if (diff < 0) {
      const pastHours = Math.floor(Math.abs(diff) / (1000 * 60 * 60));
      const pastDays = Math.floor(pastHours / 24);
      if (pastDays > 0) {
        el.textContent = `Overdue by ${pastDays} day${pastDays > 1 ? 's' : ''}`;
      } else {
        el.textContent = `Overdue by ${pastHours} hour${pastHours > 1 ? 's' : ''}`;
      }
      el.classList.add('text-rose-600', 'dark:text-rose-400', 'font-semibold');
    } else {
      const hours = Math.floor(diff / (1000 * 60 * 60));
      const days = Math.floor(hours / 24);

      if (days > 1) {
        el.textContent = `Due in ${days} days`;
      } else if (hours > 0) {
        el.textContent = `Due in ${hours} hours!`;
        el.classList.add('text-amber-600', 'dark:text-amber-400', 'font-semibold');
      } else {
        const minutes = Math.floor(diff / (1000 * 60));
        el.textContent = `Due in ${minutes} minutes!`;
        el.classList.add('text-rose-600', 'dark:text-rose-400', 'font-bold', 'urgent-badge');
      }
    }
  });
}

// Initialize on DOM ready
document.addEventListener('DOMContentLoaded', () => {
  initAdminNotifier();
  updateCountdowns();
  setInterval(updateCountdowns, 60000);
});

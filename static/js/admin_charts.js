// Admin Interactive Charts and Analytics

let assignmentChartInstance = null;
let currentChartData = null;

async function loadAdminChart(batchId = '', subjectId = '') {
  const chartCanvas = document.getElementById('assignmentCompletionChart');
  if (!chartCanvas) return;

  const ctx = chartCanvas.getContext('2d');
  const loadingEl = document.getElementById('chart-loading-indicator');
  if (loadingEl) loadingEl.classList.remove('hidden');

  try {
    let url = '/api/admin/chart-data?';
    if (batchId) url += `batch_id=${encodeURIComponent(batchId)}&`;
    if (subjectId) url += `subject_id=${encodeURIComponent(subjectId)}&`;

    const res = await fetch(url);
    const data = await res.json();
    currentChartData = data;

    if (loadingEl) loadingEl.classList.add('hidden');

    // Destroy prior chart instance if exists
    if (assignmentChartInstance) {
      assignmentChartInstance.destroy();
    }

    if (!data.labels || data.labels.length === 0) {
      // Empty state
      return;
    }

    const isDarkMode = document.documentElement.classList.contains('dark');
    const textColor = isDarkMode ? '#cbd5e1' : '#334155';
    const gridColor = isDarkMode ? 'rgba(255, 255, 255, 0.08)' : 'rgba(0, 0, 0, 0.06)';

    assignmentChartInstance = new Chart(ctx, {
      type: 'bar',
      data: {
        labels: data.labels,
        datasets: [
          {
            label: 'Completed',
            data: data.completed,
            backgroundColor: '#10b981', // emerald-500
            borderRadius: 6,
            stack: 'Stack 0',
          },
          {
            label: 'Pending / Incomplete',
            data: data.incomplete,
            backgroundColor: '#f43f5e', // rose-500
            borderRadius: 6,
            stack: 'Stack 0',
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: {
          mode: 'index',
          intersect: false,
        },
        plugins: {
          legend: {
            position: 'top',
            labels: {
              color: textColor,
              font: { family: 'Inter, sans-serif', size: 12, weight: '500' }
            }
          },
          tooltip: {
            backgroundColor: isDarkMode ? '#1e293b' : '#ffffff',
            titleColor: isDarkMode ? '#f8fafc' : '#0f172a',
            bodyColor: isDarkMode ? '#cbd5e1' : '#334155',
            borderColor: isDarkMode ? '#334155' : '#e2e8f0',
            borderWidth: 1,
            padding: 12,
            callbacks: {
              afterBody: function(context) {
                const index = context[0].dataIndex;
                const rate = data.rates[index];
                return `\nCompletion Rate: ${rate}% (${data.completed[index]}/${data.total_students} students)`;
              }
            }
          }
        },
        scales: {
          x: {
            stacked: true,
            ticks: {
              color: textColor,
              maxRotation: 45,
              minRotation: 0,
              font: { size: 11 }
            },
            grid: { color: gridColor }
          },
          y: {
            stacked: true,
            beginAtZero: true,
            ticks: {
              color: textColor,
              stepSize: 1,
              precision: 0
            },
            grid: { color: gridColor }
          }
        }
      }
    });

    // Populate the breakdown table if container exists
    renderBreakdownTable(data.assignments);

  } catch (err) {
    console.error('Error loading chart data:', err);
    if (loadingEl) loadingEl.innerHTML = `<span class="text-rose-500 text-sm">Failed to load chart analytics.</span>`;
  }
}

function renderBreakdownTable(assignments) {
  const tbody = document.getElementById('assignment-breakdown-tbody');
  if (!tbody) return;

  if (!assignments || assignments.length === 0) {
    tbody.innerHTML = `<tr><td colspan="5" class="text-center py-6 text-slate-500 text-sm">No assignments found for this filter.</td></tr>`;
    return;
  }

  tbody.innerHTML = assignments.map(a => `
    <tr class="border-b border-slate-100 dark:border-slate-800 hover:bg-slate-50 dark:hover:bg-slate-800/50 transition">
      <td class="py-3 px-4 font-medium text-slate-900 dark:text-slate-100">${escapeHtml(a.title)}</td>
      <td class="py-3 px-4 text-xs font-semibold text-indigo-600 dark:text-indigo-400">${escapeHtml(a.subject)}</td>
      <td class="py-3 px-4">
        <span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-bold bg-emerald-100 dark:bg-emerald-950/60 text-emerald-800 dark:text-emerald-300">
          ${a.completed} / ${a.total_students}
        </span>
      </td>
      <td class="py-3 px-4">
        <div class="flex items-center space-x-2">
          <div class="w-24 bg-slate-200 dark:bg-slate-700 h-2 rounded-full overflow-hidden">
            <div class="bg-emerald-500 h-2 rounded-full" style="width: ${a.rate}%"></div>
          </div>
          <span class="text-xs font-semibold text-slate-600 dark:text-slate-400">${a.rate}%</span>
        </div>
      </td>
      <td class="py-3 px-4 text-right">
        <a href="/admin/assignment/${a.id}/students" class="text-xs font-medium text-indigo-600 dark:text-indigo-400 hover:underline inline-flex items-center space-x-1">
          <span>View Roster</span>
          <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"/></svg>
        </a>
      </td>
    </tr>
  `).join('');
}

// Download Chart as High-Resolution PNG Image
function downloadChartImage() {
  const canvas = document.getElementById('assignmentCompletionChart');
  if (!canvas || !assignmentChartInstance) {
    alert('Chart is still loading or unavailable.');
    return;
  }

  // Create a temporary canvas with white background so transparent PNGs don't look black when shared
  const tempCanvas = document.createElement('canvas');
  tempCanvas.width = canvas.width;
  tempCanvas.height = canvas.height;
  const tempCtx = tempCanvas.getContext('2d');

  // Fill background
  tempCtx.fillStyle = '#ffffff';
  tempCtx.fillRect(0, 0, tempCanvas.width, tempCanvas.height);

  // Draw chart
  tempCtx.drawImage(canvas, 0, 0);

  // Trigger download
  const link = document.createElement('a');
  link.download = `Classroom_Assignment_Stats_${new Date().toISOString().slice(0, 10)}.png`;
  link.href = tempCanvas.toDataURL('image/png', 1.0);
  link.click();
}

function escapeHtml(str) {
  if (!str) return '';
  return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#039;");
}

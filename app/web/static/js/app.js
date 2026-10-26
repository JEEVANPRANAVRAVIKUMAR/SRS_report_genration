/**
 * SRS Solar Daily Log - Frontend Client (SPEC B11)
 * Mobile-First, Indian Numbering, PWA & CSRF Handling
 */

document.addEventListener('DOMContentLoaded', () => {
  initPWA();
  initTheme();
  initIndianNumberFormatting();
});

// 1. PWA Service Worker Registration
function initPWA() {
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/static/sw.js')
      .then(reg => console.log('ServiceWorker registered:', reg.scope))
      .catch(err => console.warn('ServiceWorker registration skipped:', err));
  }
}

// 2. Theme Management (Dark by default, persisted in localStorage)
function initTheme() {
  const currentTheme = localStorage.getItem('srs_theme') || 'dark';
  document.documentElement.setAttribute('data-theme', currentTheme);

  const toggleBtn = document.getElementById('theme-toggle');
  if (toggleBtn) {
    toggleBtn.addEventListener('click', () => {
      const active = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
      document.documentElement.setAttribute('data-theme', active);
      localStorage.setItem('srs_theme', active);
    });
  }
}

// 3. Indian Grouping Number Formatter (SPEC B11)
// Grouping: last 3 digits, then pairs of 2, e.g. 1,03,065.00
function formatIndianNumber(val, decimals = 2) {
  if (val === null || val === undefined || isNaN(val)) return '-';
  const num = Number(val).toFixed(decimals);
  const parts = num.split('.');
  let lastThree = parts[0].substring(parts[0].length - 3);
  const otherNumbers = parts[0].substring(0, parts[0].length - 3);
  if (otherNumbers !== '') {
    lastThree = ',' + lastThree;
  }
  const formattedInt = otherNumbers.replace(/\B(?=(\d{2})+(?!\d))/g, ',') + lastThree;
  return decimals > 0 ? formattedInt + '.' + parts[1] : formattedInt;
}

function initIndianNumberFormatting() {
  document.querySelectorAll('[data-indian-number]').forEach(el => {
    const rawVal = el.getAttribute('data-indian-number');
    const decimals = parseInt(el.getAttribute('data-decimals') || '2', 10);
    el.textContent = formatIndianNumber(rawVal, decimals);
  });
}

// 4. CSRF Fetch Wrapper (AC-20)
function getCsrfToken() {
  const meta = document.querySelector('meta[name="csrf-token"]');
  return meta ? meta.getAttribute('content') : '';
}

async function secureFetch(url, options = {}) {
  const method = (options.method || 'GET').toUpperCase();
  const headers = options.headers || {};

  if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(method)) {
    headers['X-CSRF-Token'] = getCsrfToken();
  }

  options.headers = headers;
  return fetch(url, options);
}

// 5. File Drag & Drop and Upload Interaction
function setupUploadHandlers(dropZoneId, fileInputId, previewContainerId) {
  const dropZone = document.getElementById(dropZoneId);
  const fileInput = document.getElementById(fileInputId);
  const preview = document.getElementById(previewContainerId);

  if (!dropZone || !fileInput) return;

  ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
    dropZone.addEventListener(eventName, e => {
      e.preventDefault();
      e.stopPropagation();
    });
  });

  dropZone.addEventListener('dragover', () => dropZone.classList.add('drag-active'));
  dropZone.addEventListener('dragleave', () => dropZone.classList.remove('drag-active'));

  dropZone.addEventListener('drop', e => {
    dropZone.classList.remove('drag-active');
    const files = e.dataTransfer.files;
    if (files.length > 0) {
      handleFiles(files);
    }
  });

  fileInput.addEventListener('change', () => {
    if (fileInput.files.length > 0) {
      handleFiles(fileInput.files);
    }
  });

  function handleFiles(files) {
    if (preview) {
      preview.innerHTML = '';
      Array.from(files).forEach(file => {
        const item = document.createElement('div');
        item.className = 'upload-file-item';
        item.textContent = `${file.name} (${(file.size / 1024).toFixed(0)} KB)`;
        preview.appendChild(item);
      });
    }
  }
}

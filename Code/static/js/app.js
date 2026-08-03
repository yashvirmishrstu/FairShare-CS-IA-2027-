/**
 * FairShare Client-Side Interactive Engine & Visual Analytics
 */

document.addEventListener('DOMContentLoaded', () => {
  initClientValidation();
  initBarcodeAndQRCodes();
  initFacilityScanner();
  initGuestLogin();
  initAuthTabs();
  initAdminAnalytics();
});

// Unified login page: switch between Member/Admin and Guest sign-in panels
function initAuthTabs() {
  const tabs = document.querySelectorAll('.auth-tab');
  if (!tabs.length) return;

  const activate = (tab) => {
    const target = tab.getAttribute('data-tab');
    tabs.forEach(t => {
      const active = t === tab;
      t.classList.toggle('active', active);
      t.setAttribute('aria-selected', active ? 'true' : 'false');
    });
    document.querySelectorAll('.auth-panel').forEach(panel => {
      panel.hidden = panel.getAttribute('data-panel') !== target;
    });
    // Focus the first field of the newly shown panel (skip on initial render so
    // the server-side autofocus / user's own focus is not stolen)
    if (!initAuthTabs._initialized) {
      initAuthTabs._initialized = true;
      return;
    }
    const firstInput = document.querySelector(`.auth-panel[data-panel="${target}"] input`);
    if (firstInput) firstInput.focus();
  };

  tabs.forEach(tab => {
    tab.addEventListener('click', () => activate(tab));
  });
}

// Client-side form validation
function initClientValidation() {
  const forms = document.querySelectorAll('form');
  forms.forEach(form => {
    form.addEventListener('submit', (e) => {
      const numberInputs = form.querySelectorAll('input[type="number"]');
      let valid = true;

      numberInputs.forEach(input => {
        const val = parseFloat(input.value);
        if (input.hasAttribute('data-non-negative') && val < 0) {
          alert('Validation Error: Value cannot be negative!');
          input.focus();
          valid = false;
        }
      });

      const password = form.querySelector('input[name="password"]');
      const confirm = form.querySelector('input[name="confirm_password"]');
      if (password && confirm && password.value !== confirm.value) {
        alert('Validation Error: Passwords do not match!');
        confirm.focus();
        valid = false;
      }

      if (!valid) {
        e.preventDefault();
      }
    });
  });
}

// Render all Barcode & QR elements (facility barcodes, redemption QR)
function initBarcodeAndQRCodes() {
  if (typeof JsBarcode === 'function') {
    document.querySelectorAll('[data-barcode]').forEach(elem => {
      const code = elem.getAttribute('data-barcode');
      if (!code) return;
      JsBarcode(elem, code, {
        format: "CODE128",
        lineColor: "#111827",
        width: parseInt(elem.getAttribute('data-width') || '2', 10),
        height: parseInt(elem.getAttribute('data-height') || '50', 10),
        displayValue: elem.getAttribute('data-display') !== 'false',
        margin: 4
      });
    });
  }

  if (typeof QRCode === 'function') {
    document.querySelectorAll('[data-qr]').forEach(elem => {
      const data = elem.getAttribute('data-qr');
      if (!data) return;
      const size = parseInt(elem.getAttribute('data-qr-width') || '128', 10);
      elem.innerHTML = '';
      new QRCode(elem, {
        text: data,
        width: size,
        height: size,
        colorDark: "#111827",
        colorLight: "#ffffff",
        correctLevel: QRCode.CorrectLevel.H
      });
    });
  }
}

// Facility Barcode Scanner interactions (member/scan page)
function initFacilityScanner() {
  const form = document.getElementById('scanner-form');
  const input = document.getElementById('scanner-input');
  if (!form) return;

  // Guard against rapid double-scans (twitchy scanners / fast double-clicks).
  // NOTE: the scan input must NOT be disabled — disabled controls are excluded
  // from form data, which would strip the scanned code before submission.
  form.addEventListener('submit', () => {
    form.dataset.submitting = '1';
    document.querySelectorAll('[data-demo-code]').forEach(b => { b.disabled = true; });
  });

  // Keep the scan input focused for rapid successive scans
  const card = document.getElementById('scanner-card');
  if (card) {
    card.addEventListener('click', (e) => {
      if (e.target.tagName !== 'INPUT' && e.target.tagName !== 'BUTTON' && input) {
        input.focus();
      }
    });
  }

  // Simulated scans (demo cards) — real USB scanners type into the input
  document.querySelectorAll('[data-demo-code]').forEach(btn => {
    btn.addEventListener('click', () => {
      playScanBeep(660, 0.1);
      submitFacilityScan(btn.getAttribute('data-demo-code'));
    });
  });

  const clearBtn = document.getElementById('clear-scanner');
  if (clearBtn) {
    clearBtn.addEventListener('click', () => { if (input) { input.value = ''; input.focus(); } });
  }

  initSessionTimer();
  initCameraScanner();
}

function submitFacilityScan(code) {
  const input = document.getElementById('scanner-input');
  const form = document.getElementById('scanner-form');
  if (!form || form.dataset.submitting === '1') return;
  form.dataset.submitting = '1';
  document.querySelectorAll('[data-demo-code]').forEach(b => { b.disabled = true; });
  if (input) input.value = code;
  form.requestSubmit();
  // Safety reset in case navigation stalls
  setTimeout(() => { form.dataset.submitting = '0'; }, 1500);
}

// Live elapsed timers for active facility sessions (one or many)
function initSessionTimer() {
  const timers = document.querySelectorAll('.session-timer[data-start]');
  if (!timers.length) return;

  const render = () => {
    timers.forEach(el => {
      const start = new Date((el.getAttribute('data-start') || '').replace(' ', 'T'));
      if (isNaN(start.getTime())) { el.textContent = '—'; return; }
      const total = Math.max(0, Math.floor((Date.now() - start.getTime()) / 1000));
      const h = Math.floor(total / 3600);
      const m = String(Math.floor((total % 3600) / 60)).padStart(2, '0');
      const s = String(total % 60).padStart(2, '0');
      el.textContent = h > 0 ? `${h}:${m}:${s}` : `${m}:${s}`;
    });
  };
  render();
  setInterval(render, 1000);
}

// Guest day-pass sign-in: scan the Guest Pass QR code or enter the code manually
function initGuestLogin() {
  const form = document.getElementById('guest-login-form');
  if (!form) return;

  const toggleBtn = document.getElementById('guest-camera-toggle');
  const viewport = document.getElementById('guest-camera-viewport');
  const toast = document.getElementById('guest-scan-toast');
  const labelOn = toggleBtn ? (toggleBtn.getAttribute('data-label-on') || 'Scan QR Code') : 'Scan QR Code';
  let scanner = null;

  const showToast = (msg) => {
    if (!toast) return;
    toast.textContent = msg;
    toast.hidden = false;
    clearTimeout(showToast._t);
    showToast._t = setTimeout(() => { toast.hidden = true; }, 4500);
  };

  if (toggleBtn && viewport) {
    toggleBtn.addEventListener('click', async () => {
      if (scanner) {
        try { await scanner.stop(); } catch (e) {}
        scanner = null;
        viewport.style.display = 'none';
        toggleBtn.textContent = labelOn;
        return;
      }

      if (typeof Html5Qrcode === 'undefined') {
        showToast('Camera scanning library could not be loaded. Enter your pass code manually.');
        return;
      }

      viewport.style.display = 'block';
      scanner = new Html5Qrcode('guest-camera-viewport');
      try {
        await scanner.start(
          { facingMode: 'environment' },
          { fps: 10, qrbox: { width: 220, height: 220 } },
          (decodedText) => {
            playScanBeep(660, 0.1);
            submitGuestCode(decodedText.trim().toUpperCase());
          },
          () => {}
        );
        toggleBtn.textContent = 'Stop Camera';
      } catch (err) {
        showToast('Camera is unavailable or permission was denied. Enter your pass code manually.');
        viewport.style.display = 'none';
        scanner = null;
        toggleBtn.textContent = labelOn;
      }
    });

    window.addEventListener('beforeunload', () => {
      if (scanner) scanner.stop().catch(() => {});
    });
  }

  function submitGuestCode(code) {
    const input = document.getElementById('guest-code-input');
    if (input) input.value = code;
    playScanBeep(660, 0.1);

    // If the form has other required fields (e.g. the Quick Check-In & Purchase
    // page), native validation would silently block submission — instead fill the
    // code, then focus the first empty required field so the user completes it.
    const emptyRequired = Array.from(form.querySelectorAll('[required]')).find(f => !f.value.trim());
    if (emptyRequired) {
      emptyRequired.focus();
      return;
    }
    form.requestSubmit();
  }
}

// Optional webcam QR/barcode scanning via html5-qrcode (graceful fallback)
function initCameraScanner() {
  const toggleBtn = document.getElementById('camera-toggle');
  const viewport = document.getElementById('camera-viewport');
  const toast = document.getElementById('scan-toast');
  if (!toggleBtn || !viewport) return;

  const labelOn = toggleBtn.getAttribute('data-label-on') || 'Use Camera';
  let scanner = null;

  const showToast = (msg) => {
    if (!toast) return;
    toast.textContent = msg;
    toast.hidden = false;
    clearTimeout(showToast._t);
    showToast._t = setTimeout(() => { toast.hidden = true; }, 4500);
  };

  toggleBtn.addEventListener('click', async () => {
    if (scanner) {
      try { await scanner.stop(); } catch (e) {}
      scanner = null;
      viewport.style.display = 'none';
      toggleBtn.textContent = labelOn;
      return;
    }

    if (typeof Html5Qrcode === 'undefined') {
      showToast('Camera scanning library could not be loaded. Use the scan field or facility cards instead.');
      return;
    }

    viewport.style.display = 'block';
    scanner = new Html5Qrcode('camera-viewport');
    try {
      await scanner.start(
        { facingMode: 'environment' },
        { fps: 10, qrbox: { width: 220, height: 220 } },
        (decodedText) => {
          playScanBeep(880, 0.12);
          submitFacilityScan(decodedText.trim().toUpperCase());
        },
        () => {}
      );
      toggleBtn.textContent = 'Stop Camera';
    } catch (err) {
      showToast('Camera is unavailable or permission was denied. Use the scan field or facility cards instead.');
      viewport.style.display = 'none';
      scanner = null;
      toggleBtn.textContent = labelOn;
    }
  });

  window.addEventListener('beforeunload', () => {
    if (scanner) scanner.stop().catch(() => {});
  });
}

// Short click beep to confirm a scan (single shared AudioContext)
let _beepCtx = null;
function playScanBeep(freq = 880, dur = 0.12) {
  try {
    _beepCtx = _beepCtx || new (window.AudioContext || window.webkitAudioContext)();
    const osc = _beepCtx.createOscillator();
    const gain = _beepCtx.createGain();
    osc.type = 'sine';
    osc.frequency.value = freq;
    gain.gain.setValueAtTime(0.07, _beepCtx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.0001, _beepCtx.currentTime + dur);
    osc.connect(gain);
    gain.connect(_beepCtx.destination);
    osc.start();
    osc.stop(_beepCtx.currentTime + dur);
  } catch (e) { /* audio unavailable */ }
}

// Fetch and render Admin Chart.js Visualizations
function initAdminAnalytics() {
  const peakChartElem = document.getElementById('peakHoursChart');
  const facilityChartElem = document.getElementById('facilityUsageChart');
  const rewardChartElem = document.getElementById('rewardDistChart');

  if (!peakChartElem && !facilityChartElem && !rewardChartElem) return;

  fetch('/admin/api/analytics')
    .then(res => res.json())
    .then(data => {
      // 1. Facility Usage Trends Chart
      if (facilityChartElem && data.facility_trends) {
        const labels = data.facility_trends.map(item => item.facility_name);
        const durations = data.facility_trends.map(item => item.total_duration || 0);

        new Chart(facilityChartElem, {
          type: 'bar',
          data: {
            labels: labels.length ? labels : ['Gym', 'Tennis', 'Dining', 'Pool'],
            datasets: [{
              label: 'Total Usage (Minutes)',
              data: durations.length ? durations : [120, 90, 240, 60],
              backgroundColor: 'rgba(169, 0, 14, 0.75)',
              borderColor: '#121212',
              borderWidth: 2,
              borderRadius: 0
            }]
          },
          options: {
            responsive: true,
            plugins: { legend: { labels: { color: '#1c1b1b', font: { family: 'Outfit', weight: 700 } } } },
            scales: {
              x: { ticks: { color: '#1c1b1b' }, grid: { color: 'rgba(18,18,18,0.15)' } },
              y: { ticks: { color: '#1c1b1b' }, grid: { color: 'rgba(18,18,18,0.15)' } }
            }
          }
        });
      }

      // 2. Peak Hours Distribution Chart
      if (peakChartElem && data.peak_hours) {
        const hours = data.peak_hours.map(item => `${item.hour}:00`);
        const counts = data.peak_hours.map(item => item.count);

        new Chart(peakChartElem, {
          type: 'line',
          data: {
            labels: hours.length ? hours : ['09:00', '12:00', '15:00', '18:00', '21:00'],
            datasets: [{
              label: 'Peak Check-Ins & Activity',
              data: counts.length ? counts : [5, 14, 8, 22, 11],
              borderColor: '#2850ce',
              backgroundColor: 'rgba(40, 80, 206, 0.15)',
              borderWidth: 3,
              fill: true,
              tension: 0
            }]
          },
          options: {
            responsive: true,
            plugins: { legend: { labels: { color: '#1c1b1b', font: { family: 'Outfit', weight: 700 } } } },
            scales: {
              x: { ticks: { color: '#1c1b1b' }, grid: { color: 'rgba(18,18,18,0.15)' } },
              y: { ticks: { color: '#1c1b1b' }, grid: { color: 'rgba(18,18,18,0.15)' } }
            }
          }
        });
      }

      // 3. Total Rewards Distributed Doughnut Chart
      if (rewardChartElem && data.reward_distribution) {
        const labels = data.reward_distribution.map(item => `${item.discount_percentage}% Discount Band`);
        const counts = data.reward_distribution.map(item => item.count);

        new Chart(rewardChartElem, {
          type: 'doughnut',
          data: {
            labels: labels.length ? labels : ['0% Band', '5% Band', '10% Band', '15% Band', '20% Band'],
            datasets: [{
              data: counts.length ? counts : [1, 2, 3, 1, 1],
              backgroundColor: ['#1c1b1b', '#2850ce', '#d2a600', '#755b00', '#a9000e'],
              borderColor: '#121212',
              borderWidth: 2
            }]
          },
          options: {
            responsive: true,
            plugins: { legend: { labels: { color: '#1c1b1b', font: { family: 'Outfit', weight: 700 } } } }
          }
        });
      }
    })
    .catch(err => console.error("Error loading analytics:", err));
}

/**
 * FairShare Client-Side Interactive Engine & Visual Analytics
 *
 * ============================================================================
 * IB HL CS: EVENT-DRIVEN & FUNCTIONAL JAVASCRIPT
 * ============================================================================
 * This file is the client-side counterpart to the Flask server. It turns
 * static HTML pages into an interactive application:
 *
 *  * DOM (Document Object Model) manipulation — JavaScript reads and
 *    modifies the page's element tree in response to user actions.
 *  * Event-driven programming — the code registers *event listeners*
 *    (click, submit, beforeunload) and reacts when those events fire.
 *  * Callbacks & closures — functions passed to addEventListener capture
 *    variables from their enclosing scope (a closure), e.g. the `scanner`
 *    state in initReceiptScanner.
 *  * Asynchronous programming — fetch() returns a Promise; .then() chains
 *    register callbacks that run when the network response arrives, so the
 *    page never blocks while waiting (non-blocking I/O).
 *  * Client-side validation — a first line of defence for instant feedback
 *    (the server remains the authoritative validator).
 *
 * All entry points are wired up once the DOM has finished loading
 * (DOMContentLoaded event) so elements exist before listeners attach.
 */

document.addEventListener('DOMContentLoaded', () => {
  initSessionPointsCounter();
  initPointsCelebration();
  initGeoDrift();
  initMobileNav();
  initClientValidation();
  initBarcodeAndQRCodes();
  initFacilityScanner();
  initReceiptScanner();
  initGuestLogin();
  initAuthTabs();
  initAdminAnalytics();
  initPrintIdCard();
});

// Mobile navigation hamburger toggle
// IB HL CS: responsive design — a conditional UI that adapts to screen size.
// The hamburger toggles a CSS class (`open`) that reveals/hides the nav on
// small screens; aria-expanded is updated for screen-reader accessibility.
function initMobileNav() {
  const toggle = document.getElementById('nav-toggle');
  const links = document.getElementById('nav-links');
  if (!toggle || !links) return;
  const icon = toggle.querySelector('.nav-toggle-icon');
  toggle.addEventListener('click', () => {
    const open = links.classList.toggle('open');
    if (icon) icon.textContent = open ? '✕' : '☰';
    toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
  });
}

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
// IB HL CS: this is the FIRST layer of a layered validation strategy
// (client -> server -> database constraints). It gives instant feedback
// before a network round-trip: number inputs tagged data-non-negative must
// not be negative, and password confirmation must match. querySelectorAll
// + forEach is a functional iteration over a NodeList. NOTE: client-side
// checks are cosmetic — the server re-validates everything (never trust
// the client).
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
// IB HL CS: data encoding & symbology — barcodes (CODE128, linear 1D) and
// QR codes (2D matrix with error correction level H) encode machine-readable
// identifiers. The server renders <svg>/<div> placeholders carrying a
// data-barcode / data-qr attribute; this function *declaratively* scans the
// DOM for those attributes and delegates rendering to the JsBarcode/QRCode
// libraries. This is a data-driven approach: adding a new element to any
// template automatically gets rendered without more JS.
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
// IB HL CS: state management & race-condition defence — the form dataset
// flag `submitting` is a *state variable* guarding against double-submits
// (rapid scanner triggers). Timers (setTimeout) reset the flag as a safety
// net in case navigation stalls. The scanner keeps focus for rapid
// successive scans (usability = HCI concept).
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
// IB HL CS: real-time processing with setInterval — a callback fires every
// 1000 ms and recomputes elapsed time from the server-provided start
// timestamp. Date parsing, integer division and modulo (Math.floor,
// % 3600, % 60) decompose seconds into hours:minutes:seconds — a classic
// base-60 (sexagesimal) conversion algorithm.
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

// Receipt QR Expense Scanner (member/expenses + guest/dashboard)
// Members & guests scan the QR printed at the end of a receipt to log the
// expense automatically. Codes look like RCPT-1A2B3C.
function initReceiptScanner() {
  const form = document.getElementById('receipt-scanner-form');
  const input = document.getElementById('receipt-code-input');
  if (!form) return;

  // Guard against rapid double-scans
  form.addEventListener('submit', () => {
    form.dataset.submitting = '1';
    document.querySelectorAll('[data-receipt-code]').forEach(b => { b.disabled = true; });
  });

  // Keep the scan input focused for rapid successive scans
  const card = document.getElementById('receipt-scanner-card');
  if (card) {
    card.addEventListener('click', (e) => {
      if (e.target.tagName !== 'INPUT' && e.target.tagName !== 'BUTTON' && input) {
        input.focus();
      }
    });
  }

  // Simulated scans (demo receipt cards)
  document.querySelectorAll('[data-receipt-code]').forEach(btn => {
    btn.addEventListener('click', () => {
      playScanBeep(660, 0.1);
      submitReceiptScan(btn.getAttribute('data-receipt-code'));
    });
  });

  const clearBtn = document.getElementById('receipt-clear-scanner');
  if (clearBtn) {
    clearBtn.addEventListener('click', () => { if (input) { input.value = ''; input.focus(); } });
  }

  // Optional webcam QR scanning (graceful fallback to manual entry)
  const toggleBtn = document.getElementById('receipt-camera-toggle');
  const viewport = document.getElementById('receipt-camera-viewport');
  const toast = document.getElementById('receipt-scan-toast');
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
      showToast('Camera scanning library could not be loaded. Enter the RCPT code manually.');
      return;
    }

    viewport.style.display = 'block';
    scanner = new Html5Qrcode('receipt-camera-viewport');
    try {
      await scanner.start(
        { facingMode: 'environment' },
        { fps: 10, qrbox: { width: 220, height: 220 } },
        (decodedText) => {
          playScanBeep(880, 0.12);
          submitReceiptScan(decodedText.trim().toUpperCase());
        },
        () => {}
      );
      toggleBtn.textContent = 'Stop Camera';
    } catch (err) {
      showToast('Camera is unavailable or permission was denied. Enter the RCPT code manually.');
      viewport.style.display = 'none';
      scanner = null;
      toggleBtn.textContent = labelOn;
    }
  });

  const stopScanner = () => { if (scanner) scanner.stop().catch(() => {}); };
  window.addEventListener('beforeunload', stopScanner);
  window.addEventListener('pagehide', stopScanner);
  window.addEventListener('pageshow', (e) => {
    if (e.persisted && scanner && viewport.style.display !== 'none') {
      scanner.start(
        { facingMode: 'environment' },
        { fps: 10, qrbox: { width: 220, height: 220 } },
        (decodedText) => {
          playScanBeep(880, 0.12);
          submitReceiptScan(decodedText.trim().toUpperCase());
        },
        () => {}
      ).catch(() => {});
    }
  });
}

function submitReceiptScan(code) {
  const input = document.getElementById('receipt-code-input');
  const form = document.getElementById('receipt-scanner-form');
  if (!form || form.dataset.submitting === '1') return;
  form.dataset.submitting = '1';
  document.querySelectorAll('[data-receipt-code]').forEach(b => { b.disabled = true; });
  if (input) input.value = code;
  form.requestSubmit();
  // Safety reset in case navigation stalls
  setTimeout(() => { form.dataset.submitting = '0'; }, 1500);
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

    const stopScanner = () => { if (scanner) scanner.stop().catch(() => {}); };
    window.addEventListener('beforeunload', stopScanner);
    window.addEventListener('pagehide', stopScanner);
    window.addEventListener('pageshow', (e) => {
      if (e.persisted && scanner && viewport.style.display !== 'none') {
        scanner.start(
          { facingMode: 'environment' },
          { fps: 10, qrbox: { width: 220, height: 220 } },
          (decodedText) => {
            playScanBeep(660, 0.1);
            submitGuestCode(decodedText.trim().toUpperCase());
          },
          () => {}
        ).catch(() => {});
      }
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

  const stopScanner = () => { if (scanner) scanner.stop().catch(() => {}); };
  window.addEventListener('beforeunload', stopScanner);
  window.addEventListener('pagehide', stopScanner);
  window.addEventListener('pageshow', (e) => {
    if (e.persisted && scanner && viewport.style.display !== 'none') {
      scanner.start(
        { facingMode: 'environment' },
        { fps: 10, qrbox: { width: 220, height: 220 } },
        (decodedText) => {
          playScanBeep(880, 0.12);
          submitFacilityScan(decodedText.trim().toUpperCase());
        },
        () => {}
      ).catch(() => {});
    }
  });
}

// Animated geometric background motifs — Bauhaus shapes drift in a gentle
// orbital pattern using sin/cos, matching the reference code.html design.
function initGeoDrift() {
  const shapes = document.querySelectorAll('.geo[data-geo-speed]');
  if (!shapes.length) return;

  shapes.forEach((shape) => {
    const speed = parseFloat(shape.getAttribute('data-geo-speed')) || 1.0;
    const baseSpeed = speed * 0.04;
    let pos = 0;
    const drift = () => {
      pos += baseSpeed;
      shape.style.transform =
        `translate(${Math.sin(pos) * 18}px, ${Math.cos(pos) * 18}px) rotate(${pos * 4}deg)`;
      requestAnimationFrame(drift);
    };
    requestAnimationFrame(drift);
  });
}

// Member ID Card print button — triggers the browser's print dialog.
// The @media print rules in styles.css collapse the page to just the
// ID ticket, so window.print() yields a clean single-page membership
// card (Success Criterion 7). Guarded in case the button is absent.
function initPrintIdCard() {
  const btn = document.getElementById('print-id-card');
  if (!btn) return;
  btn.addEventListener('click', () => window.print());
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
// IB HL CS: client-server data exchange + data visualisation. fetch() makes
// an asynchronous GET request to /admin/api/analytics (a REST-style JSON
// endpoint). The response Promise resolves to JSON, which is mapped into
// chart-ready arrays (.map — functional transformation) and rendered as
// bar / line / doughnut charts. This satisfies the analytics success
// criterion and demonstrates abstraction: raw SQL rows become meaningful
// visual summaries.
function initAdminAnalytics() {
  const peakChartElem = document.getElementById('peakHoursChart');
  const facilityChartElem = document.getElementById('facilityUsageChart');
  const rewardChartElem = document.getElementById('rewardDistChart');

  if (!peakChartElem && !facilityChartElem && !rewardChartElem) return;

  // Defer chart rendering until the Outfit typeface has finished loading.
  // Chart.js canvases snapshot the available fonts at draw-time, so if the
  // Google Font stylesheet is still in-flight the axes / ticks / tooltips
  // render with a system fallback instead of Outfit and can never recover.
  document.fonts.ready.then(() => {
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
            font: { family: 'Outfit' },
            responsive: true,
            plugins: { legend: { labels: { color: '#1c1b1b', font: { family: 'Outfit', weight: 700 } } } },
            scales: {
              x: { ticks: { color: '#1c1b1b', font: { family: 'Outfit', weight: 600 } }, grid: { color: 'rgba(18,18,18,0.15)' } },
              y: { ticks: { color: '#1c1b1b', font: { family: 'Outfit', weight: 600 } }, grid: { color: 'rgba(18,18,18,0.15)' } }
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
            font: { family: 'Outfit' },
            responsive: true,
            plugins: { legend: { labels: { color: '#1c1b1b', font: { family: 'Outfit', weight: 700 } } } },
            scales: {
              x: { ticks: { color: '#1c1b1b', font: { family: 'Outfit', weight: 600 } }, grid: { color: 'rgba(18,18,18,0.15)' } },
              y: { ticks: { color: '#1c1b1b', font: { family: 'Outfit', weight: 600 } }, grid: { color: 'rgba(18,18,18,0.15)' } }
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
            font: { family: 'Outfit' },
            responsive: true,plugins: { legend: { position: 'bottom', labels: { color: '#1c1b1b', font: { family: 'Outfit', weight: 700 } } } } }
        });
      }
      })
      .catch(err => console.error("Error loading analytics:", err));
  });
}

// Session Points Counter — accumulates points from flash messages across
// check-ins and check-outs during a facility scanning session.  Persists
// via sessionStorage so the total survives page reloads (each scan POST
// redirects back to the same page).  Auto-resets when leaving the scanner.
// IB HL CS: *persistent client-side state* — sessionStorage (a key-value
// store scoped to the browser tab) survives page reloads but not tab
// closes. Regex (regular expressions) extract the point values from flash
// message text — pattern matching / parsing a string, a core CS skill.
function initSessionPointsCounter() {
  const badge = document.getElementById('session-points-badge');
  const valueEl = document.getElementById('session-points-value');
  if (!badge || !valueEl) return;

  const KEY = 'fairshare-scanner-session-pts';

  // Detect points from any flash alert on this page and accumulate
  const alerts = document.querySelectorAll('.alert');
  let freshPoints = 0;
  alerts.forEach(alert => {
    const text = alert.textContent || '';
    const match = text.match(/\+?(\d+[\d,]*)\s*(?:pts|points|point)/i)
               || text.match(/(\d+[\d,]*)\s*(?:points? earned|pts earned)/i);
    if (!match) return;
    freshPoints += parseInt(match[1].replace(/[^0-9]/g, ''), 10) || 0;
  });

  // Read stored total, add new points, write back
  const stored = (() => { try { return parseInt(sessionStorage.getItem(KEY), 10) || 0; } catch(e) { return 0; } })();
  const total = stored + freshPoints;
  try { sessionStorage.setItem(KEY, total); } catch(e) {}

  // Show the badge and animate if points were just added
  if (total > 0) {
    badge.style.display = '';
    valueEl.textContent = total;
    if (freshPoints > 0) {
      badge.classList.remove('pulse');
      void badge.offsetWidth; // force reflow
      badge.classList.add('pulse');
    }
  }

  // Reset the session counter when the user navigates away from the scanner
  window.addEventListener('beforeunload', () => {
    try { sessionStorage.removeItem(KEY); } catch(e) {}
  });
}

// Points-logged celebration toast — triggered when a flash message
// indicates points were earned (check-in, purchase, referral, receipt scan).
// Matches the reference "Points Logged" design: bold red badge, scale-in,
// slight rotation, auto-dismiss.
function initPointsCelebration() {
  const alerts = document.querySelectorAll('.alert');
  if (!alerts.length) return;

  alerts.forEach(alert => {
    const text = alert.textContent || '';
    // Look for point-related keywords in flash messages
    const match = text.match(/\+?(\d+[\d,]*)\s*(?:pts|points|point)/i)
               || text.match(/(\d+[\d,]*)\s*(?:points? earned|pts earned)/i);
    if (!match) return;

    const points = parseInt(match[1].replace(/[^0-9]/g, ''), 10);
    if (!points || points <= 0) return;

    showPointsToast(points);
  });
}

function showPointsToast(points) {
  // Create backdrop
  const backdrop = document.createElement('div');
  backdrop.className = 'points-toast-backdrop';
  document.body.appendChild(backdrop);

  // Create confetti container with 8 Bauhaus particles
  const confetti = document.createElement('div');
  confetti.className = 'points-confetti';
  const shapes = ['confetti-circle', 'confetti-square', 'confetti-triangle'];
  const burstAngles = [
    { cx: -70, cy: -90, cr: 320 },
    { cx: 80, cy: -70, cr: -280 },
    { cx: -90, cy: -20, cr: 420 },
    { cx: 95, cy: 10, cr: -380 },
    { cx: -60, cy: 60, cr: 260 },
    { cx: 50, cy: 80, cr: -340 },
    { cx: -20, cy: -100, cr: 500 },
    { cx: 30, cy: 40, cr: -520 },
  ];
  for (let i = 0; i < 8; i++) {
    const p = document.createElement('div');
    p.className = `points-confetti-particle ${shapes[i % 3]}`;
    p.style.setProperty('--cx', `${burstAngles[i].cx}px`);
    p.style.setProperty('--cy', `${burstAngles[i].cy}px`);
    p.style.setProperty('--cr', `${burstAngles[i].cr}deg`);
    p.style.animationDelay = `${i * 0.04}s`;
    confetti.appendChild(p);
  }
  document.body.appendChild(confetti);

  // Create toast
  const toast = document.createElement('div');
  toast.className = 'points-toast';
  toast.innerHTML = `
    <div class="points-toast-inner">
      <div class="points-toast-value">+${points} FS</div>
      <div class="points-toast-label">Points Earned</div>
    </div>`;
  document.body.appendChild(toast);

  // Dismiss after 2.2s with fade-out
  const dismiss = () => {
    const inner = toast.querySelector('.points-toast-inner');
    if (inner) inner.classList.add('fade-out');
    if (backdrop) backdrop.classList.add('fade-out');
    if (confetti) confetti.remove();
    setTimeout(() => {
      if (toast.parentNode) toast.remove();
      if (backdrop.parentNode) backdrop.remove();
    }, 400);
  };

  setTimeout(dismiss, 2200);

  // Click anywhere to dismiss early
  const clickDismiss = () => { dismiss(); document.removeEventListener('click', clickDismiss); };
  setTimeout(() => document.addEventListener('click', clickDismiss), 100);
}

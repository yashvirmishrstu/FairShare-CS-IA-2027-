/**
 * FairShare Client-Side Interactive Engine & Visual Analytics
 */

document.addEventListener('DOMContentLoaded', () => {
  initClientValidation();
  initBarcodeAndQRCodes();
  initAdminAnalytics();
});

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

// Render Member Barcode & QR Redemption Code
function initBarcodeAndQRCodes() {
  const barcodeElem = document.getElementById('member-barcode');
  if (barcodeElem && typeof JsBarcode === 'function') {
    const code = barcodeElem.getAttribute('data-code');
    if (code) {
      JsBarcode('#member-barcode', code, {
        format: "CODE128",
        lineColor: "#111827",
        width: 2,
        height: 50,
        displayValue: true
      });
    }
  }

  const qrElem = document.getElementById('redemption-qr');
  if (qrElem && typeof QRCode === 'function') {
    const qrData = qrElem.getAttribute('data-qr');
    if (qrData) {
      qrElem.innerHTML = '';
      new QRCode(qrElem, {
        text: qrData,
        width: 128,
        height: 128,
        colorDark : "#111827",
        colorLight : "#ffffff",
        correctLevel : QRCode.CorrectLevel.H
      });
    }
  }
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
              backgroundColor: 'rgba(16, 185, 129, 0.7)',
              borderColor: '#10b981',
              borderWidth: 1.5,
              borderRadius: 6
            }]
          },
          options: {
            responsive: true,
            plugins: { legend: { labels: { color: '#9ca3af' } } },
            scales: {
              x: { ticks: { color: '#9ca3af' }, grid: { color: 'rgba(255,255,255,0.05)' } },
              y: { ticks: { color: '#9ca3af' }, grid: { color: 'rgba(255,255,255,0.05)' } }
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
              borderColor: '#3b82f6',
              backgroundColor: 'rgba(59, 130, 246, 0.15)',
              fill: true,
              tension: 0.35
            }]
          },
          options: {
            responsive: true,
            plugins: { legend: { labels: { color: '#9ca3af' } } },
            scales: {
              x: { ticks: { color: '#9ca3af' }, grid: { color: 'rgba(255,255,255,0.05)' } },
              y: { ticks: { color: '#9ca3af' }, grid: { color: 'rgba(255,255,255,0.05)' } }
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
              backgroundColor: ['#6b7280', '#3b82f6', '#8b5cf6', '#f59e0b', '#10b981'],
              borderWidth: 0
            }]
          },
          options: {
            responsive: true,
            plugins: { legend: { labels: { color: '#9ca3af' } } }
          }
        });
      }
    })
    .catch(err => console.error("Error loading analytics:", err));
}

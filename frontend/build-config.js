const fs = require('fs');
const path = require('path');

// Get backend URL from environment (Vercel will set this during build)
let BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:8000';
BACKEND_URL = BACKEND_URL.replace(/\/+$/, ''); // Remove trailing slashes

const WS_URL = BACKEND_URL.replace('http://', 'ws://').replace('https://', 'wss://') + '/ws/interview';

console.log('Build-time config injection: BACKEND_URL =', BACKEND_URL);

const indexPath = path.join(__dirname, 'index.html');
let html = fs.readFileSync(indexPath, 'utf8');

const configScript = `<script>
  (function() {
    window.__APP_CONFIG__ = {
      API_URL: "${BACKEND_URL}",
      WS_URL: "${WS_URL}"
    };
    console.log('Config loaded at build time:', window.__APP_CONFIG__);
  })();
</script>`;

// Inject before closing head tag
if (html.includes('</head>')) {
    html = html.replace('</head>', configScript + '\n</head>');
} else {
    // Fallback if no head tag
    html = configScript + '\n' + html;
}

fs.writeFileSync(indexPath, html);

console.log('Build-time config injection: Config injected successfully');

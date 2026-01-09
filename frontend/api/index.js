const express = require('express');
const path = require('path');
const fs = require('fs');

const app = express();

// Get backend URL from environment (Vercel will set this)
const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:8000';
const WS_URL = BACKEND_URL.replace('http://', 'ws://').replace('https://', 'wss://') + '/ws/interview';

// Get the frontend root directory (parent of api directory)
const frontendRoot = path.join(__dirname, '..');

// Serve static files (CSS, JS, etc.)
app.use(express.static(frontendRoot));

// Inject config and serve HTML for all routes
app.get('*', (req, res) => {
    // Skip API routes
    if (req.path.startsWith('/api/')) {
        return res.status(404).json({ error: 'Not found' });
    }
    
    // Serve index.html with injected config
    const indexPath = path.join(frontendRoot, 'index.html');
    let html = fs.readFileSync(indexPath, 'utf8');
    
    // Inject config script if not already present
    const configScript = `
    <script>
      window.__APP_CONFIG__ = {
        API_URL: "${BACKEND_URL}",
        WS_URL: "${WS_URL}"
      };
    </script>
    `;
    
    // Insert config script before closing </head> tag
    html = html.replace('</head>', configScript + '</head>');
    
    res.send(html);
});

module.exports = app;

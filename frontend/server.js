const express = require('express');
const path = require('path');
const fs = require('fs');

const app = express();
const PORT = process.env.PORT || 5174;

// Get backend URL from environment (Railway will set this)
const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:8000';
const WS_URL = BACKEND_URL.replace('http://', 'ws://').replace('https://', 'wss://') + '/ws/interview';

// Serve static files
app.use(express.static(__dirname));

// Inject config and serve HTML
app.get('/', (req, res) => {
    let html = fs.readFileSync(path.join(__dirname, 'index.html'), 'utf8');
    
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

app.listen(PORT, () => {
    console.log(`Frontend server running on port ${PORT}`);
    console.log(`Backend URL: ${BACKEND_URL}`);
    console.log(`WebSocket URL: ${WS_URL}`);
});
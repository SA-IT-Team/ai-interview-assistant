const express = require('express');
const path = require('path');
const fs = require('fs');

const app = express();

// Get backend URL from environment (Vercel will set this)
const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:8000';
const WS_URL = BACKEND_URL.replace('http://', 'ws://').replace('https://', 'wss://') + '/ws/interview';

// Get the frontend root directory (parent of api directory)
const frontendRoot = path.join(__dirname, '..');

// Helper to serve static files manually
function serveStaticFile(req, res, next) {
    if (req.path.startsWith('/api/')) {
        return next();
    }
    
    // Map common file extensions to MIME types
    const mimeTypes = {
        '.html': 'text/html',
        '.js': 'application/javascript',
        '.css': 'text/css',
        '.json': 'application/json',
        '.png': 'image/png',
        '.jpg': 'image/jpeg',
        '.gif': 'image/gif',
        '.svg': 'image/svg+xml',
        '.ico': 'image/x-icon'
    };
    
    const filePath = path.join(frontendRoot, req.path);
    const ext = path.extname(filePath).toLowerCase();
    
    // Check if file exists and serve it
    if (fs.existsSync(filePath) && fs.statSync(filePath).isFile()) {
        const content = fs.readFileSync(filePath);
        const contentType = mimeTypes[ext] || 'application/octet-stream';
        res.setHeader('Content-Type', contentType);
        return res.send(content);
    }
    
    next();
}

// Serve static files
app.use(serveStaticFile);

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

// Export as Vercel serverless function
module.exports = app;

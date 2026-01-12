const path = require('path');
const fs = require('fs');

// Get backend URL from environment (Vercel will set this)
// Note: Environment variable name must be exactly "BACKEND_URL" (not BACKEN_URL)
const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:8000';
const WS_URL = BACKEND_URL.replace('http://', 'ws://').replace('https://', 'wss://') + '/ws/interview';

// Log for debugging (will appear in Vercel function logs)
console.log('Serverless function: BACKEND_URL from env =', process.env.BACKEND_URL);
console.log('Serverless function: Using BACKEND_URL =', BACKEND_URL);

// Get the frontend root directory (parent of api directory)
const frontendRoot = path.join(__dirname, '..');

// Map common file extensions to MIME types
const mimeTypes = {
    '.html': 'text/html',
    '.js': 'application/javascript',
    '.css': 'text/css',
    '.json': 'application/json',
    '.png': 'image/png',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.gif': 'image/gif',
    '.svg': 'image/svg+xml',
    '.ico': 'image/x-icon',
    '.woff': 'font/woff',
    '.woff2': 'font/woff2',
    '.ttf': 'font/ttf'
};

// Vercel serverless function handler
module.exports = (req, res) => {
    // Skip API routes
    if (req.url.startsWith('/api/')) {
        res.statusCode = 404;
        res.setHeader('Content-Type', 'application/json');
        return res.end(JSON.stringify({ error: 'Not found' }));
    }
    
    // Get the file path
    let filePath = req.url === '/' ? 'index.html' : req.url.split('?')[0];
    filePath = path.join(frontendRoot, filePath);
    
    // Security: prevent directory traversal
    const normalizedPath = path.normalize(filePath);
    if (!normalizedPath.startsWith(frontendRoot)) {
        res.statusCode = 403;
        res.setHeader('Content-Type', 'text/plain');
        return res.end('Forbidden');
    }
    
    // Check if file exists
    if (fs.existsSync(filePath) && fs.statSync(filePath).isFile()) {
        const ext = path.extname(filePath).toLowerCase();
        const contentType = mimeTypes[ext] || 'application/octet-stream';
        const content = fs.readFileSync(filePath);
        
        res.statusCode = 200;
        res.setHeader('Content-Type', contentType);
        
        // If it's index.html, inject config
        if (filePath.endsWith('index.html')) {
            let html = content.toString('utf8');
            const configScript = `<script>
      (function() {
        window.__APP_CONFIG__ = {
          API_URL: "${BACKEND_URL}",
          WS_URL: "${WS_URL}"
        };
        console.log('Config loaded:', window.__APP_CONFIG__);
        console.log('Backend URL from env:', "${BACKEND_URL}");
      })();
    </script>`;
            // Always inject in head, before any other scripts
            if (html.includes('</head>')) {
                html = html.replace('</head>', configScript + '\n    </head>');
            } else {
                // If no head tag, inject at the very beginning
                html = configScript + '\n' + html;
            }
            return res.end(html);
        }
        
        return res.end(content);
    }
    
    // If file doesn't exist, serve index.html (for SPA routing)
    const indexPath = path.join(frontendRoot, 'index.html');
    if (fs.existsSync(indexPath)) {
        let html = fs.readFileSync(indexPath, 'utf8');
        const configScript = `<script>
      (function() {
        window.__APP_CONFIG__ = {
          API_URL: "${BACKEND_URL}",
          WS_URL: "${WS_URL}"
        };
        console.log('Config loaded:', window.__APP_CONFIG__);
        console.log('Backend URL from env:', "${BACKEND_URL}");
      })();
    </script>`;
        // Always inject in head, before any other scripts
        if (html.includes('</head>')) {
            html = html.replace('</head>', configScript + '\n    </head>');
        } else {
            // If no head tag, inject at the very beginning
            html = configScript + '\n' + html;
        }
        
        res.statusCode = 200;
        res.setHeader('Content-Type', 'text/html');
        return res.end(html);
    }
    
    // 404 if index.html doesn't exist
    res.statusCode = 404;
    res.setHeader('Content-Type', 'text/plain');
    res.end('Not found');
};

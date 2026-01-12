const path = require('path');
const fs = require('fs');

// Get backend URL from environment (Vercel will set this)
const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:8000';
const WS_URL = BACKEND_URL.replace('http://', 'ws://').replace('https://', 'wss://') + '/ws/interview';

// Get the frontend root directory (parent of api directory)
// In Vercel, __dirname points to the api directory, so we go up one level
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
    try {
        // Log request for debugging
        console.log('Request URL:', req.url);
        console.log('Frontend root:', frontendRoot);
        console.log('BACKEND_URL:', BACKEND_URL);
        
        // Skip API routes
        if (req.url.startsWith('/api/')) {
            res.statusCode = 404;
            res.setHeader('Content-Type', 'application/json');
            return res.end(JSON.stringify({ error: 'Not found' }));
        }
        
        // Get the file path
        let filePath = req.url === '/' ? 'index.html' : req.url.split('?')[0];
        // Remove leading slash for path.join
        if (filePath.startsWith('/')) {
            filePath = filePath.substring(1);
        }
        filePath = path.join(frontendRoot, filePath);
        
        // Security: prevent directory traversal
        const normalizedPath = path.normalize(filePath);
        const normalizedRoot = path.normalize(frontendRoot);
        if (!normalizedPath.startsWith(normalizedRoot)) {
            console.error('Path traversal attempt:', normalizedPath, 'not in', normalizedRoot);
            res.statusCode = 403;
            res.setHeader('Content-Type', 'text/plain');
            return res.end('Forbidden');
        }
        
        // Check if file exists
        if (fs.existsSync(filePath) && fs.statSync(filePath).isFile()) {
            const ext = path.extname(filePath).toLowerCase();
            const contentType = mimeTypes[ext] || 'application/octet-stream';
            
            let content;
            try {
                content = fs.readFileSync(filePath);
            } catch (readError) {
                console.error('Error reading file:', filePath, readError);
                res.statusCode = 500;
                res.setHeader('Content-Type', 'text/plain');
                return res.end('Error reading file');
            }
            
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
            let html;
            try {
                html = fs.readFileSync(indexPath, 'utf8');
            } catch (readError) {
                console.error('Error reading index.html:', readError);
                res.statusCode = 500;
                res.setHeader('Content-Type', 'text/plain');
                return res.end('Error reading index.html');
            }
            
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
        console.error('index.html not found at:', indexPath);
        res.statusCode = 404;
        res.setHeader('Content-Type', 'text/plain');
        res.end('Not found');
        
    } catch (error) {
        console.error('Serverless function error:', error);
        console.error('Stack:', error.stack);
        res.statusCode = 500;
        res.setHeader('Content-Type', 'application/json');
        res.end(JSON.stringify({ 
            error: 'Internal server error',
            message: error.message,
            stack: process.env.NODE_ENV === 'development' ? error.stack : undefined
        }));
    }
};

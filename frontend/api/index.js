const path = require('path');
const fs = require('fs');

// Get backend URL from environment
const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:8000';
const WS_URL = BACKEND_URL.replace('http://', 'ws://').replace('https://', 'wss://') + '/ws/interview';

// Get the frontend root directory
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
        console.log('=== Function invoked ===');
        console.log('Request URL:', req.url);
        console.log('Request method:', req.method);
        console.log('__dirname:', __dirname);
        console.log('Frontend root:', frontendRoot);
        console.log('BACKEND_URL:', BACKEND_URL);
        
        // Skip API routes
        if (req.url.startsWith('/api/')) {
            console.log('Skipping API route');
            res.statusCode = 404;
            res.setHeader('Content-Type', 'application/json');
            return res.end(JSON.stringify({ error: 'Not found' }));
        }
        
        // Get the file path
        let filePath = req.url === '/' ? 'index.html' : req.url.split('?')[0];
        // Remove leading slash
        if (filePath.startsWith('/')) {
            filePath = filePath.substring(1);
        }
        
        const fullPath = path.join(frontendRoot, filePath);
        console.log('Requested file path:', filePath);
        console.log('Full path:', fullPath);
        
        // Security: prevent directory traversal
        const normalizedPath = path.normalize(fullPath);
        const normalizedRoot = path.normalize(frontendRoot);
        console.log('Normalized path:', normalizedPath);
        console.log('Normalized root:', normalizedRoot);
        
        if (!normalizedPath.startsWith(normalizedRoot)) {
            console.error('Path traversal detected');
            res.statusCode = 403;
            res.setHeader('Content-Type', 'text/plain');
            return res.end('Forbidden');
        }
        
        // Check if file exists
        console.log('Checking if file exists:', fullPath);
        const fileExists = fs.existsSync(fullPath);
        console.log('File exists:', fileExists);
        
        if (fileExists) {
            const stats = fs.statSync(fullPath);
            console.log('Is file:', stats.isFile());
            
            if (stats.isFile()) {
                const ext = path.extname(fullPath).toLowerCase();
                const contentType = mimeTypes[ext] || 'application/octet-stream';
                
                console.log('Reading file:', fullPath);
                let content;
                try {
                    content = fs.readFileSync(fullPath);
                    console.log('File read successfully, size:', content.length);
                } catch (readError) {
                    console.error('Error reading file:', readError);
                    res.statusCode = 500;
                    res.setHeader('Content-Type', 'text/plain');
                    return res.end('Error reading file: ' + readError.message);
                }
                
                res.statusCode = 200;
                res.setHeader('Content-Type', contentType);
                
                // If it's index.html, inject config
                if (fullPath.endsWith('index.html')) {
                    console.log('Injecting config into index.html');
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
                    
                    if (html.includes('</head>')) {
                        html = html.replace('</head>', configScript + '\n    </head>');
                    } else {
                        html = configScript + '\n' + html;
                    }
                    console.log('Config injected, sending response');
                    return res.end(html);
                }
                
                console.log('Sending file content');
                return res.end(content);
            }
        }
        
        // If file doesn't exist, try to serve index.html (for SPA routing)
        const indexPath = path.join(frontendRoot, 'index.html');
        console.log('File not found, trying index.html at:', indexPath);
        const indexExists = fs.existsSync(indexPath);
        console.log('index.html exists:', indexExists);
        
        if (indexExists) {
            let html;
            try {
                html = fs.readFileSync(indexPath, 'utf8');
                console.log('index.html read successfully');
            } catch (readError) {
                console.error('Error reading index.html:', readError);
                res.statusCode = 500;
                res.setHeader('Content-Type', 'text/plain');
                return res.end('Error reading index.html: ' + readError.message);
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
            
            if (html.includes('</head>')) {
                html = html.replace('</head>', configScript + '\n    </head>');
            } else {
                html = configScript + '\n' + html;
            }
            
            res.statusCode = 200;
            res.setHeader('Content-Type', 'text/html');
            console.log('Sending index.html with config');
            return res.end(html);
        }
        
        // 404 if index.html doesn't exist
        console.error('index.html not found at:', indexPath);
        res.statusCode = 404;
        res.setHeader('Content-Type', 'text/plain');
        res.end('Not found');
        
    } catch (error) {
        console.error('=== FUNCTION ERROR ===');
        console.error('Error message:', error.message);
        console.error('Error stack:', error.stack);
        console.error('Error name:', error.name);
        console.error('=====================');
        
        res.statusCode = 500;
        res.setHeader('Content-Type', 'application/json');
        res.end(JSON.stringify({ 
            error: 'Internal server error',
            message: error.message,
            stack: error.stack
        }));
    }
};

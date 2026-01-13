const http = require('http');
const path = require('path');
const fs = require('fs');
const url = require('url');

// Get backend URL from environment
let BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:8000';
BACKEND_URL = BACKEND_URL.replace(/\/+$/, ''); // Remove trailing slashes
const WS_URL = BACKEND_URL.replace('http://', 'ws://').replace('https://', 'wss://') + '/ws/interview';

// MIME types
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

const server = http.createServer((req, res) => {
    const parsedUrl = url.parse(req.url, true);
    let filePath = parsedUrl.pathname === '/' ? 'index.html' : parsedUrl.pathname.split('?')[0];
    
    // Remove leading slash
    if (filePath.startsWith('/')) {
        filePath = filePath.substring(1);
    }
    
    const fullPath = path.join(__dirname, filePath);
    
    // Security: prevent directory traversal
    const normalizedPath = path.normalize(fullPath);
    const normalizedRoot = path.normalize(__dirname);
    
    if (!normalizedPath.startsWith(normalizedRoot)) {
        res.writeHead(403, { 'Content-Type': 'text/plain' });
        return res.end('Forbidden');
    }
    
    // Check if file exists
    if (fs.existsSync(fullPath)) {
        const stats = fs.statSync(fullPath);
        
        if (stats.isFile()) {
            const ext = path.extname(fullPath).toLowerCase();
            const contentType = mimeTypes[ext] || 'application/octet-stream';
            
            let content;
            try {
                content = fs.readFileSync(fullPath);
            } catch (readError) {
                res.writeHead(500, { 'Content-Type': 'text/plain' });
                return res.end('Error reading file: ' + readError.message);
            }
            
            // If it's index.html, inject config
            if (fullPath.endsWith('index.html')) {
                let html = content.toString('utf8');
                const configScript = `<script>
  (function() {
    window.__APP_CONFIG__ = {
      API_URL: "${BACKEND_URL}",
      WS_URL: "${WS_URL}"
    };
    console.log('Config loaded:', window.__APP_CONFIG__);
  })();
</script>`;
                
                if (html.includes('</head>')) {
                    html = html.replace('</head>', configScript + '\n</head>');
                } else {
                    html = configScript + '\n' + html;
                }
                
                res.writeHead(200, { 'Content-Type': 'text/html' });
                return res.end(html);
            }
            
            res.writeHead(200, { 'Content-Type': contentType });
            return res.end(content);
        }
    }
    
    // If file doesn't exist, try to serve index.html (for SPA routing)
    const indexPath = path.join(__dirname, 'index.html');
    if (fs.existsSync(indexPath)) {
        let html = fs.readFileSync(indexPath, 'utf8');
        const configScript = `<script>
  (function() {
    window.__APP_CONFIG__ = {
      API_URL: "${BACKEND_URL}",
      WS_URL: "${WS_URL}"
    };
    console.log('Config loaded:', window.__APP_CONFIG__);
  })();
</script>`;
        
        if (html.includes('</head>')) {
            html = html.replace('</head>', configScript + '\n</head>');
        } else {
            html = configScript + '\n' + html;
        }
        
        res.writeHead(200, { 'Content-Type': 'text/html' });
        return res.end(html);
    }
    
    // 404 if index.html doesn't exist
    res.writeHead(404, { 'Content-Type': 'text/plain' });
    res.end('Not found');
});

const PORT = process.env.PORT || 5174;
server.listen(PORT, () => {
    console.log(`Frontend server running on port ${PORT}`);
    console.log(`Backend URL: ${BACKEND_URL}`);
    console.log(`WebSocket URL: ${WS_URL}`);
});

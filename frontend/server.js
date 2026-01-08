const express = require('express');
const path = require('path');

const app = express();
const PORT = 5174;

// Serve current directory (frontend/) as static files
app.use(express.static(__dirname));

app.get('/', (req, res) => {
    res.sendFile(path.join(__dirname, 'index.html'));
});

app.listen(PORT, () => {
    console.log(`Frontend server running at http://localhost:${PORT}`);
});
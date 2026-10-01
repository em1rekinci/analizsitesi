const http = require('http');
const fs = require('fs');
const path = require('path');

const PORT = process.env.PORT || 3000;
const TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.css': 'text/css; charset=utf-8',
  '.webmanifest': 'application/manifest+json'
};

http.createServer((req, res) => {
  let urlPath = decodeURIComponent(req.url.split('?')[0]);
  if (urlPath === '/') urlPath = '/index.html';
  const file = path.join(__dirname, path.normalize(urlPath));
  if (!file.startsWith(__dirname)) { res.writeHead(403); return res.end(); }
  fs.readFile(file, (err, data) => {
    if (err) {
      return fs.readFile(path.join(__dirname, 'index.html'), (e, html) => {
        res.writeHead(e ? 404 : 200, { 'Content-Type': TYPES['.html'] });
        res.end(e ? 'Not found' : html);
      });
    }
    res.writeHead(200, { 'Content-Type': TYPES[path.extname(file)] || 'application/octet-stream' });
    res.end(data);
  });
}).listen(PORT, '0.0.0.0', () => console.log('Dükkan çalışıyor, port ' + PORT));

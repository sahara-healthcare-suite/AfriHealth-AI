const express = require('express');
const path = require('path');

const app = express();
const PORT = process.env.PORT || 3000;

// Parse JSON payloads for API requests
app.use(express.json({ limit: '10mb' }));

// CORS Header handling
app.use((req, res, next) => {
  res.header('Access-Control-Allow-Origin', '*');
  res.header('Access-Control-Allow-Headers', 'Origin, X-Requested-With, Content-Type, Accept, Authorization');
  if (req.method === 'OPTIONS') {
    res.header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE');
    return res.status(200).json({});
  }
  next();
});

// Secure Proxy Endpoint for Intron Voice API
// Allows using INTRON_API_KEY from Cloudflare Environment Variables / Secrets securely on server-side
app.post('/api/intron/transcribe', async (req, res) => {
  const apiKey = process.env.INTRON_API_KEY || req.headers.authorization;

  if (!apiKey) {
    return res.status(401).json({
      error: 'Missing Intron API key. Please configure INTRON_API_KEY in your Cloudflare Environment Variables or Secrets.'
    });
  }

  try {
    const authorization = apiKey.includes(' ') ? apiKey : ['Bearer', apiKey].join(' ');
    const response = await fetch('https://infer.voice.intron.io/v1/transcribe', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: authorization,
      },
      body: JSON.stringify(req.body)
    });

    const data = await response.json();
    return res.status(response.status).json(data);
  } catch (error) {
    console.error('Error proxying request to Intron API:', error);
    return res.status(500).json({ error: 'Failed to communicate with Intron Sahara v2.5 service.' });
  }
});

// Serve static web app assets from current directory
app.use(express.static(__dirname));

// Single Page Application route fallback
app.get('*', (req, res) => {
  res.sendFile(path.join(__dirname, 'index.html'));
});

app.listen(PORT, () => {
  console.log('================================================');
  console.log(`🚀 AfriHealth AI Server running on port ${PORT}`);
  console.log('================================================');
});

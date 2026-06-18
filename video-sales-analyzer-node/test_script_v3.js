const axios = require('axios');
const fs = require('fs');

async function test() {
  const fileId = '1sERIqqD5xx6J3LuTZg6KqaoZRgHFsq43';
  const downloadUrl = `https://drive.google.com/uc?export=download&id=${fileId}&confirm=no_virus_check`;
  const response = await axios.get(downloadUrl, { responseType: 'arraybuffer', headers: { 'Referer': 'https://drive.google.com/', 'User-Agent': 'Mozilla/5.0' } });
  const html = Buffer.from(response.data).toString('utf8');
  const confirmMatch = html.match(/name="confirm" value="([0-9A-Za-z_-]+)"/);
  
  if (confirmMatch) {
    const token = confirmMatch[1];
    console.log('Token found:', token);
    const finalUrl = `${downloadUrl}&confirm=${token}`;
    console.log('Final URL:', finalUrl);
    const confirmed = await axios.get(finalUrl, { headers: { 'Referer': 'https://drive.google.com/', 'User-Agent': 'Mozilla/5.0' } });
    console.log('Status:', confirmed.status);
  } else {
    console.log('Token not found');
  }
}
test();

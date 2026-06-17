const axios = require('axios');
const driveUrl = 'https://drive.google.com/file/d/1sERIqqD5xx6J3LuTZg6KqaoZRgHFsq43/view?usp=drive_link';
const fileId = '1sERIqqD5xx6J3LuTZg6KqaoZRgHFsq43';
const downloadUrl = `https://drive.google.com/uc?export=download&id=${fileId}&confirm=no_virus_check`;

console.log('Downloading from:', downloadUrl);

axios.get(downloadUrl, {
  responseType: 'arraybuffer',
  maxRedirects: 10,
  headers: { 'User-Agent': 'Mozilla/5.0' },
})
.then(response => {
  console.log('Status:', response.status);
  console.log('Content-Type:', response.headers['content-type']);
  console.log('Data size:', response.data.length);
})
.catch(error => {
  console.error('Error:', error.message);
});

const axios = require('axios');
const fileId = '1sERIqqD5xx6J3LuTZg6KqaoZRgHFsq43';
const downloadUrl = `https://drive.google.com/uc?export=download&id=${fileId}&confirm=no_virus_check`;

console.log('Fetching:', downloadUrl);

axios.get(downloadUrl, {
  headers: { 'User-Agent': 'Mozilla/5.0' },
})
.then(response => {
  const html = response.data;
  console.log('HTML preview:', html.substring(0, 200));
  const confirmMatch = html.match(/confirm=([0-9A-Za-z_-]+)/);
  if (confirmMatch) {
    console.log('Found confirm token:', confirmMatch[1]);
    const finalUrl = `${downloadUrl}&confirm=${confirmMatch[1]}`;
    console.log('Final URL:', finalUrl);
    return axios.get(finalUrl, { headers: { 'User-Agent': 'Mozilla/5.0' } });
  } else {
    console.log('No confirm token found.');
  }
})
.then(res => {
  if (res) console.log('Final response status:', res.status);
})
.catch(err => console.error('Error:', err.message));

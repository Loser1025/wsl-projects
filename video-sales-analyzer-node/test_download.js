const axios = require('axios');
const { CookieJar } = require('tough-cookie');

async function testDownload() {
    const jar = new CookieJar();
    const fileId = '1sERIqqD5xx6J3LuTZg6KqaoZRgHFsq43';
    
    // 検証スクリプト（test_script_v3.js）のロジック
    const downloadUrl = `https://drive.google.com/uc?export=download&id=${fileId}&confirm=no_virus_check`;
    
    // axios インスタンス設定
    const client = axios.create({
        maxRedirects: 10,
        headers: { 'User-Agent': 'Mozilla/5.0' }
    });

    console.log('Fetching initial URL...');
    const response = await client.get(downloadUrl, { 
        responseType: 'arraybuffer', 
        headers: { 'Referer': 'https://drive.google.com/', 'User-Agent': 'Mozilla/5.0' } 
    });
    
    const html = Buffer.from(response.data).toString('utf8');
    const confirmMatch = html.match(/name="confirm" value="([0-9A-Za-z_-]+)"/);
    
    if (confirmMatch) {
        const token = confirmMatch[1];
        console.log('Token found:', token);
        const finalUrl = `https://drive.google.com/uc?export=download&id=${fileId}&confirm=${token}`;
        console.log('Final URL:', finalUrl);
        
        const confirmed = await client.get(finalUrl, { 
            responseType: 'arraybuffer',
            headers: { 'Referer': 'https://drive.google.com/', 'User-Agent': 'Mozilla/5.0' } 
        });
        
        console.log('Final Status:', confirmed.status);
        console.log('Final Data Size:', Buffer.byteLength(confirmed.data));
    } else {
        console.log('Token not found. Size:', Buffer.byteLength(response.data));
    }
}
testDownload().catch(console.error);

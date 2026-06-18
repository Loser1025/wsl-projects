const axios = require('axios');
const fs = require('fs');

const ID = '1sERIqqD5xx6J3LuTZg6KqaoZRgHFsq43';
const TARGET_URL = `https://drive.google.com/uc?export=download&id=${ID}`;

async function testDownload() {
    try {
        console.log('Fetching initial page...');
        const response = await axios.get(TARGET_URL, {
            headers: {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
        });
        
        // HTMLから confirm と uuid を抽出
        const confirmMatch = response.data.match(/name="confirm" value="([^"]+)"/);
        const uuidMatch = response.data.match(/name="uuid" value="([^"]+)"/);
        const confirmToken = confirmMatch ? confirmMatch[1] : 't';
        const uuid = uuidMatch ? uuidMatch[1] : '';
        
        console.log(`Using confirm token: ${confirmToken}, uuid: ${uuid}`);

        // confirmトークンがもしtなら、ダウンロードURLを叩く際にuuidも必要
        // どうやら、この「警告」ページはダウンロードの初期ページではなく、警告が出た結果のページである可能性がある
        // 実際には、/uc?export=download&id=... を叩くと、まず警告ページが返される。
        // この警告ページのHTMLにある form action="https://drive.usercontent.google.com/download" を叩く必要がある。
        
        const formActionMatch = response.data.match(/action="([^"]+)"/);
        const formAction = formActionMatch ? formActionMatch[1] : 'https://drive.google.com/uc';
        
        console.log(`Using form action: ${formAction}`);
        
        // 必要なパラメータをすべて含める
        const downloadUrl = `${formAction}?export=download&confirm=${confirmToken}&id=${ID}&uuid=${uuid}`;
        
        console.log('Downloading file...');
        const fileResponse = await axios.get(downloadUrl, { 
            responseType: 'stream',
            headers: {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
        });
        
        const writer = fs.createWriteStream('test_output.bin');
        fileResponse.data.pipe(writer);

        writer.on('finish', () => {
            const stats = fs.statSync('test_output.bin');
            console.log(`Download finished! Size: ${stats.size} bytes`);
        });

    } catch (error) {
        console.error('Error during download:', error.message);
    }
}

testDownload();

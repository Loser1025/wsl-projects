const axios = require('axios');
const baseUrl = 'https://video-sales-analyzer-node-8a6tthmgx-loser1025s-projects.vercel.app';
const fileId = '1sERIqqD5xx6J3LuTZg6KqaoZRgHFsq43';

async function trigger() {
    try {
        console.log(`Triggering download for: ${fileId}`);
        const response = await axios.post(`${baseUrl}/api`, { fileId });
        console.log('Response status:', response.status);
    } catch (error) {
        console.error('Error:', error.message);
    }
}
trigger();

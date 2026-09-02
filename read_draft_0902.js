const fs = require('fs');
const path = require('path');

const draftDir = '/mnt/c/Users/andmiraina03/AppData/Local/CapCut/User Data/Projects/com.lveditor.draft/0902';
const files = fs.readdirSync(draftDir);
console.log("Files in 0902:", files);

const draftMetaPath = path.join(draftDir, 'draft_content.json');
if (fs.existsSync(draftMetaPath)) {
    const content = JSON.parse(fs.readFileSync(draftMetaPath, 'utf8'));
    console.log("Tracks count:", content.tracks ? content.tracks.length : 'no tracks');
    if (content.tracks) {
        content.tracks.forEach((t, i) => {
            console.log(`Track ${i} type: ${t.type}, segments: ${t.segments ? t.segments.length : 0}`);
        });
    }
} else {
    console.log("draft_content.json not found in 0902 directly, checking subdirs...");
}

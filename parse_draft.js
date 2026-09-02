const fs = require('fs');
const path = require('path');

const draftDir = '/mnt/c/Users/andmiraina03/AppData/Local/CapCut/User Data/Projects/com.lveditor.draft/0902';
const contentPath = path.join(draftDir, 'draft_content.json');
const raw = fs.readFileSync(contentPath, 'utf8');
const content = JSON.parse(raw);

console.log("Canvas:", content.canvas);
console.log("Tracks count:", content.tracks.length);
content.tracks.forEach((t, i) => {
    console.log(`\n[Track ${i}] type: ${t.type}, segments count: ${t.segments.length}`);
    t.segments.forEach((s, j) => {
        console.log(`  - Seg ${j}: id=${s.id}, material_id=${s.material_id}, target_timerange=${JSON.stringify(s.target_timerange)}`);
    });
});

if (content.materials) {
    console.log("\nMaterials summary:");
    Object.keys(content.materials).forEach(key => {
        const arr = content.materials[key];
        if (Array.isArray(arr)) {
            console.log(`  - ${key}: ${arr.length} items`);
            arr.forEach((m, idx) => {
                if (idx < 5) {
                    console.log(`    [${idx}] id=${m.id}, type=${m.type}, text=${m.content ? m.content.substring(0, 30) : 'N/A'}`);
                }
            });
        }
    });
}

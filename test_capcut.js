const { execSync } = require('child_process');
const fs = require('fs');

const draftPath = '/mnt/c/Users/andmiraina03/AppData/Local/CapCut/User Data/Projects/com.lveditor.draft';
const dirs = fs.readdirSync(draftPath);
console.log("Drafts found:", dirs);

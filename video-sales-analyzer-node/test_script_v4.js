const { execSync } = require('child_process');

try {
  console.log("Attempting to fetch logs...");
  const output = execSync('vercel logs video-sales-analyzer-node-8ayuyrivl-loser1025s-projects.vercel.app --since 5m', { encoding: 'utf-8' });
  console.log(output);
} catch (e) {
  console.log("Error:", e.stdout || e.stderr);
}

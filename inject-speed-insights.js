#!/usr/bin/env node

/**
 * Post-build script to inject Vercel Speed Insights into the generated HTML
 */

const fs = require('fs');
const path = require('path');

const htmlPath = path.join(__dirname, 'game', 'build', 'web', 'index.html');

// Speed Insights injection code
const speedInsightsCode = `
    <!-- Vercel Speed Insights -->
    <script type="module">
      import { injectSpeedInsights } from '/_vercel/speed-insights/script.js';
      injectSpeedInsights();
    </script>
`;

try {
  // Read the HTML file
  let html = fs.readFileSync(htmlPath, 'utf8');
  
  // Check if Speed Insights is already injected
  if (html.includes('speed-insights')) {
    console.log('✓ Speed Insights already present in index.html');
    process.exit(0);
  }
  
  // Inject the Speed Insights code before the closing </head> tag
  html = html.replace('</head>', `${speedInsightsCode}\n</head>`);
  
  // Write the modified HTML back
  fs.writeFileSync(htmlPath, html, 'utf8');
  
  console.log('✓ Successfully injected Vercel Speed Insights into index.html');
} catch (error) {
  console.error('Error injecting Speed Insights:', error.message);
  process.exit(1);
}

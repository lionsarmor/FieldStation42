const puppeteer = require('puppeteer');
const { spawn } = require('child_process');

(async () => {
  const browser = await puppeteer.launch({
    args: ['--no-sandbox', '--disable-setuid-sandbox'],
    defaultViewport: { width: 1280, height: 720 }
  });
  const page = await browser.newPage();

  // Use localhost to access the host machine port from the container with host network
  await page.goto('http://localhost:8080/', { waitUntil: 'networkidle2' });

  const ffmpeg = spawn('ffmpeg', [
    '-f', 'image2pipe',
    '-i', '-',
    '-vf', 'fps=10',
    '-c:v', 'libx264',
    '-preset', 'veryfast',
    '-g', '30',
    '-sc_threshold', '0',
    '-f', 'hls',
    '-hls_time', '2',
    '-hls_list_size', '3',
    '-hls_flags', 'delete_segments',
    '/app/output/stream.m3u8'
  ]);

  ffmpeg.stderr.on('data', data => console.log(`ffmpeg: ${data.toString()}`));
  ffmpeg.on('exit', code => console.log(`ffmpeg exited with code ${code}`));

  const captureFrame = async () => {
    const screenshotBuffer = await page.screenshot({ type: 'png' });
    ffmpeg.stdin.write(screenshotBuffer);
  };

  setInterval(captureFrame, 100);

  process.on('SIGINT', async () => {
    await browser.close();
    ffmpeg.stdin.end();
    process.exit();
  });
})();

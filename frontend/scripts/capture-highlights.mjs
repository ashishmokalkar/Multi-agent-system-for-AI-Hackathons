import { chromium } from '@playwright/test'
import { spawn, spawnSync } from 'node:child_process'
import { mkdir } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const project = resolve(here, '../..')
const output = resolve(project, 'artifacts/social_highlight_v3')
const temporary = resolve(output, 'capture-temp')
const framesOutput = resolve(output, 'representative_frames')
const baseURL = 'http://127.0.0.1:8765'
const exportSeconds = 14
await mkdir(temporary, { recursive: true })
await mkdir(framesOutput, { recursive: true })

async function health() {
  try {
    const response = await fetch(`${baseURL}/api/health`)
    return response.ok
  } catch {
    return false
  }
}

let server = null
if (!(await health())) {
  server = spawn('python3', ['-m', 'audio_competition_agents', '--mode', 'mock', 'serve', '--host', '127.0.0.1', '--port', '8765'], {
    cwd: project,
    env: { ...process.env, PYTHONPATH: resolve(project, 'src') },
    stdio: ['ignore', 'pipe', 'pipe'],
  })
  for (let attempt = 0; attempt < 100 && !(await health()); attempt += 1) {
    await new Promise((resolveWait) => setTimeout(resolveWait, 100))
  }
  if (!(await health())) throw new Error('control-room server did not become healthy')
}

const browser = await chromium.launch({ headless: true })
const captures = [
  { name: 'landscape', width: 1920, height: 1080, previewTime: 8.0 },
  { name: 'vertical', width: 1080, height: 1920, previewTime: 12.3 },
]
const representativeFrames = [
  { name: 'title', time: .3 },
  { name: 'orchestration', time: 2.3 },
  { name: 'verification', time: 5.5 },
  { name: 'revision', time: 8.0 },
  { name: 'outcome', time: 10.3 },
  { name: 'end', time: 12.3 },
]

try {
  for (const item of captures) {
    const context = await browser.newContext({
      viewport: { width: item.width, height: item.height },
      recordVideo: { dir: temporary, size: { width: item.width, height: item.height } },
      colorScheme: 'dark',
    })
    const page = await context.newPage()
    const video = page.video()
    await page.goto(`${baseURL}/highlight/${item.name}?autoplay=1`, { waitUntil: 'networkidle' })
    await page.waitForFunction(() => window.__HIGHLIGHT_READY__ === true)
    await page.waitForFunction(() => window.__HIGHLIGHT_COMPLETE__ === true, null, { timeout: 18_000 })
    await page.waitForTimeout(250)
    await context.close()

    const webm = resolve(temporary, `${item.name}.webm`)
    await video.saveAs(webm)
    const mp4 = resolve(output, `multi-agent-ai-hackathons-${item.name}.mp4`)
    const encoded = spawnSync('ffmpeg', [
      '-y', '-sseof', `-${exportSeconds}`, '-i', webm, '-an', '-t', `${exportSeconds}`, '-vf', 'fps=30,format=yuv420p',
      '-c:v', 'libx264', '-preset', 'medium', '-crf', '20', '-movflags', '+faststart', mp4,
    ], { stdio: 'inherit' })
    if (encoded.status !== 0) throw new Error(`ffmpeg failed for ${item.name}`)

    const previewContext = await browser.newContext({ viewport: { width: item.width, height: item.height }, colorScheme: 'dark' })
    const preview = await previewContext.newPage()
    for (const frame of representativeFrames) {
      await preview.goto(`${baseURL}/highlight/${item.name}?t=${frame.time}`, { waitUntil: 'networkidle' })
      await preview.waitForFunction(() => window.__HIGHLIGHT_READY__ === true)
      const path = resolve(framesOutput, `${item.name}-${frame.name}.png`)
      await preview.screenshot({ path })
      if (frame.time === item.previewTime) {
        await preview.screenshot({ path: resolve(output, `preview-${item.name}.png`) })
      }
    }
    await previewContext.close()
    console.log(`${item.name}: ${mp4}`)
  }
} finally {
  await browser.close()
  if (server) {
    server.kill('SIGTERM')
    await new Promise((resolveWait) => server.once('exit', resolveWait))
  }
}

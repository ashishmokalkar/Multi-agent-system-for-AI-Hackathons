import { expect, test, type Page } from '@playwright/test'

async function waitForHighlight(page: Page) {
  await page.waitForFunction(() => (window as unknown as { __HIGHLIGHT_READY__?: boolean }).__HIGHLIGHT_READY__ === true)
}

async function assertFrameFits(page: Page, width: number, height: number) {
  const geometry = await page.evaluate(() => {
    const visible = [...document.querySelectorAll<HTMLElement>('.scene h1, .scene h2, .scene p, .scene-heading, .orchestration-flow, .verification-grid, .outcome-facts')]
      .filter((element) => {
        const style = getComputedStyle(element)
        const rect = element.getBoundingClientRect()
        return style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0
      })
      .map((element) => {
        const rect = element.getBoundingClientRect()
        return { tag: element.tagName, left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom }
      })
    return {
      scrollWidth: document.documentElement.scrollWidth,
      scrollHeight: document.documentElement.scrollHeight,
      visible,
    }
  })
  expect(geometry.scrollWidth).toBeLessThanOrEqual(width)
  expect(geometry.scrollHeight).toBeLessThanOrEqual(height)
  for (const rect of geometry.visible) {
    expect(rect.left, `${rect.tag} left edge`).toBeGreaterThanOrEqual(0)
    expect(rect.right, `${rect.tag} right edge`).toBeLessThanOrEqual(width)
    expect(rect.top, `${rect.tag} top edge`).toBeGreaterThanOrEqual(0)
    expect(rect.bottom, `${rect.tag} bottom edge`).toBeLessThanOrEqual(height)
  }
}

test('1920x1080 control room renders replay, measured review, and presentation mode', async ({ page }) => {
  await page.goto('/')
  await expect(page).toHaveTitle(/Agent Control Room/)
  await expect(page.locator('.agent-card')).toHaveCount(7)
  await expect(page.locator('.mode-badge')).toContainText('MOCK')
  await expect(page.locator('.metric-scope')).toContainText('Awaiting actual CPU scoring')

  const size = await page.evaluate(() => ({
    innerWidth: window.innerWidth,
    scrollWidth: document.documentElement.scrollWidth,
    appWidth: document.querySelector('main')?.getBoundingClientRect().width,
  }))
  expect(size.innerWidth).toBe(1920)
  expect(size.scrollWidth).toBeLessThanOrEqual(1920)
  expect(size.appWidth).toBeGreaterThan(1800)

  await page.getByRole('button', { name: 'Recorded replay' }).click()
  await expect(page.locator('.mode-badge')).toContainText('RECORDED REPLAY · SOURCE MOCK')
  await page.getByRole('button', { name: /Pause/ }).click()
  const seek = page.getByLabel('Replay seek')
  await seek.evaluate((element: HTMLInputElement) => {
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!
    setter.call(element, '19')
    element.dispatchEvent(new Event('input', { bubbles: true }))
    element.dispatchEvent(new Event('change', { bubbles: true }))
  })
  await expect(page.locator('.activity-feed')).toContainText('Evaluator rejected the initial annotation')
  await expect(page.locator('.defect-visible')).toBeVisible()

  await seek.evaluate((element: HTMLInputElement) => {
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!
    setter.call(element, element.max)
    element.dispatchEvent(new Event('input', { bubbles: true }))
    element.dispatchEvent(new Event('change', { bubbles: true }))
  })
  await expect(page.locator('.metric-scope')).toContainText('toy scorer, not competition metrics')
  await expect(page.locator('.metric-row.combined')).not.toContainText('—')
  await expect(page.getByText('After revision', { exact: true })).toBeEnabled()

  await page.getByRole('button', { name: 'Presentation mode' }).click()
  await expect(page.locator('main')).toHaveClass(/presentation/)
  await expect(page.locator('.mode-picker')).toBeHidden()
})

test('landscape capture verifies every scene and the genuine correction', async ({ page }) => {
  await page.setViewportSize({ width: 1920, height: 1080 })
  const frames = [
    { time: .3, beat: 'title', name: 'title' },
    { time: 2.3, beat: 'orchestration', name: 'orchestration' },
    { time: 5.5, beat: 'verification', name: 'finding' },
    { time: 8.0, beat: 'verification', name: 'revision' },
    { time: 10.3, beat: 'outcome', name: 'outcome' },
    { time: 12.3, beat: 'end', name: 'end' },
  ]
  for (const frame of frames) {
    await page.goto(`/highlight/landscape?t=${frame.time}`)
    await waitForHighlight(page)
    await expect(page.locator('.highlight')).toHaveAttribute('data-beat', frame.beat)
    await expect(page.getByText('Recorded run · accelerated')).toBeVisible()
    await expect(page.getByText('Illustrative demo · mock execution')).toBeVisible()
    await expect(page.locator('button')).toHaveCount(0)
    await assertFrameFits(page, 1920, 1080)
    await page.screenshot({ path: `test-results/v3-landscape-${frame.name}.png` })
  }

  await page.goto('/highlight/landscape?t=0.3')
  await waitForHighlight(page)
  await expect(page.getByRole('heading', { name: 'Multi-Agent AI System for AI Hackathons' })).toBeVisible()
  await expect(page.locator('.title-content p')).toHaveText('Solving real-world ML problems with agentic swarms.')
  await expect(page.locator('.title-techline > span')).toHaveCount(3)

  await page.goto('/highlight/landscape?t=2.3')
  await waitForHighlight(page)
  await expect(page.getByRole('heading', { name: 'Coordinated agents. Structured experimentation.' })).toBeVisible()
  await expect(page.locator('.agent-node')).toHaveCount(5)
  await expect(page.getByText('Training', { exact: true })).toHaveCount(0)
  await expect(page.getByText('Ensemble', { exact: true })).toHaveCount(0)
  await expect(page.locator('.orchestration-readout')).toBeVisible()

  await page.goto('/highlight/landscape?t=5.5')
  await waitForHighlight(page)
  await expect(page.getByText('Boundary check failed')).toBeVisible()
  await expect(page.getByText('-0.050 s')).toBeVisible()
  await expect(page.getByText('+0.300 s')).toBeVisible()
  await expect(page.locator('.verification-steps > div')).toHaveCount(3)
  await expect(page.locator('.analysis-cursor')).toBeVisible()

  await page.goto('/highlight/landscape?t=8.0')
  await waitForHighlight(page)
  await expect(page.getByText('Revision verified')).toBeVisible()
  await expect(page.getByText('Accepted', { exact: true })).toBeVisible()

  await page.goto('/highlight/landscape?t=10.3')
  await waitForHighlight(page)
  await expect(page.getByRole('heading', { name: 'Workflow complete' })).toBeVisible()
  await expect(page.locator('.outcome-trace > div')).toHaveCount(3)

  await page.goto('/highlight/landscape?t=12.3')
  await waitForHighlight(page)
  await expect(page.locator('.scene-end p')).toHaveText('Explore the workflow on GitHub')
})

test('vertical capture is separately composed and safe at every transition', async ({ page }) => {
  await page.setViewportSize({ width: 1080, height: 1920 })
  const frames = [
    { time: .3, beat: 'title', name: 'title' },
    { time: 2.3, beat: 'orchestration', name: 'orchestration' },
    { time: 5.5, beat: 'verification', name: 'verification' },
    { time: 10.3, beat: 'outcome', name: 'outcome' },
    { time: 12.3, beat: 'end', name: 'end' },
  ]
  for (const frame of frames) {
    await page.goto(`/highlight/vertical?t=${frame.time}`)
    await waitForHighlight(page)
    const root = page.locator('.highlight')
    await expect(root).toHaveAttribute('data-layout', 'vertical')
    await expect(root).toHaveAttribute('data-beat', frame.beat)
    await assertFrameFits(page, 1080, 1920)
    await page.screenshot({ path: `test-results/v3-vertical-${frame.name}.png` })
  }

  await page.goto('/highlight/vertical?t=12.3')
  await waitForHighlight(page)
  const title = page.locator('.scene-end h1')
  const callout = page.locator('.scene-end p')
  const titleBox = await title.boundingBox()
  const calloutBox = await callout.boundingBox()
  expect(titleBox!.x).toBeGreaterThanOrEqual(76)
  expect(titleBox!.x + titleBox!.width).toBeLessThanOrEqual(1004)
  expect(calloutBox!.x).toBeGreaterThanOrEqual(76)
  expect(calloutBox!.x + calloutBox!.width).toBeLessThanOrEqual(1004)
})

test('interactive highlight exposes pause and replay only outside capture mode', async ({ page }) => {
  await page.setViewportSize({ width: 1920, height: 1080 })
  await page.goto('/highlight/landscape?autoplay=0')
  await waitForHighlight(page)
  await expect(page.getByRole('navigation', { name: 'Highlight replay controls' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Pause' })).toBeVisible()
  await page.getByRole('button', { name: 'Pause' }).click()
  await expect(page.getByRole('button', { name: 'Play', exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Replay' }).click()
  await expect(page.getByRole('button', { name: 'Pause' })).toBeVisible()
})

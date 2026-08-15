import fs from 'node:fs'
import path from 'node:path'
import { expect, test } from '@playwright/test'

const API = 'http://127.0.0.1:8000/api'
const OUT = 'test-results/export'

/**
 * The HTML export must be self-contained: opened from disk with no app running,
 * it should carry the solution, the deliberation trail, and its own styling.
 */
test('converged solution exports as a self-contained HTML document', async ({ page, request }) => {
  const rooms = (await (await request.get(`${API}/conversations`)).json()) as {
    id: string
    status: string
    title: string
  }[]
  const converged = rooms.find((r) => r.status === 'converged')
  test.skip(!converged, 'No converged room to export')
  fs.mkdirSync(OUT, { recursive: true })

  await page.goto('/')
  await page.getByRole('button', { name: converged!.title.slice(0, 30), exact: false }).first().click()
  await expect(page.getByText('Converged solution')).toBeVisible({ timeout: 15_000 })

  const download = await Promise.race([
    page.waitForEvent('download'),
    page.getByRole('button', { name: 'HTML' }).click().then(() => page.waitForEvent('download')),
  ])
  const file = path.join(OUT, 'converged-solution.html')
  await download.saveAs(file)

  const html = fs.readFileSync(file, 'utf-8')
  expect(html.startsWith('<!doctype html>')).toBe(true)
  expect(html).toContain('id="solution-print"')
  expect(html).toContain('How the room got here') // the deliberation trail
  expect(html).toContain('print-turn-gist')
  expect(html).toContain('.solution-md') // styles travelled with it
  expect(html).not.toContain('src="/src/') // no dev-server references
  expect(html.length).toBeGreaterThan(20_000)

  // Open the saved file directly — no app, no server — and check it renders.
  const offline = await page.context().newPage()
  await offline.goto(`file://${path.resolve(file).replace(/\\/g, '/')}`)
  const root = offline.locator('#solution-print')
  await expect(root).toBeVisible()
  const bg = await root.evaluate((el) => getComputedStyle(el).backgroundColor)
  expect(bg).toBe('rgb(255, 255, 255)')
  const turns = await offline.locator('.print-turns li').count()
  expect(turns).toBeGreaterThan(0)
  await offline.screenshot({ path: `${OUT}/html-standalone.png`, fullPage: false })

  const kb = Math.round(html.length / 1024)
  console.log(`[export] html ${kb}KB, ${turns} trail turns, renders offline`)
  await offline.close()
})

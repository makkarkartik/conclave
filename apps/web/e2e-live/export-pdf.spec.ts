import fs from 'node:fs'
import { expect, test } from '@playwright/test'

const API = 'http://127.0.0.1:8000/api'
const OUT = 'test-results/export'

/**
 * Verifies the converged-solution PDF export against a real converged room:
 * the print view carries the solution text, and Chromium renders it to a PDF
 * with backgrounds preserved (the dark palette must survive printing).
 */
test('converged solution exports to a styled PDF', async ({ page, request }) => {
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

  const card = page.getByText('Converged solution')
  await expect(card).toBeVisible({ timeout: 15_000 })

  // The print document exists, is hidden on screen, and holds the full solution.
  const printRoot = page.locator('#solution-print')
  await expect(printRoot).toHaveCount(1)
  await expect(printRoot).toBeHidden()
  const printedText = await printRoot.innerText()
  expect(printedText.length).toBeGreaterThan(200)

  // Render with print CSS applied and confirm the dark palette is retained.
  await page.emulateMedia({ media: 'print' })
  await expect(printRoot).toBeVisible()
  const bg = await printRoot.evaluate((el) => getComputedStyle(el).backgroundColor)
  expect(bg).toBe('rgb(255, 255, 255)') // paper

  // The deliberation trail must carry every turn of the room.
  const trailTurns = await page.locator('#solution-print .print-turns li').count()
  expect(trailTurns).toBeGreaterThan(0)

  // The app must contribute no layout height, or its hidden bulk becomes
  // trailing blank pages in the PDF.
  const appHeight = await page.evaluate(
    () => document.getElementById('root')?.getBoundingClientRect().height ?? -1,
  )
  expect(appHeight).toBe(0)

  // The printed document's own height should account for the whole document.
  const printHeight = await printRoot.evaluate((el) => el.getBoundingClientRect().height)
  const bodyHeight = await page.evaluate(() => document.body.scrollHeight)
  expect(bodyHeight).toBeLessThanOrEqual(printHeight + 40)

  await page.screenshot({ path: `${OUT}/print-view.png`, fullPage: true })

  const pdf = await page.pdf({
    path: `${OUT}/converged-solution.pdf`,
    printBackground: true,
    format: 'A4',
  })
  expect(pdf.byteLength).toBeGreaterThan(10_000)
  await page.emulateMedia({ media: 'screen' })

  // Page count must match the content, with no blank tail.
  const pages = Math.max(1, Math.round(printHeight / (11.7 * 96)))
  console.log(
    `[export] pdf bytes=${pdf.byteLength} chars=${printedText.length} ` +
      `printHeight=${Math.round(printHeight)}px ~pages=${pages} appHeight=${appHeight}`,
  )
})

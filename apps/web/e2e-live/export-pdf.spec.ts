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
  expect(bg).toBe('rgb(18, 20, 26)') // --color-ink
  await page.screenshot({ path: `${OUT}/print-view.png`, fullPage: true })

  const pdf = await page.pdf({
    path: `${OUT}/converged-solution.pdf`,
    printBackground: true,
    format: 'A4',
  })
  expect(pdf.byteLength).toBeGreaterThan(10_000)
  await page.emulateMedia({ media: 'screen' })

  console.log(`[export] pdf bytes=${pdf.byteLength} chars=${printedText.length}`)
})

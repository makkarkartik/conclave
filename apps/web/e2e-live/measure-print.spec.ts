import { test } from '@playwright/test'

const API = 'http://127.0.0.1:8000/api'

/** Diagnostic: compare screen vs print typography for the solution. */
test('measure print typography', async ({ page, request }) => {
  const rooms = (await (await request.get(`${API}/conversations`)).json()) as {
    id: string
    status: string
    title: string
  }[]
  const converged = rooms.find((r) => r.status === 'converged')
  test.skip(!converged, 'No converged room')

  await page.goto('/')
  await page.getByRole('button', { name: converged!.title.slice(0, 30), exact: false }).first().click()
  await page.getByText('Converged solution').waitFor()
  await page.getByRole('button', { name: /Converged solution/ }).click()

  const probe = () =>
    page.evaluate(() => {
      const onCard = document.querySelector('main .solution-md') as HTMLElement | null
      const onPrint = document.querySelector('#solution-print .solution-md') as HTMLElement | null
      const read = (el: HTMLElement | null) => {
        if (!el) return null
        const cs = getComputedStyle(el)
        const p = el.querySelector('p')
        const pcs = p ? getComputedStyle(p) : null
        // Rough characters-per-line for the measure.
        const width = el.getBoundingClientRect().width
        const fs = parseFloat(cs.fontSize)
        return {
          width: Math.round(width),
          fontSize: cs.fontSize,
          lineHeight: cs.lineHeight,
          family: cs.fontFamily.split(',')[0],
          pFamily: pcs?.fontFamily.split(',')[0] ?? '',
          charsPerLine: Math.round(width / (fs * 0.5)),
        }
      }
      const para = document.querySelector('#solution-print .solution-md > p') as HTMLElement | null
      const paraWidth = para ? para.getBoundingClientRect().width : 0
      const paraFs = para ? parseFloat(getComputedStyle(para).fontSize) : 1
      const h2 = document.querySelector('#solution-print .solution-md h2') as HTMLElement | null
      const table = document.querySelector('#solution-print .solution-md table') as HTMLElement | null
      return {
        card: read(onCard),
        print: read(onPrint),
        printH2: h2 ? getComputedStyle(h2).fontSize : null,
        printH2Family: h2 ? getComputedStyle(h2).fontFamily.split(',')[0] : null,
        paraWidth: Math.round(paraWidth),
        paraCharsPerLine: Math.round(paraWidth / (paraFs * 0.5)),
        tableWidth: table ? Math.round(table.getBoundingClientRect().width) : null,
        tableFont: table ? getComputedStyle(table).fontSize : null,
      }
    })

  console.log('SCREEN media:', JSON.stringify(await probe(), null, 1))
  await page.emulateMedia({ media: 'print' })
  await page.setViewportSize({ width: 794, height: 1123 }) // A4 at 96dpi
  console.log('PRINT media :', JSON.stringify(await probe(), null, 1))
  await page.emulateMedia({ media: 'screen' })
})

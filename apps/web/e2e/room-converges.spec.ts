import { expect, test } from '@playwright/test'
import {
  createFakeExpert,
  createRoomViaUI,
  deleteConversationByTopic,
  deleteExpert,
  suffix,
} from './helpers'

test('a room of fake experts deliberates to convergence in the browser', async ({
  page,
  request,
}) => {
  const sfx = suffix()
  const ada = await createFakeExpert(request, `Ada ${sfx}`)
  const bo = await createFakeExpert(request, `Bo ${sfx}`)
  const topic = `E2E fair rate limiter ${sfx}`

  try {
    await page.goto('/')
    await createRoomViaUI(page, topic, [ada.name, bo.name])

    await page.getByRole('button', { name: 'Start' }).click()

    // Turns stream in via polling: both experts take the floor
    await expect(page.getByText('stress-tested').first()).toBeVisible({ timeout: 30_000 })
    await expect(page.locator('main').getByText(`Ada ${sfx}`, { exact: true }).first()).toBeVisible()

    // Proposal writes show a doc-diff block on the bubble
    await expect(page.getByText('Created shared document', { exact: false }).first()).toBeVisible({
      timeout: 30_000,
    })

    // Convergence: header badge flips and the solution card appears
    await expect(page.getByText('Converged', { exact: true })).toBeVisible({ timeout: 60_000 })
    await expect(page.getByText('Converged solution')).toBeVisible()

    // Expand the card: markdown-rendered plan is present
    await page.getByRole('button', { name: /Converged solution/ }).click()
    await expect(page.getByText('Decision', { exact: false }).first()).toBeVisible()
  } finally {
    await deleteConversationByTopic(request, topic)
    await deleteExpert(request, ada.id)
    await deleteExpert(request, bo.id)
  }
})

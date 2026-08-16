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

    // Sealed start (the default): both experts draft blind, in parallel
    await expect(page.getByText('Drafted independently', { exact: false }).first()).toBeVisible({
      timeout: 30_000,
    })
    await expect(page.getByText('Sealed draft').first()).toBeVisible()

    // Then deliberation over the frozen union (protocol v3): experts take turns
    // proposing and voting; the Plan view is one click away
    await expect(page.getByRole('button', { name: 'Plan' })).toBeVisible()
    await expect(page.getByText('stress-tested', { exact: false }).first()).toBeVisible({
      timeout: 30_000,
    })
    await expect(page.locator('main').getByText(`Ada ${sfx}`, { exact: true }).first()).toBeVisible()

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

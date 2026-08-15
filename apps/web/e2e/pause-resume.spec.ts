import { expect, test } from '@playwright/test'
import {
  createFakeExpert,
  createRoomViaUI,
  deleteConversationByTopic,
  deleteExpert,
  suffix,
} from './helpers'

test('pause with direction interrupts the room; resume carries the direction to experts', async ({
  page,
  request,
}) => {
  const sfx = suffix()
  const ada = await createFakeExpert(request, `Ada ${sfx}`)
  const bo = await createFakeExpert(request, `Bo ${sfx}`)
  const topic = `E2E pause flow ${sfx}`

  try {
    await page.goto('/')
    await createRoomViaUI(page, topic, [ada.name, bo.name])

    await page.getByRole('button', { name: 'Start' }).click()

    // Pause immediately — long before the 3-lap convergence floor can be reached
    await page.getByRole('button', { name: 'Pause to direct' }).click()
    await page
      .getByPlaceholder(/Focus on abuse resistance/)
      .fill('Converge now on the current plan.')
    await page.getByRole('button', { name: 'Pause with direction' }).click()

    // Paused: the header offers Resume and the runner stops claiming this room
    await expect(page.getByRole('button', { name: 'Resume' })).toBeVisible({ timeout: 15_000 })

    // Resume: the direction reaches the experts' prompts (fake model echoes it)
    await page.getByRole('button', { name: 'Resume' }).click()
    await expect(
      page.locator('main').getByText("Following the chair's direction").first(),
    ).toBeVisible({ timeout: 30_000 })

    // And the room still converges
    await expect(page.getByText('Converged', { exact: true })).toBeVisible({ timeout: 60_000 })
  } finally {
    await deleteConversationByTopic(request, topic)
    await deleteExpert(request, ada.id)
    await deleteExpert(request, bo.id)
  }
})

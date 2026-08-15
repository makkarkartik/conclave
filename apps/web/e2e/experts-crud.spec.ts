import { expect, test } from '@playwright/test'
import { suffix } from './helpers'

test('create, edit, and delete an expert through the UI', async ({ page }) => {
  const name = `Smoke ${suffix()}`
  await page.goto('/')

  // Create
  await page.getByTitle('Add configured expert').click()
  await page.getByLabel('Name').fill(name)
  await page.getByLabel('Model').fill('gpt-4.1')
  await page.getByLabel(/^API key/).fill('sk-e2e-1234567890')
  await page.getByRole('button', { name: 'Save expert' }).click()

  const row = page.locator('aside .group', { hasText: name })
  await expect(row).toBeVisible()
  await expect(row).toContainText('openai · gpt-4.1')

  // Edit: masked key hint shown, rename persists
  await row.getByTitle('Edit connector').first().click()
  await expect(page.getByText(/Leave API key blank to keep the current key/)).toBeVisible()
  await expect(page.getByText(/sk-…7890/)).toBeVisible()
  await page.getByLabel('Name').fill(`${name} v2`)
  await page.getByRole('button', { name: 'Save changes' }).click()

  const renamed = page.locator('aside .group', { hasText: `${name} v2` })
  await expect(renamed).toBeVisible()

  // Delete
  await renamed.hover()
  await renamed.getByTitle('Delete').click()
  await expect(renamed).toHaveCount(0)
})

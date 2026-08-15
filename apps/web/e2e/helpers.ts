import { expect, type APIRequestContext, type Page } from '@playwright/test'

export const API = 'http://127.0.0.1:8000/api'

export function suffix(): string {
  return Math.random().toString(36).slice(2, 8)
}

export async function createFakeExpert(request: APIRequestContext, name: string) {
  const res = await request.post(`${API}/experts`, {
    data: { name, persona: '', provider: 'fake', model: 'fake', api_key: 'fake-key' },
  })
  expect(res.ok()).toBeTruthy()
  return (await res.json()) as { id: string; name: string }
}

export async function deleteExpert(request: APIRequestContext, id: string) {
  await request.delete(`${API}/experts/${id}`)
}

export async function deleteConversationByTopic(request: APIRequestContext, topic: string) {
  const res = await request.get(`${API}/conversations`)
  if (!res.ok()) return
  const rows = (await res.json()) as { id: string; topic: string }[]
  for (const row of rows.filter((r) => r.topic === topic)) {
    await request.delete(`${API}/conversations/${row.id}`)
  }
}

/** Create a room through the real UI: New conversation → topic → seat experts → Create. */
export async function createRoomViaUI(page: Page, topic: string, expertNames: string[]) {
  await page.getByRole('button', { name: 'New conversation' }).click()
  await page.getByLabel('Topic').fill(topic)
  for (const name of expertNames) {
    await page.locator('label', { hasText: name }).getByRole('checkbox').check()
  }
  await page.getByRole('button', { name: 'Create' }).click()
  await expect(page.getByRole('heading', { name: topic })).toBeVisible()
}

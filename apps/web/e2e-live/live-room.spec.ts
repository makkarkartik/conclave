import fs from 'node:fs'
import { expect, test, type Page } from '@playwright/test'

const KEY = process.env.LIVE_API_KEY ?? ''
const PROVIDER = (process.env.LIVE_PROVIDER ?? 'anthropic') as 'anthropic' | 'openai' | 'google'
const API = 'http://127.0.0.1:8000/api'

const DEFAULT_MODELS: Record<string, [string, string]> = {
  anthropic: ['claude-opus-5', 'claude-sonnet-5'],
  openai: ['gpt-4.1', 'gpt-4.1'],
  google: ['gemini-2.5-pro', 'gemini-2.5-flash'],
}
const MODEL_A = process.env.LIVE_MODEL_A ?? DEFAULT_MODELS[PROVIDER][0]
const MODEL_B = process.env.LIVE_MODEL_B ?? DEFAULT_MODELS[PROVIDER][1]

const TOPIC =
  process.env.LIVE_TOPIC ??
  "Design the auth and tenant-isolation rollout for Conclave's 100-user canary: what ships, in what order, and what is explicitly deferred?"

const SHOTS_DIR = 'test-results/live-shots'
const WATCH_MS = 12 * 60_000
const SHOT_EVERY_MS = 20_000

const EXPERTS = [
  {
    name: 'Pragmatist',
    model: MODEL_A,
    persona:
      'Pragmatic staff engineer. Optimizes for shipping the canary safely and fast; allergic to speculative infrastructure.',
  },
  {
    name: 'Skeptic',
    model: MODEL_B,
    persona:
      'Security-minded reviewer. Hunts abuse vectors, tenant-isolation gaps, and failure modes; demands concrete mitigations.',
  },
]

async function addExpertViaUI(
  page: Page,
  e: { name: string; model: string; persona: string },
) {
  await page.getByTitle('Add configured expert').click()
  await page.getByLabel('Name').fill(e.name)
  await page.getByLabel(/^Persona/).fill(e.persona)
  await page.getByLabel('Model').fill(e.model)
  await page.getByLabel(/^API key/).fill(KEY)
  await page.getByLabel('Provider').selectOption(PROVIDER)
  await page.getByRole('button', { name: 'Save expert' }).click()
  await expect(page.locator('aside .group', { hasText: e.name })).toBeVisible()
}

test('live: real models deliberate a real problem through the UI', async ({ page, request }) => {
  // Two modes: LIVE_API_KEY creates fresh experts via the UI; without it we use
  // experts already stored in the app (BYOK keys already supplied), preferring a
  // cross-provider pair.
  let seatNames: string[]
  if (KEY) {
    seatNames = EXPERTS.map((e) => e.name)
  } else {
    const res = await request.get(`${API}/experts`)
    const existing = (await res.json()) as { name: string; provider: string }[]
    test.skip(existing.length < 2, 'No LIVE_API_KEY and fewer than 2 stored experts')
    const envPick = [process.env.LIVE_EXPERT_A, process.env.LIVE_EXPERT_B].filter(Boolean) as string[]
    if (envPick.length === 2) {
      seatNames = envPick
    } else {
      const first = existing[0]
      const other = existing.find((e) => e.provider !== first.provider) ?? existing[1]
      seatNames = [first.name, other.name]
    }
  }
  fs.mkdirSync(SHOTS_DIR, { recursive: true })

  await page.goto('/')

  // Seat the experts — created via the modal if we hold a key, otherwise reused
  if (KEY) {
    for (const e of EXPERTS) await addExpertViaUI(page, e)
  }
  for (const name of seatNames) {
    await expect(page.locator('aside .group', { hasText: name })).toBeVisible()
  }

  // Create the room with the topic
  await page.getByRole('button', { name: 'New conversation' }).click()
  await page.getByLabel('Topic').fill(TOPIC)
  for (const name of seatNames) {
    await page.locator('label', { hasText: name }).getByRole('checkbox').check()
  }
  await page.getByRole('button', { name: 'Create' }).click()
  await expect(page.getByRole('heading', { name: TOPIC })).toBeVisible()
  await page.screenshot({ path: `${SHOTS_DIR}/00-room-created.png` })

  // Start the deliberation
  await page.getByRole('button', { name: 'Start' }).click()

  const converged = page.getByText('Converged', { exact: true })
  const start = Date.now()
  let shot = 1
  while (Date.now() - start < WATCH_MS) {
    if (await converged.isVisible().catch(() => false)) break
    await page.waitForTimeout(SHOT_EVERY_MS)
    await page.screenshot({
      path: `${SHOTS_DIR}/${String(shot).padStart(2, '0')}-t${Math.round((Date.now() - start) / 1000)}s.png`,
      fullPage: false,
    })
    shot += 1
  }

  const didConverge = await converged.isVisible().catch(() => false)
  if (didConverge) {
    await expect(page.getByText('Converged solution')).toBeVisible()
    await page.getByRole('button', { name: /Converged solution/ }).click()
    await page.waitForTimeout(600)
    await page.screenshot({ path: `${SHOTS_DIR}/99-converged-solution.png`, fullPage: true })
  } else {
    // Still deliberating at the watch cap: pause it politely and capture final state
    const pauseBtn = page.getByRole('button', { name: 'Pause to direct' })
    if (await pauseBtn.isVisible().catch(() => false)) {
      await pauseBtn.click()
      await page.getByRole('button', { name: 'Pause only' }).click()
    }
    await page.screenshot({ path: `${SHOTS_DIR}/99-paused-at-cap.png`, fullPage: true })
  }

  const bubbles = await page.locator('main .rounded-2xl.border').count()
  console.log(
    `[live] experts=${seatNames.join(' vs ')} converged=${didConverge} visible_messages≈${bubbles}`,
  )
  // The room is deliberately left in place for inspection.
})

export type Expert = {
  id: string
  name: string
  persona: string
  provider: string
  model: string
  accent: string
  api_key_masked: string
  key_source: 'own' | 'provider' | 'none'
  created_at: string
}

export type ProviderKey = {
  provider: string
  key_hint: string
  expert_count: number
  updated_at: string
}

export type Message = {
  id: string
  expert_id: string | null
  expert_name: string
  provider: string
  model: string
  lap: number
  thought: string
  content: string
  gist: string
  action: string
  agree: boolean
  chips: string[]
  citations: Citation[]
  doc_diff?: string
  created_at: string
}

export type Citation = {
  url: string
  title: string
}

export type Attachment = {
  id: string
  filename: string
  extracted_chars: number
  extraction_method: string
  created_at: string
}

export type Conversation = {
  id: string
  title: string
  topic: string
  user_direction: string
  chair_ids: string[]
  status: string
  shared_proposal: string
  converged_solution: string
  rolling_summary: string
  lap: number
  chair_index: number
  doc_rev: number
  web_search: boolean
  created_at: string
  updated_at: string
  messages: Message[]
  attachments: Attachment[]
  shared_doc: string
  speaking_expert_id: string | null
}

export type ConversationUpdates = {
  status: string
  lap: number
  chair_index: number
  doc_rev: number
  speaking_expert_id: string | null
  messages: Message[]
}

const BASE = '/api'

/** FastAPI errors come back as {"detail": "..."} — surface the message, not the JSON. */
async function errorMessage(res: Response): Promise<string> {
  const text = await res.text()
  try {
    const parsed = JSON.parse(text)
    if (typeof parsed?.detail === 'string') return parsed.detail
  } catch {
    /* not JSON — fall through to the raw body */
  }
  return text || res.statusText
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, init)
  if (!res.ok) throw new Error(await errorMessage(res))
  return res.json()
}

export const api = {
  health: () => req<{ ok: boolean }>('/health'),
  listExperts: () => req<Expert[]>('/experts'),
  createExpert: (body: Record<string, string>) =>
    req<Expert>('/experts', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  updateExpert: (id: string, body: Record<string, string>) =>
    req<Expert>(`/experts/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  deleteExpert: (id: string) => req<{ ok: boolean }>(`/experts/${id}`, { method: 'DELETE' }),
  testExpert: (id: string) => req<{ ok: boolean; reply: string }>(`/experts/${id}/test`, { method: 'POST' }),
  listProviderKeys: () => req<ProviderKey[]>('/provider-keys'),
  putProviderKey: (provider: string, api_key: string) =>
    req<ProviderKey>(`/provider-keys/${provider}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ api_key }),
    }),
  listConversations: () => req<Conversation[]>('/conversations'),
  getConversation: (id: string) => req<Conversation>(`/conversations/${id}`),
  getUpdates: (id: string, after?: string) =>
    req<ConversationUpdates>(
      `/conversations/${id}/updates${after ? `?after=${encodeURIComponent(after)}` : ''}`,
    ),
  createConversation: (body: { topic: string; chair_ids: string[]; title?: string }) =>
    req<Conversation>('/conversations', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  updateConversation: (id: string, body: Record<string, unknown>) =>
    req<Conversation>(`/conversations/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  deleteConversation: (id: string) =>
    req<{ ok: boolean }>(`/conversations/${id}`, { method: 'DELETE' }),
  start: (id: string) => req<Conversation>(`/conversations/${id}/start`, { method: 'POST' }),
  ask: (id: string, question: string, reopen = false) =>
    req<Conversation>(`/conversations/${id}/ask`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, reopen }),
    }),
  pause: (id: string, direction = '') =>
    req<Conversation>(`/conversations/${id}/pause`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ direction }),
    }),
  resume: (id: string, direction = '') =>
    req<Conversation>(`/conversations/${id}/resume`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ direction }),
    }),
  uploadFile: async (id: string, file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    const res = await fetch(`${BASE}/conversations/${id}/files`, { method: 'POST', body: fd })
    if (!res.ok) throw new Error(await errorMessage(res))
    return res.json() as Promise<{
      id: string
      filename: string
      extracted_chars: number
      extraction_method: string
    }>
  },
  deleteAttachment: (id: string, attachmentId: string) =>
    req<{ ok: boolean }>(`/conversations/${id}/files/${attachmentId}`, { method: 'DELETE' }),
  getSharedDoc: (id: string) =>
    req<{ content: string; blame: string; ops_log: string }>(`/conversations/${id}/shared-doc`),
  putSharedDoc: (id: string, content: string) =>
    req<{ content: string }>(`/conversations/${id}/shared-doc`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content }),
    }),
}

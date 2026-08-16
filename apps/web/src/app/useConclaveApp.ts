import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, type Conversation, type Expert, type Message } from '../shared/lib/api'

const POLL_MS = 2000

export function useConclaveApp() {
  const [experts, setExperts] = useState<Expert[]>([])
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [activeId, setActiveId] = useState<string | null>(null)
  const [active, setActive] = useState<Conversation | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [thinkingId, setThinkingId] = useState<string | null>(null)
  const [speakingId, setSpeakingId] = useState<string | null>(null)
  const [showExpertModal, setShowExpertModal] = useState(false)
  const [editingExpert, setEditingExpert] = useState<Expert | null>(null)
  const [showNewRoom, setShowNewRoom] = useState(false)
  const [showDoc, setShowDoc] = useState(false)
  const [showPause, setShowPause] = useState(false)
  const [direction, setDirection] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [attaching, setAttaching] = useState<string | null>(null)

  const refreshLists = useCallback(async () => {
    const [e, c] = await Promise.all([api.listExperts(), api.listConversations()])
    setExperts(e)
    setConversations(c)
  }, [])

  // Poll cursors: last message seen, and the status/doc revision the UI reflects.
  const lastMsgId = useRef<string | null>(null)
  const statusRef = useRef<string>('')
  const docRevRef = useRef<number>(0)

  const loadConversation = useCallback(async (id: string) => {
    const c = await api.getConversation(id)
    setActive(c)
    setActiveId(c.id)
    setMessages(c.messages)
    setSpeakingId(c.speaking_expert_id)
    setDirection(c.user_direction || '')
    lastMsgId.current = c.messages.length ? c.messages[c.messages.length - 1].id : null
    statusRef.current = c.status
    docRevRef.current = c.doc_rev
  }, [])

  useEffect(() => {
    refreshLists().catch((e) => setError(String(e)))
  }, [refreshLists])

  useEffect(() => {
    if (!activeId) return
    let stopped = false
    let inFlight = false

    const tick = async () => {
      if (stopped || inFlight) return
      inFlight = true
      try {
        const u = await api.getUpdates(activeId, lastMsgId.current ?? undefined)
        if (stopped) return
        if (u.messages.length) {
          lastMsgId.current = u.messages[u.messages.length - 1].id
          setMessages((prev) => {
            const seen = new Set(prev.map((m) => m.id))
            const fresh = u.messages.filter((m) => !seen.has(m.id))
            return fresh.length ? [...prev, ...fresh] : prev
          })
        }
        setSpeakingId(u.speaking_expert_id)
        setThinkingId(u.status === 'running' ? u.speaking_expert_id : null)
        const statusChanged = u.status !== statusRef.current
        const docChanged = u.doc_rev !== docRevRef.current
        if (statusChanged || docChanged) {
          statusRef.current = u.status
          docRevRef.current = u.doc_rev
          await loadConversation(activeId)
          if (statusChanged) await refreshLists()
        }
      } catch {
        // Transient poll failures are expected (deploys, sleeping laptop); next tick retries.
      } finally {
        inFlight = false
      }
    }

    tick()
    const timer = setInterval(tick, POLL_MS)
    return () => {
      stopped = true
      clearInterval(timer)
    }
  }, [activeId, loadConversation, refreshLists])

  const expertMap = useMemo(() => Object.fromEntries(experts.map((e) => [e.id, e])), [experts])
  const roomExperts = (active?.chair_ids || []).map((id) => expertMap[id]).filter(Boolean) as Expert[]

  async function onStart() {
    if (!activeId) return
    setError(null)
    try {
      setActive(await api.start(activeId))
      await refreshLists()
    } catch (e) {
      setError(String(e))
    }
  }

  async function onPause(withDirection: boolean) {
    if (!activeId) return
    try {
      setActive(await api.pause(activeId, withDirection ? direction : ''))
      setShowPause(false)
      await refreshLists()
    } catch (e) {
      setError(String(e))
    }
  }

  async function onResume() {
    if (!activeId) return
    try {
      setActive(await api.resume(activeId, direction))
      setShowPause(false)
      await refreshLists()
    } catch (e) {
      setError(String(e))
    }
  }

  async function onDeleteExpert(id: string) {
    await api.deleteExpert(id)
    await refreshLists()
  }

  function openAddExpert() {
    setEditingExpert(null)
    setShowExpertModal(true)
  }

  function openEditExpert(expert: Expert) {
    setEditingExpert(expert)
    setShowExpertModal(true)
  }

  function closeExpertModal() {
    setShowExpertModal(false)
    setEditingExpert(null)
  }

  async function onRenameConversation(id: string, title: string) {
    setError(null)
    try {
      const updated = await api.updateConversation(id, { title })
      setConversations((prev) => prev.map((c) => (c.id === id ? { ...c, title: updated.title } : c)))
      if (activeId === id) {
        setActive((prev) => (prev ? { ...prev, title: updated.title } : prev))
      }
    } catch (e) {
      setError(String(e))
      throw e
    }
  }

  async function onDeleteConversation(id: string) {
    setError(null)
    try {
      await api.deleteConversation(id)
      setConversations((prev) => prev.filter((c) => c.id !== id))
      if (activeId === id) {
        setActiveId(null)
        setActive(null)
        setMessages([])
        setSpeakingId(null)
        setThinkingId(null)
      }
    } catch (e) {
      setError(String(e))
      throw e
    }
  }

  async function onAttach(file: File) {
    if (!activeId || attaching) return
    setError(null)
    // Scanned PDFs are OCRed before the upload returns — that can take a while,
    // so show the file as pending rather than leaving the UI silent.
    setAttaching(file.name)
    try {
      await api.uploadFile(activeId, file)
      await loadConversation(activeId)
    } catch (e) {
      // Unreadable, duplicate, or unsupported files are rejected server-side.
      setError(String(e).replace(/^Error:\s*/, ''))
    } finally {
      setAttaching(null)
    }
  }

  async function onAsk(question: string, reopen = false) {
    if (!activeId) return
    setError(null)
    try {
      setActive(await api.ask(activeId, question, reopen))
      await refreshLists()
    } catch (e) {
      setError(String(e).replace(/^Error:\s*/, ''))
      throw e
    }
  }

  async function onToggleWebSearch() {
    if (!activeId || !active) return
    setError(null)
    const next = !active.web_search
    try {
      setActive(await api.updateConversation(activeId, { web_search: next }))
    } catch (e) {
      const message = String(e).replace(/^Error:\s*/, '')
      // Enabling search on a room holding documents needs explicit acknowledgement.
      if (next && message.includes('Confirm to proceed') && window.confirm(message)) {
        try {
          setActive(
            await api.updateConversation(activeId, { web_search: true, confirm_egress: true }),
          )
          return
        } catch (inner) {
          setError(String(inner).replace(/^Error:\s*/, ''))
          return
        }
      }
      setError(message)
    }
  }

  async function onRemoveAttachment(attachmentId: string) {
    if (!activeId) return
    setError(null)
    try {
      await api.deleteAttachment(activeId, attachmentId)
      await loadConversation(activeId)
    } catch (e) {
      setError(String(e).replace(/^Error:\s*/, ''))
    }
  }

  async function onSaveDoc(content: string) {
    if (!activeId) return
    await api.putSharedDoc(activeId, content)
    await loadConversation(activeId)
  }

  return {
    experts,
    conversations,
    activeId,
    active,
    messages,
    thinkingId,
    speakingId,
    showExpertModal,
    editingExpert,
    showNewRoom,
    showDoc,
    showPause,
    direction,
    error,
    attaching,
    expertMap,
    roomExperts,
    setShowExpertModal,
    setShowNewRoom,
    setShowDoc,
    setShowPause,
    setDirection,
    setError,
    refreshLists,
    loadConversation,
    onStart,
    onPause,
    onResume,
    onDeleteExpert,
    openAddExpert,
    openEditExpert,
    closeExpertModal,
    onRenameConversation,
    onDeleteConversation,
    onAttach,
    onRemoveAttachment,
    onToggleWebSearch,
    onAsk,
    onSaveDoc,
  }
}

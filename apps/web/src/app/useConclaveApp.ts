import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  api,
  subscribeConversation,
  type Conversation,
  type Expert,
  type Message,
} from '../shared/lib/api'

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

  const refreshLists = useCallback(async () => {
    const [e, c] = await Promise.all([api.listExperts(), api.listConversations()])
    setExperts(e)
    setConversations(c)
  }, [])

  const loadConversation = useCallback(async (id: string) => {
    const c = await api.getConversation(id)
    setActive(c)
    setActiveId(c.id)
    setMessages(c.messages)
    setSpeakingId(c.speaking_expert_id)
    setDirection(c.user_direction || '')
  }, [])

  useEffect(() => {
    refreshLists().catch((e) => setError(String(e)))
  }, [refreshLists])

  useEffect(() => {
    if (!activeId) return
    return subscribeConversation(activeId, {
      floor: (d) => {
        const data = d as { expert_id: string }
        setSpeakingId(data.expert_id)
        setThinkingId(null)
      },
      thinking: (d) => {
        const data = d as { expert_id: string }
        setThinkingId(data.expert_id)
      },
      act: (d) => {
        const msg = d as Message
        setMessages((prev) => (prev.some((m) => m.id === msg.id) ? prev : [...prev, msg]))
        setThinkingId(null)
      },
      converged: async () => {
        if (activeId) await loadConversation(activeId)
        await refreshLists()
      },
      paused: async () => {
        if (activeId) await loadConversation(activeId)
      },
      doc_updated: (d) => {
        const data = d as { content: string }
        setActive((prev) => (prev ? { ...prev, shared_doc: data.content } : prev))
      },
      status: async () => {
        if (activeId) await loadConversation(activeId)
      },
      error: (d) => setError(String((d as { message?: string }).message || d)),
    })
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
    if (!activeId) return
    await api.uploadFile(activeId, file)
    await loadConversation(activeId)
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
    onSaveDoc,
  }
}

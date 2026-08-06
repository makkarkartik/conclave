import { ExpertList } from '../experts/ExpertList'
import { ConversationList } from '../conversations/ConversationList'
import type { Conversation, Expert } from '../../shared/lib/api'

export function Sidebar({
  experts,
  conversations,
  activeId,
  onAddExpert,
  onEditExpert,
  onDeleteExpert,
  onSelectConversation,
  onNewConversation,
  onRenameConversation,
  onDeleteConversation,
}: {
  experts: Expert[]
  conversations: Conversation[]
  activeId: string | null
  onAddExpert: () => void
  onEditExpert: (expert: Expert) => void
  onDeleteExpert: (id: string) => void
  onSelectConversation: (id: string) => void
  onNewConversation: () => void
  onRenameConversation: (id: string, title: string) => Promise<void>
  onDeleteConversation: (id: string) => Promise<void>
}) {
  return (
    <aside className="flex w-[280px] shrink-0 flex-col border-r border-[var(--color-line)] bg-[rgba(18,20,26,0.9)]">
      <div className="flex items-center gap-2 px-5 py-5">
        <div className="flex h-8 w-8 items-center justify-center rounded-full bg-[var(--color-sky)] font-[family-name:var(--font-display)] text-sm font-bold text-[#12141a]">
          C
        </div>
        <div>
          <div className="font-[family-name:var(--font-display)] text-base font-semibold">Conclave</div>
          <div className="text-[11px] text-[var(--color-think)]">Multi-expert clarity</div>
        </div>
      </div>
      <ExpertList
        experts={experts}
        onAdd={onAddExpert}
        onEdit={onEditExpert}
        onDelete={onDeleteExpert}
      />
      <ConversationList
        conversations={conversations}
        activeId={activeId}
        onSelect={onSelectConversation}
        onNew={onNewConversation}
        onRename={onRenameConversation}
        onDelete={onDeleteConversation}
      />
    </aside>
  )
}

import { X } from 'lucide-react'
import { useConclaveApp } from './app/useConclaveApp'
import { Sidebar } from './features/shell/Sidebar'
import { EmptyState } from './features/shell/EmptyState'
import { ExpertModal } from './features/experts/ExpertModal'
import { NewRoomModal } from './features/conversations/NewRoomModal'
import { RoomHeader } from './features/conversations/RoomHeader'
import { PauseModal } from './features/conversations/PauseModal'
import { Thread } from './features/thread/Thread'
import { SolutionCard } from './features/thread/SolutionCard'
import { FollowUp } from './features/thread/FollowUp'
import { DecisionLog } from './features/thread/DecisionLog'
import { DocDrawer } from './features/files/DocDrawer'

export default function App() {
  const app = useConclaveApp()

  return (
    <div className="flex h-full overflow-hidden">
      <Sidebar
        experts={app.experts}
        conversations={app.conversations}
        activeId={app.activeId}
        onAddExpert={app.openAddExpert}
        onEditExpert={app.openEditExpert}
        onDeleteExpert={app.onDeleteExpert}
        onSelectConversation={app.loadConversation}
        onNewConversation={() => app.setShowNewRoom(true)}
        onRenameConversation={app.onRenameConversation}
        onDeleteConversation={app.onDeleteConversation}
      />

      <main className="flex min-w-0 flex-1 flex-col">
        {!app.active ? (
          <EmptyState onNew={() => app.setShowNewRoom(true)} />
        ) : (
          <>
            <RoomHeader
              active={app.active}
              roomExperts={app.roomExperts}
              speakingId={app.speakingId}
              expertMap={app.expertMap}
              onAttach={app.onAttach}
              attaching={app.attaching}
              onRemoveAttachment={app.onRemoveAttachment}
              onToggleWebSearch={app.onToggleWebSearch}
              onOpenDoc={() => app.openDoc('doc')}
              onOpenPlan={() => app.openDoc('plan')}
              onOpenLog={() => app.setShowLog(true)}
              onPause={() => app.setShowPause(true)}
              onStartOrResume={
                ['paused', 'safety_pause', 'error_pause'].includes(app.active.status)
                  ? app.onResume
                  : app.onStart
              }
            />
            <Thread
              messages={app.messages}
              expertMap={app.expertMap}
              speakingId={app.speakingId}
              thinkingId={app.thinkingId}
              running={app.active.status === 'running'}
            />
            <SolutionCard
              active={app.active}
              roomExperts={app.roomExperts}
              messages={app.messages}
            />
            <FollowUp active={app.active} onAsk={app.onAsk} />
          </>
        )}
      </main>

      {app.error && (
        <div className="fixed right-4 bottom-4 max-w-sm rounded-xl border border-[var(--color-coral)]/40 bg-[#1c1f2a] px-4 py-3 text-sm text-[var(--color-coral)] shadow-xl">
          <div className="flex justify-between gap-3">
            <span className="break-all">{app.error}</span>
            <button type="button" onClick={() => app.setError(null)}>
              <X size={14} />
            </button>
          </div>
        </div>
      )}

      {app.showExpertModal && (
        <ExpertModal
          expert={app.editingExpert}
          onClose={app.closeExpertModal}
          onSaved={async () => {
            app.closeExpertModal()
            await app.refreshLists()
            if (app.activeId) await app.loadConversation(app.activeId)
          }}
        />
      )}
      {app.showNewRoom && (
        <NewRoomModal
          experts={app.experts}
          onClose={() => app.setShowNewRoom(false)}
          onCreated={async (id) => {
            app.setShowNewRoom(false)
            await app.refreshLists()
            await app.loadConversation(id)
          }}
        />
      )}
      {app.showLog && app.active && (
        <DecisionLog
          messages={app.messages}
          roomExperts={app.roomExperts}
          expertMap={app.expertMap}
          onClose={() => app.setShowLog(false)}
        />
      )}
      {app.showDoc && app.active && (
        <DocDrawer
          conversationId={app.active.id}
          content={app.active.shared_doc}
          fallback={app.active.converged_solution || app.active.shared_proposal}
          docRev={app.active.doc_rev}
          experts={app.experts}
          seatNames={app.roomExperts.map((e) => e.name)}
          planPhase={app.active.plan_phase}
          messageCount={app.messages.length}
          initialTab={app.docTab}
          editable={!['running', 'drafting'].includes(app.active.status)}
          onClose={() => app.setShowDoc(false)}
          onSave={app.onSaveDoc}
        />
      )}
      {app.showPause && (
        <PauseModal
          direction={app.direction}
          onDirectionChange={app.setDirection}
          onClose={() => app.setShowPause(false)}
          onPauseOnly={() => app.onPause(false)}
          onPauseWithDirection={() => app.onPause(true)}
        />
      )}
    </div>
  )
}

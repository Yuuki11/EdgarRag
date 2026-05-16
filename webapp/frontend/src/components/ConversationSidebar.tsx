// Per-user conversation list with create, rename, select, and delete actions.

import type { ConversationSummary } from "../api";

type Props = {
  conversations: ConversationSummary[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  onRename: (id: string, currentTitle: string) => void;
  onDelete: (id: string) => void;
};

export default function ConversationSidebar({
  conversations,
  selectedId,
  onSelect,
  onNew,
  onRename,
  onDelete,
}: Props) {
  return (
    <section className="conversation-pane">
      <div className="conversation-head">
        <span>Chats</span>
        <button type="button" onClick={onNew} title="New chat">+</button>
      </div>
      <div className="conversation-list">
        {conversations.map((c) => (
          <button
            type="button"
            key={c.id}
            className={c.id === selectedId ? "conversation selected" : "conversation"}
            onClick={() => onSelect(c.id)}
          >
            <span>{c.title}</span>
            <span className="conversation-actions">
              <i
                role="button"
                tabIndex={0}
                title="Rename"
                onClick={(e) => {
                  e.stopPropagation();
                  onRename(c.id, c.title);
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter") onRename(c.id, c.title);
                }}
              >
                Rename
              </i>
              <i
                role="button"
                tabIndex={0}
                title="Delete"
                onClick={(e) => {
                  e.stopPropagation();
                  onDelete(c.id);
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter") onDelete(c.id);
                }}
              >
                Delete
              </i>
            </span>
          </button>
        ))}
        {conversations.length === 0 && <div className="conversation-empty">No saved chats</div>}
      </div>
    </section>
  );
}

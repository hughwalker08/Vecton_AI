// Shared by App.jsx (optimistic sidebar entry) and ChatPage.jsx (the
// conversation row persisted on first send) so the two never drift.
export function deriveChatTitle(question) {
  return question.length > 60 ? `${question.slice(0, 57)}…` : question
}

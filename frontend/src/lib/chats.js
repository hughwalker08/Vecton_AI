// Durable per-user chat history -- see backend/migrations/versions/0007_chat_history.py.
//
// Unlike most of the app's data (retrieval, generation, compliance analysis),
// which goes through the FastAPI backend, this talks to Supabase directly,
// the same way lib/supabase.js's user_profiles reads in App.jsx do. The
// backend has no user auth wired in (see 0006_compliance_feedback.py's
// docstring), so ownership here is enforced by Postgres Row Level Security
// against the Supabase client's own auth session, not by an API route.
//
// This is a separate concern from generation.py's MAX_HISTORY_MESSAGES --
// that's how much of a chat gets replayed to Gemini per question; this is
// whether the chat survives a refresh or shows up on another device at all.
import { supabase } from './supabase.js'

// A signed-in user's chats for the sidebar, most recently started first.
export async function listChats(userId) {
  const { data, error } = await supabase
    .from('chats')
    .select('id, title, jurisdiction')
    .eq('user_id', userId)
    .order('created_at', { ascending: false })

  if (error) throw error
  return data
}

// One chat's full message history, oldest first -- what ChatPage loads when
// a chat is reopened from the sidebar rather than just created.
export async function loadChatMessages(chatId) {
  const { data, error } = await supabase
    .from('chat_messages')
    .select('id, role, text, citations, abstained')
    .eq('chat_id', chatId)
    .order('created_at', { ascending: true })

  if (error) throw error
  return data
}

// Creates a new chat row, returning its id. Called once, when a user asks
// the question that starts a chat (see App.jsx's createChat).
export async function createChat(userId, title, jurisdiction) {
  const { data, error } = await supabase
    .from('chats')
    .insert({ user_id: userId, title, jurisdiction })
    .select('id')
    .single()

  if (error) throw error
  return data.id
}

// Appends one message to a chat. Called after the question is asked and
// again after a real answer comes back (see ChatPage.jsx's sendMessage) --
// never for a failed request's error bubble, which isn't a real turn (same
// reasoning as sendMessage's own history-pairing logic).
export async function saveMessage(chatId, { role, text, citations = null, abstained = false }) {
  const { error } = await supabase
    .from('chat_messages')
    .insert({ chat_id: chatId, role, text, citations, abstained })

  if (error) throw error
}

import { describe, expect, it, vi } from 'vitest'

vi.mock('./supabase.js', () => ({
  supabase: { from: vi.fn() },
}))

import { supabase } from './supabase.js'
import { createChat, listChats, loadChatMessages, saveMessage } from './chats.js'

describe('listChats', () => {
  it('queries a user\'s chats, most recently started first', async () => {
    const order = vi.fn().mockResolvedValue({ data: [{ id: 'c1', title: 'Q1', jurisdiction: 'NSW' }], error: null })
    const eq = vi.fn().mockReturnValue({ order })
    const select = vi.fn().mockReturnValue({ eq })
    supabase.from.mockReturnValue({ select })

    const chats = await listChats('user-1')

    expect(supabase.from).toHaveBeenCalledWith('chats')
    expect(select).toHaveBeenCalledWith('id, title, jurisdiction')
    expect(eq).toHaveBeenCalledWith('user_id', 'user-1')
    expect(order).toHaveBeenCalledWith('created_at', { ascending: false })
    expect(chats).toEqual([{ id: 'c1', title: 'Q1', jurisdiction: 'NSW' }])
  })

  it('throws when Supabase returns an error', async () => {
    const order = vi.fn().mockResolvedValue({ data: null, error: new Error('RLS denied') })
    supabase.from.mockReturnValue({ select: () => ({ eq: () => ({ order }) }) })

    await expect(listChats('user-1')).rejects.toThrow('RLS denied')
  })
})

describe('loadChatMessages', () => {
  it('queries one chat\'s messages, oldest first', async () => {
    const order = vi.fn().mockResolvedValue({
      data: [{ id: 'm1', role: 'user', text: 'Q1', citations: null, abstained: false }],
      error: null,
    })
    const eq = vi.fn().mockReturnValue({ order })
    const select = vi.fn().mockReturnValue({ eq })
    supabase.from.mockReturnValue({ select })

    const messages = await loadChatMessages('chat-1')

    expect(supabase.from).toHaveBeenCalledWith('chat_messages')
    expect(eq).toHaveBeenCalledWith('chat_id', 'chat-1')
    expect(order).toHaveBeenCalledWith('created_at', { ascending: true })
    expect(messages).toEqual([{ id: 'm1', role: 'user', text: 'Q1', citations: null, abstained: false }])
  })

  it('throws when Supabase returns an error', async () => {
    const order = vi.fn().mockResolvedValue({ data: null, error: new Error('network error') })
    supabase.from.mockReturnValue({ select: () => ({ eq: () => ({ order }) }) })

    await expect(loadChatMessages('chat-1')).rejects.toThrow('network error')
  })
})

describe('createChat', () => {
  it('inserts a chat row and returns its id', async () => {
    const single = vi.fn().mockResolvedValue({ data: { id: 'new-chat-id' }, error: null })
    const select = vi.fn().mockReturnValue({ single })
    const insert = vi.fn().mockReturnValue({ select })
    supabase.from.mockReturnValue({ insert })

    const id = await createChat('user-1', 'What ceiling height...', 'NSW')

    expect(supabase.from).toHaveBeenCalledWith('chats')
    expect(insert).toHaveBeenCalledWith({ user_id: 'user-1', title: 'What ceiling height...', jurisdiction: 'NSW' })
    expect(id).toBe('new-chat-id')
  })

  it('throws when Supabase returns an error', async () => {
    const single = vi.fn().mockResolvedValue({ data: null, error: new Error('insert failed') })
    supabase.from.mockReturnValue({ insert: () => ({ select: () => ({ single }) }) })

    await expect(createChat('user-1', 'Q', 'NSW')).rejects.toThrow('insert failed')
  })
})

describe('saveMessage', () => {
  it('inserts a message with the given fields', async () => {
    const insert = vi.fn().mockResolvedValue({ error: null })
    supabase.from.mockReturnValue({ insert })

    await saveMessage('chat-1', { role: 'user', text: 'What ceiling height?' })

    expect(supabase.from).toHaveBeenCalledWith('chat_messages')
    expect(insert).toHaveBeenCalledWith({
      chat_id: 'chat-1',
      role: 'user',
      text: 'What ceiling height?',
      citations: null,
      abstained: false,
    })
  })

  it('carries citations and abstained through when given', async () => {
    const insert = vi.fn().mockResolvedValue({ error: null })
    supabase.from.mockReturnValue({ insert })

    await saveMessage('chat-1', {
      role: 'assistant',
      text: 'No source found.',
      citations: [{ clause_id: 'H1D4' }],
      abstained: true,
    })

    expect(insert).toHaveBeenCalledWith({
      chat_id: 'chat-1',
      role: 'assistant',
      text: 'No source found.',
      citations: [{ clause_id: 'H1D4' }],
      abstained: true,
    })
  })

  it('throws when Supabase returns an error', async () => {
    supabase.from.mockReturnValue({ insert: vi.fn().mockResolvedValue({ error: new Error('insert failed') }) })

    await expect(saveMessage('chat-1', { role: 'user', text: 'Q' })).rejects.toThrow('insert failed')
  })
})

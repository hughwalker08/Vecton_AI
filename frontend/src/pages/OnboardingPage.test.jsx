import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import OnboardingPage from './OnboardingPage.jsx'

vi.mock('../lib/supabase.js', () => ({
  supabase: { from: vi.fn() },
}))

import { supabase } from '../lib/supabase.js'

function mockUpsert(result) {
  const upsert = vi.fn().mockResolvedValue(result)
  supabase.from.mockReturnValue({ upsert })
  return upsert
}

beforeEach(() => {
  supabase.from.mockReset()
})

describe('OnboardingPage', () => {
  it('renders the heading and jurisdiction options', () => {
    mockUpsert({ error: null })
    render(<OnboardingPage userId="user-1" onComplete={vi.fn()} />)

    expect(screen.getByRole('heading', { name: 'Select your state or territory' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'New South Wales (NSW)' })).toBeInTheDocument()
  })

  it('disables Continue until a state is selected', () => {
    mockUpsert({ error: null })
    render(<OnboardingPage userId="user-1" onComplete={vi.fn()} />)

    expect(screen.getByRole('button', { name: 'Continue' })).toBeDisabled()

    fireEvent.change(screen.getByLabelText('Australian state or territory'), {
      target: { value: 'NSW' },
    })

    expect(screen.getByRole('button', { name: 'Continue' })).toBeEnabled()
  })

  it('saves the selected jurisdiction and calls onComplete on success', async () => {
    const upsert = mockUpsert({ error: null })
    const onComplete = vi.fn()
    render(<OnboardingPage userId="user-1" onComplete={onComplete} />)

    fireEvent.change(screen.getByLabelText('Australian state or territory'), {
      target: { value: 'NSW' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }))

    await vi.waitFor(() => expect(onComplete).toHaveBeenCalledWith('NSW'))
    expect(supabase.from).toHaveBeenCalledWith('user_profiles')
    expect(upsert).toHaveBeenCalledWith(
      expect.objectContaining({ id: 'user-1', jurisdiction: 'NSW' }),
    )
  })

  it('shows a saving label while the request is in flight', async () => {
    let resolveUpsert
    supabase.from.mockReturnValue({
      upsert: vi.fn().mockReturnValue(new Promise((resolve) => { resolveUpsert = resolve })),
    })
    render(<OnboardingPage userId="user-1" onComplete={vi.fn()} />)

    fireEvent.change(screen.getByLabelText('Australian state or territory'), {
      target: { value: 'NSW' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }))

    const button = await screen.findByRole('button', { name: 'Saving…' })
    expect(button).toBeDisabled()

    resolveUpsert({ error: null })
  })

  it('shows an error and does not call onComplete when saving fails', async () => {
    mockUpsert({ error: new Error('db unavailable') })
    const onComplete = vi.fn()
    render(<OnboardingPage userId="user-1" onComplete={onComplete} />)

    fireEvent.change(screen.getByLabelText('Australian state or territory'), {
      target: { value: 'NSW' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }))

    expect(await screen.findByText('Unable to save your state or territory.')).toBeInTheDocument()
    expect(onComplete).not.toHaveBeenCalled()
  })

  it('shows a validation error if the form is submitted with nothing selected', () => {
    mockUpsert({ error: null })
    const { container } = render(<OnboardingPage userId="user-1" onComplete={vi.fn()} />)

    // The submit button is disabled with no selection, so this exercises the
    // handler's own guard directly rather than a click a real user can't make.
    fireEvent.submit(container.querySelector('form'))

    expect(screen.getByText('Please select your state or territory.')).toBeInTheDocument()
  })
})

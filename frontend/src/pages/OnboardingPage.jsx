import { useState } from 'react'
import { supabase } from '../lib/supabase.js'
import { AUSTRALIAN_JURISDICTIONS } from '../lib/jurisdictions.js'
import './OnboardingPage.css'

export default function OnboardingPage({ userId, onComplete }) {
  const [jurisdiction, setJurisdiction] = useState('')
  const [isSaving, setIsSaving] = useState(false)
  const [error, setError] = useState('')

  async function handleSubmit(event) {
    event.preventDefault()

    if (!jurisdiction) {
      setError('Please select your state or territory.')
      return
    }

    setIsSaving(true)
    setError('')

    const { error: saveError } = await supabase
      .from('user_profiles')
      .upsert({
        id: userId,
        jurisdiction,
        updated_at: new Date().toISOString(),
      })

    if (saveError) {
      console.error(saveError)
      setError('Unable to save your state or territory.')
      setIsSaving(false)
      return
    }

    onComplete(jurisdiction)
  }

  return (
    <main className="onboarding-page">
      <div className="onboarding-card">
        <div className="onboarding-brand">
          Vecton <span className="accent">AI</span>
        </div>

        <h1>Select your state or territory</h1>

        <p className="onboarding-description">
          Answers will be drawn from the codes and regulations that apply in
          your jurisdiction.
        </p>

        <form onSubmit={handleSubmit}>
          <label className="onboarding-field" htmlFor="jurisdiction">
            Australian state or territory
          </label>

          <select
            id="jurisdiction"
            className="jurisdiction-select"
            data-empty={jurisdiction === ''}
            value={jurisdiction}
            onChange={(event) => setJurisdiction(event.target.value)}
            disabled={isSaving}
          >
            <option value="">Select a state or territory</option>

            {AUSTRALIAN_JURISDICTIONS.map((item) => (
              <option key={item.code} value={item.code}>
                {item.name} ({item.code})
              </option>
            ))}
          </select>

          <button
            type="submit"
            className="onboarding-submit"
            disabled={isSaving || !jurisdiction}
          >
            {isSaving ? 'Saving…' : 'Continue'}
          </button>
        </form>

        {error && <p className="onboarding-error">{error}</p>}
      </div>
    </main>
  )
}
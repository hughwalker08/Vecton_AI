import { useState } from 'react'
import { supabase } from '../lib/supabase.js'
import { AUSTRALIAN_JURISDICTIONS } from '../lib/jurisdictions.js'

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
    <main>
      <h1>Select your State / Region</h1>

      <p>
        This will be used to provide construction compliance information
        relevant to your jurisdiction.
      </p>

      <form onSubmit={handleSubmit}>
        <label htmlFor="jurisdiction">
          Australian State / Territory
        </label>

        <select
          id="jurisdiction"
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
          disabled={isSaving || !jurisdiction}
        >
          {isSaving ? 'Saving...' : 'Continue'}
        </button>
      </form>

      {error && <p>{error}</p>}
    </main>
  )
}
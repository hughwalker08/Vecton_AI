// Runs once before each test file (see vite.config.js `test.setupFiles`).
// Adds jest-dom's DOM matchers (toBeInTheDocument, etc.) to Vitest's `expect`.
//
// Plain `import '@testing-library/jest-dom'` assumes a global `expect`
// (like Jest provides automatically) -- Vitest doesn't set that up unless
// `test.globals: true` is on, so it's pulled in explicitly here instead.
import { afterEach, expect } from 'vitest'
import * as matchers from '@testing-library/jest-dom/matchers'
import { cleanup } from '@testing-library/react'

expect.extend(matchers)

// React Testing Library auto-unmounts components after each test IF it
// detects a global `afterEach` (like Jest provides automatically) -- same
// gap as above, since we don't set test.globals: true. Without this,
// every render() in a file keeps piling onto document.body, and multi-test
// files start seeing "found multiple elements" from earlier tests' leftovers.
afterEach(() => {
  cleanup()
})

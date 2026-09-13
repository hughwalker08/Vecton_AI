// Runs once before each test file (see vite.config.js `test.setupFiles`).
// Adds jest-dom's DOM matchers (toBeInTheDocument, etc.) to Vitest's `expect`.
//
// Plain `import '@testing-library/jest-dom'` assumes a global `expect`
// (like Jest provides automatically) -- Vitest doesn't set that up unless
// `test.globals: true` is on, so it's pulled in explicitly here instead.
import { expect } from 'vitest'
import * as matchers from '@testing-library/jest-dom/matchers'

expect.extend(matchers)

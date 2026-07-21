import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export interface AuthUser {
  id: string
  email: string
  dataentry_schema: string
}

export type Theme = 'light' | 'dark'

interface SettingsState {
  token: string | null
  user: AuthUser | null
  theme: Theme
  setAuth: (token: string, user: AuthUser) => void
  clearAuth: () => void
  setTheme: (theme: Theme) => void
  toggleTheme: () => void
}

export const useSettingsStore = create<SettingsState>()(
  persist(
    (set, get) => ({
      token: null,
      user: null,
      theme: 'light',
      setAuth: (token, user) => set({ token, user }),
      clearAuth: () => set({ token: null, user: null }),
      setTheme: (theme) => set({ theme }),
      toggleTheme: () => set({ theme: get().theme === 'dark' ? 'light' : 'dark' }),
    }),
    { name: 'standup-settings' }
  )
)

/** Reflect the current theme onto <html> so Tailwind's `dark:` variants apply. */
export function applyTheme(theme: Theme) {
  const root = document.documentElement
  if (theme === 'dark') root.classList.add('dark')
  else root.classList.remove('dark')
}

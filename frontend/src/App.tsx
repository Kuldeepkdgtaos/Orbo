import { useEffect } from 'react'
import { BrowserRouter, Routes, Route, Navigate, useParams } from 'react-router-dom'
import { useSettingsStore, applyTheme } from './stores/settings'
import Login from './pages/Login'
import Register from './pages/Register'
import Dashboard from './pages/Dashboard'
import NewStandup from './pages/NewStandup'
import NewTemplate from './pages/NewTemplate'
import StandupDetail from './pages/StandupDetail'
import TemplateDetail from './pages/TemplateDetail'
import DataEntry from './pages/DataEntry'
import DataEntryTable from './pages/DataEntryTable'
import Summaries from './pages/Summaries'
import Settings from './pages/Settings'
import Features from './pages/Features'
import Layout from './components/Layout'

function RequireAuth({ children }: { children: JSX.Element }) {
  const token = useSettingsStore((s) => s.token)
  if (!token) return <Navigate to="/login" replace />
  return children
}

// Guard the :domain segment to the two known domains.
function DomainGuard({ children }: { children: JSX.Element }) {
  const { domain } = useParams<{ domain: string }>()
  if (domain === 'standup' || domain === 'project') return children
  return <Navigate to="/standup/meetings" replace />
}

export default function App() {
  const theme = useSettingsStore((s) => s.theme)
  useEffect(() => { applyTheme(theme) }, [theme])

  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/register" element={<Register />} />

        <Route
          path="/"
          element={
            <RequireAuth>
              <Layout />
            </RequireAuth>
          }
        >
          <Route index element={<Navigate to="/standup/meetings" replace />} />

          {/* Domain-scoped panels: :domain ∈ {standup, project} */}
          <Route path=":domain/meetings" element={<DomainGuard><Dashboard /></DomainGuard>} />
          <Route path=":domain/meetings/new" element={<DomainGuard><NewStandup /></DomainGuard>} />
          <Route path=":domain/meetings/:id" element={<DomainGuard><StandupDetail /></DomainGuard>} />
          <Route path=":domain/templates/new" element={<DomainGuard><NewTemplate /></DomainGuard>} />
          <Route path=":domain/templates/:id" element={<DomainGuard><TemplateDetail /></DomainGuard>} />
          <Route path=":domain/data-entry" element={<DomainGuard><DataEntry /></DomainGuard>} />
          <Route path=":domain/data-entry/:tableId" element={<DomainGuard><DataEntryTable /></DomainGuard>} />
          <Route path=":domain/summaries" element={<DomainGuard><Summaries /></DomainGuard>} />

          <Route path="settings" element={<Settings />} />
          <Route path="features" element={<Features />} />
        </Route>

        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}

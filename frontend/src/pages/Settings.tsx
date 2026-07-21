import { useNavigate } from 'react-router-dom'
import { LogOut } from 'lucide-react'
import { useSettingsStore } from '../stores/settings'

export default function Settings() {
  const navigate = useNavigate()
  const user = useSettingsStore((s) => s.user)
  const clearAuth = useSettingsStore((s) => s.clearAuth)

  const handleLogout = () => {
    clearAuth()
    navigate('/login')
  }

  return (
    <div className="max-w-xl space-y-6">
      <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">Settings</h1>

      <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-5 space-y-4">
        <h2 className="font-semibold text-gray-800 dark:text-gray-200">Account</h2>
        <dl className="space-y-3 text-sm">
          <div>
            <dt className="text-gray-500 dark:text-gray-400">Email</dt>
            <dd className="text-gray-900 dark:text-gray-100">{user?.email ?? '—'}</dd>
          </div>
          <div>
            <dt className="text-gray-500 dark:text-gray-400">Data Entry schema</dt>
            <dd className="font-mono text-xs text-gray-700 dark:text-gray-300">{user?.dataentry_schema ?? '—'}</dd>
          </div>
        </dl>
        <button onClick={handleLogout} className="btn-secondary flex items-center gap-1.5">
          <LogOut size={15} /> Logout
        </button>
      </div>

      <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-5 text-sm text-gray-600 dark:text-gray-400 space-y-2">
        <h2 className="font-semibold text-gray-800 dark:text-gray-200">Service configuration</h2>
        <p>
          Recall.ai, Azure OpenAI, and Microsoft Graph credentials are configured server-side via
          environment variables (<code>.env</code>), not from this page. See the Features page for
          setup details.
        </p>
      </div>
    </div>
  )
}

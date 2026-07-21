import { Outlet, NavLink, useNavigate } from 'react-router-dom'
import {
  Calendar, Table, BarChart3, Settings, Sparkles, LogOut,
  ClipboardList, FolderKanban, Sun, Moon,
} from 'lucide-react'
import { useSettingsStore } from '../stores/settings'

const subLinkClass = ({ isActive }: { isActive: boolean }) =>
  `flex items-center gap-2 pl-9 pr-3 py-2 rounded-md text-sm font-medium transition-colors ${
    isActive ? 'bg-blue-600 text-white' : 'text-gray-600 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-700'
  }`

const bottomLinkClass = ({ isActive }: { isActive: boolean }) =>
  `flex items-center gap-2 px-3 py-2 rounded-md text-sm font-medium transition-colors ${
    isActive ? 'bg-blue-600 text-white' : 'text-gray-600 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-700'
  }`

function DomainSection({ domain, label, Icon }: { domain: string; label: string; Icon: any }) {
  return (
    <div className="mb-4">
      <div className="flex items-center gap-2 px-3 py-2 text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide">
        <Icon size={15} />
        {label}
      </div>
      <div className="space-y-0.5">
        <NavLink to={`/${domain}/meetings`} className={subLinkClass}>
          <Calendar size={15} /> Meetings
        </NavLink>
        <NavLink to={`/${domain}/data-entry`} className={subLinkClass}>
          <Table size={15} /> Data Entry
        </NavLink>
        <NavLink to={`/${domain}/summaries`} className={subLinkClass}>
          <BarChart3 size={15} /> Summaries
        </NavLink>
      </div>
    </div>
  )
}

export default function Layout() {
  const navigate = useNavigate()
  const user = useSettingsStore((s) => s.user)
  const clearAuth = useSettingsStore((s) => s.clearAuth)
  const theme = useSettingsStore((s) => s.theme)
  const toggleTheme = useSettingsStore((s) => s.toggleTheme)

  const handleLogout = () => {
    clearAuth()
    navigate('/login')
  }

  return (
    <div className="min-h-screen flex">
      {/* Sidebar */}
      <aside className="w-60 bg-white dark:bg-gray-800 border-r border-gray-200 dark:border-gray-700 flex flex-col shrink-0">
        <div className="flex items-center gap-2 font-bold text-lg text-blue-700 dark:text-blue-400 px-4 py-4 border-b border-gray-100 dark:border-gray-700">
          <span>🪐</span>
          <span className="text-base">Orbo</span>
        </div>
        <nav className="flex-1 overflow-y-auto px-2 py-4">
          <DomainSection domain="standup" label="Standup Management" Icon={ClipboardList} />
          <DomainSection domain="project" label="Project Management" Icon={FolderKanban} />
        </nav>
        <div className="border-t border-gray-100 dark:border-gray-700 px-2 py-3 space-y-0.5">
          <NavLink to="/settings" className={bottomLinkClass}>
            <Settings size={15} /> Settings
          </NavLink>
          <NavLink to="/features" className={bottomLinkClass}>
            <Sparkles size={15} /> Features
          </NavLink>
        </div>
      </aside>

      {/* Main column */}
      <div className="flex-1 flex flex-col min-w-0">
        <header className="bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 px-6 py-3 flex items-center justify-end gap-4">
          <button
            onClick={toggleTheme}
            className="flex items-center justify-center w-8 h-8 rounded-md text-gray-500 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-700 transition-colors"
            title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
            aria-label="Toggle theme"
          >
            {theme === 'dark' ? <Sun size={17} /> : <Moon size={17} />}
          </button>
          {user && <span className="text-sm text-gray-500 dark:text-gray-400">{user.email}</span>}
          <button
            onClick={handleLogout}
            className="flex items-center gap-1.5 text-sm text-gray-600 hover:text-gray-900 dark:text-gray-300 dark:hover:text-white"
          >
            <LogOut size={15} /> Logout
          </button>
        </header>
        <main className="flex-1 px-6 py-6 max-w-6xl mx-auto w-full">
          <Outlet />
        </main>
      </div>
    </div>
  )
}

import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { PlusCircle, Repeat, RefreshCw } from 'lucide-react'
import { api } from '../api/client'
import StandupCard from '../components/StandupCard'
import TemplateCard from '../components/TemplateCard'
import { useDomain } from '../hooks/useDomain'

export default function Dashboard() {
  const domain = useDomain()
  const isProject = domain === 'project'
  const noun = isProject ? 'Project Meeting' : 'Standup'

  const { data: standups = [], isLoading: loadingStandups, error, refetch: refetchStandups } = useQuery({
    queryKey: ['standups', domain],
    queryFn: () => api.standups.list(domain),
    refetchInterval: 10_000,
  })

  const { data: templates = [], isLoading: loadingTemplates, refetch: refetchTemplates } = useQuery({
    queryKey: ['templates', domain],
    queryFn: () => api.templates.list(domain),
    refetchInterval: 30_000,
  })

  const standaloneStandups = standups.filter(s => !s.template_id)

  const handleRefresh = () => { refetchStandups(); refetchTemplates() }

  return (
    <div className="space-y-8">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">Meetings</h1>
        <div className="flex gap-2">
          <button onClick={handleRefresh} className="btn-secondary flex items-center gap-1.5">
            <RefreshCw size={15} />
            Refresh
          </button>
          <Link to={`/${domain}/templates/new`} className="btn-primary flex items-center gap-1.5">
            <Repeat size={15} />
            New Recurring
          </Link>
          <Link to={`/${domain}/meetings/new`} className="btn-secondary flex items-center gap-1.5">
            <PlusCircle size={15} />
            One-off
          </Link>
        </div>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-red-700 text-sm dark:bg-red-500/10 dark:border-red-500/30 dark:text-red-300">
          Failed to load meetings. Try signing in again.
        </div>
      )}

      {/* Recurring Templates */}
      <section>
        <h2 className="text-sm font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-3">
          Recurring {noun}s
        </h2>
        {loadingTemplates && <div className="text-gray-400 text-sm py-4">Loading…</div>}
        {!loadingTemplates && templates.length === 0 && (
          <div className="rounded-lg border-2 border-dashed border-gray-200 dark:border-gray-700 p-6 text-center">
            <p className="text-sm text-gray-400 dark:text-gray-500">No recurring {noun.toLowerCase()}s yet.</p>
            <Link to={`/${domain}/templates/new`} className="text-blue-600 hover:underline text-sm mt-1 inline-block">
              Create one →
            </Link>
          </div>
        )}
        {templates.length > 0 && (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {templates.map(t => <TemplateCard key={t.id} template={t} />)}
          </div>
        )}
      </section>

      {/* One-off / standalone meetings */}
      {standaloneStandups.length > 0 && (
        <section>
          <h2 className="text-sm font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-3">
            One-off {noun}s
          </h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {standaloneStandups.map(s => <StandupCard key={s.id} standup={s} />)}
          </div>
        </section>
      )}

      {!loadingStandups && !loadingTemplates && templates.length === 0 && standaloneStandups.length === 0 && (
        <div className="text-center py-16 text-gray-400 dark:text-gray-500">
          <p className="text-lg mb-2">No {noun.toLowerCase()}s yet</p>
          <Link to={`/${domain}/templates/new`} className="text-blue-600 hover:underline text-sm">
            Create your first recurring {noun.toLowerCase()} →
          </Link>
        </div>
      )}
    </div>
  )
}

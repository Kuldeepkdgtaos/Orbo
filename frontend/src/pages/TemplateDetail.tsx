import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Play, Repeat, ChevronRight } from 'lucide-react'
import { api } from '../api/client'
import StatusBadge from '../components/StatusBadge'
import { useDomain } from '../hooks/useDomain'

function formatDateTime(iso: string | null) {
  if (!iso) return '—'
  return new Date(iso).toLocaleString([], {
    month: 'short', day: 'numeric', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

export default function TemplateDetail() {
  const { id } = useParams<{ id: string }>()
  const domain = useDomain()
  const navigate = useNavigate()
  const qc = useQueryClient()

  const { data: template, isLoading: loadingTemplate } = useQuery({
    queryKey: ['template', id],
    queryFn: () => api.templates.get(id!),
    enabled: !!id,
  })

  const { data: sessions = [], isLoading: loadingSessions } = useQuery({
    queryKey: ['template-sessions', id],
    queryFn: () => api.templates.sessions(id!),
    enabled: !!id,
    refetchInterval: 10_000,
  })

  const startSessionMutation = useMutation({
    mutationFn: async () => {
      const session = await api.templates.startSession(id!)
      await api.standups.start(session.id)
      return session
    },
    onSuccess: (session) => {
      qc.invalidateQueries({ queryKey: ['template-sessions', id] })
      qc.invalidateQueries({ queryKey: ['templates', domain] })
      navigate(`/${domain}/meetings/${session.id}`)
    },
  })

  if (loadingTemplate) return <div className="text-gray-400 text-center py-12">Loading…</div>
  if (!template) return <div className="text-red-500 text-center py-12">Template not found.</div>

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-blue-50 text-blue-700 border border-blue-200">
              <Repeat size={10} />
              Recurring Template
            </span>
          </div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">{template.name}</h1>
          <p className="text-gray-500 dark:text-gray-400 mt-0.5">{template.team_name}</p>
        </div>
        <button
          onClick={() => startSessionMutation.mutate()}
          disabled={startSessionMutation.isPending}
          className="btn-primary flex items-center gap-1.5"
        >
          <Play size={14} />
          {startSessionMutation.isPending ? 'Starting…' : 'Start New Session'}
        </button>
      </div>

      {startSessionMutation.isError && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-red-700 text-sm">
          Failed to start session. Check your Recall.ai configuration.
        </div>
      )}

      {/* Template config */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-4">
          <h2 className="font-semibold text-gray-700 dark:text-gray-300 mb-3 text-sm uppercase tracking-wide">Meeting Config</h2>
          <dl className="space-y-2 text-sm">
            <div>
              <dt className="text-gray-500">Meeting URL</dt>
              <dd className="truncate text-blue-600">
                <a href={template.meeting_url} target="_blank" rel="noopener noreferrer">
                  {template.meeting_url}
                </a>
              </dd>
            </div>
            {template.management_recipients.length > 0 && (
              <div>
                <dt className="text-gray-500">Recipients</dt>
                <dd>{template.management_recipients.join(', ')}</dd>
              </div>
            )}
          </dl>
        </div>

        <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-4">
          <h2 className="font-semibold text-gray-700 dark:text-gray-300 mb-3 text-sm uppercase tracking-wide">Participants</h2>
          <ul className="space-y-2">
            {template.participants.map((p) => (
              <li key={p.id} className="flex items-start gap-2 text-sm">
                <div className="w-6 h-6 rounded-full bg-blue-100 flex items-center justify-center text-blue-700 font-bold text-xs shrink-0 mt-0.5">
                  {p.name[0]}
                </div>
                <div>
                  <div className="font-medium">{p.name}</div>
                  {(p.designation || p.department) && (
                    <div className="text-xs text-gray-400">
                      {[p.designation, p.department].filter(Boolean).join(' · ')}
                    </div>
                  )}
                  <div className="text-xs text-gray-400">{p.email}</div>
                </div>
              </li>
            ))}
          </ul>
        </div>
      </div>

      {/* Sessions list */}
      <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700">
        <div className="px-5 py-4 border-b border-gray-100 dark:border-gray-700 flex items-center justify-between">
          <h2 className="font-semibold text-gray-800 dark:text-gray-200">
            Past Sessions
            {sessions.length > 0 && (
              <span className="ml-2 text-xs font-normal text-gray-400">{sessions.length} total</span>
            )}
          </h2>
        </div>

        {loadingSessions && (
          <div className="p-5 text-gray-400 text-sm">Loading sessions…</div>
        )}

        {!loadingSessions && sessions.length === 0 && (
          <div className="p-8 text-center text-gray-400">
            <p className="text-sm">No sessions yet.</p>
            <p className="text-xs mt-1">Click "Start New Session" to run the first standup.</p>
          </div>
        )}

        {sessions.length > 0 && (
          <ul className="divide-y divide-gray-100 dark:divide-gray-700">
            {sessions.map((session) => (
              <li key={session.id}>
                <button
                  onClick={() => navigate(`/${domain}/meetings/${session.id}`)}
                  className="w-full flex items-center justify-between px-5 py-3.5 hover:bg-gray-50 dark:hover:bg-gray-700/50 transition-colors text-left"
                >
                  <div className="flex items-center gap-3">
                    <div className="w-8 h-8 rounded-full bg-gray-100 flex items-center justify-center text-gray-600 font-bold text-sm shrink-0">
                      {session.session_number}
                    </div>
                    <div>
                      <div className="text-sm font-medium text-gray-900">
                        Session {session.session_number}
                      </div>
                      <div className="text-xs text-gray-500 mt-0.5">
                        {session.started_at
                          ? formatDateTime(session.started_at)
                          : formatDateTime(session.created_at)}
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <StatusBadge status={session.status} />
                    <ChevronRight size={16} className="text-gray-400" />
                  </div>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}

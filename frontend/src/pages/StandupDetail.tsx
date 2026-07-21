import { useParams, Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Download, Mail, Play, RefreshCw, ChevronLeft } from 'lucide-react'
import { api } from '../api/client'
import StatusBadge from '../components/StatusBadge'
import TranscriptViewer from '../components/TranscriptViewer'
import SummaryPanel from '../components/SummaryPanel'
import LiveStatusStream from '../components/LiveStatusStream'
import { useDomain } from '../hooks/useDomain'

export default function StandupDetail() {
  const { id } = useParams<{ id: string }>()
  const domain = useDomain()
  const qc = useQueryClient()

  const { data: standup, isLoading } = useQuery({
    queryKey: ['standup', id],
    queryFn: () => api.standups.get(id!),
    refetchInterval: 5_000,
    enabled: !!id,
  })

  const { data: utterances = [] } = useQuery({
    queryKey: ['utterances', id],
    queryFn: () => api.utterances.list(id!),
    enabled: !!id && standup?.status === 'completed',
    // Poll every 5s until utterances arrive, then stop. In React Query v5 the
    // refetchInterval callback receives the Query object, so read query.state.data.
    refetchInterval: (query) => {
      const d = query.state.data
      return !d || d.length === 0 ? 5_000 : false
    },
    retry: 3,
  })

  const { data: summary, refetch: refetchSummary } = useQuery({
    queryKey: ['summary', id],
    queryFn: () => api.summary.get(id!),
    enabled: !!id && standup?.status === 'completed',
    refetchInterval: (query) => (!query.state.data ? 5_000 : false),
    retry: 3,
  })

  const { data: participantSummaries = [] } = useQuery({
    queryKey: ['participant-summaries', id],
    queryFn: () => api.summary.participantSummaries(id!),
    enabled: !!id && standup?.status === 'completed',
    refetchInterval: (query) => {
      const d = query.state.data
      return !d || d.length === 0 ? 5_000 : false
    },
    retry: 3,
  })

  const startMutation = useMutation({
    mutationFn: () => api.standups.start(id!),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['standup', id] }),
  })

  const resendMutation = useMutation({
    mutationFn: () => api.standups.resendEmail(id!),
  })

  const regenerateMutation = useMutation({
    mutationFn: () => api.summary.regenerate(id!),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['summary', id] })
      qc.invalidateQueries({ queryKey: ['participant-summaries', id] })
      qc.invalidateQueries({ queryKey: ['utterances', id] })
    },
  })

  if (isLoading) return <div className="text-gray-400 text-center py-12">Loading…</div>
  if (!standup) return <div className="text-red-500 text-center py-12">Standup not found.</div>

  const canStart = standup.status === 'idle'
  const isRunning = standup.status === 'in_progress' || standup.status === 'dispatched'
  const isCompleted = standup.status === 'completed'

  return (
    <div className="space-y-6">
      {/* Breadcrumb */}
      {standup.template_id ? (
        <Link
          to={`/${domain}/templates/${standup.template_id}`}
          className="inline-flex items-center gap-1 text-sm text-blue-600 hover:text-blue-800"
        >
          <ChevronLeft size={16} />
          Back to template
          {standup.session_number && (
            <span className="ml-1 text-gray-400">· Session {standup.session_number}</span>
          )}
        </Link>
      ) : (
        <Link to={`/${domain}/meetings`} className="inline-flex items-center gap-1 text-sm text-gray-500 hover:text-gray-700">
          <ChevronLeft size={16} />
          Meetings
        </Link>
      )}

      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">{standup.name}</h1>
          <p className="text-gray-500 dark:text-gray-400 mt-0.5">{standup.team_name}</p>
        </div>
        <div className="flex items-center gap-2">
          <StatusBadge status={standup.status} />
          {canStart && (
            <button
              onClick={() => startMutation.mutate()}
              disabled={startMutation.isPending}
              className="btn-primary flex items-center gap-1.5"
            >
              <Play size={14} />
              {startMutation.isPending ? 'Starting…' : 'Start Meeting'}
            </button>
          )}
          {isCompleted && (
            <>
              <button
                onClick={() => regenerateMutation.mutate()}
                disabled={regenerateMutation.isPending}
                className="btn-secondary flex items-center gap-1.5"
                title="Re-run GPT-4o summarization"
              >
                <RefreshCw size={14} />
                {regenerateMutation.isPending ? 'Regenerating…' : 'Regenerate'}
              </button>
              <a
                href={api.standups.excelUrl(standup.id)}
                className="btn-secondary flex items-center gap-1.5"
                download
              >
                <Download size={14} />
                Excel
              </a>
              <button
                onClick={() => resendMutation.mutate()}
                disabled={resendMutation.isPending}
                className="btn-secondary flex items-center gap-1.5"
              >
                <Mail size={14} />
                {resendMutation.isPending ? 'Sending…' : 'Resend Email'}
              </button>
            </>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-4">
          <h2 className="font-semibold text-gray-700 dark:text-gray-300 mb-3 text-sm uppercase tracking-wide">Meeting Info</h2>
          <dl className="space-y-2 text-sm">
            <div>
              <dt className="text-gray-500 dark:text-gray-400">URL</dt>
              <dd className="truncate text-blue-600">
                <a href={standup.meeting_url} target="_blank" rel="noopener noreferrer">
                  {standup.meeting_url}
                </a>
              </dd>
            </div>
            <div>
              <dt className="text-gray-500 dark:text-gray-400">Started</dt>
              <dd>{standup.started_at ? new Date(standup.started_at).toLocaleString() : '—'}</dd>
            </div>
            <div>
              <dt className="text-gray-500 dark:text-gray-400">Ended</dt>
              <dd>{standup.ended_at ? new Date(standup.ended_at).toLocaleString() : '—'}</dd>
            </div>
            <div>
              <dt className="text-gray-500 dark:text-gray-400">Bot ID</dt>
              <dd className="text-xs font-mono truncate">{standup.recall_bot_id ?? '—'}</dd>
            </div>
          </dl>
        </div>

        <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-4">
          <h2 className="font-semibold text-gray-700 dark:text-gray-300 mb-3 text-sm uppercase tracking-wide">Participants</h2>
          <ul className="space-y-2">
            {standup.participants.map((p) => (
              <li key={p.id} className="flex items-center gap-2 text-sm">
                <div className="w-6 h-6 rounded-full bg-blue-100 flex items-center justify-center text-blue-700 font-bold text-xs shrink-0">
                  {p.name[0]}
                </div>
                <div>
                  <div className="flex items-center gap-1.5">
                    <div className="font-medium">{p.name}</div>
                    {p.is_manager && (
                      <span className="px-1.5 py-0.5 rounded text-xs font-medium bg-indigo-50 text-indigo-700 border border-indigo-200">
                        Manager
                      </span>
                    )}
                  </div>
                  {(p.designation || p.department) && (
                    <div className="text-xs text-gray-500">
                      {[p.designation, p.department].filter(Boolean).join(' · ')}
                    </div>
                  )}
                  <div className="text-xs text-gray-400">{p.email}</div>
                </div>
              </li>
            ))}
          </ul>
        </div>

        <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-4">
          <h2 className="font-semibold text-gray-700 dark:text-gray-300 mb-3 text-sm uppercase tracking-wide">
            {isRunning ? 'Live Status' : 'State History'}
          </h2>
          <LiveStatusStream standupId={standup.id} />
        </div>
      </div>

      <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-5">
        <h2 className="font-semibold text-gray-800 dark:text-gray-200 mb-4">Summaries</h2>
        {isCompleted ? (
          <SummaryPanel
            summary={summary ?? null}
            participantSummaries={participantSummaries}
            participants={standup.participants}
          />
        ) : (
          <p className="text-gray-400 text-sm">Summary will be generated after the meeting ends.</p>
        )}
      </div>

      <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-5">
        <h2 className="font-semibold text-gray-800 dark:text-gray-200 mb-4">
          Transcript
          {utterances.length > 0 && (
            <span className="ml-2 text-xs font-normal text-gray-400">{utterances.length} lines</span>
          )}
        </h2>
        <TranscriptViewer utterances={utterances} participants={standup.participants} />
      </div>
    </div>
  )
}

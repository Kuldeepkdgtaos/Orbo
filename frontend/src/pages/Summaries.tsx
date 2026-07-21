import { useState } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import ReactMarkdown from 'react-markdown'
import { RefreshCw, Sparkles } from 'lucide-react'
import {
  api, Scope, Granularity, AggregateSummary, MeetingSummaryItem,
} from '../api/client'
import { useDomain } from '../hooks/useDomain'

// ── Markdown rendering (same conventions as SummaryPanel) ─────────────────────

function stripCodeFence(text: string): string {
  return text.replace(/^```(?:markdown)?\s*/i, '').replace(/\s*```\s*$/, '').trim()
}
const mdComponents = {
  h1: ({ children }: any) => <h1 className="text-lg font-bold text-gray-900 dark:text-gray-100 mt-4 mb-2 first:mt-0">{children}</h1>,
  h2: ({ children }: any) => <h2 className="text-base font-bold text-gray-900 dark:text-gray-100 mt-4 mb-2 first:mt-0">{children}</h2>,
  h3: ({ children }: any) => <h3 className="text-sm font-bold text-gray-800 dark:text-gray-200 mt-3 mb-1.5 first:mt-0">{children}</h3>,
  p: ({ children }: any) => <p className="text-sm text-gray-700 dark:text-gray-300 mb-2 leading-relaxed">{children}</p>,
  ul: ({ children }: any) => <ul className="list-disc list-inside space-y-1 mb-2 text-sm text-gray-700 dark:text-gray-300">{children}</ul>,
  ol: ({ children }: any) => <ol className="list-decimal list-inside space-y-1 mb-2 text-sm text-gray-700 dark:text-gray-300">{children}</ol>,
  li: ({ children }: any) => <li className="text-sm text-gray-700 dark:text-gray-300 leading-relaxed">{children}</li>,
  strong: ({ children }: any) => <strong className="font-semibold text-gray-900 dark:text-gray-100">{children}</strong>,
  hr: () => <hr className="my-3 border-gray-200 dark:border-gray-700" />,
}
const Md = ({ text }: { text: string }) => (
  <ReactMarkdown components={mdComponents}>{stripCodeFence(text || '')}</ReactMarkdown>
)

function isoDate(d: Date): string {
  return d.toISOString().slice(0, 10)
}

export default function Summaries() {
  const domain = useDomain()

  const scopeOptions: Scope[] = domain === 'project'
    ? ['call', 'project', 'overall']
    : ['call', 'individual', 'overall']

  const today = new Date()
  const monthAgo = new Date(today.getTime() - 30 * 24 * 60 * 60 * 1000)

  const [scope, setScope] = useState<Scope>(scopeOptions[0])
  const [granularity, setGranularity] = useState<Granularity>('overall')
  const [rangeStart, setRangeStart] = useState(isoDate(monthAgo))
  const [rangeEnd, setRangeEnd] = useState(isoDate(today))
  const [subjectEmail, setSubjectEmail] = useState('')   // individual scope
  const [projectId, setProjectId] = useState('')         // project scope / call filter
  const [selectedTables, setSelectedTables] = useState<string[]>([])

  const [meetingResults, setMeetingResults] = useState<MeetingSummaryItem[] | null>(null)
  const [aggregateResults, setAggregateResults] = useState<AggregateSummary[] | null>(null)

  const { data: templates = [] } = useQuery({
    queryKey: ['templates', domain],
    queryFn: () => api.templates.list(domain),
  })
  const { data: dataTables = [] } = useQuery({
    queryKey: ['dataentry-tables', domain],
    queryFn: () => api.dataentry.listTables(domain),
  })

  const run = useMutation({
    mutationFn: async (force: boolean) => {
      if (scope === 'call') {
        const items = await api.insights.meetings({
          domain, range_start: rangeStart, range_end: rangeEnd,
          subject_id: projectId || undefined,
        })
        return { kind: 'call' as const, items }
      }
      const subject_id = scope === 'individual' ? subjectEmail : (scope === 'project' ? projectId : '')
      const rows = await api.insights.aggregate({
        domain, scope, granularity, range_start: rangeStart, range_end: rangeEnd,
        subject_id: subject_id || undefined,
        dataentry_table_ids: selectedTables,
        force,
      })
      return { kind: 'aggregate' as const, rows }
    },
    onSuccess: (res) => {
      if (res.kind === 'call') { setMeetingResults(res.items); setAggregateResults(null) }
      else { setAggregateResults(res.rows); setMeetingResults(null) }
    },
  })

  const toggleTable = (id: string) =>
    setSelectedTables((s) => s.includes(id) ? s.filter((x) => x !== id) : [...s, id])

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">Summaries</h1>

      {/* Controls */}
      <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-5 space-y-4">
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          <div>
            <label className="label">Scope</label>
            <select className="input-field" value={scope} onChange={(e) => setScope(e.target.value as Scope)}>
              {scopeOptions.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
          {scope !== 'call' && (
            <div>
              <label className="label">Granularity</label>
              <select className="input-field" value={granularity} onChange={(e) => setGranularity(e.target.value as Granularity)}>
                <option value="overall">Overall</option>
                <option value="monthly">Monthly</option>
                <option value="weekly">Weekly</option>
              </select>
            </div>
          )}
          <div>
            <label className="label">From</label>
            <input type="date" className="input-field" value={rangeStart} onChange={(e) => setRangeStart(e.target.value)} />
          </div>
          <div>
            <label className="label">To</label>
            <input type="date" className="input-field" value={rangeEnd} onChange={(e) => setRangeEnd(e.target.value)} />
          </div>
        </div>

        {/* Subject selectors */}
        {scope === 'individual' && (
          <div>
            <label className="label">Participant email</label>
            <input className="input-field" value={subjectEmail} onChange={(e) => setSubjectEmail(e.target.value)}
              placeholder="teammate@company.com" />
          </div>
        )}
        {(scope === 'project' || (scope === 'call' && domain === 'project')) && (
          <div>
            <label className="label">Project {scope === 'call' ? '(filter, optional)' : ''}</label>
            <select className="input-field" value={projectId} onChange={(e) => setProjectId(e.target.value)}>
              <option value="">{scope === 'project' ? 'All projects (portfolio)' : 'All'}</option>
              {templates.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
            </select>
          </div>
        )}

        {/* Data Entry inclusion */}
        {scope !== 'call' && dataTables.length > 0 && (
          <div>
            <label className="label">Include Data Entry tables</label>
            <div className="flex flex-wrap gap-2">
              {dataTables.map((t) => (
                <label key={t.id} className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-sm cursor-pointer ${
                  selectedTables.includes(t.id)
                    ? 'bg-blue-50 border-blue-300 text-blue-700 dark:bg-blue-500/15 dark:border-blue-500/40 dark:text-blue-300'
                    : 'border-gray-200 text-gray-600 dark:border-gray-600 dark:text-gray-300'
                }`}>
                  <input type="checkbox" className="sr-only" checked={selectedTables.includes(t.id)}
                    onChange={() => toggleTable(t.id)} />
                  {t.display_name}
                </label>
              ))}
            </div>
          </div>
        )}

        <div className="flex gap-2">
          <button className="btn-primary flex items-center gap-1.5" disabled={run.isPending}
            onClick={() => run.mutate(false)}>
            <Sparkles size={15} /> {run.isPending ? 'Generating…' : 'Generate'}
          </button>
          {scope !== 'call' && (
            <button className="btn-secondary flex items-center gap-1.5" disabled={run.isPending}
              onClick={() => run.mutate(true)} title="Bypass cache and regenerate">
              <RefreshCw size={15} /> Regenerate
            </button>
          )}
        </div>
        {run.isError && (
          <div className="bg-red-50 border border-red-200 rounded p-2 text-red-700 text-sm dark:bg-red-500/10 dark:border-red-500/30 dark:text-red-300">
            Failed to generate summary. Ensure meetings exist in the selected range.
          </div>
        )}
      </div>

      {/* Results */}
      {meetingResults && (
        <div className="space-y-4">
          {meetingResults.length === 0 && <p className="text-gray-400 dark:text-gray-500 text-sm">No meeting summaries in this range.</p>}
          {meetingResults.map((m) => (
            <div key={m.standup_id} className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-5">
              <div className="flex items-center justify-between mb-2">
                <h3 className="font-semibold text-gray-900 dark:text-gray-100">{m.name}</h3>
                <span className="text-xs text-gray-400 dark:text-gray-500">{m.date}</span>
              </div>
              <Md text={m.rollup_markdown} />
            </div>
          ))}
        </div>
      )}

      {aggregateResults && (
        <div className="space-y-4">
          {aggregateResults.length === 0 && <p className="text-gray-400 dark:text-gray-500 text-sm">Nothing to summarize in this range.</p>}
          {aggregateResults.map((a) => (
            <div key={a.id} className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-5">
              <div className="flex items-center justify-between mb-2">
                <h3 className="font-semibold text-gray-900 dark:text-gray-100 capitalize">
                  {a.scope} · {a.bucket_key}
                </h3>
                <span className="text-xs text-gray-400 dark:text-gray-500">{a.range_start} → {a.range_end}</span>
              </div>
              <Md text={a.rollup_markdown} />
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

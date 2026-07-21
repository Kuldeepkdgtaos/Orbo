import ReactMarkdown from 'react-markdown'
import { StandupSummary, ParticipantSummary, Participant } from '../api/client'

interface Props {
  summary: StandupSummary | null
  participantSummaries: ParticipantSummary[]
  participants: Participant[]
}

function stripCodeFence(text: string): string {
  return text
    .replace(/^```(?:markdown)?\s*/i, '')
    .replace(/\s*```\s*$/, '')
    .trim()
}

const mdComponents = {
  h1: ({ children }: any) => <h1 className="text-lg font-bold text-gray-900 dark:text-gray-100 mt-4 mb-2 first:mt-0">{children}</h1>,
  h2: ({ children }: any) => <h2 className="text-base font-bold text-gray-900 dark:text-gray-100 mt-4 mb-2 first:mt-0">{children}</h2>,
  h3: ({ children }: any) => <h3 className="text-sm font-bold text-gray-800 dark:text-gray-200 mt-3 mb-1.5 first:mt-0">{children}</h3>,
  h4: ({ children }: any) => <h4 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mt-2 mb-1">{children}</h4>,
  p: ({ children }: any) => <p className="text-sm text-gray-700 dark:text-gray-300 mb-2 leading-relaxed">{children}</p>,
  ul: ({ children }: any) => <ul className="list-disc list-inside space-y-1 mb-2 text-sm text-gray-700 dark:text-gray-300">{children}</ul>,
  ol: ({ children }: any) => <ol className="list-decimal list-inside space-y-1 mb-2 text-sm text-gray-700 dark:text-gray-300">{children}</ol>,
  li: ({ children }: any) => <li className="text-sm text-gray-700 dark:text-gray-300 leading-relaxed">{children}</li>,
  strong: ({ children }: any) => <strong className="font-semibold text-gray-900 dark:text-gray-100">{children}</strong>,
  hr: () => <hr className="my-3 border-gray-200 dark:border-gray-700" />,
}

export default function SummaryPanel({ summary, participantSummaries, participants }: Props) {
  const participantMap = Object.fromEntries(participants.map(p => [p.id, p]))

  if (!summary) {
    return <p className="text-gray-400 dark:text-gray-500 text-sm">Summary not yet generated.</p>
  }

  const cleanMarkdown = stripCodeFence(summary.rollup_markdown)

  return (
    <div className="space-y-6">
      {/* Executive Rollup */}
      <div className="bg-gray-50 dark:bg-gray-800/50 rounded-xl border border-gray-200 dark:border-gray-700 p-5">
        <h3 className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-3">Executive Rollup</h3>
        <ReactMarkdown components={mdComponents}>{cleanMarkdown}</ReactMarkdown>
      </div>

      {/* Per-Person Summaries */}
      {participantSummaries.length > 0 && (
        <div>
          <h3 className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-3">Per-Person Summaries</h3>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {participantSummaries.map((ps) => {
              const p = participantMap[ps.participant_id]
              return (
                <div key={ps.id} className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4 space-y-2">
                  <div className="flex items-center gap-2">
                    <div className="w-7 h-7 rounded-full bg-blue-100 dark:bg-blue-500/20 flex items-center justify-center text-blue-700 dark:text-blue-300 font-bold text-xs shrink-0">
                      {(p?.name ?? '?')[0]}
                    </div>
                    <div>
                      <div className="flex items-center gap-1.5">
                        <span className="font-semibold text-sm text-gray-900 dark:text-gray-100">{p?.name ?? 'Unknown'}</span>
                        {p?.is_manager && (
                          <span className="inline-flex items-center px-1.5 py-0.5 rounded text-xs font-medium bg-indigo-50 text-indigo-700 border border-indigo-200 dark:bg-indigo-500/15 dark:text-indigo-300 dark:border-indigo-500/30">
                            Manager
                          </span>
                        )}
                      </div>
                      {(p?.designation || p?.department) && (
                        <div className="text-xs text-gray-400 dark:text-gray-500">
                          {[p?.designation, p?.department].filter(Boolean).join(' · ')}
                        </div>
                      )}
                    </div>
                  </div>
                  <div className="space-y-2 text-sm">
                    {ps.yesterday && (
                      <div>
                        <span className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase">Yesterday</span>
                        <p className="text-gray-700 dark:text-gray-300 mt-0.5">{ps.yesterday}</p>
                      </div>
                    )}
                    {ps.today && (
                      <div>
                        <span className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase">Today</span>
                        <p className="text-gray-700 dark:text-gray-300 mt-0.5">{ps.today}</p>
                      </div>
                    )}
                    {ps.blockers && (
                      <div>
                        <span className="text-xs font-semibold text-red-500 dark:text-red-400 uppercase">Blockers</span>
                        <p className="text-red-700 dark:text-red-400 mt-0.5">{ps.blockers}</p>
                      </div>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}

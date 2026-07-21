import { Link } from 'react-router-dom'
import { StandupListItem } from '../api/client'
import StatusBadge from './StatusBadge'
import { useDomain } from '../hooks/useDomain'

interface Props {
  standup: StandupListItem
}

export default function StandupCard({ standup }: Props) {
  const domain = useDomain()
  const formattedDate = standup.created_at
    ? new Date(standup.created_at).toLocaleString()
    : '—'

  return (
    <Link
      to={`/${domain}/meetings/${standup.id}`}
      className="block bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-4 hover:border-blue-400 dark:hover:border-blue-500 hover:shadow-sm transition-all"
    >
      <div className="flex items-start justify-between">
        <div>
          <h3 className="font-semibold text-gray-900 dark:text-gray-100">{standup.name}</h3>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">{standup.team_name}</p>
        </div>
        <StatusBadge status={standup.status} />
      </div>
      <div className="mt-3 flex items-center gap-4 text-xs text-gray-500 dark:text-gray-400">
        <span>{standup.participant_count} participant{standup.participant_count !== 1 ? 's' : ''}</span>
        <span>{formattedDate}</span>
      </div>
    </Link>
  )
}

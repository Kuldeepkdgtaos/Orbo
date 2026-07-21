import { Link } from 'react-router-dom'
import { TemplateListItem } from '../api/client'
import { Repeat, Users } from 'lucide-react'
import { useDomain } from '../hooks/useDomain'

interface Props {
  template: TemplateListItem
}

export default function TemplateCard({ template }: Props) {
  const domain = useDomain()
  const formattedDate = new Date(template.created_at).toLocaleDateString()

  return (
    <Link
      to={`/${domain}/templates/${template.id}`}
      className="block bg-white dark:bg-gray-800 rounded-lg border border-blue-200 dark:border-gray-700 p-4 hover:border-blue-400 dark:hover:border-blue-500 hover:shadow-sm transition-all"
    >
      <div className="flex items-start justify-between mb-2">
        <div className="flex-1 min-w-0">
          <h3 className="font-semibold text-gray-900 dark:text-gray-100 truncate">{template.name}</h3>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">{template.team_name}</p>
        </div>
        <span className="ml-2 inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-blue-50 text-blue-700 border border-blue-200 dark:bg-blue-500/15 dark:text-blue-300 dark:border-blue-500/30 shrink-0">
          <Repeat size={10} />
          Recurring
        </span>
      </div>
      <div className="flex items-center gap-4 text-xs text-gray-500 dark:text-gray-400 mt-3">
        <span className="flex items-center gap-1">
          <Users size={12} />
          {template.participant_count} participant{template.participant_count !== 1 ? 's' : ''}
        </span>
        <span>{template.session_count} session{template.session_count !== 1 ? 's' : ''} run</span>
        <span>{formattedDate}</span>
      </div>
    </Link>
  )
}

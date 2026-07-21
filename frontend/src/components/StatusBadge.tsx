const STATUS_STYLES: Record<string, string> = {
  idle: 'bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300',
  dispatched: 'bg-yellow-100 text-yellow-700 dark:bg-yellow-500/15 dark:text-yellow-300',
  in_progress: 'bg-blue-100 text-blue-700 dark:bg-blue-500/15 dark:text-blue-300',
  completed: 'bg-green-100 text-green-700 dark:bg-green-500/15 dark:text-green-300',
  failed: 'bg-red-100 text-red-700 dark:bg-red-500/15 dark:text-red-300',
}

interface Props {
  status: string
}

export default function StatusBadge({ status }: Props) {
  const styles = STATUS_STYLES[status] || 'bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300'
  return (
    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${styles}`}>
      {status.replace('_', ' ')}
    </span>
  )
}

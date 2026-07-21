import { useEffect, useState } from 'react'
import StatusBadge from './StatusBadge'

interface StateEvent {
  from_state: string | null
  to_state: string
  event: string
  occurred_at: string
}

interface Props {
  standupId: string
}

export default function LiveStatusStream({ standupId }: Props) {
  const [events, setEvents] = useState<StateEvent[]>([])
  const [connected, setConnected] = useState(false)

  useEffect(() => {
    // The /stream endpoint is auth-exempt (EventSource can't send headers), so
    // no token is attached here.
    const url = `/api/standups/${standupId}/stream`
    const es = new EventSource(url)

    es.onopen = () => setConnected(true)
    es.onerror = () => setConnected(false)

    es.addEventListener('state_transition', (e) => {
      const data: StateEvent = JSON.parse(e.data)
      setEvents((prev) => [...prev, data])
    })

    return () => es.close()
  }, [standupId])

  return (
    <div>
      <div className="flex items-center gap-2 mb-3">
        <span className={`w-2 h-2 rounded-full ${connected ? 'bg-green-500' : 'bg-gray-400'}`} />
        <span className="text-xs text-gray-500 dark:text-gray-400">{connected ? 'Live' : 'Disconnected'}</span>
      </div>
      {events.length === 0 ? (
        <p className="text-sm text-gray-400 dark:text-gray-500">Waiting for events…</p>
      ) : (
        <div className="space-y-2 max-h-48 overflow-y-auto">
          {events.map((e, i) => (
            <div key={i} className="flex items-center gap-2 text-xs text-gray-600 dark:text-gray-400">
              <span className="text-gray-400 dark:text-gray-500">{new Date(e.occurred_at).toLocaleTimeString()}</span>
              <span className="text-gray-400 dark:text-gray-500">{e.event}</span>
              <span>→</span>
              <StatusBadge status={e.to_state} />
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

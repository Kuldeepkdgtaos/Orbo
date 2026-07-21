import { Utterance, Participant } from '../api/client'

interface Props {
  utterances: Utterance[]
  participants: Participant[]
}

function formatTime(iso: string) {
  return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

export default function TranscriptViewer({ utterances }: Props) {

  if (!utterances.length) {
    return <p className="text-gray-400 dark:text-gray-500 text-sm">No transcript yet.</p>
  }

  const grouped: { speaker: string; items: Utterance[] }[] = []
  for (const utt of utterances) {
    const last = grouped[grouped.length - 1]
    if (last && last.speaker === utt.speaker_label) {
      last.items.push(utt)
    } else {
      grouped.push({ speaker: utt.speaker_label, items: [utt] })
    }
  }

  return (
    <div className="space-y-4 max-h-96 overflow-y-auto pr-2">
      {grouped.map((group, i) => (
        <div key={i} className="flex gap-3">
          <div className="w-8 h-8 rounded-full bg-blue-100 dark:bg-blue-500/20 flex items-center justify-center text-blue-700 dark:text-blue-300 font-bold text-sm shrink-0 mt-0.5">
            {group.speaker[0]?.toUpperCase() ?? '?'}
          </div>
          <div>
            <div className="flex items-center gap-2 mb-1">
              <span className="font-medium text-sm dark:text-gray-100">{group.speaker}</span>
              <span className="text-xs text-gray-400 dark:text-gray-500">{formatTime(group.items[0].started_at)}</span>
              {!group.items[0].participant_id && (
                <span className="text-xs bg-yellow-100 text-yellow-700 dark:bg-yellow-500/15 dark:text-yellow-300 px-1.5 py-0.5 rounded">unattributed</span>
              )}
            </div>
            <div className="space-y-1">
              {group.items.map((utt) => (
                <p key={utt.id} className="text-sm text-gray-700 dark:text-gray-300">{utt.text}</p>
              ))}
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}

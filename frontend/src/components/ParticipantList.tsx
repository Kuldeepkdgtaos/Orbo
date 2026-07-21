import { ParticipantInput } from '../api/client'
import { Trash2, UserPlus } from 'lucide-react'

interface Props {
  participants: ParticipantInput[]
  onChange: (participants: ParticipantInput[]) => void
}

export default function ParticipantList({ participants, onChange }: Props) {
  const add = () => {
    onChange([
      ...participants,
      { name: '', email: '', teams_display_name: '', order_index: participants.length },
    ])
  }

  const remove = (idx: number) => {
    const updated = participants
      .filter((_, i) => i !== idx)
      .map((p, i) => ({ ...p, order_index: i }))
    onChange(updated)
  }

  const update = (idx: number, field: keyof ParticipantInput, value: string | number) => {
    const updated = participants.map((p, i) =>
      i === idx ? { ...p, [field]: value } : p
    )
    onChange(updated)
  }

  return (
    <div>
      <div className="space-y-4">
        {participants.map((p, idx) => (
          <div key={idx} className="rounded-lg border border-gray-100 bg-gray-50 dark:border-gray-700 dark:bg-gray-800/50 p-3 space-y-2">
            {/* Required row */}
            <div className="grid grid-cols-3 gap-2 items-start">
              <input
                type="text"
                placeholder="Full Name"
                value={p.name}
                onChange={(e) => update(idx, 'name', e.target.value)}
                className="input-field"
                required
              />
              <input
                type="email"
                placeholder="Email"
                value={p.email}
                onChange={(e) => update(idx, 'email', e.target.value)}
                className="input-field"
                required
              />
              <div className="flex gap-2">
                <input
                  type="text"
                  placeholder="Teams Display Name"
                  value={p.teams_display_name}
                  onChange={(e) => update(idx, 'teams_display_name', e.target.value)}
                  className="input-field flex-1"
                  required
                />
                <button
                  type="button"
                  onClick={() => remove(idx)}
                  className="p-2 text-red-400 hover:bg-red-50 rounded-md"
                  disabled={participants.length <= 1}
                >
                  <Trash2 size={15} />
                </button>
              </div>
            </div>
            {/* Optional metadata row */}
            <div className="grid grid-cols-2 gap-2">
              <input
                type="text"
                placeholder="Designation (optional, e.g. Senior Engineer)"
                value={p.designation ?? ''}
                onChange={(e) => update(idx, 'designation', e.target.value)}
                className="input-field text-xs text-gray-500 placeholder:text-gray-400"
              />
              <input
                type="text"
                placeholder="Department (optional, e.g. Platform)"
                value={p.department ?? ''}
                onChange={(e) => update(idx, 'department', e.target.value)}
                className="input-field text-xs text-gray-500 placeholder:text-gray-400"
              />
            </div>
            {/* Manager toggle — single-select: checking one unchecks all others */}
            <label className="flex items-center gap-2 cursor-pointer w-fit">
              <input
                type="checkbox"
                checked={p.is_manager ?? false}
                onChange={(e) => {
                  const updated = participants.map((p2, i2) =>
                    i2 === idx
                      ? { ...p2, is_manager: e.target.checked }
                      : { ...p2, is_manager: false }
                  )
                  onChange(updated)
                }}
                className="w-3.5 h-3.5 accent-indigo-600"
              />
              <span className="text-xs text-indigo-700 dark:text-indigo-300 font-medium">
                Team Manager — digest is written for this person
              </span>
            </label>
          </div>
        ))}
      </div>
      <button
        type="button"
        onClick={add}
        className="mt-3 flex items-center gap-1.5 text-sm text-blue-600 hover:text-blue-800"
      >
        <UserPlus size={15} />
        Add participant
      </button>
    </div>
  )
}

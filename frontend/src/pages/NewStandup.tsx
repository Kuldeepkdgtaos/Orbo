import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api, ParticipantInput, StandupCreateInput } from '../api/client'
import ParticipantList from '../components/ParticipantList'
import { useDomain } from '../hooks/useDomain'

export default function NewStandup() {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const domain = useDomain()
  const noun = domain === 'project' ? 'Project Meeting' : 'Standup'
  const [name, setName] = useState('')
  const [teamName, setTeamName] = useState('')
  const [meetingUrl, setMeetingUrl] = useState('')
  const [recipients, setRecipients] = useState('')
  const [participants, setParticipants] = useState<ParticipantInput[]>([
    { name: '', email: '', teams_display_name: '', order_index: 0 },
  ])

  const mutation = useMutation({
    mutationFn: (data: StandupCreateInput) => api.standups.create(data),
    onSuccess: (standup) => {
      qc.invalidateQueries({ queryKey: ['standups', domain] })
      navigate(`/${domain}/meetings/${standup.id}`)
    },
  })

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const data: StandupCreateInput = {
      name,
      team_name: teamName,
      meeting_url: meetingUrl,
      domain,
      management_recipients: recipients.split(',').map(r => r.trim()).filter(Boolean),
      participants,
    }
    mutation.mutate(data)
  }

  return (
    <div className="max-w-2xl">
      <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100 mb-6">New {noun}</h1>
      <form onSubmit={handleSubmit} className="space-y-6">
        <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-5 space-y-4">
          <h2 className="font-semibold text-gray-800 dark:text-gray-200">Meeting Details</h2>
          <div>
            <label className="label">Standup Name</label>
            <input
              className="input-field"
              type="text"
              value={name}
              onChange={e => setName(e.target.value)}
              placeholder="Daily Standup — Platform Team"
              required
            />
          </div>
          <div>
            <label className="label">Team Name</label>
            <input
              className="input-field"
              type="text"
              value={teamName}
              onChange={e => setTeamName(e.target.value)}
              placeholder="Platform Engineering"
              required
            />
          </div>
          <div>
            <label className="label">Meeting URL</label>
            <input
              className="input-field"
              type="url"
              value={meetingUrl}
              onChange={e => setMeetingUrl(e.target.value)}
              placeholder="https://teams.microsoft.com/l/meetup-join/..."
              required
            />
          </div>
          <div>
            <label className="label">Management Recipients (comma-separated emails)</label>
            <input
              className="input-field"
              type="text"
              value={recipients}
              onChange={e => setRecipients(e.target.value)}
              placeholder="manager@company.com, vp@company.com"
            />
          </div>
        </div>

        <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-5">
          <h2 className="font-semibold text-gray-800 dark:text-gray-200 mb-4">Participants</h2>
          <p className="text-xs text-gray-500 dark:text-gray-400 mb-3">
            Teams Display Name must exactly match the name shown in the meeting. Used for transcript attribution.
          </p>
          <ParticipantList participants={participants} onChange={setParticipants} />
        </div>

        {mutation.error && (
          <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-red-700 text-sm dark:bg-red-500/10 dark:border-red-500/30 dark:text-red-300">
            {String(mutation.error)}
          </div>
        )}

        <div className="flex gap-3">
          <button type="submit" disabled={mutation.isPending} className="btn-primary">
            {mutation.isPending ? 'Creating…' : `Create ${noun}`}
          </button>
          <button type="button" onClick={() => navigate(`/${domain}/meetings`)} className="btn-secondary">
            Cancel
          </button>
        </div>
      </form>
    </div>
  )
}

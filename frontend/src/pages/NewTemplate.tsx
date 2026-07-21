import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api, TemplateParticipantInput, TemplateCreateInput } from '../api/client'
import ParticipantList from '../components/ParticipantList'
import { useDomain } from '../hooks/useDomain'

export default function NewTemplate() {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const domain = useDomain()
  const [name, setName] = useState('')
  const [teamName, setTeamName] = useState('')
  const [meetingUrl, setMeetingUrl] = useState('')
  const [recipients, setRecipients] = useState('')
  const [participants, setParticipants] = useState<TemplateParticipantInput[]>([
    { name: '', email: '', teams_display_name: '', order_index: 0 },
  ])

  const mutation = useMutation({
    mutationFn: (data: TemplateCreateInput) => api.templates.create(data),
    onSuccess: (template) => {
      qc.invalidateQueries({ queryKey: ['templates', domain] })
      navigate(`/${domain}/templates/${template.id}`)
    },
  })

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const data: TemplateCreateInput = {
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
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">New Recurring Standup</h1>
        <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
          Configure once — start a new session each day with one click.
        </p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-6">
        <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-5 space-y-4">
          <h2 className="font-semibold text-gray-800 dark:text-gray-200">Meeting Details</h2>
          <div>
            <label className="label">Template Name</label>
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
            <p className="text-xs text-gray-400 mt-1">
              Use your recurring Teams meeting link — it stays the same every day.
            </p>
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
          <h2 className="font-semibold text-gray-800 dark:text-gray-200 mb-1">Participants</h2>
          <p className="text-xs text-gray-500 dark:text-gray-400 mb-4">
            Teams Display Name must match exactly what appears in the meeting.
            Designation and department help AI generate richer summaries.
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
            {mutation.isPending ? 'Creating…' : 'Create Template'}
          </button>
          <button type="button" onClick={() => navigate(`/${domain}/meetings`)} className="btn-secondary">
            Cancel
          </button>
        </div>
      </form>
    </div>
  )
}

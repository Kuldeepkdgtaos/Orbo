import axios, { AxiosInstance } from 'axios'
import { useSettingsStore } from '../stores/settings'

const BASE_URL = '/api'

function createClient(): AxiosInstance {
  const instance = axios.create({ baseURL: BASE_URL })

  // Attach the JWT bearer token to every request.
  instance.interceptors.request.use((config) => {
    const token = useSettingsStore.getState().token
    if (token) {
      config.headers['Authorization'] = `Bearer ${token}`
    }
    return config
  })

  // On 401 (except from the auth endpoints themselves), drop the session and
  // bounce to the login page.
  instance.interceptors.response.use(
    (res) => res,
    (error) => {
      const url: string = error?.config?.url ?? ''
      const isAuthCall = url.includes('/auth/login') || url.includes('/auth/register')
      if (error?.response?.status === 401 && !isAuthCall) {
        useSettingsStore.getState().clearAuth()
        if (!window.location.pathname.startsWith('/login')) {
          window.location.href = '/login'
        }
      }
      return Promise.reject(error)
    }
  )
  return instance
}

const client = createClient()

// ── Auth types ─────────────────────────────────────────────────────────────

export interface AuthUser {
  id: string
  email: string
  dataentry_schema: string
  created_at?: string
}

export interface TokenResponse {
  access_token: string
  token_type: string
  user: AuthUser
}

// ── Types ────────────────────────────────────────────────────────────────────

export type Domain = 'standup' | 'project'

export interface Participant {
  id: string
  standup_id: string
  name: string
  email: string
  teams_display_name: string
  order_index: number
  designation: string | null
  department: string | null
  is_manager: boolean
}

export interface Standup {
  id: string
  name: string
  team_name: string
  meeting_url: string
  domain: string
  status: string
  scheduled_at: string | null
  started_at: string | null
  ended_at: string | null
  recall_bot_id: string | null
  management_recipients: string[]
  template_id: string | null
  session_number: number | null
  created_at: string
  updated_at: string
  participants: Participant[]
}

export interface StandupListItem {
  id: string
  name: string
  team_name: string
  domain: string
  status: string
  scheduled_at: string | null
  started_at: string | null
  ended_at: string | null
  created_at: string
  participant_count: number
  template_id: string | null
  session_number: number | null
}

export interface ParticipantInput {
  name: string
  email: string
  teams_display_name: string
  order_index: number
  designation?: string
  department?: string
  is_manager?: boolean
}

export interface StandupCreateInput {
  name: string
  team_name: string
  meeting_url: string
  domain: Domain
  scheduled_at?: string
  management_recipients: string[]
  participants: ParticipantInput[]
}

export interface Utterance {
  id: string
  standup_id: string
  participant_id: string | null
  speaker_label: string
  text: string
  started_at: string
  ended_at: string
  confidence: number | null
  created_at: string
}

export interface ParticipantSummary {
  id: string
  standup_id: string
  participant_id: string
  yesterday: string
  today: string
  blockers: string
  model: string
  created_at: string
}

export interface StandupSummary {
  id: string
  standup_id: string
  rollup_markdown: string
  key_blockers: string[]
  key_wins: string[]
  model: string
  created_at: string
}

export interface StateTransition {
  id: number
  standup_id: string
  from_state: string | null
  to_state: string
  event: string
  occurred_at: string
}

// ── Template types ────────────────────────────────────────────────────────────

export interface TemplateParticipant {
  id: string
  template_id: string
  name: string
  email: string
  teams_display_name: string
  order_index: number
  designation: string | null
  department: string | null
  is_manager: boolean
}

export interface Template {
  id: string
  name: string
  team_name: string
  meeting_url: string
  domain: string
  management_recipients: string[]
  created_at: string
  updated_at: string
  participants: TemplateParticipant[]
}

export interface TemplateListItem {
  id: string
  name: string
  team_name: string
  domain: string
  created_at: string
  participant_count: number
  session_count: number
}

export interface TemplateParticipantInput {
  name: string
  email: string
  teams_display_name: string
  order_index: number
  designation?: string
  department?: string
  is_manager?: boolean
}

export interface TemplateCreateInput {
  name: string
  team_name: string
  meeting_url: string
  domain: Domain
  management_recipients: string[]
  participants: TemplateParticipantInput[]
}

// ── Data Entry types ──────────────────────────────────────────────────────────

export type DataEntryColumnType = 'text' | 'number' | 'boolean' | 'date' | 'timestamp'

export interface DataEntryColumn {
  id: string
  physical_name: string
  display_name: string
  data_type: string
  order_index: number
}

export interface DataEntryTable {
  id: string
  physical_name: string
  display_name: string
  domain: string
  created_at: string
  columns: DataEntryColumn[]
}

export interface DataEntryRow {
  id: string
  created_at: string
  [physicalCol: string]: unknown
}

// ── Insights types ────────────────────────────────────────────────────────────

export type Scope = 'call' | 'individual' | 'project' | 'overall'
export type Granularity = 'overall' | 'weekly' | 'monthly'

export interface AggregateRequestInput {
  domain: Domain
  scope: Scope
  granularity: Granularity
  range_start: string
  range_end: string
  subject_id?: string
  dataentry_table_ids?: string[]
  force?: boolean
}

export interface AggregateSummary {
  id: string
  domain: string
  scope: string
  granularity: string
  range_start: string
  range_end: string
  subject_type: string
  subject_id: string | null
  bucket_key: string
  rollup_markdown: string
  key_points: string[]
  data_entry_refs: string[]
  model: string
  prompt_version: string
  created_at: string
  updated_at: string
}

export interface MeetingSummaryItem {
  standup_id: string
  name: string
  team_name: string
  date: string
  rollup_markdown: string
  key_wins: string[]
  key_blockers: string[]
}

// ── API functions ─────────────────────────────────────────────────────────────

export const api = {
  auth: {
    register: (email: string, password: string) =>
      client.post<TokenResponse>('/auth/register', { email, password }).then(r => r.data),
    login: (email: string, password: string) =>
      client.post<TokenResponse>('/auth/login', { email, password }).then(r => r.data),
    me: () => client.get<AuthUser>('/auth/me').then(r => r.data),
  },
  standups: {
    list: (domain?: Domain) =>
      client.get<StandupListItem[]>('/standups', { params: domain ? { domain } : {} }).then(r => r.data),
    get: (id: string) => client.get<Standup>(`/standups/${id}`).then(r => r.data),
    create: (data: StandupCreateInput) => client.post<Standup>('/standups', data).then(r => r.data),
    start: (id: string) => client.post(`/standups/${id}/start`).then(r => r.data),
    resendEmail: (id: string) => client.post(`/standups/${id}/resend-email`).then(r => r.data),
    excelUrl: (id: string) => `${BASE_URL}/standups/${id}/excel`,
  },
  templates: {
    list: (domain?: Domain) =>
      client.get<TemplateListItem[]>('/templates', { params: domain ? { domain } : {} }).then(r => r.data),
    get: (id: string) => client.get<Template>(`/templates/${id}`).then(r => r.data),
    create: (data: TemplateCreateInput) => client.post<Template>('/templates', data).then(r => r.data),
    startSession: (id: string) => client.post<Standup>(`/templates/${id}/start-session`).then(r => r.data),
    sessions: (id: string) => client.get<StandupListItem[]>(`/templates/${id}/sessions`).then(r => r.data),
  },
  utterances: {
    list: (standupId: string) =>
      client.get<Utterance[]>(`/standups/${standupId}/utterances`).then(r => r.data),
  },
  summary: {
    get: (standupId: string) =>
      client.get<StandupSummary>(`/standups/${standupId}/summary`).then(r => r.data),
    regenerate: (standupId: string) =>
      client.post(`/standups/${standupId}/regenerate`).then(r => r.data),
    participantSummaries: (standupId: string) =>
      client.get<ParticipantSummary[]>(`/standups/${standupId}/participant-summaries`).then(r => r.data),
  },
  dataentry: {
    listTables: (domain?: Domain) =>
      client.get<DataEntryTable[]>('/dataentry/tables', { params: domain ? { domain } : {} }).then(r => r.data),
    getTable: (id: string) =>
      client.get<DataEntryTable>(`/dataentry/tables/${id}`).then(r => r.data),
    createTable: (payload: { display_name: string; domain: Domain; columns: { display_name: string; data_type: DataEntryColumnType }[] }) =>
      client.post<DataEntryTable>('/dataentry/tables', payload).then(r => r.data),
    renameTable: (id: string, display_name: string) =>
      client.patch<DataEntryTable>(`/dataentry/tables/${id}`, { display_name }).then(r => r.data),
    deleteTable: (id: string) => client.delete(`/dataentry/tables/${id}`).then(r => r.data),
    addColumn: (id: string, payload: { display_name: string; data_type: DataEntryColumnType }) =>
      client.post<DataEntryTable>(`/dataentry/tables/${id}/columns`, payload).then(r => r.data),
    dropColumn: (id: string, columnId: string) =>
      client.delete<DataEntryTable>(`/dataentry/tables/${id}/columns/${columnId}`).then(r => r.data),
    listRows: (id: string) =>
      client.get<DataEntryRow[]>(`/dataentry/tables/${id}/rows`).then(r => r.data),
    insertRow: (id: string, values: Record<string, unknown>) =>
      client.post<{ id: string }>(`/dataentry/tables/${id}/rows`, { values }).then(r => r.data),
    updateRow: (id: string, rowId: string, values: Record<string, unknown>) =>
      client.patch(`/dataentry/tables/${id}/rows/${rowId}`, { values }).then(r => r.data),
    deleteRow: (id: string, rowId: string) =>
      client.delete(`/dataentry/tables/${id}/rows/${rowId}`).then(r => r.data),
  },
  insights: {
    meetings: (params: { domain: Domain; range_start: string; range_end: string; subject_id?: string }) =>
      client.get<MeetingSummaryItem[]>('/insights/meetings', { params }).then(r => r.data),
    aggregate: (payload: AggregateRequestInput) =>
      client.post<AggregateSummary[]>('/insights/aggregate', payload).then(r => r.data),
  },
}

export { client }

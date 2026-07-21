import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Plus, Trash2, X, Menu as MenuIcon, ChevronRight, ChevronDown,
  Table2, Columns3, Eye, Pencil,
} from 'lucide-react'
import { api, DataEntryColumnType, DataEntryTable } from '../api/client'
import { useDomain, Domain } from '../hooks/useDomain'

const COLUMN_TYPES: DataEntryColumnType[] = ['text', 'number', 'boolean', 'date', 'timestamp']

// ── New-table form ───────────────────────────────────────────────────────────

function NewTableForm({ domain, onClose }: { domain: Domain; onClose: () => void }) {
  const qc = useQueryClient()
  const [name, setName] = useState('')
  const [columns, setColumns] = useState<{ display_name: string; data_type: DataEntryColumnType }[]>([
    { display_name: '', data_type: 'text' },
  ])

  const create = useMutation({
    mutationFn: () =>
      api.dataentry.createTable({
        display_name: name,
        domain,
        columns: columns.filter((c) => c.display_name.trim()),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['dataentry-tables', domain] })
      onClose()
    },
  })

  return (
    <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-5 space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="font-semibold text-gray-800 dark:text-gray-200">New Table</h2>
        <button onClick={onClose} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"><X size={18} /></button>
      </div>
      <div>
        <label className="label">Table name</label>
        <input className="input-field" value={name} onChange={(e) => setName(e.target.value)}
          placeholder="Sprint Tasks" autoFocus />
      </div>
      <div className="space-y-2">
        <label className="label">Columns</label>
        {columns.map((c, i) => (
          <div key={i} className="flex gap-2">
            <input className="input-field flex-1" value={c.display_name} placeholder="Column name"
              onChange={(e) => setColumns((cs) => cs.map((x, j) => j === i ? { ...x, display_name: e.target.value } : x))} />
            <select className="input-field w-36" value={c.data_type}
              onChange={(e) => setColumns((cs) => cs.map((x, j) => j === i ? { ...x, data_type: e.target.value as DataEntryColumnType } : x))}>
              {COLUMN_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
            <button type="button" className="text-gray-400 hover:text-red-500 px-1"
              onClick={() => setColumns((cs) => cs.filter((_, j) => j !== i))}>
              <Trash2 size={16} />
            </button>
          </div>
        ))}
        <button type="button" className="text-blue-600 dark:text-blue-400 text-sm hover:underline"
          onClick={() => setColumns((cs) => [...cs, { display_name: '', data_type: 'text' }])}>
          + Add column
        </button>
      </div>
      {create.isError && (
        <div className="bg-red-50 border border-red-200 rounded p-2 text-red-700 text-sm dark:bg-red-500/10 dark:border-red-500/30 dark:text-red-300">Failed to create table.</div>
      )}
      <div className="flex gap-2">
        <button className="btn-primary" disabled={!name.trim() || create.isPending} onClick={() => create.mutate()}>
          {create.isPending ? 'Creating…' : 'Create Table'}
        </button>
        <button className="btn-secondary" onClick={onClose}>Cancel</button>
      </div>
    </div>
  )
}

// ── One table row (expandable details + three-line menu) ─────────────────────

function TableRow({ table, domain }: { table: DataEntryTable; domain: Domain }) {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [expanded, setExpanded] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)
  const [renaming, setRenaming] = useState(false)
  const [renameValue, setRenameValue] = useState(table.display_name)
  const [addingCol, setAddingCol] = useState(false)
  const [newColName, setNewColName] = useState('')
  const [newColType, setNewColType] = useState<DataEntryColumnType>('text')

  const invalidate = () => qc.invalidateQueries({ queryKey: ['dataentry-tables', domain] })

  const rename = useMutation({
    mutationFn: () => api.dataentry.renameTable(table.id, renameValue),
    onSuccess: () => { setRenaming(false); invalidate() },
  })
  const remove = useMutation({
    mutationFn: () => api.dataentry.deleteTable(table.id),
    onSuccess: invalidate,
  })
  const addColumn = useMutation({
    mutationFn: () => api.dataentry.addColumn(table.id, { display_name: newColName, data_type: newColType }),
    onSuccess: () => { setNewColName(''); setAddingCol(false); invalidate() },
  })
  const dropColumn = useMutation({
    mutationFn: (colId: string) => api.dataentry.dropColumn(table.id, colId),
    onSuccess: invalidate,
  })

  const openDetails = () => setExpanded((v) => !v)

  return (
    <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700">
      {/* Header row */}
      <div className="flex items-center gap-2 px-4 py-3">
        <button className="flex items-center gap-2 flex-1 text-left min-w-0" onClick={openDetails}>
          {expanded ? <ChevronDown size={16} className="text-gray-400 shrink-0" /> : <ChevronRight size={16} className="text-gray-400 shrink-0" />}
          <Table2 size={16} className="text-blue-600 dark:text-blue-400 shrink-0" />
          <span className="font-medium text-gray-900 dark:text-gray-100 truncate">{table.display_name}</span>
          <span className="text-xs text-gray-400 dark:text-gray-500 shrink-0">
            {table.columns.length} column{table.columns.length !== 1 ? 's' : ''}
          </span>
        </button>

        {/* Three-line menu */}
        <div className="relative shrink-0">
          <button className="p-1.5 rounded-md text-gray-500 hover:bg-gray-100 dark:text-gray-400 dark:hover:bg-gray-700"
            onClick={() => setMenuOpen((v) => !v)} aria-label="Table actions">
            <MenuIcon size={16} />
          </button>
          {menuOpen && (
            <>
              <div className="fixed inset-0 z-10" onClick={() => setMenuOpen(false)} />
              <div className="absolute right-0 mt-1 w-44 z-20 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-md shadow-lg py-1 text-sm">
                <button className="w-full flex items-center gap-2 px-3 py-2 text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-700"
                  onClick={() => { setMenuOpen(false); navigate(`/${domain}/data-entry/${table.id}`) }}>
                  <Eye size={14} /> View data
                </button>
                <button className="w-full flex items-center gap-2 px-3 py-2 text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-700"
                  onClick={() => { setMenuOpen(false); setExpanded(true); setAddingCol(true) }}>
                  <Columns3 size={14} /> Add column
                </button>
                <button className="w-full flex items-center gap-2 px-3 py-2 text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-700"
                  onClick={() => { setMenuOpen(false); setRenaming(true); setRenameValue(table.display_name) }}>
                  <Pencil size={14} /> Rename table
                </button>
                <button className="w-full flex items-center gap-2 px-3 py-2 text-red-600 dark:text-red-400 hover:bg-gray-100 dark:hover:bg-gray-700"
                  onClick={() => { setMenuOpen(false); if (confirm(`Delete table "${table.display_name}"? This drops all its data.`)) remove.mutate() }}>
                  <Trash2 size={14} /> Delete table
                </button>
              </div>
            </>
          )}
        </div>
      </div>

      {/* Rename inline */}
      {renaming && (
        <div className="flex gap-2 px-4 pb-3">
          <input className="input-field flex-1" value={renameValue} autoFocus
            onChange={(e) => setRenameValue(e.target.value)} />
          <button className="btn-primary" disabled={!renameValue.trim() || rename.isPending} onClick={() => rename.mutate()}>Save</button>
          <button className="btn-secondary" onClick={() => setRenaming(false)}>Cancel</button>
        </div>
      )}

      {/* Expanded details */}
      {expanded && (
        <div className="border-t border-gray-100 dark:border-gray-700 px-4 py-3 space-y-3">
          <h3 className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide">Columns</h3>
          {table.columns.length === 0 && <p className="text-sm text-gray-400 dark:text-gray-500">No columns yet.</p>}
          <ul className="space-y-1.5">
            {table.columns.map((col) => (
              <li key={col.id} className="flex items-center gap-2 text-sm">
                <span className="text-gray-800 dark:text-gray-200">{col.display_name}</span>
                <span className="text-xs px-1.5 py-0.5 rounded bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300">{col.data_type}</span>
                <button className="text-gray-300 dark:text-gray-500 hover:text-red-500 ml-auto" title="Drop column"
                  onClick={() => { if (confirm(`Drop column "${col.display_name}"?`)) dropColumn.mutate(col.id) }}>
                  <X size={13} />
                </button>
              </li>
            ))}
          </ul>

          {addingCol && (
            <div className="flex gap-2 pt-1">
              <input className="input-field flex-1" placeholder="Column name" value={newColName} autoFocus
                onChange={(e) => setNewColName(e.target.value)} />
              <select className="input-field w-36" value={newColType}
                onChange={(e) => setNewColType(e.target.value as DataEntryColumnType)}>
                {COLUMN_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
              </select>
              <button className="btn-primary" disabled={!newColName.trim() || addColumn.isPending} onClick={() => addColumn.mutate()}>Add</button>
              <button className="btn-secondary" onClick={() => setAddingCol(false)}>Cancel</button>
            </div>
          )}

          <div className="flex gap-3 pt-1">
            <button className="text-sm text-blue-600 dark:text-blue-400 hover:underline flex items-center gap-1"
              onClick={() => navigate(`/${domain}/data-entry/${table.id}`)}>
              <Eye size={14} /> View data
            </button>
            {!addingCol && (
              <button className="text-sm text-blue-600 dark:text-blue-400 hover:underline flex items-center gap-1"
                onClick={() => setAddingCol(true)}>
                <Columns3 size={14} /> Add column
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

// ── Page ─────────────────────────────────────────────────────────────────────

export default function DataEntry() {
  const domain = useDomain()
  const [creating, setCreating] = useState(false)

  const { data: tables = [] } = useQuery({
    queryKey: ['dataentry-tables', domain],
    queryFn: () => api.dataentry.listTables(domain),
  })

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">Data Entry</h1>
        <button className="btn-primary flex items-center gap-1.5" onClick={() => setCreating(true)}>
          <Plus size={15} /> New Table
        </button>
      </div>

      {creating && <NewTableForm domain={domain} onClose={() => setCreating(false)} />}

      {tables.length === 0 && !creating && (
        <div className="rounded-lg border-2 border-dashed border-gray-200 dark:border-gray-700 p-10 text-center text-gray-400 dark:text-gray-500">
          <p className="text-sm">No tables yet. Create one to start entering data.</p>
        </div>
      )}

      <div className="space-y-2">
        {tables.map((t) => <TableRow key={t.id} table={t} domain={domain} />)}
      </div>
    </div>
  )
}

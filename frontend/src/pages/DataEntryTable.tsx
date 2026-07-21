import { useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, Trash2, Columns3, ChevronLeft, X } from 'lucide-react'
import { api, DataEntryColumnType, DataEntryColumn, DataEntryRow } from '../api/client'
import { useDomain } from '../hooks/useDomain'

const COLUMN_TYPES: DataEntryColumnType[] = ['text', 'number', 'boolean', 'date', 'timestamp']

function cellValue(v: unknown): string {
  if (v === null || v === undefined) return ''
  if (typeof v === 'boolean') return v ? 'true' : 'false'
  return String(v)
}

export default function DataEntryTable() {
  const { tableId } = useParams<{ tableId: string }>()
  const domain = useDomain()
  const qc = useQueryClient()

  const { data: table, isLoading } = useQuery({
    queryKey: ['dataentry-table', tableId],
    queryFn: () => api.dataentry.getTable(tableId!),
    enabled: !!tableId,
  })
  const { data: rows = [] } = useQuery({
    queryKey: ['dataentry-rows', tableId],
    queryFn: () => api.dataentry.listRows(tableId!),
    enabled: !!tableId,
  })

  const [draft, setDraft] = useState<Record<string, string>>({})
  const [showAddCol, setShowAddCol] = useState(false)
  const [newColName, setNewColName] = useState('')
  const [newColType, setNewColType] = useState<DataEntryColumnType>('text')

  const invalidateRows = () => qc.invalidateQueries({ queryKey: ['dataentry-rows', tableId] })
  const invalidateTable = () => qc.invalidateQueries({ queryKey: ['dataentry-table', tableId] })

  const addColumn = useMutation({
    mutationFn: () => api.dataentry.addColumn(tableId!, { display_name: newColName, data_type: newColType }),
    onSuccess: () => { setNewColName(''); setShowAddCol(false); invalidateTable(); invalidateRows() },
  })
  const dropColumn = useMutation({
    mutationFn: (colId: string) => api.dataentry.dropColumn(tableId!, colId),
    onSuccess: () => { invalidateTable(); invalidateRows() },
  })
  const insertRow = useMutation({
    mutationFn: (values: Record<string, unknown>) => api.dataentry.insertRow(tableId!, values),
    onSuccess: () => { setDraft({}); invalidateRows() },
  })
  const updateCell = useMutation({
    mutationFn: ({ rowId, values }: { rowId: string; values: Record<string, unknown> }) =>
      api.dataentry.updateRow(tableId!, rowId, values),
  })
  const deleteRow = useMutation({
    mutationFn: (rowId: string) => api.dataentry.deleteRow(tableId!, rowId),
    onSuccess: invalidateRows,
  })

  const coerce = (col: DataEntryColumn, raw: string): unknown => {
    if (raw === '') return null
    if (col.data_type === 'boolean') return raw === 'true'
    return raw
  }

  const renderInput = (col: DataEntryColumn, value: unknown, onCommit: (raw: string) => void, key: string) => {
    if (col.data_type === 'boolean') {
      return (
        <input type="checkbox" defaultChecked={value === true || value === 'true'}
          onChange={(e) => onCommit(e.target.checked ? 'true' : 'false')} />
      )
    }
    const type = col.data_type === 'number' ? 'number' : col.data_type === 'date' ? 'date' : 'text'
    return (
      <input
        key={key}
        type={type}
        defaultValue={cellValue(value)}
        onBlur={(e) => onCommit(e.target.value)}
        className="w-full bg-transparent px-2 py-1 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-1 focus:ring-blue-400 rounded"
      />
    )
  }

  if (isLoading) return <div className="text-gray-400 dark:text-gray-500 text-center py-12">Loading…</div>
  if (!table) return <div className="text-red-500 text-center py-12">Table not found.</div>

  const columns = table.columns

  return (
    <div className="space-y-5">
      <Link to={`/${domain}/data-entry`}
        className="inline-flex items-center gap-1 text-sm text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200">
        <ChevronLeft size={16} /> Data Entry
      </Link>

      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">{table.display_name}</h1>
        <button className="btn-secondary flex items-center gap-1.5 text-sm" onClick={() => setShowAddCol((v) => !v)}>
          <Columns3 size={14} /> Add Column
        </button>
      </div>

      {showAddCol && (
        <div className="flex gap-2 bg-gray-50 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg p-3">
          <input className="input-field flex-1" placeholder="Column name" value={newColName}
            onChange={(e) => setNewColName(e.target.value)} autoFocus />
          <select className="input-field w-36" value={newColType}
            onChange={(e) => setNewColType(e.target.value as DataEntryColumnType)}>
            {COLUMN_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
          <button className="btn-primary" disabled={!newColName.trim() || addColumn.isPending}
            onClick={() => addColumn.mutate()}>Add</button>
        </div>
      )}

      {columns.length === 0 ? (
        <p className="text-sm text-gray-400 dark:text-gray-500">Add a column to start entering data.</p>
      ) : (
        <div className="overflow-x-auto border border-gray-200 dark:border-gray-700 rounded-lg bg-white dark:bg-gray-800">
          <table className="min-w-full text-sm">
            <thead>
              <tr className="border-b border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900/40">
                {columns.map((col) => (
                  <th key={col.id} className="text-left px-3 py-2 font-medium text-gray-600 dark:text-gray-300 whitespace-nowrap">
                    <span className="flex items-center gap-1.5">
                      {col.display_name}
                      <span className="text-gray-300 dark:text-gray-500 text-xs">({col.data_type})</span>
                      <button className="text-gray-300 dark:text-gray-500 hover:text-red-500" title="Drop column"
                        onClick={() => { if (confirm(`Drop column "${col.display_name}"?`)) dropColumn.mutate(col.id) }}>
                        <X size={12} />
                      </button>
                    </span>
                  </th>
                ))}
                <th className="px-3 py-2 w-10"></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row: DataEntryRow) => (
                <tr key={row.id} className="border-b border-gray-100 dark:border-gray-700/60 hover:bg-gray-50 dark:hover:bg-gray-700/30">
                  {columns.map((col) => (
                    <td key={col.id} className="px-1 py-0.5">
                      {renderInput(col, row[col.physical_name],
                        (raw) => updateCell.mutate({ rowId: row.id, values: { [col.physical_name]: coerce(col, raw) } }),
                        `${row.id}-${col.id}`)}
                    </td>
                  ))}
                  <td className="px-3 py-1 text-center">
                    <button className="text-gray-300 dark:text-gray-500 hover:text-red-500" onClick={() => deleteRow.mutate(row.id)}>
                      <Trash2 size={14} />
                    </button>
                  </td>
                </tr>
              ))}

              {/* Draft new row */}
              <tr className="bg-blue-50/40 dark:bg-blue-500/5">
                {columns.map((col) => (
                  <td key={col.id} className="px-1 py-0.5">
                    {col.data_type === 'boolean' ? (
                      <input type="checkbox" checked={draft[col.physical_name] === 'true'}
                        onChange={(e) => setDraft((d) => ({ ...d, [col.physical_name]: e.target.checked ? 'true' : 'false' }))} />
                    ) : (
                      <input
                        type={col.data_type === 'number' ? 'number' : col.data_type === 'date' ? 'date' : 'text'}
                        value={draft[col.physical_name] ?? ''}
                        onChange={(e) => setDraft((d) => ({ ...d, [col.physical_name]: e.target.value }))}
                        placeholder="New…"
                        className="w-full bg-transparent px-2 py-1 text-sm text-gray-900 dark:text-gray-100 focus:outline-none"
                      />
                    )}
                  </td>
                ))}
                <td className="px-3 py-1 text-center">
                  <button className="text-blue-600 dark:text-blue-400 hover:text-blue-800" title="Add row"
                    onClick={() => {
                      const values: Record<string, unknown> = {}
                      columns.forEach((c) => { values[c.physical_name] = coerce(c, draft[c.physical_name] ?? '') })
                      insertRow.mutate(values)
                    }}>
                    <Plus size={16} />
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      )}

      <p className="text-xs text-gray-400 dark:text-gray-500">
        Edit a cell and click away to save. Use the last row to add new entries.
      </p>
    </div>
  )
}

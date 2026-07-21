import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useMutation } from '@tanstack/react-query'
import { api } from '../api/client'
import { useSettingsStore } from '../stores/settings'

export default function Login() {
  const navigate = useNavigate()
  const setAuth = useSettingsStore((s) => s.setAuth)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')

  const mutation = useMutation({
    mutationFn: () => api.auth.login(email, password),
    onSuccess: (res) => {
      setAuth(res.access_token, res.user)
      navigate('/standup/meetings')
    },
  })

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    mutation.mutate()
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 dark:bg-gray-900 px-4">
      <div className="w-full max-w-sm">
        <div className="text-center mb-6">
          <div className="text-3xl">🪐</div>
          <h1 className="text-xl font-bold text-gray-900 dark:text-gray-100 mt-2">Orbo</h1>
          <p className="text-sm text-gray-500 dark:text-gray-400">Sign in to continue</p>
        </div>
        <form onSubmit={handleSubmit} className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-6 space-y-4">
          <div>
            <label className="label">Email</label>
            <input className="input-field" type="email" value={email}
              onChange={(e) => setEmail(e.target.value)} required autoFocus />
          </div>
          <div>
            <label className="label">Password</label>
            <input className="input-field" type="password" value={password}
              onChange={(e) => setPassword(e.target.value)} required />
          </div>
          {mutation.isError && (
            <div className="bg-red-50 border border-red-200 rounded p-2 text-red-700 text-sm dark:bg-red-500/10 dark:border-red-500/30 dark:text-red-300">
              Invalid email or password.
            </div>
          )}
          <button type="submit" disabled={mutation.isPending} className="btn-primary w-full">
            {mutation.isPending ? 'Signing in…' : 'Sign In'}
          </button>
          <p className="text-sm text-gray-500 dark:text-gray-400 text-center">
            No account?{' '}
            <Link to="/register" className="text-blue-600 hover:underline">Create one</Link>
          </p>
        </form>
      </div>
    </div>
  )
}

import { useLocation } from 'react-router-dom'

export type Domain = 'standup' | 'project'

/** Derive the active management domain from the URL's first path segment. */
export function useDomain(): Domain {
  const { pathname } = useLocation()
  return pathname.startsWith('/project') ? 'project' : 'standup'
}

export const DOMAIN_LABELS: Record<Domain, string> = {
  standup: 'Standup Management',
  project: 'Project Management',
}

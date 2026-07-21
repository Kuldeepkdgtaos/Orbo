import ReactMarkdown from 'react-markdown'
import { Sparkles, ListOrdered, Network } from 'lucide-react'
import { FEATURES_MD, SETUP_MD, ARCHITECTURE_MD } from '../content/featuresContent'

const mdComponents = {
  h3: ({ children }: any) => <h3 className="text-base font-bold text-gray-900 dark:text-gray-100 mt-5 mb-2 first:mt-0">{children}</h3>,
  h4: ({ children }: any) => <h4 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mt-3 mb-1">{children}</h4>,
  p: ({ children }: any) => <p className="text-sm text-gray-700 dark:text-gray-300 mb-3 leading-relaxed">{children}</p>,
  ul: ({ children }: any) => <ul className="list-disc list-inside space-y-1 mb-3 text-sm text-gray-700 dark:text-gray-300">{children}</ul>,
  ol: ({ children }: any) => <ol className="list-decimal list-inside space-y-1 mb-3 text-sm text-gray-700 dark:text-gray-300">{children}</ol>,
  li: ({ children }: any) => <li className="text-sm text-gray-700 dark:text-gray-300 leading-relaxed">{children}</li>,
  strong: ({ children }: any) => <strong className="font-semibold text-gray-900 dark:text-gray-100">{children}</strong>,
  a: ({ children, href }: any) => (
    <a href={href} className="text-blue-600 dark:text-blue-400 hover:text-blue-800 underline" target="_blank" rel="noopener noreferrer">
      {children}
    </a>
  ),
  code: ({ inline, children }: any) =>
    inline ? (
      <code className="px-1 py-0.5 rounded bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-200 text-xs font-mono">{children}</code>
    ) : (
      <code className="block font-mono text-xs">{children}</code>
    ),
  pre: ({ children }: any) => (
    <pre className="bg-gray-900 dark:bg-black/40 text-gray-100 rounded-md p-3 mb-3 overflow-x-auto text-xs leading-relaxed">
      {children}
    </pre>
  ),
}

function Section({ id, icon, title, subtitle, markdown }: { id: string; icon: React.ReactNode; title: string; subtitle: string; markdown: string }) {
  return (
    <section id={id} className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-6 scroll-mt-4">
      <div className="flex items-center gap-2 mb-1">
        {icon}
        <h2 className="text-lg font-bold text-gray-900 dark:text-gray-100">{title}</h2>
      </div>
      <p className="text-sm text-gray-500 dark:text-gray-400 mb-4">{subtitle}</p>
      <ReactMarkdown components={mdComponents}>{markdown}</ReactMarkdown>
    </section>
  )
}

export default function Features() {
  return (
    <div className="space-y-6 max-w-3xl mx-auto">
      <div>
        <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">Features & Architecture</h1>
        <p className="text-gray-500 dark:text-gray-400 mt-0.5">
          What this app does, how to get it running, and how it's built under the hood.
        </p>
      </div>

      <nav className="flex gap-2 text-sm">
        <a href="#features" className="btn-secondary">Features</a>
        <a href="#setup" className="btn-secondary">Setup Steps</a>
        <a href="#architecture" className="btn-secondary">Architecture</a>
      </nav>

      <Section
        id="features"
        icon={<Sparkles size={18} className="text-blue-600" />}
        title="Features"
        subtitle="What Orbo does end to end."
        markdown={FEATURES_MD}
      />

      <Section
        id="setup"
        icon={<ListOrdered size={18} className="text-blue-600" />}
        title="Steps to Make It Work"
        subtitle="From an empty environment to a running standup."
        markdown={SETUP_MD}
      />

      <Section
        id="architecture"
        icon={<Network size={18} className="text-blue-600" />}
        title="Backend Architecture"
        subtitle="The hierarchical A2A + MCP agent design behind this version."
        markdown={ARCHITECTURE_MD}
      />
    </div>
  )
}

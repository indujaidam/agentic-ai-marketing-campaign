
import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import {
  Bot,
  LayoutDashboard,
  PlusCircle,
  RefreshCw,
  CheckCircle,
  AlertCircle,
  FileText,
  Users,
  BarChart3,
  Sparkles,
  Upload,
  Download
} from 'lucide-react'
import './index.css'

const API = 'http://127.0.0.1:8000'

type Page = 'dashboard' | 'agents' | 'review' | 'analytics'

type Campaign = {
  id: number
  product_name: string
  target_audience: string
  campaign_goal: string
  approval_status: string
  results?: Record<string, unknown>
}

type AnalyticsResult = Record<string, unknown>

const agentSections: [string, string][] = [
  ['Requirement Analysis', 'requirement_analysis'],
  ['Audience & Competitor Research', 'audience_competitor_research'],
  ['Campaign Strategy', 'campaign_strategy'],
  ['Content & 30-Day Calendar', 'generated_content_and_calendar'],
  ['Content Review & Brand Compliance', 'content_review'],
  ['Campaign Analytics Plan', 'analytics_plan']
]

function App() {
  const [page, setPage] = useState<Page>('dashboard')
  const [campaigns, setCampaigns] = useState<Campaign[]>([])
  const [selected, setSelected] = useState<Campaign | null>(null)
  const [loading, setLoading] = useState(false)
  const [analyticsLoading, setAnalyticsLoading] = useState(false)
  const [message, setMessage] = useState('')
  const [analyticsFile, setAnalyticsFile] = useState<File | null>(null)
  const [analyticsResult, setAnalyticsResult] =
    useState<AnalyticsResult | null>(null)

  const [product, setProduct] = useState('Smart Water Bottle')
  const [audience, setAudience] = useState('College students')
  const [goal, setGoal] = useState('Increase product sales')
  const [description, setDescription] = useState(
    'A reusable water bottle for everyday use'
  )
  const [budget, setBudget] = useState('50000')
  const [tone, setTone] = useState('Friendly and professional')
  const [guidelines, setGuidelines] = useState(
    'Use clear, honest language. Do not invent product features or create false urgency.'
  )

  async function loadCampaigns() {
    try {
      const response = await fetch(`${API}/campaigns`)
      if (!response.ok) throw new Error('Could not load campaigns')

      const data = await response.json()
      const items: Campaign[] = Array.isArray(data)
        ? data
        : data.campaigns ?? []

      setCampaigns(items)

      if (selected) {
        const updated = items.find(item => item.id === selected.id)
        if (updated) setSelected(current => current ? { ...current, ...updated } : updated)
      }
    } catch {
      setMessage(
        'Cannot connect to backend. Make sure FastAPI is running on port 8000.'
      )
    }
  }

  async function openCampaign(id: number) {
    try {
      const response = await fetch(`${API}/campaigns/${id}`)
      const data = await response.json()

      if (!response.ok) {
        throw new Error(data.detail ?? 'Could not load campaign')
      }

      setSelected(data)
      setMessage('')
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : 'Could not load campaign'
      )
    }
  }

  useEffect(() => {
    void loadCampaigns()
  }, [])

  async function createCampaign(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setLoading(true)
    setMessage('Running the six-agent workflow. Please wait...')

    try {
      const response = await fetch(`${API}/run-campaign`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          product_name: product,
          target_audience: audience,
          campaign_goal: goal,
          product_description: description,
          budget: Number(budget),
          duration_days: 30,
          platforms: ['LinkedIn', 'Email', 'Instagram'],
          brand_tone: tone,
          brand_guidelines: guidelines,
          key_features: description
        })
      })

      const data = await response.json()

      if (!response.ok) {
        throw new Error(
          typeof data.detail === 'string'
            ? data.detail
            : JSON.stringify(data.detail ?? 'Campaign generation failed')
        )
      }

      await loadCampaigns()
      await openCampaign(data.campaign_id)
      setPage('agents')
      setMessage(
        `Campaign #${data.campaign_id} generated. Review it before approval.`
      )
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : 'Campaign generation failed'
      )
    } finally {
      setLoading(false)
    }
  }

  async function reviewCampaign(
    decision: 'approve' | 'reject' | 'revise'
  ) {
    if (!selected) {
      setMessage('Select a saved campaign first.')
      return
    }

    let feedback = ''

    if (decision === 'revise') {
      feedback = window.prompt('Enter the requested changes:') ?? ''
      if (!feedback.trim()) return
    } else if (decision === 'approve') {
      feedback = 'Campaign approved by human reviewer.'
    } else {
      feedback =
        window.prompt('Reason for rejection:') ??
        'Campaign rejected by human reviewer.'
    }

    try {
      const response = await fetch(
        `${API}/campaigns/${selected.id}/approval`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ decision, feedback })
        }
      )

      const data = await response.json()

      if (!response.ok) {
        throw new Error(
          typeof data.detail === 'string'
            ? data.detail
            : JSON.stringify(data.detail ?? 'Review failed')
        )
      }

      setMessage(data.message ?? 'Review decision saved.')
      await openCampaign(selected.id)
      await loadCampaigns()
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Review failed')
    }
  }

  async function uploadAnalytics(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()

    if (!analyticsFile) {
      setMessage('Please select a CSV file first.')
      return
    }

    const formData = new FormData()
    formData.append('file', analyticsFile)

    setAnalyticsLoading(true)
    setAnalyticsResult(null)
    setMessage('Uploading and calculating campaign analytics...')

    try {
      const response = await fetch(`${API}/analytics/upload`, {
        method: 'POST',
        body: formData
      })

      const data = await response.json()

      if (!response.ok) {
        throw new Error(
          typeof data.detail === 'string'
            ? data.detail
            : JSON.stringify(data.detail ?? 'Analytics upload failed')
        )
      }

      setAnalyticsResult(data)
      setMessage('Analytics CSV processed successfully.')
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : 'Analytics upload failed'
      )
    } finally {
      setAnalyticsLoading(false)
    }
  }

  const results = selected?.results ?? {}

  function navButton(
    target: Page,
    label: string,
    Icon: typeof LayoutDashboard
  ) {
    return (
      <button
        key={target}
        type="button"
        onClick={() => {
          setPage(target)
          setMessage('')
        }}
        className={`flex w-full items-center gap-3 rounded-lg p-3 text-left transition ${
          page === target
            ? 'bg-violet-600 text-white'
            : 'text-slate-300 hover:bg-slate-800 hover:text-white'
        }`}
      >
        <Icon size={18} />
        {label}
      </button>
    )
  }

  function renderAgentResults() {
    if (!selected) {
      return (
        <section className="rounded-2xl border bg-white p-6">
          <h3 className="text-lg font-bold">Six-Agent Results</h3>
          <p className="mt-3 text-slate-500">
            Select a saved campaign from the Dashboard to view its agent results.
          </p>
          <button
            onClick={() => setPage('dashboard')}
            className="mt-4 rounded-lg bg-violet-600 px-4 py-2 text-white"
          >
            Go to Dashboard
          </button>
        </section>
      )
    }

    return (
      <section className="rounded-2xl border bg-white p-6">
        <h3 className="text-xl font-bold">Six-Agent Results</h3>
        <p className="mb-5 mt-2 text-sm text-slate-500">
          Campaign #{selected.id} · {selected.product_name}
        </p>

        {agentSections.map(([title, key]) => (
          <details key={key} className="border-b py-4">
            <summary className="cursor-pointer font-semibold hover:text-violet-700">
              {title}
            </summary>
            <pre className="mt-3 max-h-[500px] overflow-auto whitespace-pre-wrap break-words rounded-lg bg-slate-50 p-4 text-xs leading-5">
              {results[key] !== undefined
                ? JSON.stringify(results[key], null, 2)
                : 'No result was returned for this section.'}
            </pre>
          </details>
        ))}

        
<div className="mt-5 flex flex-wrap gap-3">
  <a
    href={`${API}/campaigns/${selected.id}/export.csv`}
    className="inline-flex items-center gap-2 rounded-lg border px-4 py-3 text-sm font-semibold hover:bg-slate-50"
  >
    <Download size={16} />
    Export Campaign CSV
  </a>

  <a
    href={`${API}/campaigns/${selected.id}/export.pdf`}
    className="inline-flex items-center gap-2 rounded-lg border px-4 py-3 text-sm font-semibold hover:bg-slate-50"
  >
    <FileText size={16} />
    Export Campaign PDF
  </a>
</div>
</section>

    )
  }

  function renderReview() {
    return (
      <div className="space-y-6">
        <section className="rounded-2xl border bg-white p-6">
          <h3 className="text-xl font-bold">Human Review</h3>
          <p className="mt-2 text-sm text-slate-500">
            Select a campaign below. Review its content and explicitly approve,
            request changes, or reject it.
          </p>
        </section>

        <section className="rounded-2xl border bg-white p-6">
          <h3 className="mb-4 font-bold">Select Campaign</h3>
          {campaigns.length === 0 ? (
            <p className="text-slate-500">No saved campaigns available.</p>
          ) : (
            <div className="space-y-2">
              {campaigns.map(campaign => (
                <button
                  key={campaign.id}
                  onClick={() => void openCampaign(campaign.id)}
                  className={`flex w-full items-center justify-between gap-3 rounded-xl border p-4 text-left hover:bg-slate-50 ${
                    selected?.id === campaign.id
                      ? 'border-violet-500 bg-violet-50'
                      : ''
                  }`}
                >
                  <span>
                    <span className="block font-semibold">
                      {campaign.product_name}
                    </span>
                    <span className="text-xs text-slate-500">
                      Campaign #{campaign.id}
                    </span>
                  </span>
                  <span className="rounded-full bg-slate-100 px-3 py-1 text-xs">
                    {campaign.approval_status}
                  </span>
                </button>
              ))}
            </div>
          )}
        </section>

        {selected && (
          <section className="rounded-2xl border bg-white p-6">
            <h3 className="text-lg font-bold">{selected.product_name}</h3>
            <p className="mt-2 text-sm text-slate-600">
              Campaign #{selected.id} · Status:{' '}
              <strong>{selected.approval_status}</strong>
            </p>
            <p className="mt-2 text-sm text-slate-600">
              Target audience: {selected.target_audience}
            </p>
            <p className="mt-2 text-sm text-slate-600">
              Goal: {selected.campaign_goal}
            </p>

            <div className="mt-5 flex flex-wrap gap-3">
              <button
                onClick={() => void reviewCampaign('approve')}
                className="rounded-lg bg-emerald-600 px-4 py-3 font-semibold text-white hover:bg-emerald-700"
              >
                <CheckCircle className="mr-2 inline" size={17} />
                Approve
              </button>
              <button
                onClick={() => void reviewCampaign('revise')}
                className="rounded-lg bg-amber-500 px-4 py-3 font-semibold text-white hover:bg-amber-600"
              >
                Request Revision
              </button>
              <button
                onClick={() => void reviewCampaign('reject')}
                className="rounded-lg bg-rose-600 px-4 py-3 font-semibold text-white hover:bg-rose-700"
              >
                Reject
              </button>
              <button
                onClick={() => setPage('agents')}
                className="rounded-lg border px-4 py-3 font-semibold hover:bg-slate-50"
              >
                View Agent Results
              </button>
            </div>
          </section>
        )}
      </div>
    )
  }

  function renderAnalytics() {
    return (
      <div className="space-y-6">
        <section className="rounded-2xl border bg-white p-6">
          <div className="mb-4 flex items-center gap-3">
            <Upload className="text-violet-600" />
            <div>
              <h3 className="text-xl font-bold">Campaign Analytics</h3>
              <p className="text-sm text-slate-500">
                Upload a CSV file containing performance data.
              </p>
            </div>
          </div>

          <form onSubmit={uploadAnalytics} className="space-y-4">
            <input
              type="file"
              accept=".csv,text/csv"
              required
              onChange={event =>
                setAnalyticsFile(event.target.files?.[0] ?? null)
              }
              className="block w-full rounded-lg border p-3 text-sm"
            />
            <button
              type="submit"
              disabled={analyticsLoading || !analyticsFile}
              className="rounded-lg bg-violet-600 px-5 py-3 font-semibold text-white hover:bg-violet-700 disabled:opacity-50"
            >
              {analyticsLoading ? 'Calculating...' : 'Upload Analytics CSV'}
            </button>
          </form>
        </section>

        {analyticsResult && (
          <section className="rounded-2xl border bg-white p-6">
            <h3 className="mb-4 text-lg font-bold">Calculated Results</h3>
            <pre className="max-h-[500px] overflow-auto whitespace-pre-wrap break-words rounded-lg bg-slate-50 p-4 text-xs leading-5">
              {JSON.stringify(analyticsResult, null, 2)}
            </pre>
            <p className="mt-3 text-xs text-slate-500">
              Results are based on the uploaded data. Sample data does not
              represent verified live advertising performance.
            </p>
          </section>
        )}
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-slate-50 md:flex">
      <aside className="w-full shrink-0 bg-slate-950 p-5 text-white md:min-h-screen md:w-64">
        <div className="mb-8 flex items-center gap-3">
          <div className="rounded-xl bg-violet-600 p-3">
            <Bot size={24} />
          </div>
          <div>
            <h1 className="font-bold">Campaign AI</h1>
            <p className="text-xs text-slate-400">Multi-agent marketing</p>
          </div>
        </div>

        <nav className="space-y-2">
          {navButton('dashboard', 'Campaign Dashboard', LayoutDashboard)}
          {navButton('agents', 'Six AI Agents', Sparkles)}
          {navButton('review', 'Human Review', Users)}
          {navButton('analytics', 'Campaign Analytics', BarChart3)}
        </nav>

        <p className="mt-8 text-xs leading-5 text-slate-400">
          Human approval is required. This application does not publish content
          externally.
        </p>
      </aside>

      <main className="min-w-0 flex-1 p-4 sm:p-6 lg:p-9">
        <header className="mb-7 flex flex-wrap items-center justify-between gap-4">
          <div>
            <p className="text-sm font-semibold text-violet-700">
              MARKETING WORKSPACE
            </p>
            <h2 className="mt-1 text-2xl font-bold sm:text-3xl">
              {{
                dashboard: 'Campaign Dashboard',
                agents: 'Six AI Agents',
                review: 'Human Review',
                analytics: 'Campaign Analytics'
              }[page]}
            </h2>
            <p className="mt-2 text-sm text-slate-500">
              Plan, generate, review, and measure campaigns.
            </p>
          </div>

          <button
            onClick={() => void loadCampaigns()}
            className="flex items-center gap-2 rounded-lg border bg-white px-4 py-3 hover:bg-slate-100"
          >
            <RefreshCw size={16} /> Refresh
          </button>
        </header>

        {message && (
          <div className="mb-5 flex items-start gap-2 rounded-xl border bg-white p-4 text-sm">
            <AlertCircle size={18} className="mt-0.5 shrink-0 text-violet-600" />
            <span className="flex-1">{message}</span>
            <button
              onClick={() => setMessage('')}
              className="text-slate-400 hover:text-slate-700"
              aria-label="Dismiss message"
            >
              ×
            </button>
          </div>
        )}

        {page === 'dashboard' && (
          <>
            <section className="mb-7 grid gap-4 sm:grid-cols-3">
              <div className="rounded-2xl border bg-white p-5">
                <p className="text-sm text-slate-500">Saved Campaigns</p>
                <p className="mt-3 text-3xl font-bold">{campaigns.length}</p>
              </div>
              <div className="rounded-2xl border bg-white p-5">
                <p className="text-sm text-slate-500">Specialized AI Agents</p>
                <p className="mt-3 text-3xl font-bold">6</p>
              </div>
              <div className="rounded-2xl border bg-white p-5">
                <p className="text-sm text-slate-500">Selected Status</p>
                <p className="mt-3 break-words text-xl font-bold">
                  {selected?.approval_status ?? 'No campaign selected'}
                </p>
              </div>
            </section>

            <div className="grid items-start gap-6 xl:grid-cols-2">
              <section className="rounded-2xl border bg-white p-5 sm:p-6">
                <div className="mb-5 flex items-center gap-3">
                  <div className="rounded-lg bg-violet-100 p-2 text-violet-700">
                    <PlusCircle />
                  </div>
                  <div>
                    <h3 className="text-lg font-bold">Create Campaign</h3>
                    <p className="text-sm text-slate-500">
                      Run the six-agent workflow
                    </p>
                  </div>
                </div>

                <form onSubmit={createCampaign} className="space-y-4">
                  <label className="block text-sm font-medium">
                    Product name
                    <input
                      required
                      value={product}
                      onChange={event => setProduct(event.target.value)}
                      className="mt-1 w-full rounded-lg border p-3"
                    />
                  </label>

                  <label className="block text-sm font-medium">
                    Target audience
                    <input
                      required
                      value={audience}
                      onChange={event => setAudience(event.target.value)}
                      className="mt-1 w-full rounded-lg border p-3"
                    />
                  </label>

                  <label className="block text-sm font-medium">
                    Campaign goal
                    <input
                      required
                      value={goal}
                      onChange={event => setGoal(event.target.value)}
                      className="mt-1 w-full rounded-lg border p-3"
                    />
                  </label>

                  <label className="block text-sm font-medium">
                    Product description
                    <textarea
                      required
                      value={description}
                      onChange={event => setDescription(event.target.value)}
                      rows={3}
                      className="mt-1 w-full rounded-lg border p-3"
                    />
                  </label>

                  <label className="block text-sm font-medium">
                    Total budget (₹)
                    <input
                      required
                      type="number"
                      min="1"
                      value={budget}
                      onChange={event => setBudget(event.target.value)}
                      className="mt-1 w-full rounded-lg border p-3"
                    />
                  </label>

                  <label className="block text-sm font-medium">
                    Brand tone
                    <select
                      value={tone}
                      onChange={event => setTone(event.target.value)}
                      className="mt-1 w-full rounded-lg border bg-white p-3"
                    >
                      <option>Friendly and professional</option>
                      <option>Professional</option>
                      <option>Playful</option>
                      <option>Formal</option>
                      <option>Bold and energetic</option>
                    </select>
                  </label>

                  <label className="block text-sm font-medium">
                    Brand guidelines
                    <textarea
                      value={guidelines}
                      onChange={event => setGuidelines(event.target.value)}
                      rows={3}
                      className="mt-1 w-full rounded-lg border p-3"
                    />
                  </label>

                  <button
                    type="submit"
                    disabled={loading}
                    className="flex w-full items-center justify-center gap-2 rounded-xl bg-violet-600 p-4 font-semibold text-white hover:bg-violet-700 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    <Sparkles size={18} />
                    {loading ? 'Agents are working...' : 'Generate Full Campaign'}
                  </button>
                </form>
              </section>

              <section className="rounded-2xl border bg-white p-5 sm:p-6">
                <div className="mb-4 flex items-center gap-3">
                  <FileText className="text-violet-600" />
                  <h3 className="text-lg font-bold">Saved Campaigns</h3>
                </div>

                {campaigns.length === 0 ? (
                  <p className="text-sm text-slate-500">
                    No campaigns found yet. Create your first campaign.
                  </p>
                ) : (
                  <div className="space-y-2">
                    {campaigns.map(campaign => (
                      <button
                        key={campaign.id}
                        onClick={() => void openCampaign(campaign.id)}
                        className={`flex w-full items-center justify-between gap-3 rounded-xl border p-4 text-left hover:bg-slate-50 ${
                          selected?.id === campaign.id
                            ? 'border-violet-500 bg-violet-50'
                            : ''
                        }`}
                      >
                        <span>
                          <span className="block font-semibold">
                            {campaign.product_name}
                          </span>
                          <span className="text-xs text-slate-500">
                            Campaign #{campaign.id} · {campaign.target_audience}
                          </span>
                        </span>
                        <span className="shrink-0 rounded-full bg-slate-100 px-3 py-1 text-xs">
                          {campaign.approval_status}
                        </span>
                      </button>
                    ))}
                  </div>
                )}

                {selected && (
                  <div className="mt-5 rounded-xl bg-slate-50 p-4">
                    <p className="font-semibold">{selected.product_name}</p>
                    <p className="mt-1 text-sm text-slate-500">
                      Campaign #{selected.id} · {selected.approval_status}
                    </p>
                    <div className="mt-3 flex flex-wrap gap-2">
                      <button
                        onClick={() => setPage('agents')}
                        className="rounded-lg bg-violet-600 px-3 py-2 text-sm font-semibold text-white"
                      >
                        View Agents
                      </button>
                      <button
                        onClick={() => setPage('review')}
                        className="rounded-lg border bg-white px-3 py-2 text-sm font-semibold"
                      >
                        Review Campaign
                      </button>
                    </div>
                  </div>
                )}
              </section>
            </div>
          </>
        )}

        {page === 'agents' && renderAgentResults()}

        {page === 'review' && renderReview()}

        {page === 'analytics' && renderAnalytics()}

        <footer className="mt-10 border-t pt-5 text-xs text-slate-400">
          Agentic AI Marketing Campaign System · Human approval required before
          campaign content is approved for use.
        </footer>
      </main>
    </div>
  )
}

export default App

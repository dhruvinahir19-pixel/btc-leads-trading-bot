import React from 'react'

interface Props {
  children: React.ReactNode
}

interface State {
  hasError: boolean
  error: Error | null
}

export default class ErrorBoundary extends React.Component<Props, State> {
  constructor(props: Props) {
    super(props)
    this.state = { hasError: false, error: null }
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error('Dashboard error:', error, info)
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="min-h-screen bg-surface-950 flex items-center justify-center p-4">
          <div className="card max-w-md w-full text-center">
            <span className="text-5xl block mb-4">💥</span>
            <h2 className="text-xl font-bold text-surface-100 mb-2">Dashboard Error</h2>
            <p className="text-surface-400 text-sm mb-4">
              Something went wrong rendering the dashboard.
            </p>
            {this.state.error && (
              <pre className="text-xs text-red-400 bg-surface-900 rounded-lg p-3 mb-4 overflow-auto text-left">
                {this.state.error.message}
              </pre>
            )}
            <button
              onClick={() => window.location.reload()}
              className="btn-primary"
            >
              Reload Dashboard
            </button>
          </div>
        </div>
      )
    }

    return this.props.children
  }
}

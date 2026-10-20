import { Component, type ReactNode } from "react";

export class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) { return { error }; }
  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div style={{ height: "100%", display: "grid", placeItems: "center", padding: 24 }}>
        <div className="card" style={{ maxWidth: 520 }} role="alert">
          <h2>The interface hit an unexpected error</h2>
          <p className="muted">Your data and the backend are unaffected. Reloading usually fixes this.</p>
          <pre className="code">{this.state.error.message}</pre>
          <button className="btn primary" onClick={() => location.reload()}>Reload</button>
        </div>
      </div>
    );
  }
}

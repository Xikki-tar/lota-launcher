import { Component, ReactNode } from "react";

interface State {
  error: Error | null;
}

export default class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: { componentStack: string }) {
    console.error("[ErrorBoundary]", error.message, info.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        <div style={{
          flex: 1, display: "flex", flexDirection: "column", alignItems: "center",
          justifyContent: "center", padding: 32, gap: 12, background: "#0B0A08",
          color: "#F18A80",
        }}>
          <div style={{ fontSize: 15, fontWeight: 700 }}>Ошибка рендеринга</div>
          <div style={{ fontSize: 12, maxWidth: 600, wordBreak: "break-all", textAlign: "center" }}>
            {this.state.error.message}
          </div>
          <pre style={{
            fontSize: 10, color: "rgba(240,100,100,0.5)", maxWidth: 600,
            maxHeight: 200, overflow: "auto", whiteSpace: "pre-wrap", wordBreak: "break-all",
          }}>
            {this.state.error.stack}
          </pre>
        </div>
      );
    }
    return this.props.children;
  }
}

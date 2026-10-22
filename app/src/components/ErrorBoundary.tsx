import { Component, ErrorInfo, ReactNode } from "react";
import { useLocation } from "react-router-dom";
import { useI18n } from "../lib/I18nContext";
import styles from "./ErrorBoundary.module.css";

interface BoundaryProps {
  children: ReactNode;
  resetKey: string;
}

interface BoundaryState {
  error: Error | null;
  componentStack: string;
}

interface FallbackProps {
  error: Error;
  componentStack: string;
  onRetry: () => void;
}

function ErrorFallback({ error, componentStack, onRetry }: FallbackProps) {
  const { t } = useI18n();
  const trace = [error.stack, componentStack.trim()].filter(Boolean).join("\n\n");
  return (
    <div className={styles.root} role="alert">
      <div className={styles.title}>{t("render_error_title", "Что-то пошло не так")}</div>
      <div className={styles.message}>{error.message || error.name}</div>
      {trace && <pre className={styles.trace}>{trace}</pre>}
      <div className={styles.btns}>
        <button className={styles.btnRetry} onClick={onRetry}>{t("btn_retry", "Попробовать снова")}</button>
        <button className={styles.btnReload} onClick={() => window.location.reload()}>
          {t("btn_reload", "Перезагрузить")}
        </button>
      </div>
    </div>
  );
}

class Boundary extends Component<BoundaryProps, BoundaryState> {
  state: BoundaryState = { error: null, componentStack: "" };

  static getDerivedStateFromError(error: Error): Partial<BoundaryState> {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("[ErrorBoundary]", error, info.componentStack);
    this.setState({ componentStack: info.componentStack ?? "" });
  }

  componentDidUpdate(prev: BoundaryProps) {
    if (this.state.error && prev.resetKey !== this.props.resetKey) this.reset();
  }

  reset = () => this.setState({ error: null, componentStack: "" });

  render() {
    if (!this.state.error) return this.props.children;
    return <ErrorFallback error={this.state.error} componentStack={this.state.componentStack} onRetry={this.reset} />;
  }
}

export default function ErrorBoundary({ children }: { children: ReactNode }) {
  const location = useLocation();
  return <Boundary resetKey={location.pathname}>{children}</Boundary>;
}

"use client";

import { Component, type ReactNode } from "react";
import { useAppContext } from "@/context/AppContext";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/Feedback";

function GameErrorFallback() {
  const { language } = useAppContext();
  return (
    <main data-theme="dark" className="flex min-h-screen items-center justify-center bg-background px-4">
      <EmptyState
        title={language === "zh" ? "页面暂时无法显示" : "Something went wrong"}
        description={language === "zh" ? "请返回大厅重试，你可以重新进入房间查看对局。" : "Return to the lobby and reopen the room to view the match."}
      >
        <Button onClick={() => window.location.assign("/")}>{language === "zh" ? "返回大厅" : "Back to lobby"}</Button>
      </EmptyState>
    </main>
  );
}

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
}

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(): State {
    return { hasError: true };
  }

  render() {
    if (this.state.hasError) {
      return this.props.fallback || <GameErrorFallback />;
    }
    return this.props.children;
  }
}

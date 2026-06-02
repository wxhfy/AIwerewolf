"use client";

import { Component, type ReactNode } from "react";

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
      return this.props.fallback || (
        <div className="flex h-screen flex-col items-center justify-center gap-4 bg-background px-6 text-center">
          <p className="font-display text-lg text-textPrimary">Something went wrong</p>
          <p className="text-sm text-text-sub">The game page encountered an error. Please return to the lobby and try again.</p>
          <a href="/" className="rounded-button bg-primary px-5 py-2 text-sm font-medium text-white hover:bg-primaryHover transition-colors">
            Back to Lobby
          </a>
        </div>
      );
    }
    return this.props.children;
  }
}

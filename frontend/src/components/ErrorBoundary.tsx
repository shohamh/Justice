import { Component, ReactNode } from "react";

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
}

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false };

  static getDerivedStateFromError(): State {
    return { hasError: true };
  }

  componentDidCatch(error: unknown) {
    console.error("Unhandled render error:", error);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="min-h-screen flex items-center justify-center p-6 dark:bg-gray-900" dir="rtl">
          <p className="text-gray-600 dark:text-gray-300">משהו השתבש. נסה לרענן את הדף.</p>
        </div>
      );
    }
    return this.props.children;
  }
}

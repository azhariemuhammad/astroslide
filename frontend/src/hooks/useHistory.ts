import { useCallback, useState } from 'react';

interface HistoryState<T> {
  entries: T[];
  index: number;
}

/**
 * Linear undo/redo stack. Pushing after an undo discards the redo branch,
 * and only the most recent `limit` entries are kept.
 */
export function useHistory<T>(limit = 30) {
  const [state, setState] = useState<HistoryState<T>>({ entries: [], index: -1 });

  const push = useCallback((entry: T) => {
    setState(prev => {
      const entries = [...prev.entries.slice(0, prev.index + 1), entry].slice(-limit);
      return { entries, index: entries.length - 1 };
    });
  }, [limit]);

  const reset = useCallback((entry: T) => {
    setState({ entries: [entry], index: 0 });
  }, []);

  // Return the entry being moved to so the caller can restore it
  const undo = (): T | undefined => {
    if (state.index <= 0) return undefined;
    setState({ ...state, index: state.index - 1 });
    return state.entries[state.index - 1];
  };

  const redo = (): T | undefined => {
    if (state.index >= state.entries.length - 1) return undefined;
    setState({ ...state, index: state.index + 1 });
    return state.entries[state.index + 1];
  };

  return {
    push,
    reset,
    undo,
    redo,
    canUndo: state.index > 0,
    canRedo: state.index < state.entries.length - 1,
    // Labels of the steps that undo/redo would move to, for tooltips
    previous: state.index > 0 ? state.entries[state.index - 1] : undefined,
    next: state.entries[state.index + 1],
    current: state.entries[state.index],
  };
}

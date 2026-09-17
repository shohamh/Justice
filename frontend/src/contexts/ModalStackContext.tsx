import { createContext, useCallback, useContext, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";

export const MODAL_STACK_BASE_Z_INDEX = 50;

interface ModalStack {
  register: () => number;
  release: (layer: number) => void;
  // Rank of `layer` among the currently-active layers (1 = lowest active,
  // increasing with more recent registration), or 0 if `layer` is not
  // currently active. This is what callers should add to
  // MODAL_STACK_BASE_Z_INDEX -- NOT the raw token from register(), which is
  // only a stable ordering key and grows unboundedly across a session.
  getRank: (layer: number) => number;
  // Notified whenever the set of active layers changes, so an already-open
  // modal can recompute its rank (e.g. it moves down a slot when a
  // lower-ranked modal closes).
  subscribe: (listener: () => void) => () => void;
}

function rankOf(active: Set<number>, layer: number): number {
  if (!active.has(layer)) return 0;
  let rank = 0;
  for (const other of active) {
    if (other <= layer) rank++;
  }
  return rank;
}

function makeStandaloneStack(): ModalStack {
  const activeLayers = new Set<number>();
  const listeners = new Set<() => void>();
  let nextLayer = 0;

  function notify() {
    for (const listener of listeners) listener();
  }

  return {
    register: () => {
      const layer = ++nextLayer;
      activeLayers.add(layer);
      notify();
      return layer;
    },
    release: (layer) => {
      activeLayers.delete(layer);
      notify();
    },
    getRank: (layer) => rankOf(activeLayers, layer),
    subscribe: (listener) => {
      listeners.add(listener);
      return () => { listeners.delete(listener); };
    },
  };
}

// Fallback stack for a `useModalLayer` caller rendered outside any
// `ModalStackProvider` (e.g. in isolation in a test). Module-level singleton,
// shared across all such callers within the process.
const standaloneStack = makeStandaloneStack();

const ModalStackContext = createContext<ModalStack | null>(null);

export function ModalStackProvider({ children }: { children: ReactNode }) {
  const nextLayerRef = useRef(0);
  const activeLayersRef = useRef(new Set<number>());
  const listenersRef = useRef(new Set<() => void>());

  const notify = useCallback(() => {
    for (const listener of listenersRef.current) listener();
  }, []);

  const register = useCallback(() => {
    const layer = ++nextLayerRef.current;
    activeLayersRef.current.add(layer);
    notify();
    return layer;
  }, [notify]);

  const release = useCallback((layer: number) => {
    activeLayersRef.current.delete(layer);
    notify();
  }, [notify]);

  const getRank = useCallback((layer: number) => rankOf(activeLayersRef.current, layer), []);

  const subscribe = useCallback((listener: () => void) => {
    listenersRef.current.add(listener);
    return () => { listenersRef.current.delete(listener); };
  }, []);

  const value = useMemo(
    () => ({ register, release, getRank, subscribe }),
    [register, release, getRank, subscribe]
  );

  return (
    <ModalStackContext.Provider value={value}>
      {children}
    </ModalStackContext.Provider>
  );
}

export function useModalLayer(open: boolean): number {
  const stack = useContext(ModalStackContext) ?? standaloneStack;
  const [rank, setRank] = useState(0);
  const currentLayerRef = useRef(0);
  const wasOpenRef = useRef(false);

  // Recompute this modal's rank whenever the set of active layers changes --
  // e.g. a lower-ranked modal closing moves this one down a slot, keeping the
  // rendered z-index bounded by how many modals are open concurrently rather
  // than by how many have ever been opened this session.
  useLayoutEffect(() => {
    return stack.subscribe(() => {
      if (currentLayerRef.current) {
        setRank(stack.getRank(currentLayerRef.current));
      }
    });
  }, [stack]);

  useLayoutEffect(() => {
    if (open && !wasOpenRef.current) {
      const nextLayer = stack.register();
      currentLayerRef.current = nextLayer;
      setRank(stack.getRank(nextLayer));
    } else if (!open && wasOpenRef.current) {
      stack.release(currentLayerRef.current);
      currentLayerRef.current = 0;
      setRank(0);
    }
    wasOpenRef.current = open;

    return () => {
      if (currentLayerRef.current) {
        stack.release(currentLayerRef.current);
        currentLayerRef.current = 0;
        wasOpenRef.current = false;
      }
    };
  }, [open, stack]);

  return rank;
}

import { createContext, useCallback, useContext, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";

export const MODAL_STACK_BASE_Z_INDEX = 50;

interface ModalStack {
  register: () => number;
  release: (layer: number) => void;
}

const standaloneLayers = new Set<number>();
let nextStandaloneLayer = 0;

const standaloneStack: ModalStack = {
  register: () => {
    const layer = ++nextStandaloneLayer;
    standaloneLayers.add(layer);
    return layer;
  },
  release: (layer) => {
    standaloneLayers.delete(layer);
  },
};

const ModalStackContext = createContext<ModalStack | null>(null);

export function ModalStackProvider({ children }: { children: ReactNode }) {
  const nextLayerRef = useRef(0);
  const activeLayersRef = useRef(new Set<number>());

  const register = useCallback(() => {
    const layer = ++nextLayerRef.current;
    activeLayersRef.current.add(layer);
    return layer;
  }, []);

  const release = useCallback((layer: number) => {
    activeLayersRef.current.delete(layer);
  }, []);
  const value = useMemo(() => ({ register, release }), [register, release]);

  return (
    <ModalStackContext.Provider value={value}>
      {children}
    </ModalStackContext.Provider>
  );
}

export function useModalLayer(open: boolean): number {
  const stack = useContext(ModalStackContext) ?? standaloneStack;
  const [layer, setLayer] = useState(0);
  const currentLayerRef = useRef(0);
  const wasOpenRef = useRef(false);

  useLayoutEffect(() => {
    if (open && !wasOpenRef.current) {
      const nextLayer = stack.register();
      currentLayerRef.current = nextLayer;
      setLayer(nextLayer);
    } else if (!open && wasOpenRef.current) {
      stack.release(currentLayerRef.current);
      currentLayerRef.current = 0;
      setLayer(0);
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

  return layer;
}

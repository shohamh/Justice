import { useContext, useEffect, useRef } from "react";
import { UnsavedChangesContext, UnsavedChangesGuardHandlers } from "../contexts/UnsavedChangesContext";

let nextGuardId = 0;

export function useUnsavedChangesGuard(handlers: UnsavedChangesGuardHandlers): { requestClose: () => void } {
  const ctx = useContext(UnsavedChangesContext);
  const idRef = useRef<number>();
  if (idRef.current === undefined) idRef.current = ++nextGuardId;
  const id = idRef.current;

  const handlersRef = useRef(handlers);
  handlersRef.current = handlers;

  useEffect(() => {
    if (!ctx) return;
    ctx.setGuard(id, {
      kind: handlersRef.current.kind,
      isDirty: handlersRef.current.isDirty,
      onSave: () => handlersRef.current.onSave(),
      onDiscard: () => handlersRef.current.onDiscard(),
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ctx, id, handlers.isDirty, handlers.kind]);

  useEffect(() => {
    return () => ctx?.removeGuard(id);
  }, [ctx, id]);

  return {
    requestClose: () => {
      if (!ctx) {
        handlersRef.current.onDiscard();
        return;
      }

      // Ensure the guard is up-to-date with current handlers before calling requestClose.
      // This is needed because effects might not have run yet due to React batching.
      // The provider's requestClose will then check the guard's isDirty to decide what to do.
      ctx.setGuard(id, {
        kind: handlersRef.current.kind,
        isDirty: handlersRef.current.isDirty,
        onSave: () => handlersRef.current.onSave(),
        onDiscard: () => handlersRef.current.onDiscard(),
      });

      ctx.requestClose(id);
    },
  };
}

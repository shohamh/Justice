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
      if (!ctx || !handlersRef.current.isDirty) {
        handlersRef.current.onDiscard();
        return;
      }
      ctx.requestClose(id);
    },
  };
}

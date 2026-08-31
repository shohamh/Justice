import { useEffect, useState } from "react";
import { LevelTypeDTO, listLevelTypes } from "../api/levelTypes";

export function useLevelTypes() {
  const [levelTypes, setLevelTypes] = useState<LevelTypeDTO[]>([]);
  const [loading, setLoading] = useState(true);

  async function refresh() {
    setLevelTypes(await listLevelTypes());
  }

  useEffect(() => {
    void refresh()
      .catch(() => {
        // Swallow: a failed initial fetch (e.g. a transient network error)
        // shouldn't surface as an unhandled rejection. Callers that invoke
        // refresh() directly (after create/delete/reorder) still see the
        // rejection via their own try/catch.
      })
      .finally(() => setLoading(false));
  }, []);

  return { levelTypes, loading, refresh };
}

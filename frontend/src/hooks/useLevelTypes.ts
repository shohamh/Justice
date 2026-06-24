import { useEffect, useState } from "react";
import { LevelTypeDTO, listLevelTypes } from "../api/levelTypes";

export function useLevelTypes() {
  const [levelTypes, setLevelTypes] = useState<LevelTypeDTO[]>([]);
  const [loading, setLoading] = useState(true);

  async function refresh() {
    setLevelTypes(await listLevelTypes());
  }

  useEffect(() => {
    void refresh().finally(() => setLoading(false));
  }, []);

  return { levelTypes, loading, refresh };
}

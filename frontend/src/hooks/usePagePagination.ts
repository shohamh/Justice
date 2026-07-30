import { useSearchParams } from "react-router-dom";
import { useCallback, useMemo } from "react";

interface Options {
  limit: number;
  paramName?: string;
}

interface Result {
  page: number;
  setPage: (page: number) => void;
  offset: number;
  limit: number;
}

export function usePagePagination({ limit, paramName = "page" }: Options): Result {
  const [searchParams, setSearchParams] = useSearchParams();

  const page = useMemo(() => {
    const raw = Number(searchParams.get(paramName) ?? "1");
    return Number.isFinite(raw) && raw >= 1 ? Math.floor(raw) : 1;
  }, [searchParams, paramName]);

  const setPage = useCallback(
    (next: number) => {
      setSearchParams((prev) => {
        const params = new URLSearchParams(prev);
        if (next <= 1) {
          params.delete(paramName);
        } else {
          params.set(paramName, String(next));
        }
        return params;
      });
    },
    [setSearchParams, paramName]
  );

  return { page, setPage, offset: (page - 1) * limit, limit };
}

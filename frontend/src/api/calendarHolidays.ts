import { api } from "./client";
import { optionalArrayResponse } from "./responseGuards";

export interface Holiday {
  date: string;
  name: string;
}

export async function listHolidays(year: number): Promise<Holiday[]> {
  const r = await api.get<unknown>("/calendar/holidays", { params: { year } });
  return optionalArrayResponse<Holiday>(r.data);
}

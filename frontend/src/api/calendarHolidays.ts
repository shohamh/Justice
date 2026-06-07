import { api } from "./client";

export interface Holiday {
  date: string;
  name: string;
}

export async function listHolidays(year: number): Promise<Holiday[]> {
  return (await api.get<Holiday[]>("/calendar/holidays", { params: { year } })).data;
}

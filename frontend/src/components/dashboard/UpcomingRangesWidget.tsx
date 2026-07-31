import { RangeEvent } from "../../api/ranges";

interface Props {
  ranges: RangeEvent[];
  onOpenRange: (range: RangeEvent) => void;
}

export default function UpcomingRangesWidget({ ranges, onOpenRange }: Props) {
  const today = new Date().toISOString().slice(0, 10);
  const upcoming = ranges
    .filter((r) => r.date > today && r.status === "planned")
    .sort((a, b) => a.date.localeCompare(b.date));

  return (
    <div dir="rtl">
      <h2>מטווחים קרובים</h2>
      <table>
        <thead>
          <tr>
            <th>תאריך</th>
            <th>סוג</th>
            <th>מיקום</th>
          </tr>
        </thead>
        <tbody>
          {upcoming.map((range) => (
            <tr key={range.id} onClick={() => onOpenRange(range)}>
              <td>{range.date}</td>
              <td>{range.range_type}</td>
              <td>{range.location}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

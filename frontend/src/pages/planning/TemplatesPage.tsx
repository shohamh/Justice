import Layout from "../../components/Layout";
import { ShiftTemplatesContent } from "../ShiftTemplatesPage";

export default function TemplatesPage() {
  return (
    <Layout>
      <section className="bg-white dark:bg-gray-800 rounded-lg shadow p-6 space-y-4" dir="rtl">
        <ShiftTemplatesContent />
      </section>
    </Layout>
  );
}

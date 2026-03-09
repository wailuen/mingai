import { redirect } from "next/navigation";

/**
 * Legacy route -- redirects to /settings/engineering-issues (FE-054).
 */
export default function Page() {
  redirect("/settings/engineering-issues");
}

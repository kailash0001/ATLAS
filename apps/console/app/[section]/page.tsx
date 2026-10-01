import Console from "../console";
import { signedIn } from "../session";
import { redirect } from "next/navigation";
export default async function Page() {
  if (!(await signedIn())) redirect("/login");
  return <Console />;
}

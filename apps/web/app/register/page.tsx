import Link from "next/link";

import { AuthCard } from "@/components/auth/AuthCard";
import { RegisterForm } from "@/components/auth/RegisterForm";


export const metadata = {
  title: "Create account · Atlas",
};


export default async function RegisterPage({
  searchParams,
}: {
  searchParams: Promise<{ next?: string }>;
}) {
  const sp = await searchParams;
  const nextPath = sp.next ?? null;
  return (
    <AuthCard
      title="Create account"
      subtitle="Atlas is currently in closed development. Accounts are provisioned for the private beta."
      footer={
        <p>
          Already have an account?{" "}
          <Link
            href={`/login${nextPath ? `?next=${encodeURIComponent(nextPath)}` : ""}`}
            className="text-accent hover:underline"
          >
            Sign in
          </Link>
          .
        </p>
      }
    >
      <RegisterForm nextPath={nextPath} />
    </AuthCard>
  );
}

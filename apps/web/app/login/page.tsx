import Link from "next/link";

import { AuthCard } from "@/components/auth/AuthCard";
import { LoginForm } from "@/components/auth/LoginForm";


export const metadata = {
  title: "Sign in · Atlas",
};


export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ next?: string }>;
}) {
  const sp = await searchParams;
  const nextPath = sp.next ?? null;
  return (
    <AuthCard
      title="Sign in"
      subtitle="Access your drawings, projects, and extractions."
      footer={
        <p>
          New to Atlas?{" "}
          <Link
            href={`/register${nextPath ? `?next=${encodeURIComponent(nextPath)}` : ""}`}
            className="text-accent hover:underline"
          >
            Create an account
          </Link>
          .
        </p>
      }
    >
      <LoginForm nextPath={nextPath} />
    </AuthCard>
  );
}

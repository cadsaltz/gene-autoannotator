"use client";

import Link from "next/link";

import { useSession } from "../SessionProvider";

const SIGNED_OUT_NOTE = "Passwordless: you sign in with a 6-digit code sent to your email.";
const SIGNED_IN_NOTE = "You're signed in. Submit a gene or check on your jobs.";

export default function HeroActions() {
  const { user } = useSession();

  if (user) {
    return (
      <div className="mt-8">
        <div className="flex flex-wrap gap-3">
          <Link href="/jobs" className="workbench-button guide-button-light min-h-11 px-5 text-sm">
            Go to Jobs
          </Link>
          <Link
            href="/annotations"
            className="workbench-button guide-button-outline min-h-11 px-5 text-sm"
          >
            Search annotations
          </Link>
        </div>
        <p className="guide-hero-muted mt-3 text-sm">{SIGNED_IN_NOTE}</p>
      </div>
    );
  }

  return (
    <div className="mt-8">
      <div className="flex flex-wrap gap-3">
        <Link href="/signup" className="workbench-button guide-button-light min-h-11 px-5 text-sm">
          Sign up
        </Link>
        <Link href="/login" className="workbench-button guide-button-outline min-h-11 px-5 text-sm">
          Sign in
        </Link>
      </div>
      <p className="guide-hero-muted mt-3 text-sm">{SIGNED_OUT_NOTE}</p>
    </div>
  );
}

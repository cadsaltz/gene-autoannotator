"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";

import { login, signup, verifyCode } from "../lib/authApi";
import { sanitizeNextPath } from "../lib/authPaths";

function AuthCard({ title, kicker, children, footer }) {
  return (
    <section className="mx-auto max-w-md">
      <div className="workbench-card p-7">
        <p className="workbench-kicker">{kicker}</p>
        <h1 className="workbench-foreground mt-2 text-3xl font-bold tracking-[-0.04em]">
          {title}
        </h1>
        <div className="mt-6">{children}</div>
        {footer ? <div className="mt-6 text-sm workbench-muted">{footer}</div> : null}
      </div>
    </section>
  );
}

function ErrorText({ message }) {
  if (!message) {
    return null;
  }
  return (
    <p className="workbench-amber-bg rounded-xl border workbench-border p-3 text-sm text-[#5f4b2e]">
      {message}
    </p>
  );
}

function verifyPageUrl(email, nextRaw) {
  const params = new URLSearchParams({
    email: email.trim(),
    next: sanitizeNextPath(nextRaw),
  });
  return `/auth/verify?${params.toString()}`;
}

export function SignupForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [email, setEmail] = useState("");
  const [username, setUsername] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event) {
    event.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      await signup(email.trim(), username.trim() || null);
      router.push(verifyPageUrl(email, searchParams.get("next")));
    } catch (err) {
      setError(err.message || "Signup failed");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <AuthCard
      kicker="Account"
      title="Sign up"
      footer={
        <>
          Already have an account?{" "}
          <Link href="/login" className="font-semibold underline">
            Sign in
          </Link>
        </>
      }
    >
      <form
        className="grid gap-4"
        method="post"
        action="/signup"
        onSubmit={handleSubmit}
      >
        <label className="grid gap-2 text-sm font-medium">
          Email
          <input
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            className="workbench-input"
            required
            autoComplete="email"
          />
        </label>
        <label className="grid gap-2 text-sm font-medium">
          Username (optional)
          <input
            type="text"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            className="workbench-input"
            autoComplete="username"
          />
        </label>
        <ErrorText message={error} />
        <button
          type="submit"
          className="workbench-button workbench-button-primary min-h-11 px-5 disabled:cursor-not-allowed disabled:opacity-50"
          disabled={submitting}
        >
          {submitting ? "Sending code…" : "Continue"}
        </button>
      </form>
    </AuthCard>
  );
}

export function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [email, setEmail] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event) {
    event.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      await login(email.trim());
      router.push(verifyPageUrl(email, searchParams.get("next")));
    } catch (err) {
      setError(err.message || "Login failed");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <AuthCard
      kicker="Account"
      title="Sign in"
      footer={
        <>
          Need an account?{" "}
          <Link href="/signup" className="font-semibold underline">
            Sign up
          </Link>
        </>
      }
    >
      <form
        className="grid gap-4"
        method="post"
        action="/login"
        onSubmit={handleSubmit}
      >
        <label className="grid gap-2 text-sm font-medium">
          Email
          <input
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            className="workbench-input"
            required
            autoComplete="email"
          />
        </label>
        <ErrorText message={error} />
        <button
          type="submit"
          className="workbench-button workbench-button-primary min-h-11 px-5 disabled:cursor-not-allowed disabled:opacity-50"
          disabled={submitting}
        >
          {submitting ? "Sending code…" : "Continue"}
        </button>
      </form>
    </AuthCard>
  );
}

export function VerifyForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const initialEmail = searchParams.get("email") || "";
  const nextPath = sanitizeNextPath(searchParams.get("next"));
  const [email, setEmail] = useState(initialEmail);
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event) {
    event.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      await verifyCode(email.trim(), code.trim());
      router.push(nextPath);
      router.refresh();
    } catch (err) {
      setError(err.message || "Verification failed");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <AuthCard kicker="Account" title="Enter verification code">
      <p className="workbench-muted mb-4 text-sm leading-6">
        We sent a 6-digit code to your email
        {email ? (
          <>
            {" "}
            (<span className="font-semibold workbench-foreground">{email}</span>)
          </>
        ) : null}
        . Check your inbox, or the backend logs when{" "}
        <code className="font-mono text-xs">EMAIL_BACKEND=console</code>.
      </p>
      <form
        className="grid gap-4"
        method="post"
        action="/auth/verify"
        onSubmit={handleSubmit}
      >
        <label className="grid gap-2 text-sm font-medium">
          Email
          <input
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            className="workbench-input"
            required
            autoComplete="email"
          />
        </label>
        <label className="grid gap-2 text-sm font-medium">
          6-digit code
          <input
            type="text"
            inputMode="numeric"
            pattern="[0-9]{6}"
            maxLength={6}
            value={code}
            onChange={(event) => setCode(event.target.value)}
            className="workbench-input font-mono tracking-[0.2em]"
            required
            autoComplete="one-time-code"
            placeholder="000000"
          />
        </label>
        <ErrorText message={error} />
        <button
          type="submit"
          className="workbench-button workbench-button-primary min-h-11 px-5 disabled:cursor-not-allowed disabled:opacity-50"
          disabled={submitting}
        >
          {submitting ? "Verifying…" : "Verify and continue"}
        </button>
      </form>
    </AuthCard>
  );
}

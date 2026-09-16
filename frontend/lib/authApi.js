import { apiFetch } from "./api.js";

export function signup(email, username) {
  return apiFetch("/auth/signup", {
    method: "POST",
    body: JSON.stringify({ email, username: username || null }),
  });
}

export function login(email) {
  return apiFetch("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email }),
  });
}

export function verifyCode(email, code) {
  return apiFetch("/auth/verify", {
    method: "POST",
    body: JSON.stringify({ email, code }),
  });
}

export function getMe() {
  return apiFetch("/auth/me");
}

export function logout() {
  return apiFetch("/auth/logout", { method: "POST" });
}

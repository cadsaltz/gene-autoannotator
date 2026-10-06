"use client";

import { createContext, useContext } from "react";

const SessionContext = createContext({ user: null, suspended: false });

export function SessionProvider({ session, children }) {
  return <SessionContext.Provider value={session}>{children}</SessionContext.Provider>;
}

export function useSession() {
  return useContext(SessionContext);
}

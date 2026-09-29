const GUIDE = { href: "/", label: "Guide" };

const guestNavItems = [
  GUIDE,
  { href: "/login", label: "Sign in" },
  { href: "/signup", label: "Sign up" },
];

const userNavItems = [
  GUIDE,
  { href: "/jobs", label: "Jobs" },
  { href: "/profiles", label: "Profiles" },
  { href: "/annotations", label: "Annotations" },
];

const adminNavItems = [
  GUIDE,
  { href: "/jobs", label: "Jobs" },
  { href: "/fleet", label: "Fleet & Health" },
  { href: "/profiles", label: "Profiles" },
  { href: "/annotations", label: "Annotations" },
  { href: "/admin", label: "Admin" },
];

export function navItemsFor(user) {
  if (!user) return guestNavItems.map((item) => ({ ...item }));
  const items = user.role === "admin" ? adminNavItems : userNavItems;
  return items.map((item) => ({ ...item }));
}

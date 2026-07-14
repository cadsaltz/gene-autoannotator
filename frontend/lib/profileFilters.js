export function filterProfiles(profiles, { query = "" } = {}) {
  return profiles.filter((profile) => profileMatchesQuery(profile, query));
}

export function groupProfilesBySpecies(profiles) {
  const groups = [];
  const bySpecies = new Map();
  for (const profile of profiles) {
    const speciesName = profile.species_name || "Unknown species";
    if (!bySpecies.has(speciesName)) {
      const group = { speciesName, profiles: [] };
      bySpecies.set(speciesName, group);
      groups.push(group);
    }
    bySpecies.get(speciesName).profiles.push(profile);
  }
  return groups;
}

function fieldValues(profile) {
  return [
    profile.profile_id,
    profile.canonical_name,
    profile.species_name,
    profile.strain,
    ...(profile.synonyms || []),
    ...(profile.species_synonyms || []),
    ...(profile.strain_synonyms || []),
  ];
}

function normalize(value) {
  return String(value || "").trim().toLocaleLowerCase();
}

function profileMatchesQuery(profile, query) {
  const normalizedQuery = normalize(query);
  if (!normalizedQuery) {
    return true;
  }
  return fieldValues(profile).some((value) =>
    normalize(value).includes(normalizedQuery),
  );
}

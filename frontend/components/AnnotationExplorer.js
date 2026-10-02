"use client";

import { useState } from "react";

import { getAnnotation, getAnnotationVersions, getProfile, searchAnnotations } from "../lib/api";
import { getHiddenMatchCount, getVisibleMatches } from "../lib/annotationMatches";
import { filterMatchesByOrganism, getOrganismOptions } from "../lib/annotationSummary";
import { CURRENT_VERSION_KEY } from "../lib/annotationVersions";
import { resolveProfileFieldsForDisplay } from "../lib/profileStore";
import AnnotationDetail from "./annotations/AnnotationDetail";
import ResultsRail from "./annotations/ResultsRail";

export default function AnnotationExplorer({ initialQuery = "", initialMatches = [], initialMessage = "" }) {
  const [query, setQuery] = useState(initialQuery);
  const [matches, setMatches] = useState(initialMatches);
  const [selected, setSelected] = useState(null);
  const [profileFields, setProfileFields] = useState(null);
  const [versions, setVersions] = useState(null);
  const [selectedVersionKey, setSelectedVersionKey] = useState(CURRENT_VERSION_KEY);
  const [isLoadingVersions, setIsLoadingVersions] = useState(false);
  const [message, setMessage] = useState(initialMessage);
  const [searchedQuery, setSearchedQuery] = useState(initialQuery);
  const [isSearching, setIsSearching] = useState(false);
  const [showAllMatches, setShowAllMatches] = useState(false);
  const [organism, setOrganism] = useState("");
  const [activeTab, setActiveTab] = useState("annotation");

  const filteredMatches = filterMatchesByOrganism(matches, organism);
  const hiddenMatchCount = showAllMatches ? 0 : getHiddenMatchCount(filteredMatches);
  const visibleMatches = getVisibleMatches(filteredMatches, showAllMatches);

  async function fetchVersions(annotationId) {
    setIsLoadingVersions(true);
    try {
      const payload = await getAnnotationVersions(annotationId);
      setVersions(payload.versions || []);
    } catch (error) {
      setMessage(error.message);
    } finally {
      setIsLoadingVersions(false);
    }
  }

  async function runSearch(nextQuery = query) {
    const trimmed = nextQuery.trim();
    if (!trimmed) {
      setMessage("Enter a locus, gene name, or organism-related term.");
      return;
    }

    setIsSearching(true);
    setMessage("");
    setSelected(null);
    setProfileFields(null);
    setVersions(null);
    setSelectedVersionKey(CURRENT_VERSION_KEY);
    setSearchedQuery(trimmed);
    setShowAllMatches(false);
    setOrganism("");

    try {
      const payload = await searchAnnotations(trimmed);
      setMatches(payload.matches || []);
    } catch (error) {
      setMatches([]);
      setMessage(error.message);
    } finally {
      setIsSearching(false);
    }
  }

  async function loadAnnotation(annotationId) {
    setMessage("");
    setVersions(null);
    setProfileFields(null);
    setSelectedVersionKey(CURRENT_VERSION_KEY);
    setActiveTab("annotation");

    try {
      const annotation = await getAnnotation(annotationId);
      setSelected(annotation);
      if (annotation.profile_id) {
        try {
          const profile = await getProfile(annotation.profile_id);
          setProfileFields(resolveProfileFieldsForDisplay(profile));
        } catch {
          // Fall back to the hard-coded field list when the profile is unavailable.
          setProfileFields(null);
        }
      }
      if ((annotation.version_count || 0) > 0) {
        await fetchVersions(annotationId);
      }
    } catch (error) {
      setMessage(error.message);
    }
  }

  async function loadVersions() {
    if (!selected) return;
    await fetchVersions(selected.id);
  }

  return (
    <div className="grid min-h-[calc(100vh-4rem)] lg:grid-cols-[320px_minmax(0,1fr)]">
      <ResultsRail
        query={query}
        onQueryChange={setQuery}
        onSearch={() => runSearch()}
        isSearching={isSearching}
        message={message}
        searchedQuery={searchedQuery}
        totalCount={filteredMatches.length}
        organisms={getOrganismOptions(matches)}
        organism={organism}
        onOrganismChange={(value) => {
          setOrganism(value);
          setShowAllMatches(false);
        }}
        matches={visibleMatches}
        hiddenCount={hiddenMatchCount}
        onShowAll={() => setShowAllMatches(true)}
        selectedId={selected?.id}
        onSelect={loadAnnotation}
      />
      <div className="min-w-0 px-4 py-6 sm:px-6 lg:px-8">
        <AnnotationDetail
          annotation={selected}
          profileFields={profileFields}
          versions={versions}
          selectedVersionKey={selectedVersionKey}
          onSelectVersion={setSelectedVersionKey}
          onLoadVersions={loadVersions}
          isLoadingVersions={isLoadingVersions}
          activeTab={activeTab}
          onTabChange={setActiveTab}
        />
      </div>
    </div>
  );
}

"use client";

import { useRef, useState } from "react";

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
  const searchRequest = useRef(0);
  const loadRequest = useRef(0);

  const filteredMatches = filterMatchesByOrganism(matches, organism);
  const hiddenMatchCount = showAllMatches ? 0 : getHiddenMatchCount(filteredMatches);
  const visibleMatches = getVisibleMatches(filteredMatches, showAllMatches);

  async function fetchVersions(annotationId, id) {
    const isCurrent = () => id === loadRequest.current;
    setIsLoadingVersions(true);
    try {
      const payload = await getAnnotationVersions(annotationId);
      if (!isCurrent()) return;
      setVersions(payload.versions || []);
    } catch (error) {
      if (!isCurrent()) return;
      setMessage(error.message);
    } finally {
      if (isCurrent()) setIsLoadingVersions(false);
    }
  }

  async function runSearch(nextQuery = query) {
    const trimmed = nextQuery.trim();
    if (!trimmed) {
      setMessage("Enter a locus, gene name, or organism-related term.");
      return;
    }

    searchRequest.current += 1;
    const id = searchRequest.current;
    loadRequest.current += 1;

    setIsSearching(true);
    setMessage("");
    setSelected(null);
    setProfileFields(null);
    setVersions(null);
    setIsLoadingVersions(false);
    setSelectedVersionKey(CURRENT_VERSION_KEY);
    setSearchedQuery(trimmed);
    setShowAllMatches(false);
    setOrganism("");

    try {
      const payload = await searchAnnotations(trimmed);
      if (id !== searchRequest.current) return;
      setMatches(payload.matches || []);
    } catch (error) {
      if (id !== searchRequest.current) return;
      setMatches([]);
      setMessage(error.message);
    } finally {
      if (id === searchRequest.current) setIsSearching(false);
    }
  }

  async function loadAnnotation(annotationId) {
    loadRequest.current += 1;
    const id = loadRequest.current;
    const isCurrent = () => id === loadRequest.current;

    setMessage("");
    setVersions(null);
    setIsLoadingVersions(false);
    setProfileFields(null);
    setSelectedVersionKey(CURRENT_VERSION_KEY);
    setActiveTab("annotation");

    try {
      const annotation = await getAnnotation(annotationId);
      if (!isCurrent()) return;
      setSelected(annotation);
      if (annotation.profile_id) {
        try {
          const profile = await getProfile(annotation.profile_id);
          if (!isCurrent()) return;
          setProfileFields(resolveProfileFieldsForDisplay(profile));
        } catch {
          if (!isCurrent()) return;
          // Fall back to the hard-coded field list when the profile is unavailable.
          setProfileFields(null);
        }
      }
      if ((annotation.version_count || 0) > 0) {
        await fetchVersions(annotationId, id);
      }
    } catch (error) {
      if (isCurrent()) setMessage(error.message);
    }
  }

  async function loadVersions() {
    if (!selected) return;
    await fetchVersions(selected.id, loadRequest.current);
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

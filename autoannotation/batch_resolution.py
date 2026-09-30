from __future__ import annotations

import re

from . import gene_names, targets


def _display_input(submitted_locus, submitted_name, raw_input):
    if submitted_locus and submitted_name:
        return f"{submitted_locus},{submitted_name}"
    return raw_input


def _resolve_with_profile(profile, **kwargs):
    return targets.resolve_annotation_target(
        profile_identifier=profile.profile_id,
        organism_identifier=None,
        strain_identifier=None,
        profile_lookup=lambda _identifier: profile,
        **kwargs,
    )


def resolve_batch_entry(
    profile,
    *,
    line,
    raw_input,
    submitted_locus,
    submitted_name,
    allow_online_name_lookup=False,
    selected_locus=None,
):
    if selected_locus:
        submitted_locus = selected_locus

    if submitted_locus and submitted_name:
        target = _resolve_with_profile(
            profile,
            locus=submitted_locus,
            name=submitted_name,
            allow_online_name_lookup=allow_online_name_lookup,
        )
        preflight = target.to_preflight_dict()
        return _entry_from_target(
            line=line,
            raw_input=_display_input(submitted_locus, submitted_name, raw_input),
            submitted_locus=submitted_locus,
            submitted_name=submitted_name,
            target=target,
            preflight=preflight,
            match_method="supplied_pair",
        )

    token = (submitted_locus or submitted_name or raw_input or "").strip()
    if not token:
        return _invalid_entry(line, raw_input, None, None, "empty_input")

    if profile.locus_regex and re.fullmatch(profile.locus_regex, token):
        target = _resolve_with_profile(
            profile,
            locus=token,
            name=None,
            allow_online_name_lookup=allow_online_name_lookup,
        )
        preflight = target.to_preflight_dict()
        return _entry_from_target(
            line=line,
            raw_input=token,
            submitted_locus=token,
            submitted_name=None,
            target=target,
            preflight=preflight,
            match_method="locus_regex",
        )

    table_result = gene_names.lookup_locus_from_annotation_table(profile, token)
    if table_result and table_result.locus:
        target = _resolve_with_profile(
            profile,
            locus=table_result.locus,
            name=token,
            allow_online_name_lookup=allow_online_name_lookup,
        )
        preflight = target.to_preflight_dict()
        return _entry_from_target(
            line=line,
            raw_input=token,
            submitted_locus=table_result.locus,
            submitted_name=token,
            target=target,
            preflight=preflight,
            match_method="annotation_table",
        )
    if table_result and table_result.candidates:
        return {
            "line": line,
            "input": token,
            "submitted_locus": None,
            "submitted_name": token,
            "resolved_locus": None,
            "resolved_name": None,
            "primary_identifier": None,
            "match_method": "annotation_table",
            "status": "ambiguous",
            "warnings": [{"code": "ambiguous_locus", "message": "Multiple loci matched this gene name."}],
            "candidates": list(table_result.candidates),
        }

    if allow_online_name_lookup:
        locus_result = gene_names.resolve_locus_from_gene_name(
            profile,
            token,
            allow_online_lookup=True,
        )
        if locus_result and locus_result.locus:
            target = _resolve_with_profile(
                profile,
                locus=locus_result.locus,
                name=token,
                allow_online_name_lookup=True,
            )
            preflight = target.to_preflight_dict()
            return _entry_from_target(
                line=line,
                raw_input=token,
                submitted_locus=locus_result.locus,
                submitted_name=token,
                target=target,
                preflight=preflight,
                match_method="online",
            )
        if locus_result and locus_result.candidates:
            return {
                "line": line,
                "input": token,
                "submitted_locus": None,
                "submitted_name": token,
                "resolved_locus": None,
                "resolved_name": None,
                "primary_identifier": None,
                "match_method": "online",
                "status": "ambiguous",
                "warnings": [{"code": "ambiguous_locus", "message": "Multiple loci matched this gene name."}],
                "candidates": list(locus_result.candidates),
            }

    if not profile.locus_regex:
        target = _resolve_with_profile(
            profile,
            locus=None,
            name=token,
            allow_online_name_lookup=allow_online_name_lookup,
        )
        preflight = target.to_preflight_dict()
        return _entry_from_target(
            line=line,
            raw_input=token,
            submitted_locus=None,
            submitted_name=token,
            target=target,
            preflight=preflight,
            match_method="name_only",
        )

    return _invalid_entry(
        line,
        token,
        None,
        token,
        "not_found",
        message="Could not resolve identifier for this profile.",
    )


def _entry_from_target(*, line, raw_input, submitted_locus, submitted_name, target, preflight, match_method):
    status = "ready" if preflight["valid"] else "invalid"
    return {
        "line": line,
        "input": raw_input,
        "submitted_locus": submitted_locus,
        "submitted_name": submitted_name,
        "resolved_locus": preflight["resolved_locus"],
        "resolved_name": preflight["resolved_name"],
        "primary_identifier": preflight["primary_identifier"],
        "match_method": match_method,
        "status": status,
        "warnings": preflight["warnings"],
        "candidates": [],
    }


def _invalid_entry(line, raw_input, submitted_locus, submitted_name, code, message="Invalid identifier."):
    return {
        "line": line,
        "input": raw_input or "",
        "submitted_locus": submitted_locus,
        "submitted_name": submitted_name,
        "resolved_locus": None,
        "resolved_name": None,
        "primary_identifier": None,
        "match_method": None,
        "status": "invalid",
        "warnings": [{"code": code, "message": message}],
        "candidates": [],
    }


def apply_deduplication(entries, *, profile_id):
    seen = set()
    deduped = []
    for entry in entries:
        if entry["status"] != "ready":
            deduped.append(entry)
            continue
        key = entry.get("resolved_locus")
        if not key:
            key = f"name:{(entry.get('resolved_name') or '').casefold()}"
        dedupe_key = f"{profile_id}:{key}"
        if dedupe_key in seen:
            entry = {**entry, "status": "duplicate_skipped"}
        else:
            seen.add(dedupe_key)
        deduped.append(entry)
    return deduped


def summarize_entries(entries):
    summary = {"total": len(entries), "ready": 0, "ambiguous": 0, "invalid": 0, "duplicate_skipped": 0}
    for entry in entries:
        summary[entry["status"]] = summary.get(entry["status"], 0) + 1
    return summary

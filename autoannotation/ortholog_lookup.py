import argparse
import json
import sys

from . import orthology
from . import targets
from .targets import TARGET_WARNING_MESSAGES


def _profile_lookup_from_env():
    """Prefer the local profile store so UI-saved kegg codes work."""
    try:
        from coordinator.profile_store import profile_store_from_env
    except Exception:
        return None
    try:
        store = profile_store_from_env()
    except Exception:
        return None

    def lookup(profile_id):
        try:
            return store.get_profile(profile_id)
        except Exception:
            return None

    return lookup


def lookup_for_target(
    *,
    profile=None,
    organism=None,
    strain=None,
    locus=None,
    cache_dir='./.cache',
    profile_lookup=None,
):
    target = targets.resolve_annotation_target(
        profile_identifier=profile,
        organism_identifier=organism,
        strain_identifier=strain,
        locus=locus,
        name=None,
        profile_lookup=profile_lookup,
    )
    kegg_code = target.profile.kegg_organism_code
    gene_locus = target.resolved_locus
    warnings = [
        {
            'code': warning,
            'message': TARGET_WARNING_MESSAGES.get(warning, warning),
        }
        for warning in target.warnings
    ]

    if not kegg_code:
        warnings.append({
            'code': 'missing_kegg_organism_code',
            'message': (
                f'Profile {target.profile.profile_id!r} has no kegg_organism_code; '
                'ortholog lookup requires a KEGG organism prefix (e.g. mtu, msm, tcr).'
            ),
        })
    if not gene_locus:
        warnings.append({
            'code': 'missing_locus',
            'message': 'Ortholog lookup requires a resolved locus identifier.',
        })

    ortholog_hit = None
    if kegg_code and gene_locus:
        ortholog_hit = orthology.lookup_top_ortholog(
            kegg_code,
            gene_locus,
            cache_dir=cache_dir,
        )
        if ortholog_hit is None:
            warnings.append({
                'code': 'no_ortholog_hit',
                'message': (
                    f'KEGG SSDB returned no cross-organism hit for {kegg_code}:{gene_locus}.'
                ),
            })

    return {
        'valid': bool(kegg_code and gene_locus),
        'profile_id': target.profile.profile_id,
        'canonical_name': target.profile.canonical_name,
        'kegg_organism_code': kegg_code,
        'submitted_locus': target.submitted_locus,
        'resolved_locus': gene_locus,
        'resolved_name': target.resolved_name,
        'primary_identifier': target.primary_identifier,
        'kegg_query': f'{kegg_code}:{gene_locus}' if kegg_code and gene_locus else None,
        'ortholog_top_hit': ortholog_hit.to_metadata() if ortholog_hit else None,
        'warnings': warnings,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            'Look up the top KEGG SSDB ortholog for a target gene. '
            'Resolves the organism profile and locus the same way as annotation jobs.'
        )
    )
    parser.add_argument(
        'identifier',
        nargs='?',
        help='Configured profile/species identifier for shorthand use, e.g. mtb-h37rv',
    )
    parser.add_argument(
        'positional_locus',
        nargs='?',
        help='Gene locus for shorthand use.',
    )
    parser.add_argument('--profile', help='Configured organism profile, e.g. mtb-h37rv.')
    parser.add_argument('--organism', help='Organism/species name or synonym.')
    parser.add_argument('--strain', help='Optional strain/isolate/reference name or synonym.')
    parser.add_argument('--locus', help='Gene locus to look up.')
    parser.add_argument(
        '-c', '--cache-dir',
        default='./.cache',
        help='Cache directory for KEGG SSDB responses (default: %(default)s).',
    )
    args = parser.parse_args(argv)

    locus = args.locus or args.positional_locus
    if args.profile and args.organism:
        parser.error('use either --profile or --organism, not both')
    if (args.profile or args.organism) and args.identifier:
        parser.error('do not combine positional identifier with --profile or --organism')
    if locus is None:
        parser.error('a locus is required')

    profile = args.profile
    organism = args.organism
    if not profile and not organism:
        if args.identifier:
            profile = args.identifier
        else:
            parser.error('an organism/profile identifier is required')

    result = lookup_for_target(
        profile=profile,
        organism=organism,
        strain=args.strain,
        locus=locus,
        cache_dir=args.cache_dir,
        profile_lookup=_profile_lookup_from_env(),
    )
    print(json.dumps(result, indent=2))
    return 0 if result['ortholog_top_hit'] is not None else 1


if __name__ == '__main__':
    sys.exit(main())

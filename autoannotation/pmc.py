import json
import logging
import os
import re
import math
from urllib.parse import urlencode
from dataclasses import dataclass, field
from datetime import datetime
import xml.etree.ElementTree as ET

from . import http_
from . import metadata
from . import papers
from . import utils

logging.basicConfig(format='%(asctime)s %(levelname).1s | %(message)s')
log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)

base_url = 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/'

search_url_tmpl = base_url + 'esearch.fcgi?db=pmc&retmax=5000&retmode=json&term={term}'
pubmed_search_url_tmpl = base_url + 'esearch.fcgi?db=pubmed&retmax=5000&retmode=json&term={term}'
search_term_locus_tmpl = '{locus}[title]+OR+{locus}[abstract]'
search_term_name_tmpl = (
    '(Mycobacterium+tuberculosis[abstract]+OR+Mycobacterium+tuberculosis[title])'
    '+AND+({name}[abstract]+OR+{name}[title])'
)

fetch_url_tmpl = base_url + 'efetch.fcgi?db=pmc&id={id}'
pubmed_to_pmc_url_tmpl = base_url + 'elink.fcgi?dbfrom=pubmed&db=pmc&retmode=json&{ids}'

DEFAULT_TARGET_RELEVANCE = 9.0
DEFAULT_MIN_PAPERS = 5
DEFAULT_MAX_PAPERS = 20
DEFAULT_MIN_SCORE = 0.1
DEFAULT_MAX_RANK = 20


@dataclass(frozen=True)
class OrganismProfile:
    canonical_name: str
    target_patterns: tuple[str, ...]
    off_target_patterns: tuple[str, ...] = ()
    excluded_species_patterns: tuple[str, ...] = ()


MTB_TARGET_ORGANISM_PATTERNS = (
    r'Mycobacterium\stuberculosis', r'M.\stuberculosis', r'M.\stb', 'MTB', 'Mtb', 'MTb', 'mTB'
)
MTB_EXCLUDED_SPECIES_PATTERNS = (
    r'Mycobacterium\ssmegmatis', r'M.\ssmegmatis', r'M.\ssmeg'
)
COMMON_OFF_TARGET_ORGANISM_PATTERNS = (
    r'\bEscherichia\s+coli\b', r'\bE\.?\s*coli\b',
)
DEFAULT_ORGANISM_PROFILE = OrganismProfile(
    canonical_name='Mycobacterium tuberculosis',
    target_patterns=MTB_TARGET_ORGANISM_PATTERNS,
    off_target_patterns=COMMON_OFF_TARGET_ORGANISM_PATTERNS + MTB_EXCLUDED_SPECIES_PATTERNS,
    excluded_species_patterns=MTB_EXCLUDED_SPECIES_PATTERNS,
)


@dataclass
class PaperSelectionResult:
    selected_records: list
    cumulative_relevance: float
    selection_mode: str
    eligible_count: int
    total_retrieved: int


@dataclass
class RelevanceRecord:
    pmc_id: str
    pmid: str | None
    score: float
    retrieval_sources: list[str]
    title: str
    year: int | None
    section_hits: dict[str, dict[str, int]]
    evidence_flags: dict[str, bool]
    score_components: dict[str, float]
    warnings: list[str] = field(default_factory=list)

class PmcPaperManager(papers.PaperManager):
    path_abstrct = 'abstracts'
    path_discusn = 'discussion'
    path_methods = 'methods'
    path_results = 'results'
    path_fulltxt = 'fulltxt'
    path_mapping = 'mapping'
    path_parsed = 'parsed'
    organism_profile = DEFAULT_ORGANISM_PROFILE
    species_incl_patterns = organism_profile.target_patterns
    species_excl_patterns = organism_profile.excluded_species_patterns
    off_target_species_patterns = organism_profile.off_target_patterns

    def __init__(self, cache_dir):
        super().__init__(cache_dir)
        log.info(f'Using dir {cache_dir} for caching PMC papers')
        self.throttler = http_.Throttler()

    def get_abstract(self, pmc_id):
        abstrct_path = os.path.join(self.abstrct_dir, f'PMC{pmc_id}_abstract.txt')
        if not os.path.isfile(abstrct_path):
            parsed_path = os.path.join(self.parsed_dir, f'PMC{pmc_id}.txt')
            if os.path.isfile(parsed_path):
                log.warning(f'No abstract available for paper PMC{pmc_id}')
                return None
            log.debug(f'No cached abstract for paper PMC{pmc_id}')
            self._parse(pmc_id)
        else:
            log.debug(f'Using cached abstract for paper PMC{pmc_id}')
        try:
            with open(abstrct_path, 'r', encoding='utf8') as abstrct_file:
                return re.sub(r'\n+', r'\n', abstrct_file.read())
        except FileNotFoundError:
            return None

    def get_discussion(self, pmc_id):
        discusn_path = os.path.join(self.discusn_dir, f'PMC{pmc_id}_discussion.txt')
        if not os.path.isfile(discusn_path):
            parsed_path = os.path.join(self.parsed_dir, f'PMC{pmc_id}.txt')
            if os.path.isfile(parsed_path):
                log.debug(f'No discussion available for paper PMC{pmc_id}')
                return None
            log.debug(f'No cached discussion for paper PMC{pmc_id}')
            self._parse(pmc_id)
        else:
            log.debug(f'Using cached discussion for paper PMC{pmc_id}')
        try:
            with open(discusn_path, 'r', encoding='utf8') as discusn_file:
                return re.sub(r'\n+', r'\n', discusn_file.read())
        except FileNotFoundError:
            return None

    def get_methods(self, pmc_id):
        methods_path = os.path.join(self.methods_dir, f'PMC{pmc_id}_methods.txt')
        if not os.path.isfile(methods_path):
            parsed_path = os.path.join(self.parsed_dir, f'PMC{pmc_id}.txt')
            if os.path.isfile(parsed_path):
                log.debug(f'No methods available for paper PMC{pmc_id}')
                return None
            log.debug(f'No cached methods for paper PMC{pmc_id}')
            self._parse(pmc_id)
        else:
            log.debug(f'Using cached methods for paper PMC{pmc_id}')
        try:
            with open(methods_path, 'r', encoding='utf8') as methods_file:
                return re.sub(r'\n+', r'\n', methods_file.read())
        except FileNotFoundError:
            return None

    def get_pmc_id_sources(self, gene, name):
        log.info(f'Searching PubMed Central for gene {gene}')

        search_term_locus = search_term_locus_tmpl.format(locus=gene)
        search_url1 = search_url_tmpl.format(term=search_term_locus)

        log.debug(f'Searching PubMed Central by gene locus {gene}')
        idlist1 = self._search_pmc_idlist(search_url1, search_term_locus, f'{gene} locus')
        log.debug(
            f'Found {len(idlist1)} paper{utils.s_if_plural(idlist1)} by locus for gene {gene}'
        )

        if name == gene:
            log.debug(f'No name available for gene {gene}; moving on with obtained papers')
            return {pmc_id: {'locus'} for pmc_id in idlist1}

        log.debug(f'Searching PubMed Central by gene name {name}')

        search_term_name = search_term_name_tmpl.format(name=name)
        search_url2 = search_url_tmpl.format(term=search_term_name)

        idlist2 = self._search_pmc_idlist(search_url2, search_term_name, f'{gene} name')
        log.debug(f'Found {len(idlist2)} papers by name ({name}) for gene {gene}')

        combined = {}
        for pmc_id in idlist1:
            combined.setdefault(pmc_id, set()).add('locus')
        for pmc_id in idlist2:
            combined.setdefault(pmc_id, set()).add('name')

        if len(combined) < 3:
            log.warning(
                f'Found only {len(combined)} paper{utils.s_if_plural(combined)} for gene {gene}'
            )
        else:
            log.debug(
                f'That makes total of {len(combined)} paper{utils.s_if_plural(combined)} for ' + \
                    f'gene {gene}'
            )

        return combined

    def _search_pmc_idlist(self, pmc_search_url, search_term, query_label):
        response = self.throttler.get(pmc_search_url, base_url)
        result = json.loads(response.text)
        try:
            return self._extract_esearch_idlist(result, query_label)
        except RuntimeError as exc:
            log.warning(
                f'PMC search unavailable for {query_label} query ({exc}); '
                'falling back to PubMed-to-PMC links'
            )
            return self._search_pubmed_for_pmc_ids(search_term, query_label)

    def _search_pubmed_for_pmc_ids(self, search_term, query_label):
        pubmed_search_url = pubmed_search_url_tmpl.format(term=search_term)
        response = self.throttler.get(pubmed_search_url, base_url)
        result = json.loads(response.text)
        pubmed_ids = self._extract_esearch_idlist(result, f'{query_label} PubMed fallback')
        return self._get_pmc_ids_for_pubmed_ids(pubmed_ids)

    def _extract_esearch_idlist(self, result, query_label):
        esearch_result = result.get('esearchresult') if isinstance(result, dict) else None
        if not isinstance(esearch_result, dict):
            raise RuntimeError(f'NCBI ESearch returned malformed response for {query_label}')
        if 'idlist' in esearch_result:
            idlist = esearch_result['idlist']
            if not isinstance(idlist, list):
                raise RuntimeError(f'NCBI ESearch returned non-list idlist for {query_label}')
            return idlist
        if 'ERROR' in esearch_result:
            raise RuntimeError(f"NCBI ESearch error for {query_label}: {esearch_result['ERROR']}")
        raise RuntimeError(f'NCBI ESearch response missing idlist for {query_label}')

    def _get_pmc_ids_for_pubmed_ids(self, pubmed_ids):
        if not pubmed_ids:
            return []
        query = urlencode([('id', pubmed_id) for pubmed_id in pubmed_ids])
        url = pubmed_to_pmc_url_tmpl.format(ids=query)
        response = self.throttler.get(url, base_url)
        result = json.loads(response.text)
        pmc_ids = []
        seen = set()
        for linkset in result.get('linksets', []):
            for linksetdb in linkset.get('linksetdbs', []):
                if linksetdb.get('linkname') != 'pubmed_pmc':
                    continue
                for pmc_id in linksetdb.get('links', []):
                    if pmc_id in seen:
                        continue
                    pmc_ids.append(pmc_id)
                    seen.add(pmc_id)
        return pmc_ids

    def get_pmc_ids(self, gene, name):
        return list(self.get_pmc_id_sources(gene, name).keys())

    def get_pmid(self, pmc_id):
        if pmc_id.startswith('PMC'):
            pmc_id = pmc_id[3:]
        article_xml = self._get_article_xml(pmc_id)
        article_meta = article_xml.find('front').find('article-meta')
        try:
            return article_meta.find('article-id[@pub-id-type="pmid"]').text
        except AttributeError as ae:
            log.exception(f'Failed PMID fetch for paper PMC{pmc_id}')

    def get_results(self, pmc_id):
        results_path = os.path.join(self.results_dir, f'PMC{pmc_id}_results.txt')
        if not os.path.isfile(results_path):
            parsed_path = os.path.join(self.parsed_dir, f'PMC{pmc_id}.txt')
            if os.path.isfile(parsed_path):
                log.debug(f'No results available for paper PMC{pmc_id}')
                return None
            log.debug(f'No cached results for paper PMC{pmc_id}')
            self._parse(pmc_id)
        else:
            log.debug(f'Using cached results for paper PMC{pmc_id}')
        try:
            with open(results_path, 'r', encoding='utf8') as results_file:
                return re.sub(r'\n+', r'\n', results_file.read())
        except FileNotFoundError:
            return None

    def is_relevant(self, pmc_id, gene, name):
        record = self.score_paper_relevance(pmc_id, gene, name)
        return (
            record.score >= 0.25
            and record.evidence_flags['has_organism_hit']
            and (record.evidence_flags['has_locus_hit'] or record.evidence_flags['has_name_hit'])
            and not record.evidence_flags['has_excluded_species_hit']
        )

    def relevance_score(self, pmc_id, gene, name):
        return self.score_paper_relevance(pmc_id, gene, name).score

    def score_paper_relevance(self, pmc_id, gene, name, retrieval_sources=None):
        retrieval_sources = set(retrieval_sources or [])
        title = self._get_title(pmc_id)
        year = self._get_publication_year(pmc_id)

        abstract = self.get_abstract(pmc_id)
        gene_lower = gene.lower()
        name_lower = name.lower()
        sections = {
            'title': title or '',
            'abstract': abstract or '',
            'results': self.get_results(pmc_id) or '',
            'discussion': self.get_discussion(pmc_id) or '',
        }
        section_hits = {
            label: {
                'locus': text.lower().count(gene_lower),
                'name': 0 if name_lower == gene_lower else text.lower().count(name_lower),
                'target_organism': self._count_patterns(text, self.species_incl_patterns),
                'organism': self._count_patterns(text, self.species_incl_patterns),
                'off_target_organism': self._count_patterns(
                    text, self.off_target_species_patterns,
                ),
                'excluded_species': self._count_patterns(text, self.species_excl_patterns),
            }
            for label, text in sections.items()
        }

        has_locus_hit = any(hits['locus'] > 0 for hits in section_hits.values())
        has_name_hit = any(hits['name'] > 0 for hits in section_hits.values())
        target_organism_hits = sum(
            hits['target_organism'] for hits in section_hits.values()
        )
        off_target_organism_hits = sum(
            hits['off_target_organism'] for hits in section_hits.values()
        )
        has_organism_hit = target_organism_hits > 0
        has_off_target_organism_hit = off_target_organism_hits > 0
        has_excluded_species_hit = any(
            hits['excluded_species'] > 0 for hits in section_hits.values()
        )
        has_results_hit = (
            section_hits['results']['locus'] + section_hits['results']['name']
        ) > 0
        has_discussion_hit = (
            section_hits['discussion']['locus'] + section_hits['discussion']['name']
        ) > 0
        has_strong_target_gene_evidence = any(
            hits['target_organism'] > 0 and (hits['locus'] > 0 or hits['name'] > 0)
            for hits in section_hits.values()
        )
        is_off_target_organism_dominant = (
            has_off_target_organism_hit
            and (
                not has_organism_hit
                or (
                    off_target_organism_hits > target_organism_hits
                    and not has_strong_target_gene_evidence
                )
            )
        )

        score_components = {
            'retrieval_locus': 0.18 if 'locus' in retrieval_sources else 0.0,
            'retrieval_name': 0.08 if 'name' in retrieval_sources else 0.0,
            'title_locus': 0.35 if section_hits['title']['locus'] else 0.0,
            'title_name': 0.25 if section_hits['title']['name'] else 0.0,
            'title_organism': 0.08 if section_hits['title']['organism'] else 0.0,
            'abstract_locus': min(section_hits['abstract']['locus'] * 0.08, 0.24),
            'abstract_name': min(section_hits['abstract']['name'] * 0.05, 0.15),
            'abstract_organism': 0.12 if section_hits['abstract']['organism'] else 0.0,
            'section_locus': min(
                (section_hits['results']['locus'] + section_hits['discussion']['locus']) * 0.07,
                0.21,
            ),
            'section_name': min(
                (section_hits['results']['name'] + section_hits['discussion']['name']) * 0.05,
                0.15,
            ),
            'section_organism': 0.08 if (
                section_hits['results']['organism'] or section_hits['discussion']['organism']
            ) else 0.0,
            'organism_gene_comention': 0.15 if (
                has_organism_hit and (has_locus_hit or has_name_hit)
            ) else 0.0,
            'recency': self._recency_bonus(year),
            'missing_abstract_penalty': -0.08 if abstract is None else 0.0,
            'missing_organism_penalty': -0.18 if not has_organism_hit else 0.0,
            'name_only_penalty': -0.12 if (
                has_name_hit and not has_locus_hit and 'locus' not in retrieval_sources
            ) else 0.0,
            'off_target_organism_penalty': -0.20 if is_off_target_organism_dominant else 0.0,
            'excluded_species_penalty': -0.25 if has_excluded_species_hit else 0.0,
        }

        warnings = []
        if abstract is None:
            warnings.append('missing_abstract')
        if has_excluded_species_hit:
            warnings.append('excluded_species')
        if has_name_hit and not has_locus_hit:
            warnings.append('name_only_match')
        if not has_organism_hit:
            warnings.append('missing_target_organism')
            warnings.append('missing_organism')
        if is_off_target_organism_dominant:
            warnings.append('off_target_organism_dominant')

        score = max(0.0, min(sum(score_components.values()), 1.0))
        return RelevanceRecord(
            pmc_id=pmc_id,
            pmid=self.get_pmid(pmc_id),
            score=round(score, 3),
            retrieval_sources=sorted(retrieval_sources),
            title=title,
            year=year,
            section_hits=section_hits,
            evidence_flags={
                'has_locus_hit': has_locus_hit,
                'has_name_hit': has_name_hit,
                'has_organism_hit': has_organism_hit,
                'has_target_organism_hit': has_organism_hit,
                'has_off_target_organism_hit': has_off_target_organism_hit,
                'has_excluded_species_hit': has_excluded_species_hit,
                'has_strong_target_gene_evidence': has_strong_target_gene_evidence,
                'is_off_target_organism_dominant': is_off_target_organism_dominant,
                'has_results_hit': has_results_hit,
                'has_discussion_hit': has_discussion_hit,
            },
            score_components={
                key: round(value, 3)
                for key, value in score_components.items()
                if value != 0
            },
            warnings=warnings,
        )

    def get_ranked_papers(self, gene, name):
        pmc_sources = self.get_pmc_id_sources(gene, name)
        records = [
            self.score_paper_relevance(pmc_id, gene, name, sources)
            for pmc_id, sources in pmc_sources.items()
        ]
        return sorted(records, key=lambda record: record.score, reverse=True)

    def select_papers_to_analyze(
        self, all_ids, gene, name,
        target_relevance=DEFAULT_TARGET_RELEVANCE,
        min_score=DEFAULT_MIN_SCORE,
        max_rank=DEFAULT_MAX_RANK,
        min_papers=DEFAULT_MIN_PAPERS,
        max_papers=DEFAULT_MAX_PAPERS,
    ):
        if all(isinstance(record, RelevanceRecord) for record in all_ids):
            records = list(all_ids)
        else:
            source_map = {}
            try:
                source_map = self.get_pmc_id_sources(gene, name)
            except Exception:
                log.debug('Unable to fetch PMC ID sources during selection; scoring without provenance')
            records = [
                self.score_paper_relevance(pmc_id, gene, name, source_map.get(pmc_id, set()))
                for pmc_id in all_ids
            ]
            records = sorted(records, key=lambda record: record.score, reverse=True)

        selection = self.select_relevance_records(
            records,
            target_relevance=target_relevance,
            min_score=min_score,
            max_rank=max_rank,
            min_papers=min_papers,
            max_papers=max_papers,
        )
        return (
            [record.pmc_id for record in selection.selected_records],
            selection.cumulative_relevance,
        )

    def select_relevance_records(
        self, records,
        target_relevance=DEFAULT_TARGET_RELEVANCE,
        min_score=DEFAULT_MIN_SCORE,
        max_rank=DEFAULT_MAX_RANK,
        min_papers=DEFAULT_MIN_PAPERS,
        max_papers=DEFAULT_MAX_PAPERS,
        excluded_warnings=None,
    ):
        excluded_warnings = set(excluded_warnings or metadata.DEFAULT_EXCLUDED_WARNINGS)
        eligible_records = metadata.filter_eligible_records(
            records, min_score=min_score, excluded_warnings=excluded_warnings,
        )
        total_retrieved = len(records)

        if len(eligible_records) <= min_papers:
            selected_records = eligible_records[:max_papers]
            return PaperSelectionResult(
                selected_records=selected_records,
                cumulative_relevance=metadata.compute_cumulative_relevance(selected_records),
                selection_mode=metadata.SELECTION_MODE_LIMITED,
                eligible_count=len(eligible_records),
                total_retrieved=total_retrieved,
            )

        selected_records = []
        running_relevance = 0.0
        selected_rank = 0
        eligible_ids = {record.pmc_id for record in eligible_records}

        for rank, record in enumerate(records, start=1):
            if rank > max_rank:
                break

            if record.pmc_id not in eligible_ids:
                continue

            selected_rank += 1
            running_relevance += 2 * record.score / math.log2(selected_rank + 1)
            selected_records.append(record)

            if len(selected_records) >= max_papers:
                break

            if (
                running_relevance >= target_relevance
                and len(selected_records) >= min_papers
            ):
                break

        return PaperSelectionResult(
            selected_records=selected_records,
            cumulative_relevance=running_relevance,
            selection_mode=metadata.SELECTION_MODE_BUDGET,
            eligible_count=len(eligible_records),
            total_retrieved=total_retrieved,
        )

    def _get_title(self, pmc_id):
        try:
            title_elem = (
                self._get_article_xml(pmc_id)
                .find('front')
                .find('article-meta')
                .find('title-group')
                .find('article-title')
            )
            return ET.tostring(title_elem, encoding='unicode', method='text')
        except AttributeError:
            return ''

    def _get_publication_year(self, pmc_id):
        try:
            pub_year_elem = (
                self._get_article_xml(pmc_id)
                .find('front')
                .find('article-meta')
                .find('.//pub-date/year')
            )
            return int(pub_year_elem.text)
        except Exception:
            return None

    def _recency_bonus(self, pub_year):
        if pub_year is None:
            return 0.0
        current_year = datetime.now().year
        age = current_year - pub_year
        return max(0.0, 1.0 - (age / 20.0)) * 0.05

    def _count_patterns(self, text, patterns):
        return sum(len(re.findall(pattern, text, flags=re.IGNORECASE)) for pattern in patterns)


    def save_gene_pmc_ids(self, gene, pmc_ids):
        log.debug(
            f'Recording {len(pmc_ids)} paper{utils.s_if_plural(pmc_ids)} relevant to gene {gene}'
        )
        gene_pmc_ids_path = os.path.join(self.mapping_dir, f'{gene}.txt')
        with open(gene_pmc_ids_path, 'w', encoding='utf8') as gene_pmc_ids_file:
            gene_pmc_ids_file.write('\n'.join(pmc_ids))
            gene_pmc_ids_file.write('\n')

    def _download(self, pmc_id):
        log.debug(f'Downloading paper PMC{pmc_id} from PubMed Central')
        fetch_url = fetch_url_tmpl.format(id=pmc_id)

        response = self.throttler.get(fetch_url, base_url)

        fulltxt_path = os.path.join(self.fulltxt_dir, f'PMC{pmc_id}.xml')
        with open(fulltxt_path, 'w', encoding='utf8') as fulltxt_file:
            fulltxt_file.write(response.text)

        return response.text

    def _get_article_xml(self, pmc_id):
        fulltxt_path = os.path.join(self.fulltxt_dir, f'PMC{pmc_id}.xml')
        if os.path.isfile(fulltxt_path):
            xml_tree = ET.parse(fulltxt_path)
            root = xml_tree.getroot()
        else:
            root = ET.fromstring(self._download(pmc_id))

        return root[0]

    def _parse(self, pmc_id):
        parsed_path = os.path.join(self.parsed_dir, f'PMC{pmc_id}.txt')
        if os.path.exists(parsed_path):
            log.debug(f'Paper PMC{pmc_id} already parsed')
            return
        log.debug(f'Parsing paper PMC{pmc_id}')

        article_xml = self._get_article_xml(pmc_id)

        # abstract
        try:
            self._save_section(
                article_xml.find('front').find('article-meta').find('abstract'),
                os.path.join(self.abstrct_dir, f'PMC{pmc_id}_abstract.txt')
            )
        except AttributeError as ae:
            log.debug(f'Paper PMC{pmc_id} missing abstract')
            return

        # all other sections
        body = article_xml.find('body')
        if body is None:
            with open(parsed_path, 'w', encoding='utf8') as parsed_file:
                parsed_file.write('')
            log.debug(f'No paper body available for PMC{pmc_id}')
            return

        for section in body.findall('sec'):
            section_type = section.get('sec-type')
            if section_type is None:
                try:
                    section_type = section.find('title').text.lower()
                except AttributeError as ae:
                    log.info(
                        f'Paper PMC{pmc_id} has untitled body section; we may miss valid data'
                    )
                    continue

            if 'discussion' in section_type:
                log.debug(f'Saving discussion for paper PMC{pmc_id}')
                self._save_section(
                    section,
                    os.path.join(self.discusn_dir, f'PMC{pmc_id}_discussion.txt')
                )
            # if, not elif, since we may have combined sections
            if 'methods' in section_type or 'procedures' in section_type:
                log.debug(f'Saving methods for paper PMC{pmc_id}')
                self._save_section(
                    section,
                    os.path.join(self.methods_dir, f'PMC{pmc_id}_methods.txt')
                )
            # if, not elif, since we may have combined sections
            if 'results' in section_type:
                log.debug(f'Saving results for paper PMC{pmc_id}')
                self._save_section(
                    section,
                    os.path.join(self.results_dir, f'PMC{pmc_id}_results.txt')
                )

        with open(parsed_path, 'w', encoding='utf8') as parsed_file:
            parsed_file.write('')

    def _save_section(self, xml_element, filepath):
        with open(filepath, 'wb') as section_file: # b mode since ET.tostring with utf8 yields bytes
            section_file.write(ET.tostring(xml_element, encoding='utf8', method='text'))

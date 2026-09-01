from autoannotation.autoannotation import _sections_for_extraction


class FakePaperManager:
    def __init__(self, sections_by_pmc):
        self._sections_by_pmc = sections_by_pmc

    def get_abstract(self, pmc_id):
        return None

    def get_results(self, pmc_id):
        return self._sections_by_pmc.get(pmc_id)

    def get_discussion(self, pmc_id):
        return None


def _set_tier2_env(monkeypatch):
    monkeypatch.setenv("AUTOANNOTATION_SECTION_EXCERPT_MAX_CHARS", "100")
    monkeypatch.setenv("AUTOANNOTATION_SECTION_RETRIEVAL_THRESHOLD_CHARS", "10000")


def test_sections_for_extraction_expands_oversize(monkeypatch):
    _set_tier2_env(monkeypatch)
    p1 = "A" * 60
    p2 = "B" * 60
    fat_results = f"{p1}\n\n{p2}"
    pm = FakePaperManager({"1": fat_results})

    sections = _sections_for_extraction(pm, "1", gene="Rv0001", name="dnaA")

    assert all(len(text) <= 100 for _, text in sections)
    assert len(sections) >= 2
    assert sections[0][0] == "results#1"
    assert sections[1][0] == "results#2"


def test_sections_for_extraction_keeps_small_sections(monkeypatch):
    _set_tier2_env(monkeypatch)
    pm = FakePaperManager({"1": "short results text"})
    sections = _sections_for_extraction(pm, "1", gene="Rv0001", name="dnaA")
    assert sections == [("results", "short results text")]


def test_sections_for_extraction_uses_grep_for_long_sections(monkeypatch):
    monkeypatch.setenv("AUTOANNOTATION_SECTION_EXCERPT_MAX_CHARS", "100")
    monkeypatch.setenv("AUTOANNOTATION_SECTION_RETRIEVAL_THRESHOLD_CHARS", "500")
    text = "Z" * 600 + "Rv0001" + "Y" * 600
    pm = FakePaperManager({"1": text})

    sections = _sections_for_extraction(pm, "1", gene="Rv0001", name="dnaA")

    assert len(sections) >= 1
    assert sections[0][0] == "results#grep"
    assert "Rv0001" in sections[0][1]
    assert len(sections[0][1]) <= 100


def test_sections_for_extraction_skips_expand_when_chunking_disabled(monkeypatch):
    monkeypatch.setenv("AUTOANNOTATION_SECTION_CHUNKING", "false")
    p1 = "A" * 60
    p2 = "B" * 60
    fat = f"{p1}\n\n{p2}"
    pm = FakePaperManager({"1": fat})
    sections = _sections_for_extraction(pm, "1", gene="Rv0001", name="dnaA")
    assert sections == [("results", fat)]

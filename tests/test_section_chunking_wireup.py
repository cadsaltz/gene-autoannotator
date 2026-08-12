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


def test_sections_for_extraction_expands_oversize():
    p1 = "A" * 60
    p2 = "B" * 60
    fat_results = f"{p1}\n\n{p2}"
    pm = FakePaperManager({"1": fat_results})

    sections = _sections_for_extraction(pm, "1", max_chars=100)

    assert all(len(text) <= 100 for _, text in sections)
    assert len(sections) >= 2
    assert sections[0][0] == "results#1"
    assert sections[1][0] == "results#2"


def test_sections_for_extraction_keeps_small_sections():
    pm = FakePaperManager({"1": "short results text"})
    sections = _sections_for_extraction(pm, "1", max_chars=100)
    assert sections == [("results", "short results text")]

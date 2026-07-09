import json

from autoannotation import llms
from compareannotations.scoring import llm_similarity

def test_llm_same_fact_same_text():
	
	cases = [
		("December fifth is my birthday","December fifth is my birthday"),
		("The gene is expressed in liver tissue","The gene is expressed in liver tissue")
	]

	for a, b in cases:
		score = llm_similarity(a,b)
		assert score > 0.7, f"\nA: {a}\nB: {b}\nScore: {score}"


def test_llm_same_fact_different_text():
	
	cases = [
		("December fifth is my birthday","I was born on December fifth"),
		("The gene is expressed in liver tissue","Gene expression occurs in the liver"),
		("The protein binds to DNA","DNA binding occurs via the protein"),
		("The sample was collected in Seattle","Collection location was Seattle"),
		("Directed deletion of ΔfadE5 confirmed its reduced RIF fitness","Loss of fadE5 through directed deletion validated its decreased fitness under rifampicin exposure"),
		("Directed deletion of ΔprpD confirmed its predicted enhanced RIF fitness","Targeted deletion of prpD validated its expected increase in rifampicin-associated fitness"),
		("STM (streptomycin) reduced-survival mutants involved toxin-antitoxin systems","Genes linked to toxin–antitoxin systems were enriched among streptomycin reduced-survival mutants"),
		("RIF and STM survival mechanisms were largely distinct","Survival mechanisms under RIF and STM selection showed minimal overlap")
	]

	for a, b in cases:
		score = llm_similarity(a,b)
		assert score > 0.6, f"\nA: {a}\nB: {b}\nScore: {score}"

def test_llm_different_fact_same_text():
	
	cases = [
		("I was born on December fourth","I was born on December fifth"),
		("The gene is expressed in liver tissue","The gene is expressed in kidney tissue"),
		("The protein binds to DNA","The protein binds to RNA"),
		("The sample was collected in Seattle","The sample was collected in Boston"),
		("Directed deletion of ΔfadE5 confirmed its reduced RIF fitness","Directed deletion of ΔfadE5 confirmed its increased STM fitness"),
		("Directed deletion of ΔprpD confirmed its predicted enhanced RIF fitness","Directed deletion of ΔprpD confirmed its reduced STM fitness"),
		("STM (streptomycin) reduced-survival mutants involved toxin-antitoxin systems","RIF reduced-survival mutants involved toxin-antitoxin systems"),
		("RIF and STM survival mechanisms were largely distinct","RIF and STM survival mechanisms were largely identical across all detected mutants")
	]

	for a, b in cases:
		score = llm_similarity(a,b)
		assert score < 0.5, f"\nA: {a}\nB: {b}\nScore: {score}"


def test_llm_different_fact_different_text():
	
	cases = [
		("I was born on December fourth","December fifth is my birthday"),
		("The gene is expressed in liver tissue","Gene expression occcurs in the kidney"),
		("The protein binds to DNA","RNA binding occurs via the protein"),
		("The sample was collected in Seattle","Collection location was Boston"),
		("Directed deletion of ΔfadE5 confirmed its reduced RIF fitness","Knockout of prpD showed no measurable effect on antibiotic survival in vitro"),
		("Directed deletion of ΔprpD confirmed its predicted enhanced RIF fitness","Insertional disruption of gidB led to loss of streptomycin resistance in clinical isolates"),
		("STM (streptomycin) reduced-survival mutants involved toxin-antitoxin systems","Rifampicin-selected mutants were primarily enriched in cell wall synthesis genes rather than regulatory systems"),
		("RIF and STM survival mechanisms were largely distinct","Antibiotic treatment led to a shared set of metabolic adaptations across both drug conditions")
	]

	for a, b in cases:
		score = llm_similarity(a,b)
		assert score < 0.4, f"\nA: {a}\nB: {b}\nScore: {score}"


def test_llm_contradiction():
	
	cases = [
		("True","False"),
		("The gene is expressed in liver","The gene is not expressed in liver"),
		("The protein binds DNA","The protein does not bind DNA")
	]

	for a, b in cases:
		score = llm_similarity(a,b)
		assert score < 0.3, f"\nA: {a}\nB: {b}\nScore: {score}"


def test_llm_same_numbers():
	
	cases = [
		("10","10"),
		("300","300"),
		("846","846")
	]

	for a, b in cases:
		score = llm_similarity(a,b)
		assert score > 0.8, f"\nA: {a}\nB: {b}\nScore: {score}"


def test_llm_different_numbers():
	
	cases = [
		("10","11"),
		("300","900"),
		("846","52")
	]

	for a, b in cases:
		score = llm_similarity(a,b)
		assert score < 0.6, f"\nA: {a}\nB: {b}\nScore: {score}"


def test_llm_same_number_text():
	
	cases = [
		("The gene expression level increased by 10%","The gene expression level increased by 10%"),
		("5 mg/mL is the protein concentration","The protein concentration is 5 mg/mL")
	]

	for a, b in cases:
		score = llm_similarity(a,b)
		assert score > 0.5, f"\nA: {a}\nB: {b}\nScore: {score}"


def test_llm_different_number_text():
	
	cases = [
		("The gene has 1 functional copy of the gene","The gene has 2 functional copies of the gene"),
		("The gene expression level increased by 10%","The gene expression level increased by 45%"),
		("The protein concentration is 5.0 mg/mL","The protein concentration is 20 mg/mL"),
		("The enzyme is active at 1 copy per cell","The enzyme is active at 3 copies per cell")
	]

	for a, b in cases:
		score = llm_similarity(a,b)
		assert score < 0.5, f"\nA: {a}\nB: {b}\nScore: {score}"

def test_llm_missing_null_text():

	cases = [
		("The gene expression level increased by 10%","Null"),
		("The gene expression level increased by 10%","Unknown"),
		("The gene expression level increased by 10%","Missing")
	]

	for a, b in cases:
		score = llm_similarity(a,b)
		assert score < 0.5, f"\nA: {a}\nB: {b}\nScore: {score}"


def test_json_schema_allows_null_gene_id_for_name_only_target():
	schema = llms.build_json_schema(
		require_biology=True,
		aggregate=True,
		allow_missing_locus=True,
	)

	assert schema["properties"]["gene_id"]["type"] == ["string", "null"]
	assert "gene_id" in schema["required"]


def test_identity_prompt_tells_model_not_to_invent_missing_locus():
	prompt = llms.build_section_prompt(
		gene=None,
		name="abc1",
		text="abc1 is required for growth.",
		section_type="abstract",
		organism_profile=None,
	)

	assert "Do not invent a locus identifier" in prompt
	assert "No locus identifier was supplied or resolved" in prompt
	assert "gene_id to null" in prompt
	assert "named abc1" in prompt
	assert "unknown locus" not in prompt


def test_json_filter_accepts_null_gene_id_for_name_only_target():
	handler = llms.LlmHandler(".cache")
	response = '{"gene_id": null, "name": "abc1", "function": null, "functional_category": null, "drug_susc_impact": null, "infection_impact": null, "essential_in_vitro": null, "essential_in_vivo": null}'

	assert handler.json_regex_filter(
		response,
		organism_profile=None,
		expected_gene=None,
	) is True


def test_json_filter_rejects_null_gene_id_when_expected_gene_exists():
	handler = llms.LlmHandler(".cache")
	response = '{"gene_id": null, "name": "dnaA", "function": null, "functional_category": null, "drug_susc_impact": null, "infection_impact": null, "essential_in_vitro": null, "essential_in_vivo": null}'

	assert handler.json_regex_filter(
		response,
		organism_profile=None,
		expected_gene="Rv0001",
	) is False


def test_section_summary_uses_nullable_schema_when_gene_missing():
	captured = {}
	handler = llms.LlmHandler(cache_dir="./.cache")

	def fake_read_cache(model, prompt, json_schema):
		captured["prompt"] = prompt
		captured["schema"] = json_schema
		return json.dumps({"gene_id": None, "name": "abc1"}), 0.1

	handler._read_cache = fake_read_cache

	response, _ = handler.get_llm_gene_info_json(
		None,
		"abc1",
		"abc1 is required for growth.",
		"fake-model",
		organism_profile=None,
	)

	assert captured["schema"]["properties"]["gene_id"]["type"] == ["string", "null"]
	assert "Do not invent a locus identifier" in captured["prompt"]
	assert json.loads(response)["gene_id"] is None


def test_consensus_schema_stays_strict_by_default_when_candidate_gene_id_is_null(monkeypatch):
	captured = {}
	handler = llms.LlmHandler(cache_dir="./.cache")
	null_candidate = json.dumps({"gene_id": None, "name": "abc1", "function": "Same."})
	locus_candidate = json.dumps({"gene_id": "Rv0001", "name": "abc1", "function": "Same."})

	original = llms.build_json_schema
	def capture_schema(*args, **kwargs):
		captured["schema"] = original(*args, **kwargs)
		return captured["schema"]
	monkeypatch.setattr(llms, "build_json_schema", capture_schema)

	handler.get_llm_consensus_json(
		[null_candidate, locus_candidate],
		excerpt="Same.",
		expected_gene_id="Rv0001",
		expected_name="abc1",
		model="fake-model",
	)

	assert captured["schema"]["properties"]["gene_id"]["type"] == "string"


def test_consensus_schema_allows_null_gene_id_when_explicitly_enabled(monkeypatch):
	captured = {}
	handler = llms.LlmHandler(cache_dir="./.cache")
	null_candidate = json.dumps({"gene_id": None, "name": "abc1", "function": "Same."})
	locus_candidate = json.dumps({"gene_id": "Rv0001", "name": "abc1", "function": "Same."})

	original = llms.build_json_schema
	def capture_schema(*args, **kwargs):
		captured["schema"] = original(*args, **kwargs)
		return captured["schema"]
	monkeypatch.setattr(llms, "build_json_schema", capture_schema)

	handler.get_llm_consensus_json(
		[null_candidate, locus_candidate],
		excerpt="Same.",
		expected_gene_id="Rv0001",
		expected_name="abc1",
		model="fake-model",
		allow_missing_locus=True,
	)

	assert captured["schema"]["properties"]["gene_id"]["type"] == ["string", "null"]


def test_batch_consensus_merge_is_candidate_only(monkeypatch):
	captured = {}

	def fake_chat(**kwargs):
		captured["prompt"] = kwargs["messages"][0]["content"]
		captured["format"] = kwargs["format"]
		return {
			"message": {"content": json.dumps({"function": "Initiates DNA replication at oriC."})},
			"total_duration": 1_000_000_000,
		}

	monkeypatch.setattr("autoannotation.llms.ollama.chat", fake_chat)
	handler = llms.LlmHandler(cache_dir="./.cache")
	section_excerpt = "This excerpt must NOT appear in the consensus LLM prompt."
	result, _duration = handler._ollama_batch_consensus_merge(
		candidates=[
			{"function": "Initiates DNA replication."},
			{"function": "DNA replication initiator."},
		],
		unresolved_fields=["function"],
		model="fake-model",
	)
	assert result == {"function": "Initiates DNA replication at oriC."}
	assert "Candidate objects" in captured["prompt"]
	assert section_excerpt not in captured["prompt"]
	assert "Excerpt:" not in captured["prompt"]
	assert "do not choose one candidate over others when they conflict" in captured["prompt"].lower()
	assert "do not add facts not present in any candidate" in captured["prompt"].lower()
	assert captured["format"]["required"] == ["function"]


def test_aggregate_schema_stays_strict_by_default_when_section_gene_id_is_null():
	captured = {}
	handler = llms.LlmHandler(cache_dir="./.cache")
	null_section = json.dumps({"gene_id": None, "name": "abc1"})
	locus_aggregate = json.dumps({
		"gene_id": "Rv0001",
		"name": "abc1",
		"function": None,
		"functional_category": None,
		"drug_susc_impact": None,
		"infection_impact": None,
		"essential_in_vitro": None,
		"essential_in_vivo": None,
		"annotation_notes": None,
	})

	def fake_read_cache(model, prompt, json_schema):
		captured["schema"] = json_schema
		return locus_aggregate, 0.1

	handler._read_cache = fake_read_cache

	handler.get_llm_aggregate_json(
		[null_section],
		["12345"],
		model="fake-model",
	)

	assert captured["schema"]["properties"]["gene_id"]["type"] == "string"


def test_aggregate_schema_allows_null_gene_id_when_explicitly_enabled():
	captured = {}
	handler = llms.LlmHandler(cache_dir="./.cache")
	null_section = json.dumps({"gene_id": None, "name": "abc1"})
	null_aggregate = json.dumps({
		"gene_id": None,
		"name": "abc1",
		"function": None,
		"functional_category": None,
		"drug_susc_impact": None,
		"infection_impact": None,
		"essential_in_vitro": None,
		"essential_in_vivo": None,
		"annotation_notes": None,
	})

	def fake_read_cache(model, prompt, json_schema):
		captured["schema"] = json_schema
		return null_aggregate, 0.1

	handler._read_cache = fake_read_cache

	handler.get_llm_aggregate_json(
		[null_section],
		["12345"],
		model="fake-model",
		allow_missing_locus=True,
	)

	assert captured["schema"]["properties"]["gene_id"]["type"] == ["string", "null"]


def test_ollama_chat_uses_router_when_configured(monkeypatch):
	monkeypatch.setenv("OLLAMA_ROUTER_URL", "http://127.0.0.1:11499")
	calls = []

	class FakeRouter:
		def chat(self, **kwargs):
			calls.append(kwargs)
			return {"message": {"content": "{}"}, "total_duration": 1_000_000_000}

	monkeypatch.setattr(llms, "_router_client", lambda: FakeRouter())
	llms.ollama_chat(
		model="gemma3:1b",
		messages=[{"role": "user", "content": "hi"}],
		role="gene_aggregation",
	)
	assert calls[0]["model"] == "gemma3:1b"


def test_ollama_chat_passes_keep_alive_zero_by_default(monkeypatch):
	captured = {}

	def fake_chat(**kwargs):
		captured.update(kwargs)
		return {
			"message": {"content": "{}"},
			"total_duration": 1_000_000_000,
		}

	monkeypatch.delenv("AUTOANNOTATION_OLLAMA_KEEP_ALIVE", raising=False)
	monkeypatch.setattr("autoannotation.llms.ollama.chat", fake_chat)
	llms.ollama_chat(
		model="fake-model",
		messages=[{"role": "user", "content": "hi"}],
		role="test",
	)
	assert captured["keep_alive"] == 0


def test_read_cache_ignores_empty_response_text(tmp_path):
	handler = llms.LlmHandler(cache_dir=str(tmp_path))
	model = "fake-model"
	prompt = "prompt"
	schema = {"type": "object"}
	cache_path = handler._get_file(model, prompt, schema)
	cache_path.parent.mkdir(parents=True, exist_ok=True)
	cache_path.write_text(json.dumps({"response_text": "", "duration_sec": 0.1}))
	assert handler._read_cache(model, prompt, schema) == (None, None)
	assert not cache_path.exists()


def test_run_consensus_batch_merge_nulls_fields_after_empty_response(monkeypatch):
	def fake_chat(**kwargs):
		return {
			"message": {"content": ""},
			"total_duration": 1_000_000_000,
		}

	monkeypatch.setattr("autoannotation.llms.ollama.chat", fake_chat)
	handler = llms.LlmHandler(cache_dir="./.cache")
	result, duration = handler._run_consensus_batch_merge(
		[{"function": "A"}, {"function": "B"}],
		["function"],
		model="fake-model",
		retry=True,
	)
	assert result == {"function": None}
	assert duration == 0.0


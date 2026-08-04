
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


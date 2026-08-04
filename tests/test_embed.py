
from compareannotations.scoring import embedded_similarity

def test_embed_same_fact_same_text():
	
	cases = [
		("December fifth is my birthday","December fifth is my birthday"),
		("The gene is expressed in liver tissue","The gene is expressed in liver tissue")
	]

	for a, b in cases:
		score = embedded_similarity(a,b)
		assert score > 0.7, f"\nA: {a}\nB: {b}\nScore: {score}"


def test_embed_same_fact_different_text():
	
	cases = [
		("December fifth is my birthday","I was born on December fifth"),
		("The gene is expressed in liver tissue","Gene expression occurs in the liver"),
		("The protein binds to DNA","DNA binding occurs via the protein"),
		("The sample was collected in Seattle","Collection location was Seattle")
	]

	for a, b in cases:
		score = embedded_similarity(a,b)
		assert score > 0.6, f"\nA: {a}\nB: {b}\nScore: {score}"

def test_embed_different_fact_same_text():
	
	cases = [
		("I was born on December fourth","I was born on December fifth"),
		("The gene is expressed in liver tissue","The gene is expressed in kidney tissue"),
		("The protein binds to DNA","The protein binds to RNA"),
		("The sample was collected in Seattle","The sample was collected in Boston")
	]

	for a, b in cases:
		score = embedded_similarity(a,b)
		assert score < 0.5, f"\nA: {a}\nB: {b}\nScore: {score}"


def test_embed_different_fact_different_text():
	
	cases = [
		("I was born on December fourth","December fifth is my birthday"),
		("The gene is expressed in liver tissue","Gene expression occcurs in the kidney"),
		("The protein binds to DNA","RNA binding occurs via the protein"),
		("The sample was collected in Seattle","Collection location was Boston")
	]

	for a, b in cases:
		score = embedded_similarity(a,b)
		assert score < 0.4, f"\nA: {a}\nB: {b}\nScore: {score}"


def test_embed_contradiction():
	
	cases = [
		("True","False"),
		("The gene is expressed in liver","The gene is not expressed in liver"),
		("The protein binds DNA","The protein does not bind DNA")
	]

	for a, b in cases:
		score = embedded_similarity(a,b)
		assert score < 0.3, f"\nA: {a}\nB: {b}\nScore: {score}"


def test_embed_same_numbers():
	
	cases = [
		("10","10"),
		("300","300"),
		("846","846")
	]

	for a, b in cases:
		score = embedded_similarity(a,b)
		assert score > 0.8, f"\nA: {a}\nB: {b}\nScore: {score}"


def test_embed_different_numbers():
	
	cases = [
		("10","11"),
		("300","900"),
		("846","52")
	]

	for a, b in cases:
		score = embedded_similarity(a,b)
		assert score < 0.6, f"\nA: {a}\nB: {b}\nScore: {score}"


def test_embed_same_number_text():
	
	cases = [
		("The gene expression level increased by 10%","The gene expression level increased by 11%"),
		("5 mg/mL is the protein concentration","The protein concentration is 5 mg/mL")
	]

	for a, b in cases:
		score = embedded_similarity(a,b)
		assert score > 0.5, f"\nA: {a}\nB: {b}\nScore: {score}"


def test_embed_different_number_same_text():
	
	cases = [
		("The gene has 1 functional copy of the gene","The gene has 2 functional copies of the gene"),
		("The gene expression level increased by 10%","The gene expression level increased by 45%"),
		("The protein concentration is 5.0 mg/mL","The protein concentration is 20 mg/mL"),
		("The enzyme is active at 1 copy per cell","The enzyme is active at 3 copies per cell")
	]

	for a, b in cases:
		score = embedded_similarity(a,b)
		assert score < 0.5, f"\nA: {a}\nB: {b}\nScore: {score}"




from compareannotations.scoring import is_exact_match

def test_exact_match_same_text():
	
	assert is_exact_match("Mars","Mars") == True

def test_exact_match_extra_spaces():

	assert is_exact_match("red planet"," red  planet ") == True

def test_exact_match_different_case():

	assert is_exact_match("Red Planet","red planet") == True

def test_exact_match_different_text():

	assert is_exact_match("Mars","Jupiter") == False

def test_exact_match_punctuation():

	assert is_exact_match("Mars","Mars!") == False

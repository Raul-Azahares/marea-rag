from app.text_utils import content_words, fold, normalize_for_match, tokenize


def test_fold_removes_case_and_diacritics() -> None:
    assert fold("Póliza DAÑOS Pingüino") == "poliza danos pinguino"


def test_tokenize_ignores_punctuation() -> None:
    assert tokenize("¿Cubre «daños» por agua? (art. 4)") == [
        "cubre",
        "danos",
        "por",
        "agua",
        "art",
        "4",
    ]


def test_content_words_drop_stopwords_and_single_letters() -> None:
    assert content_words("La póliza cubre los daños por agua y el robo") == [
        "poliza",
        "cubre",
        "danos",
        "agua",
        "robo",
    ]


def test_normalize_for_match_is_layout_insensitive() -> None:
    assert normalize_for_match("Franquicia: 150\neuros.") == normalize_for_match(
        "franquicia   150 euros"
    )

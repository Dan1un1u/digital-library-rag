"""Match ready catalogue records by title or individual author name."""
import unicodedata


def _normal_form(value):
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def find_catalogue_records(documents, query):
    term = _normal_form(query)
    matches = []
    for document in documents:
        title = _normal_form(document["title"])
        authors = [_normal_form(name) for name in document["authors"]]
        candidates = [title, *authors]
        if title == term:
            rank = 0
        elif term in authors:
            rank = 1
        elif any(value.startswith(term) for value in candidates):
            rank = 2
        elif any(term in value for value in candidates):
            rank = 3
        else:
            continue
        matches.append((rank, title, document["doc_id"], document))
    return [match[-1] for match in sorted(matches)]

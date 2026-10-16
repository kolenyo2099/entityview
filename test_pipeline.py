from pipeline import chunks, keep, label, norm

assert label({"text": "Imperial Valley Gateway Center LLC", "label": "non-profit organization"}) == "company"
assert label({"text": "Thomas Greg & Sons S.A.", "label": "organization"}) == "company"
assert label({"text": "Coco", "label": "person"}) == "person"  # 'co' suffix needs a word before it
assert not keep({"text": "lawyers", "label": "company"})
assert keep({"text": "ICE", "label": "government agency"}) and keep({"text": "last week", "label": "date"})

assert norm("GEO Group, Inc.") == "geo group"
assert norm("The GEO Group") == "geo group"
assert norm("CoreCivic") == "corecivic"
assert norm("Avelo Airlines Co. Ltd") == "avelo airlines"
assert norm("AT&T") == "at&t"

text = "a " * 450 + "\n" + "b " * 10
cs = chunks(text, max_words=200)
assert [len(c.split()) for c in cs] == [200, 200, 60], [len(c.split()) for c in cs]
assert chunks("") == []
print("ok")

from push import curate
rows = [["article_id", "label", "text", "norm", "score", "context"],
        ["a", "armed group", "CoreCivic", "corecivic", "0.6", ""],
        ["a", "company", "CSI", "csi", "0.6", ""],
        ["a", "person", "Ana Reyes", "ana reyes", "0.9", ""]]
out = curate(rows)
assert out[0][-2:] == ["entity", "type"]
assert out[1][-2:] == ["CoreCivic", "company"]
assert out[2][-2:] == ["CSI Aviation", "airline"]
assert out[3][-2:] == ["Ana Reyes", "person"]
print("curate ok")

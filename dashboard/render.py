import json
import shutil
from pathlib import Path
from jinja2 import Environment, FileSystemLoader


_TEMPLATE_DIR = Path(__file__).parent
_DOCS_DIR = Path("docs")


def render_dashboard(output: dict, config: dict) -> None:
    _DOCS_DIR.mkdir(exist_ok=True)
    (_DOCS_DIR / "data").mkdir(exist_ok=True)

    # data/latest.json を docs にもコピー
    with open(_DOCS_DIR / "data" / "latest.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    # カテゴリ一覧を収集
    category_ids = [c["id"] for c in config["categories"]]
    categories = [{"id": c["id"], "name": c["name"]} for c in config["categories"]]

    # カテゴリ別に仕分け
    items_by_cat: dict[str, list] = {c["id"]: [] for c in config["categories"]}
    items_by_cat["all"] = []
    for item in output["items"]:
        items_by_cat["all"].append(item)
        cid = item.get("category_id", "")
        if cid in items_by_cat:
            items_by_cat[cid].append(item)

    env = Environment(loader=FileSystemLoader(str(_TEMPLATE_DIR)), autoescape=True)
    template = env.get_template("template.html")

    html = template.render(
        generated_at=output["generated_at"],
        total_items=output["total_items"],
        total_expected_value=output["total_expected_value"],
        categories=categories,
        items_by_cat=items_by_cat,
        items_json=json.dumps(output["items"], ensure_ascii=False),
    )

    out_path = _DOCS_DIR / "index.html"
    out_path.write_text(html, encoding="utf-8")
    print(f"  → {out_path} を出力しました")

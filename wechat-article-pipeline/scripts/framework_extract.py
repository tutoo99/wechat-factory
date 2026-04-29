#!/usr/bin/env python3
"""
半自动爆文拆解工具：生成 LLM 拆解提示词、校验框架草案、比较去重、安装到框架库。

脚本不调用 LLM。正文结构和标题结构仍由当前 AI CLI 会话根据 prepare 产物生成。
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Tuple

import yaml


SCRIPT_DIR = Path(__file__).resolve().parent
PIPELINE_ROOT = SCRIPT_DIR.parent
FACTORY_ROOT = PIPELINE_ROOT.parent
FRAMEWORKS_ROOT = FACTORY_ROOT / "frameworks"
DEFAULT_OUTPUT_ROOT = PIPELINE_ROOT / "work" / "framework-extract"
SCHEMA_DOC = FRAMEWORKS_ROOT / "schema.md"

LANES = {"tech", "emotion", "common"}
LANE_CHOICES = ["auto", "tech", "emotion", "common"]
DEPTHS = {"light", "medium", "heavy"}
KNOWN_GOALS = {"click", "read_finish", "save", "share", "comment", "conversion"}
KNOWN_MATERIAL_TYPES = {"story", "problem", "case", "list", "opinion", "data", "insight", "method"}

REQUIRED_FIELDS = [
    "id",
    "name",
    "lane",
    "subtype",
    "summary",
    "suitable_topics",
    "suitable_goals",
    "material_types",
    "material_depth",
    "keywords",
    "required_materials",
    "hook_pattern",
    "section_flow",
    "ending_pattern",
    "constraints",
    "not_for",
    "title_pattern",
]

LIST_FIELDS = [
    "suitable_topics",
    "suitable_goals",
    "material_types",
    "keywords",
    "required_materials",
    "section_flow",
    "constraints",
    "not_for",
]

TITLE_REQUIRED_FIELDS = [
    "original_title",
    "title_type",
    "hook_point",
    "reader_promise",
    "emotion_trigger",
    "information_gap",
    "formula",
    "reusable_templates",
    "variable_slots",
    "constraints",
]


@dataclass
class ValidationResult:
    errors: List[str]
    warnings: List[str]

    @property
    def ok(self) -> bool:
        return not self.errors


@dataclass
class Comparison:
    path: Path
    framework_id: str
    name: str
    body_score: float
    title_score: float
    hook_score: float
    section_score: float
    ending_score: float


def read_text(path: Path) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def load_yaml(path: Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"YAML 顶层必须是对象: {path}")
    return data


def dump_yaml(data: Dict[str, Any]) -> str:
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=1000)


def slugify(text: str, max_len: int = 48) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text[:max_len] or "untitled"


def normalize_text(value: Any) -> str:
    if isinstance(value, list):
        value = "\n".join(str(item) for item in value)
    elif value is None:
        value = ""
    else:
        value = str(value)
    value = value.lower()
    value = re.sub(r"[\s,，。！？、:：；;\"'“”‘’\[\]【】()（）<>《》\-_/|]+", "", value)
    return value


def similarity(a: Any, b: Any) -> float:
    left = normalize_text(a)
    right = normalize_text(b)
    if not left or not right:
        return 0.0
    return SequenceMatcher(None, left, right).ratio()


def safe_rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(FACTORY_ROOT))
    except ValueError:
        return str(path)


def framework_paths_for_lane(lane: str) -> List[Path]:
    dirs = [FRAMEWORKS_ROOT / lane]
    if lane != "common":
        dirs.append(FRAMEWORKS_ROOT / "common")
    paths: List[Path] = []
    for base in dirs:
        if base.exists():
            paths.extend(sorted(base.glob("*.yaml")))
    return paths


def framework_index(limit_per_lane: int = 30) -> str:
    lines: List[str] = []
    for lane in ("tech", "emotion", "common"):
        paths = sorted((FRAMEWORKS_ROOT / lane).glob("*.yaml"))[:limit_per_lane]
        if not paths:
            continue
        lines.append(f"## {lane}")
        for path in paths:
            try:
                data = load_yaml(path)
            except Exception as exc:
                lines.append(f"- {safe_rel(path)}: 读取失败：{exc}")
                continue
            flow = data.get("section_flow") or []
            title_pattern = data.get("title_pattern") or {}
            title_formula = title_pattern.get("formula") if isinstance(title_pattern, dict) else ""
            lines.append(
                "- {path}\n"
                "  id: {id}\n"
                "  name: {name}\n"
                "  hook_pattern: {hook}\n"
                "  section_flow: {flow}\n"
                "  ending_pattern: {ending}\n"
                "  title_formula: {title_formula}".format(
                    path=safe_rel(path),
                    id=data.get("id", ""),
                    name=data.get("name", path.stem),
                    hook=data.get("hook_pattern", ""),
                    flow=" / ".join(str(item) for item in flow),
                    ending=data.get("ending_pattern", ""),
                    title_formula=title_formula or "(none)",
                )
            )
    return "\n".join(lines) if lines else "(暂无框架)"


def read_article_input(article: str | None) -> Tuple[str, str]:
    if not article or article == "-":
        content = sys.stdin.read()
        source = "stdin"
    else:
        path = Path(article).expanduser()
        content = read_text(path)
        source = str(path)
    content = content.strip()
    if not content:
        raise ValueError("爆文正文为空")
    return content, source


def build_prompt(
    *,
    title: str,
    article: str,
    lane: str,
    source_url: str,
    account: str,
) -> str:
    schema_text = read_text(SCHEMA_DOC) if SCHEMA_DOC.exists() else "(未找到 frameworks/schema.md)"
    lane_instruction = (
        "用户没有指定 lane。请先判断应该放入 tech / emotion / common 哪个 lane，并把结果写入 YAML 的 lane 字段。"
        if lane == "auto"
        else f"用户指定 lane={lane}。请使用这个 lane，不要自行改 lane。"
    )
    source_lines = [
        f"- 标题：{title}",
        f"- 来源链接：{source_url or '(未提供)'}",
        f"- 对标账号：{account or '(未提供)'}",
        f"- 拆解日期：{date.today().isoformat()}",
    ]
    return f"""请把下面这篇爆款文章拆解成可沉淀到框架库的 YAML 草案。

你只拆两类资产：

1. 正文结构骨架：hook_pattern、section_flow、ending_pattern、constraints 等。
2. 爆款标题结构：title_pattern，后续会被标题生成、选题分析或标题方法库消费，不能只写备注。

重要边界：
- 只学结构，不抄标题。
- 只学推进方式，不借故事细节。
- 只学情绪节奏，不复用原文金句。
- 只学标题公式，不复用原文专属人物、数字、事件和表达。
- 输出必须是单个 YAML 对象，不要输出 Markdown 代码围栏，不要输出解释性正文。

赛道要求：
{lane_instruction}

来源信息：
{chr(10).join(source_lines)}

必须输出的 YAML 字段：
- id / name / lane / subtype / priority / summary
- suitable_topics / suitable_goals / material_types / material_depth / keywords / anti_keywords
- required_materials / hook_pattern / section_flow / ending_pattern / constraints / not_for
- title_pattern
- source_article
- extraction_notes

title_pattern 必须包含：
- original_title：爆文原标题
- title_type：反常识 / 结果前置 / 数字清单 / 冲突悬念 / 身份代入 / 痛点提醒 等
- hook_point：标题最抓人的信息点
- reader_promise：标题承诺给读者的收益、答案或情绪释放
- emotion_trigger：激发的情绪，如焦虑、好奇、委屈、爽感、警醒、获得感
- information_gap：标题制造的信息差或悬念
- formula：可复用标题公式，例如「看了 X，我才明白 Y」
- reusable_templates：2-5 个可替换模板
- variable_slots：公式中的变量槽位，每项包含 slot 和 meaning
- constraints：标题复用时不能做什么

source_article 必须包含：
- url
- title
- account
- extracted_date

参考 schema：
{schema_text}

已有框架索引摘要，请用于去重判断，但不要照抄：
{framework_index()}

爆文正文：
{article}
"""


def validate_framework(data: Dict[str, Any]) -> ValidationResult:
    errors: List[str] = []
    warnings: List[str] = []

    for field in REQUIRED_FIELDS:
        if field not in data:
            errors.append(f"缺少必填字段: {field}")

    lane = data.get("lane")
    if lane not in LANES:
        errors.append(f"lane 必须是 {sorted(LANES)} 之一，当前: {lane!r}")

    for field in LIST_FIELDS:
        if field in data and not isinstance(data.get(field), list):
            errors.append(f"{field} 必须是 list")

    material_depth = data.get("material_depth")
    if not isinstance(material_depth, dict):
        errors.append("material_depth 必须是对象，且包含 min")
    else:
        min_depth = material_depth.get("min")
        if min_depth not in DEPTHS:
            errors.append(f"material_depth.min 必须是 {sorted(DEPTHS)} 之一，当前: {min_depth!r}")

    for goal in data.get("suitable_goals") or []:
        if isinstance(goal, str) and goal not in KNOWN_GOALS:
            warnings.append(f"未知 suitable_goals 值: {goal}")
    for material_type in data.get("material_types") or []:
        if isinstance(material_type, str) and material_type not in KNOWN_MATERIAL_TYPES:
            warnings.append(f"未知 material_types 值: {material_type}")

    title_pattern = data.get("title_pattern")
    if not isinstance(title_pattern, dict):
        errors.append("title_pattern 必须是对象")
    else:
        for field in TITLE_REQUIRED_FIELDS:
            if field not in title_pattern:
                if field == "variable_slots":
                    warnings.append("title_pattern 缺少建议字段: variable_slots")
                else:
                    errors.append(f"title_pattern 缺少必填字段: {field}")
        for list_field in ("reusable_templates", "variable_slots", "constraints"):
            if list_field in title_pattern and not isinstance(title_pattern.get(list_field), list):
                errors.append(f"title_pattern.{list_field} 必须是 list")

    source_article = data.get("source_article")
    if source_article is not None and not isinstance(source_article, dict):
        errors.append("source_article 必须是对象")

    return ValidationResult(errors=errors, warnings=warnings)


def print_validation(result: ValidationResult) -> None:
    if result.errors:
        print("[error] 框架草案校验失败")
        for item in result.errors:
            print(f"- {item}")
    else:
        print("[ok] 框架草案校验通过")
    if result.warnings:
        print("\n[warning] 非阻断提醒")
        for item in result.warnings:
            print(f"- {item}")


def compare_one(draft: Dict[str, Any], path: Path, existing: Dict[str, Any]) -> Comparison:
    hook_score = similarity(draft.get("hook_pattern"), existing.get("hook_pattern"))
    section_score = similarity(draft.get("section_flow"), existing.get("section_flow"))
    ending_score = similarity(draft.get("ending_pattern"), existing.get("ending_pattern"))
    body_score = hook_score * 0.25 + section_score * 0.55 + ending_score * 0.20

    draft_title = draft.get("title_pattern") if isinstance(draft.get("title_pattern"), dict) else {}
    existing_title = existing.get("title_pattern") if isinstance(existing.get("title_pattern"), dict) else {}
    title_fields = ["title_type", "hook_point", "reader_promise", "emotion_trigger", "information_gap", "formula"]
    title_scores = [similarity(draft_title.get(field), existing_title.get(field)) for field in title_fields]
    title_score = sum(title_scores) / len(title_scores) if title_scores else 0.0

    return Comparison(
        path=path,
        framework_id=str(existing.get("id") or path.stem),
        name=str(existing.get("name") or path.stem),
        body_score=body_score,
        title_score=title_score,
        hook_score=hook_score,
        section_score=section_score,
        ending_score=ending_score,
    )


def compare_frameworks(draft: Dict[str, Any]) -> List[Comparison]:
    lane = draft.get("lane")
    if lane not in LANES:
        raise ValueError("draft lane 无效，先运行 validate 修正")
    comparisons: List[Comparison] = []
    for path in framework_paths_for_lane(lane):
        try:
            existing = load_yaml(path)
        except Exception as exc:
            print(f"[warning] 跳过无法读取的框架 {safe_rel(path)}: {exc}", file=sys.stderr)
            continue
        comparisons.append(compare_one(draft, path, existing))
    comparisons.sort(key=lambda item: (item.body_score, item.title_score), reverse=True)
    return comparisons


def print_comparisons(comparisons: List[Comparison], top_k: int) -> None:
    if not comparisons:
        print("[info] 没有可比较的现有框架")
        return
    print("相似框架 Top %d:\n" % min(top_k, len(comparisons)))
    for item in comparisons[:top_k]:
        print(f"- {safe_rel(item.path)}")
        print(f"  id: {item.framework_id}")
        print(f"  name: {item.name}")
        print(f"  body_score: {item.body_score:.2f} (hook={item.hook_score:.2f}, section={item.section_score:.2f}, ending={item.ending_score:.2f})")
        print(f"  title_score: {item.title_score:.2f}")
    best = comparisons[0]
    print("")
    if best.body_score >= 0.72:
        print(f"[建议] 正文结构高度相似，优先更新已有框架: {safe_rel(best.path)}")
    elif best.title_score >= 0.72:
        print("[建议] 正文结构可新建，但标题模式和现有框架相似，安装前考虑合并 title_pattern。")
    else:
        print("[建议] 结构差异明显，可以新建框架。")


def sanitized_for_install(data: Dict[str, Any]) -> Dict[str, Any]:
    installed = dict(data)
    installed.pop("extraction_notes", None)
    return installed


def ensure_under_frameworks(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    root = FRAMEWORKS_ROOT.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"target 必须位于 frameworks/ 下: {path}") from exc
    return resolved


def default_new_target(data: Dict[str, Any]) -> Path:
    lane = data.get("lane")
    subtype = data.get("subtype")
    if lane not in LANES:
        raise ValueError("lane 无效，无法生成默认路径")
    if not subtype or not isinstance(subtype, str):
        raise ValueError("subtype 为空，无法生成默认路径")
    return FRAMEWORKS_ROOT / lane / f"{slugify(subtype)}.yaml"


def unique_run_dir(output_root: Path, base_name: str) -> Path:
    candidate = output_root / base_name
    if not candidate.exists():
        return candidate
    for index in range(2, 100):
        candidate = output_root / f"{base_name}_{index}"
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"无法生成唯一任务目录: {output_root / base_name}")


def command_prepare(args: argparse.Namespace) -> int:
    article, source = read_article_input(args.article)
    title = args.title.strip()
    if not title:
        raise ValueError("--title 不能为空")

    output_root = Path(args.output_root).expanduser()
    run_dir = unique_run_dir(output_root, f"{date.today().isoformat()}_{slugify(title)}")
    run_dir.mkdir(parents=True, exist_ok=False)

    prompt = build_prompt(
        title=title,
        article=article,
        lane=args.lane,
        source_url=args.source_url or "",
        account=args.account or "",
    )
    write_text(run_dir / "extract.prompt.md", prompt)
    write_text(run_dir / "source.md", article + "\n")
    meta = {
        "created_at": datetime.now().isoformat(),
        "source": source,
        "title": title,
        "source_url": args.source_url or "",
        "account": args.account or "",
        "lane": args.lane,
        "draft_path": str(run_dir / "draft.yaml"),
    }
    write_text(run_dir / "meta.yaml", dump_yaml(meta))

    print(f"[ok] 拆解任务包已生成: {run_dir}")
    print(f"- prompt: {run_dir / 'extract.prompt.md'}")
    print(f"- draft:  {run_dir / 'draft.yaml'}")
    print("\n下一步：让当前 AI CLI 会话读取 extract.prompt.md，生成 draft.yaml。")
    return 0


def command_validate(args: argparse.Namespace) -> int:
    draft = load_yaml(Path(args.draft))
    result = validate_framework(draft)
    print_validation(result)
    return 0 if result.ok else 1


def command_compare(args: argparse.Namespace) -> int:
    draft = load_yaml(Path(args.draft))
    result = validate_framework(draft)
    if not result.ok:
        print_validation(result)
        return 1
    if result.warnings:
        print_validation(result)
        print("")
    comparisons = compare_frameworks(draft)
    print_comparisons(comparisons, args.top_k)
    return 0


def command_install(args: argparse.Namespace) -> int:
    draft_path = Path(args.draft)
    draft = load_yaml(draft_path)
    result = validate_framework(draft)
    if not result.ok:
        print_validation(result)
        return 1
    if result.warnings:
        print_validation(result)
        print("")

    if args.mode == "new":
        target = Path(args.target).expanduser() if args.target else default_new_target(draft)
        target = ensure_under_frameworks(target)
        if target.exists():
            raise FileExistsError(f"目标文件已存在，不能 new 覆盖: {safe_rel(target)}")
    else:
        if not args.target:
            raise ValueError("install --mode update 必须显式传 --target")
        target = ensure_under_frameworks(Path(args.target))
        if not target.exists():
            raise FileNotFoundError(f"update 目标不存在: {safe_rel(target)}")

    data = sanitized_for_install(draft)
    write_text(target, dump_yaml(data))
    print(f"[ok] 框架已安装: {safe_rel(target)}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="半自动爆文拆解沉淀框架工具")
    sub = parser.add_subparsers(dest="command", required=True)

    prepare = sub.add_parser("prepare", help="生成当前会话 LLM 使用的拆解提示词包")
    prepare.add_argument("--article", default="-", help="爆文正文 .txt/.md 路径；省略或 '-' 表示从 stdin 读取")
    prepare.add_argument("--title", required=True, help="爆文标题")
    prepare.add_argument("--source-url", default="", help="爆文来源链接")
    prepare.add_argument("--account", default="", help="对标账号")
    prepare.add_argument("--lane", default="auto", choices=LANE_CHOICES, help="指定 lane；默认 auto 让 LLM 判断")
    prepare.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT), help="任务包输出根目录")
    prepare.set_defaults(func=command_prepare)

    validate = sub.add_parser("validate", help="校验 LLM 生成的框架草案 YAML")
    validate.add_argument("--draft", required=True, help="draft.yaml 路径")
    validate.set_defaults(func=command_validate)

    compare = sub.add_parser("compare", help="和已有框架比较正文结构与标题结构")
    compare.add_argument("--draft", required=True, help="draft.yaml 路径")
    compare.add_argument("--top-k", type=int, default=5, help="展示相似框架数量，默认 5")
    compare.set_defaults(func=command_compare)

    install = sub.add_parser("install", help="安装框架草案到 frameworks 目录")
    install.add_argument("--draft", required=True, help="draft.yaml 路径")
    install.add_argument("--mode", required=True, choices=["new", "update"], help="new 新建；update 更新已有文件")
    install.add_argument("--target", default="", help="目标 YAML 路径；update 必填，new 可选")
    install.set_defaults(func=command_install)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return args.func(args)
    except Exception as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

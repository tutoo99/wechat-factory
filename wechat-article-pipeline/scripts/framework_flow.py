#!/usr/bin/env python3
"""
把“选题 -> 推荐框架 -> 编号选择/标题选择/回退”串成一条 CLI 链路。

示例：
  # 第一步：推荐
  python3 framework_flow.py \
    --channel tech \
    --topic "我把公众号发布系统重构成 channel 模型" \
    --goal click --goal save \
    --material-type case --material-type opinion \
    --material-depth heavy

  # 第二步：直接按编号选择，生成标题推荐指令包
  python3 framework_flow.py \
    --channel tech \
    --topic "我把公众号发布系统重构成 channel 模型" \
    --goal click --goal save \
    --material-type case --material-type opinion \
    --material-depth heavy \
    --code 1

  # 第三步：标题确认后，默认只生成大纲指令包；回传 outline.yaml 后才生成写作 prompt
  python3 framework_flow.py \
    --channel tech \
    --topic "我把公众号发布系统重构成 channel 模型" \
    --title "我把公众号发布系统重构成 channel 模型，终于不再发错号了" \
    --goal click --goal save \
    --material-type case --material-type opinion \
    --material-depth heavy \
    --code 1
"""

import argparse
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

import yaml

import recommend_framework as rf

SCRIPT_DIR = Path(__file__).resolve().parent
PIPELINE_ROOT = SCRIPT_DIR.parent
FACTORY_ROOT = PIPELINE_ROOT.parent
FLOW_OUTPUT_ROOT = PIPELINE_ROOT / "work" / "framework-flow"
FRAMEWORK_DRAFTS_ROOT = FACTORY_ROOT / "frameworks" / "drafts"
PUBLISHER_SCRIPTS_ROOT = FACTORY_ROOT / "wechat-publisher" / "scripts"

if str(PUBLISHER_SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(PUBLISHER_SCRIPTS_ROOT))

import recommend_theme as rt
import render_with_recommended_theme as rwrt


def slugify(text: str, max_len: int = 48) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text[:max_len] or "untitled"


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def read_text(path: Path) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def normalize_inputs(args) -> Dict:
    goals = [goal.strip() for goal in args.goal if goal.strip()]
    material_types = [value.strip() for value in args.material_type if value.strip()]
    topic = args.topic.strip()
    article_title = (getattr(args, "title", None) or "").strip()
    if args.extra_materials:
        topic = "%s\n补充素材：%s" % (topic, args.extra_materials.strip())
    return {
        "topic": topic,
        "article_title": article_title,
        "goals": goals,
        "material_types": material_types,
        "material_depth": args.material_depth,
        "no_materials": getattr(args, "no_materials", False),
        "debug_material_queries": getattr(args, "debug_material_queries", False),
    }


def reroute_by_code(code: str, payload: Dict) -> Dict:
    updated = dict(payload)
    if code == "8":
        updated["goals"] = ["click"]
    elif code == "9":
        updated["goals"] = ["read_finish"]
    elif code == "10":
        updated["goals"] = ["save"]
    elif code == "11":
        if not updated["topic"] or "补充素材：" not in updated["topic"]:
            raise ValueError("选择 11 时请通过 --extra-materials 提供补充素材。")
    return updated


def get_channel_context(channel_id: str) -> Tuple[Dict, str]:
    channels = rf.load_channels()
    channel = channels.get(channel_id)
    if not channel:
        raise KeyError("未找到 channel '%s'" % channel_id)
    lane = rf.infer_lane(channel_id, channel)
    return channel, lane


def get_persona_info(channel_id: str, channel: Dict) -> Dict:
    persona_id = (channel.get("persona") or "").strip()
    if not persona_id:
        raise ValueError("channel '%s' 缺少 persona 配置" % channel_id)
    persona_path = FACTORY_ROOT / ("persona-%s.yaml" % persona_id)
    if not persona_path.exists():
        raise FileNotFoundError("未找到 persona 文件: %s" % persona_path)
    return {
        "id": persona_id,
        "path": str(persona_path),
        "content": read_text(persona_path),
    }


def build_writing_brief(
    channel_id: str,
    channel: Dict,
    lane: str,
    persona: Dict,
    selected,
    payload: Dict,
) -> Dict:
    framework = selected.data
    topic = payload["topic"].split("\n补充素材：", 1)[0]
    supplemental = ""
    if "\n补充素材：" in payload["topic"]:
        supplemental = payload["topic"].split("\n补充素材：", 1)[1].strip()
    
    # 自动召回素材（只注入 primary_claim，不注入原文）
    # --no-materials 时跳过召回，auto_materials 为空列表
    auto_materials = []
    if not payload.get("no_materials"):
        auto_materials = fetch_materials_for_brief(
            topic=payload["topic"].split("\n补充素材：", 1)[0],
            framework=selected.data,
            lane=lane,
            material_types=payload.get("material_types") or [],
            max_per_source=2,
            limit=5,
            debug=bool(payload.get("debug_material_queries")),
        )
    return {
        "created_at": datetime.now().isoformat(),
        "channel": channel_id,
        "channel_display_name": channel.get("display_name") or channel_id,
        "lane": lane,
        "topic": topic,
        "article_title": payload.get("article_title") or topic,
        "goals": payload["goals"],
        "material_types": payload["material_types"],
        "material_depth": payload["material_depth"],
        "persona": {
            "id": persona["id"],
            "path": persona["path"],
        },
        "framework": {
            "id": framework.get("id"),
            "name": framework.get("name"),
            "summary": framework.get("summary"),
            "hook_pattern": framework.get("hook_pattern"),
            "section_flow": framework.get("section_flow") or [],
            "ending_pattern": framework.get("ending_pattern"),
            "constraints": framework.get("constraints") or [],
            "required_materials": framework.get("required_materials") or [],
            "title_pattern": framework.get("title_pattern") or {},
        },
        "supplemental_materials": supplemental,
        "auto_materials": auto_materials,
        "next_step": "按这份 brief 开始写正文初稿",
    }


STRATEGY_MATERIAL_ENGINE_ROOT = Path("/Users/naipan/.hermes/skills/strategy-material-engine")
TERMINAL_CONTROL_RE = re.compile(
    r"\x1b\[[0-?]*[ -/]*[@-~]"
    r"|\x1b\][^\x07]*(?:\x07|\x1b\\)"
    r"|\x1b[@-Z\\-_]"
)
CAPTURED_SUBPROCESS_ENV = {
    "TERM": "dumb",
    "NO_COLOR": "1",
    "PYTHONUNBUFFERED": "1",
    "TQDM_DISABLE": "1",
}

ANGLE_ORDER = ["story", "method", "insight", "mistake", "cost", "turning_point"]
ANGLE_HINTS = {
    "story": [
        "真实场景", "场景", "案例", "具体案例", "完整案例", "验证载体", "生活场景", "生活现象",
        "实操演示", "真实故事", "case", "证明方案可行", "真实实操演示",
    ],
    "method": [
        "可执行方法", "方法", "方法论", "完整操作流程", "修复动作", "解决动作", "判断标准",
        "步骤", "搭建教程", "完整方案", "维护方案", "教程", "动作", "复用经验", "长期维护",
        "方案讲解", "通用框架", "关键动作",
    ],
    "insight": [
        "核心判断", "反常识判断", "抽象原则", "底层原理", "认知科学支撑", "真相重构", "认知",
        "逻辑推演", "反常识结论", "为什么不能只看表面", "认知升华", "核心观点",
    ],
    "mistake": [
        "关键坑点", "失败中提炼的具体规则", "问题暴露", "旧做法哪里别扭", "错误", "误区",
        "失败", "低效或异常场景", "干货主体", "异议预处理", "冲突升级点",
    ],
    "cost": [
        "前后对比数据", "旧方案的成本", "吃亏或受委屈细节", "成本/效率/效果", "前后差异",
        "成本对比", "麻烦慢慢变大", "情绪逐步升级", "问题暴露", "长期影响",
    ],
    "turning_point": [
        "明确转折点", "醒悟点", "意识变化", "揭露点", "真正意图暴露", "原来如此",
        "后来的醒悟", "主角意识变化", "边界问题", "收束总结",
    ],
}
MATERIAL_TYPE_ANGLE_HINTS = {
    "story": "story",
    "case": "story",
    "problem": "mistake",
    "opinion": "insight",
    "list": "method",
    "method": "method",
    "data": "cost",
}
LANE_DEFAULT_ANGLES = {
    "tech": ["method", "mistake", "insight", "cost"],
    "emotion": ["story", "turning_point", "insight", "cost"],
}
LANE_ANGLE_TERMS = {
    "tech": {
        "story": ["真实案例", "实践场景"],
        "method": ["方法", "步骤"],
        "insight": ["底层逻辑", "本质"],
        "mistake": ["误区", "踩坑经验"],
        "cost": ["代价", "长期影响"],
        "turning_point": ["转折", "关键变化"],
    },
    "emotion": {
        "story": ["真实故事", "具体场景"],
        "method": ["处理方式", "判断"],
        "insight": ["关系本质", "心理机制"],
        "mistake": ["误区", "关系陷阱"],
        "cost": ["代价", "情绪损耗"],
        "turning_point": ["醒悟", "转折点"],
    },
}
TOPIC_SKELETON_WORDS = [
    "做任何事情", "任何事情", "必须要", "否则根本", "否则", "不会有", "不可能",
    "如果没有", "其实", "真正", "才能", "就是",
    "不是", "而是", "因为", "所以", "最容易", "待久了", "能力", "问题", "方法",
    "我把", "重构成",
]
TOPIC_TRIGGER_WORDS = [
    "不是", "而是", "因为", "所以", "真正", "本质", "问题", "能力", "代价", "误区",
    "为什么", "反而", "后果", "成本", "边界",
]
GENERIC_ANCHOR_MARKERS = [
    "一种能力", "一个共同点", "一个问题", "一个真相", "一件事", "一个习惯", "一个提醒",
    "一个代价", "一个后果",
]
ANGLE_LABELS = {
    "story": "案例",
    "method": "方法",
    "insight": "认知",
    "mistake": "误区",
    "cost": "代价",
    "turning_point": "转折",
}
SEARCH_GUARD_SPLIT_WORDS = [
    "为什么", "怎么", "如何", "最容易", "待久了", "重构成", "不是", "而是", "真正", "应该",
    "因为", "所以", "有些人", "很多人", "有人", "我们", "他们", "你会", "进入", "看清了", "看清",
    "对方", "迷恋", "不能", "可以", "一个", "一种", "这个", "那个", "这些", "那些", "能力",
    "问题", "方法", "结果", "价值", "技术人", "我把", "待久", "在",
    "重构", "用",
]
SEARCH_GUARD_STOP_TERMS = {
    "技术人", "一个", "一种", "这个", "那个", "不是", "而是", "真正", "能力",
    "问题", "方法", "结果", "价值", "自己", "别人", "很多", "容易", "需要",
}
SEARCH_GUARD_SHORT_LATIN_TERMS = {"ai", "api", "ui", "ux", "ip", "ar", "vr"}
SEARCH_GUARD_EDGE_CHARS = "的了着过呢吗吧啊呀"
SEARCH_GUARD_PREFIX_MODIFIERS = [
    "主动", "被动", "长期", "短期", "持续", "反复", "真正", "重新", "再次", "直接",
]
SEARCH_GUARD_COMPOUND_SUFFIXES = [
    "系统", "平台", "公司", "团队", "产品", "项目", "模型", "框架", "工具", "流程",
    "账号", "渠道", "文章", "素材", "案例", "关系", "情绪", "认知", "成本", "能力",
    "经验", "业务", "岗位", "方案", "策略", "内容", "用户", "客户", "服务",
]


def _compact_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _strip_terminal_control_sequences(text: str | None) -> str | None:
    if text is None:
        return None
    return TERMINAL_CONTROL_RE.sub("", str(text))


def run_captured_subprocess(cmd: list[str], **kwargs):
    env = os.environ.copy()
    env.update(CAPTURED_SUBPROCESS_ENV)
    if kwargs.get("env"):
        env.update(kwargs["env"])
    kwargs["env"] = env
    result = subprocess.run(cmd, capture_output=True, text=True, **kwargs)
    result.stdout = _strip_terminal_control_sequences(result.stdout) or ""
    result.stderr = _strip_terminal_control_sequences(result.stderr) or ""
    return result


def _clean_search_guard_term(term: str) -> str:
    term = _compact_text(term.strip(" ，。、；：！？!?\"'`[]（）()《》"))
    while term and term[-1] in SEARCH_GUARD_EDGE_CHARS:
        term = term[:-1]
    return _compact_text(term)


def _is_search_guard_term(term: str) -> bool:
    if not term or term in SEARCH_GUARD_STOP_TERMS:
        return False
    if re.fullmatch(r"[a-z0-9_+\-.]+", term):
        return len(term) >= 3 or term in SEARCH_GUARD_SHORT_LATIN_TERMS
    if len(term) < 3 or len(term) > 14:
        return False
    if term in SEARCH_GUARD_STOP_TERMS:
        return False
    if term[-1:] in SEARCH_GUARD_EDGE_CHARS:
        return False
    return True


def _derive_search_guard_terms(segment: str) -> list[str]:
    """从一个干净中文片段派生少量自然短语；不做任意滑窗 ngram。"""
    terms = []
    segment = _clean_search_guard_term(segment)
    if not segment:
        return terms

    if segment.endswith("的感觉"):
        feeling_term = _clean_search_guard_term(segment[:-3] + "感")
        if _is_search_guard_term(feeling_term):
            terms.append(feeling_term)

    if _is_search_guard_term(segment):
        terms.append(segment)

    for prefix in SEARCH_GUARD_PREFIX_MODIFIERS:
        if segment.startswith(prefix):
            remainder = _clean_search_guard_term(segment[len(prefix):])
            if _is_search_guard_term(remainder) and remainder not in terms:
                terms.append(remainder)

    for suffix in SEARCH_GUARD_COMPOUND_SUFFIXES:
        if not segment.endswith(suffix):
            continue
        prefix = segment[: -len(suffix)]
        if len(prefix) < 2:
            continue
        tail_compound = _clean_search_guard_term(prefix[-2:] + suffix)
        if _is_search_guard_term(tail_compound) and tail_compound not in terms:
            terms.append(tail_compound)
        prefix_term = _clean_search_guard_term(prefix)
        if _is_search_guard_term(prefix_term) and prefix_term not in terms:
            terms.append(prefix_term)

    return terms


def _extract_search_guard_terms(*texts: str, limit: int = 10) -> list[str]:
    """提取跨题材可复用的高精度主题锚点，用来防止低相关素材污染 prompt。"""
    candidates: list[str] = []

    def push(term: str) -> None:
        term = _clean_search_guard_term(term).lower()
        if not _is_search_guard_term(term):
            return
        if term not in candidates:
            candidates.append(term)

    for text in texts:
        normalized = _normalize_topic_text(text)
        for word in sorted(SEARCH_GUARD_SPLIT_WORDS, key=len, reverse=True):
            normalized = normalized.replace(word, " ")
        for fragment in re.split(r"[\s，,。；;：:！？!?、/|]+", normalized):
            fragment = _compact_text(fragment)
            if not fragment:
                continue
            for token in re.findall(r"[A-Za-z0-9_+\-.]{2,}|[\u4e00-\u9fff]{2,}", fragment):
                if re.search(r"[A-Za-z0-9]", token):
                    push(token)
                    continue
                for term in _derive_search_guard_terms(token):
                    push(term)
    return candidates[:limit]


def _normalize_topic_text(topic: str) -> str:
    topic = str(topic or "").split("\n补充素材：", 1)[0]
    return _compact_text(topic.strip("，。、；：！？ "))


def _split_topic_clauses(topic: str) -> list[str]:
    parts = re.split(r"[，,。；;：:！？!?]", topic)
    clauses = [_compact_text(part.strip()) for part in parts if _compact_text(part.strip())]
    return clauses or [topic]


def _score_anchor_candidate(text: str) -> int:
    score = 0
    length = len(text)
    if 6 <= length <= 18:
        score += 6
    elif 4 <= length <= 24:
        score += 4
    elif length > 24:
        score += 2
    for marker in TOPIC_TRIGGER_WORDS:
        if marker in text:
            score += 4
    if re.search(r"[A-Za-z0-9]", text):
        score += 2
    if "我" in text or "你" in text:
        score += 1
    if text.startswith(("你会", "我们会", "很多人会", "有人会")):
        score -= 2
    for marker in GENERIC_ANCHOR_MARKERS:
        if marker in text:
            score -= 5
    return score


def _extract_topic_anchor(topic: str) -> str:
    normalized = _normalize_topic_text(topic)
    candidates = []
    for clause in _split_topic_clauses(normalized):
        cleaned = clause
        for word in TOPIC_SKELETON_WORDS:
            cleaned = cleaned.replace(word, "")
        cleaned = _compact_text(cleaned.strip("，。、；：！？ "))
        if cleaned:
            candidates.append(cleaned)
    if not candidates:
        return normalized

    best = max(candidates, key=_score_anchor_candidate)
    if len(best) <= 24:
        return best

    for splitter in ("是因为", "因为", "所以", "但是", "但", "而是", "不是", "反而"):
        if splitter in best:
            fragments = [
                _compact_text(part.strip("，。、；：！？ "))
                for part in best.split(splitter)
                if _compact_text(part.strip("，。、；：！？ "))
            ]
            if fragments:
                fragment = max(fragments, key=_score_anchor_candidate)
                if len(fragment) <= 24:
                    return fragment

    phrase_candidates = re.findall(r"[\u4e00-\u9fffA-Za-z0-9]{4,18}", best)
    if phrase_candidates:
        return max(phrase_candidates, key=_score_anchor_candidate)
    return best[:24]


def _infer_framework_angles(framework: dict) -> list[str]:
    text = " ".join(
        str(value)
        for value in (framework.get("required_materials") or []) + (framework.get("section_flow") or [])
    )
    matched = []
    for angle in ANGLE_ORDER:
        for hint in ANGLE_HINTS[angle]:
            if hint.lower() in text.lower():
                matched.append(angle)
                break
    return matched


def _infer_material_type_angles(material_types: list[str]) -> list[str]:
    matched = []
    for material_type in material_types or []:
        angle = MATERIAL_TYPE_ANGLE_HINTS.get(str(material_type).strip())
        if angle and angle not in matched:
            matched.append(angle)
    return matched


def _select_query_angles(framework: dict, lane: str, material_types: list[str]) -> list[str]:
    selected = []
    for angle in _infer_framework_angles(framework):
        if angle not in selected:
            selected.append(angle)
    for angle in _infer_material_type_angles(material_types):
        if angle not in selected:
            selected.append(angle)
    for angle in LANE_DEFAULT_ANGLES.get(lane, ["insight", "method", "story"]):
        if angle not in selected:
            selected.append(angle)
    return selected[:4]


def _build_keyword_query(anchor: str, angle: str, lane: str) -> str:
    terms = LANE_ANGLE_TERMS.get(lane, LANE_ANGLE_TERMS["tech"]).get(angle, [])
    if not terms:
        return ""
    query = _compact_text(" ".join([anchor, *terms]))
    if len(query.replace(" ", "")) < 6:
        return ""
    label = ANGLE_LABELS.get(angle, "")
    if query in {anchor, f"{anchor} {label}".strip()}:
        return ""
    return query


def _build_expanded_queries(topic: str, framework: dict, lane: str, material_types: list[str]) -> list[dict]:
    """从 topic 生成多个召回 query，覆盖文章不同的写作支撑角度。"""
    topic = _normalize_topic_text(topic)
    anchor = _extract_topic_anchor(topic)
    queries = []
    seen = set()

    def push(query: str, angle: str, source: str) -> None:
        normalized = _compact_text(query)
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        queries.append({"query": normalized, "angle": angle, "source": source})

    push(topic, "original", "topic")
    if anchor != topic:
        push(anchor, "anchor", "anchor")

    for angle in _select_query_angles(framework, lane, material_types):
        expanded = _build_keyword_query(anchor, angle, lane)
        if expanded:
            push(expanded, angle, "keyword_concat")

    return queries[:6]


def fetch_materials_for_brief(
    topic: str,
    framework: dict,
    lane: str,
    material_types: list,
    max_per_source: int = 1,
    limit: int = 5,
    debug: bool = False,
) -> list[dict]:
    """从素材库召回素材，只返回 primary_claim 级别的摘要，不返回原文。
    
    使用 query 扩写策略：从 topic + section_flow + required_materials
    提取多个 query，每个 query 召回少量素材，合并去重后返回。
    """
    import subprocess, json
    
    search_script = STRATEGY_MATERIAL_ENGINE_ROOT / "scripts" / "search_materials.py"
    if not search_script.exists():
        return []
    
    query_specs = _build_expanded_queries(topic, framework, lane, material_types)
    
    # 根据框架的 required_materials 确定 prefer_type
    prefer_type = None
    required = framework.get("required_materials") or []
    required_text = " ".join(required)
    if "故事" in required_text or "场景" in required_text or "案例" in required_text:
        prefer_type = "story"
    elif "方法" in required_text or "步骤" in required_text:
        prefer_type = "method"
    elif "数据" in required_text:
        prefer_type = "data"
    
    # material_types 转换为 prefer_type 候选（不再硬过滤，改用 soft bonus）
    # 框架 required_materials 的 prefer_type 优先级高于 material_types
    mt_prefer = None
    if material_types:
        type_map = {
            "story": "story", "case": "story", "problem": "story",
            "opinion": "insight", "list": "insight", "data": "data",
            "method": "method",
        }
        for mt in material_types:
            mapped = type_map.get(mt)
            if mapped:
                mt_prefer = mapped
                break
    # 框架 prefer_type 优先，material_types 作为 fallback
    if not prefer_type and mt_prefer:
        prefer_type = mt_prefer
    
    # 每个 query 召回 limit 条，合并去重
    all_materials: dict[str, dict] = {}  # primary_claim → item
    per_query_limit = max(limit, 8)  # 每个 query 多召回一些，去重后仍有足够量
    raw_candidate_count = 0
    debug_rows = []
    
    for spec in query_specs:
        query = spec["query"]
        try:
            guard_terms = _extract_search_guard_terms(topic)
            cmd = [
                "/opt/miniconda3/bin/python3",
                str(search_script),
                query,
                "--root", str(STRATEGY_MATERIAL_ENGINE_ROOT),
                "--limit", str(per_query_limit),
                "--max-per-source", str(max_per_source),
                "--reranker", "none",
                "--domain-query", _compact_text("%s %s" % (topic, query)),
                "--min-domain-overlap", "0.04",
                "--min-vector-score", "0.44",
            ]
            if guard_terms:
                cmd.extend(["--require-term", ",".join(guard_terms), "--min-required-term-hits", "1"])
            if lane == "emotion":
                cmd.extend(["--block-term", ",".join(_emotion_material_block_terms(topic))])
            if prefer_type:
                cmd.extend(["--prefer-type", prefer_type])
            
            result = run_captured_subprocess(cmd, timeout=60)
            if result.returncode != 0:
                continue

            per_query_hits = 0
            unique_claims = set()
            for line in result.stdout.strip().splitlines():
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                    per_query_hits += 1
                    raw_candidate_count += 1
                    claim = item.get("primary_claim", "")
                    if claim and claim not in all_materials:
                        all_materials[claim] = {
                            "primary_claim": claim,
                            "type": item.get("type", ""),
                            "role": item.get("role", ""),
                            "source": item.get("source", ""),
                            "_score": item.get("score", 0),
                        }
                        unique_claims.add(claim)
                    elif claim and claim in all_materials:
                        # 取最高分
                        new_score = item.get("score", 0)
                        if new_score > all_materials[claim]["_score"]:
                            all_materials[claim]["_score"] = new_score
                        unique_claims.add(claim)
                except json.JSONDecodeError:
                    continue
            debug_rows.append(
                {
                    "query": query,
                    "angle": spec.get("angle", ""),
                    "source": spec.get("source", ""),
                    "guard_terms": guard_terms,
                    "hits": per_query_hits,
                    "unique_claims": len(unique_claims),
                }
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
            continue
    
    # 按分数排序，返回 top limit
    sorted_materials = sorted(
        all_materials.values(),
        key=lambda x: x.get("_score", 0),
        reverse=True,
    )
    # 去掉内部 _score 字段
    for m in sorted_materials:
        m.pop("_score", None)

    if debug:
        print("# material-query-debug")
        print("- topic: %s" % _normalize_topic_text(topic))
        print("- anchor: %s" % _extract_topic_anchor(topic))
        print("- framework_angles: %s" % ", ".join(_infer_framework_angles(framework) or ["-"]))
        print("- raw_candidates: %s" % raw_candidate_count)
        print("- deduped_candidates: %s" % len(all_materials))
        for row in debug_rows:
            print(
                "- query[%s/%s]: %s | guard=%s | hits=%s | unique_claims=%s"
                % (
                    row["angle"] or "original",
                    row["source"] or "topic",
                    row["query"],
                    ",".join(row.get("guard_terms") or []) or "-",
                    row["hits"],
                    row["unique_claims"],
                )
            )
    
    return sorted_materials[:limit]


def _prefer_type_for_outline_section(section: dict, material_types: list[str]) -> str:
    angle = section.get("evidence_need") or ""
    type_map = {
        "story": "story",
        "method": "method",
        "insight": "insight",
        "mistake": "insight",
        "cost": "data",
        "turning_point": "story",
    }
    prefer_type = type_map.get(angle)
    if prefer_type:
        return prefer_type
    for material_type in material_types or []:
        mapped = {
            "story": "story",
            "case": "story",
            "problem": "story",
            "opinion": "insight",
            "list": "insight",
            "data": "data",
            "method": "method",
        }.get(material_type)
        if mapped:
            return mapped
    return ""


EMOTION_RELATION_TERMS = [
    "儿媳妇", "儿媳", "婆婆", "婆媳", "儿子", "女儿", "女婿", "老伴", "亲戚",
    "老姐妹", "邻居", "孙子", "孙女", "孩子", "儿女",
]
EMOTION_SCENE_TERMS = [
    "带孙子", "带孩子", "接送孩子", "做饭", "买菜", "菜市场", "公交车", "厨房",
    "沙发", "饭桌", "电话", "红包", "退休", "回家", "发愣", "笑话", "不让带",
]
EMOTION_CONFLICT_TERMS = [
    "委屈", "面子", "没位置", "被嫌弃", "松了一口气", "边界", "心软",
    "吃亏", "受累", "埋怨", "夹在中间", "不被需要", "婆媳矛盾", "家庭关系",
]
EMOTION_TRANSFER_TERMS = [
    "家庭关系", "边界", "被需要感", "心软", "关系", "婚恋", "责任感", "价值感",
]
EMOTION_BUSINESS_TECH_BLOCK_TERMS = [
    "AI", "RAG", "程序员", "技术", "发布系统", "公众号", "账号", "素材库",
    "B站", "知乎", "带货", "流量", "项目", "产品", "课程", "录播课",
    "创业", "副业", "赚钱", "变现", "现金流", "电商", "淘宝", "京东",
]
EMOTION_ELDER_FAMILY_TERMS = [
    "儿媳", "婆婆", "孙子", "孙女", "带孙", "儿女", "女儿", "儿子",
    "女婿", "晚年", "养老", "退休", "老姐妹", "老人",
]
EMOTION_ELDER_FAMILY_BLOCK_TERMS = [
    "凤凰男", "暖男", "择偶", "恋爱", "爱情", "男人", "女性", "女生",
    "女朋友", "男朋友", "婚恋",
]
TECH_OUTLINE_GUARD_TERMS = [
    "外包", "跳槽", "换公司", "简历", "面试", "技能", "能力", "职业", "方向",
    "工作", "技术人", "甲方", "项目", "现金流", "转型", "副业", "赚钱",
    "AI", "Agent", "自动化", "测试", "开发", "程序员",
]


def _extract_terms_from_text(text: str, vocabulary: list[str], limit: int = 4) -> list[str]:
    found = []
    text = str(text or "")
    for term in vocabulary:
        if term in text and term not in found:
            found.append(term)
    return found[:limit]


def _build_default_outline_section_queries(section: dict, topic: str, lane: str) -> list[dict]:
    topic = _normalize_topic_text(topic)
    anchor = _extract_topic_anchor(topic)
    queries = []
    seen = set()

    def push(query: str, angle: str, source: str) -> None:
        normalized = _compact_text(query)
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        queries.append({"query": normalized, "angle": angle, "source": source})

    core_viewpoint = section.get("core_viewpoint") or ""
    title = section.get("title") or ""
    supporting_angles = section.get("supporting_angles") or []
    primary_angle = section.get("evidence_need") or (supporting_angles[0] if supporting_angles else "insight")

    push(core_viewpoint, primary_angle, "core_viewpoint")
    push("%s %s" % (anchor, title), primary_angle, "topic_anchor_title")
    for angle in supporting_angles[:2]:
        expanded = _build_keyword_query(anchor, angle, lane)
        if expanded:
            push(expanded, angle, "topic_anchor_angle")
        terms = LANE_ANGLE_TERMS.get(lane, LANE_ANGLE_TERMS["tech"]).get(angle, [])
        if terms:
            push("%s %s" % (core_viewpoint, terms[0]), angle, "core_viewpoint_angle")
    return queries[:4]


def _build_emotion_outline_section_queries(section: dict, topic: str) -> list[dict]:
    topic = _normalize_topic_text(topic)
    anchor = _extract_topic_anchor(topic)
    title = section.get("title") or ""
    core_viewpoint = section.get("core_viewpoint") or ""
    reader_question = section.get("reader_question") or ""
    combined = " ".join([topic, title, core_viewpoint, reader_question])
    supporting_angles = section.get("supporting_angles") or []
    primary_angle = section.get("evidence_need") or (supporting_angles[0] if supporting_angles else "story")

    relations = _extract_terms_from_text(combined, EMOTION_RELATION_TERMS, limit=4)
    scenes = _extract_terms_from_text(combined, EMOTION_SCENE_TERMS, limit=4)
    conflicts = _extract_terms_from_text(combined, EMOTION_CONFLICT_TERMS, limit=4)

    queries = []
    seen = set()

    def push(query: str, angle: str, source: str) -> None:
        normalized = _compact_text(query)
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        queries.append({"query": normalized, "angle": angle, "source": source})

    if relations and scenes and conflicts:
        push("%s %s %s" % (relations[0], scenes[0], conflicts[0]), "story", "emotion_relation_scene_conflict")
    if relations and scenes:
        push("%s %s 生活场景" % (relations[0], scenes[0]), "story", "emotion_relation_scene")
    if relations and conflicts:
        push("%s %s 真实故事" % (relations[0], conflicts[0]), "story", "emotion_relation_conflict")
    if scenes and conflicts:
        push("%s %s 老人" % (scenes[0], conflicts[0]), "story", "emotion_scene_conflict")
    if anchor and (scenes or conflicts):
        push("%s %s" % (anchor, (scenes or conflicts)[0]), primary_angle, "emotion_anchor_scene")

    # 兜底保留当前 section 的核心判断，避免只查场景而丢掉观点方向。
    push(core_viewpoint, primary_angle, "core_viewpoint")
    push("%s %s" % (anchor, title), primary_angle, "topic_anchor_title")
    return queries[:6]


def _build_outline_section_queries(section: dict, topic: str, lane: str) -> list[dict]:
    if lane == "emotion":
        return _build_emotion_outline_section_queries(section, topic)
    return _build_default_outline_section_queries(section, topic, lane)


def _build_emotion_fallback_section_queries(section: dict, topic: str) -> list[dict]:
    topic = _normalize_topic_text(topic)
    title = section.get("title") or ""
    core_viewpoint = section.get("core_viewpoint") or ""
    reader_question = section.get("reader_question") or ""
    combined = " ".join([topic, title, core_viewpoint, reader_question])

    conflicts = _extract_terms_from_text(combined, EMOTION_CONFLICT_TERMS, limit=3)
    transfer_terms = _extract_terms_from_text(combined, EMOTION_TRANSFER_TERMS, limit=3)
    elder_family_topic = _is_elder_family_topic(topic)
    if not transfer_terms:
        transfer_terms = ["家庭关系", "边界", "责任感"] if elder_family_topic else ["家庭关系", "边界", "被需要感"]

    queries = []
    seen = set()

    def push(query: str, angle: str, source: str) -> None:
        normalized = _compact_text(query)
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        queries.append({"query": normalized, "angle": angle, "source": source})

    if conflicts:
        push("家庭关系 %s %s" % (conflicts[0], transfer_terms[0]), "insight", "emotion_transfer_conflict")
    if elder_family_topic:
        push("儿女 家庭关系 边界", "insight", "emotion_transfer_elder_family")
        push("老人 家庭关系 责任感", "insight", "emotion_transfer_elder_responsibility")
        push("关系 心软 责任感", "insight", "emotion_transfer_psychology")
    else:
        push("家庭关系 边界 被需要感", "insight", "emotion_transfer_core")
        push("婚恋 关系 边界", "insight", "emotion_transfer_relationship")
        push("关系 心软 责任感", "insight", "emotion_transfer_psychology")
    return queries[:4]


def _build_tech_fallback_section_queries(section: dict, topic: str) -> list[dict]:
    topic = _normalize_topic_text(topic)
    title = section.get("title") or ""
    core_viewpoint = section.get("core_viewpoint") or ""
    reader_question = section.get("reader_question") or ""
    combined = " ".join([topic, title, core_viewpoint, reader_question])
    guard_terms = _extract_terms_from_text(combined, TECH_OUTLINE_GUARD_TERMS, limit=5)
    supporting_angles = section.get("supporting_angles") or []
    primary_angle = section.get("evidence_need") or (supporting_angles[0] if supporting_angles else "insight")

    queries = []
    seen = set()

    def push(query: str, angle: str, source: str) -> None:
        normalized = _compact_text(query)
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        queries.append({"query": normalized, "angle": angle, "source": source})

    if len(guard_terms) >= 3:
        push(" ".join(guard_terms[:4]), primary_angle, "tech_guard_terms")
    if title:
        push(title, primary_angle, "section_title")
    if guard_terms:
        for angle in supporting_angles[:2]:
            terms = LANE_ANGLE_TERMS.get("tech", {}).get(angle, [])
            if terms:
                push("%s %s" % (" ".join(guard_terms[:3]), terms[0]), angle, "tech_guard_angle")
    if core_viewpoint:
        push(core_viewpoint, primary_angle, "core_viewpoint_relaxed")
    return queries[:4]


def _extract_emotion_guard_terms(topic: str, section: dict, limit: int = 8) -> list[str]:
    combined = " ".join(
        [
            str(topic or ""),
            str(section.get("title") or ""),
            str(section.get("core_viewpoint") or ""),
            str(section.get("reader_question") or ""),
        ]
    )
    terms = []
    for vocabulary in (EMOTION_RELATION_TERMS, EMOTION_SCENE_TERMS, EMOTION_CONFLICT_TERMS):
        for term in _extract_terms_from_text(combined, vocabulary, limit=limit):
            if term not in terms:
                terms.append(term)
    return terms[:limit]


def _emotion_fallback_guard_terms(topic: str, section: dict, limit: int = 6) -> list[str]:
    combined = " ".join(
        [
            str(topic or ""),
            str(section.get("title") or ""),
            str(section.get("core_viewpoint") or ""),
            str(section.get("reader_question") or ""),
        ]
    )
    if _is_elder_family_topic(topic):
        terms = ["家庭关系", "关系", "边界", "责任感", "心软", "陪伴"]
    else:
        terms = ["家庭关系", "关系", "边界", "被需要感", "婚恋", "心软"]
    for term in _extract_terms_from_text(combined, EMOTION_CONFLICT_TERMS + EMOTION_TRANSFER_TERMS, limit=limit):
        if term not in terms:
            terms.insert(0, term)
    return terms[:limit]


def _extract_tech_guard_terms(topic: str, section: dict, fallback: bool = False, limit: int = 8) -> list[str]:
    combined = " ".join(
        [
            str(topic or ""),
            str(section.get("title") or ""),
            str(section.get("core_viewpoint") or ""),
            str(section.get("reader_question") or ""),
        ]
    )
    terms = _extract_terms_from_text(combined, TECH_OUTLINE_GUARD_TERMS, limit=limit)
    if terms:
        return terms[:limit]
    if fallback:
        return []
    return _extract_search_guard_terms(topic, section.get("title") or "", section.get("core_viewpoint") or "", limit=limit)


def _is_elder_family_topic(text: str) -> bool:
    return any(term in str(text or "") for term in EMOTION_ELDER_FAMILY_TERMS)


def _emotion_material_block_terms(topic: str, fallback: bool = False) -> list[str]:
    terms = list(EMOTION_BUSINESS_TECH_BLOCK_TERMS)
    if _is_elder_family_topic(topic) and not fallback:
        terms.extend(EMOTION_ELDER_FAMILY_BLOCK_TERMS)
    return terms


def _outline_material_search_thresholds(lane: str, fallback: bool = False) -> tuple[float, float]:
    if lane == "emotion":
        # 情感素材库目前更偏心理/关系洞察，精确生活场景覆盖较少；
        # 情感文只降低情感 lane 的阈值，保留技术号等其他频道原策略。
        return (0.0, 0.38 if fallback else 0.40)
    if lane == "tech" and fallback:
        return (0.0, 0.40)
    return (0.04, 0.44)


def _outline_candidate_allowed(section: dict, item: dict) -> bool:
    item_type = str(item.get("type") or "").strip()
    if item_type != "data":
        return True
    evidence_need = section.get("evidence_need") or ""
    supporting_angles = section.get("supporting_angles") or []
    return evidence_need == "cost" or "cost" in supporting_angles


def fetch_materials_for_outline_sections(
    outline: dict,
    topic: str,
    lane: str,
    material_types: list,
    max_per_source: int = 1,
    limit_per_section: int = 2,
    debug: bool = False,
) -> dict:
    """按 outline section 召回素材，并把结果写回 section.materials。"""
    import json
    import tempfile
    import time

    search_script = STRATEGY_MATERIAL_ENGINE_ROOT / "scripts" / "search_materials.py"
    batch_search_script = STRATEGY_MATERIAL_ENGINE_ROOT / "scripts" / "batch_search_materials.py"
    enriched = dict(outline or {})
    sections = [dict(section) for section in (outline.get("sections") or [])]
    enriched["sections"] = sections
    recall_meta = {
        "status": "attempted",
        "sections_total": len(sections),
        "sections_with_materials": 0,
        "materials_total": 0,
        "query_count": 0,
        "fallback_query_count": 0,
        "batch_calls": 0,
        "elapsed_seconds": 0.0,
        "reason": "",
    }
    started_at = time.monotonic()
    if not search_script.exists():
        recall_meta["status"] = "skipped"
        recall_meta["reason"] = "search_materials.py not found"
        enriched["section_materials_recall"] = recall_meta
        return enriched

    global_claims = set()
    debug_rows = []
    per_query_limit = max(limit_per_section * 4, 6)
    section_candidates_by_pos: list[dict[str, dict]] = [{} for _ in sections]

    def build_search_job(section_pos: int, spec: dict, fallback: bool = False) -> dict:
        section = sections[section_pos]
        prefer_type = _prefer_type_for_outline_section(section, material_types)
        if lane == "emotion":
            guard_terms = (
                _emotion_fallback_guard_terms(topic, section)
                if fallback
                else _extract_emotion_guard_terms(topic, section)
            )
        elif lane == "tech":
            guard_terms = _extract_tech_guard_terms(topic, section, fallback=fallback)
        else:
            guard_terms = _extract_search_guard_terms(topic)
        min_domain_overlap, min_vector_score = _outline_material_search_thresholds(lane, fallback=fallback)
        block_terms = _emotion_material_block_terms(topic, fallback=fallback) if lane == "emotion" else []
        return {
            "id": "",
            "section": section.get("index", section_pos + 1),
            "section_pos": section_pos,
            "query": spec["query"],
            "angle": spec.get("angle", ""),
            "source": spec.get("source", ""),
            "fallback": fallback,
            "limit": per_query_limit,
            "max_per_source": max_per_source,
            "domain_query": _compact_text(
                "%s %s %s" % (topic, section.get("title") or "", section.get("core_viewpoint") or "")
            ),
            "min_domain_overlap": min_domain_overlap,
            "min_vector_score": min_vector_score,
            "require_terms": guard_terms,
            "min_required_term_hits": 1 if guard_terms else 0,
            "block_terms": block_terms,
            "prefer_type": prefer_type,
        }

    def run_search_jobs(jobs: list[dict], timeout: int = 180) -> dict[str, dict]:
        if not jobs:
            return {}
        recall_meta["batch_calls"] += 1
        recall_meta["query_count"] += len(jobs)
        if batch_search_script.exists():
            query_path = None
            try:
                with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
                    json.dump({"queries": jobs}, handle, ensure_ascii=False)
                    query_path = Path(handle.name)
                cmd = [
                    "/opt/miniconda3/bin/python3",
                    str(batch_search_script),
                    "--root",
                    str(STRATEGY_MATERIAL_ENGINE_ROOT),
                    "--queries-json",
                    str(query_path),
                    "--reranker",
                    "none",
                ]
                result = run_captured_subprocess(cmd, timeout=timeout)
                if result.returncode != 0:
                    return {
                        job["id"]: {
                            "id": job["id"],
                            "error": "returncode=%s %s" % (result.returncode, _compact_text(result.stderr)[:160]),
                            "results": [],
                        }
                        for job in jobs
                    }
                rows = {}
                for line in result.stdout.strip().splitlines():
                    if not line.strip():
                        continue
                    try:
                        payload = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if payload.get("id"):
                        rows[str(payload["id"])] = payload
                return rows
            except (subprocess.TimeoutExpired, FileNotFoundError, Exception) as exc:
                return {job["id"]: {"id": job["id"], "error": str(exc), "results": []} for job in jobs}
            finally:
                if query_path:
                    query_path.unlink(missing_ok=True)

        rows = {}
        for job in jobs:
            if lane == "emotion":
                block_terms = _emotion_material_block_terms(topic, fallback=bool(job.get("fallback")))
            else:
                block_terms = []
            cmd = [
                "/opt/miniconda3/bin/python3",
                str(search_script),
                job["query"],
                "--root", str(STRATEGY_MATERIAL_ENGINE_ROOT),
                "--limit", str(job.get("limit") or per_query_limit),
                "--max-per-source", str(max_per_source),
                "--reranker", "none",
                "--domain-query",
                str(job.get("domain_query") or ""),
                "--min-domain-overlap", str(job.get("min_domain_overlap") or 0.0),
                "--min-vector-score", str(job.get("min_vector_score") or 0.0),
            ]
            guard_terms = job.get("require_terms") or []
            if guard_terms:
                cmd.extend(["--require-term", ",".join(guard_terms), "--min-required-term-hits", "1"])
            if block_terms:
                cmd.extend(["--block-term", ",".join(block_terms)])
            if job.get("prefer_type"):
                cmd.extend(["--prefer-type", str(job["prefer_type"])])

            try:
                result = run_captured_subprocess(cmd, timeout=60)
            except (subprocess.TimeoutExpired, FileNotFoundError, Exception) as exc:
                rows[job["id"]] = {"id": job["id"], "error": str(exc), "results": []}
                continue
            if result.returncode != 0:
                rows[job["id"]] = {
                    "id": job["id"],
                    "error": "returncode=%s %s" % (result.returncode, _compact_text(result.stderr)[:160]),
                    "results": [],
                }
                continue
            results = []
            for line in result.stdout.strip().splitlines():
                if not line.strip():
                    continue
                try:
                    results.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
            rows[job["id"]] = {"id": job["id"], "results": results}
        return rows

    def collect_job_results(jobs: list[dict], rows_by_id: dict[str, dict]) -> None:
        for job in jobs:
            section_candidates = section_candidates_by_pos[job["section_pos"]]
            row = rows_by_id.get(job["id"]) or {"results": [], "error": "missing batch result"}
            hits = 0
            unique_claims = 0
            for item in row.get("results") or []:
                hits += 1
                claim = item.get("primary_claim", "")
                if not claim:
                    continue
                existing = section_candidates.get(claim)
                score = item.get("score", 0)
                if not existing or score > existing.get("_score", 0):
                    section_candidates[claim] = {
                        "primary_claim": claim,
                        "type": item.get("type", ""),
                        "role": item.get("role", ""),
                        "source": item.get("source") or item.get("path", ""),
                        "_score": score,
                    }
                    unique_claims += 1
            debug_rows.append(
                {
                    "section": job.get("section"),
                    "query": job["query"],
                    "angle": job.get("angle", ""),
                    "source": job.get("source", ""),
                    "fallback": bool(job.get("fallback")),
                    "guard_terms": job.get("require_terms") or [],
                    "hits": hits,
                    "unique_claims": unique_claims,
                    "error": row.get("error", ""),
                }
            )

    primary_jobs = []
    primary_query_budget = 30
    fallback_query_budget = 20
    for section_pos, section in enumerate(sections):
        for spec in _build_outline_section_queries(section, topic, lane):
            if len(primary_jobs) >= primary_query_budget:
                break
            job = build_search_job(section_pos, spec, fallback=False)
            job["id"] = "primary-%s" % len(primary_jobs)
            primary_jobs.append(job)

    collect_job_results(primary_jobs, run_search_jobs(primary_jobs))

    fallback_jobs = []
    for section_pos, section_candidates in enumerate(section_candidates_by_pos):
        if section_candidates:
            continue
        section = sections[section_pos]
        if lane == "emotion":
            fallback_specs = _build_emotion_fallback_section_queries(section, topic)
        elif lane == "tech":
            fallback_specs = _build_tech_fallback_section_queries(section, topic)
        else:
            fallback_specs = []
        for spec in fallback_specs:
            if len(fallback_jobs) >= fallback_query_budget:
                break
            job = build_search_job(section_pos, spec, fallback=True)
            job["id"] = "fallback-%s" % len(fallback_jobs)
            fallback_jobs.append(job)

    if fallback_jobs:
        recall_meta["fallback_query_count"] = len(fallback_jobs)
        collect_job_results(fallback_jobs, run_search_jobs(fallback_jobs))

    for section_pos, section in enumerate(sections):
        section_materials: list[dict] = []
        section_candidates = section_candidates_by_pos[section_pos]

        sorted_candidates = sorted(section_candidates.values(), key=lambda x: x.get("_score", 0), reverse=True)
        for item in sorted_candidates:
            if len(section_materials) >= limit_per_section:
                break
            if not _outline_candidate_allowed(section, item):
                continue
            claim = item.get("primary_claim")
            if not claim or claim in global_claims:
                continue
            global_claims.add(claim)
            picked = dict(item)
            picked.pop("_score", None)
            section_materials.append(picked)
        if lane == "emotion" and not section_materials:
            for item in sorted_candidates:
                if len(section_materials) >= limit_per_section:
                    break
                if not _outline_candidate_allowed(section, item):
                    continue
                claim = item.get("primary_claim")
                if not claim:
                    continue
                picked = dict(item)
                picked.pop("_score", None)
                section_materials.append(picked)
        if lane == "tech" and not section_materials:
            for item in sorted_candidates:
                if len(section_materials) >= limit_per_section:
                    break
                if not _outline_candidate_allowed(section, item):
                    continue
                claim = item.get("primary_claim")
                if not claim:
                    continue
                picked = dict(item)
                picked.pop("_score", None)
                section_materials.append(picked)
        section["materials"] = section_materials
        if section_materials:
            recall_meta["sections_with_materials"] += 1
            recall_meta["materials_total"] += len(section_materials)

    if recall_meta["materials_total"] <= 0:
        recall_meta["status"] = "attempted_empty"
        recall_meta["reason"] = "no trusted section materials matched"
    else:
        recall_meta["status"] = "matched"
    recall_meta["elapsed_seconds"] = round(time.monotonic() - started_at, 3)
    enriched["section_materials_recall"] = recall_meta

    if debug:
        print("# outline-material-query-debug")
        print("- query_count: %s" % recall_meta["query_count"])
        print("- fallback_query_count: %s" % recall_meta["fallback_query_count"])
        print("- batch_calls: %s" % recall_meta["batch_calls"])
        print("- elapsed_seconds: %s" % recall_meta["elapsed_seconds"])
        for row in debug_rows:
            print(
                "- section[%s] query[%s/%s%s]: %s | guard=%s | hits=%s | unique_claims=%s"
                % (
                    row["section"],
                    row["angle"] or "insight",
                    row["source"] or "-",
                    "/fallback" if row.get("fallback") else "",
                    row["query"],
                    ",".join(row.get("guard_terms") or []) or "-",
                    row["hits"],
                    row["unique_claims"],
                )
            )
            if row.get("error"):
                print("  error: %s" % row["error"])

    return enriched


def build_section_materials_recall_meta(outline: dict, status: str = "unknown", reason: str = "") -> dict:
    sections = (outline or {}).get("sections") or []
    materials_total = 0
    sections_with_materials = 0
    for section in sections:
        materials = section.get("materials") or []
        if materials:
            sections_with_materials += 1
            materials_total += len(materials)
    return {
        "status": status,
        "sections_total": len(sections),
        "sections_with_materials": sections_with_materials,
        "materials_total": materials_total,
        "reason": reason,
    }


def infer_article_subtype(framework: Dict, payload: Dict) -> str:
    subtype = (framework.get("subtype") or "").strip()
    if subtype:
        return subtype
    material_types = payload.get("material_types") or []
    if "story" in material_types:
        return "emotional_story"
    if "case" in material_types:
        return "case_exploration"
    if "problem" in material_types:
        return "mistake_breakdown"
    if "list" in material_types:
        return "list_exploration"
    return "opinion"


def infer_theme_features(brief: Dict, draft_path: Path = None) -> Dict:
    features: Dict[str, object] = {}
    lane = brief.get("lane")
    material_types = brief.get("material_types") or []

    features["article_length"] = "medium" if brief.get("material_depth") == "medium" else (
        "long" if brief.get("material_depth") == "heavy" else "short"
    )
    features["contains_table"] = "list" in material_types
    features["contains_code"] = lane == "tech"
    features["emotional_density"] = "high" if lane == "emotion" else "low"
    if lane == "emotion":
        features["audience_age"] = "senior"

    if draft_path and draft_path.exists():
        source_features = rt.analyze_source(draft_path)
        features.update(source_features)

    return features


def output_base_path(channel_id: str, topic: str) -> Path:
    date_str = datetime.now().strftime("%Y-%m-%d")
    ensure_dir(FLOW_OUTPUT_ROOT)
    filename = "%s_%s_%s" % (date_str, channel_id, slugify(topic))
    return FLOW_OUTPUT_ROOT / filename


def save_brief(channel_id: str, topic: str, brief: Dict) -> Path:
    output_path = output_base_path(channel_id, topic).with_suffix(".yaml")
    with open(output_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(brief, f, allow_unicode=True, sort_keys=False)
    return output_path


def outline_prompt_output_path(channel_id: str, topic: str) -> Path:
    return output_base_path(channel_id, topic).with_suffix(".outline.prompt.md")


def outline_output_path(channel_id: str, topic: str) -> Path:
    return output_base_path(channel_id, topic).with_suffix(".outline.yaml")


def title_prompt_output_path(channel_id: str, topic: str) -> Path:
    return output_base_path(channel_id, topic).with_suffix(".title.prompt.md")


def _format_title_pattern_for_prompt(framework: Dict) -> str:
    title_pattern = framework.get("title_pattern")
    if isinstance(title_pattern, dict) and title_pattern:
        return yaml.safe_dump(title_pattern, allow_unicode=True, sort_keys=False).strip()
    return """title_pattern: 未配置
fallback_basis:
  summary: %s
  hook_pattern: %s
  section_flow:
%s
  constraints:
%s""" % (
        framework.get("summary") or "-",
        framework.get("hook_pattern") or "-",
        "\n".join("    - %s" % item for item in framework.get("section_flow") or []) or "    - -",
        "\n".join("    - %s" % item for item in framework.get("constraints") or []) or "    - -",
    )


def build_title_generation_prompt(
    channel_id: str,
    lane: str,
    persona: Dict,
    selected,
    payload: Dict,
) -> str:
    framework = selected.data
    goals = ", ".join(payload.get("goals") or []) or "-"
    material_types = ", ".join(payload.get("material_types") or []) or "-"
    title_style = _format_title_pattern_for_prompt(framework)
    return """# 标题推荐指令

你正在当前 AI CLI 会话中，为一篇公众号文章生成标题候选。不要调用外部工具，不要写大纲，不要写正文。

## 基础信息

- channel: `{channel}`
- lane: `{lane}`
- topic: {topic}
- goals: {goals}
- material_types: {material_types}
- material_depth: {material_depth}

## Persona

- id: `{persona_id}`
- path: `{persona_path}`

```text
{persona_content}
```

## 已选 Framework

- id: `{framework_id}`
- name: {framework_name}
- summary: {framework_summary}
- hook_pattern: {hook_pattern}
- ending_pattern: {ending_pattern}

## 爆文标题样式

```yaml
{title_style}
```

## 输出要求

1. 只输出 3 条标题候选，不要输出大纲或正文。
2. 3 条标题必须彼此不同，不能只是同义替换。
3. 标题必须围绕 topic，不要偏离选题。
4. 优先遵循 `title_pattern`；如果 `title_pattern` 未配置，就根据 fallback_basis 的框架开头、结构和约束生成。
5. 每条标题给出 `0.00` 到 `1.00` 的置信度评分。
6. 按置信度从高到低排序。
7. 不要照搬任何爆文原标题、具体人物、具体数字或专属事件细节；只能复用标题结构、情绪按钮、信息差和变量槽位。

## 输出格式

1. 标题：...
   置信度：0.xx
   理由：一句话说明为什么贴合框架标题样式

2. 标题：...
   置信度：0.xx
   理由：一句话说明为什么贴合框架标题样式

3. 标题：...
   置信度：0.xx
   理由：一句话说明为什么贴合框架标题样式

最后追加一句：
回复 1/2/3 选择标题；不满意可以给修改建议让我重出 3 条；也可以直接给一个你自己的标题。
""".format(
        channel=channel_id,
        lane=lane,
        topic=payload["topic"].split("\n补充素材：", 1)[0],
        goals=goals,
        material_types=material_types,
        material_depth=payload.get("material_depth") or "-",
        persona_id=persona["id"],
        persona_path=persona["path"],
        persona_content=persona["content"].strip(),
        framework_id=framework.get("id") or "-",
        framework_name=framework.get("name") or "-",
        framework_summary=framework.get("summary") or "-",
        hook_pattern=framework.get("hook_pattern") or "-",
        ending_pattern=framework.get("ending_pattern") or "-",
        title_style=title_style,
    )


def save_title_prompt(channel_id: str, topic: str, content: str) -> Path:
    output_path = title_prompt_output_path(channel_id, topic)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)
    return output_path


def save_outline_prompt(channel_id: str, topic: str, content: str) -> Path:
    output_path = outline_prompt_output_path(channel_id, topic)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)
    return output_path


ALLOWED_OUTLINE_ANGLES = set(ANGLE_ORDER)
OUTLINE_FUNCTIONS = {"hook", "story", "problem", "insight", "method", "ending"}
COMMON_PLACEHOLDER_NAMES = [
    "甲柱子", "乙栓子", "柱子", "栓子", "张三", "李四", "王五", "赵六",
    "小明", "小红", "小刚", "小美", "阿强", "阿明", "阿伟",
]
TECH_PLACEHOLDER_NAMES = ["老王", "小张", "小李", "小王"]
OUTLINE_NAMING_FIELDS = ["title", "reader_question", "core_viewpoint", "transition_to_next"]


def _normalize_outline_angle(value: object) -> str:
    text = str(value or "").strip().lower()
    aliases = {
        "case": "story",
        "scene": "story",
        "data": "cost",
        "contrast": "cost",
        "action": "method",
        "solution": "method",
        "principle": "insight",
        "reflection": "insight",
        "trap": "mistake",
        "ending": "turning_point",
        "summary": "turning_point",
    }
    text = aliases.get(text, text)
    return text if text in ALLOWED_OUTLINE_ANGLES else ""


def _compact_for_compare(value: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", str(value or "").lower())


def _looks_like_topic_title(section_title: str, topic: str) -> bool:
    title_key = _compact_for_compare(section_title)
    topic_key = _compact_for_compare(topic)
    if not title_key or not topic_key:
        return False
    if title_key == topic_key:
        return True
    if len(title_key) >= 8 and title_key in topic_key:
        return True
    if len(topic_key) >= 8 and topic_key in title_key:
        return True
    title_terms = set(re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]{2,}", str(section_title).lower()))
    topic_terms = set(re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]{2,}", str(topic).lower()))
    if not title_terms or not topic_terms:
        return False
    overlap = len(title_terms & topic_terms) / max(len(title_terms), 1)
    return overlap >= 0.8


def _placeholder_names_for_lane(lane: str) -> list[str]:
    names = list(COMMON_PLACEHOLDER_NAMES)
    if lane == "tech":
        names.extend(TECH_PLACEHOLDER_NAMES)
    return names


def _find_placeholder_character_name(text: str, lane: str = "") -> str:
    text = str(text or "")
    if not text:
        return ""
    for name in _placeholder_names_for_lane(lane):
        if name and name in text:
            return name
    if re.search(r"[甲乙丙丁][柱栓]", text):
        return re.search(r"[甲乙丙丁][柱栓]", text).group(0)
    return ""


def _naming_replacement_hint(lane: str) -> str:
    if lane == "emotion":
        return "请改成“楼下张姐/我那个老同事/菜市场认识的李姐”等关系或生活场景称呼"
    return "请改成“一个外包测试同事/前同事/项目组里一个测试/这位同事”等身份或场景称呼"


def _validate_outline_character_naming(raw: dict, fallback_index: int, lane: str = "") -> None:
    for field in OUTLINE_NAMING_FIELDS:
        bad_name = _find_placeholder_character_name(raw.get(field), lane=lane)
        if bad_name:
            raise ValueError(
                "outline.sections[%s].%s 出现占位人名“%s”，%s。"
                % (fallback_index, field, bad_name, _naming_replacement_hint(lane))
            )


def build_character_naming_guidance(lane: str) -> str:
    if lane == "emotion":
        return """## 人物与案例命名规则

- 可以使用符合人设的生活称呼，如“楼下张姐”“我那个老同事”“菜市场认识的李姐”
- 禁止使用“甲柱子”“乙栓子”“柱子”“栓子”“小明”“小红”“张三李四”等占位人名或网文式假名
- 不需要给每个案例人物起名字，优先用关系、场景、身份承接"""
    return """## 人物与案例命名规则

- 技术号不要给案例人物编虚构姓名或占位人名，如“柱子”“栓子”“阿强”“小明”“张三”“李四”“老王”“小张”
- 涉及他人时用身份/关系/场景称呼，如“一个外包测试同事”“前同事”“面试官”“项目组里一个测试”“那个转 Java 的同事”
- 如果没有真实经验或可信素材，不编完整人物故事，改写成“我见过一种情况”“面试里常见一种简历”“项目组里常发生这种事”"""


def _normalize_outline_sections(raw_sections: object, topic: str = "", lane: str = "") -> list[dict]:
    if not isinstance(raw_sections, list) or not raw_sections:
        raise ValueError("outline.sections 必须是非空列表")

    sections = []
    seen_viewpoints = set()
    for fallback_index, raw in enumerate(raw_sections, start=1):
        if not isinstance(raw, dict):
            raise ValueError("outline.sections[%s] 必须是对象" % fallback_index)

        _validate_outline_character_naming(raw, fallback_index, lane=lane)

        title = _compact_text(raw.get("title"))
        core_viewpoint = _compact_text(raw.get("core_viewpoint"))
        if not title:
            raise ValueError("outline.sections[%s].title 不能为空" % fallback_index)
        if not core_viewpoint:
            raise ValueError("outline.sections[%s].core_viewpoint 不能为空" % fallback_index)
        if title == core_viewpoint:
            raise ValueError("outline.sections[%s] 的 title 和 core_viewpoint 不能完全相同" % fallback_index)
        if fallback_index == 1 and _looks_like_topic_title(title, topic):
            raise ValueError("outline.sections[1].title 不能照搬文章 topic 或只做轻微改写，请改成具体情境/动作/冲突")
        if core_viewpoint in seen_viewpoints:
            raise ValueError("outline.sections[%s].core_viewpoint 与前文重复" % fallback_index)
        seen_viewpoints.add(core_viewpoint)

        supporting_angles = []
        for value in raw.get("supporting_angles") or []:
            angle = _normalize_outline_angle(value)
            if angle and angle not in supporting_angles:
                supporting_angles.append(angle)

        evidence_need = _normalize_outline_angle(raw.get("evidence_need"))
        if evidence_need and evidence_need not in supporting_angles:
            supporting_angles.insert(0, evidence_need)
        if not supporting_angles:
            supporting_angles = ["insight"]
            evidence_need = "insight"
        elif not evidence_need:
            evidence_need = supporting_angles[0]

        section_function = str(raw.get("function") or "").strip().lower()
        if section_function not in OUTLINE_FUNCTIONS:
            section_function = "ending" if fallback_index == len(raw_sections) else "insight"

        sections.append(
            {
                "index": int(raw.get("index") or fallback_index),
                "title": title,
                "function": section_function,
                "reader_question": _compact_text(raw.get("reader_question")),
                "core_viewpoint": core_viewpoint,
                "evidence_need": evidence_need,
                "supporting_angles": supporting_angles[:3],
                "transition_to_next": _compact_text(raw.get("transition_to_next")),
                "materials": raw.get("materials") if isinstance(raw.get("materials"), list) else [],
            }
        )

    if not 3 <= len(sections) <= 6:
        raise ValueError("outline.sections 建议保持 3-6 节，当前为 %s 节" % len(sections))
    if sections[-1]["function"] != "ending":
        sections[-1]["function"] = "ending"
    return sections


def load_outline_file(path: Path, lane: str = "") -> dict:
    if not path.exists():
        raise FileNotFoundError("未找到 outline 文件: %s" % path)
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError("outline 文件必须是 YAML 对象")
    raw_outline = data.get("outline") if isinstance(data.get("outline"), dict) else data
    topic = _compact_text(raw_outline.get("topic"))
    sections = _normalize_outline_sections(raw_outline.get("sections"), topic=topic, lane=lane)
    return {
        "version": raw_outline.get("version") or 1,
        "topic": topic,
        "article_title": _compact_text(raw_outline.get("article_title")),
        "thesis": _compact_text(raw_outline.get("thesis")),
        "source_path": str(path),
        "sections": sections,
    }


def build_outline_prompt(brief: Dict, persona: Dict) -> str:
    framework = brief["framework"]
    article_title = brief.get("article_title") or brief["topic"]
    goals = ", ".join(brief.get("goals") or []) or "-"
    material_types = ", ".join(brief.get("material_types") or []) or "-"
    required_materials = "\n".join("- %s" % item for item in framework.get("required_materials") or []) or "- 无"
    section_flow = "\n".join("- %s" % item for item in framework.get("section_flow") or []) or "- 自行组织"
    constraints = "\n".join("- %s" % item for item in framework.get("constraints") or []) or "- 无"
    character_naming_guidance = build_character_naming_guidance(brief.get("lane") or "")
    return """# 大纲生成指令

你正在当前 AI CLI 会话中为一篇公众号文章生成结构化大纲。不要调用外部工具，不要写正文，只输出 YAML。

## 基础信息

- channel: `{channel}`
- lane: `{lane}`
- topic: {topic}
- article_title: {article_title}
- goals: {goals}
- material_types: {material_types}
- material_depth: {material_depth}

## Persona

- id: `{persona_id}`
- path: `{persona_path}`

```text
{persona_content}
```

## Framework

- id: `{framework_id}`
- name: {framework_name}
- summary: {framework_summary}
- hook_pattern: {hook_pattern}
- ending_pattern: {ending_pattern}

### Required Materials
{required_materials}

### Section Flow
{section_flow}

### Constraints
{constraints}

{character_naming_guidance}

## 输出要求

只输出 YAML，顶层字段必须是 `outline`。不要输出正文，不要输出解释。

```yaml
outline:
  version: 1
  topic: "{topic}"
  article_title: "{article_title}"
  thesis: "整篇文章最终要让读者接受的一个判断"
  sections:
    - index: 1
      title: "小节标题"
      function: "hook"
      reader_question: "读者看到这一节时，心里会问什么"
      core_viewpoint: "这一节的一句话核心观点，必须是独立判断"
      evidence_need: "story"
      supporting_angles: ["story", "cost"]
      transition_to_next: "这一节如何自然过渡到下一节"
      materials: []
```

字段约束：

1. sections 必须是 3-6 节。
2. function 只能从 `hook/story/problem/insight/method/ending` 中选择，最后一节必须是 `ending`。
3. evidence_need 和 supporting_angles 只能从 `story/method/insight/mistake/cost/turning_point` 中选择。
4. core_viewpoint 不能等于 title，不能写成空泛小标题，必须是一句能支撑正文展开的判断。
5. 相邻 section 的 core_viewpoint 不能重复或同义反复。
6. materials 保持空列表，后续由脚本按节召回素材。
7. 技术号小标题直接写语义标题；情感号小标题可用“编号 + 语义标题”。
8. 第一节 title 不能照搬文章 topic，也不能只是把 topic 稍微缩短或改几个字；第一节要承接开头场景，写成具体情境/动作/冲突。
9. title / reader_question / core_viewpoint / transition_to_next 不得出现占位人名、土味虚构名、甲乙丙丁式人物；需要写人时按“人物与案例命名规则”使用身份或场景称呼。
10. article_title 是最终文章标题，不能把它原样用作第一节小标题；第一节小标题必须承接开头场景。
""".format(
        channel=brief["channel"],
        lane=brief["lane"],
        topic=brief["topic"],
        article_title=article_title,
        goals=goals,
        material_types=material_types,
        material_depth=brief.get("material_depth") or "-",
        persona_id=persona["id"],
        persona_path=persona["path"],
        persona_content=persona["content"].strip(),
        framework_id=framework.get("id") or "-",
        framework_name=framework.get("name") or "-",
        framework_summary=framework.get("summary") or "-",
        hook_pattern=framework.get("hook_pattern") or "-",
        ending_pattern=framework.get("ending_pattern") or "-",
        required_materials=required_materials,
        section_flow=section_flow,
        constraints=constraints,
        character_naming_guidance=character_naming_guidance,
    )


def build_outline_guidance(outline: dict) -> str:
    if not outline or not outline.get("sections"):
        return ""
    lines = ["## 大纲 + 分节素材指引", ""]
    recall_meta = outline.get("section_materials_recall") or {}
    if recall_meta:
        lines.extend(
            [
                "### 分节素材召回状态",
                "- status: `%s`" % (recall_meta.get("status") or "unknown"),
                "- sections_with_materials: %s/%s"
                % (recall_meta.get("sections_with_materials", 0), recall_meta.get("sections_total", 0)),
                "- materials_total: %s" % recall_meta.get("materials_total", 0),
            ]
        )
        if recall_meta.get("reason"):
            lines.append("- reason: %s" % recall_meta.get("reason"))
        if recall_meta.get("status") in {"skipped", "attempted_empty"}:
            lines.append("- 注意：本次分节素材不足，正文必须优先使用 persona 真实经历，不要编造来源或假案例")
        lines.append("")
    if outline.get("thesis"):
        lines.extend(["整篇 thesis：%s" % outline["thesis"], ""])
    for section in outline.get("sections") or []:
        lines.append("### 第%s节：%s" % (section.get("index"), section.get("title")))
        if section.get("function"):
            lines.append("- section_function: `%s`" % section.get("function"))
        if section.get("reader_question"):
            lines.append("- reader_question: %s" % section.get("reader_question"))
        lines.append("- core_viewpoint: %s" % section.get("core_viewpoint"))
        lines.append("- evidence_need: `%s`" % section.get("evidence_need"))
        if section.get("supporting_angles"):
            lines.append("- supporting_angles: %s" % ", ".join(section.get("supporting_angles") or []))
        lines.append("- 可选参考:")
        materials = section.get("materials") or []
        if materials:
            for mat in materials:
                claim = mat.get("primary_claim", "")
                if claim:
                    lines.append("  - [%s] %s" % (mat.get("type") or "-", claim))
        else:
            lines.append("  - 无（素材库未找到可信匹配，不要硬套无关案例或编造来源）")
        if section.get("transition_to_next"):
            lines.append("- transition_to_next: %s" % section.get("transition_to_next"))
        lines.append("")
    return "\n".join(lines).rstrip()


def build_opening_guidance(lane: str, framework: Dict) -> str:
    hook_pattern = framework.get("hook_pattern") or "按框架开头方式切入"
    if lane == "emotion":
        return """## 开头硬约束（影响推荐率）

正文开头决定读者是否继续看，必须单独打磨，不要直接进入观点。

- 正文第一屏必须先写 **无标题引入段**，不要第一行就写小标题，也不要重复文章标题
- 前 3 句内必须出现一个具体生活场景、一个反常点或一句带冲突的话
- 第一个小标题不能照搬文章标题，也不能只是把标题换几个字；它必须是开头场景之后自然进入的具体情境/动作/冲突
- 开头先让读者心里冒出问题：她为什么这么想？后来发生了什么？这事是不是也像我家？
- 禁止用“我想说的是”“今天聊聊”“很多人都知道”“人到晚年要明白”这类讲道理开场
- 禁止第一段直接下结论、讲观点、做总结；观点要等场景把人拉住以后再露出来
- 建议开头结构：一句反常实话 / 一个被人笑话的场面 / 一个夜里睡不着的动作 → 两三句生活细节 → 抛出“我那天才想明白”的钩子
- 本篇框架开头方式：%s""" % hook_pattern
    return """## 开头硬约束（影响推荐率）

- 正文第一屏必须先写无标题引入段，不要第一行就重复文章标题或直接进入小标题
- 前 3 句内交代一个具体问题、反常现象或结果差异
- 第一个小标题不能照搬文章标题，也不能只是把标题换几个字；它必须承接开头里的具体问题
- 禁止用泛泛背景介绍开场，先给读者一个继续读的理由
- 本篇框架开头方式：%s""" % hook_pattern


def build_writing_prompt(brief: Dict, persona: Dict) -> str:
    framework = brief["framework"]
    theme_recommendation = brief.get("theme_recommendation") or {}
    article_title = brief.get("article_title") or brief["topic"]
    goals = ", ".join(brief.get("goals") or []) or "-"
    material_types = ", ".join(brief.get("material_types") or []) or "-"
    required_materials = "\n".join("- %s" % item for item in framework.get("required_materials") or []) or "- 无"
    section_flow = "\n".join("- %s" % item for item in framework.get("section_flow") or []) or "- 自行组织"
    constraints = "\n".join("- %s" % item for item in framework.get("constraints") or []) or "- 无"
    supplemental = brief.get("supplemental_materials") or ""
    auto_materials = brief.get("auto_materials") or []
    outline_guidance = build_outline_guidance(brief.get("outline") or {})
    opening_guidance = build_opening_guidance(brief.get("lane") or "", framework)
    character_naming_guidance = build_character_naming_guidance(brief.get("lane") or "")
    
    # 构建 auto_materials 文本：只给 primary_claim 和 type，不给原文
    auto_materials_text = ""
    if auto_materials:
        lines = []
        for i, mat in enumerate(auto_materials, 1):
            claim = mat.get("primary_claim", "")
            mat_type = mat.get("type", "")
            if claim:
                lines.append("%d. [%s] %s" % (i, mat_type, claim))
        if lines:
            auto_materials_text = "\n".join(lines)
    
    if outline_guidance:
        content_guidance = """{outline_guidance}

## 补充素材

{supplemental}
 
> 注意：分节素材均为观点方向指引（primary_claim），不是原文。可选参考不是必须复述的材料，请用自己的论证、案例和表达重新阐述，不要搬运原文内容。
""".format(
            outline_guidance=outline_guidance,
            supplemental=supplemental or "无",
        )
        outline_requirements = """11. 每节必须围绕大纲给定的 core_viewpoint 展开，用自己的论证逻辑和案例去支撑
12. 大纲中的“可选参考”只是方向提示，不是要复述的内容；可以借用论证方向、换自己的例子，也可以完全不用
13. 禁止出现“正如XX所说”“有人总结过”“有篇文章提到过”这类引用句式
14. 如果某个 section 的可选参考与你的真实经验矛盾，以你的经验为准"""
    else:
        if not supplemental and not auto_materials_text:
            supplemental = "无（自动召回未找到可信匹配素材，不要为了凑素材硬套无关案例或编造来源。）"
        elif not supplemental:
            supplemental = auto_materials_text
        else:
            supplemental = auto_materials_text + "\n\n用户手动补充：\n" + supplemental
        content_guidance = """## 补充素材

{supplemental}
 
> 注意：以上素材均为观点方向指引（primary_claim），不是原文。请用自己的论证、案例和表达重新阐述，不要搬运原文内容。
""".format(supplemental=supplemental)
        outline_requirements = ""
    recommended_theme = theme_recommendation.get("recommended_theme") or "-"
    theme_candidates = "\n".join(
        "- %s (%s)"
        % (item.get("display_name"), item.get("theme_id"))
        for item in (theme_recommendation.get("candidates") or [])[:3]
    ) or "- 无"
    return """# 写作指令包

## 任务

请围绕下面这个选题，按指定 `persona + framework` 写一篇公众号正文初稿。

## 基础信息

- channel: `{channel}`
- channel_display_name: `{channel_display_name}`
- lane: `{lane}`
- topic: {topic}
- article_title: {article_title}
- goals: {goals}
- material_types: {material_types}
- material_depth: {material_depth}

## Persona

- id: `{persona_id}`
- path: `{persona_path}`

### Persona 原文

```text
{persona_content}
```

## Framework

- id: `{framework_id}`
- name: {framework_name}
- summary: {framework_summary}
- hook_pattern: {hook_pattern}
- ending_pattern: {ending_pattern}

### Required Materials
{required_materials}

### Section Flow
{section_flow}

### Constraints
{constraints}

{content_guidance}

{character_naming_guidance}

{opening_guidance}

## 推荐排版主题

- recommended_theme: `{recommended_theme}`

### Theme Candidates
{theme_candidates}

## 输出要求

1. 只输出 **Markdown 正文初稿**
2. 必须严格遵守 persona 的叙述身份、语气、禁忌事项
3. 必须优先遵循 framework 的开头方式、中段推进和结尾收束
4. 不要把“标题备选 / 摘要 / 导语 / 封面文案”混进正文
5. 如果素材不够，允许在不违背 persona 的前提下做合理补全，但不要编造明显失真的细节
6. 小标题要服务于结构推进，不要写成空洞提纲
7. 保持像真人写的，不要写成模板总结
8. 正文开头必须先写无标题引入段，至少 3-6 个自然段后再进入第一个小标题；开头不能直接抛观点
9. 正文中的第一个小标题不能直接引用文章标题，也不能只是标题的轻微改写
10. 正文出现他人时按“人物与案例命名规则”使用身份/关系/场景称呼，不要给案例人物编名字
{outline_requirements}

## 写作提醒

- 先用“场景/反常/悬念”把读者拉住，再按 framework 展开观点
- 最终文章标题是：{article_title}
- 赛道是 `{lane}`，不要跑题
- 这次主要目标是：{goals}
""".format(
        channel=brief["channel"],
        channel_display_name=brief.get("channel_display_name") or brief["channel"],
        lane=brief["lane"],
        topic=brief["topic"],
        article_title=article_title,
        goals=goals,
        material_types=material_types,
        material_depth=brief.get("material_depth") or "-",
        persona_id=persona["id"],
        persona_path=persona["path"],
        persona_content=persona["content"].strip(),
        framework_id=framework.get("id") or "-",
        framework_name=framework.get("name") or "-",
        framework_summary=framework.get("summary") or "-",
        hook_pattern=framework.get("hook_pattern") or "-",
        ending_pattern=framework.get("ending_pattern") or "-",
        required_materials=required_materials,
        section_flow=section_flow,
        constraints=constraints,
        content_guidance=content_guidance.rstrip(),
        character_naming_guidance=character_naming_guidance,
        opening_guidance=opening_guidance,
        outline_requirements=("\n" + outline_requirements) if outline_requirements else "",
        recommended_theme=recommended_theme,
        theme_candidates=theme_candidates,
    )


def save_writing_prompt(channel_id: str, topic: str, content: str) -> Path:
    output_path = output_base_path(channel_id, topic).with_suffix(".prompt.md")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)
    return output_path


def theme_output_path(channel_id: str, topic: str) -> Path:
    return output_base_path(channel_id, topic).with_suffix(".theme.yaml")


def theme_markdown_output_path(channel_id: str, topic: str) -> Path:
    return output_base_path(channel_id, topic).with_suffix(".theme.md")


def draft_output_path(channel_id: str, topic: str) -> Path:
    return output_base_path(channel_id, topic).with_suffix(".draft.md")


def generate_draft_with_codex(prompt_content: str, output_path: Path) -> Path:
    ensure_dir(output_path.parent)
    cmd = [
        "codex",
        "exec",
        "--skip-git-repo-check",
        "--sandbox",
        "workspace-write",
        "-C",
        str(FACTORY_ROOT),
        "-o",
        str(output_path),
        "-",
    ]
    subprocess.run(
        cmd,
        input=prompt_content,
        text=True,
        check=True,
    )
    return output_path


def build_local_partial_draft(brief: Dict, persona: Dict) -> str:
    framework = brief["framework"]
    title = brief.get("article_title") or brief["topic"]
    persona_id = persona["id"]
    lane = brief["lane"]
    outline_sections = (brief.get("outline") or {}).get("sections") or []
    sections = outline_sections or framework.get("section_flow") or []
    constraints = framework.get("constraints") or []
    character_naming_guidance = build_character_naming_guidance(lane)
    section_blocks = []
    for item in sections:
        if isinstance(item, dict):
            section_blocks.append(
                "## %s\n\n[核心观点：%s]\n\n[这里围绕这一节展开，保持 `%s` 人设口吻，补充真实场景、身份称呼、细节和过渡；不要给案例人物编名字。]\n"
                % (item.get("title"), item.get("core_viewpoint"), persona_id)
            )
        else:
            section_blocks.append(
                "## %s\n\n[这里按“%s”展开这一节，保持 `%s` 人设口吻，补充真实场景、身份称呼、细节和过渡；不要给案例人物编名字。]\n"
                % (item, item, persona_id)
            )
    constraints_block = "\n".join("- %s" % item for item in constraints) or "- 无"
    opening_guidance = build_opening_guidance(lane, framework)
    return """---
title: {title}
---

<!-- 正文开头先写无标题引入段，不要重复文章标题，也不要一上来就写第一个小标题。 -->

[开头先按框架要求起势：{hook_pattern}]

[这一段用 `{persona_id}` 的口吻，先写 3-6 个自然段的真实场景/反常细节/悬念，不要直接总结。第一个小标题必须等开头把读者拉住以后再出现，也不能直接引用文章标题。]

{character_naming_guidance}

{sections}

## 收尾

[这里按框架要求收尾：{ending_pattern}]

[最后用 `{persona_id}` 的自然语气收住，不要写成模板总结。]

---

> 本地补写模板说明
>
> - 这是一份本地可直接补写的半成稿模板
> - 选中框架后会始终生成，方便你立刻续写
> - 赛道：`{lane}`
> - 目标：`{goals}`
> - 素材形态：`{material_types}`
> - 注意约束：
{constraints}
""".format(
        title=title,
        hook_pattern=framework.get("hook_pattern") or "按框架开头方式切入",
        opening_guidance=opening_guidance,
        persona_id=persona_id,
        character_naming_guidance=character_naming_guidance,
        sections="\n".join(section_blocks),
        ending_pattern=framework.get("ending_pattern") or "按框架收尾",
        lane=lane,
        goals=", ".join(brief.get("goals") or []),
        material_types=", ".join(brief.get("material_types") or []),
        constraints=constraints_block,
    )


def recommend_themes_for_brief(
    brief: Dict,
    persona: Dict,
    framework: Dict,
    payload: Dict,
    draft_path: Path = None,
    top_k: int = 3,
) -> Dict:
    article_subtype = infer_article_subtype(framework, payload)
    features = infer_theme_features(brief, draft_path=draft_path)
    candidates = rt.recommend_themes(
        lane=brief.get("lane"),
        persona=persona.get("id"),
        article_subtype=article_subtype,
        goals=brief.get("goals") or [],
        features=features,
        top_k=top_k,
    )
    serialized_candidates = []
    for item in candidates:
        manifest = item.theme.get("manifest") or {}
        serialized_candidates.append(
            {
                "theme_id": item.theme_name,
                "display_name": manifest.get("display_name") or item.theme_name,
                "score": item.score,
                "summary": manifest.get("description") or "",
                "reasons": item.reasons,
                "risks": item.risks,
            }
        )
    return {
        "recommended_theme": serialized_candidates[0]["theme_id"] if serialized_candidates else None,
        "article_subtype": article_subtype,
        "features": features,
        "candidates": serialized_candidates,
        "recommended_from": str(draft_path) if draft_path else "brief",
    }


def save_theme_recommendation(channel_id: str, topic: str, data: Dict) -> Path:
    output_path = theme_output_path(channel_id, topic)
    with open(output_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
    return output_path


def build_theme_recommendation_markdown(data: Dict) -> str:
    lines = [
        "# 排版主题推荐",
        "",
        f"- recommended_theme: `{data.get('recommended_theme') or '-'}`",
        f"- article_subtype: `{data.get('article_subtype') or '-'}`",
        f"- features: `{data.get('features') or {}}`",
        f"- based_on: `{data.get('recommended_from') or 'brief'}`",
        "",
    ]
    for index, item in enumerate(data.get("candidates") or [], start=1):
        lines.extend(
            [
                f"{index}. {item.get('display_name')}",
                f"   - id: `{item.get('theme_id')}`",
                f"   - score: {item.get('score')}",
                f"   - summary: {item.get('summary') or '-'}",
                f"   - 推荐原因: {'；'.join(item.get('reasons') or []) or '-'}",
                f"   - 风险提示: {'；'.join(item.get('risks') or []) or '-'}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def save_theme_recommendation_markdown(channel_id: str, topic: str, content: str) -> Path:
    output_path = theme_markdown_output_path(channel_id, topic)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)
    return output_path


def save_local_partial_draft(channel_id: str, topic: str, content: str) -> Path:
    output_path = output_base_path(channel_id, topic).with_suffix(".draft.template.md")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)
    return output_path


def infer_draft_subtype(material_types: List[str]) -> str:
    if "story" in material_types:
        return "story_exploration"
    if "problem" in material_types:
        return "problem_exploration"
    if "case" in material_types:
        return "case_exploration"
    if "list" in material_types:
        return "list_exploration"
    return "opinion_exploration"


def infer_section_flow(material_types: List[str]) -> List[str]:
    if "story" in material_types:
        return ["反常起点", "冲突升级", "真相暴露", "实在提醒"]
    if "problem" in material_types:
        return ["问题定义", "旧做法成本", "关键解法", "可复用动作"]
    if "case" in material_types:
        return ["案例背景", "关键转折", "抽象方法", "复用边界"]
    if "list" in material_types:
        return ["总起判断", "并列展开", "重点提醒", "结尾收束"]
    return ["开头判断", "案例支撑", "核心观点", "行动建议"]


def extract_keywords(topic: str, limit: int = 8) -> List[str]:
    cleaned = topic.split("\n补充素材：", 1)[0]
    tokens = rf.tokenize(cleaned)
    unique = []
    for token in tokens:
        if len(token) <= 1:
            continue
        if token not in unique:
            unique.append(token)
        if len(unique) >= limit:
            break
    return unique


def generate_framework_draft(channel_id: str, lane: str, payload: Dict) -> Path:
    ensure_dir(FRAMEWORK_DRAFTS_ROOT / lane)
    slug = slugify(payload["topic"].split("\n补充素材：", 1)[0])
    date_str = datetime.now().strftime("%Y%m%d")
    path = FRAMEWORK_DRAFTS_ROOT / lane / ("%s_%s.yaml" % (date_str, slug))
    framework_id = "draft_%s_%s" % (lane, slug)
    material_types = payload["material_types"] or ["opinion"]
    draft = {
        "id": framework_id,
        "name": "待验证新框架草案",
        "lane": lane,
        "subtype": infer_draft_subtype(material_types),
        "priority": 50,
        "summary": "基于选题《%s》自动生成的新框架草案，待人工验证。" % payload["topic"].split("\n补充素材：", 1)[0],
        "suitable_topics": [payload["topic"].split("\n补充素材：", 1)[0]],
        "suitable_goals": payload["goals"] or ["click"],
        "material_types": material_types,
        "material_depth": {"min": payload["material_depth"]},
        "keywords": extract_keywords(payload["topic"]),
        "required_materials": [
            "至少一个真实场景或案例",
            "一个明确转折点",
            "一条可收束的核心判断",
        ],
        "hook_pattern": "从这次选题里最反常的一点切入，再抛出反问。",
        "section_flow": infer_section_flow(material_types),
        "ending_pattern": "收束成一句可执行提醒，再留一个可复用判断。",
        "constraints": [
            "先验证 3-5 次，再决定是否升级成正式框架",
            "不要直接照抄来源爆文的标题和案例表达",
        ],
        "not_for": [
            "与当前素材形态完全不匹配的选题",
        ],
        "source": {
            "channel": channel_id,
            "topic": payload["topic"],
            "generated_at": datetime.now().isoformat(),
        },
    }
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(draft, f, allow_unicode=True, sort_keys=False)
    return path


def print_selection_result(
    selected,
    brief_path: Path,
    prompt_path: Path,
    template_path: Path,
    theme_path: Path,
    theme_markdown_path: Path,
    theme_recommendation: Dict,
    outline_prompt_path: Path = None,
    outline_file_path: Path = None,
    draft_path: Path = None,
    render_result: Dict = None,
) -> None:
    data = selected.data
    print("# 已选框架\n")
    print("- name: %s" % data.get("name"))
    print("- id: `%s`" % data.get("id"))
    print("- summary: %s" % (data.get("summary") or "-"))
    print("- hook: %s" % (data.get("hook_pattern") or "-"))
    print("- ending: %s" % (data.get("ending_pattern") or "-"))
    print("- brief: `%s`" % brief_path)
    if prompt_path:
        print("- prompt: `%s`" % prompt_path)
    if outline_prompt_path:
        print("- outline_prompt: `%s`" % outline_prompt_path)
    if outline_file_path:
        print("- outline: `%s`" % outline_file_path)
    print("- template: `%s`" % template_path)
    print("- theme: `%s`" % theme_path)
    print("- theme_note: `%s`" % theme_markdown_path)
    if draft_path:
        print("- draft: `%s`" % draft_path)
    if render_result:
        print("- article: `%s`" % render_result["html_path"])
    print("")
    brief_data = {}
    try:
        with open(brief_path, "r", encoding="utf-8") as f:
            brief_data = yaml.safe_load(f) or {}
    except Exception:
        brief_data = {}
    recall_meta = ((brief_data.get("outline") or {}).get("section_materials_recall") or {})
    if recall_meta:
        print("## 分节素材召回")
        print("- status: `%s`" % (recall_meta.get("status") or "unknown"))
        print(
            "- sections_with_materials: %s/%s"
            % (recall_meta.get("sections_with_materials", 0), recall_meta.get("sections_total", 0))
        )
        print("- materials_total: %s" % recall_meta.get("materials_total", 0))
        if recall_meta.get("reason"):
            print("- reason: %s" % recall_meta.get("reason"))
        if recall_meta.get("status") in {"skipped", "attempted_empty"}:
            print("- warning: 本次正文将缺少素材库支撑，请优先使用 persona 真实经历，不要编造来源或假案例")
        print("")
    print("## 写作抓手")
    for item in data.get("section_flow") or []:
        print("- %s" % item)
    print("")
    print("## 注意")
    for item in data.get("constraints") or []:
        print("- %s" % item)
    print("")
    print("## 排版建议")
    recommended_theme = theme_recommendation.get("recommended_theme")
    if recommended_theme:
        print("- recommended_theme: `%s`" % recommended_theme)
    for item in (theme_recommendation.get("candidates") or [])[:3]:
        print(
            "- %s (`%s`)：%s"
            % (
                item.get("display_name"),
                item.get("theme_id"),
                "；".join(item.get("reasons") or []) or item.get("summary") or "-",
            )
        )
    print("")
    if render_result:
        print(
            "下一步：article.html 已生成，可继续出封面并发布；当前主题 `%s`。"
            % render_result["decision"]["theme_name"]
        )
    elif outline_prompt_path and not prompt_path:
        print("下一步：用当前 AI CLI 读取 outline_prompt 生成 outline.yaml，再通过 `--outline-file` 回传给脚本。")
    elif draft_path:
        print("下一步：draft 已生成，可以直接进入润色 / 发布包装。")
    elif prompt_path and outline_file_path:
        print("下一步：分节素材已注入 prompt，可直接写稿；如需自动 draft，可带同一个 `--outline-file` 追加 `--generate-draft` 重跑。")
    elif prompt_path:
        print("下一步：这是旧的整体素材召回 prompt，只建议用于快速降级；正式写稿请先生成 outline 并通过 `--outline-file` 回传。")
    else:
        print(
            "下一步：直接在本地模板上补写；正文定稿后可传 `--final-md` 自动生成 article.html。"
        )


def print_title_prompt_result(selected, title_prompt_path: Path) -> None:
    data = selected.data
    print("# 已选框架，等待标题选择\n")
    print("- name: %s" % data.get("name"))
    print("- id: `%s`" % data.get("id"))
    print("- summary: %s" % (data.get("summary") or "-"))
    print("- title_prompt: `%s`" % title_prompt_path)
    print("")
    print("## 下一步")
    print("1. 当前 AI CLI 读取 title_prompt，按爆文标题样式生成 3 条标题和置信度评分。")
    print("2. 让用户回复 `1/2/3` 选择；不满意就按用户建议重出 3 条，或接受用户自填标题。")
    print("3. 标题确定后，重新运行本命令并追加 `--title \"最终标题\"`；脚本会默认进入大纲准备。")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="推荐框架并处理编号式后续动作")
    parser.add_argument("--channel", required=True, help="频道标识，如 tech / emotion")
    parser.add_argument("--topic", required=True, help="本次文章选题")
    parser.add_argument("--title", default=None, help="用户最终确认的文章标题；准备大纲/正文前必填")
    parser.add_argument("--goal", action="append", default=[], help="传播目标，可重复传入")
    parser.add_argument("--material-type", action="append", default=[], help="素材形态，可重复传入")
    parser.add_argument(
        "--material-depth",
        default="medium",
        choices=["light", "medium", "heavy"],
        help="素材完整度，默认 medium",
    )
    parser.add_argument("--top-k", type=int, default=3, help="默认返回 3 个候选")
    parser.add_argument("--code", default=None, help="输入编号：1/2/3/8/9/10/11/12")
    parser.add_argument("--extra-materials", default=None, help="补充素材，配合编号 11 使用")
    parser.add_argument("--prepare-outline", action="store_true", help="选中编号后，只生成 outline.prompt.md，不调用 LLM")
    parser.add_argument("--outline-file", default=None, help="已由当前 AI CLI 生成的 outline.yaml；传入后按节召回素材并生成新版 prompt")
    parser.add_argument("--generate-draft", action="store_true", help="选中编号后，直接调用本地 codex 生成 draft.md")
    parser.add_argument("--final-md", default=None, help="正文终稿路径；若提供，将按推荐主题自动生成 article.html")
    parser.add_argument("--article-html", default=None, help="article.html 输出路径，默认与 final.md 同目录")
    parser.add_argument("--no-materials", action="store_true", help="跳过素材库自动召回，brief 中 auto_materials 为空")
    parser.add_argument(
        "--legacy-brief-materials",
        action="store_true",
        help="兼容旧流程：标题确认后不走 outline，直接用整体素材召回生成写作 prompt（不推荐）",
    )
    parser.add_argument("--debug-material-queries", action="store_true", help="打印素材召回 query、angle 和候选统计")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.prepare_outline and args.generate_draft and not args.outline_file:
        raise ValueError("--prepare-outline 只准备大纲指令包；如需生成正文，请先传入 --outline-file")
    if args.generate_draft and not args.outline_file:
        raise ValueError("--generate-draft 必须配合 --outline-file 使用，避免绕过分节素材召回直接写稿。")
    if args.legacy_brief_materials and (args.prepare_outline or args.outline_file):
        raise ValueError("--legacy-brief-materials 是旧的整体召回降级路径，不能和 --prepare-outline/--outline-file 混用。")
    if args.outline_file and args.no_materials:
        raise ValueError(
            "--outline-file 回传阶段默认必须执行分节素材召回；不要同时传 --no-materials。"
            "如果确实要跳过素材库，请先确认这是有意为之，再移除 --outline-file 或改用人工补充素材。"
        )
    payload = normalize_inputs(args)

    if args.code in {"8", "9", "10", "11"}:
        payload = reroute_by_code(args.code, payload)
        lane, candidates = rf.recommend(
            channel_id=args.channel,
            topic=payload["topic"],
            goals=payload["goals"],
            material_types=payload["material_types"],
            material_depth=payload["material_depth"],
            top_k=args.top_k,
        )
        rf.print_result(
            channel_id=args.channel,
            lane=lane,
            topic=payload["topic"],
            goals=payload["goals"],
            material_types=payload["material_types"],
            material_depth=payload["material_depth"],
            candidates=candidates,
        )
        return

    if args.code == "12":
        channel, lane = get_channel_context(args.channel)
        draft_path = generate_framework_draft(args.channel, lane, payload)
        print("# 新框架草案已生成\n")
        print("- lane: `%s`" % lane)
        print("- file: `%s`" % draft_path)
        print("- next: 先人工补齐字段，再验证 3-5 次")
        return

    lane, candidates = rf.recommend(
        channel_id=args.channel,
        topic=payload["topic"],
        goals=payload["goals"],
        material_types=payload["material_types"],
        material_depth=payload["material_depth"],
        top_k=args.top_k,
    )

    if args.code and args.code.isdigit() and args.code in {"1", "2", "3", "4", "5"}:
        index = int(args.code) - 1
        if index < 0 or index >= len(candidates):
            raise IndexError("编号 %s 超出当前候选范围" % args.code)
        selected = candidates[index]
        channel, _ = get_channel_context(args.channel)
        persona = get_persona_info(args.channel, channel)
        if not payload.get("article_title"):
            if args.prepare_outline or args.outline_file or args.generate_draft or args.final_md:
                raise ValueError("请先完成标题选择，并通过 --title 传入最终标题。")
            title_prompt_path = save_title_prompt(
                args.channel,
                payload["topic"],
                build_title_generation_prompt(
                    channel_id=args.channel,
                    lane=lane,
                    persona=persona,
                    selected=selected,
                    payload=payload,
                ),
            )
            print_title_prompt_result(selected, title_prompt_path)
            return
        if (
            not args.prepare_outline
            and not args.outline_file
            and not args.final_md
            and not args.legacy_brief_materials
        ):
            args.prepare_outline = True
        brief_payload = dict(payload)
        if args.prepare_outline or args.outline_file:
            brief_payload["no_materials"] = True
        brief = build_writing_brief(args.channel, channel, lane, persona, selected, brief_payload)
        outline_file_path = None
        if args.outline_file:
            outline_file_path = Path(args.outline_file)
            outline = load_outline_file(outline_file_path, lane=brief.get("lane") or "")
            if not payload.get("no_materials"):
                outline = fetch_materials_for_outline_sections(
                    outline=outline,
                    topic=brief["topic"],
                    lane=lane,
                    material_types=payload.get("material_types") or [],
                    max_per_source=2,
                    limit_per_section=1 if lane == "tech" else 2,
                    debug=bool(payload.get("debug_material_queries")),
                )
            else:
                outline["section_materials_recall"] = build_section_materials_recall_meta(
                    outline,
                    status="skipped",
                    reason="--no-materials",
                )
            if "section_materials_recall" not in outline:
                outline["section_materials_recall"] = build_section_materials_recall_meta(outline, status="unknown")
            brief["outline"] = outline
        theme_recommendation = recommend_themes_for_brief(
            brief=brief,
            persona=persona,
            framework=selected.data,
            payload=payload,
        )
        brief["theme_recommendation"] = theme_recommendation
        brief_path = save_brief(args.channel, payload["topic"], brief)
        outline_prompt_path = None
        if args.prepare_outline:
            outline_prompt_path = save_outline_prompt(
                args.channel,
                payload["topic"],
                build_outline_prompt(brief, persona),
            )
        prompt_content = ""
        prompt_path = None
        if not args.prepare_outline or args.outline_file:
            prompt_content = build_writing_prompt(brief, persona)
            prompt_path = save_writing_prompt(
                args.channel,
                payload["topic"],
                prompt_content,
            )
        template_path = save_local_partial_draft(
            args.channel,
            payload["topic"],
            build_local_partial_draft(brief, persona),
        )
        draft_path = None
        if args.generate_draft:
            draft_path = generate_draft_with_codex(
                prompt_content=prompt_content,
                output_path=draft_output_path(args.channel, payload["topic"]),
            )
            theme_recommendation = recommend_themes_for_brief(
                brief=brief,
                persona=persona,
                framework=selected.data,
                payload=payload,
                draft_path=draft_path,
            )
            brief["theme_recommendation"] = theme_recommendation
            brief_path = save_brief(args.channel, payload["topic"], brief)
            prompt_content = build_writing_prompt(brief, persona)
            prompt_path = save_writing_prompt(
                args.channel,
                payload["topic"],
                prompt_content,
            )
        theme_path = save_theme_recommendation(args.channel, payload["topic"], theme_recommendation)
        theme_markdown_path = save_theme_recommendation_markdown(
            args.channel,
            payload["topic"],
            build_theme_recommendation_markdown(theme_recommendation),
        )
        render_result = None
        if args.final_md:
            final_md_path = Path(args.final_md)
            if not final_md_path.exists():
                raise FileNotFoundError("未找到 final.md: %s" % final_md_path)
            render_result = rwrt.render_with_recommended_theme(
                input_path=final_md_path,
                output_path=args.article_html,
                theme_file=theme_path,
                channel=args.channel,
                article_subtype=theme_recommendation.get("article_subtype"),
                goals=brief.get("goals") or [],
            )
        print_selection_result(
            selected,
            brief_path,
            prompt_path,
            template_path,
            theme_path,
            theme_markdown_path,
            theme_recommendation,
            outline_prompt_path=outline_prompt_path,
            outline_file_path=outline_file_path,
            draft_path=draft_path,
            render_result=render_result,
        )
        return

    rf.print_result(
        channel_id=args.channel,
        lane=lane,
        topic=payload["topic"],
        goals=payload["goals"],
        material_types=payload["material_types"],
        material_depth=payload["material_depth"],
        candidates=candidates,
    )


if __name__ == "__main__":
    main()

"""Beginner-facing presets: one-click optimization scenarios.

Each preset hides SkillOpt's professional hyper-parameters behind a sensible
default while still mapping onto the exact same config keys the Pro mode edits,
so nothing is lost — a beginner picks a goal, a pro can later open the same run
and tweak everything.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class Preset:
    id: str
    title: str                  # short, human title (zh)
    desc: str                   # one-line description (zh)
    title_en: str = ""          # short title (en)
    desc_en: str = ""           # one-line description (en)
    env: str = ""               # SkillOpt benchmark / env name
    config_path: str = ""       # config file relative to the SkillOpt repo
    overrides: dict = field(default_factory=dict)
    recommended_backend: str = "openai_chat"
    kind: str = "train"         # "train" | "sleep"

    def to_dict(self) -> dict:
        return asdict(self)


PRESETS: list[Preset] = [
    Preset(
        id="docvqa_quickstart",
        title="优化文档问答技能",
        desc="针对扫描件/文档图问答（DocVQA）训练一份技能，小样本快速体验。",
        title_en="Optimize document-QA skill",
        desc_en="Train a skill for scanned/document image QA (DocVQA) with a quick small-sample run.",
        env="docvqa",
        config_path="configs/docvqa/default.yaml",
        overrides={"train.num_epochs": 2, "train.batch_size": 16},
    ),
    Preset(
        id="searchqa_quickstart",
        title="优化检索问答技能",
        desc="让模型更会用检索结果作答（SearchQA / SQuAD 风格）。",
        title_en="Optimize retrieval-QA skill",
        desc_en="Teach the model to answer better from retrieved results (SearchQA / SQuAD style).",
        env="searchqa",
        config_path="configs/searchqa/default.yaml",
        overrides={"train.num_epochs": 2},
    ),
    Preset(
        id="spreadsheet_quickstart",
        title="优化表格处理技能",
        desc="提升电子表格类任务能力（SpreadsheetBench）。",
        title_en="Optimize spreadsheet skill",
        desc_en="Improve spreadsheet-style task performance (SpreadsheetBench).",
        env="spreadsheetbench",
        config_path="configs/spreadsheetbench/default.yaml",
        overrides={"train.num_epochs": 2},
    ),
    Preset(
        id="officeqa_quickstart",
        title="优化办公文档技能",
        desc="提升 Office 文档问答与处理能力（OfficeQA）。",
        title_en="Optimize office-document skill",
        desc_en="Improve Office document QA and processing (OfficeQA).",
        env="officeqa",
        config_path="configs/officeqa/default.yaml",
        overrides={"train.num_epochs": 2},
    ),
    Preset(
        id="livemath_quickstart",
        title="优化数学解题技能",
        desc="提升数学推理与解题能力（LiveMathematicianBench）。",
        title_en="Optimize math-solving skill",
        desc_en="Improve mathematical reasoning and problem solving (LiveMathematicianBench).",
        env="livemathematicianbench",
        config_path="configs/livemathematicianbench/default.yaml",
        overrides={"train.num_epochs": 2},
    ),
    Preset(
        id="sleep_local_agent",
        title="进化我本地的编码助手",
        desc="夜间回顾你的 Claude Code / Codex 历史，自动巩固出更好的技能（SkillOpt-Sleep）。",
        title_en="Evolve my local coding assistant",
        desc_en="Review your Claude Code / Codex history at night and consolidate better skills (SkillOpt-Sleep).",
        env="",
        config_path="",
        overrides={},
        recommended_backend="mock",
        kind="sleep",
    ),
]


class PresetCatalog:
    def list(self) -> list[Preset]:
        return list(PRESETS)

    def get(self, preset_id: str) -> Preset | None:
        return next((p for p in PRESETS if p.id == preset_id), None)

"""
Frost OS Module 02 — Mission Classifier.

Provides deterministic, rule-based classification of mission descriptions
and metadata into strongly-typed MissionType and suggested PriorityLevel.
"""

from __future__ import annotations

import re
from typing import Any
from pydantic import BaseModel, Field

from app.models.mission import MissionType
from app.models.priority import PriorityLevel


class ClassificationResult(BaseModel):
    """Structured, validated classification outcome."""
    mission_type: MissionType
    suggested_priority: PriorityLevel
    confidence: float = Field(..., ge=0.0, le=1.0)
    matched_keywords: list[str] = Field(default_factory=list)
    reasoning: str


# Keyword dictionary for deterministic polar station workload classification
CLASSIFICATION_RULES: list[dict[str, Any]] = [
    {
        "type": MissionType.LIFE_SUPPORT,
        "priority": PriorityLevel.P0,
        "keywords": [
            "life support", "oxygen", "o2 generation", "air scrub", "co2 scrubber",
            "potable water", "water recycling", "atmospheric pressure", "air recirculation",
            "environmental control", "ecls",
        ],
    },
    {
        "type": MissionType.HEATING,
        "priority": PriorityLevel.P0,
        "keywords": [
            "habitat heating", "emergency heat", "freeze prevention", "pipe freeze",
            "thermal loop", "cabin temp", "insulation heat", "defrost habitat",
        ],
    },
    {
        "type": MissionType.MEDICAL,
        "priority": PriorityLevel.P0,
        "keywords": [
            "medical", "infirmary", "surgical", "icu", "patient monitor", "autoclave",
            "defibrillator", "cryo storage medical", "pharmacy cooler",
        ],
    },
    {
        "type": MissionType.WEATHER_MONITORING,
        "priority": PriorityLevel.P1,
        "keywords": [
            "weather", "blizzard radar", "anemometer", "meteorolog", "radiosonde",
            "atmospheric sounding", "storm track", "barometric", "lidar weather",
        ],
    },
    {
        "type": MissionType.COMMUNICATION,
        "priority": PriorityLevel.P1,
        "keywords": [
            "satellite uplink", "satcom", "comms array", "emergency beacon", "vhf radio",
            "deep space comm", "high-frequency radio", "telemetry link",
        ],
    },
    {
        "type": MissionType.RESEARCH,
        "priority": PriorityLevel.P1,
        "keywords": [
            "ice core", "spectrometer", "telescope", "cosmic ray", "magnetometer",
            "seismic array", "aurora", "polar science", "geological sample",
        ],
    },
    {
        "type": MissionType.LABORATORY,
        "priority": PriorityLevel.P2,
        "keywords": [
            "laboratory", "centrifuge", "microscope", "chromatograph", "fume hood",
            "incubator", "bio-analyzer", "chemical reagent",
        ],
    },
    {
        "type": MissionType.MAINTENANCE,
        "priority": PriorityLevel.P2,
        "keywords": [
            "battery conditioning", "turbine deicing", "generator service",
            "pump maintenance", "diagnostic scan", "calibration routine",
        ],
    },
    {
        "type": MissionType.OPERATIONS,
        "priority": PriorityLevel.P2,
        "keywords": [
            "airlock cycling", "vehicle charging", "snow blower", "hangar door",
            "waste management", "cargo crane", "rover recharge",
        ],
    },
    {
        "type": MissionType.COMPUTING,
        "priority": PriorityLevel.P3,
        "keywords": [
            "climate model", "compute job", "simulation", "data processing",
            "batch analysis", "neural network", "archival sync", "rendering",
        ],
    },
    {
        "type": MissionType.OFFICE,
        "priority": PriorityLevel.P3,
        "keywords": [
            "workstation", "office lighting", "desktop pc", "document printing",
            "admin network", "briefing room",
        ],
    },
    {
        "type": MissionType.RECREATION,
        "priority": PriorityLevel.P4,
        "keywords": [
            "gym", "recreation", "treadmill", "media room", "entertainment",
            "crew lounge", "coffee station", "personal electronics",
        ],
    },
]


class MissionClassifier:
    """Deterministic classifier matching workload descriptions to types and priorities."""

    def classify(self, text: str, default_type: MissionType | None = None) -> ClassificationResult:
        """Classify a text description or mission name."""
        clean_text = text.lower()
        best_match = None
        highest_score = 0
        matched_words = []

        for rule in CLASSIFICATION_RULES:
            matches = [kw for kw in rule["keywords"] if re.search(r"\b" + re.escape(kw) + r"\b", clean_text)]
            if matches:
                # Score based on number and specificity of matches
                score = len(matches) * 10
                if score > highest_score:
                    highest_score = score
                    best_match = rule
                    matched_words = matches

        if best_match and highest_score > 0:
            confidence = min(0.95, 0.65 + (0.10 * len(matched_words)))
            return ClassificationResult(
                mission_type=best_match["type"],
                suggested_priority=best_match["priority"],
                confidence=confidence,
                matched_keywords=matched_words,
                reasoning=f"Matched keywords: {', '.join(matched_words)} -> {best_match['type'].value} ({best_match['priority'].value})",
            )

        # Fallback to default or generic research
        fallback_type = default_type or MissionType.RESEARCH
        return ClassificationResult(
            mission_type=fallback_type,
            suggested_priority=PriorityLevel.P2,
            confidence=0.40,
            matched_keywords=[],
            reasoning="No domain keywords matched. Assigned default research classification.",
        )

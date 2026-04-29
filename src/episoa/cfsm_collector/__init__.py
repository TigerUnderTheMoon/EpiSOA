"""Spec-facing C-FSM collector package.

This package is a compatibility facade over ``episoa.collector``.
"""

from episoa.collector.coverage_evaluation import coverage_evaluation
from episoa.collector.event_understanding import event_understanding
from episoa.collector.fsm_graph import build_collector_graph, collector_graph
from episoa.collector.opinion_collection import browser_based_opinion_collection
from episoa.collector.page_collection import search_and_page_collection
from episoa.collector.query_planning import query_planning
from episoa.collector.source_selection import source_selection

__all__ = [
    "browser_based_opinion_collection",
    "build_collector_graph",
    "collector_graph",
    "coverage_evaluation",
    "event_understanding",
    "query_planning",
    "search_and_page_collection",
    "source_selection",
]

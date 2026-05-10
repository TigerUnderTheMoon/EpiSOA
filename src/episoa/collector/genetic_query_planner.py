"""Coverage-aware genetic query planner for formal evidence collection."""

from __future__ import annotations

from dataclasses import dataclass
import random
from typing import Any

from episoa.collector.query_planner import (
    anchor_entity_terms,
    as_list,
    event_query_seeds,
    normalize_source_scope,
    query_plan_from_queries,
    unique,
)


DEFAULT_WEIGHTS = {
    "relevance": 0.30,
    "entity_coverage": 0.25,
    "source_coverage": 0.15,
    "traceability": 0.10,
    "stakeholder_coverage": 0.08,
    "stance_diversity": 0.05,
    "redundancy_penalty": 0.05,
    "cost_penalty": 0.02,
}


@dataclass(frozen=True)
class GeneticPlannerConfig:
    enabled: bool = False
    population_size: int = 12
    generations: int = 2
    individual_size: int = 6
    tournament_size: int = 3
    mutation_rate: float = 0.25
    probe_max_results_per_query: int = 3
    random_seed: int = 42
    weights: dict[str, float] | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "GeneticPlannerConfig":
        raw = dict(raw or {})
        weights = dict(DEFAULT_WEIGHTS)
        weights.update(dict(raw.get("weights") or {}))
        return cls(
            enabled=bool(raw.get("enabled", False)),
            population_size=max(1, int(raw.get("population_size", 12))),
            generations=max(0, int(raw.get("generations", 2))),
            individual_size=max(1, int(raw.get("individual_size", 6))),
            tournament_size=max(1, int(raw.get("tournament_size", 3))),
            mutation_rate=float(raw.get("mutation_rate", 0.25)),
            probe_max_results_per_query=max(1, int(raw.get("probe_max_results_per_query", 3))),
            random_seed=int(raw.get("random_seed", 42)),
            weights=weights,
        )


class ProbeCache:
    def __init__(self) -> None:
        self._cache: dict[tuple[str, str, str, int], list[dict[str, Any]]] = {}
        self.hits = 0
        self.misses = 0

    def get(self, client: Any, *, query: str, source_type: str, time_window: Any, max_results: int) -> list[dict[str, Any]]:
        key = (query, source_type, _time_window_key(time_window), max_results)
        if key in self._cache:
            self.hits += 1
            return self._cache[key]
        self.misses += 1
        response = client.search_with_debug(
            query=query,
            max_results=max_results,
            source_type=source_type,
            time_window=time_window,
        )
        self._cache[key] = list(response.get("results") or [])
        return self._cache[key]

    def stats(self) -> dict[str, int]:
        return {"hits": self.hits, "misses": self.misses, "entries": len(self._cache)}


def build_candidate_query_pool(event: dict[str, Any]) -> list[str]:
    seeds = event_query_seeds(event)
    event_name = str(event.get("event_name") or "").strip()
    trigger = str(event.get("trigger") or "").strip()
    anchors = anchor_entity_terms(event)
    stakeholders = as_list(event.get("stakeholder_hints"))
    stances = as_list(event.get("stance_hints"))

    candidates: list[str] = []
    candidates.extend(seeds)
    candidates.extend([event_name, trigger])
    for query in seeds:
        candidates.extend([f"{query} {anchor}" for anchor in anchors])
    for anchor in anchors:
        candidates.extend([f"{event_name} {anchor}", f"{trigger} {anchor}"])
    for query in seeds:
        candidates.extend([f"{query} {stakeholder}" for stakeholder in stakeholders])
        candidates.extend([f"{query} {stance}" for stance in stances])
        candidates.extend([f"{query} {stakeholder} {stance}" for stakeholder in stakeholders for stance in stances])
    return unique([item.strip() for item in candidates if item and item.strip()])


def plan_event_queries_ga(
    event: dict[str, Any],
    *,
    client: Any,
    default_sources: list[str] | None,
    config: GeneticPlannerConfig,
    cache: ProbeCache | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    source_scope = normalize_source_scope(event.get("source_scope"), default_sources=default_sources)
    candidate_pool = build_candidate_query_pool(event)
    if not candidate_pool:
        candidate_pool = [str(event.get("event_name") or event.get("event_id") or "").strip()]
    cache = cache or ProbeCache()
    rng = random.Random(config.random_seed + _event_seed(event))
    individual_size = min(config.individual_size, len(candidate_pool))
    population = _initial_population(candidate_pool, config.population_size, individual_size, rng)

    best_individual: list[str] = population[0]
    best_score = float("-inf")
    best_breakdown: dict[str, float] = {}

    for _ in range(config.generations + 1):
        scored = [
            (individual, *fitness_for_individual(event, individual, source_scope, client, config, cache))
            for individual in population
        ]
        scored.sort(key=lambda item: (item[1], item[0]), reverse=True)
        if scored[0][1] > best_score:
            best_individual = list(scored[0][0])
            best_score = float(scored[0][1])
            best_breakdown = dict(scored[0][2])
        population = _next_generation(scored, candidate_pool, config, individual_size, rng)

    plan = query_plan_from_queries(
        event=event,
        queries=best_individual,
        source_scope=source_scope,
        generated_by="coverage_aware_ga_query_planning",
        seed_keywords=event_query_seeds(event),
    )
    stakeholders = as_list(event.get("stakeholder_hints"))
    stances = as_list(event.get("stance_hints"))
    warnings = []
    if not stakeholders:
        warnings.append("stakeholder_hints absent; stakeholder_coverage omitted from GA fitness")
    if not stances:
        warnings.append("stance_hints absent; stance_diversity omitted from GA fitness")
    debug = {
        "event_id": event.get("event_id"),
        "planner_mode": "ga",
        "candidate_pool_size": len(candidate_pool),
        "selected_queries": best_individual,
        "population_size": config.population_size,
        "generations": config.generations,
        "best_fitness": best_score,
        "best_fitness_breakdown": best_breakdown,
        "optional_components_used": {
            "stakeholder_coverage": bool(stakeholders),
            "stance_diversity": bool(stances),
            "temporal_stage_coverage": False,
        },
        "temporal_stage_coverage_mode": "not_used_in_ga_fitness",
        "cache_stats": cache.stats(),
        "notes": warnings,
    }
    return plan, debug


def fitness_for_individual(
    event: dict[str, Any],
    queries: list[str],
    source_scope: list[str],
    client: Any,
    config: GeneticPlannerConfig,
    cache: ProbeCache,
) -> tuple[float, dict[str, float]]:
    results_by_query: dict[str, list[dict[str, Any]]] = {}
    covered_source_types: set[str] = set()
    all_results: list[dict[str, Any]] = []
    for query in queries:
        query_results: list[dict[str, Any]] = []
        for source_type in source_scope:
            source_results = cache.get(
                client,
                query=query,
                source_type=source_type,
                time_window=event.get("time_window"),
                max_results=config.probe_max_results_per_query,
            )
            usable_results = [result for result in source_results if _result_text(result).strip() or result.get("url")]
            if usable_results:
                covered_source_types.add(source_type)
            query_results.extend(source_results)
        results_by_query[query] = query_results
        all_results.extend(query_results)

    anchors = anchor_entity_terms(event)
    stakeholders = as_list(event.get("stakeholder_hints"))
    stances = as_list(event.get("stance_hints"))
    relevance_terms = unique(
        as_list(event.get("event_name"))
        + as_list(event.get("trigger"))
        + event_query_seeds(event)
        + anchors
    )
    breakdown = {
        "relevance": _result_overlap_rate(all_results, relevance_terms),
        "entity_coverage": _covered_terms_rate(all_results, anchors),
        "source_coverage": _covered_sources_rate(covered_source_types, source_scope),
        "traceability": _traceability(all_results),
        "stakeholder_coverage": _covered_terms_rate(all_results, stakeholders) if stakeholders else 0.0,
        "stance_diversity": _covered_terms_rate(all_results, stances) if stances else 0.0,
        "redundancy_penalty": _redundancy_penalty(all_results),
        "cost_penalty": len(set(queries)) / max(1, config.individual_size),
    }
    weights = _active_weights(config.weights or DEFAULT_WEIGHTS, stakeholders=stakeholders, stances=stances)
    score = (
        weights.get("relevance", 0.0) * breakdown["relevance"]
        + weights.get("entity_coverage", 0.0) * breakdown["entity_coverage"]
        + weights.get("source_coverage", 0.0) * breakdown["source_coverage"]
        + weights.get("traceability", 0.0) * breakdown["traceability"]
        + weights.get("stakeholder_coverage", 0.0) * breakdown["stakeholder_coverage"]
        + weights.get("stance_diversity", 0.0) * breakdown["stance_diversity"]
        - weights.get("redundancy_penalty", 0.0) * breakdown["redundancy_penalty"]
        - weights.get("cost_penalty", 0.0) * breakdown["cost_penalty"]
    )
    breakdown["score"] = score
    return score, breakdown


def _initial_population(pool: list[str], population_size: int, individual_size: int, rng: random.Random) -> list[list[str]]:
    population = [pool[:individual_size]]
    while len(population) < population_size:
        population.append(rng.sample(pool, individual_size))
    return population


def _next_generation(
    scored: list[tuple[list[str], float, dict[str, float]]],
    pool: list[str],
    config: GeneticPlannerConfig,
    individual_size: int,
    rng: random.Random,
) -> list[list[str]]:
    next_population = [list(scored[0][0])]
    while len(next_population) < config.population_size:
        parent_a = _tournament(scored, config.tournament_size, rng)
        parent_b = _tournament(scored, config.tournament_size, rng)
        child = _crossover(parent_a, parent_b, individual_size)
        child = _mutate(child, pool, individual_size, config.mutation_rate, rng)
        next_population.append(child)
    return next_population


def _tournament(scored: list[tuple[list[str], float, dict[str, float]]], size: int, rng: random.Random) -> list[str]:
    contenders = rng.sample(scored, min(size, len(scored)))
    contenders.sort(key=lambda item: (item[1], item[0]), reverse=True)
    return list(contenders[0][0])


def _crossover(parent_a: list[str], parent_b: list[str], individual_size: int) -> list[str]:
    return unique(parent_a[: individual_size // 2] + parent_b)[:individual_size]


def _mutate(child: list[str], pool: list[str], individual_size: int, mutation_rate: float, rng: random.Random) -> list[str]:
    child = list(child)
    if rng.random() < mutation_rate:
        available = [query for query in pool if query not in child]
        if available and child:
            child[rng.randrange(len(child))] = rng.choice(available)
    for query in pool:
        if len(child) >= individual_size:
            break
        if query not in child:
            child.append(query)
    return unique(child)[:individual_size]


def _result_text(result: dict[str, Any]) -> str:
    return f"{result.get('title', '')} {result.get('snippet', '')} {result.get('text', '')}".lower()


def _result_overlap_rate(results: list[dict[str, Any]], terms: list[str]) -> float:
    if not results or not terms:
        return 0.0
    matched = sum(1 for result in results if any(term.lower() in _result_text(result) for term in terms if term))
    return matched / len(results)


def _covered_terms_rate(results: list[dict[str, Any]], terms: list[str]) -> float:
    if not terms:
        return 0.0
    texts = [_result_text(result) for result in results]
    covered = sum(1 for term in terms if any(term.lower() in text for text in texts))
    return covered / len(terms)


def _covered_sources_rate(covered_source_types: set[str], source_scope: list[str]) -> float:
    if not source_scope:
        return 0.0
    covered = {target for target in source_scope if target in covered_source_types}
    return len(covered) / len(source_scope)


def _traceability(results: list[dict[str, Any]]) -> float:
    if not results:
        return 0.0
    return sum(1 for result in results if result.get("url")) / len(results)


def _redundancy_penalty(results: list[dict[str, Any]]) -> float:
    urls = [str(result.get("url")) for result in results if result.get("url")]
    if not urls:
        return 0.0
    return (len(urls) - len(set(urls))) / len(urls)


def _active_weights(weights: dict[str, float], *, stakeholders: list[str], stances: list[str]) -> dict[str, float]:
    active = dict(weights)
    if not stakeholders:
        active.pop("stakeholder_coverage", None)
    if not stances:
        active.pop("stance_diversity", None)
    total_positive = sum(value for key, value in active.items() if not key.endswith("_penalty"))
    if total_positive <= 0:
        return active
    original_positive = sum(value for key, value in weights.items() if not key.endswith("_penalty"))
    scale = original_positive / total_positive
    for key in list(active):
        if not key.endswith("_penalty"):
            active[key] *= scale
    return active


def _time_window_key(time_window: Any) -> str:
    if isinstance(time_window, dict):
        return "|".join(f"{key}={time_window.get(key)}" for key in sorted(time_window))
    return str(time_window or "")


def _event_seed(event: dict[str, Any]) -> int:
    return sum(ord(char) for char in str(event.get("event_id") or ""))

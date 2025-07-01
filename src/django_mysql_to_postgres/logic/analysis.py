# src/django_mysql_to_postgres/logic/analysis.py (Versão com Agrupamento Inteligente)
"""
Core logic for analyzing a Django project's model dependencies with grouping.
"""
from collections import defaultdict
from typing import Dict, List, Set, Type, Any

from django.apps import apps
from django.db.models import Model
from django.db.models.fields.related import (
    ForeignKey,
    ManyToManyField,
    OneToOneField,
)


class CircularDependencyError(Exception):
    """Custom exception raised when a model dependency cycle is detected."""
    pass


def generate_migration_plan(ignore_cycles: bool = False) -> Dict[str, Any]:
    """
    Analyzes all registered Django models and generates a hierarchical migration plan.

    Models are grouped into "levels" based on their dependencies, allowing for a
    clear, structured migration path.

    Args:
        ignore_cycles: If True, will not raise a CircularDependencyError.

    Returns:
        A dictionary containing the structured migration plan.
    """
    all_models: List[Type[Model]] = apps.get_models()
    model_map: Dict[Type[Model], str] = {
        model: f"{model._meta.app_label}.{model._meta.object_name}"
        for model in all_models
    }

    # Forward and reverse dependency graphs
    dependents_graph: Dict[Type[Model], Set[Type[Model]]] = defaultdict(set)
    dependencies_graph: Dict[Type[Model], Set[str]] = defaultdict(set)
    in_degree: Dict[Type[Model], int] = defaultdict(int)

    for model in all_models:
        if model not in in_degree:
            in_degree[model] = 0
        for field in model._meta.get_fields():
            if isinstance(field, (ForeignKey, OneToOneField)):
                related_model = field.related_model
                if related_model and related_model in all_models:
                    dependents_graph[related_model].add(model)
                    dependencies_graph[model].add(model_map[related_model])
                    in_degree[model] += 1

    # Kahn's algorithm modified to produce groups (levels)
    queue: List[Type[Model]] = [
        model for model in all_models if in_degree[model] == 0
    ]
    sorted_groups: List[Dict[str, Any]] = []
    processed_count = 0

    while queue:
        # The current queue represents a whole level of models that can be migrated
        current_level_models = sorted(queue, key=lambda m: model_map[m])
        group_details = []
        for model in current_level_models:
            group_details.append({
                "model": model_map[model],
                "dependencies": sorted(list(dependencies_graph.get(model, [])))
            })

        sorted_groups.append(group_details)
        processed_count += len(current_level_models)

        next_queue = []
        for model in current_level_models:
            for dependent_model in sorted(dependents_graph[model], key=lambda m: model_map[m]):
                in_degree[dependent_model] -= 1
                if in_degree[dependent_model] == 0:
                    next_queue.append(dependent_model)
        queue = next_queue

    warnings = []
    if processed_count != len(all_models):
        unsorted_models = {m for m in all_models if in_degree[m] > 0}
        unsorted_labels = ", ".join(model_map[m] for m in unsorted_models)

        if not ignore_cycles:
            raise CircularDependencyError(
                f"Circular dependency detected. Unsorted models: {unsorted_labels}")
        else:
            warnings.append(
                f"Circular dependency detected and ignored. The following models have an unpredictable order: {unsorted_labels}")
            # Add the cyclical models as a final group
            cyclical_group_details = []
            for model in sorted(unsorted_models, key=lambda m: model_map[m]):
                cyclical_group_details.append({
                    "model": model_map[model],
                    "dependencies": sorted(list(dependencies_graph.get(model, [])))
                })
            sorted_groups.append(cyclical_group_details)

    plan = {
        "grouped_migration_order": sorted_groups,
        "warnings": warnings,
    }
    return plan

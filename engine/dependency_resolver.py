# Part of Navigare Migrate. See LICENSE file for full copyright and licensing details.
# Copyright 2025 Navigare Space Ltd
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).

import logging
from collections import defaultdict, deque

from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


def resolve_import_order(env, model_names):
    """Determine the correct import order based on model dependencies.

    Uses a topological sort over explicit ``migrate.dependency`` records
    combined with implicit Many2one relations discovered from the models'
    field definitions.

    Args:
        env: Odoo Environment.
        model_names (list[str]): Technical model names to sort.

    Returns:
        list[str]: Model names in dependency order (dependencies first).

    Raises:
        :class:`~odoo.exceptions.UserError`: On circular dependency.
    """
    if not model_names:
        return []

    model_set = set(model_names)
    graph = defaultdict(set)  # model -> set of models it depends on

    # -- 1. Explicit dependencies from migrate.dependency ------------------
    Dependency = env.get('migrate.dependency')
    if Dependency is not None:
        deps = Dependency.search([
            ('model_name', 'in', list(model_set)),
            ('depends_on_model_name', 'in', list(model_set)),
        ])
        for dep in deps:
            graph[dep.model_name].add(dep.depends_on_model_name)

    # -- 2. Implicit Many2one relations ------------------------------------
    IrModelFields = env['ir.model.fields']
    for model_name in model_set:
        try:
            Model = env[model_name]
        except KeyError:
            continue

        for field_name, field_obj in Model._fields.items():
            if field_obj.type == 'many2one' and field_obj.comodel_name:
                target = field_obj.comodel_name
                if target in model_set and target != model_name:
                    graph[model_name].add(target)

    # -- 3. Topological sort (Kahn's algorithm) ----------------------------
    # Build in-degree map
    in_degree = {m: 0 for m in model_set}
    reverse_graph = defaultdict(set)  # dependency -> set of dependents
    for model, deps in graph.items():
        for dep in deps:
            if dep in model_set:
                in_degree[model] = in_degree.get(model, 0)
                reverse_graph[dep].add(model)

    # Recount in-degrees properly
    in_degree = {m: 0 for m in model_set}
    for model in model_set:
        for dep in graph.get(model, set()):
            if dep in model_set:
                in_degree[model] += 1

    queue = deque(
        m for m in model_set if in_degree[m] == 0
    )
    result = []

    while queue:
        node = queue.popleft()
        result.append(node)
        for dependent in reverse_graph.get(node, set()):
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                queue.append(dependent)

    if len(result) != len(model_set):
        # Circular dependency detected
        remaining = model_set - set(result)
        raise UserError(
            "Circular dependency detected among models: %s. "
            "Please review your migrate.dependency configuration."
            % ', '.join(sorted(remaining))
        )

    _logger.debug("Resolved import order: %s", result)
    return result

from __future__ import annotations

from dataclasses import dataclass

from app.models.stage import StageType


@dataclass(frozen=True)
class DagNode:
    stage_type: StageType
    deps: tuple[StageType, ...] = ()
    optional: bool = False


class StageDag:
    def __init__(self, nodes: list[DagNode]):
        self._nodes = {node.stage_type: node for node in nodes}
        self._children: dict[StageType, set[StageType]] = {node.stage_type: set() for node in nodes}
        for node in nodes:
            for dep in node.deps:
                if dep not in self._nodes:
                    raise ValueError(f"Unknown dependency: {dep} -> {node.stage_type}")
                self._children[dep].add(node.stage_type)

    def topological_order(self) -> list[StageType]:
        in_degree: dict[StageType, int] = {
            node.stage_type: len(node.deps) for node in self._nodes.values()
        }
        queue: list[StageType] = [stage for stage, degree in in_degree.items() if degree == 0]
        order: list[StageType] = []

        while queue:
            stage = queue.pop(0)
            order.append(stage)
            for child in self._children[stage]:
                in_degree[child] -= 1
                if in_degree[child] == 0:
                    queue.append(child)

        if len(order) != len(self._nodes):
            raise ValueError("Stage graph contains a cycle")
        return order

    def descendants_of(self, stage_type: StageType) -> set[StageType]:
        visited: set[StageType] = set()
        stack: list[StageType] = [stage_type]
        while stack:
            current = stack.pop()
            if current in visited:
                continue
            visited.add(current)
            stack.extend(self._children.get(current, ()))
        return visited

    def ancestors_of(self, stage_type: StageType) -> set[StageType]:
        reverse: dict[StageType, set[StageType]] = {node: set() for node in self._nodes}
        for child, node in self._nodes.items():
            for dep in node.deps:
                reverse[child].add(dep)

        visited: set[StageType] = set()
        stack: list[StageType] = [stage_type]
        while stack:
            current = stack.pop()
            if current in visited:
                continue
            visited.add(current)
            stack.extend(reverse.get(current, ()))
        return visited

    def resolve_execution_subset(
        self,
        *,
        from_stage: StageType | None = None,
        to_stage: StageType | None = None,
    ) -> list[StageType]:
        order = self.topological_order()
        if from_stage is None and to_stage is None:
            return order

        start_index = 0
        end_index = len(order) - 1

        if from_stage is not None:
            if from_stage not in order:
                raise ValueError(f"from_stage not in DAG subset: {from_stage}")
            start_index = order.index(from_stage)

        if to_stage is not None:
            if to_stage not in order:
                raise ValueError(f"to_stage not in DAG subset: {to_stage}")
            end_index = order.index(to_stage)

        if start_index > end_index:
            raise ValueError(f"Invalid stage range: from={from_stage} to={to_stage}")

        return order[start_index : end_index + 1]

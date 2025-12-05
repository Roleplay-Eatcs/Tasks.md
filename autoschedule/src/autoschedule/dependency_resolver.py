"""Dependency resolution for task scheduling."""

from typing import List, Dict, Set, Optional
from difflib import get_close_matches

from .markdown_parser import TodoItem


class DependencyResolver:
    """Resolve task dependencies with fuzzy matching."""

    def __init__(self, todos: List[TodoItem]):
        """Initialize with list of todos.

        Args:
            todos: List of TodoItem objects
        """
        self.todos = todos
        self.todo_map: Dict[str, TodoItem] = {todo.title: todo for todo in todos}
        self.title_list = list(self.todo_map.keys())

    def resolve_dependencies(self) -> List[TodoItem]:
        """Resolve dependencies and return topologically sorted tasks.

        Returns:
            List of TodoItem in dependency order (prerequisites first)

        Raises:
            ValueError: If circular dependency detected
        """
        # Build dependency graph with fuzzy matching
        dependency_graph = self._build_dependency_graph()

        # Detect cycles
        if self._has_cycle(dependency_graph):
            raise ValueError("Circular dependency detected in tasks")

        # Topological sort
        return self._topological_sort(dependency_graph)

    def _build_dependency_graph(self) -> Dict[str, List[str]]:
        """Build dependency graph with fuzzy matching.

        Returns:
            Dict mapping task title to list of prerequisite task titles
        """
        graph = {}

        for todo in self.todos:
            resolved_deps = []

            for dep_name in todo.dependencies:
                # Try exact match first (case-insensitive)
                exact_match = next(
                    (title for title in self.title_list if title.lower() == dep_name.lower()),
                    None
                )

                if exact_match:
                    resolved_deps.append(exact_match)
                else:
                    # Fuzzy match (cutoff=0.6 for reasonable similarity)
                    matches = get_close_matches(dep_name, self.title_list, n=1, cutoff=0.6)
                    if matches:
                        print(f"Fuzzy matched '{dep_name}' → '{matches[0]}'")
                        resolved_deps.append(matches[0])
                    else:
                        print(f"Warning: Dependency '{dep_name}' not found for task '{todo.title}'")

            graph[todo.title] = resolved_deps

        return graph

    def _has_cycle(self, graph: Dict[str, List[str]]) -> bool:
        """Check for circular dependencies using DFS.

        Args:
            graph: Dependency graph

        Returns:
            True if cycle detected, False otherwise
        """
        visited = set()
        rec_stack = set()

        def dfs(node: str) -> bool:
            """Depth-first search to detect cycles."""
            visited.add(node)
            rec_stack.add(node)

            for neighbor in graph.get(node, []):
                if neighbor not in visited:
                    if dfs(neighbor):
                        return True
                elif neighbor in rec_stack:
                    return True

            rec_stack.remove(node)
            return False

        for node in graph:
            if node not in visited:
                if dfs(node):
                    return True

        return False

    def _topological_sort(self, graph: Dict[str, List[str]]) -> List[TodoItem]:
        """Topologically sort tasks (prerequisites first).

        Uses Kahn's algorithm.

        Args:
            graph: Dependency graph

        Returns:
            List of TodoItem in topological order
        """
        # Calculate in-degrees
        in_degree = {title: 0 for title in graph}
        for deps in graph.values():
            for dep in deps:
                in_degree[dep] += 1

        # Queue with no dependencies
        queue = [title for title, degree in in_degree.items() if degree == 0]
        sorted_titles = []

        while queue:
            # Sort by priority within same level (high > medium > low)
            queue.sort(key=lambda t: {'high': 0, 'medium': 1, 'low': 2}.get(
                self.todo_map[t].priority, 1
            ))

            current = queue.pop(0)
            sorted_titles.append(current)

            # Reduce in-degree for dependent tasks
            for title, deps in graph.items():
                if current in deps:
                    in_degree[title] -= 1
                    if in_degree[title] == 0:
                        queue.append(title)

        # Convert back to TodoItem objects
        return [self.todo_map[title] for title in sorted_titles]

    def get_dependency_info(self) -> Dict[str, Dict]:
        """Get dependency information for each task.

        Returns:
            Dict with task titles and their dependency info
        """
        graph = self._build_dependency_graph()
        sorted_tasks = self._topological_sort(graph)

        # Build schedule order map
        order_map = {task.title: idx for idx, task in enumerate(sorted_tasks)}

        info = {}
        for task in self.todos:
            deps = graph.get(task.title, [])
            info[task.title] = {
                'dependencies': deps,
                'schedule_order': order_map.get(task.title, -1),
                'must_schedule_after': [self.todo_map[d].title for d in deps] if deps else []
            }

        return info

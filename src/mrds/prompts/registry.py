"""In-memory registry that discovers and resolves versioned prompts.

The registry scans ``<root>/<feature>/<version>.yaml`` files, indexes them by
``feature -> version -> LoadedPrompt``, and resolves lookups (exact version or
latest). It is intentionally feature-agnostic: any feature directory found on
disk is registered, so future features and future versions need no code changes.

The registry is filesystem-backed for now; persisting prompt versions to the
SQLite ``prompt_versions`` table is wired up in a later sprint.
"""

from __future__ import annotations

from pathlib import Path

from mrds.observability.logging import get_logger
from mrds.prompts.errors import PromptError, PromptNotFoundError
from mrds.prompts.loader import (
    DEFAULT_PROMPTS_DIR,
    PROMPT_FILE_SUFFIXES,
    load_prompt_file,
)
from mrds.prompts.models import LoadedPrompt

logger = get_logger(__name__)


class PromptRegistry:
    """Indexes prompts by feature and version, with discovery from disk."""

    def __init__(self, root: Path = DEFAULT_PROMPTS_DIR) -> None:
        self._root = root
        self._prompts: dict[str, dict[str, LoadedPrompt]] = {}

    # -- construction -----------------------------------------------------------

    @classmethod
    def from_directory(cls, root: Path = DEFAULT_PROMPTS_DIR) -> PromptRegistry:
        """Build a registry and eagerly discover all prompts under ``root``."""
        registry = cls(root)
        registry.discover()
        return registry

    def discover(self) -> int:
        """Scan the root directory and register every prompt file found.

        Returns:
            The number of prompts registered.

        Raises:
            PromptError: If the root directory does not exist.
        """
        if not self._root.is_dir():
            raise PromptError(f"Prompts root does not exist: {self._root}")

        count = 0
        for feature_dir in sorted(p for p in self._root.iterdir() if p.is_dir()):
            for prompt_file in sorted(self._iter_prompt_files(feature_dir)):
                prompt = load_prompt_file(prompt_file, feature=feature_dir.name)
                self.register(prompt)
                count += 1

        logger.info(
            "Discovered %d prompt(s) across %d feature(s) under %s",
            count,
            len(self._prompts),
            self._root,
        )
        return count

    def register(self, prompt: LoadedPrompt) -> None:
        """Register a single loaded prompt.

        Raises:
            PromptError: If the same feature/version is registered twice.
        """
        versions = self._prompts.setdefault(prompt.feature, {})
        if prompt.version in versions:
            raise PromptError(
                f"Duplicate prompt version for {prompt.identity} "
                f"({versions[prompt.version].source_path} and {prompt.source_path})"
            )
        versions[prompt.version] = prompt

    # -- lookup -----------------------------------------------------------------

    def get(self, feature: str, version: str) -> LoadedPrompt:
        """Return the prompt for an exact ``feature`` and ``version``."""
        try:
            return self._prompts[feature][version]
        except KeyError:
            raise PromptNotFoundError(f"No prompt registered for {feature}:{version}") from None

    def get_latest(self, feature: str) -> LoadedPrompt:
        """Return the highest-numbered version for ``feature``."""
        versions = self._prompts.get(feature)
        if not versions:
            raise PromptNotFoundError(f"No prompts registered for feature '{feature}'")
        latest = max(versions.values(), key=lambda p: p.definition.version_number)
        return latest

    def versions(self, feature: str) -> list[str]:
        """Return the registered version labels for ``feature``, lowest first."""
        versions = self._prompts.get(feature, {})
        return sorted(versions, key=lambda v: versions[v].definition.version_number)

    def features(self) -> list[str]:
        """Return all registered feature names, sorted."""
        return sorted(self._prompts)

    def __len__(self) -> int:
        return sum(len(v) for v in self._prompts.values())

    # -- helpers ----------------------------------------------------------------

    @staticmethod
    def _iter_prompt_files(feature_dir: Path) -> list[Path]:
        return [
            p for p in feature_dir.iterdir() if p.is_file() and p.suffix in PROMPT_FILE_SUFFIXES
        ]

"""Loading and content-hashing of prompt files.

The loader owns file I/O and YAML parsing, delegates schema validation to
:mod:`mrds.prompts.validation`, and computes a deterministic, content-based hash.

Hashing rule: the hash is taken over the canonicalised definition **excluding**
``created_at`` (which is provenance, not behaviour). Two files with identical
content therefore hash identically regardless of formatting, comments, key order,
or authoring date; editing the prompt body changes the hash.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from mrds.core.hashing import hash_json
from mrds.observability.logging import get_logger
from mrds.prompts.errors import PromptValidationError
from mrds.prompts.models import LoadedPrompt, PromptDefinition
from mrds.prompts.validation import validate_prompt_data

logger = get_logger(__name__)

DEFAULT_PROMPTS_DIR = Path("prompts")
PROMPT_FILE_SUFFIXES = (".yaml", ".yml")

# Fields excluded from the content hash (provenance, not behaviour).
_HASH_EXCLUDE = {"created_at"}


def compute_content_hash(definition: PromptDefinition) -> str:
    """Return a deterministic, content-based hash for a prompt definition."""
    payload = definition.model_dump(mode="json", exclude=_HASH_EXCLUDE)
    return hash_json(payload)


def load_prompt_from_definition_json(
    content: str, *, feature: str, source_path: Path | None = None
) -> LoadedPrompt:
    """Reconstruct a :class:`LoadedPrompt` from a serialized prompt definition.

    The DB read counterpart to :func:`load_prompt_file`: ``content`` is a
    ``PromptDefinition`` JSON document (as persisted in ``prompt_versions.content``),
    so there is no file or YAML involved. The content hash is recomputed from the
    definition, matching how filesystem-loaded prompts derive their identity.
    """
    definition = PromptDefinition.model_validate_json(content)
    return LoadedPrompt(
        feature=feature,
        definition=definition,
        content_hash=compute_content_hash(definition),
        source_path=source_path or Path(f"db://{feature}/{definition.version}"),
    )


def load_prompt_file(path: Path, *, feature: str | None = None) -> LoadedPrompt:
    """Load, validate, and hash a single prompt file.

    Args:
        path: Path to the prompt YAML file.
        feature: Feature name; defaults to the parent directory name.

    Raises:
        PromptValidationError: If the file is missing, unreadable, not valid YAML,
            or fails schema validation.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PromptValidationError(f"Cannot read prompt file {path}: {exc}") from exc

    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise PromptValidationError(f"Malformed YAML in {path}:\n{exc}") from exc

    definition = validate_prompt_data(data, source=path)
    resolved_feature = feature or path.parent.name
    content_hash = compute_content_hash(definition)

    logger.debug(
        "Loaded prompt %s:%s (hash=%s) from %s",
        resolved_feature,
        definition.version,
        content_hash[:12],
        path,
    )
    return LoadedPrompt(
        feature=resolved_feature,
        definition=definition,
        content_hash=content_hash,
        source_path=path,
    )

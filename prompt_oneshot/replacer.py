"""Replace embedded OneShot examples in prompt templates."""
from __future__ import annotations

import argparse
import re
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence

try:
    import tomllib  # type: ignore[attr-defined]
except ModuleNotFoundError as exc:  # pragma: no cover - Python <3.11 fallback
    raise RuntimeError("Python 3.11 or later is required to run this tool.") from exc


class ConfigError(ValueError):
    """Raised when a configuration file contains invalid data."""


@dataclass
class Heading:
    """Representation of a Markdown heading."""

    level: int
    title: str
    line_index: int


class MarkdownDocument:
    """Utility helper that exposes Markdown heading based sections."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.lines = text.splitlines()
        self._headings: List[Heading] = self._parse_headings()

    def _parse_headings(self) -> List[Heading]:
        headings: List[Heading] = []
        for index, raw_line in enumerate(self.lines):
            stripped = raw_line.lstrip()
            if not stripped.startswith("#"):
                continue
            level = len(stripped) - len(stripped.lstrip("#"))
            if level <= 0:
                continue
            title = stripped[level:].strip()
            if not title:
                continue
            headings.append(Heading(level=level, title=title, line_index=index))
        return headings

    @property
    def headings(self) -> Sequence[Heading]:
        return tuple(self._headings)

    def section(
        self,
        title: str,
        *,
        level: Optional[int] = None,
        include_heading: bool = True,
        occurrence: int = 1,
        strip: bool = True,
    ) -> str:
        matches = [
            h
            for h in self._headings
            if h.title == title and (level is None or h.level == level)
        ]
        if not matches:
            raise ConfigError(f"Heading '{title}' was not found in example text.")
        if occurrence < 1 or occurrence > len(matches):
            raise ConfigError(
                f"Heading '{title}' occurrence {occurrence} is outside of the available range ({len(matches)})."
            )
        heading = matches[occurrence - 1]
        start_line = heading.line_index
        end_line = len(self.lines)
        for candidate in self._headings:
            if candidate.line_index <= start_line:
                continue
            if candidate.level <= heading.level:
                end_line = candidate.line_index
                break
        selected = self.lines[start_line:end_line]
        if not include_heading:
            selected = selected[1:]
        content = "\n".join(selected)
        if strip:
            content = content.strip("\n")
        return content


@dataclass
class SourceSpec:
    """Configuration of how to extract content for a replacement."""

    type: str
    heading: Optional[str] = None
    level: Optional[int] = None
    include_heading: bool = True
    occurrence: int = 1
    headings: Optional[List[Dict[str, object]]] = None
    separator: str = "\n\n"
    start_marker: Optional[str] = None
    end_marker: Optional[str] = None
    include_start: bool = False
    include_end: bool = False
    text: Optional[str] = None
    strip: bool = True
    dedent: bool = False
    path: Optional[str] = None
    encoding: str = "utf-8"


@dataclass
class ReplacementPlan:
    """Replacement instruction for a single OneShot block."""

    start_marker: str
    end_marker: str
    source: SourceSpec
    prefix: str = ""
    suffix: str = ""
    indent: Optional[str] = None
    start_occurrence: int = 1
    end_occurrence: int = 1
    keep_start_marker: bool = True
    keep_end_marker: bool = True
    pad_with_newlines: Optional[bool] = None
    strip_replacement: bool = True


def _find_occurrence(text: str, marker: str, occurrence: int, *, start: int = 0) -> int:
    if occurrence < 1:
        raise ConfigError("Occurrences must be >= 1.")
    index = start
    for _ in range(occurrence):
        position = text.find(marker, index)
        if position == -1:
            raise ConfigError(f"Marker '{marker}' (occurrence {occurrence}) was not found.")
        index = position + len(marker)
    return position


def _extract_between_markers(
    text: str,
    start_marker: str,
    end_marker: Optional[str],
    *,
    include_start: bool = False,
    include_end: bool = False,
    occurrence: int = 1,
    strip: bool = True,
) -> str:
    start_pos = _find_occurrence(text, start_marker, occurrence)
    start_index = start_pos if include_start else start_pos + len(start_marker)
    if end_marker is None:
        end_index = len(text)
    else:
        search_start = start_pos + len(start_marker)
        end_pos = text.find(end_marker, search_start)
        if end_pos == -1:
            raise ConfigError(
                f"End marker '{end_marker}' following '{start_marker}' was not found."
            )
        end_index = end_pos + (len(end_marker) if include_end else 0)
    extracted = text[start_index:end_index]
    if strip:
        extracted = extracted.strip("\n")
    return extracted


def _indent_text(text: str, indent: str) -> str:
    if not indent:
        return text
    lines = text.splitlines()
    return "\n".join(indent + line if line else line for line in lines)


def _maybe_dedent(text: str, dedent: bool) -> str:
    if not dedent:
        return text
    return textwrap.dedent(text)


def _apply_padding(
    original_segment: str,
    new_content: str,
    pad_with_newlines: Optional[bool],
    strip_replacement: bool,
) -> str:
    if strip_replacement:
        new_content = new_content.strip("\n")
    if pad_with_newlines is None:
        leading_ws_match = re.match(r"^\s*", original_segment)
        trailing_ws_match = re.search(r"\s*$", original_segment)
        leading_ws = leading_ws_match.group(0) if leading_ws_match else ""
        trailing_ws = trailing_ws_match.group(0) if trailing_ws_match else ""
    elif pad_with_newlines:
        leading_ws = "\n"
        trailing_ws = "\n"
    else:
        leading_ws = ""
        trailing_ws = ""
    return f"{leading_ws}{new_content}{trailing_ws}"


def _parse_source_spec(raw: Dict[str, object]) -> SourceSpec:
    if not isinstance(raw, dict):
        raise ConfigError("Each source definition must be a table/object.")
    type_value = raw.get("type")
    if not isinstance(type_value, str):
        raise ConfigError("A source entry must define a 'type'.")
    source_type = type_value.lower()

    if source_type == "heading":
        heading = raw.get("heading")
        if not isinstance(heading, str) or not heading:
            raise ConfigError("Heading sources must provide a non-empty 'heading'.")
        return SourceSpec(
            type="heading",
            heading=heading,
            level=int(raw["level"]) if "level" in raw else None,
            include_heading=bool(raw.get("include_heading", True)),
            occurrence=int(raw.get("occurrence", 1)),
            strip=bool(raw.get("strip", True)),
            dedent=bool(raw.get("dedent", False)),
        )

    if source_type in {"heading_list", "headings"}:
        headings_raw = raw.get("headings")
        if not isinstance(headings_raw, list) or not headings_raw:
            raise ConfigError(
                "Heading list sources must provide a non-empty 'headings' array."
            )
        processed: List[Dict[str, object]] = []
        for entry in headings_raw:
            if isinstance(entry, str):
                processed.append({"heading": entry})
            elif isinstance(entry, dict):
                if "heading" not in entry:
                    raise ConfigError("Heading list entries must define 'heading'.")
                processed.append(dict(entry))
            else:
                raise ConfigError("Heading list entries must be either strings or tables.")
        return SourceSpec(
            type="heading_list",
            headings=processed,
            include_heading=bool(raw.get("include_heading", True)),
            separator=str(raw.get("separator", "\n\n")),
            strip=bool(raw.get("strip", True)),
            dedent=bool(raw.get("dedent", False)),
        )

    if source_type in {"marker", "markers"}:
        start_marker = raw.get("start_marker")
        if not isinstance(start_marker, str) or not start_marker:
            raise ConfigError("Marker sources must define a non-empty 'start_marker'.")
        end_marker = raw.get("end_marker")
        if end_marker is not None and not isinstance(end_marker, str):
            raise ConfigError("'end_marker' must be a string when provided.")
        return SourceSpec(
            type="markers",
            start_marker=start_marker,
            end_marker=end_marker,
            include_start=bool(raw.get("include_start", False)),
            include_end=bool(raw.get("include_end", False)),
            occurrence=int(raw.get("occurrence", 1)),
            strip=bool(raw.get("strip", True)),
            dedent=bool(raw.get("dedent", False)),
        )

    if source_type == "literal":
        text_value = raw.get("text")
        if not isinstance(text_value, str):
            raise ConfigError("Literal sources must provide a 'text' value.")
        return SourceSpec(
            type="literal",
            text=text_value,
            strip=bool(raw.get("strip", False)),
            dedent=bool(raw.get("dedent", False)),
        )

    if source_type == "file":
        path_value = raw.get("path")
        if not isinstance(path_value, str) or not path_value:
            raise ConfigError("File sources must provide a 'path'.")
        return SourceSpec(
            type="file",
            path=path_value,
            encoding=str(raw.get("encoding", "utf-8")),
            strip=bool(raw.get("strip", True)),
            dedent=bool(raw.get("dedent", False)),
        )

    raise ConfigError(f"Unsupported source type: {source_type}")


def _parse_replacement_plan(raw: Dict[str, object]) -> ReplacementPlan:
    if not isinstance(raw, dict):
        raise ConfigError("Each replacement must be a table/object.")
    for key in ("start_marker", "end_marker", "source"):
        if key not in raw:
            raise ConfigError(f"Replacement entries must include '{key}'.")
    source = _parse_source_spec(raw["source"])  # type: ignore[arg-type]
    return ReplacementPlan(
        start_marker=str(raw["start_marker"]),
        end_marker=str(raw["end_marker"]),
        source=source,
        prefix=str(raw.get("prefix", "")),
        suffix=str(raw.get("suffix", "")),
        indent=str(raw.get("indent")) if raw.get("indent") is not None else None,
        start_occurrence=int(raw.get("start_occurrence", 1)),
        end_occurrence=int(raw.get("end_occurrence", 1)),
        keep_start_marker=bool(raw.get("keep_start_marker", True)),
        keep_end_marker=bool(raw.get("keep_end_marker", True)),
        pad_with_newlines=(
            bool(raw.get("pad_with_newlines"))
            if "pad_with_newlines" in raw
            else None
        ),
        strip_replacement=bool(raw.get("strip_replacement", True)),
    )


def _resolve_source(
    spec: SourceSpec,
    *,
    example_text: str,
    example_doc: MarkdownDocument,
    base_dir: Path,
) -> str:
    if spec.type == "heading":
        if spec.heading is None:
            raise ConfigError("Heading source missing heading name.")
        result = example_doc.section(
            spec.heading,
            level=spec.level,
            include_heading=spec.include_heading,
            occurrence=spec.occurrence,
            strip=spec.strip,
        )
    elif spec.type == "heading_list":
        if not spec.headings:
            raise ConfigError("Heading list source missing headings configuration.")
        parts: List[str] = []
        for entry in spec.headings:
            heading_name = entry.get("heading")
            if not isinstance(heading_name, str):
                raise ConfigError("Heading list entries require a 'heading' name.")
            level = entry.get("level")
            level_value = int(level) if isinstance(level, int) else None
            include_heading = entry.get("include_heading")
            include_heading_value = (
                bool(include_heading)
                if isinstance(include_heading, bool)
                else spec.include_heading
            )
            occurrence = entry.get("occurrence")
            occurrence_value = int(occurrence) if isinstance(occurrence, int) else 1
            strip_value = entry.get("strip")
            if isinstance(strip_value, bool):
                local_strip = strip_value
            else:
                local_strip = spec.strip
            part = example_doc.section(
                heading_name,
                level=level_value,
                include_heading=include_heading_value,
                occurrence=occurrence_value,
                strip=local_strip,
            )
            parts.append(part)
        result = spec.separator.join(part for part in parts if part)
        if spec.strip:
            result = result.strip("\n")
    elif spec.type == "markers":
        if spec.start_marker is None:
            raise ConfigError("Marker sources require 'start_marker'.")
        result = _extract_between_markers(
            example_text,
            spec.start_marker,
            spec.end_marker,
            include_start=spec.include_start,
            include_end=spec.include_end,
            occurrence=spec.occurrence,
            strip=spec.strip,
        )
    elif spec.type == "literal":
        result = spec.text or ""
        if spec.strip:
            result = result.strip("\n")
    elif spec.type == "file":
        if spec.path is None:
            raise ConfigError("File source missing 'path'.")
        file_path = Path(spec.path)
        if not file_path.is_absolute():
            file_path = base_dir / file_path
        if not file_path.exists():
            raise ConfigError(f"File source '{file_path}' does not exist.")
        result = file_path.read_text(encoding=spec.encoding)
        if spec.strip:
            result = result.strip("\n")
    else:  # pragma: no cover - safeguarded by parser
        raise ConfigError(f"Unsupported source type '{spec.type}'.")

    result = _maybe_dedent(result, spec.dedent)
    return result


def _replace_segment(text: str, plan: ReplacementPlan, new_content: str) -> str:
    start_pos = _find_occurrence(text, plan.start_marker, plan.start_occurrence)
    start_insertion = start_pos if not plan.keep_start_marker else start_pos + len(plan.start_marker)

    search_start = start_insertion if plan.keep_start_marker else start_pos
    end_pos = _find_occurrence(text, plan.end_marker, plan.end_occurrence, start=search_start)
    end_insertion = end_pos + len(plan.end_marker) if not plan.keep_end_marker else end_pos

    original_segment = text[start_insertion:end_pos]

    replacement = f"{plan.prefix}{new_content}{plan.suffix}" if plan.prefix or plan.suffix else new_content
    if plan.indent:
        replacement = _indent_text(replacement, plan.indent)
    replacement = _apply_padding(
        original_segment,
        replacement,
        plan.pad_with_newlines,
        plan.strip_replacement,
    )

    return f"{text[:start_insertion]}{replacement}{text[end_insertion:]}"


def replace_oneshots(
    prompt_text: str,
    example_text: str,
    plans: Sequence[ReplacementPlan],
    *,
    base_dir: Path,
) -> str:
    doc = MarkdownDocument(example_text)
    updated_text = prompt_text
    for plan in plans:
        source_text = _resolve_source(
            plan.source,
            example_text=example_text,
            example_doc=doc,
            base_dir=base_dir,
        )
        updated_text = _replace_segment(updated_text, plan, source_text)
    return updated_text


def _load_config(path: Path) -> Dict[str, object]:
    with path.open("rb") as config_file:
        return tomllib.load(config_file)


def _parse_config(config: Dict[str, object], *, base_dir: Path) -> tuple[Path, Path, Optional[Path], List[ReplacementPlan]]:
    prompt_path_value = config.get("prompt_path")
    example_path_value = config.get("example_path")
    output_path_value = config.get("output_path")

    if not isinstance(prompt_path_value, str) or not prompt_path_value:
        raise ConfigError("Config must define a non-empty 'prompt_path'.")
    if not isinstance(example_path_value, str) or not example_path_value:
        raise ConfigError("Config must define a non-empty 'example_path'.")

    prompt_path = Path(prompt_path_value)
    example_path = Path(example_path_value)
    output_path = Path(output_path_value) if isinstance(output_path_value, str) and output_path_value else None

    if not prompt_path.is_absolute():
        prompt_path = base_dir / prompt_path
    if not example_path.is_absolute():
        example_path = base_dir / example_path
    if output_path is not None and not output_path.is_absolute():
        output_path = base_dir / output_path

    replacements_raw = config.get("replacements")
    if not isinstance(replacements_raw, list) or not replacements_raw:
        raise ConfigError("Config must provide a non-empty 'replacements' array.")
    plans = [_parse_replacement_plan(item) for item in replacements_raw]

    return prompt_path, example_path, output_path, plans


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, help="Path to a TOML config file.")
    parser.add_argument("--prompt", help="Override the prompt path defined in config.")
    parser.add_argument("--example", help="Override the example path defined in config.")
    parser.add_argument(
        "--output",
        help="Override the output path defined in config. If omitted the prompt file is modified in-place.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print the updated prompt to stdout instead of writing it.")
    parser.add_argument(
        "--encoding",
        default="utf-8",
        help="Encoding used for reading and writing text files (default: utf-8).",
    )

    args = parser.parse_args(argv)
    config_path = Path(args.config)
    if not config_path.exists():
        raise SystemExit(f"Config file '{config_path}' does not exist.")

    config_data = _load_config(config_path)
    prompt_path, example_path, output_path, plans = _parse_config(config_data, base_dir=config_path.parent)

    if args.prompt:
        prompt_path = Path(args.prompt)
    if args.example:
        example_path = Path(args.example)
    if args.output:
        output_path = Path(args.output)

    if output_path is None:
        output_path = prompt_path

    prompt_text = prompt_path.read_text(encoding=args.encoding)
    example_text = example_path.read_text(encoding=args.encoding)

    updated_text = replace_oneshots(
        prompt_text,
        example_text,
        plans,
        base_dir=config_path.parent,
    )

    if args.dry_run:
        sys.stdout.write(updated_text)
        if not updated_text.endswith("\n"):
            sys.stdout.write("\n")
    else:
        output_path.write_text(updated_text, encoding=args.encoding)

    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

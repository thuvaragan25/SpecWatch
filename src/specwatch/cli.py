"""SpecWatch command-line interface."""

import logging
import os
from pathlib import Path

import typer

from specwatch.agent.provider import create_chat_model
from specwatch.analysis import run_analysis
from specwatch.code.symbol_index import build_symbol_index
from specwatch.config import load_config
from specwatch.domain.errors import ConfigError
from specwatch.git.diff import changed_files, changed_symbols
from specwatch.mapping.requirement_mapper import (
    build_symbol_bm25_index,
    build_test_bm25_index,
    candidate_symbols_for_requirement,
    expand_candidates_via_callers,
    candidate_tests_for_requirement,
)
from specwatch.reporting.github import pr_number_from_github_event, post_or_update_pr_comment, write_job_summary
from specwatch.reporting.markdown import render_findings_markdown
from specwatch.specs.extractor import extract_requirements
from specwatch.storage.db import default_db_path, get_connection
from specwatch.storage.repositories import CandidateRepository, RequirementRepository
from specwatch.tests_index.index import build_test_index

app = typer.Typer(
    name="specwatch",
    help="Agentic specification-drift auditor for pull requests.",
    no_args_is_help=True,
)

config_app = typer.Typer(help="Manage SpecWatch configuration.")
app.add_typer(config_app, name="config")

requirements_app = typer.Typer(help="Extract, list, and inspect requirements.")
app.add_typer(requirements_app, name="requirements")


@app.callback()
def main(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging."),
) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )


@config_app.command("validate")
def config_validate() -> None:
    """Validate the SpecWatch configuration for the current repository."""
    try:
        config = load_config()
    except ConfigError as exc:
        typer.secho(f"Invalid configuration: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc

    typer.secho(f"Configuration valid (repo_path={config.repo_path})", fg=typer.colors.GREEN)


@requirements_app.command("extract")
def requirements_extract(
    path: Path = typer.Argument(..., help="Markdown spec file to parse."),
) -> None:
    """Parse a Markdown spec file and persist extracted requirements."""
    config = load_config()
    text = path.read_text()
    requirements = extract_requirements(text, source_file=str(path))

    conn = get_connection(default_db_path(config.repo_path))
    RequirementRepository(conn).save_all(requirements)

    typer.echo(f"Extracted {len(requirements)} requirement(s) from {path}")


@requirements_app.command("list")
def requirements_list() -> None:
    """List all requirements in the registry."""
    config = load_config()
    conn = get_connection(default_db_path(config.repo_path))
    requirements = RequirementRepository(conn).list()

    if not requirements:
        typer.echo("No requirements found. Run `specwatch requirements extract <file>` first.")
        return

    for requirement in requirements:
        typer.echo(
            f"{requirement.id}  [{requirement.passage_type.value}/{requirement.status.value}]  "
            f"{requirement.title}  ({requirement.source.file}:"
            f"{requirement.source.line_start}-{requirement.source.line_end})"
        )


@requirements_app.command("show")
def requirements_show(requirement_id: str) -> None:
    """Show full detail for one requirement."""
    config = load_config()
    conn = get_connection(default_db_path(config.repo_path))
    requirement = RequirementRepository(conn).get(requirement_id)

    if requirement is None:
        typer.secho(f"Unknown requirement: {requirement_id}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    typer.echo(f"{requirement.id} — {requirement.title}")
    typer.echo(f"Type: {requirement.passage_type.value}  Status: {requirement.status.value}")
    typer.echo(
        f"Source: {requirement.source.file}:"
        f"{requirement.source.line_start}-{requirement.source.line_end}"
    )
    typer.echo("")
    typer.echo(requirement.statement)

    candidate_repo = CandidateRepository(conn)
    symbol_candidates = candidate_repo.symbol_candidates_for_requirement(requirement.id)
    if symbol_candidates:
        typer.echo("\nCandidate code symbols:")
        for candidate in symbol_candidates:
            typer.echo(f"  {candidate.symbol_qualified_name}  ({candidate.method.value}, {candidate.score:.2f})")

    test_candidates = candidate_repo.test_candidates_for_requirement(requirement.id)
    if test_candidates:
        typer.echo("\nCandidate tests:")
        for candidate in test_candidates:
            typer.echo(f"  {candidate.test_qualified_name}  ({candidate.method.value}, {candidate.score:.2f})")


@app.command("diff")
def diff_command(
    base: str = typer.Option("HEAD~1", "--base", help="Base git revision."),
    head: str = typer.Option("HEAD", "--head", help="Head git revision."),
) -> None:
    """Show changed Python files and changed symbols between base and head."""
    config = load_config()
    files = changed_files(config.repo_path, base, head)

    if not files:
        typer.echo(f"No changed Python files between {base} and {head}.")
        return

    typer.echo(f"Changed files ({base}...{head}):")
    for file in files:
        rename_note = f" (renamed from {file.old_path})" if file.old_path else ""
        typer.echo(f"  {file.change_type.value:10s} {file.path}{rename_note}")

    symbols = changed_symbols(config.repo_path, base, head, config.repo_path)
    typer.echo("\nChanged symbols:")
    if not symbols:
        typer.echo("  (none)")
    for symbol in symbols:
        typer.echo(f"  {symbol.change_type.value:10s} {symbol.qualified_name}")


@app.command("index")
def index_repository(
    spec: Path = typer.Option(..., "--spec", help="Markdown spec file to extract requirements from."),
) -> None:
    """Extract requirements, index code and tests, and generate candidate mappings."""
    config = load_config()
    conn = get_connection(default_db_path(config.repo_path))

    requirements = extract_requirements(spec.read_text(), source_file=str(spec))
    RequirementRepository(conn).save_all(requirements)

    symbol_index = build_symbol_index(config.repo_path)
    test_index = build_test_index(config.repo_path, symbol_index)
    symbol_bm25 = build_symbol_bm25_index(symbol_index)
    test_bm25 = build_test_bm25_index(test_index)

    candidate_repo = CandidateRepository(conn)
    for requirement in requirements:
        symbol_candidates = expand_candidates_via_callers(
            candidate_symbols_for_requirement(requirement, symbol_bm25), symbol_index
        )
        test_candidates = candidate_tests_for_requirement(
            requirement, symbol_candidates, test_index, test_bm25
        )
        candidate_repo.replace_symbol_candidates(requirement.id, symbol_candidates)
        candidate_repo.replace_test_candidates(requirement.id, test_candidates)

    typer.echo(
        f"Indexed {len(requirements)} requirement(s), {len(symbol_index.symbols)} code symbol(s), "
        f"{len(test_index.list())} test(s)."
    )


@app.command("analyze")
def analyze_command(
    base: str = typer.Option(..., "--base", help="Base git revision."),
    head: str = typer.Option("HEAD", "--head", help="Head git revision."),
    post_github: bool = typer.Option(
        False,
        "--post-github",
        help="Also write a GitHub Actions job summary and create/update a single PR "
        "comment. Requires GITHUB_TOKEN, GITHUB_REPOSITORY, and GITHUB_EVENT_PATH "
        "(all set automatically inside a pull_request-triggered GitHub Actions run).",
    ),
) -> None:
    """Run the full pipeline: diff, impact filter, investigate, verify. Requires `specwatch index` to have been run first."""
    config = load_config()
    conn = get_connection(default_db_path(config.repo_path))
    chat_model = create_chat_model(config.model)

    results = run_analysis(
        repo=config.repo_path,
        base=base,
        head=head,
        chat_model=chat_model,
        conn=conn,
        min_confidence=config.min_confidence,
        max_tool_calls=config.max_tool_calls,
        max_rounds=config.max_rounds,
    )

    markdown = render_findings_markdown(results)
    published = [r for r in results if r.decision == "publish"]
    typer.echo("No specification drift findings." if not published else markdown)

    if not post_github:
        return

    write_job_summary(markdown)

    token = os.environ.get("GITHUB_TOKEN")
    repo_slug = os.environ.get("GITHUB_REPOSITORY")
    resolved_pr_number = pr_number_from_github_event()
    if not token or not repo_slug or not resolved_pr_number:
        typer.secho(
            "--post-github requires GITHUB_TOKEN, GITHUB_REPOSITORY, and a pull_request "
            "GITHUB_EVENT_PATH; skipping PR comment.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1)

    post_or_update_pr_comment(repo_slug, resolved_pr_number, token, markdown)


if __name__ == "__main__":
    app()

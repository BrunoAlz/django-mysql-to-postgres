# src/django_mysql_to_postgres/cli/main.py
"""
The main Command-Line Interface (CLI) for the application.
This file orchestrates the analysis and migration process by calling
the core logic and interacting with the user via prompts.
"""
import json
import os
import re
import sys
from importlib import import_module
from pathlib import Path
from typing import Optional

import django
import questionary
import typer
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress
from rich.table import Table

app = typer.Typer(
    name="db-porter",
    help="A robust tool to migrate data from MySQL to PostgreSQL for Django projects.",
)
console = Console()


def _find_django_project_root() -> Optional[Path]:
    """Searches upward from the current directory to find a 'manage.py' file."""
    current_dir = Path.cwd()
    for _ in range(10):
        if (current_dir / "manage.py").exists():
            return current_dir
        if current_dir.parent == current_dir:
            return None
        current_dir = current_dir.parent
    return None


def _get_settings_module_path(project_path: str) -> str:
    """Reads manage.py to find the project's settings module path."""
    manage_py_path = Path(project_path) / "manage.py"
    if not manage_py_path.exists():
        console.print(
            f"[bold red]Error: 'manage.py' not found at {project_path}.[/bold red]")
        raise typer.Exit(1)

    try:
        with open(manage_py_path, "r", encoding="utf-8") as f:
            content = f.read()
            match = re.search(
                r"os\.environ\.setdefault\(\s*['\"]DJANGO_SETTINGS_MODULE['\"]\s*,\s*['\"](.*?)['\"]\s*\)",
                content,
            )
            if match:
                return match.group(1)
    except Exception as e:
        console.print(
            f"[bold red]Error reading or parsing manage.py: {e}[/bold red]")
        raise typer.Exit(1)

    console.print(
        "[bold red]Error: Could not dynamically find DJANGO_SETTINGS_MODULE in manage.py.[/bold red]")
    raise typer.Exit(1)


def _setup_django(project_path: str, settings_module: str, db_config: Optional[dict] = None):
    """Dynamically configures the Django environment."""
    project_dir = Path(project_path).resolve()
    if str(project_dir) not in sys.path:
        sys.path.append(str(project_dir))

    os.environ["DJANGO_SETTINGS_MODULE"] = settings_module

    if db_config:
        from django.conf import settings
        settings.DATABASES = db_config

    try:
        django.setup()
        console.print(
            "[green]✔ Django environment configured successfully.[/green]")
    except ImportError as e:
        console.print(f"[bold red]Error during Django setup: {e}[/bold red]")
        raise typer.Exit(1)


@app.command()
def analyze(
    project_path: Optional[str] = typer.Option(
        None, "--path", "-p", help="Path to your Django project."),
    ignore_cycles: bool = typer.Option(
        False, "--ignore-cycles", help="Generate a plan even if cycles are detected.")
):
    """Analyzes a Django project and creates a safe data migration plan."""
    from django_mysql_to_postgres.logic.analysis import (
        CircularDependencyError,
        generate_migration_plan,
    )
    console.print(Panel.fit(
        "[bold magenta]Step 1: Analyzing Project Dependencies[/bold magenta]"))

    if not project_path:
        found_path = _find_django_project_root()
        if found_path:
            project_path = str(found_path.resolve())
            console.print(
                f"[bold green]✔ Django project found at:[/bold green] [cyan]{project_path}[/cyan]")
        else:
            console.print(
                "[bold red]Error: Could not auto-detect project root. Please provide the path using --path.[/bold red]")
            raise typer.Exit(1)

    settings_module = _get_settings_module_path(project_path)
    _setup_django(project_path, settings_module)

    try:
        plan = generate_migration_plan(ignore_cycles=ignore_cycles)
        # ... (rest of the logic is the same)
    except Exception as e:
        # ...
        pass


@app.command()
def migrate(
    plan_file: Path = typer.Option(
        "migration_plan.json", "--plan", help="Path to the migration plan."),
    project_path: Optional[str] = typer.Option(
        None, "--path", "-p", help="Path to your Django project.")
):
    """Executes the data migration using a pre-generated plan."""
    from django_mysql_to_postgres.cli.prompts import ask_for_db_credentials
    from django_mysql_to_postgres.logic.migration import execute_migration

    console.print(
        Panel.fit("[bold magenta]Step 2: Executing Data Migration[/bold magenta]"))

    if not plan_file.exists():
        console.print(
            f"[bold red]Error: Plan file '{plan_file}' not found. Run 'analyze' first.[/bold red]")
        raise typer.Exit(1)
    with open(plan_file, "r") as f:
        plan = json.load(f)

    if not project_path:
        found_path = _find_django_project_root()
        if found_path:
            project_path = str(found_path.resolve())
        else:
            console.print(
                "[bold red]Error: Could not auto-detect project root. Please provide the path using --path.[/bold red]")
            raise typer.Exit(1)

    # Load source credentials without initializing Django fully
    settings_module_path = _get_settings_module_path(project_path)
    sys.path.insert(0, project_path)
    user_settings = import_module(settings_module_path)
    source_creds = user_settings.DATABASES['default']
    sys.path.pop(0)

    console.print(
        "[green]✔ Source database (MySQL) detected from project settings.[/green]")

    dest_creds = ask_for_db_credentials(
        db_type="PostgreSQL", direction="Destination")

    table = Table(title="Migration Confirmation",
                  show_header=False, box=box.ROUNDED)
    table.add_column("Key", style="cyan", no_wrap=True)
    table.add_column("Value", style="magenta")
    table.add_row("Source DB (from settings)",
                  f"MySQL: '{source_creds['NAME']}' on {source_creds.get('HOST', 'localhost')}")
    table.add_row("Destination DB (provided)",
                  f"PostgreSQL: '{dest_creds['NAME']}' on {dest_creds.get('HOST', 'localhost')}")
    table.add_row("Models to Process", str(
        len(plan.get("migration_order", []))))
    console.print(table)

    console.print(
        "[bold yellow]WARNING: Data in the destination database tables will be DELETED before migration.[/bold yellow]")
    if not questionary.confirm("Are you sure you want to proceed?").ask():
        console.print("Migration cancelled by user.")
        raise typer.Exit()

    migration_db_config = {
        "default": dest_creds,
        "source": source_creds,
    }

    _setup_django(project_path, settings_module_path,
                  db_config=migration_db_config)

    with Progress() as progress:
        task = progress.add_task(
            "[cyan]Migrating...", total=len(plan["migration_order"]))

        def progress_callback(level, message):
            if "Migrating" in message and "\n" in message:
                progress.update(task, advance=1, description=message.strip())
            elif level in ("ERROR", "WARNING"):
                progress.console.print(f"[{level.lower()}]{message}[/]")

        try:
            execute_migration(plan, "source", "default", progress_callback)
        except Exception as e:
            console.print(f"\n[bold red]Migration failed: {e}[/bold red]")
            raise typer.Exit(1)

    console.print(
        Panel.fit("[bold green]✔ Data migration completed successfully![/bold green]"))


def run():
    app()

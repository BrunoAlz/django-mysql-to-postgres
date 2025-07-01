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


def _setup_django(project_path: str, db_config: Optional[dict] = None):
    """Dynamically configures the Django environment."""
    project_dir = Path(project_path).resolve()
    if str(project_dir) not in sys.path:
        sys.path.append(str(project_dir))

    manage_py_path = project_dir / "manage.py"
    if not manage_py_path.exists():
        console.print(
            f"[bold red]Error: 'manage.py' not found at {project_dir}.[/bold red]")
        raise typer.Exit(1)

    settings_module = None
    try:
        with open(manage_py_path, "r", encoding="utf-8") as f:
            content = f.read()
            match = re.search(
                r"os\.environ\.setdefault\(\s*['\"]DJANGO_SETTINGS_MODULE['\"]\s*,\s*['\"](.*?)['\"]\s*\)",
                content,
            )
            if match:
                settings_module = match.group(1)
    except Exception as e:
        console.print(
            f"[bold red]Error reading or parsing manage.py: {e}[/bold red]")
        raise typer.Exit(1)

    if not settings_module:
        console.print(
            "[bold red]Error: Could not dynamically find DJANGO_SETTINGS_MODULE in manage.py.[/bold red]")
        raise typer.Exit(1)

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
        None, "--path", "-p", help="Path to your Django project. Auto-detects if not provided."
    ),
    ignore_cycles: bool = typer.Option(
        False, "--ignore-cycles", help="Generate a best-effort plan even if dependency cycles are detected."
    )
):
    """
    Analyzes a Django project and creates a safe data migration plan.
    """
    from django_mysql_to_postgres.cli.prompts import ask_for_django_project_path
    from django_mysql_to_postgres.logic.analysis import (
        CircularDependencyError,
        generate_migration_plan,
    )

    console.print(Panel.fit(
        "[bold magenta]Step 1: Analyzing Project Dependencies[/bold magenta]"))

    if not project_path:
        console.print(
            "--> Project path not provided. Searching for 'manage.py'...")
        found_path = _find_django_project_root()
        if found_path:
            project_path = str(found_path.resolve())
            console.print(
                f"[bold green]✔ Django project found at:[/bold green] [cyan]{project_path}[/cyan]")
        else:
            console.print(
                "[bold yellow]Could not auto-detect project root.[/bold yellow]")
            project_path = ask_for_django_project_path()

    if not project_path:
        console.print(
            "[bold red]Error: Project path is required. Aborting.[/bold red]")
        raise typer.Exit(1)

    try:
        _setup_django(project_path)
        plan = generate_migration_plan(ignore_cycles=ignore_cycles)

        if plan.get("warnings"):
            console.print(
                "\n[bold yellow]Warnings generated during analysis:[/bold yellow]")
            for warning in plan["warnings"]:
                console.print(f"- {warning}")

        plan_md_path = Path("migration_plan.md")
        with open(plan_md_path, "w", encoding="utf-8") as f:
            f.write("# Migration Plan (Auto-Generated)\n\n")
            f.write("## Migration Order\n\n")
            flat_order = []
            for i, group in enumerate(plan.get("grouped_migration_order", []), 1):
                f.write(f"### Group {i}\n\n")
                for item in group:
                    model_label = item['model']
                    flat_order.append(model_label)
                    dependencies = item['dependencies']
                    comment = f"  # Depends on: {', '.join(dependencies)}" if dependencies else ""
                    f.write(f"- `{model_label}`{comment}\n")
                f.write("\n")

        plan_json_path = Path("migration_plan.json")
        with open(plan_json_path, "w") as f:
            simple_plan = {
                "migration_order": flat_order,
                "m2m_through_models": plan.get("m2m_through_models", [])
            }
            json.dump(simple_plan, f, indent=2)

        console.print(
            f"\n[bold green]✔ Analysis complete! Plan saved to:[/bold green]")
        console.print(f"- [cyan]{plan_md_path.resolve()}[/cyan]")

    except CircularDependencyError as e:
        console.print(f"\n[bold red]Error: {e}[/bold red]")
        console.print(
            "To generate a plan anyway, try running with the [bold cyan]--ignore-cycles[/bold cyan] flag.")
        raise typer.Exit(1)
    except Exception as e:
        console.print(
            f"\n[bold red]An unexpected error occurred: {e}[/bold red]")
        raise typer.Exit(1)


@app.command()
def migrate(
    plan_file: Path = typer.Option(
        "migration_plan.json", "--plan", help="Path to the migration_plan.json file."
    )
):
    """
    Executes the data migration using a pre-generated plan.
    """
    from django_mysql_to_postgres.cli.prompts import ask_for_db_credentials
    from django_mysql_to_postgres.logic.migration import execute_migration

    console.print(
        Panel.fit("[bold magenta]Step 2: Executing Data Migration[/bold magenta]"))

    if not plan_file.exists():
        console.print(
            f"[bold red]Error: Plan file '{plan_file}' not found.[/bold red]")
        console.print("Please run the 'analyze' command first.")
        raise typer.Exit(1)

    with open(plan_file, "r") as f:
        plan = json.load(f)

    # Ask for both database credentials upfront.
    source_creds = ask_for_db_credentials(db_type="MySQL", direction="Source")
    dest_creds = ask_for_db_credentials(
        db_type="PostgreSQL", direction="Destination")

    # Display confirmation table
    table = Table(title="Migration Confirmation",
                  show_header=False, box=box.ROUNDED)
    table.add_column("Key", style="cyan", no_wrap=True)
    table.add_column("Value", style="magenta")
    table.add_row(
        "Source DB", f"MySQL: '{source_creds['NAME']}' on {source_creds.get('HOST', 'localhost')}")
    table.add_row("Destination DB",
                  f"PostgreSQL: '{dest_creds['NAME']}' on {dest_creds.get('HOST', 'localhost')}")
    table.add_row("Models to Process", str(
        len(plan.get("migration_order", []))))
    console.print(table)

    console.print(
        "[bold yellow]WARNING: Data in the destination database tables will be DELETED before migration.[/bold yellow]")
    if not questionary.confirm("Are you sure you want to proceed?").ask():
        console.print("Migration cancelled by user.")
        raise typer.Exit()

    # Define the two-database configuration for the migration operation.
    migration_db_config = {
        "default": dest_creds,  # Destination must be 'default' for write operations
        "source": source_creds,  # Source can have any alias
    }

    # Setup Django ONCE with the complete two-database configuration.
    project_path = _find_django_project_root()
    if not project_path:
        console.print(
            "[bold red]Error: Could not find Django project root.[/bold red]")
        raise typer.Exit(1)

    _setup_django(str(project_path), db_config=migration_db_config)

    # Execute the migration
    with Progress() as progress:
        task = progress.add_task(
            "[cyan]Migrating...", total=len(plan["migration_order"]))

        def progress_callback(level, message):
            if "Migrating" in message and "\n" in message:
                progress.update(task, advance=1, description=message.strip())
            elif level in ("ERROR", "WARNING"):
                progress.console.print(f"[{level.lower()}]{message}[/]")

        try:
            execute_migration(
                plan=plan,
                source_db_alias="source",
                destination_db_alias="default",
                progress_callback=progress_callback,
            )
        except Exception as e:
            console.print(f"\n[bold red]Migration failed: {e}[/bold red]")
            raise typer.Exit(1)

    console.print(
        Panel.fit("[bold green]✔ Data migration completed successfully![/bold green]"))


def run():
    app()

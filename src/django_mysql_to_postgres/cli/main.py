# src/django_mysql_to_postgres/cli/main.py
"""
The main Command-Line Interface (CLI) for the application.
This file orchestrates the analysis and migration process by calling
the core logic and interacting with the user via prompts.
"""
import re  # NOVO: Importa o módulo de expressões regulares
import json
import os
import sys
from pathlib import Path
from typing import Optional

import django
import questionary
import typer
from decouple import Config, RepositoryEnv
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress
from rich.table import Table
from rich import box
from django_mysql_to_postgres.cli.prompts import ask_for_django_project_path

# Create the Typer app and a Rich console for beautiful output
app = typer.Typer(
    name="db-porter",
    help="A robust tool to migrate data from MySQL to PostgreSQL for Django projects.",
)
console = Console()

# --- Helper function to configure Django dynamically ---

# Adicione esta função auxiliar no main.py


def _find_django_project_root() -> Optional[Path]:
    """
    Searches upward from the current directory to find a Django project root.

    The project root is identified by the presence of a 'manage.py' file.

    Returns:
        A Path object to the project root if found, otherwise None.
    """
    current_dir = Path.cwd()
    # Limit search to avoid scanning the entire filesystem
    for _ in range(10):  # Search up to 10 levels up
        if (current_dir / "manage.py").exists():
            return current_dir
        if current_dir.parent == current_dir:  # Reached the filesystem root
            return None
        current_dir = current_dir.parent
    return None


def _setup_django(project_path: str, db_config: Optional[dict] = None):
    """
    Dynamically configures the Django environment by reading manage.py
    to find the correct settings module.
    """
    project_dir = Path(project_path).resolve()
    if str(project_dir) not in sys.path:
        sys.path.append(str(project_dir))

    manage_py_path = project_dir / "manage.py"
    if not manage_py_path.exists():
        console.print(
            f"[bold red]Error: 'manage.py' not found at {project_dir}.[/bold red]")
        raise typer.Exit(1)

    # NOVO: Lógica para encontrar o DJANGO_SETTINGS_MODULE dinamicamente
    settings_module = None
    try:
        with open(manage_py_path, "r") as f:
            content = f.read()
            # Procura pela linha: os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'my_project.settings')
            match = re.search(
                r"os\.environ\.setdefault\(\s*['\"]DJANGO_SETTINGS_MODULE['\"]\s*,\s*['\"](.*?)['\"]\s*\)",
                content,
            )
            if match:
                # Extrai o caminho do settings
                settings_module = match.group(1)
    except Exception as e:
        console.print(
            f"[bold red]Error reading or parsing manage.py: {e}[/bold red]")
        raise typer.Exit(1)

    if not settings_module:
        console.print(
            "[bold red]Error: Could not dynamically find DJANGO_SETTINGS_MODULE in manage.py.[/bold red]")
        console.print(
            "Please ensure it is set in the standard os.environ.setdefault format.")
        raise typer.Exit(1)

    console.print(f"--> Found settings module: [cyan]{settings_module}[/cyan]")
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", settings_module)

    # O resto da função continua igual
    if db_config:
        from django.conf import settings
        settings.DATABASES = db_config

    try:
        django.setup()
        console.print(
            "[green]✔ Django environment configured successfully.[/green]")
    except ImportError as e:
        console.print(f"[bold red]Error during Django setup: {e}[/bold red]")
        console.print(
            f"Please ensure that the project path '{project_path}' is correct and all dependencies are installed.")
        raise typer.Exit(1)
# --- Analyze Command ---


@app.command()
def analyze(

    project_path: Optional[str] = typer.Option(
        None, "--path", "-p", help="Path to your Django project root directory. Auto-detects if not provided."
    ),
    ignore_cycles: bool = typer.Option(
        False, "--ignore-cycles", help="Generate a best-effort plan even if dependency cycles are detected."
    )  # NOVO: Adiciona a flag --ignore-cycles
):
    """
    Analyzes a Django project, detects model dependencies, and creates a migration plan.
    """
    # ... (a lógica de detecção de caminho continua a mesma) ...
    from django_mysql_to_postgres.logic.analysis import (
        CircularDependencyError,
        generate_migration_plan,
    )

    console.print(Panel.fit(
        "[bold magenta]Step 1: Analyzing Project Dependencies[/bold magenta]"))

    if project_path:
        console.print(
            f"--> Using provided project path: [cyan]{project_path}[/cyan]")
    else:
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
        # NOVO: Passa a flag para a função de análise
        plan = generate_migration_plan(ignore_cycles=ignore_cycles)

        # NOVO: Verifica se o plano gerado contém avisos
        if plan.get("warnings"):
            console.print(
                "\n[bold yellow]Warnings generated during analysis:[/bold yellow]")
            for warning in plan["warnings"]:
                console.print(f"- {warning}")

        # ... (a lógica para salvar os arquivos .json e .md continua a mesma) ...
        plan_json_path = Path("migration_plan.json")
        with open(plan_json_path, "w") as f:
            json.dump(plan, f, indent=2)

        plan_md_path = Path("migration_plan.md")
        with open(plan_md_path, "w", encoding="utf-8") as f:
            f.write("# Migration Plan (Auto-Generated)\n\n")
            f.write("This plan was generated by `db-porter`.\n")
            f.write(
                "Models are grouped by dependency levels for a safe migration order.\n\n")

            if plan.get("warnings"):
                f.write("## ⚠️ Warnings\n\n")
                for warning in plan["warnings"]:
                    f.write(f"- **{warning}**\n")
                f.write(
                    "\n_The migration will proceed, but the order for cyclical models is not guaranteed._\n\n")

            # --- NOVO: Lógica para escrever os grupos ---
            grouped_order = plan.get("grouped_migration_order", [])
            for i, group in enumerate(grouped_order, 1):
                f.write(f"## Group {i}\n\n")
                f.write("These models can be migrated now.\n\n")
                for item in group:
                    model_label = item['model']
                    dependencies = item['dependencies']
                    comment = f"  # Depends on: {', '.join(dependencies)}" if dependencies else ""
                    f.write(f"- `{model_label}`{comment}\n")
                f.write("\n")

        # A lógica para salvar o JSON e imprimir as mensagens de sucesso continua a mesma
        plan_json_path = Path("migration_plan.json")
        with open(plan_json_path, "w") as f:
            # Para o JSON, vamos salvar uma lista simples para retrocompatibilidade com o comando migrate
            flat_order = [item['model']
                          for group in grouped_order for item in group]
            simple_plan = {"migration_order": flat_order,
                           "warnings": plan["warnings"]}
            json.dump(simple_plan, f, indent=2)

        console.print(
            f"\n[bold green]✔ Analysis complete! Intelligent plan saved to:[/bold green]")
        console.print(f"- [cyan]{plan_json_path.resolve()}[/cyan]")
        console.print(f"- [cyan]{plan_md_path.resolve()}[/cyan]")

        console.print(
            f"\n[bold green]✔ Analysis complete! Plan saved to:[/bold green]")
        console.print(f"- [cyan]{plan_json_path.resolve()}[/cyan]")
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
# --- Migrate Command ---


@app.command()
def migrate(
    plan_file: Path = typer.Option(
        "migration_plan.json", "--plan", help="Path to the migration_plan.json file."
    ),
    project_path: Optional[str] = typer.Option(
        None, "--path", "-p", help="Path to your Django project. Auto-detects if not provided."
    )
):
    """
    Executes the data migration using a pre-generated plan.
    It auto-detects the source database from the project's 'default' settings
    and prompts only for the destination database credentials.
    """
    from django.conf import settings
    from django.db import connections  # Importa o gerenciador de conexões
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

    console.print(
        "--> Auto-detecting source database from project settings...")
    if not project_path:
        project_path_obj = _find_django_project_root()
        if not project_path_obj:
            console.print(
                "[bold red]Error: Could not find Django project. Please run from within your project or provide a path with --path.[/bold red]")
            raise typer.Exit(1)
        project_path = str(project_path_obj)

    _setup_django(project_path)

    try:
        source_creds = settings.DATABASES['default']
        if "mysql" not in source_creds.get("ENGINE", ""):
            console.print(
                f"[bold red]Error: The project's default database is not MySQL ({source_creds.get('ENGINE')}).[/bold red]")
            raise typer.Exit(1)
        console.print(
            "[green]✔ Source database (MySQL) detected from settings.[/green]")
    except KeyError:
        console.print(
            "[bold red]Error: No 'default' database configured in your project's settings.[/bold red]")
        raise typer.Exit(1)

    dest_creds = ask_for_db_credentials(
        db_type="PostgreSQL", direction="Destination")

    table = Table(title="Migration Confirmation", show_header=False)
    table.add_column("Key", style="cyan", no_wrap=True)
    table.add_column("Value", style="magenta")
    table.add_row("Source DB (from settings)",
                  f"MySQL: '{source_creds['NAME']}' on {source_creds.get('HOST', 'localhost')}")
    table.add_row("Destination DB (provided)",
                  f"PostgreSQL: '{dest_creds['NAME']}' on {dest_creds['HOST']}")
    table.add_row("Models to Process", str(len(plan["migration_order"])))
    console.print(table)

    console.print(
        "[bold yellow]WARNING: Data in the destination database tables will be DELETED before migration.[/bold yellow]")
    confirmed = questionary.confirm("Are you sure you want to proceed?").ask()

    if not confirmed:
        console.print("Migration cancelled by user.")
        raise typer.Exit()

    # --- A CORREÇÃO FINAL ---
    # 1. Força o Django a fechar todas as conexões em cache (a 'default' para o MySQL)
    connections.close_all()

    # 2. Define a nova configuração de bancos de dados para a migração
    migration_db_config = {
        # O destino (PostgreSQL) se torna o 'default' para a operação
        "default": dest_creds,
        "source_from_settings": source_creds,
    }

    # 3. Reconfigura o ambiente Django, que agora será forçado a criar novas conexões
    _setup_django(str(project_path), db_config=migration_db_config)

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
                source_db_alias="source_from_settings",
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

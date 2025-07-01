# src/django_mysql_to_postgres/cli/prompts.py
"""
Handles all interactive user prompts for the CLI.
"""
from typing import Dict

import questionary
from rich.console import Console

console = Console()


def ask_for_db_credentials(db_type: str, direction: str) -> Dict[str, str]:
    """
    Interactively asks the user for database credentials.

    Args:
        db_type: The type of the database (e.g., "MySQL", "PostgreSQL").
        direction: The role of the database ("Source" or "Destination").

    Returns:
        A dictionary containing the database credentials.
    """
    prefix = f"{direction} ({db_type})"
    console.print(
        f"\n[bold cyan]Please provide the {prefix} database credentials:[/bold cyan]")

    creds = {}
    creds["ENGINE"] = (
        "django.db.backends.mysql" if db_type == "MySQL" else "django.db.backends.postgresql"
    )
    creds["HOST"] = questionary.text(
        f"  {prefix} - Host:", default="localhost").ask()
    creds["PORT"] = questionary.text(
        f"  {prefix} - Port:", default="3306" if db_type == "MySQL" else "5432"
    ).ask()
    creds["NAME"] = questionary.text(f"  {prefix} - Database Name:").ask()
    creds["USER"] = questionary.text(f"  {prefix} - User:").ask()
    creds["PASSWORD"] = questionary.password(f"  {prefix} - Password:").ask()

    return creds


def ask_for_django_project_path() -> str:
    """Asks the user for the path to their Django project's root directory."""
    console.print(
        "\n[bold cyan]Please provide the absolute path to your Django project's root directory:[/bold cyan]")
    console.print(
        "(This is the directory that contains your 'manage.py' file)")

    path = questionary.path("Project Path:").ask()
    return path

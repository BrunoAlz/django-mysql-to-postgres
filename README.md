# Django MySQL to PostgreSQL Data Porter (`db-porter`)

A robust, interactive command-line tool to migrate data from a MySQL database to PostgreSQL for Django projects, preserving primary keys and handling complex dependencies.

![PyPI Version](https://img.shields.io/pypi/v/django-mysql-to-postgres)
![License](https://img.shields.io/pypi/l/django-mysql-to-postgres)

---

## The Problem

Migrating a live Django application's database from MySQL to PostgreSQL can be a complex and error-prone process. Standard tools like `pgloader` may not correctly handle Django's specific content types or complex foreign key relationships, and using `dumpdata`/`loaddata` often fails with circular dependencies.

This tool was born from a real-world migration challenge and is designed to automate and simplify this entire process.

## Key Features

* **Interactive CLI:** A user-friendly command-line interface that guides you through every step.
* **Dynamic Django Integration:** Automatically detects your Django project and settings, even complex structures (e.g., `configurations/`).
* **Intelligent Dependency Analysis:** Performs a topological sort on your models to determine a safe migration order.
* **Circular Dependency Handling:** Includes a `--ignore-cycles` mode to generate a best-effort plan for projects with inescapable circular dependencies.
* **Robust & Safe:** Cleans destination tables before migration, re-enables database constraints, and resets primary key sequences upon completion.
* **Human-Readable Plans:** Generates a `migration_plan.md` file so you can review the migration order before executing.

## Installation

Install the package within your Django project's virtual environment. You'll also need the appropriate database drivers.

```bash
# Install the tool and the postgres driver
pip install django-mysql-to-postgres psycopg2-binary

# If your source is MySQL, also install the mysql driver
pip install mysqlclient
```

## Usage

The process is two simple steps: `analyze` and `migrate`.

### Step 1: Analyze Your Project

First, navigate to your Django project's root directory (the one with `manage.py`) and run the `analyze` command.

```bash
db-porter analyze
```

* The tool will auto-detect your project and settings.
* It will analyze all your models and their dependencies.
* It will create two files:
    * `migration_plan.json`: A machine-readable migration order.
    * `migration_plan.md`: A human-readable plan for you to review.

If you have circular dependencies, the command will fail safely. You can generate a "best-effort" plan using the `--ignore-cycles` flag:

```bash
db-porter analyze --ignore-cycles
```

### Step 2: Execute the Migration

Once you are satisfied with the plan, run the `migrate` command:

```bash
db-porter migrate
```

* The tool will interactively ask for your **Source (MySQL)** and **Destination (PostgreSQL)** database credentials.
* It will show you a final confirmation summary.
* Upon confirmation, it will clean the destination tables and migrate all data, showing a live progress bar.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Contributing

Contributions, issues, and feature requests are welcome!
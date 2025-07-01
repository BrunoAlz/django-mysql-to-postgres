# seu_app/management/commands/analyze_dependencies.py

from django.core.management.base import BaseCommand
from django.apps import apps
from django.db.models.fields.related import ForeignKey, OneToOneField, ManyToManyField


class Command(BaseCommand):
    help = 'Analisa e lista todos os modelos e suas dependências de chave estrangeira.'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS(
            "--- Relatório de Dependências de Modelos ---"
        ))
        self.stdout.write(
            "Use este relatório para construir a ordem manual de migração.\n"
            "Um modelo que aparece na lista de dependências de outro deve ser migrado ANTES."
        )

        # Pega todos os modelos e os ordena por nome para uma saída consistente
        all_models = sorted(
            apps.get_models(),
            key=lambda m: f"{m._meta.app_label}.{m._meta.object_name}"
        )

        for model in all_models:
            model_label = f"{model._meta.app_label}.{model._meta.object_name}"
            self.stdout.write("\n" + "="*len(model_label))
            self.stdout.write(self.style.SUCCESS(model_label))
            self.stdout.write("="*len(model_label))

            found_dependency = False

            # Pega todos os campos, incluindo ManyToMany
            fields = model._meta.get_fields(include_hidden=False)

            for field in sorted(fields, key=lambda f: f.name):
                related_model = None
                field_type_str = ""

                # Verifica se é uma relação direta (FK, O2O)
                if isinstance(field, (ForeignKey, OneToOneField)):
                    related_model = field.related_model
                    field_type_str = field.__class__.__name__

                # Verifica se é uma relação ManyToMany
                elif isinstance(field, ManyToManyField):
                    related_model = field.related_model
                    field_type_str = "ManyToManyField"

                if related_model:
                    found_dependency = True
                    related_model_label = (
                        f"{related_model._meta.app_label}."
                        f"{related_model._meta.object_name}"
                    )

                    self.stdout.write(
                        f"  -> Campo '{self.style.WARNING(field.name)}' "
                        f"({field_type_str}) aponta para: "
                        f"{self.style.NOTICE(related_model_label)}"
                    )

            if not found_dependency:
                self.stdout.write(self.style.HTTP_INFO(
                    "  (Sem dependências diretas de chave estrangeira)"))

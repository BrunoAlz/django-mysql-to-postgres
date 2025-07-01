# seu_app/management/commands/migrate_from_mysql.py

from django.core.management.base import BaseCommand
from django.apps import apps
from django.db import connections, transaction, models
import sys

# Tenta importar os erros específicos do psycopg2 para um tratamento mais preciso
try:
    from psycopg2 import errors as psycopg2_errors
except ImportError:
    psycopg2_errors = None


class Command(BaseCommand):
    help = 'Limpa, migra e trata erros de tabelas inexistentes no processo.'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS(
            "Iniciando o processo completo de migração de dados."))

        MODELS_TO_MIGRATE = [
            # A lista de modelos permanece a mesma que definimos anteriormente
            'administracao.Cargo', 'azure.AzureBug', 'clickup.ClickUpTeam', 'clickup.ClickUpUser',
            'contenttypes.ContentType', 'django_apscheduler.DjangoJob',
            'sessions.Session', 'sistemas.Sistema', 'auth.Permission', 'clickup.ClickUpSpace',
            'django_apscheduler.DjangoJobExecution', 'sistemas.Menu', 'sistemas.Modulo',
            'auth.Group', 'clickup.ClickUpFolder', 'sistemas.SubModulo',
            'clickup.ClickUpList', 'administracao.Operacao', 'usuario.User', 'admin.LogEntry',
            'administracao.HistoricoDeBuscas', 'casostestes.SessaoDeTeste', 'notificacoes.Notificacao',
            'relatorios.Exportacao', 'sobre.Sobre', 'tutoriais.Tutorial', 'versoes.Versao',
            'administracao.Ambiente', 'dados_operacao.OperacaoUnidade', 'sistemas.Tela',
            'sobre.SobreConteudo', 'versoes.NotaVersao', 'analise_ambiente.ChecklistTemplate',
            'conteudos.Conteudo', 'dados_operacao.OperacaoSistema', 'rotinas.Rotina',
            'sistemas.Componente', 'sobre.SobreArquivo', 'sobre.SobreVideo', 'analise_ambiente.CheckListItem',
            'casostestes.CasoDeTeste', 'clickup.ClickUpTask', 'dados_operacao.OperacaoParametros',
            'dados_operacao.OperacaoUtilizacao', 'rotinas.RotinaConteudo', 'sistemas.HistoricalComponente',
            'sistemas.RelacionamentoComponente', 'sistemas.ValidacoesComponente', 'analise_ambiente.ChecklistExecucao',
            'bug_tracker.Bug', 'casostestes.CasoDeTesteSessao', 'casostestes.HistoricalCasoDeTeste',
            'clickup.ClickUpAttachment', 'rotinas.RotinaArquivo', 'rotinas.RotinaContribuicao',
            'rotinas.RotinaParametros', 'rotinas.RotinaReacoes', 'rotinas.RotinaVideo',
            'sistemas.HistoricalRelacionamentoComponente', 'sistemas.HistoricalValidacoesComponente',
            'sistemas.Images', 'analise_ambiente.ItemExecucao', 'bug_tracker.OcorrenciaBug',
        ]

        with connections['default'].cursor() as cursor:
            self.stdout.write(self.style.WARNING(
                "Desativando triggers e foreign keys no PostgreSQL..."))
            cursor.execute("SET session_replication_role = 'replica';")

            # FASE 1: LIMPEZA
            self.stdout.write(self.style.SUCCESS(
                "\n--- FASE 1: Limpando tabelas de destino... ---"))
            for model_label in reversed(MODELS_TO_MIGRATE):
                try:
                    model = apps.get_model(model_label)
                    table_name = model._meta.db_table
                    self.stdout.write(f"Limpando tabela: {table_name}")
                    cursor.execute(
                        f'TRUNCATE TABLE "{table_name}" RESTART IDENTITY CASCADE;')
                except psycopg2_errors.UndefinedTable:
                    # NOVO: Captura o erro específico e continua
                    self.stdout.write(self.style.WARNING(
                        f"AVISO: Tabela '{table_name}' não encontrada no PostgreSQL. Pulando limpeza."))
                    pass
                except Exception as e:
                    self.stderr.write(self.style.ERROR(
                        f"Erro inesperado ao limpar a tabela {model_label}: {e}"))
                    cursor.execute("SET session_replication_role = 'origin';")
                    sys.exit(1)

            # FASE 2: MIGRAÇÃO DOS DADOS
            self.stdout.write(self.style.SUCCESS(
                "\n--- FASE 2: Migrando dados do MySQL para o PostgreSQL... ---"))
            migrated_models_classes = []
            for model_label in MODELS_TO_MIGRATE:
                model = apps.get_model(model_label)
                migrated_models_classes.append(model)

                self.stdout.write(
                    f"\nMigrando {model._meta.verbose_name_plural}...")
                try:
                    source_items = list(
                        model.objects.using('mysql_source').all())
                    count = len(source_items)
                except Exception as e:
                    # Também trata o erro caso a tabela não exista no MySQL
                    if '1146' in str(e):  # Código de erro do MySQL para "Table doesn't exist"
                        self.stdout.write(self.style.WARNING(
                            f"AVISO: Tabela para '{model_label}' não encontrada no MySQL. Pulando."))
                        continue
                    self.stderr.write(self.style.ERROR(
                        f"Erro ao buscar dados do MySQL para {model_label}: {e}"))
                    continue

                if count == 0:
                    self.stdout.write("Nenhum item para migrar.")
                    continue

                self.stdout.write(
                    f"Encontrados {count} itens. Inserindo no PostgreSQL...")
                try:
                    model.objects.using('default').bulk_create(
                        source_items, batch_size=1000)
                    self.stdout.write(self.style.SUCCESS("Sucesso!"))
                except psycopg2_errors.UndefinedTable:
                    # NOVO: Captura o erro específico durante a inserção
                    self.stdout.write(self.style.WARNING(
                        f"AVISO: Tabela para '{model._meta.db_table}' não encontrada no PostgreSQL. Pulando inserção."))
                    pass
                except Exception as e:
                    self.stderr.write(self.style.ERROR(
                        f"Erro ao inserir dados: {e}"))
                    self.stderr.write(self.style.ERROR(
                        "A migração foi interrompida."))
                    cursor.execute("SET session_replication_role = 'origin';")
                    sys.exit(1)

            # FASE 3: MIGRAÇÃO DE TABELAS MANY-TO-MANY
            # (A lógica aqui é robusta o suficiente, pois os modelos principais já foram verificados)
            self.stdout.write(self.style.SUCCESS(
                "\n--- FASE 3: Migrando relações Many-to-Many... ---"))
            for model in migrated_models_classes:
                for field in model._meta.get_fields():
                    if isinstance(field, models.ManyToManyField) and not field.auto_created:
                        m2m_model = field.remote_field.through
                        self.stdout.write(
                            f"\nProcessando M2M para o campo: {field.name} (tabela {m2m_model._meta.db_table})")
                        try:
                            m2m_relations = list(
                                m2m_model.objects.using('mysql_source').all())
                            if m2m_relations:
                                m2m_model.objects.using('default').bulk_create(
                                    m2m_relations, batch_size=2000)
                                self.stdout.write(self.style.SUCCESS(
                                    f"Sucesso: {len(m2m_relations)} relações migradas."))
                            else:
                                self.stdout.write(
                                    "Nenhuma relação para migrar.")
                        except Exception as e:
                            self.stderr.write(self.style.ERROR(
                                f"Erro ao migrar M2M {m2m_model._meta.db_table}: {e}"))

            # FASE FINAL: REATIVAÇÃO E VERIFICAÇÃO
            self.stdout.write(self.style.WARNING(
                "\n--- Finalizando: Reativando triggers e foreign keys... ---"))
            cursor.execute("SET session_replication_role = 'origin';")

            self.stdout.write(self.style.SUCCESS(
                "\nVerificando e ajustando as sequências de ID..."))
            for model in migrated_models_classes:
                try:
                    table_name = model._meta.db_table
                    pk_name = model._meta.pk.name

                    if not isinstance(model._meta.pk, (models.AutoField, models.BigAutoField)):
                        continue

                    sql = f"""SELECT setval(pg_get_serial_sequence('"{table_name}"', '{pk_name}'), COALESCE(MAX("{pk_name}"), 1), MAX("{pk_name}") IS NOT NULL) FROM "{table_name}";"""
                    cursor.execute(sql)
                except psycopg2_errors.UndefinedTable:
                    # NOVO: Pula o ajuste de sequência se a tabela não existir
                    pass
                except Exception as e:
                    # Outros erros (ex: permissão, etc.) ainda são reportados
                    if 'relation' in str(e) and 'does not exist' in str(e):
                        pass  # Ignora silenciosamente se a tabela sumiu
                    else:
                        self.stderr.write(self.style.WARNING(
                            f"Não foi possível ajustar sequência para {table_name}: {e}"))

        self.stdout.write(self.style.SUCCESS(
            "\n\nPROCESSO DE MIGRAÇÃO CONCLUÍDO! (Verifique os avisos acima para tabelas puladas)"))

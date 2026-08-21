# Flyway: Практическое руководство по эксплуатации

## Определения

*   **Версионированная миграция (Versioned Migration):** Скрипт с уникальным номером версии (например, `V1__init.sql`), который применяется один раз.
*   **Повторяемая миграция (Repeatable Migration):** Скрипт (например, `R__views.sql`), который применяется каждый раз при изменении его контрольной суммы. Идеально для View, функций и процедур.
*   **Undo-миграция (Undo Migration):** Скрипт (например, `U1__init.sql`), предназначенный для отката соответствующей версионированной миграции (доступно в Teams/Enterprise).
*   **Схема метаданных (Schema History Table):** Таблица (по умолчанию `flyway_schema_history`), где Flyway хранит состояние примененных миграций.

## Базовые конфигурации

### 1. Конфигурация через `flyway.conf` (CLI)
Рекомендуется для использования в Docker и CI-пайплайнах.

```properties
flyway.url=jdbc:postgresql://db.example.com:5432/mydb
flyway.user=flyway_user
flyway.password=${DB_PASSWORD}
flyway.schemas=public
flyway.locations=filesystem:./sql
flyway.connectRetries=10
# Запрет очистки БД на всех средах кроме local
flyway.cleanDisabled=true
```

### 2. Конфигурация в Maven (`pom.xml`)
```xml
<plugin>
    <groupId>org.flywaydb</groupId>
    <artifactId>flyway-maven-plugin</artifactId>
    <version>10.0.0</version>
    <configuration>
        <url>jdbc:postgresql://localhost:5432/mydb</url>
        <user>postgres</user>
        <password>pass</password>
        <locations>
            <location>filesystem:src/main/resources/db/migration</location>
        </locations>
    </configuration>
</plugin>
```

---

## CI/CD Пайплайны

### 1. GitLab CI (через Docker-образ Flyway)
Паттерн: запуск миграций перед деплоем приложения.

```yaml
variables:
  FLYWAY_IMAGE: flyway/flyway:10.0.0-alpine

migrate_database:
  stage: deploy
  image: $FLYWAY_IMAGE
  script:
    - flyway migrate \
        -url="jdbc:postgresql://${DB_HOST}:5432/${DB_NAME}" \
        -user="${FLYWAY_USER}" \
        -password="${FLYWAY_PASSWORD}" \
        -connectRetries=60
  only:
    - main
  environment:
    name: production
```

### 2. GitHub Actions (через CLI)
```yaml
name: DB Migration
on:
  push:
    branches: [ main ]
jobs:
  migrate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Install Flyway
        run: |
          wget -qO- https://download.red-gate.com/maven/release/com/redgate/flyway/flyway-commandline/10.0.0/flyway-commandline-10.0.0-linux-x64.tar.gz | tar xvz
          sudo ln -s `pwd`/flyway-10.0.0/flyway /usr/local/bin/flyway
      - name: Run Flyway Migrate
        env:
          FLYWAY_PASSWORD: ${{ secrets.DB_PASSWORD }}
        run: |
          flyway migrate \
            -url="jdbc:postgresql://${{ secrets.DB_HOST }}:5432/mydb" \
            -user="flyway_user" \
            -locations="filesystem:./migrations"
```

---

## Сложные откаты и стратегии восстановления

### 1. Стратегия "Fix-Forward" (SRE Best Practice)
Самый безопасный метод. Вместо отката создается новая миграция, исправляющая проблему.
*   **Пример:** `V2__add_index.sql` вызвал лаг. Решение: создать `V3__drop_problematic_index.sql`.
*   **Плюс:** Сохраняется иммутабельность истории, нет риска расхождения состояний между БД в кластере.

### 2. Использование Undo-скриптов (Flyway Teams)
Если необходимо физически откатить схему:
1. Создать пару: `V5__add_col.sql` и `U5__add_col.sql`.
2. Выполнить команду: `flyway undo`.
*   **Риск:** `Undo` не может восстановить данные, удаленные с помощью `DROP COLUMN`. Всегда делайте бэкап перед `undo`.

### 3. Ручное восстановление при Checksum Mismatch
Если кто-то изменил файл `V1__init.sql` после его применения:
1. **Dev/Test:** Выполнить `flyway repair`. Это обновит контрольные суммы в таблице истории.
2. **Production:** **НИКОГДА** не делайте `repair` автоматически. Исправьте файл в Git так, чтобы он соответствовал тому, что было применено, или создайте новую миграцию.

---

## Рекомендации SRE

*   **Транзакционность:** Flyway автоматически оборачивает каждую миграцию в транзакцию (если СУБД поддерживает DDL-транзакции, как PostgreSQL).
    *   *Внимание:* В MySQL/Oracle DDL вызывает неявный коммит. При сбое миграция может примениться частично. В таких случаях требуется ручная очистка таблицы `flyway_schema_history`.
*   **Baseline:** При внедрении Flyway в существующий проект используйте `flyway baseline`. Это создаст запись о текущем состоянии, и Flyway начнет отсчет с этой точки.
*   **Placeholder:** Используйте плейсхолдеры для переменных окружения (например, `${schema_name}`). Это позволяет использовать одни и те же скрипты для разных схем (Dev/Stage/Prod).

## См. также
- **[Database CI/CD](../database-ci-cd.md)** — общие принципы автоматизации.
- **[Стратегии отката (Rollback)](../rollback_strategies.md)** — теория и выбор подхода.
- **[Liquibase: Практическое руководство](./liquibase_practical_guide.md)** — альтернативный инструмент.

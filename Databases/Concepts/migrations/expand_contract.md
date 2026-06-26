# Обратно-совместимые миграции: Принцип Expand-Contract

## Определения

**Expand-Contract (также известный как Parallel Change)** — это паттерн внесения изменений в схему базы данных, который позволяет безопасно обновлять структуру данных без простоя приложения (zero-downtime). Суть метода заключается в разделении одного разрушающего изменения (например, переименования или удаления колонки) на несколько последовательных, обратно-совместимых этапов.

## Основные концепции

Процесс разделяется на три ключевые фазы:

1. **Расширение (Expand):** в базу данных добавляются новые структурные элементы (колонки, таблицы), но старые при этом сохраняются. Приложение начинает писать данные в оба места (или используются триггеры для синхронизации).
2. **Миграция (Migrate):** существующие данные постепенно переносятся из старых структур в новые. Этот процесс может выполняться фоновыми батч-заданиями.
3. **Сокращение (Contract):** после того как весь код приложения переключен на использование новых структур и данные полностью перенесены, старые (устаревшие) элементы удаляются.

Этот подход гарантирует, что на любом этапе (кроме финального удаления) можно безопасно откатить код приложения к предыдущей версии, так как старая схема остается валидной.

## Практические сценарии

### Сценарий 1: Разделение одного поля на два

Задача: разделить колонку `name` в таблице `users` на `first_name` и `last_name`.

#### Визуализация процесса

```
Фаза 1: EXPAND (Добавление)
┌────────────────────────────────────────────────────────────┐
│  Старая схема                    Новая схема               │
│                                                            │
│  users                     ┌──────────► users              │
│  ├── id                    │            ├── id             │
│  ├── name                  │            ├── name           │
│  └── email                 │            ├── email          │
│                            │            ├── first_name (new)│
│                            │            └── last_name (new) │
│                            │                              │
│                            │  Код пишет в old (name)      │
│                            │  Триггеры синхронизируют      │
└────────────────────────────────────────────────────────────┘

Фаза 2: MIGRATE (Миграция данных)
┌────────────────────────────────────────────────────────────┐
│  Обновление всех записей:                                  │
│  UPDATE users SET                                          │
│    first_name = SPLIT_PART(name, ' ', 1),                  │
│    last_name = SPLIT_PART(name, ' ', 2);                   │
└────────────────────────────────────────────────────────────┘

Фаза 3: CONTRACT (Удаление)
┌────────────────────────────────────────────────────────────┐
│  Только новая схема                                        │
│                                                            │
│  users                                                     │
│  ├── id                                                    │
│  ├── first_name                                            │
│  ├── last_name                                             │
│  └── email                                                 │
│                                                            │
│  Удаляем name и триггеры                                   │
└────────────────────────────────────────────────────────────┘
```

#### Реализация в PostgreSQL

```sql
-- Фаза 1: Расширение (Expand)
-- Добавляем новые колонки как nullable
ALTER TABLE users ADD COLUMN first_name VARCHAR(100);
ALTER TABLE users ADD COLUMN last_name VARCHAR(100);

-- Создаем функцию и триггер для обеспечения двусторонней синхронизации
CREATE OR REPLACE FUNCTION sync_user_names()
RETURNS TRIGGER AS $$
BEGIN
    -- Если запись идет в новые поля — обновляем старое
    IF NEW.first_name IS NOT NULL OR NEW.last_name IS NOT NULL THEN
        NEW.name = COALESCE(NEW.first_name, '') || ' ' || COALESCE(NEW.last_name, '');
    -- Если запись идет в старое поле — обновляем новые
    ELSIF NEW.name IS NOT NULL THEN
        NEW.first_name = SPLIT_PART(NEW.name, ' ', 1);
        NEW.last_name = SPLIT_PART(NEW.name, ' ', 2);
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER sync_user_names_trigger
BEFORE INSERT OR UPDATE ON users
FOR EACH ROW EXECUTE FUNCTION sync_user_names();

-- Фаза 2: Миграция (Migrate)
-- Выполняется постепенно для исторических данных
UPDATE users 
SET first_name = SPLIT_PART(name, ' ', 1),
    last_name = SPLIT_PART(name, ' ', 2)
WHERE first_name IS NULL;

-- Фаза 3: Сокращение (Contract)
-- Выполняется после переключения всего кода приложения на новые колонки
DROP TRIGGER sync_user_names_trigger ON users;
DROP FUNCTION sync_user_names();
ALTER TABLE users DROP COLUMN name;
```

### Сценарий 2: Rolling Update в Kubernetes

При обновлении сервиса через Rolling Update в Kubernetes старый и новый код работают параллельно. Миграция должна быть обратно-совместимой на всех этапах.

**Процесс:**

```yaml
# 1. Сначала — миграция схемы (K8s Job)
apiVersion: batch/v1
kind: Job
metadata:
  name: db-migrate
spec:
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: migrate
          image: flyway/flyway:latest
          command: ["flyway", "migrate"]
```

```yaml
# 2. Затем — Rolling Update приложения с PDB
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: my-app-pdb
spec:
  minAvailable: 1
  selector:
    matchLabels:
      app: my-app
```

Migration Job запускается **до** rolling update подов. PDB (`minAvailable: 1`) гарантирует, что при обновлении хотя бы один pod остаётся активным.

**Пример для добавления колонки:**

```sql
-- Expand: nullable — старый код её не видит и не ломается
ALTER TABLE orders ADD COLUMN discount NUMERIC(10,2);
```

```bash
# Запуск миграции как K8s Job
kubectl apply -f db-migrate-job.yaml
kubectl wait --for=condition=complete job/db-migrate

# Rolling update (старый код игнорирует колонку, новый — использует)
kubectl set image deployment/my-app my-app=my-registry/my-app:v2
```

**Contract** (DROP/переименование) выносится в следующий релиз, когда старых подов гарантированно нет в кластере.

### Инструменты версионированных миграций

| Инструмент | Язык | Особенности |
|:---|:---|:---|
| **Flyway** | Java, SQL | Версионирование по имени файла (`V1__description.sql`), `flyway migrate`/`undo`, проверки (`validate`) |
| **Liquibase** | Java, SQL, XML, YAML, JSON | Changeset с `id`+`author`, rollback per changeset, diff между БД |
| **Goose** | Go | Переносимая бинарная сборка (один файл), миграции на Go + SQL |

**Правило:** никаких `DROP COLUMN`, `RENAME COLUMN` или `ALTER COLUMN ... SET NOT NULL` без полного Expand-Contract цикла. Деструктивные изменения — только в фазе Contract, через один или несколько релизов после Expand.

## Дополнительная информация

### Рекомендации

- **Обработка NULL:** при расширении новые колонки всегда должны создаваться как `NULLABLE`, так как старый код о них ничего не знает. Ограничение `NOT NULL` добавляется только на фазе сокращения.
- **Длительность фаз:** фаза миграции может длиться от нескольких минут до нескольких дней в зависимости от объема данных. Важно мониторить лаг синхронизации.
- **Триггеры vs Приложение:** синхронизацию можно реализовать на уровне приложения (двойная запись), но триггеры в БД гарантируют целостность независимо от версии развернутого кода.

### Смежные темы

- **[Миграции баз данных: Основы](migration_basics.md)** — общие принципы и типы миграций.
- **[Типовые сценарии](scenarios.md)** — примеры применения Expand-Contract для других задач.
- **[Rolling Update в Kubernetes](../../../CI-CD/Deployment_Strategies/rolling_update.md)** — стратегия поэтапного обновления подов.

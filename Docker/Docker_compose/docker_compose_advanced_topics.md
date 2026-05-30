# Продвинутые возможности Docker Compose

## Определения

**Продвинутые возможности Docker Compose** — набор техник для управления сложными многоконтейнерными стеками, позволяющий адаптировать конфигурации под различные окружения (Dev/Stage/Prod) и минимизировать дублирование кода.

## Базовые концепции

### Интерполяция переменных

Docker Compose поддерживает подстановку переменных окружения из командной оболочки или файла `.env`.

- **Приоритет источников:**
  1. Переменные системной оболочки (shell).
  2. Файл `.env` в корне проекта.

- **Синтаксис:**
  - `${VAR}` — простая подстановка.
  - `${VAR:-default}` — использование `default`, если переменная не задана.
  - `${VAR:?error}` — вывод ошибки, если переменная отсутствует.

> **Безопасность:** Не используйте `.env` для хранения паролей в production. Для чувствительных данных применяйте [Docker Secrets](../Docker_security/secrets_management.md).

### Переопределение конфигурации

По умолчанию Docker Compose ищет и объединяет `compose.yml` и `compose.override.yml`. Это позволяет хранить базовую структуру в основном файле, а локальные правки (порты, монтирование кода) — в override-файле.

Для явного объединения нескольких файлов используется флаг `-f`:
```bash
docker compose -f compose.yml -f compose.prod.yml up -d
# → [OK] Стек запущен с применением настроек из обоих файлов
```

### Переиспользование через extends

Директива `extends` позволяет сервису наследовать параметры другого сервиса из этого же или внешнего файла.

```yaml
services:
  web:
    extends:
      file: common.yml
      service: base_web
    build: .
```

> **Примечание:** В современных конфигурациях для переиспользования внутри одного файла часто предпочитают **YAML anchors (&)** и **aliases (*)** за их наглядность.

### Интеграция с Docker Swarm (deploy)

Секция `deploy` используется для настройки ресурсов и репликации.

> **Важно:** Полная поддержка `deploy` доступна только в Docker Swarm через `docker stack deploy`. Однако `docker compose` (v2.20+) умеет обрабатывать параметры `replicas` и `resources.limits` даже в обычном режиме.

### Масштабирование сервисов

Горизонтальное масштабирование на одном хосте выполняется через флаг `--scale` или параметр `replicas`.

```bash
docker compose up -d --scale worker=3
# → Creating project_worker_2 ... done
# → Creating project_worker_3 ... done
```

## Практические сценарии

### HA-кластер PostgreSQL с Patroni

Пример реализации отказоустойчивого кластера с использованием YAML-якорей для исключения дублирования.

- **Компоненты:** etcd (DCS), HAProxy (балансировщик), Patroni (управление PostgreSQL).
- **Концепция HA:** Подробно описана в [High Availability PostgreSQL](../../Databases/PostgreSQL/Concepts/high_availability.md).

```yaml
services:
  etcd:
    image: 'bitnami/etcd:3.4'
    environment:
      - ALLOW_NONE_AUTHENTICATION=yes

  patroni1: &patroni-base
    image: 'bitnami/patroni:3.0'
    environment: &patroni-env
      - PATRONI_SCOPE=pg-cluster
      - PATRONI_ETCD_HOSTS=etcd:2379
      - PATRONI_NAME=patroni1
    volumes:
      - patroni_data1:/data/patroni1

  patroni2:
    <<: *patroni-base
    environment:
      <<: *patroni-env
      - PATRONI_NAME=patroni2
    volumes:
      - patroni_data2:/data/patroni2

volumes:
  patroni_data1:
  patroni_data2:
```

## Дополнительная информация

- **[Справочник по директивам](./docker_compose_directives.md)** — описание всех ключей `compose.yml`
- **[Примеры конфигураций](./docker_compose_file_example.md)** — готовые стеки для различных технологий
- **[Безопасное управление секретами](../Docker_security/secrets_management.md)** — использование Docker Secrets

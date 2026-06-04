# Yandex Cloud — Managed Databases

## Определения

**Managed Databases** — семейство сервисов Yandex Cloud для развёртывания и управления базами данных. Сервис берёт на себя установку, настройку, резервное копирование, обновления и мониторинг.

**Кластер БД** — группа хостов, объединённых для обеспечения отказоустойчивости, масштабирования и высокой доступности.

---

## Основные концепции

### Доступные движки СУБД

| Движок | Тип | Сценарии | Версии (2026) |
| :--- | :--- | :--- | :--- |
| **PostgreSQL** | Реляционная (OLTP) | Транзакционные нагрузки, микросервисы | 14, 15, 16, 17, 18 |
| **MySQL** | Реляционная (OLTP) | Веб-приложения, CMS | 8.0, 8.4 |
| **ClickHouse** | Колоночная (OLAP) | Аналитика, отчётность, Big Data | 23.8+, 24.8+ |
| **Redis** | Key-value (in-memory) | Кэш, сессии, очереди | 6.2, 7.0, 7.2 |
| **MongoDB** | Документная | Гибкая схема, каталоги, контент | 5.0, 6.0, 7.0 |
| **MariaDB** | Реляционная (OLTP) | Наследие MySQL, форк MySQL | 10.6, 10.11, 11.2 |
| **MSSQL** | Реляционная (OLTP) | Enterprise .NET-приложения | 2017, 2019, 2022 |

> **Важно:** PostgreSQL 10–13 прекращены (ноябрь 2025). Рекомендуется миграция на 17 или 18.

### Общие возможности

**Автоматизация:**

- Автоматические бэкапы с хранением до 30 дней.
- Point-in-Time Recovery (PITR) для PostgreSQL, MySQL, MariaDB.
- Автоматические обновления с окнами обслуживания.
- Автоматический failover мастера (PostgreSQL, MySQL).

**Безопасность:**

- Шифрование трафика (TLS).
- Аутентификация через IAM (PostgreSQL).
- Security Groups для сегментации доступа.
- Аудит событий (по запросу).

**Масштабирование:**

- Вертикальное: изменение класса ресурсов хостов.
- Горизонтальное: реплики чтения, шардирование (ClickHouse, MongoDB).
- Мульти-АЗ: размещение по зонам доступности.

**Мониторинг:**

- Встроенные дашборды в консоли YC.
- Интеграция с Yandex Monitoring.
- Экспорт метрик в Prometheus.

### Архитектура кластеров

**Single-node:**

- Один хост.
- Для разработки и тестирования.
- Минимальная стоимость.

**High-availability (HA):**

- Мастер + реплика(и).
- Автоматический failover.
- Для продакшена.

**Read replicas:**

- Мастер + реплики только для чтения.
- Масштабирование read-нагрузки.
- Для аналитики и отчётности.

---

## Практические сценарии

### PostgreSQL: создание кластера через yc CLI

```bash
# Создание PostgreSQL кластера
yc managed-postgresql cluster create \
  --name pg-main \
  --environment PRODUCTION \
  --network-id default \
  --version 17 \
  --postgresql-config-access-complexity SIMPLE \
  --host zone=ru-central1-a,subnet-id=default-ru-central1-a,assign-public-ip=false \
  --host zone=ru-central1-b,subnet-id=default-ru-central1-b,assign-public-ip=false \
  --resource-preset b2.medium \
  --disk-type network-ssd \
  --disk-size 20 \
  --database app \
  --user name=app,password=secure_password,permissions=database=app

# Проверка статуса
yc managed-postgresql cluster get --name pg-main
```

### PostgreSQL: автоматизация через Terraform

```hcl
resource "yandex_mdb_postgresql_cluster" "pg" {
  name        = "pg-main"
  environment = "PRODUCTION"
  network_id  = var.network_id

  config {
    version = "17"
    resources {
      resource_preset_id = "b2.medium"
      disk_type_id       = "network-ssd"
      disk_size          = 20
    }
  }

  host {
    zone             = "ru-central1-b"
    subnet_id        = var.subnet_id
    assign_public_ip = false
  }

  host {
    zone             = "ru-central1-a"
    subnet_id        = var.subnet_id_a
    assign_public_ip = false
  }

  database {
    name = "app"
  }

  user {
    name     = "app"
    password = var.pg_password
    permission {
      database_name = "app"
    }
  }
}
```

### MySQL: создание кластера

```bash
yc managed-mysql cluster create \
  --name mysql-main \
  --environment PRODUCTION \
  --network-id default \
  --version 8.4 \
  --host zone=ru-central1-a,subnet-id=default-ru-central1-a \
  --resource-preset b2.medium \
  --disk-type network-ssd \
  --disk-size 20 \
  --database app \
  --user name=app,password=secure_password,permissions=database=app
```

### Redis: создание кластера для кэша

```bash
yc managed-redis cluster create \
  --name redis-cache \
  --environment PRODUCTION \
  --network-id default \
  --version 7.2 \
  --host zone=ru-central1-a,subnet-id=default-ru-central1-a \
  --sharded \
  --resource-preset b2.medium \
  --disk-type network-ssd \
  --disk-size 10 \
  --config maxmemory-policy allkeys-lru \
  --config timeout 300
```

### ClickHouse: создание аналитического кластера

```bash
yc managed-clickhouse cluster create \
  --name ch-analytics \
  --environment PRODUCTION \
  --network-id default \
  --version 24.8 \
  --host zone=ru-central1-a,subnet-id=default-ru-central1-a,type=CLICKHOUSE \
  --host zone=ru-central1-a,subnet-id=default-ru-central1-a,type=ZOOKEEPER \
  --resource-preset c2.medium \
  --disk-type network-ssd \
  --disk-size 50
```

### Бэкапы и восстановление

```bash
# Список бэкапов
yc managed-postgresql backup list --cluster-name pg-main

# Восстановление на момент времени (PITR)
yc managed-postgresql cluster restore \
  --name pg-restored \
  --from-backup-id <backup_id> \
  --restore-time "2026-03-01T10:00:00Z" \
  --environment PRODUCTION

# Создание бэкапа по запросу
yc managed-postgresql backup create --cluster-name pg-main
```

### Выбор класса ресурсов

| Класс | vCPU | RAM | Сценарии |
| :--- | :--- | :--- | :--- |
| **b2.small** | 1 | 2 ГБ | Dev/Test, небольшие нагрузки |
| **b2.medium** | 2 | 4 ГБ | Продакшен начального уровня |
| **b2.large** | 4 | 8 ГБ | Средние нагрузки |
| **c2.medium** | 2 | 2 ГБ | CPU-интенсивные запросы |
| **c2.large** | 4 | 4 ГБ | Высокая вычислительная нагрузка |
| **m2.medium** | 4 | 16 ГБ | Память-интенсивные БД |

---

## Дополнительная информация

Сети и security groups для кластеров — [VPC](./VPC.md), альтернатива: БД на ВМ — [Compute Cloud](./Compute-Cloud.md), интеграция метрик БД — [Monitoring](./Monitoring/index.md), хранение бэкапов — [Storage](./Storage/index.md).

Подробные концепции СУБД: [PostgreSQL](../Databases/PostgreSQL/overview.md), [ClickHouse](../Databases/clickhouse.md), [Redis](../Databases/redis_overview.md). Подключение приложений из [Kubernetes](../Kubernetes/kubernetes_overview.md).

Безопасность: [Security Groups](./VPC.md#security-groups-группы-безопасности) для изоляции трафика, TLS для шифрования соединений, IAM-аутентификация для PostgreSQL, приватные подсети — без публичного доступа.

### Актуальные версии движков

- **PostgreSQL:** 14 (EOL ноябрь 2026), 15, 16, 17, 18. Версии 10–13 прекращены.
- **MySQL:** 8.0, 8.4.
- **Redis:** 6.2, 7.0, 7.2.
- **ClickHouse:** 23.8+, 24.8+.
- **MongoDB:** 5.0, 6.0, 7.0.
- **MariaDB:** 10.6, 10.11, 11.2.
- **MSSQL:** 2017, 2019, 2022.

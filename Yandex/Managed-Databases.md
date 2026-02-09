# Yandex Cloud DevOps - Managed Databases

## Managed Databases: выбор движка и операционные аспекты

Управляемые СУБД снимают рутину по разворачиванию, обновлению и бэкапам. Доступны кластеры PostgreSQL и MySQL (OLTP), MongoDB (документы), Redis (кэш/сессии), ClickHouse (аналитика). Важные возможности:

- Автоматические бэкапы и точка во времени (PITR) для поддерживаемых движков.
- Репликация и размещение по зонам доступности для отказоустойчивости.
- Управляемые обновления с окнами обслуживания.
- Сегментация доступа через security groups, TLS-подключения, аудит.

Минимальный пример Terraform для PostgreSQL-кластера:

```hcl
provider "yandex" {
  token     = var.yc_token
  cloud_id  = var.cloud_id
  folder_id = var.folder_id
  zone      = "ru-central1-b"
}

resource "yandex_mdb_postgresql_cluster" "pg" {
  name        = "pg-main"
  environment = "PRODUCTION"
  network_id  = var.network_id

  config {
    version = "15"
    resources {
      resource_preset_id = "b2.medium"
      disk_type_id       = "network-ssd"
      disk_size          = 20
    }
  }

  host {
    zone           = "ru-central1-b"
    subnet_id      = var.subnet_id
    assign_public_ip = false
  }

  database { name = "app" }
  user { name = "app"; password = var.pg_password }
}
```

Выбор движка диктуется профилем нагрузки: транзакционные операции — PostgreSQL/MySQL; кэш и очереди с низкой задержкой — Redis; аналитические отчеты на больших данных — ClickHouse; гибкая схема — MongoDB.

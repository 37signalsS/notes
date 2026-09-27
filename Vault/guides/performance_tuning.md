# Производительность и тюнинг Vault

## Определения

**Performance Tuning** — процесс оптимизации конфигурации Vault для достижения максимальной производительности в production-среде.

**Throughput (Пропускная способность)** — количество запросов, которые Vault может обработать за единицу времени (обычно секунду).

**Latency (Задержка)** — время, которое требуется Vault для обработки запроса (от получения запроса до отправки ответа).

**IOPS (Input/Output Operations Per Second)** — количество операций ввода-вывода в секунду. Критично для Raft-хранилища.

**Raft Log Compaction** — процесс очистки и сжатия Raft-лога для поддержания производительности.

**Cache Hit Ratio** — доля запросов, обслуженных из кэша. Высокий hit ratio снижает нагрузку на Vault.

**Connection Pooling** — механизм повторного использования соединений с БД для снижения overhead.

## Основные концепции

### Факторы, влияющие на производительность

1. **Хранилище:** SSD vs HDD, IOPS, latency
2. **Сеть:** Задержка между узлами кластера, bandwidth
3. **Конфигурация:** Размеры пулов, лимиты соединений, кэширование
4. **Нагрузка:** Количество запросов, размер секретов, сложность политик

### Оптимизируемые параметры

| Параметр | Описание | Влияние |
| :--- | :--- | :--- |
| `max_lease_ttl_seconds` | Максимальный TTL lease | Ограничивает количество активных lease |
| `default_lease_ttl_seconds` | TTL по умолчанию | Влияет на частоту ротации |
| `cache` | Размер и тип кэша | Влияет на hit ratio |
| `listener` | TCP backlog, timeouts | Влияет на обработку соединений |
| `storage` | Тип хранилища, синхронизация | Влияет на latency и throughput |

## Практические сценарии

### Сценарий 1: Оптимизация Raft-хранилища

#### Выбор хранилища

| Тип хранилища | IOPS | Latency | Рекомендация |
| :--- | :--- | :--- | :--- |
| **NVMe SSD** | 100K+ | < 1ms | Production |
| **SSD** | 50K–100K | 1–5ms | Production |
| **HDD** | 100–500 | 5–20ms | Dev/Test only |

#### Настройка systemd для оптимизации диска

```ini
# /etc/systemd/system/vault.service
[Service]
LimitNOFILE=65536
LimitMEMLOCK=infinity

# Оптимизация диска
IOWeight=1000
```

#### sysctl оптимизации

```bash
# /etc/sysctl.d/99-vault.conf
vm.max_map_count=65536
fs.file-max=100000
net.core.somaxconn=65535
net.ipv4.tcp_syncookies=0
```

### Сценарий 2: Оптимизация конфигурации сервера

#### Оптимизация listener

```hcl
listener "tcp" {
  address       = "0.0.0.0:8200"
  cluster_address = "0.0.0.0:8201"
  
  # TCP оптимизации
  tls_disable = 0
  tls_cert_file = "/etc/vault.d/tls/vault.crt"
  tls_key_file = "/etc/vault.d/tls/vault.key"
  
  # Timeouts
  read_timeout = "30s"
  write_timeout = "30s"
  idle_timeout = "5m"
}
```

#### Оптимизация lease TTL

```hcl
# server.hcl
# Короткий TTL по умолчанию для снижения нагрузки
default_lease_ttl_seconds = 2764800  # 32 дня
max_lease_ttl_seconds     = 31536000  # 365 дней

# Для высоконагруженных сред: ещё короче
# default_lease_ttl_seconds = 86400   # 1 день
# max_lease_ttl_seconds     = 604800   # 7 дней
```

### Сценарий 3: Оптимизация кэширования

#### Настройка кэша на сервере

```hcl
# server.hcl
cache {
  use_auto_auth_token = true
  
  # Размер кэша
  size = 100000  # количество записей
  
  # Персистентный кэш (BoltDB)
  persist "file" {
    path = "/var/lib/vault/cache.db"
    keep_after_import = true
    exit_on_err = true
  }
}
```

#### Мониторинг hit ratio

```promql
# Hit ratio кэша
sum(rate(vault_cache_hit[5m])) / (sum(rate(vault_cache_hit[5m])) + sum(rate(vault_cache_miss[5m])))
```

### Сценарий 4: Оптимизация для high-load

#### Разделение компонентов

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Client    │────▶│   Load      │────▶│   Vault     │
│             │     │   Balancer  │     │   Primary   │
└─────────────┘     └─────────────┘     └─────────────┘
                           │                   │
                           ▼                   ▼
                    ┌─────────────┐     ┌─────────────┐
                    │   Vault     │     │   Vault     │
                    │   Secondary │     │   Secondary │
                    └─────────────┘     └─────────────┘
```

#### Настройка Performance Standby (Enterprise)

```bash
# Включение Performance Standby
vault write -f sys/replication/performance/primary/enable
```

#### Настройка Load Balancer

```nginx
upstream vault_cluster {
    least_conn;
    server vault-0.example.com:8200 max_fails=3 fail_timeout=10s;
    server vault-1.example.com:8200 max_fails=3 fail_timeout=10s;
    server vault-2.example.com:8200 max_fails=3 fail_timeout=10s;
}

server {
    listen 8200;
    server_name vault.example.com;

    location / {
        proxy_pass https://vault_cluster;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Vault-Request true;

        # Keepalive
        proxy_http_version 1.1;
        proxy_set_header Connection "";

        # Timeouts
        proxy_connect_timeout 5s;
        proxy_send_timeout 30s;
        proxy_read_timeout 30s;
    }
}
```

### Сценарий 5: Бенчмаркинг

#### Бенчмарк запросов

```bash
# Установка hey (HTTP load generator)
go install github.com/rakyll/hey@latest

# Бенчмарк чтения секретов
hey -n 10000 -c 100 -m GET \
    -H "X-Vault-Token: $VAULT_TOKEN" \
    https://vault.example.com:8200/v1/secret/data/myapp/config

# Бенчмарк записи секретов
hey -n 1000 -c 10 -m POST \
    -H "X-Vault-Token: $VAULT_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"data": {"password": "test"}}' \
    https://vault.example.com:8200/v1/secret/data/myapp/config
```

#### Интерпретация результатов

| Метрика | Хорошо | Плохо |
| :--- | :--- | :--- |
| **Requests/sec** | > 1000 | < 100 |
| **Latency p50** | < 10ms | > 100ms |
| **Latency p95** | < 50ms | > 500ms |
| **Latency p99** | < 100ms | > 1000ms |
| **Error rate** | < 0.1% | > 1% |

### Сценарий 6: Диагностика проблем производительности

#### Проверка Raft-лога

```bash
# Информация о Raft
vault operator raft info
# → Raft Log
# →   Last Log Index: 12345
# →   Last Log Term: 3
# →   Commit Index: 12340
# →   Applied Index: 12340

# Проверка размера Raft-лога
du -sh /opt/vault/data/raft/
```

#### Проверка метрик

```bash
# Запрос метрик
curl -s https://vault.example.com:8200/v1/sys/metrics | grep vault_raft

# Ключевые метрики
vault_raft_commit_time
vault_raft_apply
vault_raft_replication
```

#### Анализ audit логов

```bash
# Медленные запросы
jq 'select(.request.duration > 1000) | .request.path, .request.duration' /var/log/vault/audit.log
```

## Лучшие практики

1. **SSD/NVMe:** Используйте SSD или NVMe для Raft-хранилища. HDD непригодны для production.
2. **IOPS:** Обеспечьте достаточное количество IOPS (минимум 10K для production).
3. **Сеть:** Низколатентная сеть между узлами (< 5ms). Избегайте cross-AZ трафика.
4. **Кэширование:** Включите кэширование на сервере и используйте Vault Agent с persistent cache.
5. **Load Balancer:** Настройте LB с least_conn и keepalive.
6. **Мониторинг:** Отслеживайте `vault_raft_commit_time` и `vault_raft_apply`.
7. **Benchmark:** Регулярно проводите бенчмарки для оценки производительности.

## Ограничения и известные проблемы

- **Raft и HDD:** Raft не подходит для HDD из-за высокой latency. Используйте SSD/NVMe.
- **Write throughput:** Vault имеет ограниченный write throughput (≈ 100–500 записей/сек на узел). Для high-write сред используйте Performance Standby.
- **Large secrets:** Секреты > 1MB снижают производительность. Используйте external storage для больших данных.
- **Complex policies:** Сложные ACL-политики с множеством путей увеличивают latency.

## Дополнительная информация

*   **[Производительность и репликация](./performance_and_replication.md)** — HA-кластер и stale reads.
*   **[Установка Vault](../guides/vault_installation.md)** — требования к hardware.
*   **[Мониторинг и алертинг](./monitoring_and_alerting.md)** — метрики и дашборды.
*   [Официальная документация по производительности](https://developer.hashicorp.com/vault/docs/enterprise/performance)

# RabbitMQ: Справочник конфигурации

## Определения

- **rabbitmq.conf:** Основной конфигурационный файл RabbitMQ. Формат — sysctl-like (ключ = значение). Все параметры задаются в этом файле.
- **advanced.config:** Дополнительный конфигурационный файл для Erlang-настроек ( networking, SSL, кластеризация). Используется реже, чем `rabbitmq.conf`.
- **environment:** Конфигурация Erlang-окружения (переменные среды). Доступна через `rabbitmqctl environment`.
- **Default Value:** Значение параметра по умолчанию, если он не задан в конфигурации.
- **Hot Reload:** Изменение параметров без перезапуска брокера (для некоторых параметров).

## Структура каталогов

```
/etc/rabbitmq/
├── rabbitmq.conf         # Основной конфигурационный файл
├── advanced.config       # Erlang конфигурация (опционально)
├── enabled_plugins      # Список включенных плагинов
└── tls/                 # Сертификаты TLS
    ├── ca.pem
    ├── server.pem
    └── server.key
```

## Основные параметры rabbitmq.conf

### Сетевые настройки

```ini
# === AMQP слушатели ===

# TCP слушатель (AMQP 0-9-1)
listeners.tcp.default = 5672

# Несколько слушателей
listeners.tcp.1 = 5672
listeners.tcp.2 = 5673

# IPv6 слушатель
listeners.tcp.local = 127.0.0.1:5672
listeners.tcp.ipv6 = [::1]:5672

# TLS слушатель
listeners.ssl.default = 5671

# === Inter-node ===

# Порт inter-node коммуникации
# (автоматически через epmd)
cluster_formation.peer_discovery_backend = classic_config
cluster_formation.classic_config.nodes.1 = rabbit@node1
cluster_formation.classic_config.nodes.2 = rabbit@node2

# === Management UI ===

# HTTP Management UI
management.tcp.port = 15672
management.tcp.ip = 127.0.0.1

# HTTPS Management UI
management.ssl.port = 15671
management.ssl.cacertfile = /etc/rabbitmq/tls/ca.pem
management.ssl.certfile = /etc/rabbitmq/tls/server.pem
management.ssl.keyfile = /etc/rabbitmq/tls/server.key

# === Prometheus ===

# Prometheus метрики
prometheus.tcp.port = 15692
prometheus.return_per_object_metrics = false
```

### Память и ресурсы

```ini
# === Память ===

# Высокий порог памяти (процент от RAM)
# По умолчанию: 0.4 (40% RAM)
vm_memory_high_watermark.relative = 0.4

# Абсолютное значение высокого порога
vm_memory_high_watermark.absolute = 2GB

# Порог памяти для signaling processes
vm_memory_high_watermark_paging_ratio = 0.5

# === Диск ===

# Минимальное свободное место на диске
# По умолчанию: 1GB
disk_free_limit.absolute = 2GB

# Процент от RAM
disk_free_limit.relative = 1.0

# === Erlang-процессы ===

# Максимальное количество Erlang-процессов
# По умолчанию: ~1048576
process_limit = 2000000

# === Файловые дескрипторы ===

# Лимит открытых файлов (через systemd)
# В /etc/systemd/system/rabbitmq-server.service.d/limits.conf
[Service]
LimitNOFILE=65536
```

### Логирование

```ini
# === Консольное логирование ===

log.console = true
log.console.level = info

# === Файловое логирование ===

log.file = true
log.file.level = info
log.file.path = /var/log/rabbitmq/rabbit@node1.log
log.file.rotation.date = $D0
log.file.rotation.size = 104857600
log.file.rotation.count = 5

# === Лог-обменник ===

log.exchange = true
log.exchange.type = direct
log.exchange.key = rabbitmq.logs
log.exchange.durable = true
```

### Кластеризация

```ini
# === Peer Discovery ===

# Классический (static) peer discovery
cluster_formation.peer_discovery_backend = classic_config
cluster_formation.classic_config.nodes.1 = rabbit@node1
cluster_formation.classic_config.nodes.2 = rabbit@node2
cluster_formation.classic_config.nodes.3 = rabbit@node3

# DNS peer discovery
cluster_formation.peer_discovery_backend = dns
cluster_formation.dns.host = rabbitmq.example.com

# === Khepri (metadata store) ===

# Включение Khepri (RabbitMQ 4.0+)
metadata_store = khepri

# === Partition Handling ===

# Обработка сетевых разбиений
# autoheal — автоматическое восстановление
# pause_minority — остановка при меньшинстве
# ignore — игнорирование
cluster_partition_handling = autoheal

# Или
cluster_partition_handling = pause_minority
```

### Очереди

```ini
# === Quorum Queues ===

# Минимальное количество реплик
quorum.queue.replica_factor = 3

# === Stream Queues ===

# Размер сегмента Stream
stream.segment.bytes = 4096

# Время жизни сегмента
stream.max_age = 1h

# === Lazy Queues (deprecated) ===

# lazy-очереди deprecated в RabbitMQ 3.12+
# Используйте quorum queues вместо этого
```

### Консьюмеры

```ini
# === Prefetch ===

# Глобальный prefetch count (по умолчанию: 0 — без ограничений)
# Рекомендуется: 10-100 в зависимости от сценария
consumer_timeout = 1800000  # 30 минут (мс)

# === Heartbeat ===

# Heartbeat timeout (секунды)
# По умолчанию: 60
heartbeat = 60

# Для клиентов
# В connection parameters: heartbeat=60
```

### Безопасность

```ini
# === Аутентификация ===

# Механизмы аутентификации
auth_mechanisms.1 = PLAIN
auth_mechanisms.2 = AMQPLAIN

# SASL MECHANISMS
# EXTERNAL — для TLS сертификатов
# OAUTHBEARER — для OAuth 2.0

# === LDAP ===

auth_ldap.enabled = true
auth_ldap.servers.1 = ldap://ldap.example.com
auth_ldap.user_dn_pattern = ou=users,dc=example,dc=com
auth_ldap.bind_dn = cn=admin,dc=example,dc=com
auth_ldap.bind_password = password
auth_ldap.use_ssl = true
auth_ldap.port = 636

# === OAuth 2.0 ===

auth_mechanisms.1 = OAUTHBEARER
auth_oauth2.jwks_url = https://auth.example.com/.well-known/jwks.json
auth_oauth2.issuer = https://auth.example.com
auth_oauth2.audience = rabbitmq

# === ACL ===

# Включить ACL
authorization.enable = true
```

### TLS

```ini
# === TLS ===

# Версии TLS
ssl_options.versions.1 = tlsv1.2
ssl_options.versions.2 = tlsv1.3

# Сертификаты сервера
ssl_options.cacertfile = /etc/rabbitmq/tls/ca.pem
ssl_options.certfile = /etc/rabbitmq/tls/server.pem
ssl_options.keyfile = /etc/rabbitmq/tls/server.key

# Верификация клиента (mTLS)
ssl_options.verify = verify_peer
ssl_options.fail_if_no_peer_cert = true

# Inter-node TLS
ssl_options.inter_node_tls = true
```

### Прочее

```ini
# === Имя узла ===

# Имя ноды (автоматически)
# node_name = rabbit@hostname

# === Временная зона ===

# Временная зона для логов
# tz = UTC

# === Reverse DNS ===

# Включить reverse DNS lookup
# reverse_dns_lookup = true

# === Collector ===

# Сбор метрик для Prometheus
# collector_metrics = queue_metrics
```

## Advanced.config (Erlang)

```erlang
%% /etc/rabbitmq/advanced.config

[
  %% Networking
  {rabbit, [
    {tcp_listeners, [5672]},
    {ssl_listeners, [5671]},
    
    %% Handshake timeout
    {handshake_timeout, 30000},
    
    %% Channel operation timeout
    {channel_operation_timeout, 60000},
    
    %% Heartbeat
    {heartbeat, 60},
    
    %% Frame max
    {frame_max, 131072},
    
    %% Channel max
    {channel_max, 2048}
  ]},
  
  %% Mnesia (deprecated в RabbitMQ 4.0+)
  {mnesia, [
    {dir, "/var/lib/rabbitmq/mnesia"}
  ]},
  
  %% Logging
  {lager, [
    {handlers, [
      {lager_console_backend, [{level, info}]},
      {lager_file_backend, [
        {file, "/var/log/rabbitmq/rabbit.log"},
        {level, info},
        {size, 104857600},
        {date, "$D0"},
        {count, 5}
      ]}
    ]}
  ]}
].
```

## Шпаргалка: типичные сценарии

### Production конфигурация

```ini
# /etc/rabbitmq/rabbitmq.conf

# === Сеть ===
listeners.tcp.default = 5672
management.tcp.port = 15672
management.tcp.ip = 0.0.0.0
prometheus.tcp.port = 15692

# === Память ===
vm_memory_high_watermark.relative = 0.4
disk_free_limit.absolute = 2GB

# === Кластер ===
cluster_formation.peer_discovery_backend = classic_config
cluster_formation.classic_config.nodes.1 = rabbit@node1
cluster_formation.classic_config.nodes.2 = rabbit@node2
cluster_formation.classic_config.nodes.3 = rabbit@node3
cluster_partition_handling = autoheal

# === Логирование ===
log.console = true
log.console.level = info
log.file = true
log.file.level = info

# === TLS ===
listeners.ssl.default = 5671
ssl_options.cacertfile = /etc/rabbitmq/tls/ca.pem
ssl_options.certfile = /etc/rabbitmq/tls/server.pem
ssl_options.keyfile = /etc/rabbitmq/tls/server.key
ssl_options.verify = verify_peer
ssl_options.fail_if_no_peer_cert = true

# === Консьюмеры ===
heartbeat = 60
consumer_timeout = 1800000
```

### Development конфигурация

```ini
# /etc/rabbitmq/rabbitmq.conf

listeners.tcp.default = 5672
management.tcp.port = 15672
management.tcp.ip = 127.0.0.1

vm_memory_high_watermark.relative = 0.6
disk_free_limit.absolute = 1GB

log.console = true
log.console.level = debug
```

## Проверка конфигурации

```bash
# Просмотр текущей конфигурации
sudo rabbitmqctl environment

# Проверка конкретного параметра
sudo rabbitmqctl eval 'application:get_env(rabbit, vm_memory_high_watermark).'

# Валидация конфигурационного файла
# (проверка синтаксиса перед запуском)
sudo rabbitmq-server -rabbit vm_memory_high_watermark 0.5

# Просмотр всех параметров
sudo rabbitmqctl eval 'application:get_all_env(rabbit).'
```

## Лучшие практики

1. **Используйте `rabbitmq.conf`** — основной файл конфигурации.
2. **Не редактируйте `advanced.config`** — только для специфических Erlang-настроек.
3. **Храните конфигурацию в VCS** — git для отслеживания изменений.
4. **Тестируйте изменения** — сначала в staging, затем в production.
5. **Проверяйте `cluster_status`** после изменений.
6. **Используйте минимум параметров** — доверяйте дефолтам.
7. **Документируйте нестандартные настройки** — комментарии в конфиге.
8. **Регулярно проверяйте устаревшие параметры** — обновления могут менять дефолты.

## Дополнительная информация

### См. также

- **[Установка и кластеризация](./installation_and_clustering.md)** — кластерные настройки.
- **[Безопасность](./security.md)** — TLS, аутентификация.
- **[Мониторинг и алертинг](./monitoring_and_alerting.md)** — Prometheus конфигурация.
- **[Плагины](./plugins.md)** — включение плагинов.

# Другие экспортеры Prometheus: Полный каталог

## Определения

**Другие экспортеры** — систематизированный перечень агентов и встроенных механизмов мониторинга для различных технологических стеков. Экспортеры преобразуют метрики целевых систем в формат Prometheus.

В современных реалиях 2026 года подходы к сбору метрик делятся на три типа:
1.  **Внешние экспортеры (Exporters):** Отдельные процессы для систем без встроенной поддержки (MySQL, PostgreSQL).
2.  **Нативный экспорт (Native Support):** Встроенные эндпоинты `/metrics` в самом ПО (RabbitMQ, Angie, Triton).
3.  **Универсальные коллекторы:** Использование [OpenTelemetry Collector](../../OpenTelemetry/opentelemetry_overview.md) как единого шлюза.

## Основные концепции

### Категоризация

Экспортеры сгруппированы по типам наблюдаемых систем. Каждый раздел содержит информацию о портах, репозиториях и ссылки на детальные руководства в базе знаний.

**Связанные темы:** [Обзор экспортеров](./overview.md), [Принцип работы экспортера](./overview.md#принцип-работы-экспортера).

---

## Практические сценарии: Каталог экспортеров

### 1. Базы данных (Databases)

| Экспортер | Описание | Репозиторий | Порт | Ссылка на SSoT |
| :--- | :--- | :--- | :--- | :--- |
| **mysqld_exporter** | Мониторинг MySQL/MariaDB | [GitHub](https://github.com/prometheus/mysqld_exporter) | 9104 | **[MySQL](../../Databases/MySQL/overview.md)** |
| **postgres_exporter** | Мониторинг PostgreSQL | [GitHub](https://github.com/prometheus-community/postgres_exporter) | 9187 | **[PostgreSQL](../../Databases/PostgreSQL/overview.md)** |
| **redis_exporter** | Мониторинг Redis (Кэш и очереди) | [GitHub](https://github.com/oliver006/redis_exporter) | 9121 | **[Redis](../../Databases/redis_overview.md)** |
| **mongodb_exporter** | Мониторинг MongoDB | [GitHub](https://github.com/percona/mongodb_exporter) | 9216 | **[MongoDB](../../Databases/MongoDB/mongodb.md)** |
| **elasticsearch_exporter** | Мониторинг Elasticsearch | [GitHub](https://github.com/prometheus-community/elasticsearch_exporter) | 9114 | **[Elasticsearch](../../ELK_Stack/Elasticsearch/elasticsearch_overview.md)** |
| **consul_exporter** | Мониторинг KV и Health Checks Consul | [GitHub](https://github.com/prometheus/consul_exporter) | 9107 | **[Consul](../../Consul/consul_overview.md)** |
| **memcached_exporter** | Мониторинг Memcached | [GitHub](https://github.com/prometheus/memcached_exporter) | 9150 | **[Memcached](../../Databases/memcached_overview.md)** |
| **cassandra_exporter** | Мониторинг Apache Cassandra | [GitHub](https://github.com/criteo/cassandra_exporter) | 9116 | — |
| **clickhouse_exporter** | Мониторинг ClickHouse | [GitHub](https://github.com/ClickHouse/clickhouse_exporter) | 9116 | **[ClickHouse](../../Databases/ClickHouse/overview.md)** |

### 2. Веб-серверы и L7 Прокси

| Экспортер | Описание | Репозиторий | Порт | Ссылка на SSoT |
| :--- | :--- | :--- | :--- | :--- |
| **nginx-prometheus-exporter** | Мониторинг Nginx (через stub_status) | [GitHub](https://github.com/nginxinc/nginx-prometheus-exporter) | 9113 | **[Nginx](../../WebServers/Nginx/Core/nginx_overview.md)** |
| **angie (native)** | Нативный экспорт метрик Angie | — | 80/443 | **[Angie](../../WebServers/Angie/angie_overview.md)** |
| **apache_exporter** | Мониторинг Apache HTTPD | [GitHub](https://github.com/Lusitaniae/apache_exporter) | 9117 | **[Apache](../../WebServers/Apache/apache_overview.md)** |
| **haproxy_exporter** | Мониторинг HAProxy (v2.0+ нативно) | [GitHub](https://github.com/prometheus/haproxy_exporter) | 9101 | **[HAProxy](../../WebServers/haproxy_overview.md)** |
| **traefik (native)** | Встроенный мониторинг Traefik | — | 8080 | **[Traefik](../../WebServers/Traefik/traefik_overview.md)** |
| **envoy-exporter** | Мониторинг Envoy Proxy | [GitHub](https://github.com/prometheus/envoy_exporter) | 9102 | **[Envoy](../../Service_Mesh/service_mesh_concepts.md)** |

### 3. Брокеры сообщений (Message Brokers)

| Экспортер | Описание | Репозиторий | Порт | Ссылка на SSoT |
| :--- | :--- | :--- | :--- | :--- |
| **rabbitmq_exporter** | Мониторинг RabbitMQ (нативно в v3.8+) | [GitHub](https://github.com/kbudde/rabbitmq_exporter) | 9419 | **[RabbitMQ](../../Kafka/rabbitmq_vs_kafka.md)** |
| **kafka_exporter** | Мониторинг Kafka (очереди, консьюмеры) | [GitHub](https://github.com/danielqsj/kafka_exporter) | 9308 | **[Kafka](../../Kafka/kafka_for_monitoring.md)** |
| **nats_exporter** | Мониторинг NATS брокера | [GitHub](https://github.com/nats-io/prometheus-nats-exporter) | 7777 | — |

### 4. Искусственный интеллект и GPU (AI/ML) — Новое в 2026

| Экспортер | Описание | Репозиторий | Порт |
| :--- | :--- | :--- | :--- |
| **NVIDIA DCGM Exporter** | Метрики GPU: утилизация, VRAM, NVLink | [GitHub](https://github.com/NVIDIA/dcgm-exporter) | 9400 |
| **Triton (native)** | Метрики инференса NVIDIA Triton Server | — | 8002 |
| **AMD ROCm Exporter** | Мониторинг ускорителей AMD | [GitHub](https://github.com/ROCm/prometheus-exporter) | 9000 |

### 5. Облачные платформы и Виртуализация

| Экспортер | Описание | Репозиторий | Порт |
| :--- | :--- | :--- | :--- |
| **yandex_exporter** | Мониторинг Yandex Cloud | [GitHub](https://github.com/yandex-cloud/prometheus-exporter) | 9100 |
| **openstack_exporter** | Мониторинг инфраструктуры OpenStack | [GitHub](https://github.com/openstack/exporter) | 9119 |
| **vmware_exporter** | Мониторинг vSphere/ESXi | [GitHub](https://github.com/pryorda/vmware_exporter) | 9271 |
| **cloudwatch_exporter** | Сбор метрик из AWS CloudWatch | [GitHub](https://github.com/prometheus/cloudwatch_exporter) | 9106 |

### 6. Системы хранения и Сеть

| Экспортер | Описание | Репозиторий | Порт |
| :--- | :--- | :--- | :--- |
| **ceph_exporter** | Мониторинг Ceph кластера | [GitHub](https://github.com/digitalocean/ceph_exporter) | 9128 |
| **snmp_exporter** | Мониторинг сетевых устройств (SNMP) | [GitHub](https://github.com/prometheus/snmp_exporter) | 9116 |
| **bind_exporter** | Мониторинг DNS сервиса BIND | [GitHub](https://github.com/prometheus-community/bind_exporter) | 9119 |
| **ipmi_exporter** | Мониторинг "железа" через IPMI | [GitHub](https://github.com/prometheus-community/ipmi_exporter) | 9290 |

### 7. Операционные системы и Контейнеры

| Экспортер | Описание | Ссылка на SSoT | Порт |
| :--- | :--- | :--- | :--- |
| **node_exporter** | Мониторинг Linux систем | **[Node Exporter](./node_exporter.md)** | 9100 |
| **windows_exporter** | Мониторинг Windows Server | [GitHub](https://github.com/prometheus-community/windows_exporter) | 9182 |
| **cAdvisor** | Метрики Docker-контейнеров | **[cAdvisor](./cadvisor.md)** | 8080 |
| **kube-state-metrics** | Статус объектов Kubernetes | [GitHub](https://github.com/kubernetes/kube-state-metrics) | 8080 |

### 8. Специализированные инструменты

| Экспортер | Описание | Репозиторий | Порт |
| :--- | :--- | :--- | :--- |
| **blackbox_exporter** | Мониторинг доступности HTTP/TCP | **[Blackbox Exporter](./blackbox/blackbox_exporter_overview.md)** | 9115 |
| **process_exporter** | Детальный мониторинг групп процессов | [GitHub](https://github.com/ncabatoff/process-exporter) | 9256 |
| **json_exporter** | Парсинг произвольных JSON API | [GitHub](https://github.com/prometheus-community/json_exporter) | 9117 |
| **sql_exporter** | Выполнение SQL-запросов для метрик | [GitHub](https://github.com/prometheus-community/sql_exporter) | 9116 |
| **php-fpm_exporter** | Мониторинг PHP-FPM статуса | [GitHub](https://github.com/hipages/php-fpm_exporter) | 9253 |

---

## Дополнительная информация

### Reliability Score: 10
Каталог актуализирован на июль 2026 года. Включены современные AI-инструменты и подтверждена нативная поддержка в RabbitMQ, Angie и HAProxy.

### Поиск и расширяемость
*   **Textfile Collector:** Для простых bash-скриптов используйте [Textfile Collector](./extensibility/textfile_collector.md).
*   **Свой экспортер:** Для разработки на Go см. [написание кастомных экспортеров](./extensibility/custom_exporters.md).
*   **Реестр сообщества:** Полный список доступен на [Prometheus.io](https://prometheus.io/docs/instrumenting/exporters/).

### Связанные темы
*   [Обзор экспортеров](./overview.md) — принцип работы и архитектура.
*   [Service Discovery и Relabeling](../service_discovery_and_relabeling.md) — автоматизация сбора.
*   [Безопасность экспортеров](./overview.md#безопасность-экспортеров) — TLS и аутентификация.

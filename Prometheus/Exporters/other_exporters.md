# Другие экспортеры Prometheus: Полный каталог

## Определения

**Другие экспортеры** — систематизированный перечень агентов и встроенных механизмов мониторинга для различных технологических стеков. Они преобразуют метрики целевых систем (баз данных, веб-серверов, очередей) в формат Prometheus.

В современных реалиях 2026 года подходы к сбору метрик делятся на три типа:
1.  **Внешние экспортеры (Standalone/Sidecar):** Отдельные процессы для систем без встроенной поддержки (MySQL, PostgreSQL, Linux).
2.  **Нативный экспорт (Native Support):** Встроенные эндпоинты `/metrics` в самом ПО. Это предпочтительный метод, не требующий дополнительных агентов (RabbitMQ, Angie, Traefik).
3.  **Универсальные коллекторы:** Использование [OpenTelemetry Collector](../../OpenTelemetry/opentelemetry_overview.md) как единого шлюза для трансляции логов и метрик.

**См. также:** [Обзор экспортеров](./overview.md), [Принципы работы экспортера](./overview.md#принцип-работы-экспортера).

## Основные концепции

### Категоризация

Каталог разбит по типам целевых систем. Для каждой системы указаны:
*   Рекомендуемый инструмент скрапинга.
*   Тип (нативный или внешний).
*   Стандартный порт (важно для настройки `scrape_configs` и Service Discovery).
*   Ссылка на профильную SSoT-статью в базе знаний (если применимо).

---

## Практические сценарии: Каталог экспортеров

### 1. Базы данных (Databases)

| Экспортер | Описание | Тип | Порт | Ссылка на SSoT |
| :--- | :--- | :--- | :--- | :--- |
| **mysqld_exporter** | MySQL/MariaDB. Требует юзера с GRANT PROCESS. | Внешний | 9104 | **[MySQL](../../Databases/MySQL/overview.md)** |
| **postgres_exporter** | PostgreSQL. Анализ таблиц `pg_stat_*`. | Внешний | 9187 | **[PostgreSQL](../../Databases/PostgreSQL/overview.md)** |
| **redis_exporter** | Redis. Поддерживает сбор по нескольким URI. | Внешний | 9121 | **[Redis](../../Databases/redis_overview.md)** |
| **mongodb_exporter** | MongoDB. Настройка через Percona PMM. | Внешний | 9216 | **[MongoDB](../../Databases/MongoDB/mongodb.md)** |
| **elasticsearch_exporter** | Elasticsearch. Состояние кластера и индексов. | Внешний | 9114 | **[Elasticsearch](../../ELK_Stack/Elasticsearch/elasticsearch_overview.md)** |
| **consul_exporter** | Consul. Health Checks, лидерство, KV. | Внешний | 9107 | **[Consul](../../Consul/consul_overview.md)** |
| **clickhouse_exporter** | ClickHouse. (В CH также есть нативный эндпоинт). | Внешний | 9116 | **[ClickHouse](../../Databases/ClickHouse/overview.md)** |

### 2. Веб-серверы и L7 Прокси

| Экспортер | Описание | Тип | Порт | Ссылка на SSoT |
| :--- | :--- | :--- | :--- | :--- |
| **Angie (нативно)** | Встроенный модуль `prometheus_zone`. | Нативный | 80/443 | **[Angie](../../WebServers/Angie/angie_overview.md)** |
| **Traefik (нативно)** | Мониторинг Gateway API, Ingress. | Нативный | 8080 | **[Traefik](../../WebServers/Traefik/traefik_overview.md)** |
| **nginx-prometheus-exporter** | Nginx OSS. Парсит страницу `stub_status`. | Внешний | 9113 | **[Nginx](../../WebServers/Nginx/Core/nginx_overview.md)** |
| **apache_exporter** | Apache HTTPD. Парсит `/server-status`. | Внешний | 9117 | **[Apache](../../WebServers/Apache/apache_overview.md)** |
| **haproxy_exporter** | HAProxy. (В v2.0+ есть нативный экспорт). | Внешний | 9101 | **[HAProxy](../../WebServers/haproxy_overview.md)** |
| **envoy-exporter** | Envoy Proxy (Service Mesh). | Внешний | 9102 | **[Envoy](../../Service_Mesh/service_mesh_concepts.md)** |

### 3. Брокеры сообщений (Message Brokers)

| Экспортер | Описание | Тип | Порт | Ссылка на SSoT |
| :--- | :--- | :--- | :--- | :--- |
| **RabbitMQ (нативно)** | Плагин `rabbitmq_prometheus` (включен в v3.8+). | Нативный | 15692 | **[RabbitMQ](../../Kafka/rabbitmq_vs_kafka.md)** |
| **kafka_exporter** | Kafka. Задержки консьюмеров (lag), партиции. | Внешний | 9308 | **[Kafka](../../Kafka/kafka_for_monitoring.md)** |

### 4. Искусственный интеллект и GPU (AI/ML)

Мониторинг инфраструктуры машинного обучения стал критичным в 2025-2026 годах.

| Экспортер | Описание | Репозиторий / Тип | Порт |
| :--- | :--- | :--- | :--- |
| **NVIDIA DCGM Exporter** | Метрики GPU: утилизация, VRAM, энергопотребление. | Внешний (NVIDIA) | 9400 |
| **Triton (нативно)** | Метрики инференса NVIDIA Triton Inference Server. | Нативный | 8002 |
| **AMD ROCm Exporter** | Мониторинг ускорителей AMD (MI250/MI300). | Внешний | 9000 |

### 5. Облачные платформы и Виртуализация

| Экспортер | Описание | Порт | Ссылка |
| :--- | :--- | :--- | :--- |
| **yandex_exporter** | Сбор метрик Yandex Cloud (Compute, MDB) API. | 9100 | [GitHub](https://github.com/yandex-cloud/prometheus-exporter) |
| **vmware_exporter** | Мониторинг vSphere/ESXi. | 9271 | [GitHub](https://github.com/pryorda/vmware_exporter) |
| **cloudwatch_exporter** | Мост к метрикам AWS CloudWatch. | 9106 | [GitHub](https://github.com/prometheus/cloudwatch_exporter) |

### 6. Системы хранения и Аппаратное обеспечение

| Экспортер | Описание | Ссылка на SSoT | Порт |
| :--- | :--- | :--- | :--- |
| **node_exporter** | Мониторинг Linux (CPU, RAM, Disks). | **[Node Exporter](./node_exporter.md)** | 9100 |
| **cAdvisor** | Мониторинг контейнеров (Docker/K8s). | **[cAdvisor](./cadvisor.md)** | 8080 |
| **ceph_exporter** | Мониторинг Ceph кластера и OSD. | — | 9128 |
| **ipmi_exporter** | Мониторинг BMC, кулеров, питания серверов. | — | 9290 |
| **snmp_exporter** | Опрос коммутаторов, ИБП (Multi-Target паттерн). | — | 9116 |

### 7. Специализированные и "Blackbox" инструменты

| Экспортер | Описание | Ссылка на SSoT | Порт |
| :--- | :--- | :--- | :--- |
| **blackbox_exporter** | Проверка доступности (HTTP, TCP, DNS, ICMP). | **[Blackbox Exporter](./blackbox/blackbox_exporter_overview.md)** | 9115 |
| **process_exporter** | Детальный мониторинг по конкретным именам процессов. | — | 9256 |
| **json_exporter** | Парсинг произвольных JSON API ответов в метрики. | — | 9117 |
| **sql_exporter** | Периодическое выполнение кастомных SQL-запросов. | — | 9116 |

## Дополнительная информация

### Поиск и расширяемость

Если требуемой системы нет в каталоге:
1.  **Реестр сообщества:** Проверьте официальный список поддерживаемых портов и экспортеров на [Prometheus.io](https://prometheus.io/docs/instrumenting/exporters/).
2.  **Скрипты:** Для простых разовых проверок используйте bash-скрипты в связке с [Textfile Collector](./extensibility/textfile_collector.md).
3.  **Собственная разработка:** Архитектурные паттерны создания агентов на Go описаны в статье [Создание собственных экспортеров](./extensibility/custom_exporters.md).

### См. также

*   [Обзор экспортеров](./overview.md) — принцип работы и безопасность (TLS/Auth).
*   [Service Discovery и Relabeling](../service_discovery_and_relabeling.md) — автоматизация сбора метрик с большого количества агентов.

# Другие экспортеры Prometheus

## Определения

**Другие экспортеры** — каталог дополнительных экспортеров для мониторинга баз данных, веб-серверов, брокеров сообщений, облачных платформ, систем хранения, сетевых устройств, контейнеров и приложений. Полный список доступен в [official exporters](https://prometheus.io/docs/instrumenting/exporters/) и [community exporters](https://prometheus.io/docs/instrumenting/exporters/#community-exporters).

## Базовые концепции

### Категоризация экспортеров

Экспортеры сгруппированы по категориям в зависимости от типа monitored системы. Каждый экспортер собирает метрики целевой системы и преобразует их в формат Prometheus.

**Связанные темы:** [Принцип работы экспортера](./overview.md#принцип-работы-экспортера), [Выбор экспортера](./overview.md#выбор-экспортера-для-задачи)

## Практические сценарии

### Базы данных

| Экспортер | Описание | Репозиторий | Порт |
| :--- | :--- | :--- | :--- |
| **mysqld_exporter** | Мониторинг MySQL/MariaDB | [GitHub](https://github.com/prometheus/mysqld_exporter) | 9104 |
| **postgres_exporter** | Мониторинг PostgreSQL | [GitHub](https://github.com/prometheus-community/postgres_exporter) | 9187 |
| **redis_exporter** | Мониторинг Redis | [GitHub](https://github.com/oliver006/redis_exporter) | 9121 |
| **mongodb_exporter** | Мониторинг MongoDB | [GitHub](https://github.com/percona/mongodb_exporter) | 9216 |
| **elasticsearch_exporter** | Мониторинг Elasticsearch | [GitHub](https://github.com/prometheus-community/elasticsearch_exporter) | 9114 |
| **consul_exporter** | Мониторинг Consul | [GitHub](https://github.com/prometheus/consul_exporter) | 9107 |
| **memcached_exporter** | Мониторинг Memcached | [GitHub](https://github.com/prometheus/memcached_exporter) | 9150 |
| **cassandra_exporter** | Мониторинг Cassandra | [GitHub](https://github.com/criteo/cassandra_exporter) | 9116 |

**Связанные темы:** [MySQL](../../Databases/MySQL/overview.md), [PostgreSQL](../../Databases/PostgreSQL/overview.md), [Redis](../../Databases/redis_overview.md), [Elasticsearch](../../ELK_Stack/Elasticsearch/elasticsearch_overview.md)

### Веб-серверы и прокси

| Экспортер | Описание | Репозиторий | Порт |
| :--- | :--- | :--- | :--- |
| **nginx-prometheus-exporter** | Мониторинг Nginx | [GitHub](https://github.com/nginxinc/nginx-prometheus-exporter) | 9113 |
| **nginx-vts-exporter** | Мониторинг Nginx VTS module | [GitHub](https://github.com/hnlq715/nginx-vts-exporter) | 9115 |
| **apache_exporter** | Мониторинг Apache | [GitHub](https://github.com/Lusitaniae/apache_exporter) | 9117 |
| **haproxy_exporter** | Мониторинг HAProxy | [GitHub](https://github.com/prometheus/haproxy_exporter) | 9101 |
| **traefik_exporter** | Мониторинг Traefik | [GitHub](https://github.com/maxwo/traefik_exporter) | 9899 |
| **envoy-exporter** | Мониторинг Envoy | [GitHub](https://github.com/prometheus/envoy_exporter) | 9102 |

### Брокеры сообщений

| Экспортер | Описание | Репозиторий | Порт |
| :--- | :--- | :--- | :--- |
| **rabbitmq_exporter** | Мониторинг RabbitMQ | [GitHub](https://github.com/kbudde/rabbitmq_exporter) | 9419 |
| **kafka_exporter** | Мониторинг Kafka | [GitHub](https://github.com/danielqsj/kafka_exporter) | 9308 |
| **nats_exporter** | Мониторинг NATS | [GitHub](https://github.com/nats-io/prometheus-nats-exporter) | 7777 |

> Примечание: `redis_exporter` также может использоваться для мониторинга Redis как брокера сообщений (см. раздел [Базы данных](#базы-данных)).

**Связанные темы:** [Kafka](../../Kafka/kafka_for_monitoring.md), [RabbitMQ](../../Kafka/rabbitmq_vs_kafka.md)

### Облачные платформы

> Примечание: Для локальной аренды используйте openstack_exporter или прямые экспортеры систем хранения.

| Экспортер | Описание | Репозиторий | Порт |
| :--- | :--- | :--- | :--- |
| **yandex_exporter** | Мониторинг Yandex Cloud | [GitHub](https://github.com/yandex-cloud/prometheus-exporter) | 9100 |
| **openstack_exporter** | Мониторинг OpenStack | [GitHub](https://github.com/openstack/exporter) | 9119 |
| **vmware_exporter** | Мониторинг vSphere | [GitHub](https://github.com/pryorda/vmware_exporter) | 9271 |

### Системы хранения

| Экспортер | Описание | Репозиторий | Порт |
| :--- | :--- | :--- | :--- |
| **ceph_exporter** | Мониторинг Ceph | [GitHub](https://github.com/digitalocean/ceph_exporter) | 9128 |
| **gluster_exporter** | Мониторинг GlusterFS | [GitHub](https://github.com/aojea/gluster_exporter) | 9118 |
| **freenas_exporter** | Мониторинг FreeNAS | [GitHub](https://github.com/klarasystems/freenas-exporter) | 9100 |

### Сетевые устройства

| Экспортер | Описание | Репозиторий | Порт |
| :--- | :--- | :--- | :--- |
| **snmp_exporter** | Мониторинг через SNMP | [GitHub](https://github.com/prometheus/snmp_exporter) | 9116 |
| **ipmi_exporter** | Мониторинг через IPMI | [GitHub](https://github.com/prometheus-community/ipmi_exporter) | 9290 |
| **bind_exporter** | Мониторинг DNS (BIND) | [GitHub](https://github.com/prometheus-community/bind_exporter) | 9119 |

### Операционные системы

| Экспортер | Описание | Репозиторий | Порт |
| :--- | :--- | :--- | :--- |
| **node_exporter** | Мониторинг Linux | [node_exporter](./node_exporter.md) | 9100 |
| **windows_exporter** | Мониторинг Windows (ex wmi_exporter) | [GitHub](https://github.com/prometheus-community/windows_exporter) | 9182 |
| **darwin_exporter** | Мониторинг macOS | [GitHub](https://github.com/prometheus-community/darwin_exporter) | 9100 |
| **freebsd_exporter** | Мониторинг FreeBSD | [GitHub](https://github.com/prometheus/freebsd_exporter) | 9100 |

### Контейнеры и оркестрация

| Экспортер | Описание | Репозиторий | Порт |
| :--- | :--- | :--- | :--- |
| **cAdvisor** | Мониторинг Docker-контейнеров | [cadvisor](./cadvisor.md) | 8080 |
| **kube-state-metrics** | Мониторинг Kubernetes objects | [GitHub](https://github.com/kubernetes/kube-state-metrics) | 8080 |
| **docker_exporter** | Мониторинг Docker Engine | [GitHub](https://github.com/prometheus/prometheus/tree/main/documentation/examples/docker-compose-alerts) | 9323 |

**Связанные темы:** [Docker](../../Docker/docker_overview.md), [Kubernetes](../../Kubernetes/kubernetes_overview.md)

### Приложения и сервисы

| Экспортер | Описание | Репозиторий | Порт |
| :--- | :--- | :--- | :--- |
| **gitlab_exporter** | Мониторинг GitLab | [GitHub](https://github.com/feiskyer/gitlab-exporter) | 9127 |
| **github_exporter** | Мониторинг GitHub API | [GitHub](https://github.com/prometheus-community/github_exporter) | 9120 |
| **jira_exporter** | Мониторинг Jira | [GitHub](https://github.com/prometheus-community/jira_exporter) | 9121 |
| **sonarqube_exporter** | Мониторинг SonarQube | [GitHub](https://github.com/witekio/sonarqube-exporter) | 9119 |
| **vault_exporter** | Мониторинг HashiCorp Vault | [GitHub](https://github.com/prometheus-community/vault_exporter) | 9102 |

### Специализированные экспортеры

| Экспортер | Описание | Репозиторий | Порт |
| :--- | :--- | :--- | :--- |
| **1c_exporter** | Мониторинг 1С | [GitHub](https://github.com/1c-syntax/1c-exporter) | 9100 |
| **php-fpm_exporter** | Мониторинг PHP-FPM | [GitHub](https://github.com/hipages/php-fpm_exporter) | 9253 |
| **process_exporter** | Мониторинг процессов | [GitHub](https://github.com/ncabatoff/process-exporter) | 9256 |
| **json_exporter** | Мониторинг JSON API | [GitHub](https://github.com/prometheus-community/json_exporter) | 9117 |
| **sql_exporter** | Мониторинг SQL баз данных | [GitHub](https://github.com/prometheus-community/sql_exporter) | 9116 |

## Дополнительная информация

### Поиск экспортеров

Поиск подходящего экспортера следует начинать с [official exporters](https://prometheus.io/docs/instrumenting/exporters/) и [community exporters](https://github.com/search?q=prometheus+exporter). Также можно выполнить поиск по [GitHub](https://github.com/search?q=prometheus+exporter).

### Написание своего экспортера

Если подходящий экспортер не найден, его можно написать самостоятельно. Доступны [Textfile Collector](./extensibility/custom_exporters.md) для простых сценариев через внешние скрипты или [написание кастомных экспортеров](./extensibility/custom_exporters.md) на Go.

### Связанные темы

[Exporters Overview](./overview.md), [Service Discovery и Relabeling](../service_discovery_and_relabeling.md), [Конфигурация Prometheus](../configuration.md)

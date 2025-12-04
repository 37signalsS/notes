# Концепции высокой доступности (High Availability) PostgreSQL

Высокая доступность (High Availability, HA) для PostgreSQL означает, что база данных продолжает функционировать даже при частичных сбоях системы. Это достигается за счет избыточности и автоматизации процессов переключения (failover) и восстановления.

## Автоматическая отработка отказа (Automatic Failover)

В контексте физической репликации, ручное переключение реплики на мастер (`PROMOTE`) в случае сбоя требует оперативного вмешательства администратора. Для минимизации простоя и предотвращения проблем, таких как "split-brain", используются специализированные системы управления кластером, обеспечивающие автоматическую отработку отказа.

### Patroni

**Patroni** — это open-source решение, которое предоставляет шаблон для создания отказоустойчивых кластеров PostgreSQL. Он не является менеджером репликации как таковым, а скорее системой, которая автоматизирует управление кластером PostgreSQL, используя распределенное хранилище конфигурации (DCS) для координации.

**Ключевые особенности Patroni:**
*   **Автоматическое переключение при сбое (Automatic Failover):** Patroni непрерывно отслеживает состояние ведущего узла (мастера). Если мастер становится недоступным, Patroni автоматически выбирает наиболее подходящую реплику и повышает ее до нового ведущего узла.
*   **Распределенное хранилище конфигурации (DCS):** Для координации действий между узлами и хранения состояния кластера (кто является мастером, какие есть реплики) Patroni использует такие DCS, как `etcd`, `Consul` или `ZooKeeper`.
*   **Простота развертывания:** Patroni хорошо подходит для развертывания в контейнерных средах. Практические примеры приведены ниже. Для производственных сред в Kubernetes рекомендуется использовать [оператор CloudNativePG](../Operations/kubernetes_deployment.md).
*   **Восстановление бывшего мастера:** Когда бывший мастер снова становится доступным, Patroni может автоматически настроить его как реплику к новому мастеру, используя `pg_rewind` или базовое резервное копирование (`pg_basebackup`).

## Предотвращение "Split-Brain"

Проблема "Split-Brain" возникает, когда из-за проблем с сетью или координацией два узла кластера независимо друг от друга начинают считать себя мастерами. Это приводит к расхождению данных и нарушению целостности. Системы, такие как Patroni, активно предотвращают эту ситуацию, обеспечивая, что в кластере всегда есть только один мастер.

## Роль балансировщиков нагрузки

В высокодоступных конфигурациях часто используются балансировщики нагрузки (например, HAProxy, PgBouncer).
*   **HAProxy:** Может выступать в роли "умного" прокси, направляя запросы на запись только к текущему мастеру, а запросы на чтение — как к мастеру, так и к доступным репликам. Он постоянно отслеживает состояние узлов кластера.
*   **PgBouncer:** Легковесный пулер соединений, который может использоваться для снижения нагрузки на PostgreSQL, а также для маршрутизации соединений к активному мастеру или репликам.

Использование Patroni в связке с балансировщиком нагрузки позволяет создать полностью автоматизированный и [масштабируемый](./scaling.md) кластер PostgreSQL. Основой для этого служат механизмы [физической репликации](./replication.md).

## Практические сценарии развертывания в Docker

В дополнение к теоретическим концепциям, рассмотрим конкретные примеры развертывания отказоустойчивых кластеров PostgreSQL с использованием Docker Compose.

### Репликация с Bitnami RepManager

Образы Bitnami с `repmgr` упрощают настройку кластера с физической репликацией.

**Преимущества образов Bitnami:**
*   **Non-root контейнеры:** Повышают безопасность.
*   **Регулярные обновления:** Оперативно включают исправления уязвимостей.
*   **Удобство для кластеров:** Значительно упрощают настройку репликации и HA.

**Пример `docker-compose.replication.yml`:**
```yaml
version: '3.8'

services:
  postgresql-primary:
    image: bitnami/postgresql-repmgr:15
    restart: always
    environment:
      - POSTGRESQL_USERNAME=postgres
      - POSTGRESQL_PASSWORD=mysecretpassword
      - POSTGRESQL_DATABASE=myapp
      - REPMGR_PASSWORD=repmgrpassword
      - REPMGR_PRIMARY_HOST=postgresql-primary
      - REPMGR_PARTNER_NODES=postgresql-primary,postgresql-replica
      - REPMGR_NODE_NAME=postgresql-primary
    volumes:
      - pg_primary_data:/bitnami/postgresql
    networks:
      - repl-net

  postgresql-replica:
    image: bitnami/postgresql-repmgr:15
    restart: always
    environment:
      - POSTGRESQL_USERNAME=postgres
      - POSTGRESQL_PASSWORD=mysecretpassword
      - POSTGRESQL_DATABASE=myapp
      - REPMGR_PASSWORD=repmgrpassword
      - REPMGR_PRIMARY_HOST=postgresql-primary
      - REPMGR_PARTNER_NODES=postgresql-primary,postgresql-replica
      - REPMGR_NODE_NAME=postgresql-replica
    volumes:
      - pg_replica_data:/bitnami/postgresql
    networks:
      - repl-net
    depends_on:
      - postgresql-primary

volumes:
  pg_primary_data:
  pg_replica_data:

networks:
  repl-net:
```
В этом примере `repmgr` автоматически настраивает `postgresql-replica` как реплику `postgresql-primary` и обеспечивает автоматическое переключение при сбое.

### Отказоустойчивый кластер с Patroni

Patroni — это более продвинутый инструмент для создания HA-кластеров.

**Пример `docker-compose.patroni.yml`:**
```yaml
version: '3.8'

services:
  etcd:
    image: bitnami/etcd:3.5
    environment:
      - ALLOW_NONE_AUTHENTICATION=yes
      - ETCD_ADVERTISE_CLIENT_URLS=http://etcd:2379
    networks:
      - patroni-net

  haproxy:
    image: haproxy:2.9
    volumes:
      - ./haproxy.cfg:/usr/local/etc/haproxy/haproxy.cfg:ro
    ports:
      - '5000:5000' # Порт для записи (мастер)
      - '5001:5001' # Порт для чтения (реплики)
      - '8008:8008' # Статистика HAProxy
    networks:
      - patroni-net
    depends_on:
      - patroni1
      - patroni2

  patroni1:
    image: bitnami/postgresql:15 # Используйте совместимую с Patroni версию
    restart: always
    environment:
      - PATRONI_NAME=patroni1
      - PATRONI_SCOPE=my-cluster
      - PATRONI_ETCD_HOST=etcd
      - POSTGRESQL_USERNAME=postgres
      - POSTGRESQL_PASSWORD=mysecretpassword
    volumes:
      - patroni1_data:/bitnami/postgresql
    networks:
      - patroni-net
    depends_on:
      - etcd

  patroni2:
    image: bitnami/postgresql:15
    restart: always
    environment:
      - PATRONI_NAME=patroni2
      - PATRONI_SCOPE=my-cluster
      - PATRONI_ETCD_HOST=etcd
      - POSTGRESQL_USERNAME=postgres
      - POSTGRESQL_PASSWORD=mysecretpassword
    volumes:
      - patroni2_data:/bitnami/postgresql
    networks:
      - patroni-net
    depends_on:
      - etcd

volumes:
  patroni1_data:
  patroni2_data:
  
networks:
  patroni-net:
```
*В данном примере `etcd` используется как распределенное хранилище для управления состоянием кластера, а `HAProxy` выступает в роли балансировщика, направляя запросы на текущий мастер-узел.*

---
[PostgreSQL: Обзор](../overview.md)
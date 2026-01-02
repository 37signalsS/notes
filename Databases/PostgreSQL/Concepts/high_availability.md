# Концепции высокой доступности (High Availability) для PostgreSQL

## 1. Определения

*   **Высокая доступность (High Availability, HA):** Способность системы продолжать функционировать даже при частичных сбоях (например, отказе одного из серверов) за счет избыточности и автоматизации.
*   **Отработка отказа (Failover):** Процесс автоматического переключения на резервный компонент (например, реплику) при сбое основного.
*   **Split-Brain:** Критическая ошибка в кластерных системах, при которой из-за нарушения связи два узла одновременно решают, что они являются главными (мастерами), что приводит к рассинхронизации данных.

## 2. Основные концепции

1.  **Фундамент — репликация:** Основой любой HA-стратегии является наличие как минимум одной синхронизированной резервной копии сервера (реплики), готовой взять на себя нагрузку.
    > См. подробнее: **[Типы репликации в PostgreSQL](./replication.md)**.

2.  **Проблема — автоматизация:** В ручном режиме при сбое мастера администратор должен сам подключиться к реплике и "повысить" ее до нового мастера (`pg_ctl promote`). Это создает простой и несет риск человеческой ошибки.

3.  **Решение — менеджеры кластера:** Для минимизации простоя и предотвращения проблемы "Split-Brain" используются специализированные системы управления кластером, которые обеспечивают **автоматическую отработку отказа (Automatic Failover)**.

## 3. Практические сценарии и инструменты

### Patroni
**Patroni** — это open-source решение, которое предоставляет шаблон для создания отказоустойчивых кластеров PostgreSQL. Он автоматизирует управление жизненным циклом кластера, используя внешнее распределенное хранилище конфигурации (DCS) для координации.

*   **Ключевые особенности Patroni:**
    *   **Автоматический Failover:** Непрерывно отслеживает состояние мастера. Если мастер становится недоступным, Patroni автоматически выбирает лучшую реплику и повышает ее до нового мастера, обеспечивая целостность данных и предотвращая "Split-Brain".
    *   **Распределенное хранилище (DCS):** Для хранения состояния кластера (кто мастер, какие есть реплики) Patroni использует `etcd`, `Consul` или `ZooKeeper`.
    *   **Восстановление бывшего мастера:** Когда отказавший мастер возвращается в строй, Patroni автоматически настраивает его как реплику к новому мастеру, используя `pg_rewind`.
*   **Развертывание в Kubernetes:** Для производственных сред в Kubernetes рекомендуется использовать специализированные операторы, такие как [CloudNativePG](../Operations/kubernetes_deployment.md), которые часто используют принципы Patroni под капотом.

### Роль балансировщиков нагрузки
В HA-конфигурациях приложения не должны подключаться напрямую к конкретному узлу БД. Вместо этого используется балансировщик нагрузки:
*   **HAProxy:** Может выступать в роли "умного" прокси, направляя запросы на запись только к текущему мастеру, а запросы на чтение — как к мастеру, так и к доступным репликам. Он постоянно отслеживает состояние узлов кластера.
*   **PgBouncer:** Легковесный пулер соединений, который может использоваться для снижения нагрузки на PostgreSQL, а также для маршрутизации соединений к активному мастеру или репликам.

Использование Patroni в связке с балансировщиком нагрузки позволяет создать полностью автоматизированный и [масштабируемый](./scaling.md) кластер PostgreSQL. Основой для этого служат механизмы [физической репликации](./replication.md).

### Примеры развертывания в Docker

#### Репликация с Bitnami RepManager
Образы Bitnami с `repmgr` (альтернатива Patroni) упрощают настройку кластера с физической репликацией.

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

#### Отказоустойчивый кластер с Patroni и HAProxy
Это более продвинутая и надежная конфигурация.

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
*В данном примере `etcd` используется как DCS, а `HAProxy` — как единая точка входа для приложений.*

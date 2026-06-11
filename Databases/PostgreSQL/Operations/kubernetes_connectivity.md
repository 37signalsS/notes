# Сетевая связность Kubernetes и PostgreSQL в многозонных средах

## Определения

* **Topology Aware Routing (Topology Aware Hints)** — механизм Kubernetes, позволяющий направлять трафик на эндпоинты, находящиеся в той же зоне доступности (Availability Zone), что и клиент.
* **Cross-Zone Traffic** — сетевой трафик между разными зонами доступности. Обычно является платным и вносит дополнительные задержки (latency).
* **Connection Pooler (PgBouncer/Odyssey)** — промежуточный слой между приложением и БД для управления пулом соединений.
* **Locality-based Load Balancing** — стратегия балансировки трафика, приоритезирующая локальные ресурсы для минимизации задержек.

## Базовые концепции

При работе в многозонных облачных средах (AWS, GCP, Azure, Yandex Cloud) основная цель сетевой настройки — минимизировать межзонный трафик для снижения затрат и задержек.

### Проблема задержек и стоимости

Запросы из Kubernetes (зона A) к PostgreSQL (зона B) проходят через сетевую фабрику облака, что добавляет 1-2 мс задержки и увеличивает стоимость сетевого трафика. В высоконагруженных системах это может стать узким местом.

### Стратегии маршрутизации

1. **Topology Aware Routing (Native K8s)**:
   При включении этого механизма для Service, Kubernetes пытается отправить запрос на Pod в той же зоне. Это идеально работает для реплик PostgreSQL, распределенных по зонам.

2. **PgBouncer как локальный прокси**:
   Развертывание PgBouncer в каждой зоне (или как sidecar-контейнер). Приложение всегда подключается к `localhost` или локальному сервису PgBouncer, а пулер уже управляет соединением с БД (возможно, межзонным, если мастер находится в другой зоне).

3. **Service per Zone**:
   Создание отдельных Kubernetes Services для каждой зоны (например, `db-zone-a`, `db-zone-b`), использующих селекторы по меткам узлов (`topology.kubernetes.io/zone`).

## Практические сценарии

### Сценарий 1: Использование Topology Aware Routing

Для активации локальной маршрутизации необходимо добавить аннотацию к Service:

```yaml
apiVersion: v1
kind: Service
metadata:
  name: postgres-replica
  annotations:
    service.kubernetes.io/topology-mode: Auto # Ранее TopologyAwareHints
spec:
  selector:
    app: postgres
    role: replica
  ports:
    - protocol: TCP
      port: 5432
```

*Требование: Эндпоинты (поды БД) должны иметь информацию о топологии (обычно добавляется облачным контроллером).*

### Сценарий 2: Доступ к Managed БД (RDS/Cloud SQL) из конкретной зоны

Если база находится вне Kubernetes, можно использовать **Headless Service** с ручным указанием эндпоинтов по зонам.

```yaml
apiVersion: v1
kind: Service
metadata:
  name: external-db-zone-a
spec:
  clusterIP: None
  ports:
    - port: 5432
---
apiVersion: v1
kind: Endpoints
metadata:
  name: external-db-zone-a
subsets:
  - addresses:
      - ip: 10.0.1.5 # IP базы в зоне A
    ports:
      - port: 5432
```

### Сценарий 3: CloudNativePG и межзонная репликация

Оператор **CloudNativePG** автоматически управляет сервисами `-rw` (для записи) и `-ro` (для чтения). Для оптимизации чтения из локальной зоны:

1. Используйте `topologySpreadConstraints` в манифесте `Cluster`, чтобы распределить поды по зонам.
2. Для приложений используйте чтение через локальный PgBouncer или настройте Service Mesh (Istio) с приоритетом Locality Load Balancing.

### Сценарий 4: Доступ через Cloud SQL Auth Proxy (GCP/Yandex)

При использовании sidecar-контейнера с Auth Proxy:

* Приложение подключается к `127.0.0.1:5432`.
* Proxy устанавливает зашифрованное соединение с API БД.
* Если Proxy запущен в зоне A, он будет пытаться минимизировать задержки, если облачный провайдер поддерживает zone-awareness на уровне балансировщика сервиса.

## Дополнительная информация

### Рекомендации по выбору

* **Для чтения (Read-only)**: Всегда используйте `Topology Aware Routing` или локальные реплики.
* **Для записи (Read-Write)**: Межзонный трафик неизбежен, если Primary-узел находится в другой зоне. Минимизируйте количество соединений через PgBouncer.
* **Мониторинг**: Отслеживайте метрику `cross_zone_traffic_bytes` (если доступна в облаке) для контроля затрат.

### Смотрите также

* **[PostgreSQL в Kubernetes](./kubernetes_deployment.md)** — развертывание через операторы.
* **[Affinity и TopologySpreadConstraints](../../../Kubernetes/Scheduling/affinity.md)** — управление размещением подов по зонам.
* **[Типы сервисов Kubernetes](../../../Kubernetes/Networking/Service/service_types_summary.md)** — обзор сетевых абстракций.

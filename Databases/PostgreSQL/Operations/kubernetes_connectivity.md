# Сетевая связность Kubernetes и PostgreSQL в многозонных средах

## Определения

* **Topology Aware Routing** (ранее Topology Aware Hints) — механизм Kubernetes (стабилен с v1.27), позволяющий направлять трафик на эндпоинты в той же зоне доступности (AZ), что и клиент.
* **Service Internal Traffic Policy** — параметр `spec.internalTrafficPolicy`, определяющий, может ли трафик выходить за пределы узла. Значение `Local` заставляет K8s искать эндпоинт строго на той же ноде.
* **Cross-Zone Traffic** — сетевой трафик между разными зонами доступности. Обычно является платным и вносит дополнительные задержки (latency).
* **Connection Pooler (PgBouncer/Odyssey)** — промежуточный слой между приложением и БД для управления пулом соединений и снижения нагрузки на backend.
* **Locality-based Load Balancing** — стратегия балансировки трафика, приоритезирующая локальные ресурсы для минимизации задержек.
* **mTLS (Mutual TLS)** — взаимная аутентификация через сертификаты. В K8s используется для шифрования трафика между приложением и БД (Pod-to-Pod) без изменения кода приложения.
* **Global Load Balancer (GSLB)** — механизм балансировки между разными кластерами или регионами (например, через ExternalDNS + Route53/Cloudflare).

## Базовые концепции

При работе в многозонных кластерах (AWS, GCP, Azure, Yandex Cloud) критически важно минимизировать межзонный трафик. Это решает две задачи: снижение стоимости владения инфраструктурой и уменьшение задержек.

### Задержки и производительность

| Тип соединения | Типичная задержка (Latency) | Влияние на PostgreSQL |
|:---|:---|:---|
| Внутри одной ноды | < 0.1 мс | Идеально для высокоинтенсивных транзакций |
| Между нодами (одна AZ) | 0.2 – 0.5 мс | Стандарт для production-среды |
| Межзонный трафик (Cross-AZ) | 1.0 – 2.5 мс | Заметное замедление при большом количестве commit |

### Безопасность и шифрование (Zero Trust)

В современных инфраструктурах (2026+) сетевой периметр кластера считается небезопасным.
1. **CloudNativePG Native TLS**: Оператор умеет автоматически выпускать сертификаты для клиентских подключений.
2. **Service Mesh (Istio/Cilium)**: Прозрачное шифрование трафика. *Важно: Sidecar-прокси (Envoy) может вносить до 0.5 мс задержки.*
3. **NetworkPolicies**: Обязательное ограничение доступа. Разрешайте входящий трафик на порт 5432 только из Namespaces с приложениями.

### Основные стратегии оптимизации

1. **Topology Aware Routing (Native K8s)**:
   Kubernetes через EndpointSlice контроллер отслеживает топологию и при значении `Auto` пытается удержать трафик в рамках зоны. Это особенно эффективно для реплик, распределенных по AZ.

2. **Internal Traffic Policy (Node Local)**:
   Если PgBouncer запущен как Sidecar или DaemonSet, использование `internalTrafficPolicy: Local` гарантирует, что приложение соединится с пулером без лишних сетевых прыжков.

3. **PgBouncer как зональный прокси**:
   Развертывание отдельного Deployment PgBouncer в каждой зоне. Приложение из зоны A обращается к `pgbouncer-zone-a.svc.cluster.local`.

## Практические сценарии

### Сценарий 1: Активация Topology Aware Routing

Для нативной балансировки с учетом зон добавьте аннотацию к Service:

```yaml
apiVersion: v1
kind: Service
metadata:
  name: postgres-replica
  annotations:
    service.kubernetes.io/topology-mode: Auto
spec:
  selector:
    app: postgres
    role: replica
  ports:
    - protocol: TCP
      port: 5432
```

*Важно: Для корректной работы количество эндпоинтов в каждой зоне должно быть пропорционально ресурсам нод в этой зоне, иначе K8s может отключить подсказки (hints).*

### Сценарий 2: Доступ к внешним БД (RDS / Cloud SQL)

Для работы с базами вне кластера используйте **ExternalName** (для DNS-имен) или **Headless Service** с ручными эндпоинтами.

**Вариант с ExternalName:**
```yaml
apiVersion: v1
kind: Service
metadata:
  name: external-db
spec:
  type: ExternalName
  externalName: my-db.cluster-cxyz.eu-central-1.rds.amazonaws.com
```

### Сценарий 3: Сетевая топология в CloudNativePG

Оператор **CloudNativePG** автоматически создает несколько сервисов. Для их оптимизации можно добавить аннотации через `spec.serviceTemplate`:

```yaml
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata:
  name: pg-prod
spec:
  instances: 3
  serviceTemplate:
    metadata:
      annotations:
        service.kubernetes.io/topology-mode: Auto
  # ... остальная конфигурация
```

**Типы сервисов CNPG:**
* `<name>-rw`: Всегда ведет на Primary.
* `<name>-ro`: Только на реплики (идеально для `topology-mode: Auto`).
* `<name>-r`: На любые инстансы, включая Primary.

### Сценарий 4: Принудительная локальность (Sidecar PgBouncer)

Если вы используете PgBouncer в каждом поде с приложением (Sidecar) или на каждой ноде, настройте сервис так, чтобы трафик не уходил на другие узлы:

```yaml
apiVersion: v1
kind: Service
metadata:
  name: pgbouncer-local
spec:
  internalTrafficPolicy: Local
  selector:
    app: pgbouncer
  ports:
    - port: 5432

### Сценарий 5: mTLS с cert-manager (CloudNativePG)

Для использования корпоративного CA вместо самоподписанных сертификатов оператора:

```yaml
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata:
  name: pg-secure
spec:
  instances: 3
  certificates:
    issuerRef:
      name: my-vault-issuer # Ссылка на ClusterIssuer (cert-manager)
      kind: ClusterIssuer
      group: cert-manager.io
```
*Результат: Все сертификаты для узлов и клиентов будут автоматически выпускаться и ротироваться через cert-manager.*

### Сценарий 6: Multi-cluster / Hybrid Connectivity (ExternalDNS)

Для доступа к БД из другого кластера или извне через FQDN:

```yaml
apiVersion: v1
kind: Service
metadata:
  name: postgres-public
  annotations:
    external-dns.alpha.kubernetes.io/hostname: "db-prod.example.com"
spec:
  type: LoadBalancer
  selector:
    cnpg.io/cluster: pg-prod
    role: primary
  ports:
    - port: 5432
```
*Внимание: Публикация БД через LoadBalancer требует обязательного шифрования и ограничения доступа по IP (loadBalancerSourceRanges).*

## Поиск и устранение неисправностей (SRE)

| Ошибка | Возможная причина | Диагностика |
|:---|:---|:---|
| `Connection timeout` | NetworkPolicy или Firewall | `kubectl exec -it app-pod -- nc -zv db-service 5432` |
| `SSL error: decryption failed` | Ошибка mTLS / Sidecar | Проверить логи `istio-proxy` или статус `Certificate` в cert-manager |
| `Unknown host` | Проблемы DNS / CoreDNS | `kubectl exec -it app-pod -- nslookup db-service.namespace.svc.cluster.local` |
| `Slow commits` | Высокий Cross-AZ Latency | `ping` между нодами разных зон. Проверить `topology-mode: Auto`. Подробнее: **[Cross-zone traffic и задержки](../../../Networking/Troubleshooting/cross-zone-latency.md)** |

## Дополнительная информация

### Рекомендации по выбору

* **Для чтения (Select)**: Используйте сервис реплик (`-ro`) с `topology-mode: Auto`. Это обеспечит чтение из "своей" зоны.
* **Для записи (Insert/Update)**: Межзонный трафик к Primary неизбежен, если он в другой AZ. Используйте PgBouncer для уменьшения количества открытых сессий через сеть.
* **Observability**: Используйте `Istio` или другой Service Mesh для визуализации Cross-AZ трафика и автоматической настройки Locality Failover.

### Смотрите также

* **[PostgreSQL в Kubernetes](./kubernetes_deployment.md)** — развертывание через CloudNativePG.
* **[Наблюдаемость PostgreSQL](./observability.md)** — настройка мониторинга и трассировки.
* **[Предотвращение истечения SSL](../../../Kubernetes/Operations/ssl_expiration_prevention.md)** — настройка cert-manager для Kubernetes.
* **[Affinity и TopologySpreadConstraints](../../../Kubernetes/Scheduling/affinity.md)** — управление распределением подов.
* **[Основные концепции Service Mesh](../../../Service_Mesh/service_mesh_concepts.md)** — управление East-West трафиком и mTLS.
* **[Безопасная установка СУБД](../../installation_security.md)** — общее руководство по закалке PostgreSQL.

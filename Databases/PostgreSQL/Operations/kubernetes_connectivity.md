# Сетевая связность Kubernetes и PostgreSQL в многозонных средах

## Определения

* **Topology Aware Routing** (ранее Topology Aware Hints) — механизм Kubernetes (стабилен с v1.27), позволяющий направлять трафик на эндпоинты в той же зоне доступности (AZ), что и клиент. Реализуется через аннотацию `service.kubernetes.io/topology-mode: Auto`.
* **trafficDistribution: PreferClose** — новое поле в спецификации Service (стабильно с v1.31), обеспечивающее более мягкое и предсказуемое управление трафиком внутри зоны. В отличие от Hints, оно не отключается автоматически при небольшом дисбалансе нагрузки, что делает его стандартом для БД в 2026 году.
* **Service Internal Traffic Policy** — параметр `spec.internalTrafficPolicy`, определяющий, может ли трафик выходить за пределы узла. Значение `Local` заставляет K8s искать эндпоинт строго на той же ноде, исключая сетевой переход даже внутри одной AZ.
* **Cross-Zone Traffic** — сетевой трафик между разными зонами доступности. Обычно является платным и вносит дополнительные задержки (latency). В облачных средах (AWS, GCP, Azure, Yandex Cloud) минимизация этого трафика критична для экономики и производительности.
* **Connection Pooler (PgBouncer/Odyssey)** — промежуточный слой между приложением и БД для управления пулом соединений и снижения нагрузки на backend. Позволяет переиспользовать сессии и сглаживать пики нагрузки.
* **Locality-based Load Balancing** — стратегия балансировки трафика, приоритезирующая локальные ресурсы (внутри узла или зоны) для минимизации задержек.
* **eBPF (Extended Berkeley Packet Filter)** — технология в ядре Linux (используется в Cilium), позволяющая ускорять сетевые операции, перехватывая пакеты на уровне сокетов и минуя стек `iptables/kube-proxy`.
* **mTLS (Mutual TLS)** — взаимная аутентификация через сертификаты. В K8s используется для шифрования трафика между приложением и БД (Pod-to-Pod) без изменения кода приложения. В 2026 году часто реализуется прозрачно через Service Mesh (Ambient Mesh) или Cilium.
* **Global Load Balancer (GSLB)** — механизм балансировки между разными кластерами или регионами (например, через ExternalDNS + Route53/Cloudflare или Cilium ClusterMesh).

## Базовые концепции

При работе в многозонных кластерах критически важно минимизировать межзонный трафик. Это решает две задачи: снижение стоимости владения инфраструктурой и уменьшение задержек.

### Задержки и производительность (PG 18 Context)

С внедрением **PostgreSQL 18** и нативного асинхронного ввода-вывода (**AIO**), влияние сетевых задержек на пропускную способность снизилось, но задержка конкретных транзакций (Latency) остается определяющей для UX.

| Тип соединения | Типичная задержка (Latency) | Влияние на PostgreSQL |
|:---|:---|:---|
| Внутри одной ноды (Unix Socket) | < 0.05 мс | Идеально для высокоинтенсивных транзакций |
| Внутри одной ноды (TCP) | < 0.1 мс | Минимальные накладные расходы сетевого стека |
| Между нодами (одна AZ) | 0.2 – 0.5 мс | Стандарт для production-среды |
| Межзонный трафик (Cross-AZ) | 1.0 – 2.5 мс | Заметное замедление при большом количестве commit |
| Межрегиональный трафик | 10 – 60 мс | Только для асинхронной репликации |

### Безопасность и шифрование (Zero Trust)

В современных инфраструктурах (2026+) сетевой периметр кластера считается небезопасным.
1. **CloudNativePG Native TLS**: Оператор умеет автоматически выпускать сертификаты для клиентских подключений.
2. **Service Mesh (Istio/Cilium)**: Прозрачное шифрование трафика. *Важно: Sidecar-прокси (Envoy) может вносить до 0.5 мс задержки. Sidecar-less решения (Ambient/eBPF) снижают этот оверхед до < 0.1 мс.*
3. **NetworkPolicies**: Обязательное ограничение доступа. Разрешайте входящий трафик на порт 5432 только из Namespaces с приложениями, используя Identity-подход (Cilium Identity).

### Основные стратегии оптимизации

1. **Topology Aware Routing (Native K8s)**:
   Kubernetes через EndpointSlice контроллер отслеживает топологию и при значении `Auto` пытается удержать трафик в рамках зоны. Это особенно эффективно для реплик, распределенных по AZ. С версии 1.31 рекомендуется использовать `trafficDistribution: PreferClose`.

2. **Internal Traffic Policy (Node Local)**:
   Если PgBouncer запущен как Sidecar или DaemonSet, использование `internalTrafficPolicy: Local` гарантирует, что приложение соединится с пулером без лишних сетевых прыжков.

3. **PgBouncer как зональный прокси**:
   Развертывание отдельного Deployment PgBouncer в каждой зоне. Приложение из зоны A обращается к `pgbouncer-zone-a.svc.cluster.local`.

4. **Акселерация через eBPF (Cilium)**:
   Использование Cilium для Socket-level балансировки позволяет перенаправлять трафик минуя инкапсуляцию, что дает производительность, близкую к Unix Sockets.

## Практические сценарии

### Сценарий 1: Активация зональной балансировки (Topology Aware Routing)

Для нативной балансировки с учетом зон добавьте аннотацию к Service (или используйте `trafficDistribution` для K8s 1.31+):

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
  # Доступно с v1.31 для более предсказуемого поведения
  # trafficDistribution: PreferClose
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

**Вариант с Headless Service и ручными эндпоинтами:**
```yaml
apiVersion: v1
kind: Service
metadata:
  name: legacy-db
spec:
  clusterIP: None
  ports:
    - port: 5432
---
apiVersion: v1
kind: Endpoints
metadata:
  name: legacy-db
subsets:
  - addresses:
      - ip: 192.168.1.50
    ports:
      - port: 5432
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
```

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

### Сценарий 6: Multi-cluster / Hybrid Connectivity (ExternalDNS & ClusterMesh)

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
*Внимание: Публикация БД через LoadBalancer требует обязательного шифрования и ограничения доступа по IP (loadBalancerSourceRanges). В 2026 году предпочтительно использовать **Cilium ClusterMesh** для объединения кластеров без публичных IP.*

### Сценарий 7: Cilium Identity-based Security Policy

Безопасность на основе имен сервисов, а не динамических IP-адресов.

```yaml
apiVersion: "cilium.io/v2"
kind: CiliumNetworkPolicy
metadata:
  name: allow-app-to-postgres
spec:
  endpointSelector:
    matchLabels:
      app: postgres
  ingress:
  - fromEndpoints:
    - matchLabels:
        app: my-web-app
    toPorts:
    - ports:
      - port: "5432"
        protocol: TCP
```

## Поиск и устранение неисправностей (SRE)

| Ошибка | Возможная причина | Диагностика |
|:---|:---|:---|
| `Connection timeout` | NetworkPolicy или Firewall | `kubectl exec -it app-pod -- nc -zv db-service 5432` / `cilium monitor` |
| `SSL error: decryption failed` | Ошибка mTLS / Sidecar | Проверить логи `istio-proxy` или статус `Certificate` в cert-manager |
| `Unknown host` | Проблемы DNS / CoreDNS | `kubectl exec -it app-pod -- nslookup db-service.namespace.svc.cluster.local` |
| `Slow commits` | Высокий Cross-AZ Latency | `ping` между нодами разных зон. Проверить `topology-mode: Auto` или `PreferClose`. Подробнее: **[Cross-zone traffic и задержки](../../../Networking/Troubleshooting/cross-zone-latency.md)** |
| `No endpoints available` | Topology Hints откл.Hints | Проверить равномерность распределения подов по зонам. |

## Дополнительная информация

### Рекомендации по выбору

* **Для чтения (Select)**: Используйте сервис реплик (`-ro`) с `topology-mode: Auto` или `trafficDistribution: PreferClose`. Это обеспечит чтение из "своей" зоны и сэкономит до 90% затрат на межзонный трафик.
* **Для записи (Insert/Update)**: Межзонный трафик к Primary неизбежен, если он в другой AZ. Используйте **PgBouncer** для уменьшения количества открытых сессий через сеть.
* **Observability**: Используйте **Hubble** (Cilium UI) или **Istio** для визуализации Cross-AZ трафика и автоматической настройки Locality Failover.

### Смотрите также

* **[PostgreSQL в Kubernetes](./kubernetes_deployment.md)** — развертывание через CloudNativePG.
* **[Наблюдаемость PostgreSQL](./observability.md)** — настройка мониторинга и трассировки.
* **[Предотвращение истечения SSL](../../../Kubernetes/Operations/ssl_expiration_prevention.md)** — настройка cert-manager для Kubernetes.
* **[Affinity и TopologySpreadConstraints](../../../Kubernetes/Scheduling/affinity.md)** — управление распределением подов.
* **[Основные концепции Service Mesh](../../../Service_Mesh/service_mesh_concepts.md)** — управление East-West трафиком и mTLS.
* **[Cilium: eBPF Networking](../../../Kubernetes/Networking/Network/CNI/ebpf.md)** — руководство по эксплуатации Cilium.
* **[Безопасная установка СУБД](../../installation_security.md)** — общее руководство по закалке PostgreSQL.

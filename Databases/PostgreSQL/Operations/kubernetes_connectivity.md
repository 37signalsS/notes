# Сетевая связность Kubernetes и PostgreSQL в многозонных средах

**Актуально для:** Kubernetes 1.33–1.36 (`trafficDistribution` GA в 1.33; `PreferClose` deprecated в 1.34 в пользу `PreferSameZone`/`PreferSameNode`), CloudNativePG 1.30.x, cert-manager 1.21.x. Теория межзонных задержек — в [Cross-zone Latency](../../../Networking/Troubleshooting/cross-zone-latency.md).

## Определения

* **Topology Aware Routing** (ранее Topology Aware Hints) — механизм Kubernetes (GA с v1.27), направляющий трафик на эндпоинты в той же зоне доступности (AZ), что и клиент. Реализуется через аннотацию `service.kubernetes.io/topology-mode: Auto`.
* **`trafficDistribution`** — поле `spec` Service (GA с v1.33), заменяющая аннотацию предпочтение маршрутизации. `PreferClose` удерживает трафик в зоне клиента; в Kubernetes 1.34 deprecated в пользу `PreferSameZone` (синоним) и `PreferSameNode` (локальный эндпоинт с fallback на удалённый). При одновременной установке аннотация `topology-mode` имеет приоритет над полем (аннотация сама будет deprecated в будущем).
* **Service Internal Traffic Policy** — `spec.internalTrafficPolicy` (GA с v1.26): `Cluster` (все готовые эндпоинты) или `Local` (только эндпоинты на той же ноде). `Local` имеет приоритет над `trafficDistribution` для внутреннего трафика.
* **Cross-Zone Traffic** — трафик между зонами доступности. Вносит дополнительную задержку (latency) и потребляет канал между зонами; в многозонных кластерах его минимизация критична для производительности.
* **Connection Pooler (PgBouncer/Odyssey)** — промежуточный слой между приложением и БД для переиспользования сессий и сглаживания пиков нагрузки.
* **Locality-based Load Balancing** — балансировка, приоритезирующая локальные ресурсы (внутри узла или зоны) для минимизации задержек.
* **eBPF (Extended Berkeley Packet Filter)** — технология ядра Linux (используется в Cilium), ускоряющая сетевые операции за счёт перехвата пакетов на уровне сокетов, минуя стек `iptables/kube-proxy`.
* **mTLS (Mutual TLS)** — взаимная аутентификация через сертификаты; шифрование Pod-to-Pod без изменения кода приложения. Реализуется прозрачно через Service Mesh (Ambient Mesh, eBPF) или сертификаты оператора.
* **Multi-cluster Connectivity** — объединение кластеров (Cilium ClusterMesh, ExternalDNS) для доступа к БД из другого кластера без публичных IP.

## Базовые концепции

При работе в многозонных кластерах критически важно минимизировать межзонный трафик: это снижает задержки транзакций и нагрузку на межзонный канал. Детальный анализ задержек и методов измерения — в [Cross-zone Latency](../../../Networking/Troubleshooting/cross-zone-latency.md).

### Задержки и производительность (PG 18 Context)

С внедрением **PostgreSQL 18** и нативного асинхронного ввода-вывода (**AIO**) влияние сетевых задержек на пропускную способность снизилось, но задержка конкретных транзакций (latency) остаётся определяющей для UX. Особенно чувствительны к задержке: синхронная репликация (`synchronous_commit`), двухфазный commit и распределённые транзакции.

| Тип соединения | Типичная задержка (порядковая) | Влияние на PostgreSQL |
|:---|:---|:---|
| Внутри одной ноды (Unix Socket) | < 0.05 мс | Идеально для высокоинтенсивных транзакций |
| Внутри одной ноды (TCP) | < 0.1 мс | Минимальные накладные расходы сетевого стека |
| Между нодами (одна AZ) | 0.2 – 0.5 мс | Стандарт для production-среды |
| Межзонный трафик (Cross-AZ) | 1.0 – 2.5 мс | Заметное замедление при большом количестве commit |
| Межрегиональный трафик | 10 – 60 мс | Только для асинхронной репликации |

### Безопасность и шифрование (Zero Trust)

Сетевой периметр кластера считается небезопасным: шифруйте и ограничивайте трафик даже внутри кластера.
1. **CloudNativePG Native TLS**: оператор по умолчанию выпускает и ротирует сертификаты (operator-managed CA). Подробности — [Сценарий 5](#сценарий-5-tls-в-cloudnativepg).
2. **Service Mesh (Istio/Cilium)**: прозрачное шифрование трафика. Sidecar-прокси (Envoy) добавляет накладные расходы на каждый хоп; sidecar-less решения (Ambient/eBPF) минимизируют оверхед. Теория — [Service Mesh](../../../Service_Mesh/service_mesh_concepts.md).
3. **NetworkPolicies**: ограничение доступа на порт 5432 только из namespaces приложений; Identity-подход (Cilium Identity). Детали и паттерны — [NetworkPolicy](../../../Kubernetes/Security/network_policies.md).

### Основные стратегии оптимизации

1. **Topology Aware Routing / `trafficDistribution`** (Native K8s): EndpointSlice-контроллер отслеживает топологию и удерживает трафик в рамках зоны. Эффективно для реплик, распределённых по AZ. Generic-сценарии — [Service: практические сценарии](../../../Kubernetes/Networking/Service/service_practical_scenarios.md).
2. **Internal Traffic Policy (Node Local)**: если PgBouncer развёрнут как Sidecar или DaemonSet, `internalTrafficPolicy: Local` гарантирует соединение с пулером без лишних сетевых прыжков.
3. **PgBouncer как зональный прокси**: отдельный Deployment PgBouncer в каждой зоне; приложение из зоны A обращается к `pgbouncer-zone-a.svc.cluster.local`.
4. **Акселерация через eBPF (Cilium)**: socket-level балансировка перенаправляет трафик минуя инкапсуляцию, давая производительность, близкую к Unix Sockets. Эксплуатация Cilium — [eBPF Networking](../../../Kubernetes/Networking/Network/CNI/ebpf.md).

## Практические сценарии

### Сценарий 1: Активация зональной балансировки

Для нативной балансировки с учётом зон добавьте аннотацию к Service (или используйте `trafficDistribution` для K8s 1.33+):

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
  # GA с v1.33; в 1.34+ PreferClose deprecated в пользу PreferSameZone
  trafficDistribution: PreferClose
  ports:
    - protocol: TCP
      port: 5432
```

*Важно:* Topology Aware Hints требуют минимум 3 подов на зону и равномерного распределения ресурсов по зонам — при меньшем количестве K8s отключает подсказки (hints) и направляет трафик случайно. Статус: `kubectl get endpointslices -l kubernetes.io/service-name=postgres-replica`.

### Сценарий 2: Доступ к внешним БД (вне кластера)

Для работы с базами вне кластера (legacy на физических серверах или в другом кластере) используйте **ExternalName** (для DNS-имен) или **Headless Service** с ручными эндпоинтами.

**Вариант с ExternalName:**
```yaml
apiVersion: v1
kind: Service
metadata:
  name: external-db
spec:
  type: ExternalName
  externalName: pg-legacy.db.internal.example.com  # ← placeholder
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

Оператор **CloudNativePG** автоматически создаёт несколько сервисов. Аннотации добавляются через `spec.serviceTemplate`:

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
* `<name>-rw`: всегда ведёт на Primary (чтение-запись).
* `<name>-ro`: только реплики (идеально для `topology-mode: Auto` — read-трафик остаётся в зоне).
* `<name>-r`: любые инстансы, включая Primary.

### Сценарий 4: Принудительная локальность (Sidecar PgBouncer)

Если PgBouncer развёрнут в каждом поде приложения (Sidecar) или на каждой ноде (DaemonSet), настройте сервис так, чтобы трафик не уходил на другие узлы:

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

### Сценарий 5: TLS в CloudNativePG

Оператор работает в двух режимах (детали — [Certificates](https://cloudnative-pg.io/documentation/1.30/certificates)):

1. **Operator-managed (default)**: оператор создаёт самоподписанный CA и автоматически выпускает/ротирует серверные и клиентские сертификаты — обновление за 7 дней до истечения, срок действия 90 дней. Если DNS-зона кластера не `cluster.local`, задайте `KUBERNETES_CLUSTER_DOMAIN`.
2. **User-provided (с cert-manager)**: cert-manager создаёт Secret с серверным сертификатом, оператор использует его. Пользовательские сертификаты оператор не ротирует — ответственность за обновление на стороне issuer.

```yaml
# cert-manager создаёт Secret с меткой cnpg.io/reload (оператор перечитает конфиг)
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: pg-prod-server-cert
spec:
  secretName: pg-prod-server-cert
  usages:
    - server auth
  dnsNames:
    - pg-prod
    - pg-prod-rw
    - pg-prod-rw.default
    - pg-prod-rw.default.svc
    - pg-prod-r
    - pg-prod-r.default
    - pg-prod-r.default.svc
    - pg-prod-ro
    - pg-prod-ro.default
    - pg-prod-ro.default.svc
  issuerRef:
    name: internal-ca
    kind: ClusterIssuer
    group: cert-manager.io
---
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata:
  name: pg-prod
spec:
  instances: 3
  certificates:
    serverTLSSecret: pg-prod-server-cert   # Secret типа kubernetes.io/tls (tls.crt + tls.key)
    serverCASecret: pg-prod-server-cert     # Secret с ключом ca.crt
  # ... остальная конфигурация
```

*Важно:* dnsNames должны покрывать все сервисы кластера (`<name>`, `<name>-rw`, `<name>-r`, `<name>-ro` и их суффиксы `.namespace`/`.namespace.svc`) — иначе клиенты будут получать ошибки проверки имени хоста. Клиентские сертификаты (в т.ч. для streaming replication) оператор продолжает управлять сам. Полный сценарий mTLS с cert-manager — [Internal mTLS](../../../Kubernetes/ToolsUtilities/cert_manager/Administration/internal_mtls.md).

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
  loadBalancerSourceRanges:   # ← ограничение доступа по IP обязательно
    - 10.0.0.0/8
  ports:
    - port: 5432
```

*Внимание:* публикация БД через LoadBalancer требует обязательного шифрования и ограничения доступа по IP (`loadBalancerSourceRanges`). Для объединения кластеров без публичных IP предпочтительнее **Cilium ClusterMesh**; регистрация DNS через self-hosted ExternalDNS поддерживает разные DNS-провайдеры.

### Сценарий 7: NetworkPolicy для PostgreSQL

Безопасность на основе имён (меток), а не динамических IP-адресов. Полные паттерны сегментации — [NetworkPolicy](../../../Kubernetes/Security/network_policies.md).

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-app-to-postgres
spec:
  podSelector:
    matchLabels:
      app: postgres
  policyTypes:
    - Ingress
  ingress:
    - from:
        - podSelector:
            matchLabels:
              app: my-web-app
      ports:
        - port: 5432
          protocol: TCP
```

## Поиск и устранение неисправностей (SRE)

| Ошибка | Возможная причина | Диагностика |
|:---|:---|:---|
| `Connection timeout` | NetworkPolicy или Firewall | `kubectl exec -it app-pod -- nc -zv db-service 5432` / `cilium monitor` |
| `SSL error: decryption failed` | Ошибка TLS / истёк сертификат | `kubectl get certificate`; статус `Certificate` в cert-manager; [ssl_expiration_prevention](../../../Kubernetes/Operations/ssl_expiration_prevention.md) |
| `Unknown host` | Проблемы DNS / CoreDNS | `kubectl exec -it app-pod -- nslookup db-service.namespace.svc.cluster.local` |
| `Slow commits` | Высокий Cross-AZ Latency | `ping` между нодами разных зон; проверить `topology-mode: Auto` или `PreferClose`. Подробнее: [Cross-zone traffic и задержки](../../../Networking/Troubleshooting/cross-zone-latency.md) |
| `No endpoints available` | Topology Hints отключены | Проверить равномерность распределения подов по зонам (минимум 3 на зону): `kubectl get endpointslices` |
| `x509: certificate is valid for ...` | dnsNames не покрывают сервис CNPG | Проверить SAN сертификата на все сервисы (`-rw`, `-r`, `-ro`) |

## Лучшие практики

* **Для чтения (SELECT)**: сервис реплик (`-ro`) с `topology-mode: Auto` или `trafficDistribution: PreferClose` — read-трафик остаётся в зоне клиента.
* **Для записи**: межзонный трафик к Primary неизбежен, если он в другой AZ; используйте **PgBouncer** для уменьшения количества сессий через сеть.
* **Observability**: **Hubble** (Cilium UI) или **Istio** для визуализации cross-AZ трафика и настройки Locality Failover.
* `internalTrafficPolicy: Local` применяйте только при гарантированном присутствии эндпоинта на каждой ноде (DaemonSet/Sidecar), иначе часть трафика будет дропаться.
* Регулярно проверяйте срок сертификатов: `kubectl get certificate -o wide`; operator-managed сертификаты CNPG ротируются автоматически, user-provided — нет.

## Дополнительная информация

### Связанные документы

* **[PostgreSQL в Kubernetes](./kubernetes_deployment.md)** — развёртывание через CloudNativePG.
* **[Наблюдаемость PostgreSQL](./observability.md)** — мониторинг и трассировка.
* **[PgBouncer](./pgbouncer_setup.md)** — теория пулинга и sizing.
* **[Cross-zone Latency](../../../Networking/Troubleshooting/cross-zone-latency.md)** — теория и диагностика межзонных задержек.
* **[Service: практические сценарии](../../../Kubernetes/Networking/Service/service_practical_scenarios.md)** — generic Topology Aware Routing.
* **[NetworkPolicy](../../../Kubernetes/Security/network_policies.md)** — сегментация и изоляция подов.
* **[Internal mTLS](../../../Kubernetes/ToolsUtilities/cert_manager/Administration/internal_mtls.md)** — cert-manager для PostgreSQL.
* **[ssl_expiration_prevention](../../../Kubernetes/Operations/ssl_expiration_prevention.md)** — предотвращение истечения сертификатов.
* **[Affinity и TopologySpreadConstraints](../../../Kubernetes/Scheduling/affinity.md)** — управление распределением подов.
* **[Service Mesh](../../../Service_Mesh/service_mesh_concepts.md)** — East-West трафик и mTLS.
* **[Cilium: eBPF Networking](../../../Kubernetes/Networking/Network/CNI/ebpf.md)** — эксплуатация Cilium.
* **[Безопасная установка СУБД](../../installation_security.md)** — закалка PostgreSQL.

# Развёртывание VictoriaLogs в Kubernetes

## Определения

**VictoriaLogs Stack** — это комплексное решение для сбора, хранения и анализа журналов (логов) в среде Kubernetes. Оно спроектировано для обеспечения высокой производительности при минимальных затратах на ресурсы, что делает его предпочтительной альтернативой ELK и Loki в высоконагруженных кластерах.

**vlagent** — высокопроизводительный агент от VictoriaMetrics для сбора логов. В 2026 году он вытесняет Fluent Bit благодаря нативной поддержке LogsQL, автоматическому обнаружению контейнеров и в 4 раза более низкой нагрузке на CPU при сопоставимой пропускной способности.

---

## 1. Архитектура решения

Типовая схема в кластере 2026:
1.  **Сбор данных:** `vlagent` (DaemonSet) с включенным `-kubernetesCollector`. Он автоматически собирает логи с `/var/log/pods`, добавляя метаданные K8s (labels, annotations) без использования тяжелых sidecar-контейнеров.
2.  **Хранение:**
    *   `VLSingle` (Custom Resource) — одиночный инстанс для малых и средних нагрузок.
    *   `VLCluster` (Custom Resource) — распределенная система с независимым масштабированием компонентов приёма (`vlinsert`), хранения (`vlstorage`) и запросов (`vlselect`).
3.  **Визуализация:** Grafana с плагином `victoriametrics-logs-datasource` и встроенный веб-интерфейс **VMUI**.
4.  **Управление:** **VictoriaMetrics Operator** — обеспечивает декларативное управление всем жизненным циклом стека через CRD.

---

## 2. Подготовка и инфраструктура

Для автоматизации TLS-сертификатов и безопасного доступа по HTTPS требуется наличие `cert-manager`.

**Установка cert-manager (v1.19+):**
```bash
helm install cert-manager oci://quay.io/jetstack/charts/cert-manager \
  --version v1.19.2 --namespace cert-manager --create-namespace --set crds.enabled=true
```

**ClusterIssuer (Let's Encrypt):**
```yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-prod
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    email: admin@example.com
    privateKeySecretRef:
      name: letsencrypt-prod
    solvers:
    - http01:
        ingress:
          class: nginx
```

---

## 3. Методы установки

### Вариант А: Одиночный узел (Single Node)
Подходит для большинства средних инсталляций (до нескольких ТБ логов в день). Один под выполняет все функции, что упрощает эксплуатацию.

```bash
helm upgrade --install victoria-logs-single \
  oci://ghcr.io/victoriametrics/helm-charts/victoria-logs-single \
  --namespace victoria-logs --create-namespace --version 0.7.0
```

### Вариант Б: Кластерный режим (Cluster Mode)
Для распределения нагрузки и обеспечения высокой доступности. Позволяет масштабировать `vlinsert` (при росте трафика) и `vlstorage` (при росте объема хранения) независимо.

```bash
helm upgrade --install victoria-logs-cluster \
  oci://ghcr.io/victoriametrics/helm-charts/victoria-logs-cluster \
  --namespace victoria-logs-cluster --create-namespace \
  -f victorialogs-cluster-values.yaml
```

**Пример Ingress в values.yaml для кластера:**
```yaml
vlselect:
  ingress:
    enabled: true
    hosts:
      - name: logs.example.com
    ingressClassName: nginx
    annotations:
      cert-manager.io/cluster-issuer: letsencrypt-prod
    tls:
      - hosts: [logs.example.com]
        secretName: victorialogs-tls
```

### Вариант В: VictoriaMetrics Operator (Рекомендуемый для Production)
Использование оператора (v0.68+) позволяет описывать кластер как единый объект.

**Важно:** С версии **v0.68.4** (апрель 2026) изменены стандарты меток `matchLabels` для соответствия `app.kubernetes.io/component`. При обновлении может потребоваться пересоздание ресурсов (manual recreate).

**Пример CRD для развёртывания VLCluster:**
```yaml
apiVersion: operator.victoriametrics.com/v1
kind: VLCluster
metadata:
  name: victorialogs-prod
  namespace: monitoring
spec:
  clusterDomainName: cluster.local
  managedMetadata:
    labels:
      component: vlogs
  requestsLoadBalancer:
    enabled: true # Развертывание vmauth для маршрутизации
    spec:
      replicaCount: 2
  vlinsert:
    replicaCount: 3
    extraArgs:
      insert.maxLineSizeBytes: "1048576" # 1MB для длинных JSON/Stacktraces
      memory.allowedPercent: "80"
  vlselect:
    replicaCount: 3
    extraArgs:
      memory.allowedPercent: "80"
      search.maxQueryDuration: "30s"
  vlstorage:
    replicaCount: 2
    retentionPeriod: 30d
    extraArgs:
      retention.maxDiskSpaceUsageBytes: 900GiB
    storage:
      volumeClaimTemplate:
        spec:
          resources:
            requests:
              storage: 1Ti
          storageClassName: csi-cephfs-hdd
```

---

## 4. Сбор логов (DaemonSet и vlagent)

В 2026 году рекомендуется использовать **vlagent** вместо Fluent Bit для минимизации оверхеда.

### Сравнение производительности (на 10к логов/сек)
| Метрика | vlagent | Fluent Bit |
| :--- | :--- | :--- |
| **CPU** | ~0.5 core | ~2.1 cores |
| **Memory** | ~40 MiB | ~120 MiB |
| **Парсинг** | Нативный (LogsQL) | Lua/Regex |

**Установка сборщика через Helm:**
```bash
helm upgrade --install victoria-logs-collector \
  oci://ghcr.io/victoriametrics/helm-charts/victoria-logs-collector \
  --namespace monitoring --create-namespace \
  -f collector-values.yaml
```

**Пример конфигурации collector-values.yaml:**
```yaml
vlagent:
  enabled: true
  spec:
    k8sCollector:
      enabled: true # Нативный сбор логов контейнеров (New 2026)
    remoteWrite:
      - url: http://victoria-logs-single-addr:9428/insert/jsonline?_stream_fields=pod,container,namespace
        headers:
          VL-Ignore-Fields: ["kubernetes.pod_ip", "kubernetes.node_name"] # Фильтрация лишних метаданных
    extraArgs:
      "lib.logger.format": "json"
      "insert.maxLineSizeBytes": "1048576"
```

---

## 5. Визуализация в Grafana

Для работы требуется плагин `victoriametrics-logs-datasource`. Он позволяет выполнять LogsQL запросы напрямую из Grafana Explore.

**Настройка Datasource в Helm (vmks):**
```yaml
grafana:
  plugins:
    - victoriametrics-logs-datasource
  additionalDataSources:
    - name: VictoriaLogs
      type: victoriametrics-logs-datasource
      url: http://vlselect-prod.monitoring.svc:9481  # URL сервиса vlselect
      jsonData:
        maxLines: 2000
        keepCookies: ["vlogs-tenant-id"] # Для мультитенантности
```

---

## 6. Тестирование и проверка

Для генерации тестовых данных и проверки корректности парсинга JSON используйте `flog`:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: flog-generator
spec:
  replicas: 1
  template:
    spec:
      containers:
      - name: flog
        image: mingrammer/flog
        args: ["--format", "json", "--loop", "--delay", "500ms"]
```

### Процедура проверки:
1.  **Доступность API:** Выполните `curl http://<vlselect-url>/select/logsql/ping` (должен вернуть `pong`).
2.  **Проверка данных:** Зайдите в VMUI (`/select/vmui`) и выполните запрос `* | limit 10`.
3.  **Логи сборщика:** Проверьте отсутствие ошибок `remote_write` в логах DaemonSet `victoria-logs-collector`.

### См. также
- **[LogsQL: руководство по запросам](../../VictoriaMetrics/logsql_overview.md)** — описание синтаксиса и функций аналитики.
- **[Внутреннее устройство и оптимизации](../../VictoriaMetrics/victorialogs_internals.md)** — глубокий разбор механизмов хранения и сжатия.
- **[Обзор VictoriaMetrics Operator](../../VictoriaMetrics/overview.md)** — управление всем стеком мониторинга.

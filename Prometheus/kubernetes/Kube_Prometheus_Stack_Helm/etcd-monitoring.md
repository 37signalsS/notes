# Мониторинг ETCD в Kubernetes через kube-prometheus-stack

## Определения

**ETCD** — распределённое key-value хранилище, используемое Kubernetes как Single Source of Truth для хранения состояния кластера.

**Мониторинг ETCD** — сбор метрик через HTTPS-эндпоинт ETCD (порт 2379) с использованием клиентских TLS-сертификатов для аутентификации Prometheus.

**Проблема автоматического обнаружения** — при ручном развертывании Kubernetes (без Rancher) `kube-prometheus-stack` не собирает метрики ETCD автоматически, т.к. ETCD работает как static Pod с `hostNetwork=true` и не имеет Kubernetes Service.

---

## Базовые концепции

### Почему требуется ручная настройка

ETCD в kubeadm-кластерах запускается как static Pod на control-plane узлах с `hostNetwork=true`. Prometheus Operator обнаруживает цели через Kubernetes Services, поэтому для ETCD необходимо вручную создать:

1. **Secret** с TLS-сертификатами для аутентификации
2. **Headless Service** без селектора — логическая точка входа
3. **Endpoints** — указание реальных IP-адресов ETCD-узлов
4. **ServiceMonitor** — инструкция для Prometheus Operator по сбору метрик

### TLS-аутентификация

ETCD использует mutual TLS. Для сбора метрик Prometheus должен предоставить:

- **CA-сертификат** — для валидации серверного сертификата ETCD
- **Клиентский сертификат** — для аутентификации Prometheus перед ETCD
- **Клиентский ключ** — для подписи клиентского сертификата

### Альтернативный подход через Helm values

`kube-prometheus-stack` предоставляет параметры `kubeEtcd.*` для автоматической настройки мониторинга ETCD через `values.yaml`. Этот подход описан в [other_components_config.md](./other_components_config.md).

Ручной подход (описанный ниже) применяется, когда:

- ETCD использует нестандартную конфигурацию TLS
- Требуется детальный контроль над ServiceMonitor
- Helm values не покрывают специфический сценарий

---

## Практические сценарии

### Сценарий 1: Подготовка TLS-сертификатов

Сертификаты обычно находятся на control-plane узлах в `/etc/kubernetes/pki/etcd/`. Их необходимо закодировать в base64 и создать Kubernetes Secret.

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: kube-etcd-client-certs
  namespace: kube-system
type: Opaque
data:
  etcd-client-ca.crt: <base64_encoded_ca_cert>
  etcd-client.crt: <base64_encoded_client_cert>
  etcd-client.key: <base64_encoded_client_key>
```

**Важно:**

- Ключи в `data` должны совпадать с именами, используемыми в `ServiceMonitor.tlsConfig`
- Prometheus Operator должен иметь права на чтение этого Secret
- Базовое кодирование: `cat etcd-client-ca.crt | base64 -w 0`

### Сценарий 2: Создание Service и Endpoints

ETCD работает как static Pod с `hostNetwork=true`, поэтому требуется headless Service без селектора и ручные Endpoints.

```yaml
apiVersion: v1
kind: Service
metadata:
  name: etcd
  namespace: kube-system
  labels:
    k8s-app: etcd-metrics
spec:
  ports:
  - name: metrics
    port: 2379
    protocol: TCP
    targetPort: 2379
  clusterIP: None
  type: ClusterIP
---
apiVersion: v1
kind: Endpoints
metadata:
  name: etcd
  namespace: kube-system
  labels:
    k8s-app: etcd-metrics
subsets:
  - addresses:
      - ip: <IP_ETCD_узла_1>
      - ip: <IP_ETCD_узла_2>
      - ip: <IP_ETCD_узла_3>
    ports:
      - name: metrics
        port: 2379
        protocol: TCP
```

**Важно:**

- Метка `k8s-app: etcd-metrics` используется ServiceMonitor для обнаружения
- Замените `<IP_ETCD_узла_N>` на реальные IP control-plane узлов
- `clusterIP: None` делает Service headless — трафик идёт напрямую в Endpoints

### Сценарий 3: Создание ServiceMonitor

ServiceMonitor связывает Service с конфигурацией сбора метрик Prometheus.

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: etcd-k8s-monitor
  namespace: kube-system
  labels:
    release: prometheus-stack
spec:
  jobLabel: k8s-app
  endpoints:
  - port: metrics
    interval: 30s
    scheme: https
    tlsConfig:
      ca:
        secret:
          name: kube-etcd-client-certs
          key: etcd-client-ca.crt
      cert:
        secret:
          name: kube-etcd-client-certs
          key: etcd-client.crt
      key:
        secret:
          name: kube-etcd-client-certs
          key: etcd-client.key
    metricRelabelings:
    - sourceLabels: [__name__]
      regex: 'etcd_debugging_mvcc_db_total_size_in_bytes|etcd_server_has_leader|etcd_server_leader|etcd_network_client_grpc_received_bytes_total|etcd_network_client_grpc_sent_bytes_total|etcd_disk_wal_fsync_duration_seconds_bucket|etcd_mvcc_db_total_size_in_bytes'
      action: keep
  selector:
    matchLabels:
      k8s-app: etcd-metrics
  namespaceSelector:
    matchNames:
    - kube-system
```

**Критичные параметры:**

| Параметр | Описание |
| :--- | :--- |
| `labels.release` | Должен совпадать с `release` меткой Prometheus (обычно `prometheus-stack` или `rancher-monitoring`) |
| `scheme: https` | ETCD требует HTTPS для метрик |
| `tlsConfig` | Ссылка на Secret с TLS-сертификатами |
| `selector.matchLabels` | Должен совпадать с метками Service/Endpoints |
| `metricRelabelings` | Фильтрация метрик для снижения нагрузки на Prometheus |

### Сценарий 4: Проверка работоспособности

После применения манифестов:

1. **Проверить статус ServiceMonitor:**

   ```bash
   kubectl get servicemonitor etcd-k8s-monitor -n kube-system
   ```

2. **Проверить Target в Prometheus UI:**
   - Открыть Prometheus → Status → Targets
   - Найти target `serviceMonitor/kube-system/etcd-k8s-monitor/0`
   - Убедиться в статусе `UP`

3. **Проверить метрики в Prometheus:**

   ```
   etcd_server_has_leader
   etcd_mvcc_db_total_size_in_bytes
   ```

---

## Дополнительная информация

### Примечание о Rancher UI

При редактировании `values.yaml` через Rancher Web UI, Rancher удаляет все комментарии из файла. Для понимания доступных параметров рекомендуется обращаться к [официальной документации kube-prometheus-stack](https://github.com/prometheus-community/helm-charts/tree/main/charts/kube-prometheus-stack).

### Ключевые метрики ETCD

Подробное описание метрик ETCD, включая recommended thresholds и alerting rules, доступно в [etcd_monitoring.md](../../../etcd/etcd_monitoring.md).

### Связанные темы

- **[ETCD monitoring (концепции и метрики)](../../../etcd/etcd_monitoring.md)** — ключевые метрики, health check, alerting
- **[ETCD monitoring через Helm values](./other_components_config.md)** — настройка через параметры `kubeEtcd.*` в `values.yaml`
- **[ServiceMonitor CRD](../../operator/crd/servicemonitor.md)** — полное описание CRD ServiceMonitor
- **[Rancher мониторинг](../../../Kubernetes/Rancher/rancher_monitoring.md)** — настройка мониторинга в Rancher

### Альтернативные подходы к TLS

В зависимости от конфигурации кластера, TLS-сертификаты могут подключаться через:

- **Kubernetes Secret** (описано выше) — универсальный подход
- **hostPath volume** — прямое монтирование с хоста (описано в [other_components_config.md](./other_components_config.md))

Выбор зависит от политики безопасности кластера и расположения сертификатов.

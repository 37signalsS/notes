# Мониторинг etcd в Kubernetes через kube-prometheus-stack

## Определения

**etcd** — высокодоступное распределённое key-value хранилище, используемое Kubernetes как Single Source of Truth для хранения всех данных состояния кластера (конфигурации, секреты, состояние объектов).

**Мониторинг etcd** — процесс сбора и анализа метрик производительности хранилища (задержки записи/чтения, размер БД, смена лидеров) через HTTPS-эндпоинт (порт 2379) с обязательной TLS-аутентификацией.

**Prometheus Operator ServiceMonitor** — Custom Resource, определяющий способ обнаружения и параметры сбора метрик с etcd инстансов для Prometheus.

---

## Базовые концепции

### Проблема автоматического обнаружения

В кластерах, развернутых через `kubeadm`, компоненты Control Plane (включая etcd) запускаются как **Static Pods** на мастер-узлах с параметром `hostNetwork: true`. Они не имеют стандартной абстракции Kubernetes Service, что делает их "невидимыми" для механизмов Service Discovery Prometheus Operator по умолчанию.

Для реализации мониторинга необходимо создать логический мост между статическими подами и Оператором, состоящий из:
1.  **Secret:** содержит клиентские TLS-сертификаты для доступа к API etcd.
2.  **Headless Service & Endpoints/EndpointSlice:** предоставляют сетевой адрес узлов etcd.
3.  **ServiceMonitor:** описывает правила сбора метрик и конфигурацию TLS.

### Безопасность и RBAC

etcd хранит чувствительные данные кластера, поэтому доступ к его метрикам защищен mutual TLS (mTLS).
*   **Сертификаты:** Prometheus должен использовать сертификат, подписанный CA кластера etcd (обычно `/etc/kubernetes/pki/etcd/ca.crt`).
*   **Права доступа:** Инстанс Prometheus (ServiceAccount) должен иметь права `get` на Secret в неймспейсе `kube-system` (или там, где хранятся сертификаты), иначе сбор метрик завершится ошибкой `failed to load certificates`.

### Масштабируемость: Endpoints vs EndpointSlice

В современных кластерах (K8s 1.21+) рекомендуется использовать **EndpointSlice** вместо устаревших **Endpoints**. Это снижает нагрузку на API-сервер при обновлении сетевых адресов в больших кластерах. Prometheus Operator нативно поддерживает оба ресурса через роль обнаружения `endpointslice`.

---

## Практические сценарии

### Сценарий 1: Подготовка TLS-сертификатов

Сертификаты обычно находятся на control-plane узлах в `/etc/kubernetes/pki/etcd/`. Их необходимо закодировать в base64 и создать Kubernetes Secret.

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: kube-etcd-client-certs
  namespace: kube-system # Или namespace, где запущен Prometheus
type: Opaque
data:
  etcd-client-ca.crt: <base64_encoded_ca_cert>
  etcd-client.crt: <base64_encoded_client_cert>
  etcd-client.key: <base64_encoded_client_key>
```

**Важно:**
*   Если Prometheus запущен в другом неймспейсе (например, `monitoring`), Secret должен быть создан именно там, либо скопирован.
*   Команда для кодирования: `cat /etc/kubernetes/pki/etcd/ca.crt | base64 -w 0`.

### Сценарий 2: Создание Service и сетевых эндпоинтов

Для обнаружения статических подов etcd используется Headless Service и ручное описание адресов.

#### Вариант А: Стандартный (Endpoints)
```yaml
apiVersion: v1
kind: Service
metadata:
  name: etcd-k8s
  namespace: kube-system
  labels:
    k8s-app: etcd
spec:
  clusterIP: None
  ports:
  - name: https-metrics
    port: 2379
    targetPort: 2379
---
apiVersion: v1
kind: Endpoints
metadata:
  name: etcd-k8s
  namespace: kube-system
subsets:
- addresses:
  - ip: 192.168.1.10 # IP Master-узла 1
  - ip: 192.168.1.11 # IP Master-узла 2
  - ip: 192.168.1.12 # IP Master-узла 3
  ports:
  - name: https-metrics
    port: 2379
```

#### Вариант Б: Современный (EndpointSlice)
```yaml
apiVersion: discovery.k8s.io/v1
kind: EndpointSlice
metadata:
  name: etcd-k8s-slice
  namespace: kube-system
  labels:
    kubernetes.io/service-name: etcd-k8s
addressType: IPv4
ports:
  - name: https-metrics
    port: 2379
endpoints:
  - addresses: ["192.168.1.10"]
  - addresses: ["192.168.1.11"]
  - addresses: ["192.168.1.12"]
```

### Сценарий 3: Создание ServiceMonitor

ServiceMonitor описывает для Prometheus Operator, как именно собирать метрики с созданного сервиса.

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: etcd-monitor
  namespace: monitoring
  labels:
    release: prometheus-stack
spec:
  jobLabel: k8s-app
  endpoints:
  - port: https-metrics
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
      # Критично, если сертификат выписан на конкретное имя
      serverName: kubernetes
    metricRelabelings:
    - sourceLabels: [__name__]
      regex: '(etcd_server_has_leader|etcd_server_leader_changes_seen_total|etcd_mvcc_db_total_size_in_bytes|etcd_network_client_grpc_received_bytes_total)'
      action: keep
  selector:
    matchLabels:
      k8s-app: etcd
  namespaceSelector:
    matchNames:
    - kube-system
```

### Сценарий 4: Проверка работоспособности

После применения манифестов:

1. **Проверить статус ServiceMonitor:**
   ```bash
   kubectl get servicemonitor etcd-monitor -n monitoring
   ```

2. **Проверить Target в Prometheus UI:**
   - Открыть Prometheus → Status → Targets.
   - Найти target в формате `serviceMonitor/monitoring/etcd-monitor/0`.
   - Статус должен быть `UP`.

3. **Проверить метрики:**
   ```promql
   etcd_server_has_leader
   ```

---

## Дополнительная информация

### Диагностика и Troubleshooting

| Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| **Target status: DOWN (403)** | Ошибка RBAC | Убедитесь, что ClusterRole Прометеуса имеет доступ к Secret в `kube-system`. |
| **Target status: DOWN (TLS error)** | Ошибка сертификатов | Проверьте, что `serverName` совпадает с именами в сертификате etcd (`openssl x509 -in cert.crt -text`). |
| **Target не виден в UI** | Ошибка селектора | Проверьте `labels` в Service и `matchLabels` в ServiceMonitor. |

### Ключевые метрики

Подробный разбор метрик производительности и алертов доступен в руководстве: **[Метрики etcd](../../../etcd/etcd_monitoring.md)**.

### Связанные темы

- **[etcd: обслуживание в Kubernetes](../../../Kubernetes/Concepts/etcd_operations.md)** — команды обслуживания и проверки кворума.
- **[Service Discovery и Relabeling](../../../Prometheus/service_discovery_and_relabeling.md)** — теория переименования меток.
- **[Настройка других компонентов KPS](./other_components_config.md)** — конфигурация `values.yaml` для etcd.
- **[Мониторинг в Rancher](../../../Kubernetes/Rancher/rancher_monitoring.md)** — особенности для Rancher-кластеров.

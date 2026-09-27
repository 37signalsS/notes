# Мониторинг etcd в Kubernetes через kube-prometheus-stack

## Определения

**etcd** — высокодоступное распределённое key-value хранилище, используемое Kubernetes как Single Source of Truth для хранения всех данных состояния кластера (конфигурации, секреты, состояние объектов).

**Мониторинг etcd** — процесс сбора и анализа метрик производительности хранилища (задержки записи/чтения, размер БД, смена лидеров) через HTTPS-эндпоинт (порт 2379) с обязательной TLS-аутентификацией.

**Prometheus Operator ServiceMonitor** — Custom Resource, определяющий способ обнаружения и параметры сбора метрик с etcd инстансов для Prometheus.

## Архитектура и жизненный цикл

### Роль etcd в кластере Kubernetes

etcd является центральным компонентом Control Plane. Все изменения состояния кластера (создание Pod, обновление ConfigMap, изменение секретов) проходят через etcd через протокол консенсуса Raft. Потеря работоспособности etcd делает кластер доступным только для чтения или полностью неработоспособным.

### Жизненный цикл мониторинга в kube-prometheus-stack

1. **Инициализация:** При установке чарта Prometheus Operator создаёт ServiceMonitor для etcd (если параметр `kubeEtcd.enabled: true`).
2. **Discovery:** ServiceMonitor указывает Operator'у на наличие сервиса `etcd-k8s` в namespace `kube-system`. Operator генерирует конфигурацию scrape для Prometheus.
3. **Сбор метрик:** Prometheus опрашивает эндпоинты etcd по HTTPS с использованием mTLS-сертификатов.
4. **Хранение:** Метрики сохраняются в TSDB Prometheus.
5. **Визуализация:** Дашборды Grafana отображают ключевые показатели.
6. **Алертинг:** Правила PrometheusRule генерируют алерты при превышении порогов.

```
kube-prometheus-stack (values.yaml)
  └── kubeEtcd
        ├── serviceMonitor (TLS config, interval, selector)
        ├── secret (etcd-client-certs)
        └── Headless Service + Endpoints/EndpointSlice
              └── Статические поды etcd на master-нодах
```

### Встроенный механизм sidecar (ConfigMap Reload)

Prometheus Operator использует sidecar-контейнер `configmap-reload` (или встроенный механизм в современных версиях Оператора) для автоматической перезагрузки конфигурации при изменении ServiceMonitor, PrometheusRule или Secret. Это обеспечивает динамическое обновление правил сбора без перезапуска пода Prometheus.

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

### Высокая доступность

Для etcd мониторинг должен сохранять работоспособность даже при частичных сбоях:
*   **Несколько мастер-узлов:** Минимум 3 узла для кворума. Мониторинг должен опрашивать все доступные члены кластера.
*   **TLS отказоустойчивость:** При временной недоступности одного узла Prometheus должен автоматически переключаться на другие эндпоинты.
*   **Prometheus HA:** При запуске нескольких реплик Prometheus каждый экземпляр должен иметь доступ к сертификатам.

## Предварительные требования

*   **Kubernetes** 1.25+ (1.28+ рекомендуется для Gateway API и стабильной работы Ingress).
*   **Helm** 3.10+ (3.14+ рекомендуется для OCI-репозиториев).
*   **Доступ к control-plane узлам:** Необходим SSH-доступ или способ чтения файлов из `/etc/kubernetes/pki/etcd/`.
*   **etcd Client Certificates:** Корректно выписанные клиентские сертификаты, подписанные CA etcd.
*   **StorageClass** с поддержкой `ReadWriteOnce` (RWO) для Prometheus (если используется persistence).
*   **Ingress-контроллер** (NGINX, Traefik) — если требуется внешний доступ к Prometheus/Grafana.
*   **cert-manager** — для автоматической выдачи и ротации TLS-сертификатов (опционально, но рекомендуется).

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

### Сценарий 4: Production-конфигурация через values.yaml

```yaml
# values.yaml для kube-prometheus-stack
kubeEtcd:
  enabled: true
  service:
    enabled: true
    port: 2381
    targetPort: 2381
  serviceMonitor:
    enabled: true
    scheme: https
    caFile: /etc/prometheus/secrets/etcd-certs/ca.crt
    certFile: /etc/prometheus/secrets/etcd-certs/client.crt
    keyFile: /etc/prometheus/secrets/etcd-certs/client.key
    interval: 30s
    # timeout: 10s # Раскомментируйте при высокой задержке сети

  # Ресурсы для ServiceMonitor (если требуется дополнительный relabeling)
  # metricRelabelings:
  # - sourceLabels: [__name__]
  #   regex: 'etcd_.*'
  #   action: keep

# Секрет с сертификатами (должен существовать в namespace monitoring)
# apiVersion: v1
# kind: Secret
# metadata:
#   name: etcd-certs
#   namespace: monitoring
# type: Opaque
# data:
#   ca.crt: <base64>
#   client.crt: <base64>
#   client.key: <base64>
```

### Сценарий 5: Проверка работоспособности

После применения манифестов:

1. **Проверить статус ServiceMonitor:**
   ```bash
   kubectl get servicemonitor etcd-monitor -n monitoring
   # → NAME        AGE
   # → etcd-monitor   2m
   ```

2. **Проверить Target в Prometheus UI:**
   - Открыть Prometheus → Status → Targets.
   - Найти target в формате `serviceMonitor/monitoring/etcd-monitor/0`.
   - Статус должен быть `UP`.

3. **Проверить метрики:**
   ```promql
   etcd_server_has_leader
   ```

4. **Валидация через kubectl:**
   ```bash
   # Проверить endpoints
   kubectl get endpoints etcd-k8s -n kube-system
   # → NAME       ENDPOINTS                         AGE
   # → etcd-k8s   192.168.1.10:2379,192.168.1.11:2379,192.168.1.12:2379   5m

   # Проверить endpointslice (если используется)
   kubectl get endpointslice etcd-k8s-slice -n kube-system
   ```

### Сценарий 6: Апгрейд и откат

При обновлении kube-prometheus-stack мониторинг etcd должен оставаться доступным.

1. **Перед апгрейдом:**
   ```bash
   helm get values prometheus-stack -n monitoring > values-backup.yaml
   # Создайте snapshot etcd (если у вас есть доступ)
   ETCDCTL_API=3 etcdctl snapshot save /backup/etcd-pre-upgrade.db
   ```

2. **Выполнение апгрейда:**
   ```bash
   helm upgrade prometheus-stack prometheus-community/kube-prometheus-stack \
     -n monitoring \
     -f values-backup.yaml \
     --version 55.x.x
   ```

3. **Проверка после апгрейда:**
   ```bash
   kubectl get servicemonitor -n monitoring
   kubectl get pods -n monitoring -l app.kubernetes.io/name=prometheus
   # Проверьте, что Prometheus перезапустился без ошибок
   ```

4. **Откат при проблемах:**
   ```bash
   helm rollback prometheus-stack -n monitoring
   ```

### Сценарий 7: Очистка окружения

При удалении мониторинга etcd:

```bash
# Удалить ServiceMonitor
kubectl delete servicemonitor etcd-monitor -n monitoring

# Удалить Service и Endpoints/EndpointSlice
kubectl delete service etcd-k8s -n kube-system
kubectl delete endpoints etcd-k8s -n kube-system
# ИЛИ
kubectl delete endpointslice etcd-k8s-slice -n kube-system

# Удалить Secret с сертификатами
kubectl delete secret kube-etcd-client-certs -n kube-system

# Удалить PVC (если не требуется сохранение данных)
kubectl delete pvc -n monitoring -l app.kubernetes.io/name=prometheus

# Удалить неймспейс (если он создавался для стека)
kubectl delete namespace monitoring
```

## Дополнительная информация

### Диагностика и Troubleshooting

| Симптом | Вероятная причина | Решение |
| :--- | :--- | :--- |
| **Target status: DOWN (403)** | Ошибка RBAC | Убедитесь, что ClusterRole Prometheus имеет доступ к Secret в `kube-system`. |
| **Target status: DOWN (TLS error)** | Ошибка сертификатов | Проверьте, что `serverName` совпадает с именами в сертификате etcd (`openssl x509 -in cert.crt -text`). |
| **Target не виден в UI** | Ошибка селектора | Проверьте `labels` в Service и `matchLabels` в ServiceMonitor. |
| **Pod CrashLoopBackOff (Prometheus)** | Неверный путь к сертификатам | Проверьте mounts: `kubectl describe pod <prometheus-pod>`. |
| **Метрики не обновляются** | Ошибка relabeling или интервал | Проверьте Prometheus UI → Service Discovery для наличия target. |
| **Сертификаты истекли** | Срок действия client.crt | Перевыпустите сертификаты через `kubeadm` или `cert-manager` и обновите Secret. |
| **EndpointSlice не создаётся** | Отсутствует Headless Service | Создайте Service с `clusterIP: None` перед EndpointSlice. |

### Ключевые метрики

Подробный разбор метрик производительности, порогов, дашбордов и правил алертинга доступен в руководстве: **[Мониторинг etcd](../../../etcd/etcd_monitoring.md)**.

### Подбираемые параметры ресурсов (эмпирически)

| Компонент | Параметр | Значение (базовое) | Метрика для мониторинга |
| :--- | :--- | :--- | :--- |
| Prometheus | `requests.memory` | `256Mi` | `container_memory_working_set_bytes` |
| Prometheus | `requests.cpu` | `100m` | `rate(container_cpu_cfs_throttled_seconds_total[5m])` |
| PVC | `persistence.size` | `10Gi` | `kubelet_volume_stats_available_bytes` |
| ServiceMonitor | `interval` | `30s` | `up{job="etcd"}` |

### Ограничения и особые случаи (Edge Cases)

1. **Лимит размера Secret (1 МБ):** Kubernetes ограничивает размер Secret 1 МБ. Если сертификаты и ключи слишком велики (например, цепочка из 10+ сертификатов), используйте отдельные Secret для CA и клиентских ключей.
2. **ReadOnlyRootFilesystem:** При использовании `readOnlyRootFilesystem: true` в Prometheus убедитесь, что пути к сертификатам корректно монтируются через `volumes` и `volumeMounts`.
3. **Configuration Drift:** Изменения, сделанные через UI Grafana/Prometheus, не сохраняются обратно в Helm-чарт. Все изменения должны вноситься через `values.yaml` или отдельные манифесты.
4. **hostNetwork:** Из-за `hostNetwork: true` у статических подов etcd нельзя использовать стандартный kube-proxy для доступа. Обязательно используйте IP-адреса master-узлов в Endpoints/EndpointSlice.
5. **Разное количество master-уздов:** При изменении количества master-узлов не забудьте обновить Endpoints/EndpointSlice.
6. **etcd v2 store:** В etcd 3.7+ v2 store полностью удалён. Убедитесь, что ваш кластер использует v3 API.

### Связанные темы

*   **[Конфигурация прочих компонентов](./other_components_config.md)** — параметры `kubeEtcd`, RBAC, reload, Thanos Ruler.
*   **[Обнаружение сервисов в Kubernetes](../../Prometheus/kubernetes/service_discovery.md)** — теория Service Discovery и практика мониторинга статических подов.
*   **[Обслуживание etcd в Kubernetes](../../Kubernetes/Concepts/etcd_operations.md)** — команды обслуживания и проверки кворума.

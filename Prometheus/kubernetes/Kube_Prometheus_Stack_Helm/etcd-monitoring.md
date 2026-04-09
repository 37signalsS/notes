
**Примечание о Rancher UI и `values.yaml`**: При редактировании `values.yaml` Helm-чарта `kube-prometheus-stack` через Rancher Web UI, Rancher имеет тенденцию удалять все комментарии из файла. Это может затруднить понимание настроек, поэтому для получения полной информации о доступных параметрах и их описаниях рекомендуется всегда обращаться к официальной документации Helm-чарта `kube-prometheus-stack`.

---

## Мониторинг ETCD с помощью kube-prometheus-stack

Для полноценного мониторинга кластера Kubernetes крайне важно собирать метрики с ETCD. В случаях, когда Kubernetes развернут вручную (без использования инструментов Rancher для инсталляции кластера), `kube-prometheus-stack` может не собирать эти метрики автоматически. Ручная настройка включает создание Kubernetes-объектов для обнаружения ETCD и его метрик.

### 1. Подготовка сертификатов ETCD

ETCD использует TLS для безопасной коммуникации. Prometheus должен использовать клиентские сертификаты для аутентификации при сборе метрик. Эти сертификаты (CA, client certificate, client key) обычно находятся на Control Plane узлах Kubernetes и должны быть помещены в Kubernetes Secret.

**Пример создания Secret (предполагается, что файлы сертификатов уже извлечены):**

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: kube-etcd-client-certs
  namespace: kube-system # Или другой namespace, где Prometheus Operator имеет доступ
type: Opaque
data:
  etcd-client-ca.crt: <base64_encoded_ca_cert>
  etcd-client.crt: <base64_encoded_client_cert>
  etcd-client.key: <base64_encoded_client_key>
```

**Примечание**: Ключи полей `etcd-client-ca.crt`, `etcd-client.crt`, `etcd-client.key` должны совпадать с именами, которые будут использоваться в `ServiceMonitor`. Убедитесь, что Prometheus Operator имеет права на чтение этого `Secret`.

### 2. Создание Service и Endpoint для ETCD

Prometheus Operator использует Service Discovery через Kubernetes Services. Поскольку ETCD может быть запущен как статический Pod (kubelet-managed) с `hostNetwork=true`, для него необходимо создать `Service` типа `ClusterIP` без селектора (headless Service) и вручную добавить `Endpoint`, указывающий на IP-адреса ETCD-узлов.

```yaml
apiVersion: v1
kind: Service
metadata:
  name: etcd
  namespace: kube-system
  labels:
    k8s-app: etcd-metrics # Метка для ServiceMonitor
spec:
  ports:
  - name: metrics
    port: 2379
    protocol: TCP
    targetPort: 2379
  clusterIP: None # Headless Service
  type: ClusterIP
---
apiVersion: v1
kind: Endpoints
metadata:
  name: etcd
  namespace: kube-system
  labels:
    k8s-app: etcd-metrics # Метка для ServiceMonitor
subsets:
  - addresses:
      - ip: <IP_адрес_первого_ETCD_узла>
      - ip: <IP_адрес_второго_ETCD_узла>
      - ip: <IP_адрес_третьего_ETCD_узла>
    ports:
      - name: metrics
        port: 2379
        protocol: TCP
```

**Примечание**: Замените `<IP_адрес_..._ETCD_узла>` на реальные IP-адреса ваших ETCD-серверов. Метка `k8s-app: etcd-metrics` в `Service` и `Endpoints` используется `ServiceMonitor` для обнаружения.

### 3. Создание ServiceMonitor для ETCD

`ServiceMonitor` инструктирует Prometheus, как собирать метрики с созданного Service.

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: etcd-k8s-monitor
  namespace: kube-system # Namespace, где развернут Service
  labels:
    release: prometheus-stack # Важно: эта метка должна соответствовать 'release' метке вашего Prometheus,
                            # управляемого kube-prometheus-stack. Обычно это 'prometheus-stack' или 'rancher-monitoring'.
spec:
  jobLabel: k8s-app
  endpoints:
  - port: metrics
    interval: 30s # Интервал сбора метрик
    scheme: https # ETCD использует HTTPS
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
      # InsecureSkipVerify: true # Использовать с осторожностью, только для отладки
    metricRelabelings: # Опционально: отфильтровать ненужные метрики
    - sourceLabels: [__name__]
      regex: 'etcd_debugging_mvcc_db_total_size_in_bytes|etcd_server_has_leader|...'
      action: keep
  selector:
    matchLabels:
      k8s-app: etcd-metrics # Соответствует метке Service и Endpoints
  namespaceSelector:
    matchNames:
    - kube-system # Namespace, где находится Service
```

**Важные параметры `ServiceMonitor`**:

* `namespace`: Должен быть тем же `namespace`, что и `Service`/`Endpoints`.
* `labels.release`: Критически важен, так как Prometheus Operator использует эту метку для связывания `ServiceMonitor` с конкретным экземпляром Prometheus. Замените `prometheus-stack` на `rancher-monitoring`, если вы используете Rancher.
* `scheme: https`: Указывает, что метрики собираются по HTTPS.
* `tlsConfig`: Конфигурация TLS, указывающая на `Secret` с клиентскими сертификатами ETCD.
* `selector.matchLabels`: Должен соответствовать меткам `Service` и `Endpoints`.
* `namespaceSelector.matchNames`: Указывает, в каких `namespaces` искать Service.

После применения этих манифестов Prometheus должен начать собирать метрики с ETCD, которые затем станут доступны для визуализации в Grafana.

### Сбор бизнес-метрик приложений с помощью ServiceMonitor

`ServiceMonitor` — это мощный Custom Resource, предоставляемый Prometheus Operator, который позволяет динамически настраивать Prometheus для сбора метрик с различных целей. Помимо мониторинга системных компонентов, он активно используется для сбора бизнес-метрик с пользовательских приложений.

**Основные принципы:**

1. **Обнаружение Service:** `ServiceMonitor` указывает Prometheus Operator, какой Kubernetes Service он должен мониторить, используя метки (label selector).
2. **Эндпоинты:** Определяет, по какому порту и пути в `Service` доступны метрики (например, `/metrics`).
3. **Ассоциация с Prometheus:** Экземпляр Prometheus, управляемый Prometheus Operator, будет автоматически настроен на сбор метрик с таргетов, соответствующих `ServiceMonitor`. Для Rancher-мониторинга критически важна метка `release: rancher-monitoring`.

**Пример ServiceMonitor для пользовательского приложения:**

Предположим, у вас есть приложение, развернутое в `namespace test-app`, которое предоставляет метрики на пути `/metrics` через порт `web` в своем `Service` с меткой `app: test-app`.

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: test-app-monitor
  namespace: test-app # ServiceMonitor разворачивается в том же namespace, что и приложение
  labels:
    release: rancher-monitoring # Должно совпадать с release-меткой Prometheus, управляемого Rancher
spec:
  selector:
    matchLabels:
      app: test-app # Соответствует метке 'app' Service вашего приложения
  endpoints:
  - port: web # Имя порта, определенного в Service вашего приложения
    path: /metrics # Путь, по которому доступны метрики
    interval: 15s # Интервал сбора метрик
```

**Пояснения:**

* **`metadata.namespace`**: `ServiceMonitor` обычно развертывается в том же `namespace`, что и `Service` приложения, которое он мониторит.
* **`labels.release: rancher-monitoring`**: Эта метка критически важна. Она позволяет экземпляру Prometheus, развернутому Rancher (имеющему аналогичную `release`-метку), обнаружить и использовать этот `ServiceMonitor`. Если эта метка не совпадает, Prometheus не будет собирать метрики.
* **`spec.selector.matchLabels`**: Указывает `ServiceMonitor`, какие `Service` он должен выбрать. Эти метки должны точно совпадать с метками `Service` вашего приложения.
* **`spec.endpoints`**: Определяет, к какому порту (по имени, как определено в `Service`) и по какому пути обращаться за метриками.
* **`interval: 15s`**: Указывает интервал сбора метрик. Более частый сбор (например, 15 секунд) может быть полезен для бизнес-метрик, но увеличивает нагрузку на Prometheus.

После применения этого `ServiceMonitor` Prometheus Operator автоматически обновит конфигурацию Prometheus, и тот начнет собирать метрики с вашего приложения. Проверить статус сбора можно в UI Prometheus в разделе "Targets".

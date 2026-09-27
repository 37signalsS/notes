# Конфигурация прочих компонентов в kube-prometheus-stack

## Определения

**Прочие компоненты kube-prometheus-stack** — вспомогательные элементы Helm-чарта, обеспечивающие работу стека мониторинга: управление доступом (RBAC), автоматическая перезагрузка конфигураций, стандартные правила алертов, агрегация алертов через Thanos Ruler, сбор метрик через Pushgateway и мониторинг системных компонентов Kubernetes.

> **См. также:** [Pushgateway — общая информация](../../pushgateway.md), [Prometheus Operator CRD](../operator/concepts.md).

## Основные концепции

### RBAC и Service Account

Управление правами доступа критично для работы Оператора, так как ему необходим доступ к API Kubernetes для обнаружения целей (Service Discovery).

| Параметр | Описание | Значение по умолчанию |
| :--- | :--- | :--- |
| `rbac.create` | Создание ClusterRole и ClusterRoleBinding для Prometheus Operator. | `true` |
| `serviceAccount.create` | Создание ServiceAccount для каждого компонента. | `true` |
| `serviceAccount.name` | Имя существующего ServiceAccount (если `create: false`). | `""` |
| `global.rbac.create` | Глобальный переключатель RBAC для всех компонентов чарта. | `true` |

**Стандартные права (ClusterRole), требуемые для полноценной работы:**

| Ресурс | Группа API | Глаголы (Verbs) | Зачем |
| :--- | :--- | :--- | :--- |
| `nodes`, `pods`, `services` | `""` (core) | `get, list, watch` | Service Discovery целей |
| `endpoints`, `endpointslices` | `""` / `discovery.k8s.io` | `get, list, watch` | Актуальные IP целей (EndpointSlice предпочтительнее) |
| `ingresses` | `networking.k8s.io` | `get, list, watch` | Discovery для Ingress-мониторинга |
| `configmaps`, `secrets` | `""` (core) | `get, list, watch` | Чтение конфигураций |
| `services`, `endpointslices` | `""` / `discovery.k8s.io` | `create, update, patch` | Управление ресурсами мониторинга (если требуется) |
| `statefulsets` | `apps` | `get, list, watch, update, patch` | Управление инстансами Prometheus |
| `prometheuses`, `*monitors` | `monitoring.coreos.com` | `*` | Управление собственными CRD |

**Рекомендация:** Оставляйте `create: true`. При использовании существующих ServiceAccount (например, созданных через IaC-инструменты) укажите `name` и установите `create: false`. В production используйте ClusterRole с минимальными правами: исключите `create, update, patch, delete` для ресурсов, которые не требуют изменения.

### ConfigMap Reload (Sidecar)

Механизм автоматической перезагрузки конфигурации без перезапуска Pod.

| Параметр | Описание | Значение по умолчанию |
| :--- | :--- | :--- |
| `configmapReload.prometheus.enabled` | Sidecar для автоперезагрузки Prometheus. | `true` |
| `configmapReload.alertmanager.enabled` | Sidecar для автоперезагрузки Alertmanager. | `true` |
| `configmapReload.container.image` | Образ `ghcr.io/prometheus-operator/prometheus-config-reloader`. | Актуальная версия |
| `configmapReload.resources` | Requests/limits для reload-контейнера. | `{}` |

**Принцип работы:** Sidecar отслеживает изменения ConfigMap/Secret и отправляет HTTP POST запрос на `/-/reload` основному контейнеру. С версии Оператора v0.70+ многие функции релоадера встроены в основной бинарный файл Оператора, но sidecar всё ещё используется для обеспечения совместимости с конфигурационными секретами.

**Практические нюансы:**
- **Имя контейнера в Pod:** В разных версиях чарта контейнер может называться `configmap-reload` или `prometheus-config-reloader`. Используйте `kubectl get pod <name> -n monitoring -o jsonpath='{.spec.containers[*].name}'` для определения точного имени.
- **Гранулярность перезагрузки:** Изменение `PodMonitor` перезагружает конфигурацию, но не останавливает уже запущенные процессы скрапинга.
- **Гонка состояний (Race Condition):** При одновременном изменении нескольких ServiceMonitor/PrometheusRule возможны множественные reload-ы. Sidecar использует debounce-механизм для снижения частоты перезагрузок.

### Правила алертов по умолчанию (defaultRules)

Набор преднастроенных `PrometheusRule` для базового мониторинга состояния компонентов кластера и стека.

| Параметр | Описание | Значение по умолчанию |
| :--- | :--- | :--- |
| `defaultRules.create` | Создание стандартных правил алертов. | `true` |
| `defaultRules.rules.*` | Включение/отключение отдельных групп правил. | `true` |
| `defaultRules.additionalRuleLabels` | Добавление лейблов ко всем правилам. | `{}` |
| `defaultRules.additionalRuleAnnotations` | Добавление аннотаций ко всем правилам. | `{}` |

**Группы правил (Актуальный список 2024–2025):**

| Группа | Описание | Когда отключать |
| :--- | :--- | :--- |
| `alertmanager` | Состояние Alertmanager, кластерная связность (gossip). | При использовании кастомных правил. |
| `etcd` | Мониторинг etcd: лидерство, задержки, размер БД. | Если etcd не управляется вами. |
| `general` | Общие алерты (TargetDown, Watchdog). | Редко — полезно для всех. |
| `k8s` | Базовые правила Kubernetes: состояния подов, deployments, jobs. | Редко — полезно для всех. |
| `kubeApiserverAvailability` | Доступность API-сервера (код ответа 5xx, latency). | Редко. |
| `kubeApiserverBurnrate` | Error Burnrate для API-сервера (SLO-based). | При использовании кастомных SLO. |
| `kubelet` | Алерты для kubelet: состояние подов, давление на ресурсы. | При внешнем мониторинге узлов. |
| `nodeExporterAlerting` | Алерты Node Exporter (CPU, Disk, Mem). | При использовании своих порогов. |
| `nodeExporterRecording` | Правила записи (агрегаты для дашбордов). | Для экономии ресурсов. |
| `prometheus` | Мониторинг самого Prometheus (TSDB, конфигурация, WAL). | Редко. |
| `windows` | Алерты для Windows-узлов. | Если в кластере нет Windows-нод. |

### Thanos Ruler

| Параметр | Описание | Значение по умолчанию |
| :--- | :--- | :--- |
| `thanosRuler.enabled` | Включение Thanos Ruler для агрегации алертов. | `false` |
| `thanosRuler.replicas` | Количество реплик (рекомендуется 2 для HA). | `1` |
| `thanosRuler.resources` | Requests/limits CPU/memory. | `{}` |
| `thanosRuler.thanosRulerSpec.ruleSelector` | Селектор для PrometheusRule. | `{}` |
| `thanosRuler.thanosRulerSpec.alertmanagersConfig` | Конфигурация Alertmanager для отправки алертов. | `{}` |

**Когда использовать:** Позволяет вычислять правила алертов над данными из нескольких Prometheus (например, в распределённой архитектуре с Thanos Querier). Ruler работает как отдельный компонент, который может выполнять `PrometheusRule` над глобальным набором данных, что обеспечивает централизованный алертинг в мульти-кластерных сценариях.

### Push Gateway

| Параметр | Описание | Значение по умолчанию |
| :--- | :--- | :--- |
| `pushgateway.enabled` | Включение Push Gateway. | `false` |
| `pushgateway.replicaCount` | Количество реплик. | `1` |
| `pushgateway.resources` | Requests/limits CPU/memory. | `{}` |
| `pushgateway.persistentVolume.enabled` | Сохранение метрик между перезапусками. | `false` |
| `pushgateway.persistentVolume.size` | Размер хранилища для метрик. | `2Gi` |

**Важно:** Используйте только для задач, которые нельзя опросить по pull-модели (batch jobs, CI/CD пайплайны). Не используйте для обычных сервисов. Gateway хранит метрик в памяти и на диске (при включённом persistence), что создаёт риск утечки данных при отсутствии retention-политики.

### Мониторинг Control Plane

| Параметр | Описание | Значение по умолчанию |
| :--- | :--- | :--- |
| `kubeApiServer.enabled` | Мониторинг API Server. | `true` |
| `kubeControllerManager.enabled` | Мониторинг Controller Manager. | `false` |
| `kubeScheduler.enabled` | Мониторинг Scheduler. | `false` |
| `kubeEtcd.enabled` | Мониторинг etcd. | `true` |
| `kubeProxy.enabled` | Мониторинг kube-proxy. | `true` |

**Важные нюансы:**

- **kube-controller-manager / kube-scheduler:** По умолчанию слушают `127.0.0.1`. Нужно изменить на `0.0.0.0` в манифестах статических подов (`/etc/kubernetes/manifests/`) на мастер-нодах. Без этого Prometheus не сможет собрать метрики.
- **etcd:** Требует доступа к сертификатам. Можно прокинуть секрет с сертификатами в под Prometheus или использовать `insecureSkipVerify: true` (не рекомендуется для production).
- **EndpointSlice vs Endpoints:** С 2025 года рекомендуется использовать `EndpointSlice` для снижения нагрузки на API-сервер. Prometheus Operator поддерживает оба типа ресурсов.

## Практические сценарии

### Production-конфигурация (Пример)

```yaml
rbac:
  create: true

configmapReload:
  prometheus:
    resources:
      requests: { cpu: 10m, memory: 16Mi }
      limits: { cpu: 50m, memory: 64Mi }

defaultRules:
  create: true
  rules:
    nodeExporterAlerting: true
    nodeExporterRecording: true
  additionalRuleLabels:
    cluster: "prod-main"

pushgateway:
  enabled: true
  persistentVolume:
    enabled: true
    size: 2Gi
```

### Валидация конфигурации

Перед применением `helm upgrade` проверяйте, что все компоненты корректно сконфигурированы:

```bash
# 1. Dry-run: проверка синтаксиса values.yaml
helm template monitoring prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  -f values.yaml | kubectl apply --dry-run=client -f -
# → все ресурсы должны пройти валидацию без ошибок

# 2. Проверка CRD
kubectl get crd | grep monitoring.coreos.com
# → prometheuses.monitoring.coreos.com
# → alertmanagers.monitoring.coreos.com
# → servicemonitors.monitoring.coreos.com
# → podmonitors.monitoring.coreos.com
# → prometheusrules.monitoring.coreos.com
# → probes.monitoring.coreos.com
# → alertmanagerconfigs.monitoring.coreos.com

# 3. Проверка RBAC (ClusterRole и Binding)
kubectl get clusterrole,clusterrolebinding | grep prometheus
# → Должны быть созданы: prometheus-operator, prometheus-k8s (или аналоги)
```

### Настройка etcd (On-prem кластер)

```yaml
kubeEtcd:
  enabled: true
  service:
    enabled: true
    port: 2381
    targetPort: 2381
  serviceMonitor:
    scheme: https
    caFile: /etc/prometheus/secrets/etcd-certs/ca.crt
    certFile: /etc/prometheus/secrets/etcd-certs/client.crt
    keyFile: /etc/prometheus/secrets/etcd-certs/client.key
```

### Проверка работы ConfigMap Reload

```bash
# Список контейнеров в поде Prometheus
kubectl get pods -n monitoring -l app.kubernetes.io/name=prometheus -o jsonpath='{.items[*].spec.containers[*].name}'
# → prometheus configmap-reload (или prometheus-config-reloader)

# Логи релоадера
kubectl logs -n monitoring -l app.kubernetes.io/name=prometheus -c configmap-reload

# Тест: измените любой PrometheusRule и проверьте логи
kubectl patch prometheusrule <name> --type merge -p '{"metadata":{"labels":{"test":"reload"}}}'
```

### Использование Push Gateway в CI/CD (Bash)

```bash
#!/bin/bash
JOB_NAME="backup-db"
START=$(date +%s)

# Команда бэкапа
./backup.sh
STATUS=$?

END=$(date +%s)
DURATION=$((END - START))

# Отправка в Pushgateway
cat <<EOF | curl --data-binary @- http://pushgateway.monitoring.svc:9091/metrics/job/$JOB_NAME
# HELP backup_duration_seconds Время выполнения бэкапа
# TYPE backup_duration_seconds gauge
backup_duration_seconds $DURATION
# HELP backup_status Статус бэкапа (0 - успех)
# TYPE backup_status gauge
backup_status $STATUS
EOF
```

### Thanos Ruler для распределённой архитектуры

```yaml
thanosRuler:
  enabled: true
  replicas: 2
  thanosRulerSpec:
    ruleSelector:
      matchLabels:
        thanos-ruler: "true"
    alertmanagersConfig:
      secret:
        name: alertmanager-main-db # Секрет с конфигом Alertmanager
        key: alertmanager.yaml
    # Для интеграции с Thanos Querier
    # thanosQuery:
    #   endpoints:
    #     - dnssrv+http://thanos-query.monitoring.svc.cluster.local:10901
```

### Апгрейд и откат компонентов

```bash
# Перед апгрейдом: экспорт текущих значений
helm get values monitoring -n monitoring > backup-values.yaml
kubectl get servicemonitor,podmonitor,prometheusrule,alertmanagerconfig \
  -n monitoring -o yaml > backup-custom-resources.yaml

# Выполнение апгрейда
helm upgrade monitoring prometheus-community/kube-prometheus-stack \
  -n monitoring \
  -f values.yaml \
  --version 55.x.x

# Проверка rollout
kubectl rollout status statefulset/prometheus-operated -n monitoring --timeout=5m
kubectl rollout status statefulset/alertmanager-monitoring-kube-prometheus-alertmanager -n monitoring --timeout=5m

# При проблемах: откат к предыдущей версии
helm rollback monitoring -n monitoring
```

### Очистка окружения

```bash
# Удаление релиза (сохранение CRD и данных)
helm uninstall monitoring -n monitoring

# Удаление namespace (если пустой)
kubectl delete namespace monitoring

# При необходимости удалить PVC
kubectl delete pvc -n monitoring -l app.kubernetes.io/instance=monitoring

# Удаление секретов с сертификатами (etcd)
kubectl delete secret kube-etcd-client-certs -n monitoring
```

## Дополнительная информация

### Диагностика и типичные проблемы

| Симптом | Вероятная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Target status: DOWN** | Ошибка RBAC | `kubectl auth can-i get endpoints --namespace <ns>` | Убедитесь, что ClusterRole Prometheus имеет доступ к ресурсам. |
| **Target status: DOWN** | Ошибка селектора | Проверка labels на сервисе и `matchLabels` в ServiceMonitor | Сравните labels в сервисе и селектор в ServiceMonitor. |
| **Target status: DOWN** | TLS error | Логи Prometheus: `failed to scrape` | Проверьте `serverName`, CA, пути к сертификатам. |
| **ConfigMap Reload не срабатывает** | Проблемы с permissions | `kubectl logs -n monitoring -c configmap-reload` | Проверьте права ServiceAccount на ConfigMap/Secret. |
| **Pod CrashLoopBackOff** | OOMKilled | `kubectl get pod <pod> -n monitoring -o yaml` | Увеличьте memory limit, включите native-histograms. |
| **Pod CrashLoopBackOff** | Неверный путь к сертификатам | `kubectl describe pod <pod> -n monitoring` | Проверьте mounts: paths в `volumeMounts` должны совпадать с `tlsConfig`. |
| **Метрики не обновляются** | Ошибка relabeling | Prometheus UI → Service Discovery | Проверьте `metricRelabelings` и `relabelings`. |
| **EndpointSlice не создаётся** | Отсутствует Headless Service | `kubectl get svc,endpointslice -n <ns>` | Создайте Service с `clusterIP: None` перед EndpointSlice. |
| **etcd Target DOWN (403)** | Ошибка RBAC | `kubectl logs -n monitoring -l app.kubernetes.io/name=prometheus` | Убедитесь, что ClusterRole имеет доступ к Secret в namespace с сертификатами. |

### Подбираемые параметры ресурсов (эмпирически)

| Компонент | Параметр | Значение (базовое) | Метрика для мониторинга |
| :--- | :--- | :--- | :--- |
| configmapReload | `requests.memory` | `16Mi` | `container_memory_working_set_bytes` |
| configmapReload | `requests.cpu` | `10m` | `rate(container_cpu_usage_seconds_total[5m])` |
| pushgateway | `requests.memory` | `64Mi` | `container_memory_working_set_bytes` |
| pushgateway | `retention` | `15d` | Размер PVC (`kubelet_volume_stats_available_bytes`) |
| thanosRuler | `requests.memory` | `512Mi` | `container_memory_working_set_bytes` |

### Ограничения и особые случаи (Edge Cases)

1. **Лимит размера Secret (1 МБ):** Kubernetes ограничивает размер Secret 1 МБ. Если сертификаты и ключи слишком велики (например, цепочка из 10+ сертификатов), используйте отдельные Secret для CA и клиентских ключей.
2. **ReadOnlyRootFilesystem:** При использовании `readOnlyRootFilesystem: true` в Prometheus убедитесь, что пути к сертификатам корректно монтируются через `volumes` и `volumeMounts`.
3. **Configuration Drift:** Изменения, сделанные через UI Grafana/Prometheus, не сохраняются обратно в Helm-чарт. Все изменения должны вноситься через `values.yaml` или отдельные манифесты.
4. **hostNetwork:** Из-за `hostNetwork: true` у статических подов Control Plane нельзя использовать стандартный kube-proxy для доступа. Обязательно используйте IP-адреса мастер-узлов в Endpoints/EndpointSlice.
5. **Разное количество master-узлов:** При изменении количества master-узлов не забудьте обновить Endpoints/EndpointSlice.
6. **etcd v2 store:** В etcd 3.7+ v2 store полностью удалён. Убедитесь, что ваш кластер использует v3 API.

### Связанные темы

* [Prometheus Operator — архитектура](../operator/concepts.md)
* [Конфигурация Alertmanager](./alertmanager_config.md)
* [Thanos — общее описание](../../scaling/thanos_overview.md)

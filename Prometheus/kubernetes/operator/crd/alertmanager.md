# Alertmanager — Концепции (CRD)

## Определения

**`kind: Alertmanager`** — Custom Resource Definition в Prometheus Operator, предназначенный для декларативного описания развёртывания и жизненного цикла экземпляра Alertmanager в Kubernetes. Ресурс управляет созданием StatefulSet, Service, Secret и конфигурацией кластеризации.

**Reconciliation Loop в Alertmanager CRD** — процесс, при котором Оператор отслеживает изменения в объекте `Alertmanager` и связанных с ним `AlertmanagerConfig`, обеспечивая актуальность конфигурации маршрутизации и состояния подов.

**API version:** `monitoring.coreos.com/v1`

> **См. также:** [Alertmanager (общий обзор)](../../../alertmanager.md) — архитектура, маршрутизация и дедупликация.

## Базовые концепции

### Архитектура управления экземпляром

Alertmanager CRD является декларативным описанием желаемого состояния. Оператор отслеживает изменения ресурса и автоматически управляет инфраструктурными объектами:

1.  **Контроллер (Controller):** Отслеживает ресурс `Alertmanager` и вычисляет разницу между желаемым и текущим состоянием.
2.  **Генератор (Generator):** На основе селекторов (`alertmanagerConfigSelector`, `alertmanagerConfigNamespaceSelector`) собирает все `AlertmanagerConfig` ресурсы, агрегируя их в единый `alertmanager.yaml`.
3.  **Config-Reloader (Sidecar):** Sidecar-контейнер в поде Alertmanager обнаруживает изменения в Secret/ConfigMap с конфигурацией и инициирует HTTP-запрос `/-/reload` к API Alertmanager для горячей перезагрузки без рестарта пода.
4.  **Инфраструктура:** StatefulSet управляет подами Alertmanager, Service обеспечивает доступ, PVC предоставляет персистентное хранилище для состояния (Silences), ServiceAccount и RBAC управляют правами доступа.

### Селекторы и изоляция конфигурации

Alertmanager CRD использует селекторы для определения, какие `AlertmanagerConfig` ресурсы должны быть включены в конфигурацию инстанса:

- **`spec.alertmanagerConfigSelector`:** Селектор меток для выбора `AlertmanagerConfig` в разрешенных namespace. Если пустой (`{}`), Alertmanager не подхватывает никакие конфигурации.
- **`spec.alertmanagerConfigNamespaceSelector`:** Селектор для ограничения namespace, из которых загружаются `AlertmanagerConfig`. По умолчанию используется собственный namespace инстанса.
- **`spec.alertmanagerConfigMatcherStrategy`:** Стратегия применения matcher'ов (опционально).

> **Ловушка «Пустого селектора»:** В Helm-чарте `kube-prometheus-stack` параметр `alertmanagerConfigSelector` по умолчанию часто пуст `{}`. Это означает, что Alertmanager **не будет подхватывать** никакие `AlertmanagerConfig`. Для активации необходимо обновить `values.yaml`:
> ```yaml
> alertmanager:
>   alertmanagerSpec:
>     alertmanagerConfigSelector:
>       matchLabels:
>         resource: prometheus # Любая метка на ваш выбор
> ```

### Взаимосвязь ресурсов

| Ресурс | Роль | Описание |
| :--- | :--- | :--- |
| **Alertmanager** | Инфраструктура | Описывает "как" и "где" запущен инстанс (ресурсы, PVC, TLS). |
| [AlertmanagerConfig](./alertmanagerconfig.md) | Маршрутизация | Описывает "кому" и "как" отправлять алерты (receivers, routes). |
| [Prometheus](./prometheus.md) | Генератор алертов | Отправляет алерты в инстанс Alertmanager. |
| [PrometheusRule](./prometheusrule.md) | Правила | Генерирует алерты на основе метрик Prometheus. |

### Новые возможности (2025–2026)

*   **Нативная конфигурация (`spec.alertmanagerConfiguration`):** Экспериментальная возможность описывать настройки Alertmanager напрямую в CRD, минуя создание внешних секретов (`configSecret`). Имеет приоритет при заполнении обоих полей.
*   **Имена пиров (v0.30.0+):** Оператор использует имена подов в качестве имен пиров в кластере Gossip, что повышает стабильность кластеризации и упрощает диагностику по сравнению с ID-based подходом.
*   **Нативный HTTPS (`spec.web`):** Настройка TLS для веб-интерфейса напрямую через CRD, включая mTLS и выбор криптографических кривых.
*   **Безопасный Gossip (`spec.clusterTLS`):** Шифрование трафика между узлами кластера Alertmanager по протоколу Gossip (порт 9094).
*   **Topology Aware Routing:** Интеграция с Kubernetes Topology (>= 1.35) для зонального шардирования и минимизации межзонального трафика.
*   **Подресурс Status:** Поддержка условий (`Conditions`), таких как `Reconciled`, для GitOps-инструментов, позволяющая отслеживать завершение применения конфигурации.
*   **Специфичные для Alertmanager порты:** Gossip-порт `9094` (UDP/TCP) автоматически настраивается Operator'ом через Headless Service. Визуализация порта в StatefulSet требует явного указания `containerPort` только в кастомных сценариях.

## Практические сценарии

### Сценарий 1: Отказоустойчивая Production-конфигурация (HA + TLS)

Настройка кластера из 3 реплик с включенным TLS для веб-интерфейса и персистентным хранилищем.

```yaml
apiVersion: monitoring.coreos.com/v1
kind: Alertmanager
metadata:
  name: main
  namespace: monitoring
spec:
  replicas: 3
  version: v0.30.0
  web:
    tlsConfig:
      cert:
        secret:
          name: alertmanager-tls
          key: tls.crt
      keySecret:
        name: alertmanager-tls
        key: tls.key
  storage:
    volumeClaimTemplate:
      spec:
        storageClassName: fast-ssd
        accessModes: ["ReadWriteOnce"]
        resources:
          requests:
            storage: 10Gi
  alertmanagerConfigSelector:
    matchLabels:
      release: monitoring
```

### Сценарий 2: Прямая конфигурация через CRD (Experimental)

Использование поля `alertmanagerConfiguration` для задания глобальных настроек без использования Secret.

```yaml
apiVersion: monitoring.coreos.com/v1
kind: Alertmanager
metadata:
  name: direct-config
spec:
  replicas: 3
  alertmanagerConfiguration:
    name: main-config
    global:
      resolveTimeout: 5m
      httpConfig:
        followRedirects: true
    templates:
      - name: custom-templates
        key: alert.tmpl
```

### Сценарий 3: Запуск в Host Network

Использование сетевого пространства хоста для обхода ограничений CNI или минимизации задержек.

```yaml
spec:
  hostNetwork: true
  dnsPolicy: ClusterFirstWithHostNet
  securityContext:
    runAsNonRoot: true
    runAsUser: 1000
```

### Сценарий 4: Мультитенантная изоляция через AlertmanagerConfig

Разные команды управляют своими маршрутами и получателями в отдельных namespace, не затрагивая глобальную конфигурацию. Alertmanager агрегирует конфигурации через селекторы.

```yaml
apiVersion: monitoring.coreos.com/v1
kind: Alertmanager
metadata:
  name: main
  namespace: monitoring
spec:
  replicas: 3
  alertmanagerConfigSelector:
    matchLabels:
      team: platform
  alertmanagerConfigNamespaceSelector:
    matchNames:
      - monitoring
      - team-a
      - team-b
  alertmanagerConfigMatcherStrategy:
    type: Default
```

### Сценарий 5: Безопасное развертывание (TLS + mTLS + ClusterTLS + Proxy)

Полная изоляция трафика: HTTPS для UI, mTLS для внешних запросов, шифрование Gossip, корпоративный прокси.

```yaml
apiVersion: monitoring.coreos.com/v1
kind: Alertmanager
metadata:
  name: main
  namespace: monitoring
spec:
  replicas: 3
  web:
    tlsConfig:
      cert:
        secret:
          name: alertmanager-tls
          key: tls.crt
      keySecret:
        name: alertmanager-tls
        key: tls.key
    httpConfig:
      proxyURL: http://squid.corp.internal:3128
  clusterTLS:
    tlsConfig:
      cert:
        secret:
          name: alertmanager-gossip-tls
          key: tls.crt
      keySecret:
        name: alertmanager-gossip-tls
        key: tls.key
      ca:
        secret:
          name: alertmanager-gossip-ca
          key: ca.crt
  storage:
    volumeClaimTemplate:
      spec:
        storageClassName: fast-ssd
        resources:
          requests:
            storage: 10Gi
```

### Сценарий 6: Управление ресурсами и QoS (Guaranteed)

Перевод подов в класс `Guaranteed` для защиты от OOMKill и обеспечения стабильной производительности.

```yaml
spec:
  replicas: 3
  resources:
    requests:
      cpu: 500m
      memory: 2Gi
    limits:
      cpu: 500m
      memory: 2Gi
  storage:
    volumeClaimTemplate:
      spec:
        storageClassName: fast-ssd
        accessModes: ["ReadWriteOnce"]
        resources:
          requests:
            storage: 20Gi
  podDisruptionBudget:
    minAvailable: 2
```

### Сценарий 7: Внешний ServiceAccount с IRSA

Использование AWS IAM Roles for Service Accounts для доступа к внешним секретам в AWS Secrets Manager без статичных ключей.

```yaml
spec:
  serviceAccountName: alertmanager-sa
  volumeMounts:
    - name: alertmanager-config-volume
      mountPath: /etc/alertmanager/config
  volumes:
    - name: alertmanager-config-volume
      secret:
        secretName: alertmanager-external-config
```

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: alertmanager-sa
  namespace: monitoring
  annotations:
    eks.amazonaws.com/role-arn: arn:aws:iam::123456789012:role/alertmanager-role
```

### Сценарий 8: Сетевая конфигурация Gossip-кластера и Topology

Гарантирование доступности порта 9094 для Gossip и распределение подов по зонам доступности.

```yaml
spec:
  replicas: 3
  version: v0.30.0
  topologySpreadConstraints:
    - maxSkew: 1
      topologyKey: "topology.kubernetes.io/zone"
      whenUnsatisfiable: ScheduleAnyway
      labelSelector:
        matchLabels:
          app.kubernetes.io/name: alertmanager
  podDisruptionBudget:
    minAvailable: 2
  clusterAdvertiseAddress: 0.0.0.0:9094
```

## Дополнительная информация

### Основные параметры спецификации (v1)

| Параметр | Описание | Значение / Особенности |
| :--- | :--- | :--- |
| **`replicas`** | Количество подов. | Минимум 3 для HA. |
| **`version`** | Версия Alertmanager. | v0.30+ для стабильного пиринга. |
| **`alertmanagerConfiguration`** | Встроенная конфигурация. | Экспериментально; заменяет `configSecret`. |
| **`hostNetwork`** | Использование сети хоста. | Добавлено в 2025 году. |
| **`web.tlsConfig`** | Настройка HTTPS UI. | Заменяет ручное создание `web-config.yaml`. |
| **`web.httpConfig`** | Прокси и дополнительные настройки HTTP. | Поддержка `proxyURL`, `noProxy`. |
| **`clusterTLS`** | TLS для Gossip (порт 9094). | Требует Alertmanager v0.24+. |
| **`paused`** | Остановка reconciliation. | Используется при ручных правках StatefulSet. |
| **`retention`** | Время хранения данных. | По умолчанию 120h (5 дней). |
| **`storage`** | Конфигурация PVC. | `volumeClaimTemplate` для TSDB. |
| **`serviceAccountName`** | ServiceAccount для пода. | Для RBAC и IRSA. |
| **`topologySpreadConstraints`** | Распределение по топологии. | Минимизация межзонального трафика. |
| **`alertmanagerConfigSelector`** | Селектор AlertmanagerConfig. | По умолчанию пуст `{}`. |
| **`alertmanagerConfigNamespaceSelector`** | Селектор namespace для AlertmanagerConfig. | По умолчанию собственный namespace. |
| **`clusterAdvertiseAddress`** | Адрес для Gossip-пиринга. | `0.0.0.0:9094` для автоматического обнаружения. |

### Статус реконсиляции (Reconciliation Status)

С версии Operator v0.80+ объект `Alertmanager` предоставляет детальный статус:
- **`Reconciled`**: `True` означает, что текущая конфигурация успешно применена ко всем подам.
- **`Available`**: Сигнализирует о готовности минимального количества реплик.
- **`Warning`**: Содержит сообщения о депрекации полей или ошибках в `AlertmanagerConfig`.

### Требования RBAC

Для работы Alertmanager в кластере необходимы следующие права. При использовании `serviceAccountName` убедитесь, что роль содержит необходимые permissions:

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: alertmanager-sa
  namespace: monitoring
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: alertmanager-role
rules:
  - apiGroups: [""]
    resources: ["nodes", "pods", "services", "endpoints", "endpointslices"]
    verbs: ["get", "list", "watch"]
  - apiGroups: ["monitoring.coreos.com"]
    resources: ["alertmanagers", "alertmanagerconfigs"]
    verbs: ["get", "list", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: alertmanager-rolebinding
subjects:
  - kind: ServiceAccount
    name: alertmanager-sa
    namespace: monitoring
roleRef:
  kind: ClusterRole
  name: alertmanager-role
  apiGroup: rbac.authorization.k8s.io
```

### Валидация работоспособности

После развертывания проверьте следующие группы:

1.  **Статус реплик:**
    ```bash
    kubectl get pods -n monitoring -l app.kubernetes.io/name=alertmanager
    # Все реплики должны быть в статусе Running
    ```
2.  **Готовность кластера Gossip:**
    ```bash
    kubectl exec -it alertmanager-main-0 -n monitoring -- amtool cluster show
    # Должно отображаться 3 активных участника
    ```
3.  **Генерация конфигурации:**
    ```bash
    kubectl get secret alertmanager-main-generated -n monitoring -o jsonpath='{.data.alertmanager\.yaml}' | base64 -d
    # Проверьте наличие маршрутов и receivers из AlertmanagerConfig
    ```
4.  **Доступность UI:**
    ```bash
    kubectl port-forward svc/alertmanager-operated -n monitoring 9093
    curl -k https://localhost:9093/api/v2/status
    # Должен вернуться JSON с версией Alertmanager
    ```
5.  **Метрики:**
    ```bash
    # alertmanager_cluster_members должен равняться replicas (3)
    kubectl exec -it alertmanager-main-0 -n monitoring -- curl -s http://localhost:9093/metrics | grep cluster_members
    ```
6.  **Секреты TLS:**
    ```bash
    # Проверка срока действия сертификатов
    kubectl get secret alertmanager-tls -n monitoring -o jsonpath='{.data.tls\.crt}' | base64 -d | openssl x509 -noout -dates
    ```

### Ограничения и крайние случаи

1.  **Лимит размера Secret (1MB):** Общая конфигурация Alertmanager, включающая все `AlertmanagerConfig`, не должна превышать 1MB. При превышении Оператор не сможет создать/обновить Secret.
2.  **Пустой селектор:** Если `alertmanagerConfigSelector` не указан или пуст, Alertmanager игнорирует все `AlertmanagerConfig`.
3.  **Имена Receivers и TimeIntervals:** Должны быть уникальны в рамках одного Alertmanager инстанса. Конфликты имен приведут к ошибкам валидации.
4.  **Gossip порт 9094:** Должен быть доступен по UDP и TCP между всеми репликами Alertmanager внутри кластера. NetworkPolicy или Security Groups могут блокировать кластеризацию.
5.  **Кворум:** При нечетном количестве реплик (например, 3) кластер продолжает работать при отказе 1 узла. При 2 репликах потеря 1 узла приводит к потере кворума.
6.  **External Labels:** Не используйте одинаковые `externalLabels` для разных Alertmanager инстансов — это нарушит дедупликацию.
7.  **CEL-валидация:** Некорректные `AlertmanagerConfig` (например, несколько типов авторизации одновременно) отклоняются на уровне API-сервера с понятным сообщением.
8.  **Совместимость версий:** Версия Alertmanager в `spec.version` должна соответствовать возможностям используемых полей (например, `clusterTLS` требует v0.24+).

### Типичные проблемы и диагностика

#### Проблема 1: Alertmanager не видит AlertmanagerConfig

**Симптом:** В сгенерированном Secret отсутствуют маршруты из AlertmanagerConfig.

**Диагностика:**
```bash
# Проверьте селекторы в CRD
kubectl get alertmanager main -n monitoring -o yaml | grep -A 5 alertmanagerConfigSelector
# Проверьте лейблы на AlertmanagerConfig
kubectl get alertmanagerconfig -A --show-labels
```

**Решение:** Убедитесь, что `AlertmanagerConfig` имеет метки, соответствующие `alertmanagerConfigSelector`, и находится в namespace, разрешенном `alertmanagerConfigNamespaceSelector`.

#### Проблема 2: Кластер Gossip не образуется (split-brain)

**Симптом:** `amtool cluster show` показывает менее 3 участников.

**Диагностика:**
```bash
kubectl get pods -n monitoring -l app.kubernetes.io/name=alertmanager
kubectl logs -n monitoring alertmanager-main-1 -c alertmanager | grep -i gossip
```

**Решение:** Проверьте доступность порта 9094 (UDP/TCP) между подами. Убедитесь, что `clusterAdvertiseAddress` настроен корректно.

#### Проблема 3: Ошибка «Secret is invalid: data: Too long»

**Симптом:** Оператор не применяет изменения.

**Решение:** Уменьшите размер конфигурации (удалите избыточные receivers/inhibit rules) или используйте несколько Alertmanager инстансов с разными селекторами.

#### Проблема 4: TLS-ошибки при загрузке UI

**Симптом:** `curl -k https://...` возвращает `x509: certificate signed by unknown authority`.

**Решение:** Проверьте, что секрет `alertmanager-tls` содержит действительные `tls.crt` и `tls.key`, и срок их действия не истек.

### Лучшие практики

1.  **Минимум 3 реплики:** Обеспечивает кворум в Gossip-кластере и отказоустойчивость.
2.  **Совпадение версий:** Используйте версию Alertmanager, совместимую с `clusterTLS` и другими экспериментальными полями.
3.  **Имена пиров:** Используйте поды с именами, соответствующими шаблону StatefulSet, для стабильного пиринга.
4.  **Гарантированный QoS:** Устанавливайте `requests.memory == limits.memory` для перевода в класс `Guaranteed`.
5.  **Сетевая политика:** Открывайте порт `9094` (UDP/TCP) только между репликами Alertmanager внутри namespace.
6.  **Секреты TLS:** Используйте cert-manager для автоматического обновления сертификатов веб-интерфейса и Gossip.
7.  **Изоляция конфигурации:** Предпочитайте `AlertmanagerConfig` вместо нативной `alertmanagerConfiguration` в Production до стабилизации функции.
8.  **Мониторинг кластера:** Добавьте алерт на `alertmanager_cluster_members < replicas`.
9.  **Retention:** Храните Silences минимум 5 дней (120h) для возможности анализа инцидентов.
10. **Secrets:** Не храните токены ботов (Slack, Telegram) в ConfigMap — используйте Secret с явным именем и ключом.

### Связанные темы

*   **[AlertmanagerConfig CRD](./alertmanagerconfig.md)** — детальная настройка маршрутов и селекторов.
*   **[Prometheus CRD](./prometheus.md)** — настройка `alertmanager`-селекторов и Remote Write.
*   **[PrometheusRule CRD](./prometheusrule.md)** — генерация алертов.
*   **[High Availability](../high_availability.md)** — общие принципы отказоустойчивости стека.
*   **[Troubleshooting](../troubleshooting.md)** — диагностика проблем оператора и конфигурации.
*   **[Безопасность в Prometheus Operator](../Security/index.md)** — RBAC и TLS.

### См. также
* [Prometheus Operator API Specification (v1)](https://prometheus-operator.dev/docs/operator/api/)
* [Alertmanager Configuration Guide](https://prometheus.io/docs/alerting/latest/configuration/)

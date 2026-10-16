# Конфигурация Alertmanager в kube-prometheus-stack

## Определения

**Alertmanager в kube-prometheus-stack** — компонент Helm-чарта, развёртывающий Alertmanager как управляемое через Prometheus Operator приложение (обычно StatefulSet). В рамках чарта конфигурация реализуется на трёх уровнях:

1.  **Инфраструктурный уровень (`alertmanager.alertmanagerSpec`)** — описание параметров пода (ресурсы, реплики, хранилище, аффинити).
2.  **Глобальный конфигурационный уровень (`alertmanager.config`)** — формирование основного файла `alertmanager.yaml` (глобальные настройки, корневой маршрут).
3.  **Декларативный уровень (`AlertmanagerConfig` CRD)** — создание модульных конфигураций (маршруты и получатели) через отдельные Kubernetes-ресурсы.

> **См. также:** [Alertmanager — общая конфигурация](../../alertmanager.md), [Alertmanager CRD](../operator/crd/alertmanager.md).

## Архитектура

### Жизненный цикл конфигурации

```
values.yaml
    ├── alertmanager.config          → Secret (<name>-alertmanager-config)
    │       └── alertmanager.yaml     → Mount в pod Alertmanager
    │
    ├── AlertmanagerConfig CRD        → Operator агрегирует
    │       └── Secret (<name>-generated) → Config-Reloader
    │               └── POST /-/reload → Alertmanager
    │
    └── alertmanager.alertmanagerSpec → StatefulSet, Service, PVC
```

**Поток применения изменений:**

1. Пользователь изменяет `values.yaml` или применяет `AlertmanagerConfig`.
2. Prometheus Operator обнаруживает изменения через Kubernetes API Watch.
3. Если изменён `AlertmanagerConfig`, Operator агрегирует все выбранные конфигурации в единый `alertmanager.yaml` и записывает его в Secret.
4. Sidecar-контейнер `config-reloader` обнаруживает изменение Secret и отправляет HTTP POST на `/-/reload`.
5. Alertmanager перечитывает конфигурацию без рестарта пода.
6. Оператор обновляет статус объекта `Alertmanager` (подресурс `status.conditions`).

### Уровни конфигурации

| Уровень | KPS параметр | Объект Kubernetes | Ответственность |
| :--- | :--- | :--- | :--- |
| Инфраструктурный | `alertmanager.alertmanagerSpec` | StatefulSet, Service, PVC, PDB | Жизненный цикл подов, хранилище, ресурсы |
| Глобальный | `alertmanager.config` | Secret (`<release>-alertmanager-config`) | Глобальные настройки, корневой маршрут, receivers |
| Декларативный | `alertmanager.alertmanagerSpec.alertmanagerConfigSelector` | AlertmanagerConfig CRD → Secret (`<release>-generated`) | Маршруты команд, модульные receivers |

> **Примечание:** Имена секретов зависят от названия Helm-релиза. По умолчанию для релиза `monitoring` в namespace `monitoring` имена будут `monitoring-alertmanager-config` и `monitoring-alertmanager-generated`.

## Предварительные требования

- Namespace `monitoring` создан и активен.
- Helm-репозиторий `prometheus-community` добавлен (`helm repo add prometheus-community https://prometheus-community.github.io/helm-charts`).
- Версия Helm-чарта `kube-prometheus-stack` >= 88.1.x (актуальная на 2026 год).
- Kubernetes >= 1.28.
- Для `AlertmanagerConfig`: Prometheus Operator >= v0.57.0 (поддержка `v1beta1` API).
- Для `configSecret`: предварительно созданный Secret с валидным YAML.
- Для `tplConfig`: шаблонизатор Helm должен иметь доступ к переменным (включая `lookup` для чтения Secrets).

## Основные концепции

### Структура параметров в values.yaml

| Параметр | Описание | Значение по умолчанию |
| :--- | :--- | :--- |
| `alertmanager.enabled` | Включение/выключение компонента. | `true` |
| `alertmanager.apiVersion` | Версия API Alertmanager (рекомендуется `v2`). | `v2` |
| `alertmanager.alertmanagerSpec` | Спецификация для Prometheus Operator (ресурсы, хранилище, реплики). | `{}` |
| `alertmanager.config` | Тело конфигурации `alertmanager.yaml` (глобальные настройки, маршруты, receivers). | `{}` |
| `alertmanager.alertmanagerSpec.configSecret` | Имя внешнего Secret вместо встроенного `alertmanager.config`. | `""` |
| `alertmanager.tplConfig` | Включение Helm-шаблонизации внутри конфига. | `false` |
| `alertmanager.ingress.enabled` | Создание Ingress-ресурса для доступа к UI. | `false` |
| `alertmanager.configmapReload` | Параметры sidecar для автоперезагрузки. | `{}` |

### Высокая доступность (HA)

Alertmanager поддерживает кластеризацию для предотвращения потери уведомлений при сбое узла.

*   **Репликация:** Настраивается через `alertmanager.alertmanagerSpec.replicas`. Для промышленной среды рекомендуется `3` реплики (нечётное число обеспечивает кворум при отказе одного узла).
*   **Синхронизация:** Поды обмениваются данными (состоянием силенсов и уведомлений) через gossip-протокол. Оператор автоматически добавляет флаги `--cluster.peer` при `replicas > 1`.
*   **Дедупликация:** Выполняется на стороне Alertmanager. Если несколько реплик получают один и тот же алерт, пользователю уйдёт только одно уведомление.
*   **Порт Gossip:** Для кластеризации должен быть открыт порт `9094` (TCP/UDP) между всеми репликами Alertmanager.
*   **TopologySpreadConstraints:** Рекомендуется использовать `topologyKey: kubernetes.io/hostname` с `whenUnsatisfiable: ScheduleAnyway` для распределения подов по разным узлам.

### Хранилище и сохранение состояния

По умолчанию Alertmanager использует `emptyDir`, что приводит к потере силенсов (silences) и данных о доставке уведомлений при перезапуске подов.

Для сохранения состояния необходимо настроить Persistent Volume:

```yaml
alertmanager:
  alertmanagerSpec:
    storage:
      volumeClaimTemplate:
        spec:
          storageClassName: "standard" # Ваш StorageClass
          accessModes: ["ReadWriteOnce"]
          resources:
            requests:
              storage: 10Gi
```

**Важно:** При использовании `volumeClaimTemplate` убедитесь, что StorageClass поддерживает динамическое provisioning. Если используется существующий PVC, укажите `storage.volumeClaimTemplate` соответствующим образом.

### Интеграция с AlertmanagerConfig (CRD)

Это современный подход к управлению уведомлениями, позволяющий командам настраивать свои алерты самостоятельно.

*   **Селекторы:** Чтобы Alertmanager подхватывал CRD, в `values.yaml` должен быть настроен селектор:
    ```yaml
    alertmanager:
      alertmanagerSpec:
        alertmanagerConfigSelector:
          matchLabels:
            alertmanagerConfig: "enabled"
    ```
*   **Область видимости:** По умолчанию Alertmanager ищет CRD только в своём namespace. Для поиска по всему кластеру используйте `alertmanagerConfigNamespaceSelector: {}`.
*   **Ловушка пустого селектора:** В Helm-чарте `kube-prometheus-stack` параметр `alertmanagerConfigSelector` по умолчанию часто пуст `{}`. Это означает, что Alertmanager не будет подхватывать никакие `AlertmanagerConfig`. Для активации необходимо обновить `values.yaml` как показано выше.

### Config-Reloader и горячая перезагрузка

Sidecar-контейнер `config-reloader` отслеживает изменения в ConfigMap/Secret и инициирует HTTP POST на `/-/reload`. В `kube-prometheus-stack` управление reloader'ом реализовано через:

```yaml
alertmanager:
  configmapReload:
    enabled: true
    resources:
      requests:
        cpu: 50m
        memory: 64Mi
```

### Безопасное управление секретами

Хранение паролей (SMTP, Webhook tokens) напрямую в `values.yaml` (`alertmanager.config`) не рекомендуется. Существует три способа безопасной настройки:

1.  **Использование `configSecret`:** Вы заранее создаёте Secret с файлом `alertmanager.yaml` и указываете его имя.
    ```yaml
    alertmanager:
      alertmanagerSpec:
        configSecret: "custom-alertmanager-config"
    ```
2.  **Шаблонизация (`tplConfig: true`):** Использование Helm-шаблонизации для подстановки значений из Kubernetes Secrets через `lookup`.
3.  **AlertmanagerConfig с внешними секретами:** Использование полей `apiURL` и `secret` в receivers для ссылки на Kubernetes Secret с чувствительными данными.

### Подресурс статуса и отслеживание применения

С версии Prometheus Operator v0.80+ объект `Alertmanager` предоставляет детальный статус через подресурс `status`:

```yaml
status:
  conditions:
    - type: Reconciled
      status: "True"
      lastTransitionTime: "2025-09-15T10:00:00Z"
      reason: ReconciliationSucceeded
      message: "Successfully applied Alertmanager configuration"
```

| Поле | Описание |
| :--- | :--- |
| **`type: Reconciled`** | `True` означает, что конфигурация успешно применена ко всем подам. |
| **`type: Available`** | Сигнализирует о готовности минимального количества реплик. |
| **`type: Warning`** | Содержит сообщения о депрекации полей или ошибках в `AlertmanagerConfig`. |

## Практические сценарии

### Глобальная конфигурация (Production)

Пример настройки через `values.yaml` с интеграцией Slack и PagerDuty.

```yaml
alertmanager:
  enabled: true
  apiVersion: v2
  
  alertmanagerSpec:
    replicas: 3
    externalUrl: "https://alertmanager.example.com"
    resources:
      requests:
        cpu: 100m
        memory: 256Mi
      limits:
        cpu: 200m
        memory: 512Mi
    storage:
      volumeClaimTemplate:
        spec:
          storageClassName: "fast-ssd"
          accessModes: ["ReadWriteOnce"]
          resources:
            requests:
              storage: 10Gi
    alertmanagerConfigSelector:
      matchLabels:
        alertmanagerConfig: "enabled"

  config:
    global:
      resolve_timeout: 5m
      slack_api_url: "https://hooks.slack.com/services/TXXX/BXXX/XXXX"

    route:
      group_by: ['alertname', 'cluster', 'service']
      group_wait: 30s
      group_interval: 5m
      repeat_interval: 12h
      receiver: 'slack-default'
      routes:
        - matchers:
            - severity="critical"
          receiver: 'pagerduty-urgent'

    receivers:
      - name: 'slack-default'
        slack_configs:
          - channel: '#monitoring-alerts'
            send_resolved: true
            title: '[{{ .Status | toUpper }}] {{ .GroupLabels.alertname }}'
            text: "{{ range .Alerts }}{{ .Annotations.summary }}\n{{ end }}"

      - name: 'pagerduty-urgent'
        pagerduty_configs:
          - service_key: "YOUR-PAGERDUTY-KEY"
```

### Конфигурация с Telegram (Alertmanager 0.26+)

Начиная с Alertmanager 0.26, `telegram_configs` поддерживаются нативно. Ниже — пример маршрутизации по severity с отправкой в разные каналы Telegram.

```yaml
alertmanager:
  config:
    global:
      resolve_timeout: 5m
    route:
      group_by: ['alertname', 'job']
      group_wait: 30s
      group_interval: 5m
      repeat_interval: 12h
      receiver: 'telegram'
      routes:
        - matchers:
            - severity = "critical"
          receiver: 'telegram-critical'
          repeat_interval: 1h
    receivers:
      - name: 'telegram'
        telegram_configs:
          - bot_token: "${TELEGRAM_BOT_TOKEN}"
            chat_id: -123456789
            message: |
              {{ range .Alerts }}
              {{ .Status | toUpper }}: {{ .Annotations.summary }}
              {{ .Annotations.description }}
              {{ end }}

      - name: 'telegram-critical'
        telegram_configs:
          - bot_token: "${TELEGRAM_BOT_TOKEN}"
            chat_id: -1122334455
            message: |
              {{ range .Alerts }}
              🚨 CRITICAL: {{ .Annotations.summary }}
              {{ .Annotations.description }}
              {{ end }}
```

> **Важно:** `bot_token` и `chat_id` не должны храниться в `values.yaml` в открытом виде. Используйте переменные окружения (через `externalSecret` или `secret`) и ссылайтесь через `${TELEGRAM_BOT_TOKEN}`.

**Получение `chat_id` для группы:**
1. Добавьте бота в группу Telegram.
2. Отправьте сообщение в группу, затем запросите:
   ```bash
   curl "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates" | jq '.result[-1].message.chat.id'
   ```

### Использование AlertmanagerConfig для команд

Пример манифеста для отдельного приложения, который будет автоматически включен в общую конфигурацию.

```yaml
apiVersion: monitoring.coreos.com/v1beta1
kind: AlertmanagerConfig
metadata:
  name: team-alpha-config
  namespace: team-alpha
  labels:
    alertmanagerConfig: "enabled"
spec:
  route:
    receiver: 'alpha-telegram'
    group_by: ['job']
    matchers:
      - name: team
        value: alpha
  receivers:
    - name: 'alpha-telegram'
      webhook_configs:
        - url: 'http://telegram-bot-proxy.monitoring.svc:8080/send'
          send_resolved: true
```

### Настройка Ingress и TLS

```yaml
alertmanager:
  ingress:
    enabled: true
    ingressClassName: nginx
    annotations:
      cert-manager.io/cluster-issuer: "letsencrypt-prod"
    hosts:
      - alertmanager.example.com
    paths:
      - /
    tls:
      - secretName: alertmanager-general-tls
        hosts:
          - alertmanager.example.com
```

### Валидация конфигурации перед применением

```bash
# 1. Проверка синтаксиса values.yaml
helm template monitoring prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  -f values.yaml | kubectl apply --dry-run=client -f -

# 2. Проверка сгенерированных ресурсов
helm get manifest monitoring -n monitoring | grep -A 20 "kind: Alertmanager"

# 3. Валидация AlertmanagerConfig (если используется CRD)
kubectl apply --dry-run=server -f team-alpha-config.yaml

# 4. Проверка синтаксиса alertmanager.yaml через amtool
POD=$(kubectl get pods -n monitoring -l app.kubernetes.io/name=alertmanager -o jsonpath='{.items[0].metadata.name}')
kubectl exec -n monitoring $POD -c alertmanager -- amtool check-config /etc/alertmanager/config/alertmanager.yaml
```

### Обновление и откат конфигурации

```bash
# 1. Создание резервной копии текущих значений
helm get values monitoring -n monitoring > values-backup.yaml

# 2. Применение изменений
helm upgrade monitoring prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  -f values-backup.yaml \
  -f values.yaml

# 3. Проверка rollout
kubectl rollout status statefulset/alertmanager-monitoring-kube-prometheus-alertmanager -n monitoring --timeout=5m

# 4. Проверка статуса Alertmanager CRD
kubectl get alertmanager -n monitoring -o yaml

# 5. В случае проблем — откат
helm rollback monitoring -n monitoring --timeout=5m
```

### Очистка окружения

```bash
# 1. Удаление Helm-релиза
helm uninstall monitoring -n monitoring

# 2. Удаление Persistent Volume Claims (если не используются)
kubectl delete pvc -n monitoring -l app.kubernetes.io/instance=monitoring

# 3. Удаление AlertmanagerConfig ресурсов
kubectl delete alertmanagerconfig -A -l app.kubernetes.io/instance=monitoring

# 4. Удаление namespace (опционально)
kubectl delete namespace monitoring
```

## Диагностика и отладка

### Проверка текущего конфига

Оператор генерирует итоговый конфиг в Secret. Его можно просмотреть командой:

```bash
kubectl get secret -n monitoring alertmanager-monitoring-kube-prometheus-alertmanager -o jsonpath='{.data.alertmanager\.yaml}' | base64 -d
```
*Примечание: Имя секрета зависит от названия вашего Helm-релиза.*

### Проверка сгенерированной конфигурации (AlertmanagerConfig)

```bash
# Получение агрегированного конфига из AlertmanagerConfig
kubectl get secret alertmanager-monitoring-kube-prometheus-alertmanager-generated -n monitoring \
  -o jsonpath='{.data.alertmanager\.yaml}' | base64 -d | grep -A 5 "route:"

# Проверка, что Alertmanager подхватил конфиг
kubectl exec -n monitoring alertmanager-monitoring-kube-prometheus-alertmanager-0 -- \
  amtool config routes show
```

### Использование amtool

Внутри пода Alertmanager доступна утилита `amtool` для проверки конфигурации и управления алертами.

```bash
# Проверка синтаксиса текущего файла в поде
kubectl exec -it -n monitoring alertmanager-monitoring-kube-prometheus-alertmanager-0 -- \
  amtool check-config /etc/alertmanager/config/alertmanager.yaml

# Просмотр активных алертов
kubectl exec -it -n monitoring alertmanager-monitoring-kube-prometheus-alertmanager-0 -- \
  amtool alert

# Просмотр дерева маршрутизации
kubectl exec -it -n monitoring alertmanager-monitoring-kube-prometheus-alertmanager-0 -- \
  amtool config routes show

# Просмотр состояния кластера
kubectl exec -it -n monitoring alertmanager-monitoring-kube-prometheus-alertmanager-0 -- \
  amtool cluster show
```

### Обновление CRD при апгрейде

Helm не обновляет Custom Resource Definitions (CRDs) автоматически при обновлении чарта. Если вы обновляете `kube-prometheus-stack` на новую мажорную версию, необходимо вручную применить актуальные CRDs:

```bash
kubectl apply -f https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/main/example/prometheus-operator-crd/monitoring.coreos.com_alertmanagerconfigs.yaml
kubectl apply -f https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/main/example/prometheus-operator-crd/monitoring.coreos.com_alertmanagers.yaml
```

### NetworkPolicy для Alertmanager

При включенном NetworkPolicy в кластере необходимо разрешить:

```yaml
# Ingress: Prometheus и скрейпинг
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-alertmanager-ingress
  namespace: monitoring
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: alertmanager
  policyTypes:
    - Ingress
  ingress:
    - from:
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: prometheus
      ports:
        - port: 9093
          protocol: TCP
        - port: 9094
          protocol: TCP

# Egress: внешние сервисы (Slack, PagerDuty, Email)
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-alertmanager-egress
  namespace: monitoring
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: alertmanager
  policyTypes:
    - Egress
  egress:
    - to:
        - ipBlock:
            cidr: 0.0.0.0/0
      ports:
        - port: 443
          protocol: TCP
        - port: 587
          protocol: TCP
    - to:
        - namespaceSelector: {}
      ports:
        - port: 53
          protocol: UDP
        - port: 53
          protocol: TCP
```

## Дополнительная информация

### Типичные проблемы и диагностика

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| Alertmanager не видит AlertmanagerConfig | Пустой `alertmanagerConfigSelector` | Добавьте `matchLabels` в `values.yaml` |
| Кластер Gossip не образуется | Порт 9094 заблокирован NetworkPolicy | Откройте порт 9094 между репликами |
| Ошибка «Secret is invalid: data: Too long» | Конфигурация превышает 1MB | Уменьшите количество receivers/inhibit rules |
| `401 Unauthorized` от Prometheus | Отсутствует `basicAuth` в алертинге | Добавьте учетные данные в `alerting.alertmanagers` |
| Потеря силенсов после рестарта | Отсутствует `storage.volumeClaimTemplate` | Настройте Persistent Volume |
| Алерты не группируются | Неправильные `group_by` в route | Убедитесь, что метки существуют в алертах |
| Пустые алерты в receivers | Отсутствуют аннотации | Добавьте `summary` и `description` в PrometheusRule |

### Ограничения и крайние случаи

1.  **Лимит размера Secret (1MB):** Общая конфигурация Alertmanager, включая все `AlertmanagerConfig`, не должна превышать 1MB. При превышении Оператор не сможет создать/обновить Secret.
2.  **Пустой селектор:** Если `alertmanagerConfigSelector` не указан или пуст, Alertmanager игнорирует все `AlertmanagerConfig`.
3.  **Имена Receivers и TimeIntervals:** Должны быть уникальны в рамках одного Alertmanager инстанса. Конфликты имен приведут к ошибкам валидации.
4.  **Gossip порт 9094:** Должен быть доступен по UDP и TCP между всеми репликами Alertmanager внутри кластера. NetworkPolicy или Security Groups могут блокировать кластеризацию.
5.  **Кворум:** При нечётном количестве реплик (например, 3) кластер продолжает работать при отказе 1 узла. При 2 репликах потеря 1 узла приводит к потере кворума.
6.  **External Labels:** Не используйте одинаковые `externalLabels` для разных Alertmanager инстансов — это нарушит дедупликацию.
7.  **CEL-валидация:** Некорректные `AlertmanagerConfig` (например, несколько типов авторизации одновременно) отклоняются на уровне API-сервера с понятным сообщением.
8.  **Совместимость версий:** Версия Alertmanager в `spec.version` должна соответствовать возможностям используемых полей (например, `clusterTLS` требует v0.24+).

### Рекомендации по ресурсам

| Нагрузка | Поды | CPU (Req/Limit) | RAM (Req/Limit) | Хранилище |
| :--- | :--- | :--- | :--- | :--- |
| Малая (<100 алертов/день) | 1-2 | 50m / 100m | 128Mi / 256Mi | 5Gi |
| Средняя (100-1000 алертов/день) | 3 | 100m / 200m | 256Mi / 512Mi | 10Gi |
| Высокая (>1000 алертов/день) | 3-5 | 200m / 500m | 512Mi / 1Gi | 20Gi |

### Лучшие практики

1.  **Минимум 3 реплики:** Обеспечивает кворум в Gossip-кластере и отказоустойчивость.
2.  **Совпадение версий:** Используйте версию Alertmanager, совместимую с `clusterTLS` и другими экспериментальными полями.
3.  **Гарантированный QoS:** Устанавливайте `requests.memory == limits.memory` для перевода в класс `Guaranteed`.
4.  **Сетевая политика:** Открывайте порт `9094` (UDP/TCP) только между репликами Alertmanager внутри namespace.
5.  **Секреты TLS:** Используйте cert-manager для автоматического обновления сертификатов веб-интерфейса и Gossip.
6.  **Изоляция конфигурации:** Предпочитайте `AlertmanagerConfig` вместо нативной `alertmanagerConfiguration` в Production до стабилизации функции.
7.  **Мониторинг кластера:** Добавьте алерт на `alertmanager_cluster_members < replicas`.
8.  **Retention:** Храните Silences минимум 5 дней (120h) для возможности анализа инцидентов.

### Связанные темы

*   **[Конфигурация компонентов](./other_components_config.md)** — RBAC, config-reloader, default rules, Thanos Ruler.
*   **[Веб-аутентификация для Prometheus, Alertmanager и Grafana](./practical_scenarios/web_authentication.md)** — настройка Basic Auth, OAuth, TLS для Alertmanager UI.
*   **[AlertmanagerConfig CRD](../operator/crd/alertmanagerconfig.md)** — детальное описание ресурсов для команд.

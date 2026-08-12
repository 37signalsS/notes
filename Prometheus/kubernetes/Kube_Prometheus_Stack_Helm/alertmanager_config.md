# Конфигурация Alertmanager в kube-prometheus-stack

## Определения

**Alertmanager в kube-prometheus-stack** — компонент Helm-чарта, развёртывающий Alertmanager как управляемое через Prometheus Operator приложение (обычно StatefulSet). В рамках чарта конфигурация реализуется на трёх уровнях:

1.  **Инфраструктурный уровень (`alertmanager.alertmanagerSpec`)** — описание параметров пода (ресурсы, реплики, хранилище, аффинити).
2.  **Глобальный конфигурационный уровень (`alertmanager.config`)** — формирование основного файла `alertmanager.yaml` (глобальные настройки, корневой маршрут).
3.  **Декларативный уровень (`AlertmanagerConfig` CRD)** — создание модульных конфигураций (маршрутов и получателей) через отдельные Kubernetes-ресурсы.

> **См. также:** [Alertmanager — общая конфигурация](../../alertmanager.md), [Alertmanager CRD](../operator/crd/alertmanager.md).

## Основные концепции

### Структура параметров в values.yaml

| Параметр | Описание | Значение по умолчанию |
| :--- | :--- | :--- |
| `alertmanager.enabled` | Включение/выключение компонента. | `true` |
| `alertmanager.apiVersion` | Версия API Alertmanager (рекомендуется `v2`). | `v2` |
| `alertmanager.alertmanagerSpec` | Спецификация для Prometheus Operator (ресурсы, хранилище). | `{}` |
| `alertmanager.config` | Тело конфигурации `alertmanager.yaml`. | `{}` |
| `alertmanager.ingress.enabled` | Создание Ingress-ресурса для доступа к UI. | `false` |
| `alertmanager.tplConfig` | Позволяет использовать шаблонизацию Helm внутри конфига. | `false` |

### Высокая доступность (HA)

Alertmanager поддерживает кластеризацию для предотвращения потери уведомлений при сбое узла.

*   **Репликация:** Настраивается через `alertmanager.alertmanagerSpec.replicas`. Для промышленной среды рекомендуется `3` реплики.
*   **Синхронизация:** Поды обмениваются данными (состоянием силенсов и уведомлений) через gossip-протокол. Оператор автоматически добавляет флаги `--cluster.peer` при `replicas > 1`.
*   **Дедупликация:** Выполняется на стороне Alertmanager. Если несколько реплик получают один и тот же алерт, пользователю уйдёт только одно уведомление.

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

### Безопасное управление секретами

Хранение паролей (SMTP, Webhook tokens) напрямую в `values.yaml` (`alertmanager.config`) не рекомендуется. Существует два способа безопасной настройки:

1.  **Использование `configSecret`:** Вы заранее создаёте Secret с файлом `alertmanager.yaml` и указываете его имя.
    ```yaml
    alertmanager:
      alertmanagerSpec:
        configSecret: "custom-alertmanager-config"
    ```
2.  **Шаблонизация и внешние секреты:** Использование операторов вроде External Secrets или Helm-шаблонизации (`tplConfig: true`) для подстановки значений из Kubernetes Secrets.

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

### Использование AlertmanagerConfig для команд

Пример манифеста для отдельного приложения, который будет автоматически включен в общую конфигурацию.

```yaml
apiVersion: monitoring.coreos.com/v1alpha1
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

## Диагностика и отладка

### Проверка текущего конфига

Оператор генерирует итоговый конфиг в Secret. Его можно просмотреть командой:

```bash
kubectl get secret -n monitoring alertmanager-monitoring-kube-prometheus-alertmanager -o jsonpath='{.data.alertmanager\.yaml}' | base64 -d
```
*Примечание: Имя секрета зависит от названия вашего Helm-релиза.*

### Использование amtool

Внутри пода Alertmanager доступна утилита `amtool` для проверки конфигурации и управления алертами.

```bash
# Проверка синтаксиса текущего файла в поде
kubectl exec -it -n monitoring alertmanager-monitoring-kube-prometheus-alertmanager-0 -- amtool check-config /etc/alertmanager/config/alertmanager.yaml

# Просмотр активных алертов
kubectl exec -it -n monitoring alertmanager-monitoring-kube-prometheus-alertmanager-0 -- amtool alert
```

### Обновление CRD при апгрейде

Helm не обновляет Custom Resource Definitions (CRDs) автоматически при обновлении чарта. Если вы обновляете `kube-prometheus-stack` на новую мажорную версию, необходимо вручную применить актуальные CRDs:

```bash
kubectl apply -f https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/main/example/prometheus-operator-crd/monitoring.coreos.com_alertmanagerconfigs.yaml
```

## Дополнительная информация

### Рекомендации по ресурсам

| Нагрузка | Поды | CPU (Req/Limit) | RAM (Req/Limit) |
| :--- | :--- | :--- | :--- |
| Малая (<100 алертов/день) | 1-2 | 50m / 100m | 128Mi / 256Mi |
| Средняя (100-1000 алертов/день) | 3 | 100m / 200m | 256Mi / 512Mi |
| Высокая (>1000 алертов/день) | 3-5 | 200m / 500m | 512Mi / 1Gi |

### Связанные темы

* [Alertmanager — общая конфигурация](../../alertmanager.md) — логика маршрутизации и шаблоны.
* [Alertmanager CRD](../operator/crd/alertmanager.md) — глубокое погружение в параметры оператора.
* [AlertmanagerConfig CRD](../operator/crd/alertmanagerconfig.md) — детальное описание ресурсов для команд.
* [Karma Dashboard](../../karma_dashboard.md) — визуализация алертов для больших инсталляций.

# Установка Grafana для визуализации логов Loki

## Определения

**Grafana** — платформа визуализации и анализа данных из Loki, Prometheus, Mimir и других источников. Grafana не хранит данные, только запрашивает и отображает их.

> **⚠️ Важно:** Для полного руководства по установке Grafana в Kubernetes см. [Установка Grafana через Helm](../../Grafana/Installation/grafana_helm_installation.md). Данный файл описывает специфику интеграции с Loki.

**Текущая версия (апрель 2026):** Grafana 12.4.2 (LTS — 11.6.x)

## Основные концепции

### Миграция Helm-репозитория (январь 2026)

Официальный репозиторий `grafana https://grafana.github.io/helm-charts` **более не обновляется**.

**Новый репозиторий:**

```bash
helm repo add grafana-community https://grafana-community.github.io/helm-charts
helm repo update
```

### Архитектура интеграции Grafana + Loki

| Компонент | Назначение | URL |
| :--- | :--- | :--- |
| **Loki Gateway** | HTTP-шлюз для запросов к Loki | `http://loki-gateway.logging.svc.cluster.local:80` |
| **Loki Querier** | Выполнение запросов LogQL | Внутренний сервис кластера |
| **Grafana** | Визуализация через плагин Loki | Подключается к Loki Gateway |

**Поток данных:** `Grafana (Explore/Dashboard)` → `LogQL запрос` → `Loki Gateway` → `Querier/Ingester` → `Результат`

## Практические сценарии

### Сценарий 1: Установка Grafana с преднастроенным datasource Loki

**Файл `grafana-values.yaml` для Loki-стека:**

```yaml
# grafana-values.yaml
ingress:
  enabled: true
  ingressClassName: nginx
  hosts:
    - host: grafana.example.com
      paths:
        - path: /
          pathType: Prefix
  tls:
    - hosts:
        - grafana.example.com
      secretName: grafana-tls

# Учетные данные через Kubernetes Secret
admin:
  existingSecret: grafana-admin-secret
  userKey: admin-user
  passwordKey: admin-password

# Автоматическая настройка datasource Loki
datasources:
  datasources.yaml:
    apiVersion: 1
    datasources:
      - name: Loki
        type: loki
        access: proxy
        url: http://loki-gateway.logging.svc.cluster.local:80
        isDefault: true
        editable: false
        jsonData:
          maxLines: 1000
          derivedFields:
            - name: TraceID
              matcherRegex: 'trace_id=(\w+)'
              url: '$${__value.raw}'
              datasourceUid: tempo

# Персистентность
persistence:
  enabled: true
  size: 10Gi
  storageClassName: standard

# Загрузка дашбордов через sidecar
sidecar:
  dashboards:
    enabled: true
    label: grafana_dashboard
    labelValue: "1"
  datasources:
    enabled: true
    label: grafana_datasource
```

**Создание секрета:**

```bash
kubectl create secret generic grafana-admin-secret \
  --from-literal=admin-user="admin" \
  --from-literal=admin-password="$(openssl rand -base64 20)" \
  -n logging
```

**Установка:**

```bash
helm upgrade --install grafana grafana-community/grafana \
  --namespace logging \
  --create-namespace \
  -f grafana-values.yaml \
  --wait --atomic
```

### Сценарий 2: Ручное добавление datasource Loki

Если datasource не настроен через `values.yaml`:

1. Перейдите в **Connections** → **Data sources** → **Add data source** → **Loki**
2. Укажите URL:
   - Один namespace: `http://loki-gateway.logging.svc.cluster.local:80`
   - Разные namespaces: `http://loki.loki.svc.cluster.local:3100`
3. Нажмите **Save & Test**

### Сценарий 3: Настройка Derived Fields для корреляции с Tempo

Для перехода от логов к трассировкам извлеките `trace_id` из логов:

```yaml
datasources:
  datasources.yaml:
    apiVersion: 1
    datasources:
      - name: Loki
        type: loki
        access: proxy
        url: http://loki-gateway.logging.svc.cluster.local:80
        jsonData:
          derivedFields:
            - name: TraceID
              matcherRegex: 'trace_id=([a-f0-9]{32})'
              url: '$${__value.raw}'
              datasourceUid: tempo
              matcherType: Label
```

### Проверка установки

```bash
# Проверка пода
kubectl get pods -n logging -l app.kubernetes.io/name=grafana

# Проверка Ingress
kubectl get ingress -n logging -l app.kubernetes.io/name=grafana

# Логи Grafana
kubectl logs -n logging -l app.kubernetes.io/name=grafana -f
```

### Troubleshooting

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Datasource не подключается** | Неправильный URL | Проверьте `kubectl get svc -n logging \| grep loki-gateway` |
| **404 при доступе** | Неправильный `root_url` | Добавьте `grafana.ini.server.root_url` в `values.yaml` |
| **Дашборды не загружаются** | Sidecar не находит ConfigMap | Проверьте метки: `kubectl get configmap -l grafana_dashboard=1` |

## Дополнительная информация

| Ресурс | Описание |
| :--- | :--- |
| [Полное руководство по установке](../../Grafana/Installation/grafana_helm_installation.md) | Production checklist, troubleshooting, HA |
| [Обзор Loki](../loki_overview.md) | Архитектура, LogQL |
| [Примеры LogQL](logql_examples.md) | Запросы для анализа логов |
| [Провиженинг Grafana](../../Grafana/grafana_provisioning.md) | Автоматическая настройка дашбордов |
| [Установка Loki](loki_installation.md) | Установка бэкенда Loki |

# Настройка Grafana для визуализации логов Loki

## Определения

**Grafana** — платформа визуализации и анализа данных, используемая в стеке Loki для выполнения запросов LogQL и отображения логов. Она выступает интерфейсом для взаимодействия с [Loki](../loki_overview.md).

> **Первоисточник:** Полное руководство по развертыванию Grafana в Kubernetes см. в файле **[Установка Grafana через Helm](../../Grafana/Installation/grafana_helm_installation.md)**. Данный документ описывает только специфику интеграции с Loki.

## Основные концепции

### Архитектура интеграции Grafana + Loki

| Компонент | Назначение | URL в кластере |
| :--- | :--- | :--- |
| **Loki Gateway** | Точка входа для запросов (Nginx/Gateway) | `http://loki-gateway.logging.svc.cluster.local:80` |
| **Pluggable Datasource** | Плагин Grafana для работы с LogQL | Настраивается через `values.yaml` или UI |
| **Explore Mode** | Интерфейс для оперативного поиска по логам | Встроен в Grafana |

**Поток данных:**
`Grafana UI` → `LogQL запрос` → `Loki Gateway` → `Loki Querier` → `Результат визуализации`

## Практические сценарии

### Сценарий 1: Автоматическая настройка (Provisioning)

Рекомендуемый способ — конфигурация источника данных через `values.yaml` при установке Grafana.

**Пример `values.yaml` с поддержкой Loki и корреляцией с Tempo:**

```yaml
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
          # Настройка Derived Fields для перехода к трейсам
          derivedFields:
            - name: TraceID
              matcherRegex: 'trace_id=(\w+)'
              url: '$${__value.raw}'
              datasourceUid: tempo
              matcherType: Label
```

**Установка с использованием актуального репозитория:**

```bash
# Добавление репозитория (если не добавлен)
helm repo add grafana-community https://grafana-community.github.io/helm-charts
helm repo update

# Установка
helm upgrade --install grafana grafana-community/grafana \
  --namespace logging \
  -f grafana-values.yaml
```

### Сценарий 2: Ручное добавление источника данных

Если Grafana уже установлена:

1. Перейдите в **Connections** → **Data sources**.
2. Нажмите **Add data source** и выберите **Loki**.
3. В поле **URL** укажите адрес шлюза: `http://loki-gateway.logging.svc.cluster.local:80`.
4. Нажмите **Save & Test**. Если статус «Data source is working», настройка завершена.

### Сценарий 3: Настройка корреляции логов и трассировок (Derived Fields)

Для перехода из строки лога к соответствующей трассировке в Tempo необходимо настроить извлечение `trace_id`.

**Параметры регулярного выражения:**

- Для стандартных JSON-логов: `trace_id=([a-f0-9]{32})`
- Для logfmt: `trace_id=(\w+)`

После настройки в интерфейсе Grafana (Explore) при нажатии на `trace_id` появится ссылка для перехода в datasource Tempo.

## Дополнительная информация

### Устранение неполадок

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Data source connected, but no logs** | Ошибки в лейблах или отсутствие логов | Проверьте наличие данных в Loki через `logcli` |
| **Connection refused** | Неверный URL или порт шлюза | Проверьте сервис: `kubectl get svc -n logging` |
| **Derived field link not visible** | Регулярное выражение не совпадает | Проверьте формат логов и `matcherRegex` |

### См. также

- **[Примеры LogQL](logql_examples.md)** — составление запросов для дашбордов
- **[Установка Loki](loki_installation.md)** — развертывание бэкенда
- **[Провиженинг Grafana](../../Grafana/grafana_provisioning.md)** — детали автоматизации дашбордов
- **[Установка Grafana через Helm](../../Grafana/Installation/grafana_helm_installation.md)** — базовый SSoT по установке

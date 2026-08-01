# Управление правилами vmalert в Kubernetes

## 1. Определения

**vmalert** — специализированный компонент [VictoriaMetrics](./overview.md), отвечающий за вычисление правил алертинга и записи. В инфраструктуре Kubernetes управление правилами осуществляется двумя основными способами:

1.  **Декларативный (VMRule CRD)** — использование Custom Resource Definitions и VictoriaMetrics Operator. Это стандарт индустрии (2026), обеспечивающий автоматизацию жизненного цикла правил.
2.  **Традиционный (ConfigMap)** — монтирование YAML-файлов правил в поды через стандартные механизмы Kubernetes. Используется в случаях, когда установка оператора невозможна или нецелесообразна.

## 2. Базовые концепции

### Сравнение подходов

| Характеристика | VMRule (Operator) | ConfigMap (Manual) |
| :--- | :--- | :--- |
| **Обновление** | Автоматический Hot reload | Требует перезапуска пода или sidecar (reloader) |
| **Валидация** | На уровне Admission Webhook (до применения) | Только после запуска компонента (в логах) |
| **Масштабируемость** | Высокая (Discovery по меткам в любых Namespaces) | Низкая (Ручное управление путями и томами) |
| **GitOps** | Нативная поддержка (ArgoCD, Flux) | Требует сложной настройки монтирования файлов |
| **Типы данных** | Метрики (MetricsQL) и Логи (LogsQL) | Любые, поддерживаемые vmalert |

## 3. Практические сценарии

### Сценарий 1: Управление через VMRule CRD (Рекомендуемый)

VictoriaMetrics Operator использует ресурс **VMRule** для определения групп правил. Оператор автоматически сканирует кластер на наличие этих ресурсов и обновляет конфигурацию `vmalert`.

#### Пример алертинга на основе метрик (MetricsQL)

```yaml
apiVersion: operator.victoriametrics.com/v1beta1
kind: VMRule
metadata:
  name: infrastructure-alerts
  namespace: monitoring
  labels:
    role: alert-rules
    tier: production
spec:
  groups:
    - name: HostMetrics
      interval: 30s
      rules:
        - alert: HighCpuUsage
          expr: 100 - (avg by (instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100) > 85
          for: 5m
          labels:
            severity: warning
          annotations:
            summary: "Высокая загрузка CPU на {{ $labels.instance }}"
            description: "Загрузка CPU превышает 85% более 5 минут. Текущее значение: {{ $value | printf \"%.2f\" }}%"
```

#### Пример алертинга на основе логов (LogsQL)

С выходом VictoriaLogs правила алертинга могут анализировать журналы напрямую через тот же ресурс `VMRule`.

```yaml
apiVersion: operator.victoriametrics.com/v1beta1
kind: VMRule
metadata:
  name: application-log-alerts
  namespace: monitoring
spec:
  groups:
    - name: AppErrors
      rules:
        - alert: HighErrorRateInLogs
          # Пример LogsQL запроса
          expr: |
            _stream:{app="api-gateway"} | filter "status=500" | stats by (host) count() > 20
          for: 2m
          labels:
            severity: critical
          annotations:
            summary: "Всплеск 500-х ошибок в логах {{ $labels.app }}"
```

### Связывание VMRule и VMAlert (Discovery)

Чтобы `vmalert` "увидел" ваши правила, в его конфигурации (ресурс `VMAlert`) должны быть настроены селекторы. Это позволяет реализовать **Multitenancy** (многоарендность).

```yaml
apiVersion: operator.victoriametrics.com/v1beta1
kind: VMAlert
metadata:
  name: main-vmalert
spec:
  # Выбирать правила с определенной меткой
  ruleSelector:
    matchLabels:
      role: alert-rules
  # Искать правила во всех Namespaces с меткой мониторинга
  ruleNamespaceSelector:
    matchLabels:
      monitoring-enabled: "true"
  datasource:
    url: "http://vmselect:8481/select/0/prometheus"
  notifier:
    url: "http://alertmanager:9093"
```

### Сценарий 2: Управление через ConfigMap

Используется для специфических конфигураций или legacy-сред. Основная сложность — обеспечение обновления правил без простоя.

**1. Создание ConfigMap с правилами:**
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: vmalert-manual-rules
data:
  rules.yaml: |
    groups:
      - name: ManualGroup
        rules:
          - alert: ManualAlert
            expr: up == 0
```

**2. Монтирование в Deployment:**
При использовании ConfigMap рекомендуется монтировать весь каталог, а не отдельные файлы через `subPath`, так как `subPath` блокирует автоматическое обновление файлов внутри контейнера при изменении ConfigMap.

```yaml
spec:
  containers:
    - name: vmalert
      args:
        - "-rule=/etc/vmalert/rules/*.yaml"
      volumeMounts:
        - name: rules-volume
          mountPath: /etc/vmalert/rules
  volumes:
    - name: rules-volume
      configMap:
        name: vmalert-manual-rules
```

## 4. Поиск и устранение неисправностей (Troubleshooting)

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Правила не отображаются в UI | `ruleSelector` не соответствует меткам VMRule | Проверить соответствие меток (labels) и селекторов в `VMAlert` и `VMRule` |
| Ошибка в MetricsQL/LogsQL | Синтаксическая ошибка в выражении | Проверить логи оператора или запустить `vmalert-tool check` локально |
| Правила из другого Namespace не подхватываются | Не настроен `ruleNamespaceSelector` | Убедиться, что `ruleNamespaceSelector` в `VMAlert` разрешает поиск в целевом Namespace |
| ConfigMap обновился, но vmalert не видит изменений | Использование `subPath` в монтировании | Отказаться от `subPath` или использовать sidecar (stakater/reloader) для рестарта пода |

## 5. Дополнительная информация

### Лучшие практики (2026)

- **CI/CD Валидация:** Всегда запускайте `vmalert-tool test` в пайплайне перед деплоем манифестов. Это позволяет протестировать логику алертов на синтетических данных (unit tests для алертов).
- **Разделение ответственности:** Создавайте отдельные `VMRule` для разных команд/приложений, используя метки для фильтрации в соответствующих инстансах `vmalert`.
- **Версионирование:** Используйте LTS версии образов (например, `v1.136.0`) для обеспечения стабильности работы движка правил.

**Ссылки:**
- [VMAlert Operator CRD Docs](https://docs.victoriametrics.com/operator/resources/vmalert/)
- [LogsQL Alerting Guide](https://docs.victoriametrics.com/victorialogs/querying/#alerting-rules)
- [Обзор vmalert](./vmalert_overview.md)

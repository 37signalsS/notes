# VictoriaMetrics в Kubernetes: чарт `victoria-metrics-k8s-stack`

## Определения

**`victoria-metrics-k8s-stack`** — официальный Helm-чарт VictoriaMetrics для развёртывания мониторингового стека в Kubernetes «из коробки»: VictoriaMetrics (single или cluster), `vmagent`, `vmalert`, `vmauth`, `Alertmanager` и вложенный `Grafana` с готовыми дашбордами и datasource. Полный аналог `kube-prometheus-stack`, но на компонентах VictoriaMetrics.

**Отличие от Operator** — оператор (см. [operator_overview.md](./operator_overview.md)) управляет VM через CRD (декларативный подход для сложных сценариев и автоматизации). `k8s-stack` — готовый «стек в один helm install»: быстрее для большинства сред, но менее гибкий для кастомных CRD-манипуляций.

## Базовые концепции

### Что входит в чарт

| Компонент | Роль |
| :--- | :--- |
| `victoriametrics.vmetricssingle` (single) или `.vmcluster` (cluster) | Хранение метрик и query API |
| `victoriametrics.vmagent` | Скрейпинг node/job/ServiceMonitor и Push |
| `victoriametrics.vmalert` | Правила алертинга + recording rules |
| `victoriametrics.vmauth` | Маршрутизация и аутентификация внешнего доступа |
| `alertmanager` | Рассылка оповещений (связан с `vmalert`) |
| `grafana` | Дашборды; datasources VM подключаются автоматически provision |
| Виртуальные `serviceMonitors` / `prometheusRule` | Интеграция с прометеусовскими CRD |

- Default-дашборды (node, kube-state-metrics, VM) приходят в Grafana через sidecar;
- Datasource «VictoriaMetrics» создаётся автоматически при установке (тип Prometheus, URL на `vmsingle`/`vmcluster`);
- В кластере логи (VictoriaLogs) ставятся **отдельно** — см. [kubernetes: VictoriaLogs](./../Kubernetes/MonitoringLogging/victorialogs_k8s_setup.md).

### Когда использовать

- Средние/крупные prod-окружения: быстрый старт мониторинга node + kube-state + приложений;
- Для deep-CRD автоматизации (автомасштабирование, секции много-кластерых реплик) — предпочесть оператор;
- Мелкие кластеры — подойдёт даже `vmsingle` (один инстанс VM вместо кластера).

### Зачем это в заметках

VM в k8s — распространённый паттерн: деплой через `k8s-stack` сокращает «ручное» конфигурирование Grafana/vmalert/Alertmanager до пары команд helm. Полезно на собеседовании: «как бы ты поднял мониторинг Prometheus/VictoriaMetrics в k8s».

## Практические сценарии

### 1. Быстрая установка стека (default-конфигурация)

```bash
helm repo add vm https://victoriametrics.github.io/helm-charts/
helm upgrade --install victoria-metrics-k8s-stack \
  vm/victoria-metrics-k8s-stack \
  --namespace monitoring --create-namespace
```

После установки в `monitoring` работают: Grafana (NodePort/Ingress), vmagent (DaemonSet), vmsingle, vmalert, alertmanager. Проверка:

```bash
kubectl -n monitoring get pods
kubectl -n monitoring port-forward svc/victoria-metrics-k8s-stack-grafana 3000:80
# login admin/prom-operator (по умолчанию)
```

### 2. Минимальный production-конфиг через `values.yaml`

```yaml
# values.yaml
victoriametrics:
  vmagent:
    enabled: true
  vmsingle:
    enabled: true
    spec:
      retentionPeriod: 30d
      resources:
        requests:
          memory: 2Gi
          cpu: 500m
  vmalert:
    enabled: true
    spec:
      dataSource:
        url: http://victoria-metrics-k8s-stack-vmsingle:8429
      notifier:
        url: http://victoria-metrics-k8s-stack-alertmanager:9093
grafana:
  enabled: true
  sidecar:
    dashboards:
      enabled: true
alertmanager:
  enabled: true
  config:
    global:
      resolve_timeout: 5m
```

> Структура values и названия ключей периодически меняются между мажорными версиями чарта — сверяйтесь с README релиза на https://github.com/VictoriaMetrics/helm-charts.

### 3. Переключение single → cluster

Замените `victoriametrics.vmsingle:` на `victoriametrics.vmcluster:`:

```yaml
victoriametrics:
  vmcluster:
    enabled: true
    vmsingle_count: 1
    vmstorage:
      podManagementPolicy: Parallel
      replicaCount: 3
      storage:
        volumeClaimTemplate:
          spec:
            resources:
              requests:
                storage: 100Gi
    vminsert:
      replicaCount: 2
    vmselect:
      replicaCount: 2
```

Часть данных снова шардируется — см. детали репликации в [cluster_operations.md](./cluster_operations.md).

### 4. Кастомные алерты через prometheusRule

```yaml
victoriametrics:
  vmalert:
    enabled: true
    spec:
      ...
prometheusRule:
  victoriametrics:
    rules:
      - group: "custom"
        rules:
          - alert: HighCPULoad
            expr: "100 - (avg by(instance) (rate(node_cpu_seconds_total{mode=\"idle\"}[5m])) * 100) > 80"
            for: 10m
            labels:
              severity: warning
```

### 5. Доступ к UI через ingress/vmauth

```yaml
victoriametrics:
  vmauth:
    enabled: true
    spec:
      routeSettings: {}
      unauthorizedUser:
        urlMap:
          - src_paths: ["/vmui", "/api/v1/.*"]
            url_prefix: http://victoria-metrics-k8s-stack-vmsingle:8429
ingress:
  enabled: true
  className: nginx
  hosts:
    - vm.example.com
```

## Валидация установки

```bash
kubectl -n monitoring port-forward svc/victoria-metrics-k8s-stack-vmsingle 8429:8429 &
curl -s  http://localhost:8429/metrics | head -n 3
curl -s  'http://localhost:8429/api/v1/query?query=up' | jq '.data.result | length'   # >0

# Grafana
kubectl -n monitoring port-forward svc/victoria-metrics-k8s-stack-grafana 3000:80
```

## Поиск и устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Grafana 401 после входа | `grafana.adminPassword` не задан | Выставить в values `grafana.adminPassword`; пароль из secret `grafana` |
| Datasource «No data» | vmsingle URL в datasource изменился после апгрейда | Проверить `victoriametrics.kube-stack...` секции; убедиться что vmsingle запущен |
| vmagent не скрейпит поды | ServiceMonitor недоступен/не в `monitoring` | Настроить `serviceScrapeSelector`/`serviceMonitorSelector` в vmagent |
| vmalert не алертит | `notifier` не указывает на Alertmanager | Проверить `spec.notifier.url` на сервис `-alertmanager` |
| Нет node-метрик | node-exporter не в чарте | Включить `victoriametrics.componentEnablement.nodeExporter.enabled` |

## Рекомендации по эксплуатации

- Обновляйте чарт осознанно по SemVer: мажорная версия чарта = значимые структурные изменения values;
- Для прод-сред отдельными release ставьте Grafana (управление паролями/идентификацией), а не вложенный — ср. [Grafana Helm](./../Grafana/Installation/grafana_helm_installation.md);
- Datasource VM создаётся автоматически, но проверяйте его после каждого апгрейда (URL может поменяться);
- Следите за retention диска vmsingle/vmstorage (`kubectl get pvc`) — расширение требует пересоздания PVC;
- Для полного «Прометеусовского» опыта прометеус-ориентированные дашборды ставятся как sidecar-dashboards — совместимы без правок.

## Ограничения и особые случаи

- Стек не покрывает VictoriaLogs: для логов отдельный чарт `victoria-logs-single`/`victoria-logs-cluster` (см. `Kubernetes/MonitoringLogging/victorialogs_k8s_setup.md`);
- `unsupportedChart_` признаки — в наличии k8s-stack только для vmsingle/vmcluster runtime не покрывает `vmbackupmanager`;
- На кластерах < 3 нод полноценный multi-узловой `vmcluster` не даст отказоустойчивости хранения (Shared-Nothing) — разумнее `vmsingle`;

## Дополнительная информация

### См. также

- [VictoriaMetrics Operator](./operator_overview.md) — CRD-подход;
- [Операции с кластером](./cluster_operations.md) — vmcluster, RF;
- [VictoriaLogs в Kubernetes](./../Kubernetes/MonitoringLogging/victorialogs_k8s_setup.md) — чарты logs, vlmg;
- [Grafana Helm install](./../Grafana/Installation/grafana_helm_installation.md) — отдельный Grafana;
- Официальный репозиторий чартов: `https://github.com/VictoriaMetrics/helm-charts`.
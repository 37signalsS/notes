# External Monitoring via static_configs (kube-prometheus-stack)

> [Назад к оглавлению](../practical_scenarios.md)

> **SSoT для темы:** мониторинг внешних (не-Kubernetes) целей через `static_configs` и `additionalScrapeConfigs`.  
> **Смежные темы:** [Service Discovery и Relabeling](../../../service_discovery_and_relabeling.md) — общие концепции SD; [Мониторинг удалённых хостов (Docker)](../../../installation/docker_stack/remote_hosts_monitoring.md) — bare-metal/Docker контекст; [Blackbox Exporter](../../../Exporters/blackbox/blackbox_exporter_installation_and_setup.md) — blackbox-подход.

## Definitions

**`static_configs`** — простейший механизм service discovery в Prometheus, при котором цели перечисляются вручную в конфигурации. Подходит для неизменной инфраструктуры (виртуальные машины, физические серверы, внешние сервисы).

**`additionalScrapeConfigs`** — поле в `values.yaml` Helm-чарта `kube-prometheus-stack`, позволяющее добавить произвольные `scrape_configs` в конфигурацию Prometheus, генерируемую чартом. Основной способ интегрировать внешние цели в Kubernetes-развёртывание Prometheus.

**Whitebox-мониторинг** — сбор метрик через экспортеры (node_exporter, windows_exporter), установленные на целевой системе. Даёт детальную видимость внутренних метрик (CPU, память, диски).

**Blackbox-мониторинг** — проверка доступности сервисов снаружи (HTTP, TCP, ICMP, DNS) через [Blackbox Exporter](../../../Exporters/blackbox/blackbox_exporter_installation_and_setup.md). Не требует установки ПО на целевую систему.

## Basic Concepts

### Архитектура

```
┌─────────────────────────────┐      scrape       ┌──────────────────────┐
│  kube-prometheus-stack      │ ─────────────────► │  Внешний хост       │
│  (Prometheus в Kubernetes)  │    :9100/metrics   │  node_exporter      │
└─────────────────────────────┘                    └──────────────────────┘
                                                   ┌──────────────────────┐
                          ───────────────────────► │  Внешний хост       │
                               :9100/metrics       │  node_exporter      │
                                                   └──────────────────────┘
```

### Ключевые требования

1. **Сетевая доступность** — Pods Prometheus должны иметь сетевой доступ к внешним целевым IP (`__address__`) на порту экспортера.
2. **Firewall rules** — порт экспортера (например, `9100/tcp` для node_exporter) должен быть открыт для входящих соединений с pod-сети Kubernetes.
3. **Стабильные IP/hostname** — `static_configs` не обновляется автоматически; при изменении IP целей требуется обновление `values.yaml` и apply.
4. **Лейблы** — каждый `static_configs`-блок поддерживает произвольные лейблы (`env`, `team`, `location`), которые добавляются ко всем метrikaм цели.

### Relabeling для внешних целей

Для обогащения внешних целей метаданными используются `relabel_configs`:

```yaml
prometheus:
  prometheusSpec:
    additionalScrapeConfigs:
      - job_name: 'external-nodes'
        static_configs:
          - targets: ['192.168.1.100:9100', '192.168.1.101:9100']
            labels:
              env: 'production'
              team: 'infra'
        # Пример: добавить лейбл из имени хоста
        relabel_configs:
          - source_labels: [__address__]
            target_label: instance_ip
```

> **Подробнее:** [relabel_configs и metric_relabel_configs](../../../service_discovery_and_relabeling.md).

## Practical Scenarios

### Сценарий 1: Whitebox — мониторинг внешних серверов с node_exporter

**Контекст:** Виртуальные машины или физические серверы вне Kubernetes с установленным node_exporter.

```yaml
# values.yaml
prometheus:
  prometheusSpec:
    additionalScrapeConfigs:
      - job_name: 'external-nodes'
        scrape_interval: 30s
        static_configs:
          - targets:
              - '192.168.1.100:9100'
              - '192.168.1.101:9100'
            labels:
              env: 'production'
              role: 'app-server'
          - targets:
              - '192.168.1.200:9100'
            labels:
              env: 'staging'
              role: 'db-server'
```

**Проверка:**

```bash
# Port-forward к Prometheus
kubectl port-forward svc/prometheus-operated -n monitoring 9090:9090

# Открыть http://localhost:9090/targets — внешние цели должны быть в статусе UP
```

### Сценарий 2: Whitebox — мониторинг Docker-хостов с cadvisor

**Контекст:** Удалённые хосты с Docker, где cadvisor отдаёт метрики контейнеров.

```yaml
# values.yaml
prometheus:
  prometheusSpec:
    additionalScrapeConfigs:
      - job_name: 'remote-cadvisor'
        scrape_interval: 15s
        static_configs:
          - targets:
              - '192.168.1.100:8080'
              - '192.168.1.101:8080'
            labels:
              env: 'production'
```

> **Подготовка хоста:** На каждом удалённом хосте запускается cadvisor с binding на внешний IP. [Подробнее](../../../installation/docker_stack/remote_hosts_monitoring.md).

### Сценарий 3: Blackbox — проверка доступности внешних эндпоинтов

**Контекст:** Мониторинг доступности HTTP/TCP/ICMP без установки ПО на цель. Используется Blackbox Exporter, развёрнутый внутри Kubernetes.

```yaml
# Создание Probe CRD
apiVersion: monitoring.coreos.com/v1
kind: Probe
metadata:
  name: external-websites
  namespace: monitoring
spec:
  prober:
    url: prometheus-blackbox-exporter.monitoring.svc.cluster.local:9115
  module: http_2xx
  targets:
    staticConfig:
      static:
        - https://example.com
        - https://api.example.com
```

> **Подробнее:** [Blackbox Exporter installation](../../../Exporters/blackbox/blackbox_exporter_installation_and_setup.md), [Probe CRD](../../operator/crd/probe.md).

### Сценарий 4: Отключение встроенных экспортеров при внешнем мониторинге

**Контекст:** Если мониторинг хостов уже ведётся внешними системами, встроенный node-exporter можно отключить.

```yaml
# values.yaml
nodeExporter:
  enabled: false  # если используется внешний мониторинг хостов
```

> **Важно:** Отключение приведёт к потере метрик с Kubernetes-нод. Убедитесь, что альтернативный источник метрик настроен.  
> **См.:** [Конфигурация экспортеров](../exporters_config.md).

## Additional Information

### Troubleshooting

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| Target в статусе DOWN | Firewall блокирует порт | Проверить `telnet <IP> <port>` из pod Prometheus |
| Target не найден | Опечатка в `values.yaml` | Сверить YAML-синтаксис, выполнить `helm diff` |
| Метрики без ожидаемых лейблов | Лейблы не в том `static_configs` блоке | Каждый блок `static_configs` имеет свой набор лейблов |
| Дубликаты метрик | Внешний target совпадает с internal | Проверить `targets` на пересечение с pod CIDR кластера |

### Диагностика из pod Prometheus

```bash
# Exec в pod Prometheus
kubectl exec -it -n monitoring $(kubectl get pods -n monitoring -l app.kubernetes.io/name=prometheus -o jsonpath='{.items[0].metadata.name}') -- sh

# Проверка доступности внешней цели
wget -qO- http://192.168.1.100:9100/metrics | head

# Проверка конфигурации
cat /etc/prometheus/config_out/prometheus.env.yaml | grep -A 20 'external-nodes'
```

### Best Practices

1. **Группировка по среде** — разделяйте `static_configs` блоки по `env` (production/staging) для удобства фильтрации в PromQL.
2. **Helm values в Git** — храните `values.yaml` с `additionalScrapeConfigs` в Git; изменения внешних целей = commit + `helm upgrade`.
3. **Альтернатива для динамических целей** — при большом количестве внешних систем используйте `file_sd_configs` или [Consul SD](../../../../Consul/consul_overview.md) вместо ручного перечисления.
4. **Security** — node_exporter не имеет built-in аутентификации; защищайте канал через firewall rules и mTLS (sidecar-proxy).

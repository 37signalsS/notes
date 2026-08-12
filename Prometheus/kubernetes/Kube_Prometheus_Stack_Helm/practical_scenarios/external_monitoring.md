# Мониторинг внешних целей в kube-prometheus-stack

> [Назад к оглавлению](../overview.md)

## Определения

**Внешние цели (External Targets)** — ресурсы, находящиеся вне кластера Kubernetes (виртуальные машины, bare-metal серверы, облачные сервисы), метрики которых необходимо собирать централизованным экземпляром Prometheus.

**`static_configs`** — механизм статического перечисления адресов целей в конфигурации Prometheus. Является базовым способом мониторинга объектов с неизменными сетевыми реквизитами.

**`additionalScrapeConfigs`** — параметр в `values.yaml` Helm-чарта `kube-prometheus-stack`, позволяющий добавить произвольные секции `scrape_config` напрямую в конфигурационный файл Prometheus.

**`ScrapeConfig` CRD** — современный (v0.65+) ресурс Prometheus Operator, позволяющий декларативно описывать конфигурации сбора метрик для внешних целей без редактирования глобальных секретов или `values.yaml`.

> **См. также:** [Service Discovery и Relabeling](../../../service_discovery_and_relabeling.md), [Blackbox Exporter](../../../Exporters/blackbox/blackbox_exporter_installation_and_setup.md).

## Основные концепции

### Архитектура взаимодействия

Prometheus, запущенный внутри Kubernetes, инициирует исходящие соединения (Scrape) к внешним IP-адресам.

```
┌─────────────────────────────┐      HTTP GET      ┌──────────────────────┐
│  Kubernetes Cluster         │ ─────────────────► │  Внешний сервер      │
│  (kube-prometheus-stack)    │    :9100/metrics   │  (Node Exporter)     │
└─────────────────────────────┘                    └──────────────────────┘
```

### Ключевые требования

1.  **Сетевая связность:** Поды Prometheus должны иметь маршрут к внешним сетям. Если внешние хосты находятся в приватной сети, может потребоваться VPN, Peering или Transit Gateway.
2.  **Firewall:** На внешних хостах должен быть разрешён входящий трафик на порты экспортеров (например, 9100 для Node Exporter) с IP-адресов нод кластера или конкретного диапазона Pod CIDR.
3.  **Разрешение имен:** Если в качестве целей используются DNS-имена, CoreDNS в кластере должен уметь их разрешать (через `forward` или `stubDomains`).

### Выбор метода конфигурации

| Метод | Плюсы | Минусы |
| :--- | :--- | :--- |
| **additionalScrapeConfigs** | Поддерживает любые виды Service Discovery (Consul, EC2, OpenStack). | Требует обновления Helm-релиза и перезагрузки конфига через секрет. |
| **ScrapeConfig CRD** | Полностью декларативен, поддерживает проверку схемы (Validation), модульность. | Поддерживается в новых версиях Оператора (v0.65+). |

## Практические сценарии

### Сценарий 1: Мониторинг внешних серверов через additionalScrapeConfigs

Классический способ добавления группы статических хостов через `values.yaml`.

```yaml
# values.yaml
prometheus:
  prometheusSpec:
    additionalScrapeConfigs:
      - job_name: 'external-linux-servers'
        scrape_interval: 30s
        static_configs:
          - targets:
              - '192.168.10.50:9100'
              - '192.168.10.51:9100'
            labels:
              env: 'production'
              datacenter: 'dc-1'
        relabel_configs:
          - source_labels: [__address__]
            regex: '(.*):9100'
            target_label: 'instance'
            replacement: '$1'
```

### Сценарий 2: Использование ScrapeConfig CRD (современный подход)

Создание отдельного ресурса для мониторинга внешней базы данных.

```yaml
apiVersion: monitoring.coreos.com/v1alpha1
kind: ScrapeConfig
metadata:
  name: external-postgres
  namespace: monitoring
spec:
  staticConfigs:
    - targets:
        - 'db-prod.internal:9187'
      labels:
        service: 'postgresql'
  relabelings:
    - targetLabel: 'cluster'
      replacement: 'main'
```

### Сценарий 3: Защищенный мониторинг с Basic Auth

Если экспортер на внешнем хосте защищен паролем.

```yaml
# values.yaml
prometheus:
  prometheusSpec:
    additionalScrapeConfigs:
      - job_name: 'secure-external-app'
        static_configs:
          - targets: ['app.external.com:443']
        scheme: https
        basic_auth:
          username: 'prometheus-user'
          password: 'secret-password' # Рекомендуется использовать секрет
```

### Сценарий 4: Мониторинг внешних Docker-контейнеров (cAdvisor)

```yaml
prometheus:
  prometheusSpec:
    additionalScrapeConfigs:
      - job_name: 'external-docker-hosts'
        static_configs:
          - targets: ['10.0.5.10:8080']
            labels:
              provider: 'hetzner'
```

## Диагностика и отладка

### Проверка конфигурации в Prometheus

После применения конфигурации необходимо убедиться, что цели (Targets) появились в UI Prometheus.

1.  Выполните port-forward: `kubectl port-forward svc/prometheus-operated -n monitoring 9090:9090`.
2.  Перейдите в раздел **Status -> Targets**.
3.  Найдите `job_name`, указанный в конфигурации.

### Типичные ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `context deadline exceeded` | Проблема сетевой доступности или Firewall. | Проверьте `ping` и `telnet` с ноды кластера до цели. |
| `connection refused` | Экспортер не запущен или слушает только `127.0.0.1`. | Проверьте статус сервиса на внешнем хосте и его `listen-address`. |
| `server returned HTTP status 403 Forbidden` | Неверные учетные данные или ограничения на стороне экспортера. | Проверьте настройки `basic_auth` или IP-фильтры экспортера. |

### Полезные команды

```bash
# Проверка сформированного конфига внутри пода Prometheus
kubectl exec -it -n monitoring prometheus-kps-prometheus-0 -- cat /etc/prometheus/config_out/prometheus.env.yaml | grep -A 20 "job_name: external"

# Проверка доступности метрик изнутри кластера (используя временный под)
kubectl run debug --image=curlimages/curl -it --rm -- curl -v http://192.168.10.50:9100/metrics
```

## Дополнительная информация

### Рекомендации (Best Practices)

1.  **Интервалы сбора:** Для внешних целей через нестабильные каналы (Internet/VPN) рекомендуется увеличивать `scrape_interval` до 30–60 секунд и `scrape_timeout` до 10–20 секунд.
2.  **Безопасность:** Никогда не оставляйте экспортеры на внешних хостах открытыми в мир. Используйте VPN, IP-ограничения или TLS + Basic Auth.
3.  **Relabeling:** Используйте `relabel_configs` для приведения имен инстансов к читаемому виду (например, удаление портов из метки `instance`).
4.  **Модульность:** Предпочитайте `ScrapeConfig` CRD вместо гигантского `values.yaml`, если ваша версия Оператора это позволяет.

### Связанные ресурсы

*   [ServiceMonitor CRD](../operator/crd/servicemonitor.md)
*   [Экспортеры: общая информация](../../../Exporters/overview.md)
*   [Blackbox Exporter в Kubernetes](../../../Exporters/blackbox/blackbox_exporter_installation_and_setup.md)

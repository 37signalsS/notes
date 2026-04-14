# Kubernetes Monitoring and Logging Architecture

## Definitions

**Monitoring** — сбор и анализ метрик для оценки состояния системы. В Kubernetes охватывает все уровни: от бизнес-показателей до утилизации CPU на нодах.

**Logging** — запись событий системы в виде текстовых сообщений. В отличие от метрик, логи содержат детальную информацию о конкретных событиях.

**Structured Logging** — практика записи логов в формате с чёткой структурой (JSON). Критически важно для эффективного парсинга и анализа в централизованных системах.

> **См. также:** [Observability Definitions](../../Concepts/Observability_and_Monitoring/observability_definitions.md) — различия мониторинга и наблюдаемости; [Four Pillars of Observability](../../Concepts/Observability_and_Monitoring/four_pillars_of_observability.md) — логи, метрики, трассировки, профилирование.

## Basic Concepts

### Уровни мониторинга в Kubernetes

| Уровень | Объект | Примеры метрик |
| :--- | :--- | :--- |
| **Бизнес-уровень** | Пользовательские сценарии | Количество заказов, конверсия |
| **Приложения** | Сервисы и микросервисы | RPS, error rate, latency |
| **Кластер** | Компоненты K8s | etcd latency, API server requests |
| **Ноды** | Инфраструктура | CPU, память, диск, сеть |

### Методологии анализа метрик

**USE Method** (Utilization, Saturation, Errors) — для инфраструктурных ресурсов. Детали: [Monitoring Methodologies](../../Concepts/Observability_and_Monitoring/monitoring_methodologies.md).

**RED Method** (Rate, Errors, Duration) — для сервисов и приложений. Детали: [Monitoring Methodologies](../../Concepts/Observability_and_Monitoring/monitoring_methodologies.md).

**Four Golden Signals** (Latency, Traffic, Errors, Saturation) — от Google SRE. Детали: [Monitoring Methodologies](../../Concepts/Observability_and_Monitoring/monitoring_methodologies.md).

### Алертинг

**Алертинг** — процесс уведомления инженеров о проблемах, требующих вмешательства. Без эффективного алертинга мониторинг становится пассивным.

**Правила эффективного алертинга:**

1. **Действенность** — уведомлять только о том, что требует немедленного вмешательства.
2. **Результативность** — каждый алерт должен приводить к действию (исправление, тюнинг, изменение порога).
3. **Совместная работа** — настраивать мониторинг и алертинг совместно с разработчиками.
4. **Анализ** — формировать периодические отчёты для выявления трендов.

### Логирование в Kubernetes

**Стандартный подход:** приложения пишут логи в `stdout`/`stderr`. Среда выполнения (Docker/containerd) перехватывает потоки, сохраняет в файлы на диске хоста и управляет ротацией.

**12 Factor App: Логи как поток событий** — приложение не должно управлять файлами логов. Инфраструктура отвечает за маршрутизацию, хранение и обработку. Детали: [12factor.net/logs](https://12factor.net/logs).

**Расположение логов:**

- **Docker:** `/var/lib/docker/containers/<container_id>/<container_id>-json.log`
- **Kubernetes (симлинки):** `/var/log/pods/` и `/var/log/containers/` — символические ссылки для удобства поиска по имени пода и namespace.

**Логирование системных компонентов:**

- **Компоненты в подах** (`kube-apiserver`, `etcd`, `CoreDNS`) — логируются как обычные приложения.
- **Компоненты на хосте** (`kubelet`, `containerd`/`docker`) — пишут в системный журнал (`journalctl -u kubelet`).

### Ограничения стандартного подхода

Централизованная система логирования необходима по причинам:

1. **Недолговечность логов** — при удалении пода логи теряются.
2. **Распределённость** — логи одного приложения разбросаны по разным узлам.
3. **Отсутствие метаданных** — стандартные логи не содержат информацию о поде/namespace.
4. **Сложность анализа** — простой текст сложно фильтровать и агрегировать.

## Practical Scenarios

### Инструменты для каждого уровня мониторинга

| Уровень | Инструменты |
| :--- | :--- |
| **Бизнес-метрики** | Postgres-экспортер (SQL-запросы), скрипт-экспортер (кастомные сценарии) |
| **Метрики приложений** | Клиентские библиотеки Prometheus для инструментирования кода |
| **Метрики кластера и нод** | Prometheus, Node Exporter, kube-state-metrics |

### Ключевые компоненты кластера для мониторинга

| Компонент | Метрики |
| :--- | :--- |
| **etcd** | Доступность кластера, частота смены лидера |
| **Control Plane** | [kube-apiserver](./kube_apiserver_monitoring.md), `kube-controller-manager`, `kube-scheduler`, `kubelet`, `kube-proxy` |
| **Среда выполнения** | Работоспособность Docker/containerd демонов |
| **DNS (CoreDNS)** | Количество запросов, ошибок, кэш-промахов |
| **Ingress Controller** | Доступность подов, потребление ресурсов, внутренние метрики |
| **kube-state-metrics** | Состояние объектов K8s (деплойменты, поды) |

### Архитектура централизованной системы логирования

**Logging Agent (DaemonSet)** — агент на каждой ноде, который:

1. Читает лог-файлы контейнеров из `/var/log/pods/` или `/var/log/containers/`.
2. Собирает логи системных компонентов из `journald`.
3. Обращается к Kubernetes API для обогащения логов метаданными (имя пода, namespace, лейблы).
4. Отправляет обработанные логи в центральное хранилище.

**Популярные стеки:**

**EFK Stack (Elasticsearch, Fluent Bit, Kibana):**

- **Fluent Bit** — легковесный логирующий агент.
- **Elasticsearch** — мощное хранилище для поиска и анализа.
- **Kibana** — UI для визуализации.
- Надёжный, но ресурсоёмкий стек. Детали: [EFK Stack Setup](./EFK/efk_stack_setup_guide.md).

**Loki Stack (Promtail, Loki, Grafana):**

- **Promtail** — агент для Loki.
- **Loki** — система хранения, индексирует только метаданные (лейблы), а не текст лога.
- **Grafana** — визуализация метрик и логов в одном инструменте.
- Легковесный стек для средних инсталляций. Детали: [Loki Installation](../../Loki/loki_stack_setup/loki_installation.md).

### Стек мониторинга на базе VictoriaMetrics

Альтернатива Prometheus для высоконагруженных сред:

| Компонент | Назначение |
| :--- | :--- |
| **vmagent** | Сбор метрик (scraping) с экспортеров, отправка в хранилище |
| **VictoriaMetrics** | TSDB для долгосрочного хранения (замена Prometheus/Thanos) |
| **Grafana** | Визуализация метрик |
| **vmalert** | Выполнение правил алертинга по данным VictoriaMetrics |
| **AlertManager** | Дедупликация, группировка, маршрутизация алертов |
| **Karma** | Дашборд для AlertManager с удобным UI |

### Пример окружения для развёртывания

**Требования к кластеру:**

- **Kubernetes:** 1.23+ (важно из-за изменений в API).
- **Сетевой плагин:** MetalLB или аналог для `LoadBalancer`.
- **Ingress Controller:** Для доступа к Grafana, Karma.
- **Cert Manager:** Автоматические TLS-сертификаты для Ingress.
- **Хранилище:** NFS Client Provisioner или облачное решение для `PersistentVolumes`.

### Анти-паттерны мониторинга

1. **Ручная настройка** — использовать service discovery.
2. **Алертинг только по ресурсам (CPU/RAM)** — привязывать к симптомам (задержки, ошибки).
3. **Изолированный специалист** — настройка требует знания инфраструктуры и приложений.
4. **Один инструмент для всего** — не использовать систему мониторинга для логирования или трейсинга.

## Additional Information

**Связанные темы:**

- [Observability Definitions](../../Concepts/Observability_and_Monitoring/observability_definitions.md) — фундаментальные концепции
- [Monitoring Methodologies](../../Concepts/Observability_and_Monitoring/monitoring_methodologies.md) — Golden Signals, RED, USE
- [Metrics Deep Dive](../../Concepts/Observability_and_Monitoring/metrics_deep_dive.md) — типы метрик
- [Logs Deep Dive](../../Concepts/Observability_and_Monitoring/logs_deep_dive.md) — стратегии сбора логов
- [Kube API Server Monitoring](./kube_apiserver_monitoring.md) — мониторинг API-сервера

**Инструменты:**

- **[Prometheus](../../Prometheus/overview.md)** — сбор и хранение метрик
- **[VictoriaMetrics](../../VictoriaMetrics/overview.md)** — масштабируемая TSDB
- **[Loki](../../Loki/loki_overview.md)** — агрегация логов
- **[Grafana](../../Grafana/grafana_overview.md)** — визуализация
- **[Fluent Bit](./EFK/fluentbit/fluentbit_configuration.md)** — сбор и отправка логов

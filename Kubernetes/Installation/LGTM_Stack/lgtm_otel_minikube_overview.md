# Развертывание стека LGTM и OpenTelemetry на Minikube

> **Навигация по руководству:**
>
> - [Предварительные требования и подготовка окружения](./lgtm_otel_minikube_prerequisites_environment.md)
> - [Развертывание вспомогательных компонентов](./lgtm_otel_minikube_auxiliary_components.md)
> - [Развертывание стека LGTM](./lgtm_otel_minikube_lgtm_stack_deployment.md)
> - [Развертывание OpenTelemetry](./lgtm_otel_minikube_opentelemetry_deployment.md)
> - [Тестирование и верификация](./lgtm_otel_minikube_test_app_verification.md)
> - [Production Hardening](./lgtm_production_hardening.md)
> - [Backup и восстановление](./lgtm_backup_disaster_recovery.md)
> - [CI/CD интеграция](./lgtm_cicd_gitops_integration.md)
> - [Оптимизация производительности](./lgtm_performance_tuning.md)
> - [Мониторинг стека](./lgtm_monitoring_self_monitoring.md)

## Целевая аудитория

Руководство предназначено для DevOps/SRE-инженеров, разработчиков и системных администраторов, которым необходимо:

- Развернуть полноценный стек наблюдаемости (метрики, логи, трассировки) в локальном окружении для разработки и тестирования.
- Изучить принципы работы OpenTelemetry Collector и его интеграцию с экосистемой Grafana.
- Оценить возможности кросс-сигнальной корреляции (метрики <-> логи <-> трассировки) перед внедрением в production.
- Отыладить конфигурацию Pipeline Collector, процессоров и экспортеров без риска для рабочих систем.

**Не входит в scope руководства:** развертывание в облачных средах (EKS/GKE/AKS), использование AI-инструментов, настройка production-уровня (Grafana Mimir, распределенный Loki/Tempo).

## Краткое содержание руководства

| Этап | Описание | Результат |
| :--- | :--- | :--- |
| **1. Подготовка** | Установка Docker, Minikube, Helm, kubectl. Настройка репозиториев. | Готовое окружение для развертывания |
| **2. Вспомогательные компоненты** | Cert-manager (TLS), локальный Docker Registry. | Инфраструктура хранения образов и сертификатов |
| **3. Стек LGTM** | Prometheus (метрики), Grafana (визуализация), Loki (логи), Tempo (трассировки). | Работающие системы хранения и визуализации |
| **4. OpenTelemetry** | Operator, Collector, автоматическая инструментация приложений. | Пайплайн сбора и обработки телеметрии |
| **5. Тестирование** | Верификация данных, проверка корреляции, RED-метрики. | Подтвержденная работоспособность всего стека |
| **6. Production** | Безопасность, backup, CI/CD, оптимизация, мониторинг. | Готовность к production-развертыванию |

**Ожидаемое время выполнения:** 45–90 минут (в зависимости от скорости интернета и ресурсов машины).

**Ожидаемые результаты:** После завершения руководства будут развернуты и работают:

- Grafana с преднастроенными источниками данных (Prometheus, Loki, Tempo) и включенной корреляцией.
- Prometheus со включенным OTLP-приемником и Exemplars для связи с трассировками.
- Loki для хранения логов с настроенной корреляцией с Tempo.
- Tempo для хранения трассировок с поддержкой TraceQL.
- OTel Collector с настроенным Pipeline для приема и маршрутизации телеметрии.
- Тестовое приложение с автоматической инструментацией, генерирующее метрики, логи и трассировки.

## Определения

**Стек LGTM** — интегрированный набор компонентов для обеспечения [наблюдаемости](../../../Concepts/Observability_and_Monitoring/observability_definitions.md) от Grafana Labs: **L**oki (логи), **G**rafana (визуализация), **T**empo (трассировки), **M**imir/Prometheus (метрики). В данном руководстве используется Prometheus из состава `kube-prometheus-stack`. Подробнее: [Обзор Loki](../../../Loki/loki_overview.md), [Обзор Grafana](../../../Grafana/grafana_overview.md), [Обзор Tempo](../../../Tempo/index.md), [Обзор Mimir](../../../Mimir/mimir_overview.md).

**OpenTelemetry (OTel)** — открытый стандарт CNCF для сбора и экспорта телеметрии. Подробнее: [Обзор OpenTelemetry](../../../OpenTelemetry/opentelemetry_overview.md).

**Minikube** — инструмент для запуска локального кластера Kubernetes на персональном компьютере. Используется как целевая среда для данного руководства, поскольку обеспечивает полную функциональность Kubernetes без необходимости в облачной инфраструктуре. Для LGTM-стека требуются минимум 4 CPU и 8 ГБ RAM. Подробнее: [Концепции Minikube](../../Installation/minikube/minikube_concepts.md).

**Docker Registry** — сервис хранения и распространения образов контейнеров. В Minikube используется для хранения локально собранных образов приложений и компонентов стека. По умолчанию Minikube не доверяет локальным реестрам, поэтому требуется настройка `insecure-registries`. Подробнее: [Docker Registries](../../../Docker/docker_registries.md).

**OTLP (OpenTelemetry Protocol)** — унифицированный протокол передачи данных телеметрии (метрики, логи, трассировки) на основе gRPC (порт 4317) или HTTP (порт 4318). Является стандартом de facto для передачи телеметрии в экосистеме OpenTelemetry. Все компоненты стека (OTel Collector, Prometheus, Loki, Tempo) взаимодействуют через OTLP.

**Persistence (Хранение)** — механизм сохранения данных между перезапусками подов и кластера. В Minikube по умолчанию используются эфемерные тома (`emptyDir`), которые теряются при удалении пода. Для сохранения данных Prometheus, Loki и Tempo между перезапусками Minikube необходимо настроить персистентные тома на базе `hostPath` или `StorageClass`. Подробнее: [Хранение данных](../../Concepts/Storage/data_storage_overview.md).

**Cert-manager** — нативный Kubernetes-контроллер для автоматизации управления TLS-сертификатами. Обеспечивает выпуск и обновление сертификатов для Ingress-контроллера и внутренних сервисов стека. В данном руководстве используется для выпуска самоподписанных сертификатов в тестовом окружении. Подробнее: [Cert-manager](../../ToolsUtilities/cert_manager/definitions.md).

> **Важно:** Для продуктивных сред рекомендуется использовать [Grafana Alloy](../../../Grafana/grafana_alloy_overview.md). Grafana Alloy — это унифицированный агент для сбора метрик, логов и трассировок, который заменяет устаревшие Promtail и Grafana Agent (окончание поддержки последних запланировано на 2025–2026 годы).

---

## Основные концепции

### Почему именно Minikube

Minikube выбирается как целевая среда по нескольким причинам:

- **Полная функциональность Kubernetes:** Minikube предоставляет стандартный API Kubernetes, что позволяет тестировать конфигурации, которые будут работать в production без изменений.
- **Изоляция:** Весь стек работает в изолированной среде, не влияя на рабочие системы.
- **Воспроизводимость:** Благодаря декларативной конфигурации (Helm-чарты, манифесты) развертывание воспроизводимо на любой машине.
- **Экономия ресурсов:** Не требует облачных ресурсов и оплаты, подходит для обучения и разработки.

**Ограничения Minikube:** одноузловая архитектура, отсутствие реальной отказоустойчивости, ограниченные ресурсы (RAM/CPU), эфемерное хранилище по умолчанию. Поэтому данный стек предназначен исключительно для development и testing, но не для production.

### Почему Prometheus вместо Mimir

В данном руководстве используется Prometheus из состава `kube-prometheus-stack` вместо Grafana Mimir по следующим причинам:

- **Простота развертывания:** Prometheus работает как один процесс, тогда как Mimir требует настройки нескольких компонентов (ingester, distributor, querier, store-gateway).
- **Меньшие ресурсы:** Минимальные требования Prometheus — 512Mi RAM, тогда как Mimir требует минимум 2-4 ГБ для стабильной работы.
- **Полная функциональность:** Для development-окружения Prometheus предоставляет все необходимые возможности: скрейпинг, алерты, Exemplars для связи с трассировками.
- **Совместимость с OTel:** Prometheus поддерживает OTLP-приемник (нативный с версии 2.47), что позволяет OTel Collector отправлять метрики напрямую.

Для production рекомендуется использовать Grafana Mimir или VictoriaMetrics как более масштабируемые решения. Подробнее: [Обзор Mimir](../../../Mimir/mimir_overview.md).

### Архитектура решения

```
┌─────────────────┐     ┌──────────────────────────────────────────────────┐
│   Приложение    │────>│          OpenTelemetry Collector                 │
│  (Java/OTel)    │OTLP │  (прием, обработка, экспорт телеметрии)          │
└─────────────────┘     └─────────────┬────────────────┬──────────────────┘
                                      │                │
                    ┌─────────────────┼────────────────┼─────────────┐
                    │                 │                │             │
                    ▼                 ▼                ▼             ▼
              ┌──────────┐     ┌──────────┐    ┌──────────┐  ┌────────────┐
              │   Loki   │     │  Tempo   │    │Prometheus│  │  Grafana   │
              │  (логи)  │     │(трейсы)  │    │(метрики) │  │(визуализ.) │
              └──────────┘     └──────────┘    └──────────┘  └────────────┘
```

**Компоненты архитектуры:**

1. **Приложение** — инструментировано с помощью [OpenTelemetry SDK](../../../OpenTelemetry/instrumentation_sdk.md). Поддерживает автоматическую инструментацию (внедрение агента без изменения кода) для популярных фреймворков (Java/Spring Boot, Python, .NET, Node.js). Генерирует три типа сигналов: метрики (через Meter), логи (через Logger), трассировки (через Tracer).
2. **OpenTelemetry Collector** — центральный компонент для обработки и экспорта данных по протоколу [OTLP](../../../OpenTelemetry/otlp_protocol.md). Работает по принципу конвейера: Receivers (прием) -> Processors (обработка) -> Exporters (экспорт). В Minikube работает в режиме Deployment (единственный экземпляр). Подробнее: [Архитектура и сигналы](../../../OpenTelemetry/architecture_signals.md).
3. **Grafana** — интерфейс для анализа сигналов с поддержкой корреляции. Предоставляет единое окно для просмотра метрик (Prometheus), логов (Loki) и трассировок (Tempo) с возможностью перехода между ними через Exemplars и Derived Fields. Подробнее: [Обзор Grafana](../../../Grafana/grafana_overview.md).
4. **Вспомогательные компоненты:** [Cert-manager](../../ToolsUtilities/cert_manager/cluster_ca.md) обеспечивает выпуск TLS-сертификатов, [Локальный Docker Registry](../../../Docker/docker_registries.md) хранит образы контейнеров, Ingress Controller (nginx) маршрутизирует HTTP-трафик.
5. **Хранилище:** по умолчанию в Minikube используется эфемерное хранилище (`emptyDir`). Для Production необходимы блочные (EBS, Longhorn) или объектные (S3, MinIO) хранилища. Подробнее: [Хранение данных](../../Concepts/Storage/data_storage_overview.md).

### Сигналы наблюдаемости

| Сигнал | Описание | Сбор | Хранение | Визуализация |
| :--- | :--- | :--- | :--- | :--- |
| **Метрики** | Состояние системы (CPU, RAM) | OTel SDK -> Collector | Prometheus | Grafana |
| **Логи** | События с метками времени | OTel SDK -> Collector | Loki | Grafana |
| **Трассировки** | Путь запроса в системе | OTel SDK -> Collector | Tempo | Grafana |
| **Профилирование** | Расход ресурсов кодом | Grafana Pyroscope | Grafana Cloud/OSS | Grafana |

### Кросс-сигнальная корреляция

Ключевое преимущество стека — связывание сигналов для быстрой диагностики. Вместо изучения каждого типа данных по отдельности, инженер может начать с любого сигнала и перейти к связанному:

1. **Метрики -> Трассировки** — через **Exemplars** (Prometheus + Tempo). Каждая точка на графике метрики (например, p99 latency) может содержать ссылку на конкретный TraceID, вызвавший всплеск. Это позволяет за один клик перейти от графика к детальному трейсу в Tempo. Подробнее: [Корреляция телеметрии](../../../Grafana/grafana_correlation_exemplars.md).
2. **Логи -> Трассировки** — через **Derived Fields** (Loki + Tempo). В настройках Loki определяется Regex для извлечения TraceID из текста лога. При обнаружении совпадения Grafana автоматически создает ссылку для перехода к трассировке. Подробнее: [Обзор Loki](../../../Loki/loki_overview.md).
3. **Трассировки -> Логи** — через **Traces to Logs** (Tempo + Loki). Из интерфейса просмотра трассировки можно одним кликом найти все логи, относящиеся к конкретному спану, с фильтрацией по TraceID и временному интервалу.

Дополнительно поддерживается связь **Трассировки -> Метрики** (Traces to Metrics) — из Tempo можно перейти к агрегированным метрикам по конкретному сервису или операции.

Подробнее: [Обзор наблюдаемости](../../../Concepts/Observability_and_Monitoring/observability_definitions.md), [Четыре столпа наблюдаемости](../../../Concepts/Observability_and_Monitoring/four_pillars_of_observability.md).

---

## Практические сценарии

### Сценарий: Развертывание полного стека наблюдаемости на Minikube

**Цель:** Развернуть LGTM + OTel на локальном кластере для разработки и тестирования.

**Предварительные требования:**

- Docker (запущенный), Helm 3+, kubectl, minikube.
- Минимум: 4 CPU, 8 ГБ RAM, 40 ГБ диска.
- Рекомендуется: 6 CPU, 12 ГБ RAM, 60 ГБ диска.
- Доступ к интернету для скачивания образов и чартов.

**Пример запуска Minikube:**

```bash
minikube start --cpus 4 --memory 12288 --disk-size 50g --addons ingress,metrics-server
```

> **Важно:** Параметр `--memory 12288` (12 ГБ) обеспечивает стабильную работу всех компонентов. При нехватке памяти возможны OOMKill (аварийное завершение подов). Минимальный порог — 8 ГБ, но при этом рекомендуется отключить неиспользуемые сервисы.

**Этапы развертывания:**

1. [Подготовка окружения](./lgtm_otel_minikube_prerequisites_environment.md) — Minikube, Docker, Helm, kubectl. Добавление Helm-репозиториев (включая OCI для Loki/Tempo).
2. [Вспомогательные компоненты](./lgtm_otel_minikube_auxiliary_components.md) — Cert-manager (TLS-сертификаты), локальный Docker Registry (хранение образов).
3. [Стек LGTM](./lgtm_otel_minikube_lgtm_stack_deployment.md) — Prometheus (метрики + Exemplars), Grafana (визуализация), Loki (логи), Tempo (трассировки).
4. [OpenTelemetry](./lgtm_otel_minikube_opentelemetry_deployment.md) — OTel Operator, OTel Collector (конвейер обработки), автоматическая инструментация.
5. [Тестирование](./lgtm_otel_minikube_test_app_verification.md) — верификация сбора данных, проверка корреляции между сигналами.

### Валидация окружения перед развертыванием

После запуска Minikube убедитесь, что кластер готов:

```bash
# Проверка статуса кластера
minikube status
# → Expected: Running

# Проверка узлов
kubectl get nodes
# → Expected: 1 node, status Ready

# Проверка включенных аддонов
minikube addons list | grep -E "ingress|metrics-server"
# → Expected: ingress [enabled], metrics-server [enabled]

# Проверка доступных ресурсов
kubectl top nodes
# → Expected: показывает CPU/Memory использования
```

### Проверка работоспособности стека

После завершения всех этапов развертывания проверьте ключевые компоненты:

```bash
# Проверка подов во всех пространствах имен
kubectl get pods -n monitoring
kubectl get pods -n loki
kubectl get pods -n tempo
kubectl get pods -n opentelemetry
# → Expected: все поды в статусе Running (без CrashLoopBackOff)

# Проверка сервисов и доступности
kubectl get svc -n monitoring grafana
# → Expected: SERVICE_TYPE = ClusterIP или NodePort

# Проверка Ingress
kubectl get ingress -A
# → Expected: записи для grafana.test, loki.test

# Проверка OTel Collector
kubectl get otelcol -n opentelemetry
# → Expected: otel-collector в статусе Running
```

### Очистка окружения

Для полного удаления развернутого стека:

```bash
# Удаление компонентов стека в обратном порядке
helm uninstall prometheus -n monitoring
helm uninstall loki -n loki
helm uninstall tempo -n tempo
helm uninstall opentelemetry-operator -n opentelemetry-operator
helm uninstall cert-manager -n cert-manager
helm uninstall docker-registry -n docker-registry

# Удаление пространств имен
kubectl delete namespace monitoring loki tempo opentelemetry opentelemetry-operator cert-manager docker-registry

# Удаление кластера Minikube (все данные будут потеряны)
minikube delete

# Очистка записей в /etc/hosts
sudo sed -i '' '/registry.test/d' /etc/hosts
sudo sed -i '' '/grafana.test/d' /etc/hosts
sudo sed -i '' '/loki.test/d' /etc/hosts
```

> **Внимание:** `minikube delete` удаляет все данные безвозвратно. Если необходимо сохранить данные Prometheus/Loki/Tempo, выполните копирование перед удалением.

---

## Дополнительная информация

### Требования к сети и портам

Для корректной работы стека необходимо обеспечить доступность следующих портов:

| Сервис | Порт (внутри кластера) | Протокол | Назначение |
| :--- | :--- | :--- | :--- |
| **OTel Collector** | 4317 | gRPC | Прием OTLP-данных (основной) |
| **OTel Collector** | 4318 | HTTP | Прием OTLP-данных (альтернативный) |
| **OTel Collector** | 8889 | HTTP | Экспорт метрик для скрейпинга Prometheus |
| **Prometheus** | 9090 | HTTP | API и UI Prometheus |
| **Grafana** | 3000 | HTTP | UI Grafana |
| **Loki** | 3100 | HTTP | API Loki (push/query) |
| **Tempo** | 3200 | HTTP | API Tempo (query) |
| **Tempo** | 4317 | gRPC | Прием трейсов по OTLP |
| **Docker Registry** | 30000 | HTTP | Хранение образов (NodePort) |

> **Примечание:** В Minikube с Ingress-контроллером доступ к сервисам осуществляется через DNS-имена (grafana.test, loki.test и т.д.), которые разрезолвятся на IP-адрес Minikube. Необходимо добавить записи в `/etc/hosts` на хост-машине.

### Таблица компонентов и версий

| Компонент | Версия Helm | Документация |
| :--- | :--- | :--- |
| **kube-prometheus-stack** | `>=88.1.x` | [Prometheus K8s](../../../Prometheus/kubernetes/overview.md) |
| **Loki** | `>=18.7.x` | [Обзор Loki](../../../Loki/loki_overview.md) |
| **Tempo** | `>=3.0.x` | [Обзор Tempo](../../../Tempo/index.md) |
| **OpenTelemetry Operator** | `>=0.120.x` | [Обзор OTel](../../../OpenTelemetry/opentelemetry_overview.md) |
| **Cert-Manager** | `>=1.21.x` | [Cert-manager](../../ToolsUtilities/cert_manager/definitions.md) |
| **Docker Registry** | `>=2.x` | [Docker Registries](../../../Docker/docker_registries.md) |

### Требования к ресурсам (Minikube)

| Компонент | CPU (request/limit) | Memory (request/limit) |
| :--- | :--- | :--- |
| **Prometheus** | 500m / 1000m | 512Mi / 2Gi |
| **Grafana** | 100m / 500m | 128Mi / 512Mi |
| **Loki** | 100m / 500m | 128Mi / 512Mi |
| **Tempo** | 100m / 500m | 128Mi / 512Mi |
| **OTel Collector** | 100m / 500m | 128Mi / 512Mi |

**Минимальные требования Minikube:** `--cpus 4 --memory 8192mb`. Для стабильной работы при развертывании нескольких микросервисов рекомендуется увеличить память до `12288mb` (12Gi). При использовании Mimir вместо Prometheus требования к памяти возрастают до 16Gi. В случае дефицита ресурсов возможны **OOMKill** (Out Of Memory) процессов, что приведет к нестабильности сбора телеметрии.

### Мониторинг ресурсов в процессе развертывания

В процессе развертывания и тестирования стека контролируйте потребление ресурсов:

```bash
# Мониторинг использования ресурсов узлом
kubectl top nodes

# Мониторинг по пространствам имен
kubectl top pods -n monitoring
kubectl top pods -n loki
kubectl top pods -n tempo
kubectl top pods -n opentelemetry

# Более детальный вывод с лимитами
kubectl describe nodes | grep -A 10 "Allocated resources"
```

> **Важно:** Если использование памяти приближается к 80-90% от лимита, увеличьте ресурсы Minikube (`minikube stop` -> `minikube start --memory 16384`) или уменьшите `resources.limits` в Helm-конфигурации компонентов.

### Поиск и устранение неисправностей

| Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| **Grafana не открывается** | Ingress не настроен или DNS не резолвится | Проверить Ingress: `kubectl get ingress -A`. Добавить запись в `/etc/hosts`: `$(minikube ip) grafana.test` |
| **Нет данных в Loki** | Ошибка экспорта из Collector | Проверить логи Collector: `kubectl logs -n opentelemetry -l app.kubernetes.io/name=opentelemetry-collector`. Убедиться, что Loki доступен: `kubectl exec -n opentelemetry <pod> -- curl -s http://loki.loki:3100/ready` |
| **Tempo не принимает трейсы** | Неверный эндпоинт в Collector | Проверить конфигурацию экспортера `otlp` в Collector: endpoint должен быть `tempo.tempo:4317` |
| **Prometheus не скрейпит метрик OTel** | Сервис Collector не имеет аннотаций | Убедиться, что сервис Collector имеет аннотации для Prometheus: `prometheus.io/scrape: "true"`, `prometheus.io/port: "8889"` |
| **OOMKill в подах** | Недостаточно лимитов памяти | Увеличить `resources.limits.memory` в values.yaml или увеличить память Minikube |
| **ImagePullBackOff** | Ошибка локального реестра | Проверить статус реестра: `kubectl get pods -n docker-registry`. Убедиться, что `insecure-registries` настроен в Minikube |
| **Certificate не готов (False)** | cert-manager не может выпустить сертификат | Проверить логи: `kubectl logs -n cert-manager -l app=cert-manager`. Проверить события: `kubectl describe certificate -A` |
| **Агент не внедряется в Pod** | Отсутствует Instrumentation или аннотация | Проверить наличие Instrumentation: `kubectl get instrumentation`. Проверить аннотацию пода: `kubectl describe pod <pod-name> \| grep instrumentation` |

### Безопасность

> **Внимание:** Конфигурация предназначена исключительно для тестовых и демонстрационных окружений. Использование в production не рекомендуется без модификации параметров безопасности.

| Аспект | Текущая конфигурация | Рекомендация для Production |
| :--- | :--- | :--- |
| **TLS** | Самоподписанные (Cert-Manager) | Публичные (Let's Encrypt) / Корпоративный CA |
| **Аутентификация** | Отсутствует (Grafana: admin/prom-operator) | Интеграция OIDC/OAuth2 (Keycloak, Okta) |
| **Изоляция** | Отсутствует (общий namespace) | NetworkPolicies, RBAC, Namespace isolation |
| **Секреты** | Plaintext в Helm/Manifests | Vault, Sealed Secrets, External Secrets Operator |
| **mTLS** | Отключен | Включить между всеми компонентами (cert-manager + Istio/Linkerd) |

### Альтернативы для продуктивной среды

| Компонент | Minikube (для данного руководства) | Production |
| :--- | :--- | :--- |
| **Kubernetes** | Minikube (1 узел) | Managed (EKS/GKE/AKS), Kubespray, kops |
| **Метрики** | Prometheus (single) | Grafana Mimir (distributed), VictoriaMetrics |
| **Логи** | Loki (single) | Loki (микросервисы), Grafana Alloy |
| **Трассировки** | Tempo (monolithic) | Tempo (distributed) |
| **Агент** | OTel Collector (Deployment) | Grafana Alloy, OTel Collector (Agent+Gateway) |
| **Хранение** | emptyDir / hostPath | S3/MinIO (объектное), EBS/Longhorn (блоковое) |

### Ограничения и известные особенности

- **Одноузловая архетектура:** Minikube не поддерживает распределенные конфигурации Loki/Tempo/Mimir. Используются монолитные режимы.
- **Эфемерное хранилище:** По умолчанию данные теряются при `minikube delete`. Для сохранения необходимо настроить `hostPath` или внешнее хранилище.
- **Ограниченные ресурсы:** Рекомендуется не развертывать более 3-4 приложений одновременно при 12 ГБ RAM.
- **Сеть:** Ingress работает через Minikube IP, DNS-записи добавляются вручную в `/etc/hosts`.
- **Без отказоустойчивости:** Отказ одного компонента приводит к потере соответствующего типа данных.

### См. также

- [Обзор наблюдаемости](../../../Concepts/Observability_and_Monitoring/observability_definitions.md) — базовые концепции мониторинга и наблюдаемости.
- [Grafana Alloy: Современный агент](../../../Grafana/grafana_alloy_overview.md) — альтернатива OTel Collector для production-сред.
- [OpenTelemetry: Архитектура](../../../OpenTelemetry/architecture_signals.md) — детали устройства OTel Collector и пайплайнов.

### Production и интеграция

- [Production Hardening](./lgtm_production_hardening.md) — безопасность и жёсткая настройка стека LGTM.
- [Backup и восстановление](./lgtm_backup_disaster_recovery.md) — резервное копирование и восстановление данных.
- [CI/CD интеграция](./lgtm_cicd_gitops_integration.md) — GitOps и автоматизация деплоя.
- [Оптимизация производительности](./lgtm_performance_tuning.md) — настройка retention, compaction и ресурсов.
- [Мониторинг стека](./lgtm_monitoring_self_monitoring.md) — самомониторинг компонентов LGTM.

---

**Навигация по руководству:**

- [Предварительные требования](./lgtm_otel_minikube_prerequisites_environment.md)
- [Развертывание вспомогательных компонентов](./lgtm_otel_minikube_auxiliary_components.md)

# Мониторинг Kubernetes с помощью Kube-Prometheus-Stack

## Определения

**`kube-prometheus-stack`** — это популярный [Helm-чарт](../../Kubernetes/ToolsUtilities/helm_overview.md), который разворачивает полноценную систему мониторинга на базе Prometheus в кластере [Kubernetes](../../Kubernetes/kubernetes_overview.md). Он значительно упрощает установку, настройку и управление компонентами, необходимыми для сбора, визуализации и оповещения о метриках.

## Основные концепции

### Экосистема Prometheus

*   **[Prometheus Server](../overview.md):** Центральный компонент для сбора, хранения и обработки метрик. Разворачивается как `StatefulSet`. Осуществляет сбор метрик по модели pull-based, активно опрашивая (scrapes) целевые эндпоинты экспортеров по HTTP. Имеет встроенный механизм `service discovery` для автоматического обнаружения целей в динамических средах.
*   **[Alertmanager](../alertmanager.md):** Отдельная сущность, отвечающая за дедупликацию, группировку и маршрутизацию оповещений, сгенерированных Prometheus. Он получает алерты от Prometheus и отправляет их в различные каналы связи.
*   **[Push Gateway](../pushgateway.md):** Компонент, предназначенный для сбора метрик от кратковременных или периодически запускаемых задач (например, `cron` job), которые не могут быть опрошены Prometheus напрямую. Эти задачи "проталкивают" (push) свои метрики в Push Gateway, откуда Prometheus их уже забирает по своей стандартной pull-модели.
*   **[Экспортеры](../Exporters/overview.md):** Программы, которые собирают метрики из различных систем (ОС, базы данных, приложения) и преобразуют их в текстовый формат, понятный Prometheus, предоставляя по HTTP-эндпоинту (обычно `/metrics`). Примеры: `node-exporter` для метрик хоста, `kube-state-metrics` для метрик объектов Kubernetes.
*   **[Grafana](../../Grafana/grafana_overview.md):** Инструмент для мощной визуализации метрик, создания интерактивных дашбордов и настройки алертов. Работает с Prometheus как с основным источником данных.

### Архитектура `kube-prometheus-stack`: Оператор и CRD

`kube-prometheus-stack` основан на паттерне "Оператор" и устанавливает целую экосистему компонентов:

*   **[Prometheus Operator](./operator.md):** Является "мозгом" системы. Это контроллер, который расширяет API Kubernetes с помощью **Custom Resource Definitions (CRD)** и управляет конфигурацией всего стека. Вместо ручного редактирования сложных файлов `prometheus.yml`, вы описываете желаемое состояние с помощью простых CRD-манифестов. Оператор следит за этими CRD и автоматически преобразует их в реальные объекты кластера (StatefulSet, ConfigMap, Secret и т.д.). Подробное описание его архитектуры и принципов работы находится в основной заметке: **[Prometheus Operator](./operator.md)**.
*   **[Prometheus Server](../overview.md):** Настраивается и управляется Оператором.
*   **[Grafana](../../Grafana/grafana_overview.md):** Для визуализации метрик, поставляется с набором готовых дашбордов.
*   **[Alertmanager](../alertmanager.md):** Для управления и маршрутизации оповещений, также управляется Оператором.
*   **[Node Exporter](../Exporters/overview.md#node-exporter):** Собирает метрики с узлов Kubernetes (`DaemonSet`).
*   **[Kube-State-Metrics](../Exporters/overview.md#kube-state-metrics):** Генерирует метрики о состоянии объектов Kubernetes.

#### Ключевые CRD, управляемые Оператором:

*   **`ServiceMonitor`**:
    *   Описывает, как Prometheus должен обнаруживать и собирать метрики с группы подов, объединенных одним `Service`.
    *   Использует `selector` для поиска нужных сервисов по их лейблам.
    *   **Важный нюанс**: Prometheus Operator **не** направляет Prometheus на ClusterIP сервиса. Вместо этого он обращается к Kubernetes API, находит `Endpoints` объекта `Service` (которые содержат реальные IP-адреса подов, стоящих за сервисом) и генерирует соответствующую конфигурацию `scrape_config` для Prometheus. Это позволяет собирать метрики со всех подов, а не только с одного случайного.
    *   **Лейбл `release`**: Для корректной работы `ServiceMonitor` в Helm-установке `kube-prometheus-stack` необходимо, чтобы `ServiceMonitor` имел лейбл `release`, совпадающий с названием вашей Helm-инсталляции (например, `release: otus`). Без него Prometheus Operator не сможет найти и обработать `ServiceMonitor`.

*   **`PodMonitor`**:
    *   Аналогичен `ServiceMonitor`, но позволяет мониторить поды напрямую по их лейблам, без необходимости создавать для них сервис.

*   **`PrometheusRule`**:
    *   Позволяет декларативно описывать правила алертинга и записи (`recording rules`). Оператор автоматически загружает их в Prometheus.

*   **`Probe`**:
    *   Используется для мониторинга внешних систем (например, веб-сайтов) с помощью `blackbox-exporter`.

### Observability: Метрики, Логи, Трассировка

Важно четко различать роли различных инструментов в [Observability (наблюдаемости)](../../Concepts/Observability_and_Monitoring/observability_overview.md):

*   **Метрики (Prometheus):** Отвечают на вопрос "**Что происходит?**". Помогают понять общее состояние системы.
*   **Логи ([ELK Stack](../../ELK_Stack/elk_stack_overview.md), [Grafana Loki](../../Loki/loki_overview.md)):** Отвечают на вопрос "**Почему это произошло?**". Содержат детальную информацию о событиях.
*   **Трассировка ([Jaeger](../../Jaeger/jaeger_overview.md), [OpenTelemetry](../../OpenTelemetry/opentelemetry_overview.md)):** Отвечает на вопрос "**Как это произошло?**". Позволяет проследить путь запроса.

## Практические сценарии

### Процесс развертывания

1.  **Подготовка:**
    *   Создается отдельный `namespace` для мониторинга (например, `monitoring`).
    *   Добавляется Helm-репозиторий `prometheus-community`.

2.  **Установка через Helm:**
    *   Используется команда `helm install`.
    *   Ключевым элементом является кастомизация через файл `values.yaml`.

3.  **Настройка `values.yaml`:**
    *   **Prometheus:**
        *   `retention`: Срок хранения метрик в локальном хранилище Prometheus (например, `31d`).
        *   `requests` и `limits`: Запросы и лимиты ресурсов (CPU, Memory).
        *   `persistentVolume`: Конфигурация постоянного хранилища. Использует `volumeClaimTemplate` с указанием `storageClassName` (например, `DigitalOcean Block Storage`), `accessModes` (например, `ReadWriteOnce`) и `size`.
    *   **Grafana:**
        *   `root_url`: Важный параметр для генерации корректных ссылок в Grafana (например, для приглашений пользователей).
        *   `adminPassword`: Пароль для пользователя `admin`. Рекомендуется использовать `Secret` для хранения.
        *   `sidecar.dashboards.enabled: true`: Позволяет Grafana автоматически подгружать дашборды из `ConfigMap`, помеченных специальными лейблами. Это реализует подход "Dashboards as Code".
        *   `additionalGrafanaPlugins`: Позволяет устанавливать дополнительные плагины (например, `grafana-worldmap-panel`).
        *   `persistence`: Настройка постоянного хранилища для Grafana, чтобы сохранять дашборды, созданные через UI, и другие настройки.
    *   **Node Exporter:**
        *   `relabeling`: Настройка правил для обогащения метрик, например, для добавления читаемого имени узла (`node`) в метрики `node-exporter` (используя `__meta_kubernetes_pod_node_name`).

### Доступ к веб-интерфейсам

После установки для доступа к веб-интерфейсам Grafana или Prometheus можно использовать `kubectl port-forward`, если Ingress не настроен. Это эквивалентно SSH-туннелю и позволяет получить доступ к сервисам, работающим внутри кластера, через локальный порт на вашей машине.

*   **Для Grafana (порт 3000):**
    ```bash
    kubectl -n monitoring port-forward svc/kube-prometheus-stack-grafana 3000:80
    ```
    Затем откройте `http://localhost:3000` в браузере. (Имя сервиса может отличаться, например, `prometheus-grafana`).
*   **Для Prometheus (порт 9090):**
    ```bash
    kubectl -n monitoring port-forward svc/kube-prometheus-stack-prometheus 9090:9090
    ```

### Мониторинг внешних ресурсов

1.  **Blackbox-мониторинг:**
    *   Используется `blackbox-exporter` для выполнения внешних проверок доступности (HTTP, TCP, ICMP) произвольных ресурсов.
    *   Настраивается либо через CRD `Probe` (при использовании `kube-prometheus-stack`), либо путем включения `ServiceMonitor` для `blackbox-exporter` и указания целей через его параметры.
    *   Пример: проверка доступности внешнего URL (`google.com`) или внутреннего IP-адреса не-Kubernetes узла (`192.168.1.77`).
    *   **Совет из лекции**: Используйте `Probe` CRD для удобной декларативной настройки blackbox-проверок.

2.  **Whitebox-мониторинг (для систем с Prometheus-метриками):**
    *   Если внешний сервис (например, ВМ, физический сервер) уже отдает метрики в формате Prometheus (например, на нем запущен `node-exporter`), его можно добавить в конфигурацию Prometheus, запущенного в Kubernetes.
    *   Это делается через секцию `prometheus.prometheusSpec.additionalScrapeConfigs` в `values.yaml` Helm-чарта. Сюда можно вписать статические конфигурации (`static_configs`) для целей вне Kubernetes:
        ```yaml
        prometheus:
          prometheusSpec:
            additionalScrapeConfigs:
              - job_name: 'external-non-k8s-host'
                static_configs:
                  - targets: ['192.168.1.100:9100'] # IP и порт node-exporter на внешней ВМ
                    labels:
                      env: 'production'
        ```
    *   **Условие**: Необходима сетевая связность между Prometheus в Kubernetes и внешними целями.
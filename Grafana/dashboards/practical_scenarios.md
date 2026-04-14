# Grafana: Дашборды — Практические сценарии

## Сценарий 1: Создание дашборда с нуля

1. **Создайте дашборд**: Перейдите в **Dashboards -> New Dashboard**. В настройках (`Dashboard settings`) задайте имя и выберите папку для хранения.

2. **Добавьте панель (Graph)**: Нажмите **Add panel -> Add new panel**.
    - **Источник данных**: Выберите ваш источник (например, Prometheus).
    - **Запрос**: Напишите PromQL-запрос. Для отображения скорости роста счетчика используйте функцию `rate()`:

      ```promql
      # Потребление CPU в пользовательском режиме за последнюю минуту
      rate(node_cpu_seconds_total{mode="user"}[1m])
      ```

    - **Легенда**: Для читаемости настройте легенду, используя краткие, стабильные шаблоны. Например, `{{deployment}}` или `{{job}}/{{instance}}`.

3. **Добавьте вторую панель (Gauge)**: Нажмите **Add panel**.
    - **Визуализация**: Справа выберите тип **Gauge**.
    - **Запрос**: Добавьте запрос, возвращающий одно числовое значение:

      ```promql
      # Количество активных горутин
      go_goroutines{job="prometheus"}
      ```

4. **Сохраните дашборд**: Нажмите **Save** в правом верхнем углу.

---

## Сценарий 2: Использование переменных для динамических дашбордов

1. **Создайте переменную**:
    - Перейдите в **Dashboard settings -> Variables** и нажмите **New**.
    - **Name**: `namespace`.
    - **Type**: `Query`.
    - **Data source**: Prometheus.
    - **Query**: Используйте `label_values`, чтобы получить список всех `namespace` из метрики:

      ```promql
      label_values(kube_deployment_status_replicas_available, namespace)
      ```

      Или более общие запросы:

      ```promql
      label_values(up, job)
      label_values(up{job="$job"}, instance)
      ```

    - **Selection Options**: Включите **Multi-value** и **Include All option**.

2. **Используйте переменную в запросе**:
    - В настройках панели измените запрос, добавив фильтр по переменной. Используйте `$` для ссылки на переменную и `=~` для поддержки нескольких значений.

      ```promql
      kube_deployment_status_replicas_available{namespace=~"$namespace"}
      ```

    - Теперь дашборд будет динамически обновляться при выборе `namespace` из выпадающего списка.

3. **Повторение панелей**: Повторение панелей по переменной (например, `$instance`) позволяет показывать однотипные графики для множества узлов без дублирования конфигурации.

---

## Сценарий 3: Импорт готовых дашбордов

У Grafana есть огромная [библиотека готовых дашбордов](https://grafana.com/grafana/dashboards/).

1. **Найдите дашборд**: Например, **Node Exporter Full** (ID `1860`) для мониторинга хоста или **cAdvisor Exporter** (ID `14282`) для Docker-контейнеров.

2. **Импортируйте**:
    - Перейдите в **Dashboards -> New -> Import**.
    - Вставьте ID дашборда в поле "Import via grafana.com".
    - Нажмите **Load**.
    - В настройках выберите правильный источник данных (Prometheus) и нажмите **Import**.

---

## Сценарий 4: Клонирование и модификация дашборда

Для безопасного создания копии дашборда (например, для переноса между средами или создания вариации):

1. Откройте дашборд, который хотите скопировать.
2. Нажмите **Share -> Export**.
3. Активируйте переключатель **"Export for sharing externally"**. Это очистит из JSON все уникальные ID, которые могут вызвать конфликт.
4. Скопируйте JSON.
5. Перейдите в **Dashboards -> New -> Import** и вставьте скопированный JSON. Grafana создаст новую, независимую копию.

---

## Сценарий 5: Создание плейлистов для NOC

1. Перейдите в **Dashboards -> Playlists** и нажмите **New playlist**.
2. Задайте имя и интервал переключения (например, `1m`).
3. Добавьте в плейлист существующие дашборды.
4. Сохраните и запустите плейлист в режиме **TV** или **Kiosk** для полноэкранного отображения без лишних элементов интерфейса.

---

## Сценарий 6: Дашборд здоровья приложения в Kubernetes

Этот сценарий описывает создание дашборда для оценки здоровья приложения, запущенного в Kubernetes. Дашборд предназначен для дежурного инженера и должен позволять быстро оценить состояние сервиса.

### 6.1 Базовые метрики состояния

#### Количество контейнеров в поде

Панель показывает соотношение работающих контейнеров к общему количеству:

```promql
# Доступные реплики / Желаемые реплики
kube_deployment_status_replicas_available{deployment="<deployment_name>", namespace="<namespace>"}
/
kube_deployment_status_replicas{deployment="<deployment_name>", namespace="<namespace>"}
```

**Визуализация:** Stat или Gauge с пороговыми значениями:

- **Зеленый:** 100% (все реплики доступны)
- **Желтый:** 50-99% (частичная доступность)
- **Красный:** <50% (критическая недоступность)

#### Статусы подов и контейнеров

Панель для отслеживания состояний подов:

```promql
# Поды по статусам
count by (phase) (kube_pod_status_phase{namespace="<namespace>", phase=~"Running|Pending|Failed|Unknown|Succeeded"})
```

**Детализация по причинам завершения контейнеров:**

```promql
# OOM Killed контейнеры
count(kube_pod_container_status_last_terminated_reason{reason="OOMKilled", namespace="<namespace>"})

# Error статусы
count(kube_pod_container_status_last_terminated_reason{reason="Error", namespace="<namespace>"})

# Completed статусы
count(kube_pod_container_status_state_completed{namespace="<namespace>"} == 1)
```

**Визуализация:** Table или State Timeline с группировкой по причинам (`reason`).

### 6.2 Инфраструктурные метрики

#### CPU (Total Seconds)

```promql
# Потребление CPU контейнером
rate(container_cpu_usage_seconds_total{namespace="<namespace>", container="<container_name>"}[5m])
```

**Визуализация:** Time series с пороговыми значениями на основе `limits`.

#### Память

```promql
# Использование памяти контейнером
container_memory_usage_bytes{namespace="<namespace>", container="<container_name>"}

# Процент использования от limits
container_memory_usage_bytes{namespace="<namespace>", container="<container_name>"}
/
kube_pod_container_resource_limits{resource="memory", namespace="<namespace>", container="<container_name>"}
* 100
```

**Визуализация:** Time series + Gauge с порогом 80-90%.

### 6.3 Метрики деплойментов

#### Реплики и доступность

```promql
# Желаемые vs Доступные реплики
kube_deployment_status_replicas{deployment="<deployment_name>"}
kube_deployment_status_replicas_available{deployment="<deployment_name>"}
kube_deployment_status_replicas_unavailable{deployment="<deployment_name>"}
```

**Визуализация:** Stat с сравнением (например, `5/5 available`).

#### Ошибки конфигурации

```promql
# ConfigMap не загружены
count(kube_configmap_info{namespace="<namespace>"} == 0)

# Secret не загружены
count(kube_secret_info{namespace="<namespace>"} == 0)
```

### 6.4 Логи (опционально)

При наличии Loki можно добавить панель с последними логами:

```logql
{namespace="<namespace>", pod=~"<pod_name>.*"} |~ "ERROR|Exception|Fatal" | line_format "{{.pod}}: {{.line}}"
```

**Визуализация:** Logs panel с фильтром по уровню ошибок.

### 6.5 Рекомендуемая структура дашборда

| Row | Панели | Тип визуализации |
| :--- | :--- | :--- |
| **Status Overview** | Доступность реплик, Статусы подов | Stat, State Timeline |
| **Container Health** | OOM Killed, Error, Completed | Table, Bar chart |
| **Resources** | CPU, Memory usage | Time series, Gauge |
| **Deployment Metrics** | Реплики, ConfigMap/Secret статусы | Stat, Table |
| **Logs** | Последние ошибки | Logs panel |

### 6.6 Переменные для динамической фильтрации

Создайте переменные для удобной навигации:

| Имя | Query | Описание |
| :--- | :--- | :--- |
| `namespace` | `label_values(kube_namespace_labels, namespace)` | Выбор namespace |
| `deployment` | `label_values(kube_deployment_labels{namespace="$namespace"}, deployment)` | Выбор деплоймента |
| `pod` | `label_values(kube_pod_labels{namespace="$namespace"}, pod)` | Выбор пода |
| `container` | `label_values(kube_pod_container_info{namespace="$namespace", pod="$pod"}, container)` | Выбор контейнера |

> **См. также:** [Алертинг в Grafana](../alerting/concepts.md) для настройки уведомлений при критических состояниях.

---

## Ссылки

- **[Определения и концепции](./definitions_and_concepts.md)** — базовая информация
- **[Провижионинг через ConfigMap](./provisioning_configmap.md)** — развертывание дашбордов
- **[Provisioning](../grafana_provisioning.md)** — управление дашбордами как код
- **[Kubernetes Monitoring](../../Kubernetes/MonitoringLogging/kubernetes-monitoring-logging-architecture.md)** — мониторинг Kubernetes

# Установка Tempo и TraceQL

## Определения

**Установка Tempo** — развёртывание хранилища трассировок в Kubernetes или как монолит.

**TraceQL** — язык запросов для поиска и фильтрации трассировок в Tempo.

> **Навигация:** [Главная Tempo](./index.md) | [Архитектура](./architecture_operations.md)

---

## Practical Scenarios

### Установка

#### Способы установки

* **Бинарный файл:** Доступны бинарники для Linux, macOS и Windows.
* **Docker:** Использовать официальный [Docker-образ](../Docker/docker_overview.md).
* **Kubernetes:** Развернуть с помощью Helm-чарта в [Kubernetes](../Kubernetes/kubernetes_overview.md).
* **Grafana Cloud:** Использовать Tempo как сервис.

#### Развёртывание в Kubernetes

```bash
# Добавление репозитория
helm repo add grafana https://grafana.github.io/helm-charts
helm repo update

# Установка Tempo (распределённая версия)
helm install tempo grafana/tempo-distributed \
  --namespace tempo \
  --create-namespace
```

> **См. также:** [LGTM Stack в Minikube](../Kubernetes/Installation/LGTM_Stack/lgtm_otel_minikube_overview.md)

---

### Язык запросов TraceQL

**TraceQL** — это язык запросов для поиска и фильтрации трассировок в Tempo. Он позволяет искать трассировки по атрибутам спанов, продолжительности, времени выполнения и другим параметрам. TraceQL вдохновлен PromQL и LogQL, что обеспечивает схожесть синтаксиса и упрощает освоение.

#### Базовый синтаксис

```traceql
// Фильтрация по атрибутам спанов
{.service.name = "frontend" && .http.status_code = 500}

// Фильтрация по продолжительности спанов
{.duration > 100ms}

// Поиск по событиям (events)
{ event.name = "exception" }

// Поиск по ссылкам (links)
{ link.opentracing.ref_type = "child_of" }

// Комбинированные запросы
{ .service.name = "auth" } && { .service.name = "payment" }
```

#### TraceQL Metrics (экспериментально, с v2.6)

TraceQL поддерживает агрегацию и подсчет метрик на основе трассировок:

```traceql
// Подсчёт по сервисам
count_by(.service.name)

// Сравнение метрик
compare(rate({.status = error}[1h]))

// Мгновенные запросы (быстрее диапазонных)
/api/metrics/query?q={.duration > 1s}
```

> **Важно:** Для TraceQL Metrics требуется `replication_factor: 1` и настройка `local-blocks` processor.

#### Примеры возможностей TraceQL

* Фильтрация по атрибутам спанов: `{.service.name = "frontend" && .http.status_code = 500}`
* Фильтрация по продолжительности спанов: `{.duration > 100ms}`
* Поиск по событиям (events) и ссылкам (links)
* Агрегация и подсчет: `count_by(.service.name)`
* Функция `compare()` для сравнения метрик
* Мгновенные запросы метрик (instant queries)

---

## Additional Information

### Связанные темы

* **[LGTM Stack в Minikube](../Kubernetes/Installation/LGTM_Stack/lgtm_otel_minikube_overview.md)** — пример развёртывания
* **[Grafana datasources](../Grafana/grafana_datasources.md)** — настройка datasource Tempo

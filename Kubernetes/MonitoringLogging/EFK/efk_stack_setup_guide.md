# Стек EFK в Kubernetes

<!--
Reliability: 10 (Основано на стандартных Helm-чартах Elastic и Fluent)
Freshness: 10 (Актуально для версий Elasticsearch 8.x и Fluent Bit 3.x)
-->

## Определения

**Стек EFK (Elasticsearch, Fluent Bit, Kibana)** — комплексное решение для сбора, хранения и визуализации логов в среде Kubernetes.

**Elasticsearch** — распределенный поисковый и аналитический движок, используемый как централизованное хранилище логов.

**Fluent Bit** — легковесный агент сбора и обработки логов (Log Shipper), оптимизированный для работы в контейнеризированных средах.

**Kibana** — веб-интерфейс для визуализации данных и выполнения поисковых запросов к Elasticsearch.

**Helm** — менеджер пакетов для Kubernetes, используемый для автоматизации развертывания компонентов стека.

## Основные концепции

### Архитектура сбора логов

В кластере Kubernetes Fluent Bit развертывается как **DaemonSet** (один под на каждый узел). Он собирает стандартные потоки вывода (`STDOUT`/`STDERR`) контейнеров, обогащает их метаданными Kubernetes (имена подов, пространств имен, меток) и пересылает в Elasticsearch.

### Управление индексами

Логи в Elasticsearch группируются в **индексы**. Для эффективного управления данными используется:
* **Ротация индексов**: создание новых индексов по времени (например, ежедневно).
* **ILM (Index Lifecycle Management)** — управление жизненным циклом индексов (автоматическое перемещение на дешевые диски или удаление старых данных).
* **Data Views (Index Patterns)** — шаблоны в Kibana, объединяющие группу индексов для поиска (например, `kube-logs-*`).

### Оптимизация ресурсов

* **JVM (Java Virtual Machine)**: Elasticsearch требует настройки параметров памяти `Xms` и `Xmx`. Рекомендуется устанавливать их в значение, равное 50% от доступной оперативной памяти пода.
* **Backpressure**: механизм Fluent Bit для приостановки чтения логов при переполнении буферов или недоступности хранилища.

## Практические сценарии

### Развертывание стека EFK через Helm

#### 1. Подготовка окружения

Создайте пространство имен для логирования и добавьте репозитории чартов.

```bash
kubectl create ns logging
helm repo add elastic https://helm.elastic.co
helm repo add fluent https://fluent.github.io/helm-charts
helm repo update
```

#### 2. Установка Elasticsearch

Для обеспечения отказоустойчивости рекомендуется использовать минимум 3 реплики.

```bash
helm upgrade --install elasticsearch elastic/elasticsearch \
  --namespace logging \
  --set replicas=3 \
  --set esJavaOpts="-Xmx1g -Xms1g" \
  --set resources.requests.cpu="100m" \
  --set resources.requests.memory="2Gi" \
  --set resources.limits.cpu="1000m" \
  --set resources.limits.memory="2Gi" \
  --set volumeClaimTemplate.resources.requests.storage="10Gi"
```

#### 3. Установка Fluent Bit

Настройте толерантности (`tolerations`), чтобы агент работал на всех узлах, включая мастер-ноды.

```bash
helm upgrade --install fluent-bit fluent/fluent-bit \
  --namespace logging \
  --set tolerations[0].operator="Exists" \
  --set tolerations[0].effect="NoSchedule"
```

#### 4. Установка Kibana

Для доступа к интерфейсу настройте `Ingress`.

```bash
helm upgrade --install kibana elastic/kibana \
  --namespace logging \
  --set ingress.enabled=true \
  --set ingress.hosts[0].host="kibana.example.com" \
  --set ingress.hosts[0].paths[0].path="/"
```

### Настройка парсинга и фильтрации

* **JSON (JavaScript Object Notation)**: Для автоматического разбора структурированных логов включите `Merge_Log On` в конфигурации Fluent Bit.
* **Системные логи**: Для сбора логов Kubelet или Docker Engine используйте плагин `systemd`.

## Дополнительная информация

* [Конфигурация Fluent Bit](./fluentbit/fluentbit_configuration.md) — детальное описание настройки секций INPUT, FILTER и OUTPUT.
* [Парсинг логов во Fluent Bit](./fluentbit/parsing.md) — работа с регулярными выражениями и многострочными логами.
* [Практическое руководство по Kibana](./kibana_guide.md) — поиск логов и создание дашбордов.
* [Устранение неполадок EFK](./efk_stack_troubleshooting.md) — решение типичных проблем при развертывании и эксплуатации.
* [Сравнение Fluentd и Fluent Bit](./fluentbit/fluent_comparison.md) — выбор между агентом и агрегатором.

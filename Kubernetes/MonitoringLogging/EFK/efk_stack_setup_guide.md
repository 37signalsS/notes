# Стек EFK в Kubernetes

## Определения

**Стек EFK** — это комплексное решение для сбора, хранения и визуализации логов в среде Kubernetes, состоящее из трех ключевых компонентов:
- **Elasticsearch**: поисковый и аналитический движок.
- **Fluent Bit**: сборщик и обработчик логов.
- **Kibana**: веб-интерфейс для визуализации и анализа данных.

## Базовые концепции

Компоненты стека выполняют следующие роли в процессе управления логами:

- **[Elasticsearch](../../../ELK_Stack/Elasticsearch/elasticsearch_sharding_replication_cluster.md)**: Используется как централизованное хранилище для логов. Он индексирует поступающие данные, обеспечивая их быстрый поиск и анализ.

- **Fluent Bit**: Работает как легковесный агент, который развертывается на каждом узле кластера Kubernetes (обычно с помощью `DaemonSet`). Его задача — собирать логи из всех подов на узле, обогащать их метаданными (например, именами подов и неймспейсов) и отправлять в Elasticsearch.

- **Kibana**: Предоставляет графический интерфейс для взаимодействия с данными в Elasticsearch. С помощью Kibana инженеры могут выполнять полнотекстовый поиск по логам, создавать дашборды для мониторинга состояния системы и анализировать события.

## Практический сценарий: Настройка стека EFK

### 1. Подготовка

Создадим отдельное пространство имен `logging` для всех компонентов стека.
```bash
kubectl create ns logging
```

Добавим необходимые Helm-репозитории.
```bash
helm repo add elastic https://helm.elastic.co
helm repo add fluent https://fluent.github.io/helm-charts
helm repo update
```

### 2. Установка Elasticsearch

Установим Elasticsearch с помощью Helm. Ключевые параметры:

*   **`replicas`**: Количество реплик Elasticsearch. Для отказоустойчивости рекомендуется 3.
*   **`esJavaOpts`**: Настройки JVM. Рекомендуется устанавливать `Xms` и `Xmx` в половину от лимита памяти пода.
*   **`resources`**: Лимиты и запросы для подов. Elasticsearch требователен к памяти.
*   **`volumeClaimTemplate.resources.requests.storage`**: Размер диска для хранения данных.

Создадим отдельный `namespace` для компонентов логирования:

```bash
kubectl create ns logging
```

Установим Elasticsearch с помощью Helm, применив необходимые параметры:

```bash
helm upgrade --install elasticsearch elastic/elasticsearch \
  --namespace logging \
  --set replicas=3 \
  --set esJavaOpts="-Xmx1g -Xms1g" \
  --set resources.requests.cpu="100m" \
  --set resources.requests.memory="2Gi" \
  --set resources.limits.cpu="1000m" \
  --set resources.limits.memory="2Gi" \
  --set volumeClaimTemplate.resources.requests.storage="5Gi"
```
После установки проверьте статус подов:
```bash
kubectl get pods -n logging
```

### 3. Установка Fluent Bit

Установим Fluent Bit. Важно добавить `tolerations`, чтобы агент собирал логи со всех узлов, включая `master`-ноды.
```bash
helm upgrade --install fluent-bit fluent/fluent-bit \
  --namespace logging \
  --set tolerations[0].operator="Exists" \
  --set tolerations[0].effect="NoSchedule"
```
Проверьте, что поды Fluent Bit запустились на всех узлах кластера:
```bash
kubectl get pods -n logging -o wide
```

### 4. Установка Kibana

Установим Kibana и включим `Ingress` для доступа к веб-интерфейсу.
```bash
helm upgrade --install kibana elastic/kibana \
  --namespace logging \
  --set ingress.enabled=true \
  --set ingress.hosts[0].host="kibana.example.com" \
  --set ingress.hosts[0].paths[0].path="/"
```
> **Важно:** Замените `kibana.example.com` на ваш реальный домен.

### 5. Доступ и использование

После успешного запуска пода Kibana вы сможете получить доступ к веб-интерфейсу по адресу, указанному в `Ingress`.

## Дополнительная информация

- В production-средах рекомендуется выносить Elasticsearch за пределы кластера Kubernetes на выделенные серверы для обеспечения производительности и надежности. Для буферизации большого потока логов перед Elasticsearch можно использовать, например, Kafka.
- В данном руководстве параметры передаются через флаг `--set` для простоты. В реальных проектах рекомендуется использовать файлы `values.yaml` для управления конфигурацией.
- Для более детального разбора параметров `values.yaml` Fluent Bit обратитесь к документу **[Глубокое погружение в конфигурацию Fluent Bit](./fluentbit_deep_dive.md)**.
- Подробности о работе с логами в Kibana описаны в **[практическом руководстве](./kibana_guide.md)**.
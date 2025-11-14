# Руководство по настройке стека EFK (Elasticsearch, Fluent Bit, Kibana) в Kubernetes

В этом руководстве рассматривается процесс установки и настройки стека для сбора и визуализации логов в кластере Kubernetes с использованием Elasticsearch, Fluent Bit и Kibana.

## 1. Установка [Elasticsearch](../Elasticsearch/elasticsearch_sharding_replication_cluster.md)

Elasticsearch будет использоваться для хранения и индексации логов.

### 1.1. Добавление Helm-репозитория Elastic

Добавьте официальный Helm-репозиторий Elastic:

```bash
helm repo add elastic https://helm.elastic.co
helm repo update
```

### 1.2. Настройка и установка

В данном руководстве мы будем передавать кастомные значения напрямую через флаг `--set` для простоты. В реальных проектах рекомендуется использовать файл `values.yaml`.

Ключевые параметры для изменения:
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

> **Примечание:** В production-средах рекомендуется выносить Elasticsearch за пределы кластера Kubernetes на выделенные серверы для обеспечения производительности и надежности. Для буферизации большого потока логов перед Elasticsearch можно использовать, например, Kafka.

После установки проверьте статус подов:

```bash
kubectl get pods -n logging
```

## 2. Установка Fluent Bit

Fluent Bit — это легковесный сборщик логов, который будет работать как DaemonSet на каждой ноде кластера.

### 2.1. Добавление Helm-репозитория Fluent

```bash
helm repo add fluent https://fluent.github.io/helm-charts
helm repo update
```

### 2.2. Настройка и установка

Ключевые моменты конфигурации:
*   **Tolerations:** Чтобы Fluent Bit собирал логи со всех нод, включая `master` и `ingress` ноды со специальными `taints`, необходимо добавить `tolerations`.
*   **Output:** Конфигурация вывода логов уже настроена на отправку в сервис `elasticsearch-master.logging.svc.cluster.local`, который был создан на предыдущем шаге.

Установим Fluent Bit, добавив `tolerations` через флаг `--set`:

```bash
helm upgrade --install fluent-bit fluent/fluent-bit \
  --namespace logging \
  --set tolerations[0].operator="Exists" \
  --set tolerations[0].effect="NoSchedule"
```

После применения `tolerations` Fluent Bit должен запуститься на всех нодах кластера. Проверьте поды:

```bash
kubectl get pods -n logging -o wide
```

## 3. Установка Kibana

Kibana — это веб-интерфейс для поиска, анализа и визуализации данных из Elasticsearch.

### 3.1. Настройка и установка

Основная настройка — это включение `Ingress` для доступа к веб-интерфейсу Kibana извне кластера.

Установим Kibana с настроенным `Ingress`:

```bash
helm upgrade --install kibana elastic/kibana \
  --namespace logging \
  --set ingress.enabled=true \
  --set ingress.hosts[0].host="kibana.example.com" \
  --set ingress.hosts[0].paths[0].path="/"
```
> Замените `kibana.example.com` на ваш реальный домен.

### 3.2. Доступ к Kibana

После успешного запуска пода Kibana вы сможете получить доступ к веб-интерфейсу по адресу, указанному в `Ingress` (например, `http://kibana.example.com`).

## 4. Дальнейшая настройка и использование

Это руководство описывает базовую установку. Для более детального изучения конфигурации и использования компонентов обратитесь к следующим документам:

-   **[Глубокое погружение в конфигурацию Fluent Bit](./fluentbit_deep_dive.md)**: Подробный разбор параметров `values.yaml` для Fluent Bit, включая фильтры, парсеры, обогащение логов метаданными Kubernetes и решение проблем.
-   **[Практическое руководство по работе с Kibana](./kibana_guide.md)**: Инструкции по созданию индекс-паттернов и использованию вкладки Discover для поиска и анализа логов.
-   **[Устранение неполадок стека EFK](./efk_stack_troubleshooting.md)**: Руководство по диагностике и решению распространенных проблем с Elasticsearch, Fluent Bit и Kibana.
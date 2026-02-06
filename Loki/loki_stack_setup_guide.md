# Настройка стека Loki в Kubernetes

## 1. Определения

Для ознакомления с определениями, архитектурой, языком запросов LogQL и другими базовыми концепциями обратитесь к основному источнику знаний: **[Обзор Grafana Loki](./loki_overview.md)**.

## 2. Практические сценарии

### Подготовка: Добавление Helm-репозитория

Добавьте официальный Helm-репозиторий Grafana, который содержит чарты для всех компонентов стека:

```bash
helm repo add grafana https://grafana.github.io/helm-charts
helm repo update
```

### Установка Loki

Loki будет использоваться для хранения и индексации логов.

#### Настройка Values для Loki

Сохраним стандартные `values` для дальнейшей кастомизации:

```bash
helm show values grafana/loki > loki_values.yaml
```

Основные параметры для изменения в файле `loki_values.yaml`:

*   **`persistence`**: Настройка постоянного хранилища для Loki. В production-средах рекомендуется использовать облачные хранилища (S3, GCS) или распределенные файловые системы. Для тестовых сред можно использовать `filesystem`.
*   **`replicas`**: Количество реплик Loki. Для высокой доступности рекомендуется 3 и более.
*   **`resources`**: Настройка ресурсов CPU и памяти для подов Loki.

Пример изменения `persistence` (для тестовой среды):

```yaml
# В файле loki_values.yaml
persistence:
  enabled: true
  size: 10Gi
  storageClassName: "your-storage-class" # Укажите ваш storage class
```

> **Примечание:** В некоторых учебных средах с ограниченными ресурсами (например, диски по 5GB на ноду), может потребоваться уменьшить `size` до `5Gi`, чтобы избежать проблем с нехваткой места.

#### Установка Loki

Установим Loki с помощью Helm в `logging` namespace:

```bash
helm upgrade --install loki grafana/loki \
  --namespace logging \
  -f loki_values.yaml
```

Проверьте статус подов:

```bash
kubectl get pods -n logging -l app.kubernetes.io/name=loki
```

### Установка Promtail

Promtail — это агент для сбора логов, который будет работать как DaemonSet на каждой ноде кластера и отправлять логи в Loki.

#### Настройка Values для Promtail

Сохраним `values` для чарта `grafana/promtail`:

```bash
helm show values grafana/promtail > promtail_values.yaml
```

Ключевые моменты конфигурации в файле `promtail_values.yaml`:

*   **`loki.serviceName`**: Убедитесь, что Promtail настроен на отправку логов в сервис Loki. По умолчанию это `loki`.
*   **`tolerations`**: Чтобы Promtail собирал логи со всех нод, включая `master` и `ingress` ноды со специальными `taints`, необходимо добавить `tolerations`.

Добавьте в `promtail_values.yaml` следующие `tolerations`. Это позволит Promtail запускаться на всех нодах, включая `master` и `ingress`, игнорируя любые `taints` (независимо от их `key` и `effect`), что необходимо для полного сбора логов со всего кластера.

```yaml
# В файле promtail_values.yaml
tolerations:
  - operator: "Exists"
```

#### Установка Promtail

Установим Promtail, применив измененные `values`:

```bash
helm upgrade --install promtail grafana/promtail \
  --namespace logging \
  -f promtail_values.yaml
```

Проверьте поды:

```bash
kubectl get pods -n logging -l app.kubernetes.io/name=promtail -o wide
```

### Установка Grafana

Grafana будет использоваться для визуализации и анализа логов из Loki.

#### Настройка Values для Grafana

Сохраним `values` для чарта `grafana/grafana`:

```bash
helm show values grafana/grafana > grafana_values.yaml
```

Основные настройки в файле `grafana_values.yaml`:

*   **`ingress.enabled`**: Включите Ingress для доступа к веб-интерфейсу Grafana извне кластера.
*   **`ingress.hosts`**: Укажите доменное имя для доступа к Grafana.
*   **`adminPassword`**: Установите надежный пароль для пользователя `admin`.
*   **`datasources`**: Настройте Loki как источник данных по умолчанию.

Пример изменения `ingress` и `datasources`:

```yaml
# В файле grafana_values.yaml
ingress:
  enabled: true
  hosts:
    - grafana.example.com # Замените на ваш домен
  # ... другие настройки Ingress

adminPassword: "your-secure-password" # Обязательно измените!

datasources:
  datasources.yaml:
    apiVersion: 1
    datasources:
      - name: Loki
        type: loki
        access: proxy
        orgId: 1
        url: http://loki.logging.svc.cluster.local:3100 # URL сервиса Loki
        isDefault: true
        version: 1
        editable: true
```

#### Установка Grafana

Установим Grafana с настроенным Ingress и источником данных Loki:

```bash
helm upgrade --install grafana grafana/grafana \
  --namespace logging \
  -f grafana_values.yaml
```

#### Доступ к Grafana

После успешного запуска пода Grafana вы сможете получить доступ к веб-интерфейсу по адресу, указанному в `Ingress` (например, `http://grafana.example.com`). Войдите с логином `admin` и установленным вами паролем.

### Работа с логами в Grafana

После установки стека можно приступать к анализу логов в Grafana.

#### Подключение Loki как источника данных (вручную)

Если вы не настроили `datasource` через `values.yaml` при установке Grafana, его можно добавить вручную:

1.  Перейдите в `Configuration` -> `Data Sources`.
2.  Нажмите `Add data source` и выберите `Loki`.
3.  В поле `URL` укажите адрес сервиса Loki. Обычно это `http://loki:3100`.
    *   **Важно:** Если Grafana и Loki находятся в разных `namespaces` (например, Grafana в `monitoring`, а Loki в `logging`), используйте полное имя сервиса: `http://loki.logging.svc.cluster.local:3100`.
4.  Нажмите `Save & Test`. Grafana должна показать сообщение об успешном подключении.

#### Анализ логов с помощью LogQL

После подключения источника данных вы можете анализировать логи с помощью языка запросов LogQL в разделе `Explore`.

Подробное описание языка, его функций и примеры запросов вы найдете в основной теоретической заметке: **[Обзор Grafana Loki (раздел LogQL)](./loki_overview.md#язык-запросов-logql)**.

Примеры запросов, специфичные для Kubernetes:

*   **Логи из конкретного namespace:** `{namespace="ingress-nginx"}`
*   **Логи конкретного пода:** `{pod="my-app-pod-12345"}`
*   **Поиск ошибок в логах Java-приложения:** `{app="my-java-app"} |= "Exception"`
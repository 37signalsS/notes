# Установка Grafana в Kubernetes

## Подготовка

Grafana будет использоваться для визуализации и анализа логов из Loki.

## Настройка Values для Grafana

Сохраним `values` для чарта `grafana/grafana`:

```bash
helm show values grafana/grafana > grafana_values.yaml
```

### Актуальные параметры для Grafana 10.x/11.x

| Параметр | Описание | Рекомендуемое значение |
| :--- | :--- | :--- |
| **`ingress.enabled`** | Включить Ingress | `true` (для доступа извне) |
| **`ingress.hosts`** | Хосты для Ingress | `["grafana.example.com"]` |
| **`adminPassword`** | Пароль admin | Используйте secrets! |
| **`datasources`** | Источники данных | Loki, Prometheus |
| **`persistence.enabled`** | Персистентность | `true` |
| **`serviceMonitor.enabled`** | ServiceMonitor | `true` |

### Пример `grafana_values.yaml`

```yaml
# grafana_values.yaml
ingress:
  enabled: true
  hosts:
    - grafana.example.com
  annotations:
    kubernetes.io/ingress.class: nginx
  tls:
    - secretName: grafana-tls
      hosts:
        - grafana.example.com

admin:
  existingSecret: grafana-admin-secret
  userKey: admin-user
  passwordKey: admin-password

datasources:
  datasources.yaml:
    apiVersion: 1
    datasources:
      - name: Loki
        type: loki
        access: proxy
        orgId: 1
        url: http://loki-gateway.logging.svc.cluster.local:80
        isDefault: true
        version: 1
        editable: false
      - name: Prometheus
        type: prometheus
        access: proxy
        orgId: 1
        url: http://prometheus-server.monitoring.svc.cluster.local:80
        version: 1
        editable: false

persistence:
  enabled: true
  size: 10Gi
  storageClassName: standard

serviceMonitor:
  enabled: true
  namespace: logging
  labels:
    release: prometheus
```

> **Безопасность:** Не указывайте пароли в plain text. Используйте Kubernetes Secrets:
>
> ```bash
> kubectl create secret generic grafana-admin-secret \
>   --from-literal=admin-user="admin" \
>   --from-literal=admin-password="$(openssl rand -base64 20)" \
>   -n logging
> ```

## Установка Grafana

Установим Grafana с настроенным Ingress и источником данных Loki:

```bash
helm upgrade --install grafana grafana/grafana \
  --namespace logging \
  -f grafana_values.yaml
```

## Доступ к Grafana

После успешного запуска пода Grafana вы сможете получить доступ к веб-интерфейсу по адресу, указанному в `Ingress` (например, `https://grafana.example.com`). Войдите с логином `admin` и паролем из секрета.

## Подключение Loki как источника данных (вручную)

Если вы не настроили `datasource` через `values.yaml` при установке Grafana, его можно добавить вручную:

1. Перейдите в **Connections** → **Data sources**
2. Нажмите **Add data source** и выберите **Loki**
3. В поле **URL** укажите адрес сервиса Loki:
   * Если Grafana и Loki в одном namespace: `http://loki:3100`
   * Если в разных namespaces: `http://loki-gateway.logging.svc.cluster.local:80`
4. Нажмите **Save & Test**

## Связанные темы

* **[Обзор Grafana Loki](../loki_overview.md)** — архитектура, LogQL
* **[Установка Loki](loki_installation.md)** — установка Loki
* **[Примеры LogQL](logql_examples.md)** — запросы для анализа логов
* **[Grafana Provisioning](../../Grafana/grafana_provisioning.md)** — автоматическая настройка дашбордов

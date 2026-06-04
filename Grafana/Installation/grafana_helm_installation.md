# Установка Grafana через Helm

## Определения

- **Grafana**: Платформа для аналитики и визуализации. См. [Обзор Grafana](../grafana_overview.md).
- **Helm**: Пакетный менеджер для Kubernetes, автоматизирующий установку и управление приложениями.
- **Helm-чарт Grafana**: Набор шаблонов Kubernetes-ресурсов для развертывания Grafana.
- **`values.yaml`**: Основной файл конфигурации Helm-чарта для кастомизации установки.

> **Примечание:** Для установки Grafana в составе полного стека мониторинга см. [kube-prometheus-stack](../../Prometheus/kubernetes/Kube_Prometheus_Stack_Helm/overview.md).

### Миграция репозитория (январь 2026)

Официальный репозиторий `grafana` (github.io/helm-charts) **устарел**. Актуальный репозиторий для чарта `grafana`:

```bash
helm repo add grafana-community https://grafana-community.github.io/helm-charts
helm repo update
```

---

## Основные концепции

### Персистентность (Persistence)

Использование **PersistentVolumeClaim (PVC)** необходимо для сохранения данных (дашбордов, настроек пользователей, плагинов) между перезапусками подов. В Helm-чарте настраивается через секцию `persistence`.

### Внешний доступ (Ingress)

Ресурс Ingress предоставляет доступ к веб-интерфейсу Grafana извне кластера. Важным параметром является `root_url` в `grafana.ini`, который должен соответствовать публичному адресу для корректной генерации ссылок.

### Автоматизация (Provisioning)

Автоматическая загрузка дашбордов и источников данных через механизм **sidecar**. Sidecar-контейнер отслеживает ConfigMaps с определенными метками (например, `grafana_dashboard: "1"`) и импортирует их в Grafana. См. [Провиженинг Grafana](../grafana_provisioning.md).

### Рендеринг изображений (Image Renderer)

Дополнительный компонент (плагин или сервис) для генерации PNG-изображений графиков, необходимых для визуализации алертов в мессенджерах (Slack, Telegram).

---

## Практические сценарии

### Сценарий 1: Базовая установка

1. **Добавление репозитория:**

    ```bash
    helm repo add grafana-community https://grafana-community.github.io/helm-charts
    helm repo update
    ```

2. **Создание конфигурации `values.yaml`:**

    ```yaml
    # grafana-values.yaml
    adminPassword: "StrongPassword123"
    
    persistence:
      enabled: true
      size: 5Gi
      storageClassName: standard

    ingress:
      enabled: true
      ingressClassName: nginx
      hosts:
        - grafana.example.com
      tls:
        - secretName: grafana-tls
          hosts:
            - grafana.example.com

    grafana.ini:
      server:
        root_url: "https://grafana.example.com"
    ```

3. **Установка:**

    ```bash
    helm install grafana grafana-community/grafana \
      -f grafana-values.yaml \
      --namespace monitoring --create-namespace
    ```

### Сценарий 2: Production-конфигурация

Для стабильной работы в продуктивной среде рекомендуется:

- Запуск от непривилегированного пользователя.
- Настройка лимитов ресурсов.
- Использование внешних секретов для паролей.

```yaml
# production-values.yaml
security:
  runAsUser: 472
  runAsGroup: 472
  fsGroup: 472

resources:
  limits:
    cpu: 500m
    memory: 512Mi
  requests:
    cpu: 100m
    memory: 256Mi

sidecar:
  dashboards:
    enabled: true
    label: grafana_dashboard
    searchNamespace: ALL

networkPolicy:
  enabled: true
```

### Сценарий 3: Проверка и обновление

**Проверка статуса:**

```bash
kubectl get pods -n monitoring -l app.kubernetes.io/name=grafana
helm status grafana -n monitoring
```

**Обновление конфигурации:**

```bash
helm upgrade grafana grafana-community/grafana -f grafana-values.yaml -n monitoring
```

---

## Дополнительная информация

### Устранение неполадок (Troubleshooting)

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Pod в статусе `Pending`** | Нет свободных PV или ресурсов | Проверьте `kubectl describe pod` и доступность PVC |
| **404 при доступе** | Ошибка в `root_url` или Ingress | Проверьте `grafana.ini` и правила Ingress |
| **Дашборды не загружаются** | Sidecar не видит ConfigMap | Проверьте метки на ConfigMap и `searchNamespace` |
| **OOMKilled** | Превышен лимит памяти | Увеличьте `resources.limits.memory` |

### Полезные команды Helm

```bash
# Просмотр всех параметров чарта
helm show values grafana-community/grafana

# Проверка истории релизов
helm history grafana -n monitoring

# Откат к предыдущей версии
helm rollback grafana <revision_number> -n monitoring
```

**См. также:**

- [Провиженинг Grafana](../grafana_provisioning.md)
- [Высокая доступность Grafana](../high_availability.md)
- [Конфигурация Grafana в kube-prometheus-stack](../../Prometheus/kubernetes/Kube_Prometheus_Stack_Helm/grafana_config.md)
- [Плагины Grafana](../grafana_plugins.md)

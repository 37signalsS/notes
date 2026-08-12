# Онлайн-установка (kube-prometheus-stack)

> [Назад к оглавлению](../overview.md)

> **SSoT для темы:** стандартная установка kube-prometheus-stack в Kubernetes с доступом к интернету через Helm.  
> **Смежные темы:** [Обзор kube-prometheus-stack](../overview.md) — компоненты, версии, архитектура; [Offline Air-gapped Installation](./offline_airgapped_installation.md) — установка в закрытых контурах; [Persistent Volumes](./persistent_volumes.md) — настройка хранилища.

## Определения

**Онлайн-установка** — развёртывание стека мониторинга в Kubernetes-кластер с неограниченным доступом к внешним ресурсам. Helm автоматически загружает чарт из публичного репозитория (`prometheus-community`), а Kubelet загружает образы из публичных реестров (docker.io, quay.io, ghcr.io).

**Helm release** — именованный экземпляр развёрнутого чарта. Имя релиза является префиксом для большинства ресурсов (Service, Pod, Secret), что критично для автоматизации и сетевой связности.

## Основные концепции

### Состав развёртываемого стека

```
helm install [RELEASE_NAME] prometheus-community/kube-prometheus-stack
    │
    ├── Prometheus Operator (Deployment)
    │       └── Управление жизненным циклом Prometheus и Alertmanager через CRD
    │
    ├── Prometheus Server (StatefulSet)
    │       └── Сбор, хранение (TSDB) и обработка метрик
    │
    ├── Alertmanager (StatefulSet)
    │       └── Обработка, группировка и маршрутизация оповещений
    │
    ├── Grafana (Deployment)
    │       └── Визуализация и преднастроенные дашборды
    │
    ├── Node Exporter (DaemonSet)
    │       └── Метрики ОС с каждого узла кластера
    │
    ├── kube-state-metrics (Deployment)
    │       └── Генерация метрик на основе объектов Kubernetes API
    │
    └── CRDs (Custom Resource Definitions)
            └── Описания ресурсов: ServiceMonitor, PodMonitor, PrometheusRule и др.
```

### Влияние имени релиза на именование ресурсов

Выбор короткого и понятного имени релиза (например, `monitoring` или `kps`) упрощает дальнейшую эксплуатацию.

| Имя релиза | Prometheus Service | Grafana Service | Secret с паролем Grafana |
|---|---|---|---|
| `monitoring` | `prometheus-operated` | `monitoring-grafana` | `monitoring-grafana` |
| `kps` | `kube-prometheus-kube-prome-prometheus` | `kube-prometheus-grafana` | `kube-prometheus-grafana` |

> **Рекомендация:** Используйте имя `monitoring` для обеспечения предсказуемости имен сервисов.

### Сравнение с offline-установкой

| Параметр | Online | Offline (Air-gapped) |
|---|---|---|
| Источник чарта | GitHub Pages (автоматически) | Локальный Registry (OCI) или файл |
| Источник образов | Публичные Registry | Приватный Harbor/Nexus/Artifactory |
| Конфигурация образов | Значения по умолчанию | Обязательное переопределение `global.imageRegistry` |
| Трудозатраты | Низкие (одна команда) | Высокие (зеркалирование образов, подготовка чарта) |

## Практические сценарии

### Сценарий 1: Быстрый старт (Minimal install)

Подходит для тестирования, разработки (Sandbox) или локальных кластеров (Minikube/Kind).

```bash
# Добавление репозитория
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update

# Установка в пространство имен monitoring
helm install monitoring prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --create-namespace
```

### Сценарий 2: Промышленная установка (Production-ready)

Использование `values.yaml` для настройки отказоустойчивости, персистентности и лимитов ресурсов.

**1. Подготовка values.yaml:**

```yaml
# values.yaml
prometheus:
  prometheusSpec:
    replicas: 2
    retention: 30d
    resources:
      requests:
        cpu: 500m
        memory: 2Gi
      limits:
        cpu: 2000m
        memory: 8Gi
    storageSpec:
      volumeClaimTemplate:
        spec:
          storageClassName: longhorn # Или gp3, standard и др.
          accessModes: ["ReadWriteOnce"]
          resources:
            requests:
              storage: 100Gi

grafana:
  adminPassword: "strong-password-here"
  persistence:
    enabled: true
    size: 10Gi
  ingress:
    enabled: true
    ingressClassName: nginx
    hosts:
      - grafana.company.tld

alertmanager:
  alertmanagerSpec:
    replicas: 3
    storage:
      volumeClaimTemplate:
        spec:
          storageClassName: longhorn
          resources:
            requests:
              storage: 5Gi
```

**2. Установка:**

```bash
helm install monitoring prometheus-community/kube-prometheus-stack \
  -n monitoring --create-namespace \
  -f values.yaml
```

### Сценарий 3: Безопасное обновление через helm-diff

Плагин `helm-diff` позволяет увидеть планируемые изменения в манифестах до их применения, что предотвращает случайное удаление ресурсов.

```bash
# Установка плагина (выполняется один раз)
helm plugin install https://github.com/databus23/helm-diff

# Просмотр изменений перед обновлением
helm diff upgrade monitoring prometheus-community/kube-prometheus-stack \
  -n monitoring \
  -f values.yaml

# Применение обновлений
helm upgrade monitoring prometheus-community/kube-prometheus-stack \
  -n monitoring \
  -f values.yaml
```

### Сценарий 4: Тестирование и верификация (helm test)

После установки или обновления рекомендуется запустить встроенные тесты Helm для проверки доступности компонентов.

```bash
# Запуск тестов
helm test monitoring -n monitoring

# Проверка статуса подов и сервисов
kubectl get all -n monitoring -l release=monitoring

# Проверка созданных CRD
kubectl get crd | grep monitoring.coreos.com
```

### Сценарий 5: Получение доступа к UI (Port-forward)

Если Ingress не настроен, можно использовать временный проброс портов.

```bash
# Grafana (доступ по http://localhost:3000)
kubectl -n monitoring port-forward svc/monitoring-grafana 3000:80

# Prometheus UI (доступ по http://localhost:9090)
kubectl -n monitoring port-forward svc/prometheus-operated 9090:9090
```

### Сценарий 6: Учётные данные и секреты

**Получение пароля администратора Grafana (если не задан в values.yaml):**

```bash
kubectl -n monitoring get secret monitoring-grafana \
  -o jsonpath='{.data.admin-password}' | base64 -d; echo
```

## Дополнительная информация

### Диагностика и устранение проблем

| Проблема | Причина | Решение |
|---|---|---|
| `ImagePullBackOff` | Rate limit на docker.io или отсутствие доступа | Настройте `global.imagePullSecrets` или зеркало; проверьте NAT/Firewall. |
| `Pending` поды | Недостаточно ресурсов (CPU/RAM) или проблемы с PVC | Выполните `kubectl describe pod`; проверьте квоты и StorageClass. |
| CRD не создаются | Конфликт с существующими CRD | Удалите старые CRD вручную; используйте `--skip-crds` только при ручном управлении. |
| Targets в статусе DOWN | Неверные селекторы в ServiceMonitor | Проверьте labels на сервисе и `matchLabels` в ServiceMonitor. |
| Grafana 404/502 (Ingress) | Ошибка в конфигурации путей | Проверьте `grafana.ingress.path` и `pathType` (обычно Prefix). |

### Рекомендации по эксплуатации (Best Practices)

1.  **Выделенный Namespace:** Всегда используйте отдельный namespace (например, `monitoring`) для изоляции ресурсов.
2.  **Фиксация версий:** При установке в production всегда указывайте версию чарта: `--version 88.1.x`.
3.  **Персистентность для TSDB:** Никогда не используйте `emptyDir` для Prometheus в production. Данные будут потеряны при любом перезапуске пода.
4.  **Лимиты ресурсов:** Настраивайте `resources.requests` максимально близко к `resources.limits` для Prometheus, чтобы избежать OOMKill при всплесках нагрузки.
5.  **Безопасность (NetworkPolicies):** Включайте сетевые политики в `values.yaml` для ограничения доступа к компонентам мониторинга:
    ```yaml
    prometheus:
      networkPolicy:
        enabled: true
    ```

### Полезные команды для отладки

```bash
# Просмотр логов оператора (основной источник правды при ошибках конфигурации)
kubectl logs -n monitoring -l app.kubernetes.io/name=prometheus-operator

# Проверка событий в пространстве имен
kubectl get events -n monitoring --sort-by='.lastTimestamp'

# Описание конкретного ресурса (например, Prometheus)
kubectl describe prometheus monitoring-kube-prometheus-prometheus -n monitoring
```

### Связанные ресурсы

* [Обзор kube-prometheus-stack](../overview.md) — детальное описание компонентов.
* [Persistent Volumes для мониторинга](./persistent_volumes.md) — подробные сценарии работы с хранилищем.
* [Настройка мониторинга внешних ресурсов](./external_monitoring.md) — сбор метрик вне кластера.
* [Grafana Configuration](../grafana_config.md) — тюнинг визуализации.

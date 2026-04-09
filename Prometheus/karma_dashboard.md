# Karma Dashboard

## Definitions

**Karma** — дашборд для [Alertmanager](./alertmanager.md), предоставляющий расширенный UI для визуализации и управления алертами. В отличие от стандартного интерфейса Alertmanager, Karma поддерживает агрегацию нескольких экземпляров, продвинутую фильтрацию и удобную работу с silences.

## Basic Concepts

### Возможности

| Функция | Описание |
|---|---|
| Агрегация | Сбор алертов из нескольких Alertmanager в едином интерфейсе |
| Фильтрация и поиск | Поиск по меткам (`labels`), статусу, severity |
| Группировка | Визуальное объединение алертов для чистоты интерфейса |
| Silences | Создание/управление тишинами прямо из UI |
| Темы | Тёмная/светлая тема |
| Stateless | Без собственного бэкенда/БД — настройки хранятся в браузере |

## Practical Scenarios

### Установка через Helm

**`values.yaml`:**

```yaml
alertmanager:
  servers:
    - name: "main"
      uri: "http://alertmanager-operated.monitoring.svc.cluster.local:9093"

ingress:
  enabled: true
  hosts:
    - name: "karma.my-domain.com"
      path: "/"

readonly: false

replicaCount: 1
resources:
  limits:
    cpu: 100m
    memory: 128Mi
  requests:
    cpu: 50m
    memory: 64Mi
```

**Развёртывание:** `helm install` или GitOps (ArgoCD) — через `Application` ресурс, указывающий на репозиторий с чартом.

### Установка через манифесты

Создаются стандартные ресурсы Kubernetes:

| Ресурс | Назначение |
|---|---|
| `ConfigMap` | Конфигурация Karma (URL Alertmanager) |
| `Deployment` | Управление подами Karma |
| `Service` | Внутренний сетевой доступ |
| `Ingress` | Внешний доступ к UI (опционально) |

## Additional Information

> Подробное руководство с манифестами: [Alertmanager + Karma в Kubernetes](./kubernetes/examples/alertmanager-karma-manifests-tutorial/intro.md)

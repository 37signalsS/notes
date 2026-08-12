# Alertmanager — Концепции (CRD)

## Определения

**`kind: Alertmanager`** — Custom Resource Definition в Prometheus Operator, предназначенный для декларативного описания развёртывания и жизненного цикла экземпляра Alertmanager в Kubernetes. Ресурс управляет созданием StatefulSet, Service, Secret и конфигурацией кластеризации.

**Reconciliation Loop в Alertmanager CRD** — процесс, при котором Оператор отслеживает изменения в объекте `Alertmanager` и связанных с ним `AlertmanagerConfig`, обеспечивая актуальность конфигурации маршрутизации и состояния подов.

**API version:** `monitoring.coreos.com/v1`

> **См. также:** [Alertmanager (общий обзор)](../../../alertmanager.md) — архитектура, маршрутизация и дедупликация.

## Базовые концепции

### Назначение и функции

CRD `Alertmanager` автоматизирует следующие задачи:
- **Масштабирование:** Управление количеством реплик (минимум 3 для обеспечения кворума в HA-режиме).
- **Хранилище:** Настройка PersistentVolume для сохранения Silences и состояния уведомлений.
- **Сетевая конфигурация:** Настройка параметров веб-интерфейса, TLS, поддержка `hostNetwork` и протокола Gossip (кластеризация).
- **Интеграция конфигураций:** Агрегация глобальных настроек и локальных маршрутов через `AlertmanagerConfig` или прямое описание в `alertmanagerConfiguration`.

### Взаимосвязь ресурсов

| Ресурс | Роль | Описание |
| :--- | :--- | :--- |
| **Alertmanager** | Infrastructure SSoT | Описывает "как" и "где" запущен инстанс (ресурсы, PVC, TLS). |
| [AlertmanagerConfig](./alertmanagerconfig.md) | Routing SSoT | Описывает "кому" и "как" отправлять алерты (receivers, routes). |
| [Prometheus](./prometheus.md) | Producer | Отправляет алерты в инстанс Alertmanager. |
| [PrometheusRule](./prometheusrule.md) | Generator | Генерирует алерты на основе метрик Prometheus. |

### Новые возможности (2025–2026)

*   **Нативная конфигурация (`spec.alertmanagerConfiguration`):** Экспериментальная возможность описывать настройки Alertmanager напрямую в CRD, минуя создание внешних секретов (`configSecret`). Имеет приоритет при заполнении обоих полей.
*   **Имена пиров (v0.30.0+):** Оператор использует имена подов в качестве имен пиров в кластере Gossip, что повышает стабильность кластеризации и упрощает диагностику по сравнению с ID-based подходом.
*   **Нативный HTTPS (`spec.web`):** Настройка TLS для веб-интерфейса напрямую через CRD, включая mTLS и выбор криптографических кривых.
*   **Безопасный Gossip (`spec.clusterTLS`):** Шифрование трафика между узлами кластера Alertmanager по протоколу Gossip (порт 9094).
*   **Topology Aware Routing:** Интеграция с Kubernetes Topology (>= 1.35) для зонального шардирования и минимизации межзонального трафика.
*   **Подресурс Status:** Поддержка условий (`Conditions`), таких как `Reconciled`, для GitOps-инструментов, позволяющая отслеживать завершение применения конфигурации.

## Практические сценарии

### Сценарий 1: Отказоустойчивая Production-конфигурация (HA + TLS)

Настройка кластера из 3 реплик с включенным TLS для веб-интерфейса и персистентным хранилищем.

```yaml
apiVersion: monitoring.coreos.com/v1
kind: Alertmanager
metadata:
  name: main
  namespace: monitoring
spec:
  replicas: 3
  version: v0.27.0
  web:
    tlsConfig:
      cert:
        secret:
          name: alertmanager-tls
          key: tls.crt
      keySecret:
        name: alertmanager-tls
        key: tls.key
  storage:
    volumeClaimTemplate:
      spec:
        storageClassName: longhorn
        accessModes: ["ReadWriteOnce"]
        resources:
          requests:
            storage: 10Gi
  alertmanagerConfigSelector:
    matchLabels:
      release: monitoring
```

### Сценарий 2: Прямая конфигурация через CRD (Experimental)

Использование поля `alertmanagerConfiguration` для задания глобальных настроек без использования Secret.

```yaml
apiVersion: monitoring.coreos.com/v1
kind: Alertmanager
metadata:
  name: direct-config
spec:
  replicas: 3
  alertmanagerConfiguration:
    name: main-config
    global:
      resolveTimeout: 5m
      httpConfig:
        followRedirects: true
    templates:
      - name: custom-templates
        key: alert.tmpl
```

### Сценарий 3: Запуск в Host Network

Использование сетевого пространства хоста для обхода ограничений CNI или минимизации задержек.

```yaml
spec:
  hostNetwork: true
  dnsPolicy: ClusterFirstWithHostNet
  securityContext:
    runAsNonRoot: true
    runAsUser: 1000
```

## Дополнительная информация

### Основные параметры спецификации (v1)

| Параметр | Описание | Значение / Особенности |
| :--- | :--- | :--- |
| **`replicas`** | Количество подов. | Рекомендуется 3 для HA. |
| **`version`** | Версия Alertmanager. | Рекомендуется v0.30+ для стабильного пиринга. |
| **`alertmanagerConfiguration`** | Встроенная конфигурация. | Экспериментально; заменяет `configSecret`. |
| **`hostNetwork`** | Использование сети хоста. | Добавлено в 2025 году. |
| **`web.tlsConfig`** | Настройка HTTPS UI. | Заменяет ручное создание `web-config.yaml`. |
| **`clusterTLS`** | TLS для Gossip (порт 9094). | Требует Alertmanager v0.24+. |
| **`paused`** | Остановка reconciliation. | Используется при ручных правках StatefulSet. |
| **`retention`** | Время хранения данных. | По умолчанию 120h (5 дней). |

### Статус реконсиляции (Reconciliation Status)

С версии Operator v0.80+ объект `Alertmanager` предоставляет детальный статус:
- **`Reconciled`**: `True` означает, что текущая конфигурация успешно применена ко всем подам.
- **`Available`**: Сигнализирует о готовности минимального количества реплик.
- **`Warning`**: Содержит сообщения о депрекации полей или ошибках в `AlertmanagerConfig`.

### Диагностика и мониторинг

1.  **Проверка статуса кластера:**
    Метрика `alertmanager_cluster_members` должна быть равна `replicas`.
2.  **Проверка конфигурации:**
    Фактическая конфигурация генерируется в Secret `alertmanager-<name>-generated` (если используется `alertmanagerConfigSelector`).
3.  **Логи оператора:**
    `kubectl logs -n monitoring -l app.kubernetes.io/name=prometheus-operator` — ищите ошибки валидации и конфликты селекторов.

### Связанные темы

*   **[AlertmanagerConfig CRD](./alertmanagerconfig.md)** — детальная настройка маршрутов.
*   **[High Availability](../high_availability.md)** — общие принципы отказоустойчивости стека.
*   **[Безопасность в Prometheus Operator](../Security/index.md)** — RBAC и TLS.

### См. также
* [Prometheus Operator API Specification (v1)](https://prometheus-operator.dev/docs/operator/api/)
* [Alertmanager Configuration Guide](https://prometheus.io/docs/alerting/latest/configuration/)

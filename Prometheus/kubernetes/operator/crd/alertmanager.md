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
- **Сетевая конфигурация:** Настройка параметров веб-интерфейса, TLS и протокола Gossip (кластеризация).
- **Интеграция конфигураций:** Агрегация глобальных настроек и локальных маршрутов из `AlertmanagerConfig`.

### Взаимосвязь ресурсов

| Ресурс | Роль | Описание |
| :--- | :--- | :--- |
| **Alertmanager** | Infrastructure SSoT | Описывает "как" и "где" запущен инстанс (ресурсы, PVC, TLS). |
| [AlertmanagerConfig](./alertmanagerconfig.md) | Routing SSoT | Описывает "кому" и "как" отправлять алерты (receivers, routes). |
| [Prometheus](./prometheus.md) | Producer | Отправляет алерты в инстанс Alertmanager. |
| [PrometheusRule](./prometheusrule.md) | Generator | Генерирует алерты на основе метрик Prometheus. |

### Новые возможности (2025–2026)

*   **Нативный HTTPS (`spec.web`):** Возможность настройки TLS для веб-интерфейса напрямую через CRD, включая mTLS и выбор криптографических кривых.
*   **Безопасный Gossip (`spec.clusterTLS`):** Шифрование трафика между узлами кластера Alertmanager по протоколу Gossip.
*   **Глобальный HTTP Config:** Управление настройками прокси, таймаутов и TLS для всех исходящих уведомлений через `spec.alertmanagerConfiguration.global.httpConfig`.
*   **Stricter API:** Переход на знаковые целые числа (`int`) с валидаторами для предотвращения ошибок конфигурации в GitOps-инструментах.

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

### Сценарий 2: Защита трафика кластеризации (Gossip TLS)

Обеспечение безопасности внутреннего взаимодействия между репликами Alertmanager.

```yaml
spec:
  clusterTLS:
    cert:
      secret:
        name: alertmanager-cluster-tls
        key: tls.crt
    keySecret:
      name: alertmanager-cluster-tls
      key: tls.key
    ca:
      configMap:
        name: root-ca
        key: ca.crt
```

### Сценарий 3: Глобальные настройки прокси для уведомлений

Настройка единого прокси-сервера для всех исходящих запросов к Slack, PagerDuty и т.д.

```yaml
spec:
  alertmanagerConfiguration:
    name: global-alert-config
    global:
      httpConfig:
        proxyUrl: "http://squid.corp.internal:3128"
        tlsConfig:
          insecureSkipVerify: false
```

## Дополнительная информация

### Основные параметры спецификации (v1)

| Параметр | Описание | Значение / Особенности |
| :--- | :--- | :--- |
| **`replicas`** | Количество подов. | Рекомендуется 3 для HA. |
| **`version`** | Версия Alertmanager. | Поддержка v0.27+ в последних релизах Operator. |
| **`alertmanagerConfigSelector`** | Поиск маршрутов. | Фильтрует объекты `AlertmanagerConfig`. |
| **`web.tlsConfig`** | Настройка HTTPS UI. | Заменяет ручное создание `web-config.yaml`. |
| **`clusterTLS`** | TLS для Gossip (порт 9094). | Требует Alertmanager v0.24+. |
| **`paused`** | Остановка reconciliation. | Используется при ручных правках StatefulSet. |
| **`retention`** | Время хранения данных. | По умолчанию 120h (5 дней). |

### Диагностика и мониторинг

1.  **Проверка статуса кластера:**
    Метрика `alertmanager_cluster_members` должна быть равна `replicas`.
2.  **Проверка конфигурации:**
    Фактическая конфигурация генерируется в Secret `alertmanager-<name>-generated`.
3.  **Логи оператора:**
    `kubectl logs -n monitoring -l app.kubernetes.io/name=prometheus-operator` — ищите ошибки валидации `AlertmanagerConfig`.

### Связанные темы

*   **[AlertmanagerConfig CRD](./alertmanagerconfig.md)** — детальная настройка маршрутов.
*   **[High Availability](../high_availability.md)** — общие принципы отказоустойчивости стека.
*   **[Безопасность в Prometheus Operator](../Security/index.md)** — RBAC и TLS.
*   **[Reliability Scores](../../../GEMINI.md)** — методология оценки достоверности (Score: 10).

### См. также
* [Prometheus Operator API Specification](https://prometheus-operator.dev/docs/operator/api/)
* [Alertmanager Configuration Guide](https://prometheus.io/docs/alerting/latest/configuration/)

# Reloader — Обзор и основные концепции

## Определения

**Reloader** — контроллер Kubernetes от Stakater, который отслеживает изменения в `ConfigMap` и `Secret` и автоматически инициирует rolling upgrade (плавное обновление) для связанных `Deployment`, `StatefulSet` или `DaemonSet`.

**Проблема:** По умолчанию Kubernetes не перезапускает поды (Pods) при изменении ConfigMap/Secret, требуя ручного вмешательства (`kubectl rollout restart`).

**Связанные файлы:** [Установка](./reloader_installation.md) · [Использование](./reloader_usage_scenarios.md) · [Мониторинг](./reloader_monitoring_and_best_practices.md)

---

## Основные концепции

### Принцип работы

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  ConfigMap /    │ ──> │    Reloader      │ ──> │  Rolling Upgrade│
│    Secret       │     │   (watch API)    │     │   подов         │
│   (изменение)   │     │                  │     │                 │
└─────────────────┘     └──────────────────┘     └─────────────────┘
```

1. **Отслеживание (Watch):** Reloader следит за событиями обновления ресурсов через Kubernetes API (Application Programming Interface).
2. **Поиск зависимостей:** При изменении ресурса ищет workload-ы (рабочие нагрузки), использующие этот ресурс.
3. **Инициирование rollout:** Выполняет перезапуск для найденных объектов.

### Механизм обнаружения зависимостей

Reloader определяет зависимости по:

- **volumeMounts** — монтирование ConfigMap/Secret как тома (Volume).
- **envFrom** — загрузка переменных окружения (ENV) из ConfigMap/Secret.
- **env.valueFrom** — отдельные переменные из ConfigMap/Secret.

### Аннотации для конфигурации

**Автоматическое обнаружение (`auto`):**

```yaml
metadata:
  annotations:
    reloader.stakater.com/auto: "true"
```

Reloader автоматически следит за всеми ресурсами, используемыми в поде.

**Явное указание ресурсов:**

```yaml
metadata:
  annotations:
    # Следить за одним ConfigMap
    configmap.reloader.stakater.com/reload: "my-app-config"
    # Следить за Secret
    secret.reloader.stakater.com/reload: "my-app-tls"
```

### Стратегии обновления

| Стратегия | Описание |
| :--- | :--- |
| **`env-vars`** (Default) | Добавляет фиктивную переменную окружения для форсирования обновления. |
| **`annotations`** | Добавляет аннотацию `reloader.stakater.com/last-reloaded-from`. Рекомендуется для GitOps (ArgoCD), чтобы избежать ложных diff-ов. |

### Интеграция с CSI

Reloader поддерживает интеграцию с CSI (Container Storage Interface). При включении `reloader.enableCSIIntegration: true` контроллер может отслеживать изменения в секретах, доставляемых через Secrets Store CSI Driver, даже если они не представлены как объекты Secret в Kubernetes.

---

## Практические сценарии

### Сценарий 1: Выбор между Reloader и альтернативами

| Инструмент | Подход | Когда использовать |
| :--- | :--- | :--- |
| **Reloader** | Контроллер | Простота, динамическая среда, много сервисов. |
| **Checksum-аннотация** | Хеш в манифесте | Статический CI/CD (Continuous Integration / Continuous Deployment), Helm. |
| **ArgoCD** | GitOps | Полный контроль над состоянием через Git. |

Подробнее: [Обновление ConfigMap и его влияние на поды](../../Base/ConfigMap/update_and_rollout.md)

### Сценарий 2: Применение лучших практик

Для обеспечения стабильности кластера и предсказуемости обновлений при использовании Reloader рекомендуется следовать набору правил (явные аннотации, изоляция системных пространств имён, настройка лимитов ресурсов).

Подробное руководство: [Лучшие практики Reloader](./reloader_monitoring_and_best_practices.md#сценарий-4-применение-лучших-практик)

---

## Дополнительная информация

### Требования и ресурсы

Подробная информация о системных требованиях, лимитах ресурсов и совместимости версий находится в разделе:
[Установка и настройка: Требования и ресурсы](./reloader_installation.md#основные-концепции)

### Ограничения

- **subPath:** По умолчанию изменения в файлах, смонтированных через `subPath`, могут не подхватываться без явной аннотации.
- **Один контроллер на кластер:** В сверхбольших кластерах может потребоваться шардирование или увеличение ресурсов.
- **Rolling Update:** Reloader инициирует только плавную перезагрузку, он не может обновлять процессы внутри контейнера без его перезапуска.

### Ресурсы

- [GitHub: stakater/Reloader](https://github.com/stakater/Reloader)
- [Helm Chart на ArtifactHub](https://artifacthub.io/packages/helm/stakater/reloader)

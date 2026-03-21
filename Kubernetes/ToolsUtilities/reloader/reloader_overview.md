# Reloader — Обзор и основные концепции

## 1. Определения

**Reloader** — это контроллер для Kubernetes от Stakater, который отслеживает изменения в `ConfigMap` и `Secret` и автоматически выполняет rolling upgrade для связанных с ними `Deployment`, `StatefulSet` или `DaemonSet`.

**Проблема:** По умолчанию Kubernetes не перезапускает поды при изменении ConfigMap или Secret, что требует ручного вмешательства (`kubectl rollout restart`).

## 2. Основные концепции

### Принцип работы

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  ConfigMap /    │ ──> │    Reloader      │ ──> │  Rolling Upgrade│
│    Secret       │     │   (watch API)    │     │   подов         │
│   (изменение)   │     │                  │     │                 │
└─────────────────┘     └──────────────────┘     └─────────────────┘
```

1. **Отслеживание (Watch):** Reloader следит за событиями обновления ConfigMap и Secret через Kubernetes Watch API
2. **Поиск зависимостей:** При изменении ресурса ищет workload'ы, использующие этот ресурс
3. **Инициирование rollout:** Выполняет `rollout restart` для найденных workload'ов

### Механизм обнаружения зависимостей

Reloader определяет зависимости по:

- **volumeMounts** — монтирование ConfigMap/Secret как тома
- **envFrom** — загрузка переменных окружения из ConfigMap/Secret
- **env.valueFrom** — отдельные переменные из ConfigMap/Secret

### Аннотации для конфигурации

**Автоматическое обнаружение (`auto`):**

```yaml
metadata:
  annotations:
    reloader.stakater.com/auto: "true"
```

В этом режиме Reloader автоматически следит за всеми ConfigMap и Secret, используемыми в поде.

**Явное указание ресурсов:**

```yaml
metadata:
  annotations:
    # Следить за одним ConfigMap
    configmap.reloader.stakater.com/reload: "my-app-config"

    # Следить за несколькими ConfigMap (через запятую)
    configmap.reloader.stakater.com/reload: "config-1,config-2"

    # Следить за Secret
    secret.reloader.stakater.com/reload: "my-app-tls"

    # Следить за несколькими Secret
    secret.reloader.stakater.com/reload: "tls-secret,db-creds"
```

**Префикс для search-by-prefix (опционально):**

```yaml
metadata:
  annotations:
    reloader.stakater.com/search: "true"
```

### Режимы работы

| Режим | Описание |
| :--- | :--- |
| **Default** | Перезапуск подов при изменении ресурсов |
| **Strategy: Rename** | Переименование ресурса для принудительного обновления (enterprise) |
| **Ignore** | Игнорирование определённых namespace'ов или ресурсов |

## 3. Дополнительная информация

### Требования

| Компонент | Минимальная версия | Примечание |
| :--- | :--- | :--- |
| Kubernetes | 1.19+ | Проверено до 1.32 |
| Helm | 3.0+ | Для установки через Helm |

### Ресурсы контроллера

| Ресурс | Request | Limit |
| :--- | :--- | :--- |
| **CPU** | 100m | 300m |
| **Memory** | 128Mi | 256Mi |

### Сравнение с альтернативами

| Инструмент | Подход | Преимущества | Недостатки |
| :--- | :--- | :--- | :--- |
| **Reloader** | Аннотации | Простота, гибкость | Требует аннотаций |
| **Checksum-аннотация** | Хеш в манифесте | Работает без контроллера | Требует настройки CI/CD |
| **ArgoCD** | GitOps | Полный контроль | Сложнее в настройке |

**Подробнее:** [Обновление ConfigMap и его влияние на поды](../../Base/ConfigMap/update_and_rollout.md)

### Лучшие практики

1. **Игнорируйте системные namespace'ы** — `kube-system`, `kube-public`
2. **Используйте явные аннотации** — предсказуемее чем `auto: "true"`
3. **Настройте мониторинг** — отслеживайте логи Reloader
4. **Тестируйте в staging** — перед применением в production
5. **Задавайте ресурсы** — limits и requests для контроллера

### Ограничения

- **Не работает с `subPath` по умолчанию** — требуется явная аннотация
- **Только rolling restart** — не обновляет поды in-place
- **Один контроллер на кластер** — может быть bottleneck в больших кластерах

### Связанные документы

- **[Установка Reloader](./reloader_installation.md)** — установка через Helm и манифесты
- **[Сценарии использования](./reloader_usage_scenarios.md)** — практические примеры
- **[Мониторинг и отладка](./reloader_monitoring_and_best_practices.md)** — логи и диагностика
- **[ConfigMap](../../Base/ConfigMap/update_and_rollout.md)** — обновление ConfigMap и rollout
- **[Secrets](../../Security/application_secrets_management.md)** — управление секретами
- **[Deployment](./index.md)** — rolling update стратегия
- **[Helm](../Helm/helm_overview.md)** — установка через Helm

### Репозиторий и документация

- [GitHub: stakater/Reloader](https://github.com/stakater/Reloader)
- [Документация Stakater](https://github.com/stakater/Reloader#readme)
- [Helm Chart](https://github.com/stakater/stakater-charts/tree/master/charts/reloader)

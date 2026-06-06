# Практические сценарии Helm-чартов

Рабочие процессы создания, валидации и развёртывания Helm-чартов для production-окружений.

---

## Определения

| Термин | Описание |
|--------|----------|
| **helm create** | Команда генерации стандартной структуры чарта. См. [Структура Helm-чарта](./helm_chart_structure.md) |
| **helm lint** | Валидация синтаксиса и структуры чарта |
| **helm template** | Локальный рендер шаблонов без кластера |
| **helm dependency** | Управление зависимостями чарта. См. [Зависимости и Library Charts](./helm_dependencies_and_library_charts.md) |

---

## Основные концепции

### Команды валидации

```bash
# Проверка синтаксиса чарта
helm lint .

# Локальный рендер шаблонов без кластера
helm template myrelease .

# Рендер с values-файлом
helm template myrelease . -f values-production.yaml

# Проверка с подключением к кластеру (dry-run)
helm install --dry-run --debug myrelease .
```

**Команда `helm template`:**

Рендерит шаблоны на локальной машине без подключения к кластеру. Полезна для:

- Визуальной проверки итоговых манифестов
- Отладки шаблонов перед коммитом
- Генерации манифестов для применения через `kubectl apply -f`

**Флаг `--debug` при dry-run:**

Позволяет проверять шаблоны с незакоммиченными изменениями без риска поломать развёртывание:

```bash
# Рендер с отладочной информацией
helm install --dry-run --debug myrelease .
```

### Команды работы с зависимостями

```bash
# Обновление зависимостей и создание Chart.lock
helm dependency update

# Построение зависимостей из Chart.lock
helm dependency build
```

---

## Практические сценарии

### Создание нового чарта

```bash
helm create mychart
cd mychart
```

Команда генерирует чарт с примерами шаблонов и `_helpers.tpl`. См. [Структура Helm-чарта](./helm_chart_structure.md) для деталей организации файлов.

### Структура production-чарта

```
production-chart/
├── Chart.yaml              # Метаданные
├── Chart.lock              # Зафиксированные версии зависимостей
├── values.yaml             # Базовые значения
├── values-production.yaml  # Переопределения для prod
├── values-staging.yaml     # Переопределения для staging
├── templates/
│   ├── _helpers.tpl        # Вспомогательные функции
│   ├── deployment.yaml
│   ├── service.yaml
│   ├── ingress.yaml
│   ├── configmap.yaml
│   ├── secrets.yaml
│   ├── hpa.yaml            # HorizontalPodAutoscaler
│   ├── pdb.yaml            # PodDisruptionBudget
│   └── tests/              # Тесты для helm test
│       └── test-connection.yaml
└── charts/                 # Загруженные зависимости (после helm dependency update)
    └── postgresql-12.1.0.tgz
```

### Многоокружная стратегия через values-файлы

Для управления конфигурациями в разных окружениях (dev, staging, production) используется несколько `values` файлов.

**Подход:**

1. **`values.yaml` (файл по умолчанию):**
    - Содержит "безопасные" и минимальные значения. Многие функции по умолчанию отключены (`ingress.enabled: false`, `autoscaling.enabled: false`).
    - Служит основной документацией для чарта. В нем полезно оставлять закомментированные блоки, демонстрирующие структуру сложных параметров (например, `resources` или `affinity`), чтобы пользователи знали, что они могут сконфигурировать.

    ```yaml
    # values.yaml
    replicaCount: 1

    ingress:
      enabled: false

    # Ресурсы по умолчанию не заданы, но показана структура для пользователя
    # resources:
    #   limits:
    #     cpu: 100m
    #     memory: 128Mi
    #   requests:
    #     cpu: 100m
    #     memory: 128Mi
    ```

2. **`values-<окружение>.yaml` (файл переопределения):**
    - Содержит только те значения, которые отличаются от `values.yaml` и специфичны для конкретного окружения.

    ```yaml
    # values-production.yaml
    replicaCount: 3

    ingress:
      enabled: true
      hosts:
        - host: myapp.prod.com
      tls:
       - secretName: myapp-prod-tls
         hosts:
           - myapp.prod.com

    resources:
      limits:
        cpu: 2000m
        memory: 4Gi
      requests:
        cpu: 1000m
        memory: 2Gi
    ```

**Применение:**

При установке или обновлении чарта флаг `-f` (или `--values`) можно указывать несколько раз. Файлы применяются последовательно, и каждое последующее значение перезаписывает предыдущее.

```bash
# Сначала загружается values.yaml, затем его значения перезаписываются из values-dev.yaml
helm install app ./chart -f values.yaml -f values-dev.yaml -n dev

# Для production
helm upgrade app ./chart -f values.yaml -f values-production.yaml -n prod --atomic
```

---

## См. также

- [Зависимости и Library Charts в Helm](./helm_dependencies_and_library_charts.md)
- [Основные команды и рабочий процесс Helm](./helm_commands_and_workflow.md)

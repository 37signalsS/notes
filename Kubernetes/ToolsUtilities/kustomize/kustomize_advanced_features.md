# Kustomize — Продвинутые возможности

## 1. Определения

**Генераторы (Generators)** — механизмы Kustomize для динамического создания ресурсов (ConfigMap, Secret) из внешних источников (файлы, переменные окружения, литералы) с автоматическим управлением жизненным циклом (хеширование имен).

**Компоненты (Components)** — высокоуровневый механизм для создания переиспользуемых фрагментов конфигурации, которые могут содержать ресурсы и патчи. В отличие от `base`, компоненты позволяют подмешивать логику в разные оверлеи без создания жестких иерархий.

**Замены (Replacements)** — современный механизм (пришел на смену `vars`) для копирования значений из одного поля ресурса в другое. Позволяет динамически обновлять переменные окружения, аргументы командной строки и другие поля на основе данных из других ресурсов.

**Интеграция с Helm** — встроенная возможность Kustomize рендерить Helm-чарты без использования внешних скриптов, позволяя накладывать Kustomize-патчи поверх сгенерированных Helm-манифестов.

## 2. Основные концепции

### Хеширование имен (Name Hashing)

По умолчанию Kustomize добавляет хеш содержимого к именам ресурсов, созданных через генераторы (например, `app-config-f7h8z9`).
- **Зачем:** Это гарантирует обновление Подов (Rolling Update). Когда данные в ConfigMap меняются, хеш меняется → имя ресурса меняется → Deployment видит изменение в `volumes` или `envFrom` → инициируется перезапуск Подов.
- **Шаблон:** Это реализация паттерна **Immutable ConfigMap/Secret**.

### Поведение генераторов (Behavior)

При наследовании (base → overlay) можно управлять тем, как новый генератор взаимодействует с базовым:
- `create`: создает новый независимый ресурс (по умолчанию).
- `merge`: объединяет данные из overlay с данными из base.
- `replace`: полностью заменяет генератор из базы, игнорируя базовые данные.

### Компоненты против Баз (Components vs Base)

| Характеристика | Base | Components |
| :--- | :--- | :--- |
| **Использование** | Основа проекта | Опциональные фичи |
| **Связь** | Иерархическая (вертикальная) | Композиционная (горизонтальная) |
| **Гибкость** | Низкая (одна база на оверлей) | Высокая (несколько компонентов на оверлей) |
| **Пример** | Основной Deployment | Включение Prometheus, Sidecar-логирование |

### Замены против Переменных (Replacements vs Vars)

> **Важно:** Поле `vars` официально признано устаревшим (deprecated) в Kustomize v5 и будет удалено. Рекомендуется использовать `replacements`.

`Replacements` обладают более строгой типизацией и позволяют точно указывать источник (source) и цели (targets) для копирования данных, не полагаясь на глобальный поиск подстрок.

## 3. Практические сценарии

### 3.1. Генерация из разных источников

```yaml
# kustomization.yaml
configMapGenerator:
  - name: app-env
    envs:
      - configs.env        # Загрузка всех пар KEY=VALUE из файла
  - name: app-config
    files:
      - config.json        # Файл целиком в секцию data
  - name: app-literals
    literals:
      - LOG_LEVEL=debug    # Прямое указание значений
```

### 3.2. Генерация секретов (Opaque и TLS)

```yaml
# kustomization.yaml
secretGenerator:
  - name: db-secret
    literals:
      - password=S3cr3t
  - name: site-tls
    type: kubernetes.io/tls
    files:
      - tls.crt
      - tls.key
```

### 3.3. Настройка генераторов (generatorOptions)

Позволяет добавить метаданные ко всем сгенерированным ресурсам или отключить хеширование.

```yaml
# kustomization.yaml
generatorOptions:
  disableNameSuffixHash: false
  labels:
    type: generated
  annotations:
    managed-by: kustomize

configMapGenerator:
  - name: static-config
    behavior: create
    literals:
      - VERSION=1.0
```

### 3.4. Использование Компонентов (Components)

Полезно для включения функционала «по требованию».

```yaml
# components/monitoring/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1alpha1 # Для компонентов часто используется этот API
kind: Component
patches:
  - target:
      kind: Deployment
    patch: |-
      - op: add
        path: /spec/template/metadata/annotations/prometheus.io~1scrape
        value: "true"

# overlays/production/kustomization.yaml
resources:
  - ../../base
components:
  - ../../components/monitoring
```

### 3.5. Механизм Замен (Replacements)

Пример копирования хешированного имени ConfigMap в переменную окружения другого ресурса.

```yaml
# kustomization.yaml
replacements:
  - source:
      kind: ConfigMap
      name: app-config
      fieldPath: metadata.name
    targets:
      - select:
          kind: Deployment
          name: api-server
        fieldPaths:
          - spec.template.spec.containers.[name=api].env.[name=CONFIG_NAME].value
```

### 3.6. Интеграция с Helm (Декларативная)

Kustomize может скачивать и рендерить чарты в процессе сборки.

```yaml
# kustomization.yaml
helmCharts:
  - name: redis
    repo: https://charts.bitnami.com/bitnami
    version: 17.x.x
    releaseName: my-redis
    namespace: database
    includeCRDs: true
    valuesFile: values.yaml
```

**Запуск:** `kustomize build --enable-helm .` (требует установленного `helm` в системе).

### 3.7. Валидация результата (CI/CD)

Всегда проверяйте итоговый манифест перед деплоем.

```bash
# 1. Проверка синтаксиса Kustomize
kustomize build overlays/production/ > result.yaml

# 2. Валидация против схем Kubernetes через kubeconform
kustomize build overlays/production/ | kubeconform -strict -summary -

# 3. Dry-run проверка через API сервер (если есть доступ)
kubectl apply -k overlays/production/ --dry-run=server
```

## 4. Дополнительная информация

### Ограничения и особенности

1. **Порядок применения:** Kustomize применяет генераторы раньше, чем патчи. Это позволяет патчить сгенерированные ресурсы.
2. **Безопасность Secret:** Помните, что `secretGenerator` хранит значения в YAML в открытом виде (если не используются плагины типа `sops`). Не коммитьте реальные секреты в Git.
3. **Производительность Helm:** Использование `helmCharts` замедляет сборку, так как требует сетевых запросов и запуска бинарного файла Helm.

### Связь с другими разделами

- [Обзор и основные концепции](./kustomize_overview.md) — базовые определения и установка
- [Структура и синтаксис](./kustomize_structure_and_syntax.md) — структура kustomization.yaml
- [Наложения и патчи](./kustomize_overlays_and_patches.md) — механизм работы патчей
- [Валидация манифестов (kubeconform)](../kubeconform_overview.md) — подробнее о проверке схем

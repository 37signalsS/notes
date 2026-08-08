# Kustomize — Продвинутые возможности

В данном разделе рассматриваются механизмы Kustomize, позволяющие управлять сложными конфигурациями, интегрировать внешние инструменты (Helm) и расширять возможности инструмента через плагины и кастомные схемы.

## 1. Определения

**Генераторы (Generators)** — механизмы Kustomize для динамического создания ресурсов (ConfigMap, Secret) из внешних источников (файлы, переменные окружения, литералы) с автоматическим управлением жизненным циклом через хеширование имен.

**Компоненты (Components)** — высокоуровневый механизм для создания переиспользуемых фрагментов конфигурации, которые могут содержать ресурсы и патчи. В отличие от `base`, компоненты позволяют «подмешивать» логику (например, мониторинг или прокси) в разные оверлеи без создания жестких иерархий.

**Замены (Replacements)** — механизм (пришел на смену устаревшим `vars`) для типизированного копирования значений из одного поля ресурса в другое. Позволяет динамически обновлять переменные окружения, аргументы командной строки и другие поля на основе данных из других ресурсов.

**Плагины (Plugins)** — расширения для Kustomize, позволяющие генерировать или трансформировать ресурсы с помощью внешних исполняемых файлов (Exec plugins) или модулей Go.

**OpenAPI Integration** — использование пользовательских схем OpenAPI для обучения Kustomize правилам обработки Custom Resources (CRD), например, для корректного применения патчей или добавления меток.

## 2. Основные концепции

### Хеширование имен (Name Hashing)

По умолчанию Kustomize добавляет хеш содержимого к именам ресурсов, созданных через генераторы (например, `app-config-f7h8z9`).
- **Зачем:** Это гарантирует обновление Подов (Rolling Update). Когда данные в ConfigMap меняются, хеш меняется → имя ресурса меняется → Deployment видит изменение в ссылке → инициируется перезапуск Подов.
- **Паттерн:** Реализация концепции **Immutable Infrastructure**.

### Поведение генераторов (Behavior)

При наследовании (base → overlay) можно управлять тем, как новый генератор взаимодействует с базовым:
- `create`: создает новый независимый ресурс (по умолчанию).
- `merge`: объединяет данные из overlay с данными из base.
- `replace`: полностью заменяет генератор из базы.

### Композиция через Components

| Характеристика | Base | Components |
| :--- | :--- | :--- |
| **Использование** | Фундамент проекта | Опциональные возможности |
| **Связь** | Вертикальная (иерархия) | Горизонтальная (подмешивание) |
| **Гибкость** | Одна база на оверлей | Неограниченное количество компонентов |

### Использование OpenAPI схем

Kustomize «из коробки» знает, как работать со стандартными ресурсами Kubernetes. Для корректной обработки **Custom Resources** (например, чтобы `commonLabels` добавлялись в правильные поля CRD) требуется предоставить Kustomize схему OpenAPI. Это предотвращает ошибки при слиянии патчей и обеспечивает безопасность типов.

## 3. Практические сценарии

### 3.1. Продвинутая генерация ресурсов

```yaml
# kustomization.yaml
generatorOptions:
  disableNameSuffixHash: false # Включение/выключение хеша для всех генераторов
  labels:
    type: generated

configMapGenerator:
  - name: app-config
    behavior: merge # Объединение с базовым конфигом
    files:
      - settings.json
    literals:
      - LOG_LEVEL=info
```

### 3.2. Работа с Replacements (взамен Vars)

Копирование хешированного имени ConfigMap в аргументы контейнера.

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
          name: web-app
        fieldPaths:
          - spec.template.spec.containers.[name=main].args.0
        options:
          delimiter: "="
          index: 1 # Замена только части значения после разделителя
```

### 3.3. Встроенные трансформаторы (Built-in Transformers)

Массовое обновление образов и меток без написания патчей.

```yaml
# kustomization.yaml
images:
  - name: my-api
    newName: my-registry.com/api
    newTag: v1.2.3

commonLabels:
  app.kubernetes.io/part-of: billing-system

commonAnnotations:
  team: backend-ops
```

### 3.4. Интеграция с Helm

Декларативное описание Helm-чарта как ресурса Kustomize.

```yaml
# kustomization.yaml
helmCharts:
  - name: postgresql
    repo: https://charts.bitnami.com/bitnami
    version: 12.x.x
    releaseName: db
    valuesFile: values-prod.yaml
```
# → Команда сборки: kustomize build --enable-helm .

### 3.5. Использование OpenAPI для CRD

Помогает Kustomize понять структуру Custom Resource для правильного наложения меток.

```yaml
# kustomization.yaml
openapi:
  path: schema.json # Схема, содержащая определения ваших CRD
```

### 3.6. Плагины (Exec Plugins)

Пример использования внешнего генератора (например, для получения секретов из Vault).

```yaml
# vault-secret-gen.yaml
apiVersion: my-plugins/v1
kind: VaultSecretGenerator
metadata:
  name: db-creds
path: secret/data/db

# kustomization.yaml
generators:
  - vault-secret-gen.yaml
```
# → Требует настройки KUSTOMIZE_PLUGIN_HOME и --enable-alpha-plugins

## 4. Дополнительная информация

### Ограничения и особенности

1. **Порядок обработки:** Kustomize выполняет операции в строгом порядке: `resources` → `generators` → `transformers` → `validators`. Патчи применяются в фазе трансформации.
2. **Безопасность плагинов:** Использование сторонних плагинов требует осторожности, так как они запускают произвольный код в системе сборки.
3. **Версионность:** Replacements доступны только в Kustomize v4.0.0+. Использование `vars` в новых проектах запрещено (deprecated).

### См. также
- **[Обзор и основные концепции](./kustomize_overview.md)** — базовые определения и установка.
- **[Наложения и патчи](./kustomize_overlays_and_patches.md)** — механизм работы Strategic Merge и JSON патчей.
- **[Интеграция в CD конвейеры](./kustomize_cd_integration.md)** — использование в Jenkins и GitOps.

### Внешние ресурсы
- [Kustomize Built-in Plugins](https://kubectl.docs.kubernetes.io/guides/extending_kustomize/builtins/)
- [Kustomize Replacements Guide](https://kubectl.docs.kubernetes.io/references/kustomize/kustomization/replacements/)

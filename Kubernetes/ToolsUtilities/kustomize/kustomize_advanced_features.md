# Kustomize — Продвинутые возможности

## 1. Определения

**ConfigMap/Secret Generator** — механизм Kustomize для автоматического создания ConfigMap и Secret из файлов или литералов с автоматическим добавлением хеша содержимого к имени ресурса (immutable pattern).

**Behavior** — директива, управляющая поведением генератора при наследовании: `create` (по умолчанию), `merge` (объединение с базовым), `replace` (полная замена).

**Helm-Kustomize Hybrid** — подход генерации базовых манифестов через `helm template` с последующим управлением окружениями через Kustomize overlays.

## 2. Основные концепции

### Hash-суффиксы для ConfigMap и Secret

Kustomize автоматически добавляет хеш содержимого к имени ресурса:

```yaml
# kustomization.yaml
configMapGenerator:
  - name: app-config
    literals:
      - DATABASE_URL=postgres://localhost:5432/db
```

Результат: `app-config-<hash>`. Это гарантирует обновление Pod при изменении данных, так как изменение имени ConfigMap вызывает рестарт контейнеров (шаблон Immutable ConfigMap).

### Поведение (Behavior) при наследовании

| Значение | Описание |
| :--- | :--- |
| **create** | Создание нового ресурса (по умолчанию) |
| **merge** | Объединение с генератором из базового слоя (base) |
| **replace** | Полная замена генератора из базового слоя |

### Ограничения генераторов

- **Отсутствие условной логики** — нельзя генерировать разные ресурсы для разных окружений в рамках одного файла.
- **Отсутствие циклов** — каждая запись в манифесте создает ровно один ресурс.
- **Хеширование** — по умолчанию включено для всех генерируемых ресурсов. Для использования статических имен необходимо установить `generatorOptions.disableNameSuffixHash: true`.

## 3. Практические сценарии

### 3.1. Генерация ConfigMap из литералов

```yaml
# base/kustomization.yaml
configMapGenerator:
  - name: app-config
    literals:
      - DATABASE_URL=postgres://localhost:5432/db
      - CACHE_TTL=3600
```

### 3.2. Генерация ConfigMap из файлов

```yaml
# base/kustomization.yaml
configMapGenerator:
  - name: nginx-config
    files:
      - nginx.conf
```

Файл `nginx.conf` должен находиться в той же директории, что и `kustomization.yaml`.

### 3.3. Генерация Secret из литералов

```yaml
# overlays/production/kustomization.yaml
secretGenerator:
  - name: db-secret
    literals:
      - username=admin
      - password=S3cr3t
    type: Opaque  # Тип по умолчанию
```

### 3.4. Генерация TLS Secret из файлов

```yaml
# overlays/production/kustomization.yaml
secretGenerator:
  - name: tls-secret
    files:
      - tls.crt
      - tls.key
    type: kubernetes.io/tls
```

Файлы сертификата и ключа должны находиться в директории overlay.

### 3.5. Использование Behavior: merge

```yaml
# overlays/production/kustomization.yaml
configMapGenerator:
  - name: app-config
    behavior: merge  # Объединение с базовой конфигурацией
    literals:
      - LOG_LEVEL=info
      - ENV=production
```

Ключи из базового слоя сохраняются, новые добавляются. При совпадении имен ключей приоритет имеет значение из overlay.

### 3.6. Использование Behavior: replace

```yaml
# overlays/production/kustomization.yaml
configMapGenerator:
  - name: app-config
    behavior: replace  # Игнорирование базовой конфигурации
    literals:
      - DATABASE_URL=postgres://prod-db:5432/prod
      - CACHE_TTL=7200
```

### 3.7. Отключение хеш-суффикса

```yaml
# kustomization.yaml
generatorOptions:
  disableNameSuffixHash: true

configMapGenerator:
  - name: static-config
    literals:
      - KEY=value
```

Результат выполнения `kustomize build`: ресурс будет иметь имя `static-config` без суффикса.

### 3.8. Интеграция Helm и Kustomize

Существует два основных способа совместного использования инструментов.

#### Гибридный подход (ручной)

Генерация манифестов через Helm с последующим использованием их как базовых ресурсов:

```bash
# 1. Генерация манифестов
helm template my-chart ./chart > base/manifests.yaml

# 2. Использование в Kustomize (base/kustomization.yaml)
resources:
  - manifests.yaml
```

#### Нативная интеграция (helmCharts)

Kustomize (4.1.0+) поддерживает декларативное описание чартов.

```yaml
# kustomization.yaml
helmCharts:
  - name: podinfo
    repo: https://stefanprodan.github.io/podinfo
    version: 6.3.5
    releaseName: my-podinfo
    namespace: my-namespace
    valuesFile: values.yaml
```

Для сборки необходимо использовать флаг:
```bash
kustomize build --enable-helm
# → Вывод: манифесты Helm-чарта с примененными патчами Kustomize
```

### 3.9. Валидация результата

Рекомендуется проверять корректность манифестов через [kubeconform](../kubeconform/kubeconform_overview.md):

```bash
# Валидация с выводом сводки
kubectl kustomize overlays/production | kubeconform -summary -
# → Вывод: Summary: 5 resources found, 0 errors

# Строгая валидация
kubectl kustomize overlays/production | kubeconform -strict -
```

## 4. Дополнительная информация

### Связь с другими разделами

- [Обзор и основные концепции](./kustomize_overview.md) — базовые определения
- [Структура и синтаксис](./kustomize_structure_and_syntax.md) — структура проекта
- [Наложения и патчи](./kustomize_overlays_and_patches.md) — типы патчей и примеры

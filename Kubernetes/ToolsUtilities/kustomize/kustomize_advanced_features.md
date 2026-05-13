# Kustomize — Advanced Features

## 1. Definitions

**ConfigMap/Secret Generator** — механизм Kustomize для автоматического создания ConfigMap и Secret из файлов или литералов с автоматическим добавлением хеша содержимого к имени ресурса (immutable pattern).

**Behavior** — директива, управляющая поведением генератора при наследовании: `create` (по умолчанию), `merge` (объединение с базовым), `replace` (полная замена).

**Helm-Kustomize Hybrid** — подход генерации базовых манифестов через `helm template` с последующим управлением окружениями через Kustomize overlays.

## 2. Basic Concepts

### Hash-суффиксы для ConfigMap/Secret

Kustomize автоматически добавляет хеш содержимого к имени ресурса:

```yaml
# kustomization.yaml
configMapGenerator:
  - name: app-config
    literals:
      - DATABASE_URL=postgres://localhost:5432/db
```

Результат: `app-config-<hash>` — это гарантирует обновление Pods при изменении данных (immutable ConfigMap pattern).

### Behavior при наследовании

| Значение | Поведение |
| :--- | :--- |
| `create` | Создание нового ресурса (default) |
| `merge` | Объединение с базовым генератором |
| `replace` | Полная замена базового генератора |

### Ограничения генераторов

- **Нет условной логики** — нельзя генерировать разные ConfigMap для разных окружений в одном файле
- **Нет циклов** — каждая запись создаёт один ресурс
- **Хеширование нельзя отключить** — для статических имён используйте `generatorOptions.disableNameSuffixHash: true`

## 3. Practical Scenarios

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

Файл `nginx.conf` должен существовать в той же директории, что и `kustomization.yaml`.

### 3.3. Генерация Secret из литералов

```yaml
# overlays/production/kustomization.yaml
secretGenerator:
  - name: db-secret
    literals:
      - username=admin
      - password=S3cr3t
    type: Opaque  # default
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

Файлы `tls.crt` и `tls.key` должны существовать в директории overlay.

### 3.5. Behavior: merge для наследования

```yaml
# overlays/production/kustomization.yaml
configMapGenerator:
  - name: app-config
    behavior: merge  # объединение с base
    literals:
      - LOG_LEVEL=info
      - ENV=production
```

Базовые ключи из `base/` сохраняются, новые — добавляются. При конфликте побеждает значение из overlay.

### 3.6. Behavior: replace для полной замены

```yaml
# overlays/production/kustomization.yaml
configMapGenerator:
  - name: app-config
    behavior: replace  # игнорирование base
    literals:
      - DATABASE_URL=postgres://prod-db:5432/prod
      - CACHE_TTL=7200
```

### 3.7. Отключение hash-суффикса

```yaml
# kustomization.yaml
generatorOptions:
  disableNameSuffixHash: true

configMapGenerator:
  - name: static-config
    literals:
      - KEY=value
```

Результат: `static-config` (без хеша).

### 3.8. Интеграция Helm + Kustomize

Существует два основных способа совместного использования Helm и Kustomize.

#### Вариант А: Гибридный подход (ручной)

Генерация базовых манифестов из Helm с последующим использованием их в качестве `resources` в Kustomize:

```bash
# Шаг 1: Генерация манифестов
helm template my-chart ./chart > base/manifests.yaml

# Шаг 2: Использование в Kustomize
# base/kustomization.yaml
resources:
  - manifests.yaml
```

#### Вариант Б: Нативная интеграция (helmCharts)

Kustomize (начиная с v4.1.0) поддерживает декларативное описание Helm-чартов непосредственно в `kustomization.yaml`. Это позволяет Kustomize автоматически скачивать и рендерить чарты при сборке.

```yaml
# kustomization.yaml
helmCharts:
  - name: podinfo
    repo: https://stefanprodan.github.io/podinfo
    version: 6.3.5
    releaseName: my-podinfo
    namespace: my-namespace
    valuesFile: values.yaml  # внешние значения
    # valuesInline:          # или встроенные значения
    #   replicaCount: 2
```

**Преимущества нативной интеграции:**

- **Автоматизация**: Kustomize сам управляет скачиванием и рендерингом (требуется установленный бинарник `helm`).
- **Патчинг**: Можно накладывать Kustomize патчи поверх ресурсов, сгенерированных Helm, даже если автор чарта не предусмотрел нужных параметров в `values.yaml`.
- **Чистота**: Нет необходимости хранить огромные сгенерированные YAML-файлы в Git.

**Особенности использования:**

- Требуется запуск сборки с флагом `--enable-helm`: `kustomize build --enable-helm`.
- Для `kubectl` эта функция может потребовать дополнительных настроек или использования отдельного CLI `kustomize`.

### 3.9. Валидация результата kustomize

Перед применением в кластер рекомендуется валидировать манифесты через [kubeconform](../kubeconform/index.md):

```bash
# Валидация с выводом сводки
kubectl kustomize overlays/production | kubeconform -summary -

# Строгая валидация (отклонение неизвестных полей)
kubectl kustomize overlays/production | kubeconform -strict -
```

Интеграция в CI/CD: валидация должна выполняться автоматически при каждом изменении kustomization файлов.

## 4. Additional Information

### Связь с базовыми концепциями

- [Overview and Core Concepts](./kustomize_overview.md) — базовые определения
- [Структура и синтаксис](./kustomize_structure_and_syntax.md) — структура проекта
- [Наложения и патчи](./kustomize_overlays_and_patches.md) — типы патчей

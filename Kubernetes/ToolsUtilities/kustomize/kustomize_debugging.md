# Kustomize — Отладка и диагностика

## 1. Определения

**Debugging Kustomize** — процесс локализации и устранения ошибок, возникающих на этапах сборки (`kustomize build`), наложения патчей и применения манифестов в кластер. В отличие от ошибок Kubernetes API, ошибки Kustomize возникают на стороне клиента и не оставляют следов в логах кластера, что делает их диагностику нетривиальной задачей.

**Молчаливый failure (Silent failure)** — ситуация, при которой патч применяется без ошибки, но не модифицирует целевой ресурс. Наиболее частая причина инцидентов в production, связанных с Kustomize: оператор уверен, что изменение применено, но кластер продолжает работать со старой конфигурацией.

**Build-time vs Runtime errors** — ошибки Kustomize делятся на两类: build-time (парсинг, валидация схем, несуществующие файлы) и runtime (конфликты патчей, невалидные JSON Pointer, несовместимость с Kubernetes API). Build-time ловятся до `kubectl apply`, runtime — только после.

## 2. Основные концепции

### Чеклист диагностики сломанного билда

Когда `kustomize build` падает или работает некорректно, выполняйте шаги последовательно:

```text
Шаг 1: Воспроизвести ошибку
    ↓
Шаг 2: Проверить kustomization.yaml на синтаксис
    ↓
Шаг 3: Определить, какой компонент вызывает ошибку
    ↓
Шаг 4: Изолировать проблему (бинарный поиск)
    ↓
Шаг 5: Исправить и проверить
```

### Классификация ошибок

| Категория | Примеры | Критичность |
| :--- | :--- | :--- |
| **Синтаксические** | Невалидный YAML, опечатка в ключе | Блокирующая |
| **Ссылки на ресурсы** | Несуществующий файл в `resources`, неверный путь | Блокирующая |
| **Конфликты патчей** | Два патча изменяют одно поле, невалидный JSON Pointer | Молчаливая или блокирующая |
| **Схемы и типы** | Невалидное значение поля, неизвестный kind CRD | Блокирующая |
| **Сборка и окружение** | Нет `git` для удаленных баз, нет прав на чтение файлов | Блокирующая |

### Инструменты отладки

| Инструмент | Назначение | Когда использовать |
| :--- | :--- | :--- |
| `kustomize build . --enable-alpha-plugins --v=4` | Подробный лог сборки | Первый шаг при любой ошибке |
| `kustomize build . 2>&1 \| head -50` | Вывод ошибки с контекстом | Быстрый просмотр |
| `kubectl kustomize .` | Проверка через встроенный kubectl | Когда kustomize CLI недоступен |
| `kustomize build . --dry-run=client 2>&1` | Валидация без API-вызовов | Проверка синтаксиса |
| `kubectl diff -k overlays/production/` | Сравнение с текущим состоянием кластера | Поиск drift перед apply |

## 3. Практические сценарии

### 3.1. Базовая диагностика: `kustomize build` падает

**Симптом:**
```bash
$ kustomize build overlays/production/
Error: accumulating resources: accumulation err='accumulating resources from '../base':
  ...
  error calculating remote url for root: ...
```

**Чеклист:**
```bash
# 1. Проверить синтаксис kustomization.yaml
kustomize build overlays/production/ --dry-run=client 2>&1

# 2. Включить verbose для деталей
kustomize build overlays/production/ --v=4 2>&1 | head -100

# 3. Проверить, что все файлы в resources существуют
ls -la overlays/production/
ls -la base/

# 4. Проверить удаленные ресурсы (если используются Git URL)
git ls-remote https://github.com/org/repo//path?ref=v1.0

# 5. Проверить, что kustomization.yaml валиден как YAML
python3 -c "import yaml; yaml.safe_load(open('overlays/production/kustomization.yaml'))"
```

### 3.2. Молчаливый патч: патч не применяется без ошибки

**Симптом:** `kustomize build` завершается успешно, но целевой ресурс не изменен.

**Причины (по частоте):**
1. `target.name` или `target.kind` не совпадают с ресурсом
2. Патч ссылается на несуществующее поле
3. Namespace/ prefix Applied до патча (порядок трансформаций)

**Диагностика:**
```bash
# 1. Вывести сгенерированный манифест и найти целевой ресурс
kustomize build overlays/production/ | grep -A 20 "kind: Deployment"

# 2. Проверить, что target selectors корректны
# В kustomization.yaml:
patches:
  - target:
      kind: Deployment    # ← Точное совпадение с kind ресурса
      name: web-server    # ← Точное совпадение с metadata.name
    patch: |-
      - op: replace
        path: /spec/replicas
        value: 5

# 3. Проверить, что имя ресурса НЕ было изменено namePrefix/nameSuffix
# namePrefix применяется ДО патчей, поэтому target.name должно быть
# имя БЕЗ префикса (если патч применяется до трансформации)
```

**Правило:** `target.name` в патче должно совпадать с именем ресурса в **базе** (до применения `namePrefix`/`nameSuffix`), потому что Kustomize сначала читает ресурсы, затем применяет патчи, и только потом — трансформации метаданных.

### 3.3. Конфликт двух патчей на одно поле

**Симптом:**
```bash
$ kustomize build .
Error: addOps.patch ... for field "replicas" already set
```

**Решение:** Патчи применяются строго в порядке перечисления. Если два патча изменяют одно поле, оставьте только один:

```yaml
# НЕПРАВИЛЬНО:
patches:
  - target:
      kind: Deployment
      name: web-server
    patch: |-
      - op: replace
        path: /spec/replicas
        value: 3
  - target:
      kind: Deployment
      name: web-server
    patch: |-
      - op: replace
        path: /spec/replicas  # ← Конфликт!
        value: 5

# ПРАВИЛЬНО: оставить только итоговое значение
patches:
  - target:
      kind: Deployment
      name: web-server
    patch: |-
      - op: replace
        path: /spec/replicas
        value: 5
```

### 3.4. Ошибки JSON Pointer (RFC 6902)

**Частые ошибки:**
```yaml
# ОШИБКА: экранирование / в имени аннотации
patch: |-
  - op: add
    path: /metadata/annotations/app.kubernetes.io/name  # ← Неверно!
    value: myapp

# ПРАВИЛЬНО: использовать ~1 для экранирования /
patch: |-
  - op: add
    path: /metadata/annotations/app.kubernetes.io~1name  # ← Верно
    value: myapp

# ОШИБКА: индекс массива сдвинут после другого патча
patch: |-
  - op: replace
    path: /spec/template/spec/containers/0/resources/limits/cpu  # ← Индекс 0
    value: "500m"

# ПРАВИЛЬНО: использовать name-селектор вместо индекса
patch: |-
  - op: replace
    path: /spec/template/spec/containers/[name=web-server]/resources/limits/cpu
    value: "500m"
```

### 3.5. Порядок трансформаций: namespace/namePrefix Applied до патчей

**Ключевой момент:** Kustomize применяет операции в строго определённом порядке:
1. `resources` — чтение файлов
2. `generators` — создание ConfigMap/Secret
3. `namespace`, `namePrefix`, `nameSuffix`, `commonLabels` — трансформации метаданных
4. `patches`, `images`, `replacements` — контентные трансформации

**Это означает:** если `namePrefix: prod-` добавляет префикс ко всем ресурсам, то патч с `target.name: web-server` **не найдёт** ресурс `prod-web-server`. Патч должен ссылаться на имя **до** префикса.

```yaml
# kustomization.yaml overlay:
namePrefix: prod-
patches:
  - target:
      kind: Deployment
      name: web-server  # ← Имя БЕЗ префикса!
    patch: |-
      - op: replace
        path: /spec/replicas
        value: 5
```

### 3.6. Хеш ConfigMap не меняется при изменении

**Симптом:** Pod не перезапускается после изменения ConfigMap.

**Диагностика:**
```bash
# 1. Проверить, что хеш изменился
kustomize build overlays/production/ | grep "app-config-"
# → app-config-7d3k8f   (старый)
# → app-config-9x2m1n   (новый) — если хеш изменился, все ОК

# 2. Проверить generatorOptions
kustomize build overlays/production/ | grep -A 5 "generatorOptions"
# → disableNameSuffixHash: true  ← ОПАСНО! Хеш отключен

# 3. Проверить, что используется configMapGenerator, а не статический configmap.yaml
# Статический configmap.yaml НЕ получает хеш автоматически
```

**Решение:** Убедитесь, что `disableNameSuffixHash: false` (или отсутствует) и используется `configMapGenerator`.

### 3.7. Циклическая зависимость base ↔ overlay

**Симптом:**
```bash
Error: accumulating resources: found cycle between directories
```

**Диагностика:**
```bash
# 1. Проверить ссылки в resources
grep -r "resources:" --include="kustomization.yaml" .

# 2. Построить граф зависимостей
# base/kustomization.yaml ссылается на overlays/X?
# overlays/X/kustomization.yaml ссылается на base?
# Если да — это цикл!

# 3. Использовать kustomize cfg lint для автоматического поиска
kustomize cfg lint .
```

**Решение:** Base никогда не должна ссылаться на overlay. Связь всегда однонаправленная: `overlay → base`.

### 3.8. Удаленные базы: проблемы с сетью и Git

**Симптом:**
```bash
Error: accumulating resources: fetching ...
 unable to run: git ... not found
```

**Диагностика:**
```bash
# 1. Проверить наличие git
which git
git --version

# 2. Проверить доступ к репозиторию
git ls-remote https://github.com/org/repo//path?ref=v1.0

# 3. Проверить, что ?ref= указан явно
# Без ref Kustomize клонирует HEAD, что может привести к нестабильности

# 4. В CI-окружении проверить доступ к сети
curl -I https://github.com

# 5. Очистить кэш (при проблемах с актуальностью)
rm -rf /tmp/kustomize-*
```

### 3.9. Диагностика после `kubectl apply`: ресурс не создался/не обновился

```bash
# 1. Сравнить ожидаемое и реальное состояние
kustomize build overlays/production/ > /tmp/expected.yaml
kubectl diff -f /tmp/expected.yaml
# → Покажет все расхождения

# 2. Проверить events целевого ресурса
kubectl describe deployment web-server -n production
# → Секция "Events" покажет ошибки

# 3. Проверить, что манифест валиден на стороне сервера
kustomize build overlays/production/ | kubectl apply --dry-run=server -f -
# → Если есть ошибки, kubectl покажет их

# 4. Проверить, не откатил ли GitOps-контроллер изменение
kubectl get deployment web-server -n production -o yaml | grep "kubectl.kubernetes.io/last-applied-configuration"
```

### 3.10. Отладка с ArgoCD/Flux

```bash
# ArgoCD: что именно видит контроллер
argocd app manifests my-app-production
argocd app diff my-app-production

# Flux: статус и логи kustomize-controller
flux get kustomization my-app-production
flux logs --kind=kustomization --name=my-app-production
kubectl describe kustomization my-app-production -n flux-system

# Проверить, не в состоянии ли лирица (suspend)
flux get kustomizations | grep True  # ← SUSPENDED = true

# Принудительная реконсиляция
flux reconcile kustomization my-app-production --with-source
```

## 4. Дополнительная информация

### Чеклист перед коммитом

```bash
# 1. Валидация YAML
kustomize build . --dry-run=client 2>&1

# 2. Валидация схем Kubernetes API
kustomize build . | kubeconform -strict -summary -

# 3. Проверка diff (если кластер доступен)
kubectl diff -k overlays/production/

# 4. Проверка порядка ресурсов (Namespace → ConfigMap → Deployment)
kustomize build . | grep "^kind:"
```

### Частые ошибки на собеседованиях

**Вопрос:** "У вас есть overlay с `namePrefix: prod-` и патч на Deployment. Патч не применяется. В чем причина?"

**Ответ:** Kustomize применяет `namePrefix` до патчей. Если в патче указан `target.name: myapp`, а после префикса ресурс называется `prod-myapp`, патч не найдёт цель. Нужно указывать имя **до** префикса.

**Вопрос:** "ConfigMap изменился, но Pod не перезапускается. Как диагностировать?"

**Ответ:** Проверить: 1) используется ли `configMapGenerator` (а не статический файл), 2) включен ли `disableNameSuffixHash: false`, 3) действительно ли изменился хеш в `kustomize build` output.

### См. также

- [Обзор Kustomize](./kustomize_overview.md) — базовые определения и установка
- [Наложения и патчи](./kustomize_overlays_and_patches.md) — детали Strategic Merge и JSON Patch
- [Интеграция в CD](./kustomize_cd_integration.md) — troubleshooting в контексте CI/CD

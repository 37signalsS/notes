# Kustomize vs Helm — Рамки принятия решений

## 1. Определения

**Kustomize** — инструмент декларативного управления конфигурациями Kubernetes через наложение патчей (overlays) на базовые YAML-манифесты без шаблонизации. Нативно встроен в `kubectl` с версии 1.14.

**Helm** — пакетный менеджер Kubernetes, использующий Go-шаблоны для параметризации манифестов. Управляет жизненным циклом приложений через механизм релизов (releases) с историей откатов.

**Гибридный подход** — комбинация Helm для получения чартов и Kustomize для кастомизации рендеренных манифестов. Реализуется через `helmCharts` в Kustomize или `--post-renderer` в Helm.

## 2. Основные концепции

### Фундаментальное различие

| Аспект | Kustomize | Helm |
| :--- | :--- | :--- |
| **Подход** | Overlays (наложение патчей) | Templating (шаблонизация) |
| **Язык** | Валидный YAML, без шаблонов | Go templates с `{{ .Values.x }}` |
| **Пакетирование** | Нет (только директории) | Да (charts, OCI registries) |
| **Версионирование** | Git commits | Chart versions + app versions |
| **Release tracking** | Нет (Git = источник истины) | Да (helm history, revisions) |
| **Rollback** | `git revert` / `kubectl rollout undo` | `helm rollback` с историей |
| **Условная логика** | Нет | Да (`if`, `range`, `with`) |
| **Циклы** | Нет | Да (`range`) |
| **Dependency management** | Ручной (Git submodules, ресурсы) | Нативный (Chart.yaml dependencies) |

### Матрица решений: когда что выбирать

| Сценарий | Рекомендация | Обоснование |
| :--- | :--- | :--- |
| **Third-party приложения** (Prometheus, Nginx, cert-manager) | **Helm** | Чарты уже существуют, параметризация через values.yaml |
| **Свои внутренние приложения с 2–5 env** | **Kustomize** | Нет шаблонов, чистый YAML, diff-рендер |
| **Команда новичков в Kubernetes** | **Kustomize** | Низкая кривая обучения, читаемый YAML |
| **Нужен automated rollback** | **Helm** | `helm rollback <release> <revision>` с историей |
| **GitOps подход** | **Оба** | ArgoCD/Flux поддерживают нативно |
| **Сложная параметризация** (условия, циклы) | **Helm** | Go templates дают полную гибкость |
| **Минимальные изменения квантов** | **Kustomize** | Каждый патч — отдельный файл, чистый diff |
| **Мульти-тенантность** | **Kustomize** | Overlays для namespace/tenant, без шаблонов |
| **Распространение чартов другим командам** | **Helm** | OCI-регистры, `helm push/pull` |
| **Нужна validation перед apply** | **Kustomize** | `kustomize build` + `kubeconform` |

### Гибридный паттерн: Helm + Kustomize

```text
helm template (рендеринг)  →  kustomize build (кастомизация)  →  kubectl apply
```

**Сценарий 1: Kustomize поверх Helm-чарта (декларативный)**
```yaml
# kustomization.yaml
helmCharts:
  - name: kube-prometheus-stack
    repo: https://prometheus-community.github.io/helm-charts
    version: 58.x.x
    releaseName: monitoring
    valuesFile: values-base.yaml
    additionalValuesFiles:
      - values-production.yaml
```
```bash
kustomize build --enable-helm .
```

**Сценарий 2: Kustomize пост-рендеринг (императивный)**
```bash
# Рендер Helm-чарта → Kustomize кастомизация → применение
helm template monitoring ./charts/kube-prometheus-stack \
  -f values.yaml \
  | kustomize build overlays/production/
  | kubectl apply -f -
```

**Сценарий 3: Helm post-renderer (плагин в v4)**
```bash
# В Helm v4 post-renderer — плагин типа postrenderer/v1
helm install monitoring ./charts/kube-prometheus-stack \
  --post-renderer kustomize \
  -f values.yaml
```

### Когда Kustomize проигрывает Helm

| Ограничение | Влияние | Решение |
| :--- | :--- | :--- |
| **Нет dependency management** | Сложно управлять зависимостями между сервисами | Использовать `resources` с Git URL или Helm для third-party |
| **Нет release tracking** | Нет истории версий «что было deployed» | Git log + GitOps-контроллер (ArgoCD/Flux) |
| **Нет条件ной логики** | Нельзя создать ресурс на основе переменной | Components (ограниченно) или Helm |
| **Нет циклов** | Нельзя сгенерировать N одинаковых ресурсов | Генераторы или Helm `range` |
| **Нет пакетирования** | Нельзя распространять как единый артефакт | Git submodules или OCI + `kustomize build -o` |

### Когда Helm проигрывает Kustomize

| Ограничение | Влияние | Решение |
| :--- | :--- | :--- |
| **Сложный синтаксис шаблонов** | Малочитаемые `{{ if }}{{ range }}` конструкции | Kustomize overlays с чистым YAML |
| **Diff-рендер затруднен** | Сложно понять, что именно изменится | `helm template` → `diff -u` или Kustomize |
| **Нет нативной интеграции с kubectl** | Требуется отдельный бинарь | `kubectl kustomize` работает «из коробки» |
| **Трудности с immutable ресурсами** | Helm пытается `update` immutable ConfigMap/Secret | Kustomize через hash suffix + пересоздание |
| **Release-мусор** | Старые revisionsconsumes etcd storage | Kustomize не оставляет мусора в кластере |

## 3. Практические сценарии

### 3.1. Полная таблица сравнения для собеседования

```yaml
# Kustomize: Простой overlay
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ../../base
namespace: production
namePrefix: prod-
patches:
  - target:
      kind: Deployment
      name: web-server
    patch: |-
      - op: replace
        path: /spec/replicas
        value: 5
```

```yaml
# Helm: Аналогичная кастомизация через values
# values-production.yaml
replicaCount: 5
namespace: production
nameOverride: prod-
```

**Kustomize** показывает *что именно изменяется* (diff-дружелюбный). **Helm** показывает *итоговое состояние* (diff-враждебный).

### 3.2. Decision Flowchart

```text
Начало
  │
  ├─ Third-party чарт (Prometheus, Ingress, cert-manager)?
  │   └─ ДА → Helm
  │
  ├─ Свое приложение, 2-5 окружений?
  │   └─ ДА → Kustomize
  │
  ├─ Нужны условия/цикла в конфигурации?
  │   └─ ДА → Helm
  │
  ├─ Нужен release tracking и rollback по revisions?
  │   └─ ДА → Helm
  │
  ├─ Команда не знает Go templates?
  │   └─ ДА → Kustomize
  │
  ├─ GitOps (ArgoCD/Flux)?
  │   └─ ДА → Оба (выбор по舒适度)
  │
  └─ Нужно распространять пакеты другим командам?
      └─ ДА → Helm (OCI registries)
```

### 3.3. Миграция с Helm на Kustomize

**Шаг 1:** Экспорт текущих манифестов
```bash
helm template my-release ./chart -f values.yaml > base/manifests.yaml
```

**Шаг 2:** Разбить на базовые ресурсы
```bash
# Разделить multi-doc YAML на отдельные файлы
csplit base/manifests.yaml '/^---/' '{*}'
# Переименовать: 00_namespace.yaml, 01_deployment.yaml, ...
```

**Шаг 3:** Создать overlays
```bash
mkdir -p overlays/{development,staging,production}
# В каждом overlays/*/kustomization.yaml:
resources:
  - ../../base
patches: [...]
```

**Шаг 4:** Обновить CI/CD pipeline
```bash
# Было:
helm upgrade --install my-release ./chart -f values-prod.yaml

# Стало:
kubectl apply -k overlays/production/
# Или через ArgoCD/Flux
```

### 3.4. Миграция с Kustomize на Helm

**Шаг 1:** Создать Helm-шаблоны из base
```bash
helm create my-app
# Скопировать base/*.yaml в templates/
# Заменить статичные значения на {{ .Values.x }}
```

**Шаг 2:** Создать values.yaml для каждого окружения
```yaml
# values.yaml (default)
replicaCount: 2
image:
  repository: my-app
  tag: latest

# values-production.yaml
replicaCount: 5
image:
  tag: v1.7.3
```

**Шаг 3:** Обновить CI/CD pipeline
```bash
# Было:
kubectl apply -k overlays/production/

# Стало:
helm upgrade --install my-app ./chart -f values-production.yaml --atomic
```

### 3.5. Сравнение для собеседования: "Kustomize vs Helm"

**Краткий ответ (30 секунд):**
> Kustomize —.overlay-based подход без шаблонов, встроен в kubectl, ideal для internal apps с 2–5 env. Helm — пакетный менеджер с Go templates, ideal для third-party charts и scenarios с dependency management. Многие команды используют оба: Helm для Prometheus/Nginx, Kustomize для своих сервисов. GitOps (ArgoCD/Flux) поддерживают оба нативно.

**Длинный ответ (с примерами):**
> Kustomize лучше для cases, где нужен чистый diff и minimal learning curve:.base/overlay структура, патчи как отдельные YAML-файлы,GitOps-friendly (kustomize build → apply). Helm лучше для distribution (OCI registries),release tracking (helm history), и conditional logic (if/else в шаблонах). Гибрид: `helm template | kustomize build -` для third-party charts с organizational overlays.

## 4. Дополнительная информация

### Чеклист для принятия решения

- [ ] Определите: third-party или internal приложение?
- [ ] Определите: сколько окружений (dev/staging/prod)?
- [ ] Есть ли потребность в conditions/loops?
- [ ] Нужен ли release tracking с rollback по revisions?
- [ ] Какой уровень GitOps (ArgoCD/Flux)?
- [ ] Какой опыт команды (YAML vs Go templates)?

### Метрики выбора

| Метрика | Kustomize | Helm |
| :--- | :--- | :--- |
| **Кривая обучения** | 1–2 дня | 1–2 недели |
| **Читаемость diff** | Отличная | Средняя |
| **Скорость разработки** | Высокая (без шаблонов) | Средняя (шаблоны) |
| **Поддержка** | SIG (Kubernetes) | CNCF |
| **Распространение** | Git | OCI/Helm Hub |
| **Аудит** | Git log | helm history |

### См. также

- [Обзор Kustomize](./kustomize_overview.md) — сравнение с Helm в таблице
- [Продвинутые возможности](./kustomize_advanced_features.md) — интеграция Helm в Kustomize
- [Helm: Advanced scenarios](../../Helm/Advanced/scenarios.md) — post-rendering с Kustomize

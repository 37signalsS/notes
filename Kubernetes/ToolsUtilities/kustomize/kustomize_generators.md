# Kustomize — Генераторы ConfigMap и Secret

**Актуально для:** Kustomize 5.0–5.8

В Kustomize `configMapGenerator` и `secretGenerator` создают объекты Kubernetes из файлов, литералов или env-файлов. Главная особенность: по умолчанию к имени добавляется хеш содержимого — при изменении данных автоматически запускается rolling update зависимых подов.

## 1. Определения

**Генераторы (Generators)** — механизмы Kustomize для динамического создания ConfigMap и Secret из внешних источников (файлы, env-файлы, литералы) с автоматическим управлением жизненным циклом через хеширование имен.

**configMapGenerator** — генератор ConfigMap из файлов, строковых литералов или env-файлов. По умолчанию к имени добавляется суффикс-хеш (`configmap-name-<hash>`).

**secretGenerator** — генератор Secret. API идентичен `configMapGenerator`, но добавляет поддержку `type` (TLS, docker-registry, Opaque и др.).

**Name Hashing** — механизизм добавления к имени ресурса суффикса на основе SHA256-хеша содержимого. Гарантирует, что при изменении данных имя ресурса изменится, что автоматически триггерит обновление шаблона пода в Deployment/StatefulSet.

**disableNameSuffixHash** — опция (в `generatorOptions` или `options` конкретного генератора), отключающая добавление хеш-суффикса. При `true` имя остается без хеша — ссылки на ресурс не ломаются, но rolling update при изменении данных не запускается автоматически.

## 2. Основные концепции

### Принцип работы Name Hashing

Kustomize вычисляет SHA256-хеш от содержимого ConfigMap/Secret и добавляет 10-символьный «безопасный» суффикс (избегает гласных и похожих на буквы символов `0/1/3/a/e`, по аналогии с `GenerateName` в Kubernetes API) к имени ресурса. Это гарантирует:

- При изменении данных — новое имя → Deployment видит изменение в ссылке → инициируется Rolling Update.
- При откате — ссылка возвращается на старое имя → детерминированный откат к прежнему состоянию.

### NameReferenceTransformer — автоматическое переписывание ссылок

Kustomize применяет **NameReferenceTransformer** к всему выходному манифесту. Когда имя ресурса изменяется (например, хеш-суффикс добавлен), ссылки на него переписываются во всех местах: Deployments, StatefulSets, Pods, VolumeClaimTemplates. Это работает независимо от того, где ссылка используется — через `configMapRef`, `secretRef`, `envFrom` или `volumes`.

### Отключение хеш-суффикса

По умолчанию (`disableNameSuffixHash: false`) хеш добавляется. Отключение (`true`) требуется, когда имя ресурса жёстко прописано во внешних системах (Helm-чарты, HelmRelease, sidecar-контроллеры с фиксированными именами).

### Поведение генераторов (behavior)

При наследовании (base → overlay) можно управлять взаимодействием:

- `create` — создает новый независимый ресурс (по умолчанию).
- `merge` — объединяет данные из overlay с данными из base.
- `replace` — полностью заменяет генератор из базы.

## 3. Практические сценарии

### 3.1. configMapGenerator: основы

Генератор создаёт ConfigMap из файлов, литералов и env-файлов:

```yaml
# kustomization.yaml
configMapGenerator:
  - name: vector-config
    namespace: observability
    files:
      - vector.yaml=configs/vector.yaml
    options:
      labels:
        app.kubernetes.io/component: vector

generatorOptions:
  disableNameSuffixHash: false
```

Генерируется ConfigMap с именем `vector-config-<hash>`. Любой Deployment, ссылающийся на этот ConfigMap, автоматически перезапустится при изменении `configs/vector.yaml`.

**Синтаксис `key=source`:**

- `vector.yaml=configs/vector.yaml` — ключ внутри ConfigMap будет `vector.yaml`, данные берутся из `configs/vector.yaml`.
- Без `=` (например, просто `configs/vector.yaml`) — имя файла используется и как ключ, и как путь: ключ `vector.yaml`, источник `configs/vector.yaml`.

### 3.2. Отключение хеш-суффикса

Когда имя ConfigMap жёстко прописано во внешних системах (Helm values, sidecar-контроллеры), хеш-суффикс ломает ссылку:

```yaml
# kustomization.yaml
configMapGenerator:
  - name: grafana-dashboards
    namespace: observability
    options:
      disableNameSuffixHash: true
    files:
      - dashboards/cluster-overview.json
      - dashboards/apisix.json
      - dashboards/nodes.json
```

При `disableNameSuffixHash: true` имя остаётся `grafana-dashboards`. Sidecar Grafana находит ConfigMap по метке и загружает дашборды динамически.

> **Важно:** при отключении хеша смена данных не вызовет автоматический rolling update. Для применения изменений используйте `kubectl rollout restart` вручную.

### 3.3. secretGenerator

API идентичен `configMapGenerator`, добавлено поле `type`:

```yaml
# kustomization.yaml
secretGenerator:
  - name: vector-tls
    namespace: observability
    files:
      - tls.crt=certs/vector-tls.crt
      - tls.key=certs/vector-tls.key
    type: kubernetes.io/tls
    options:
      disableNameSuffixHash: true
```

Для учётных данных из литералов:

```yaml
# kustomization.yaml
secretGenerator:
  - name: app-db-credentials
    namespace: dev
    literals:
      - username=appuser
      - password=changeme
```

> **Безопасность:** реальные секреты не должны храниться в `literals` в открытом виде. Используйте [SealedSecrets](https://github.com/bitnami-labs/sealed-secrets) или [ExternalSecrets](https://external-secrets.io/). Подробнее о безопасном управлении секретами в CD: [Интеграция Kustomize в конвейеры CD](./kustomize_cd_integration.md).

### 3.4. Источник из env-файла (envs)

Для нескольких пар `key=value` из `.env`-файла:

```yaml
# kustomization.yaml
configMapGenerator:
  - name: app-config
    namespace: dev
    envs:
      - configs/app.env
```

Содержимое `configs/app.env`:

```text
LOG_LEVEL=info
METRICS_PORT=9090
FEATURE_FLAG_X=true
DB_HOST=postgres.dev.svc.cluster.local
```

Каждая строка становится отдельным ключом в ConfigMap. Удобнее длинного списка `literals:`.

**Правила формата env-файла:**

- Каждая строка — пара `key=value`; разделителем является первый символ `=`.
- Комментарии начинаются с `#` (строка пропускаются).
- Имя ключа должно быть валидным именем переменной окружения: `[a-zA-Z_][a-zA-Z0-9_]*`.

### 3.5. valuesFrom в HelmRelease

ConfigMap от Kustomize можно передавать как values-источник для HelmRelease (Flux CD):

```yaml
# HelmRelease
spec:
  valuesFrom:
    - kind: ConfigMap
      name: vector-helm-values
      valuesKey: values.yaml
```

```yaml
# kustomization.yaml
configMapGenerator:
  - name: vector-helm-values
    namespace: observability
    options:
      disableNameSuffixHash: true
    files:
      - values.yaml=helm-values/vector-values.yaml
```

Удобно, когда values-файл большой или часто меняется — не нужно встраивать весь YAML прямо в HelmRelease.

> **Примечание:** `valuesFrom` — это функция [HelmRelease CRD](https://fluxcd.io/flux/components/helm/api/#valuesfrom) из Flux CD, а не Kustomize. Kustomize здесь выступает как генератор источника значений.

### 3.6. Патчи + генераторы вместе

Патчи могут ссылаться на ConfigMap по оригинальному имени — Kustomize автоматически перепишет ссылки на имя с хешем через NameReferenceTransformer:

```yaml
# kustomization.yaml
patches:
  - patch: |
      apiVersion: apps/v1
      kind: Deployment
      metadata:
        name: vector
      spec:
        template:
          spec:
            volumes:
              - name: config
                configMap:
                  name: vector-config   # переписывается в vector-config-<hash>
    target:
      kind: Deployment
      name: vector
```

Kustomize переписывает ссылки на имена ConfigMap по всему выходному манифесту — в Deployments, StatefulSets, Pods.

### 3.7. Несколько генераторов

```yaml
# kustomization.yaml
configMapGenerator:
  - name: prometheus-rules
    namespace: monitoring
    files:
      - alerting-rules/k8s.yaml
      - alerting-rules/apps.yaml
      - alerting-rules/infra.yaml
    options:
      disableNameSuffixHash: true
      annotations:
        prometheus-operator: "true"
  - name: grafana-provisioning
    namespace: monitoring
    files:
      - provisioning/datasources.yaml
      - provisioning/dashboards.yaml
    options:
      disableNameSuffixHash: true
```

## 4. Диагностика

Проверить, что генерирует Kustomize до применения:

```bash
kubectl kustomize . | grep -A 20 "kind: ConfigMap"
```

Проверить сгенерированный хеш-суффикс:

```bash
kubectl get configmap -n observability | grep vector-config
# → vector-config-7d3k8f9b4h   1     5m
```

Подробнее об отладке Kustomize: [Отладка и диагностика](./kustomize_debugging.md).

## 5. Рекомендации и лучшие практики

- **Всегда используйте `configMapGenerator`/`secretGenerator`** вместо статических манифестов — это гарантирует хеш-суффикс и автоматический rolling update при изменении данных.
- **Для production включайте `immutable: true`** через `generatorOptions` — снижает нагрузку на kube-apiserver и предотвращает конфигурационный дрейф.
- **Для фиксированных имён** (Helm values, sidecar-контроллеры) используйте `disableNameSuffixHash: true`, но помните о необходимости ручного `rollout restart`.
- **Никогда не храните секреты в `literals`** — используйте SealedSecrets или ExternalSecrets. Подробнее: [Управление секретами в CD](./kustomize_cd_integration.md#36-управление-секретами).
- **Используйте env-файлы (`envs`)** для большого количества пар `key=value` — это чище, чем длинный список `literals:`.

## 6. Дополнительная информация

### См. также

- **[Продвинутые возможности](./kustomize_advanced_features.md)** — компоненты, replacements, hash-суффиксы, exec-плагины.
- **[Структура и синтаксис](./kustomize_structure_and_syntax.md)** — полный разбор полей `kustomization.yaml`.
- **[Наложения и патчи](./kustomize_overlays_and_patches.md)** — механизм `behavior: merge` для генераторов в оверлеях.
- **[Отладка и диагностика](./kustomize_debugging.md)** — troubleshooting ошибок сборки и проблем с хеш-суффиксами.
- **[Интеграция в CD](./kustomize_cd_integration.md)** — CI/CD-пайплайны, GitOps, управление секретами.
- **[Создание ConfigMap](Base/ConfigMap/creation.md)** — сравнение методов создания, детали Name Hashing.
- **[Создание Secret](Base/secrets/creating_secrets.md)** — secretGenerator с примерами и best practices.

### Внешние ресурсы

- [Kustomize Generators Documentation](https://kubectl.docs.kubernetes.io/references/kustomize/kustomization/configmapgenerator/)
- [Kustomize SecretGenerator Documentation](https://kubectl.docs.kubernetes.io/references/kustomize/kustomization/secretgenerator/)
- [Flux CD HelmRelease API](https://fluxcd.io/flux/components/helm/api/)

## Приложение: Overlap Declaration

Ниже перечислены существующие файлы, проверенные на пересечение тем (§0.2, §0.10):

1. `kustomize_advanced_features.md` (§3.1 «Продвинутая генерация ресурсов») — содержит краткий пример `configMapGenerator` с `generatorOptions`. Ссылка на этот файл добавлена в «См. также». Секция 3.1 дополена кросс-ссылкой на новый SSoT.
2. `kustomize_cd_integration.md` («Хеширование имен в CD») — содержит примеры `configMapGenerator` и `secretGenerator` в контексте CD. Дублирование минимальное; добавлена кросс-ссылка.
3. `kustomize_debugging.md` (§3.6) — содержит отладку проблем с хеш-суффиксом. Дублирование избегнуто: отдельная диагностическая секция в этом файле направляет читателя в `kustomize_debugging.md`.
4. `ConfigMap/creation.md` (§«Сценарий 2») — содержит детальный `configMapGenerator` с `envs`, `generatorOptions`, `behavior`. Ссылка добавлена в «См. также».
5. `secrets/creating_secrets.md` (§«Генерация через Kustomize») — содержит `secretGenerator` с `literals`, `files`, `envs`, `type`. Ссылка добавлена в «См. также».
6. `ConfigMap/best_practices.md` — упоминает `configMapGenerator` в контексте Name Hashing. Ссылка добавлена в «См. также».
7. `kustomize_overlays_and_patches.md` (§3.6) — `behavior: merge` для генераторов в оверлеях. Отдельная тема от автоматического переписывания ссылок (§3.6 этого файла); ссылка добавлена.

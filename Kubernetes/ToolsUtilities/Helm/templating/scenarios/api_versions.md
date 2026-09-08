# Проверка версий API и возможностей кластера

---

## Определения

**API-группы и версии** — иерархическая структура ресурсов Kubernetes (например, `apps/v1`, `networking.k8s.io/v1`). Версионность позволяет внедрять новые функции (Alpha, Beta) и плавно выводить устаревшие API из обращения.

**.Capabilities** — встроенный объект Helm, предоставляющий метаданные о целевом кластере и клиенте: версию ядра Kubernetes, список поддерживаемых API-ресурсов и версию Helm.

**Интроспекция (Introspection)** — процесс программного анализа среды выполнения (кластера) для динамической адаптации манифестов во время рендеринга.

**Discovery cache** — кэш информации об API, который Helm получает от `kubectl`/API-сервера. Helm использует этот кэш для заполнения `.Capabilities.APIVersions` и кэширует его на диске между вызовами.

**Deprecation lifecycle** — этапы жизни API в Kubernetes: `Alpha` → `Beta` → `Stable (GA)` → `Deprecated` → `Removed`. Каждый этап имеет чётко определённые сроки и гарантии обратной совместимости.

---

## Основные концепции

### Объект .Capabilities

Helm позволяет адаптировать манифесты под конкретное окружение, используя свойства объекта `.Capabilities`:

- **`.Capabilities.KubeVersion`**: Объект с версией Kubernetes.
  - `.Version`: Полная строка версии (например, `v1.30.2`).
  - `.Major`: Мажорная версия (обычно `1`).
  - `.Minor`: Минорная версия (например, `30`).

- **`.Capabilities.APIVersions`**: Список строк вида `<group>/<version>` или `<group>/<version>/<resource>`, доступных в целевом кластере. Для проверки используется метод `Has`:
  - `"batch/v1/CronJob"` — проверка конкретного ресурса.
  - `"networking.k8s.io/v1"` — проверка группы и версии.
  - `"policy/v1"` — проверка версии группы без указания ресурса.

- **`.Capabilities.HelmVersion`**: Объект с версией клиента Helm.
  - `.Version`: Полная строка версии (например, `v4.0.0`).
  - `.Major`, `.Minor`: компоненты версии.

### Источники данных для .Capabilities

Helm заполняет `.Capabilities` из разных источников в зависимости от режима работы:

| Режим | Источник данных | Особенности |
|-------|-----------------|-------------|
| `helm install` / `upgrade` / `rollback` | Живой API-сервер | Полный discovery. Обновляется при каждом вызове Helm. |
| `helm template` (оффлайн) | Дефолтные значения Helm | Используется последняя стабильная версия K8s, известная на момент сборки Helm. `.Capabilities.APIVersions.Has` может возвращать `false` для ресурсов, доступных в целевом кластере. |
| `helm install --dry-run=client` | Дефолтные значения | Без обращения к кластеру. Аналогично `helm template`. |
| `helm install --dry-run=server` | Живой API-сервер | Полные данные, как при реальном деплое. Требует доступа к кластеру. |

**Важно:** Helm кэширует discovery на диске (обычно в `~/.cache/helm/repository/`). При обновлении кластера кэш может содержать устаревшие данные. Для принудительного обновления используйте `--dry-run --debug` или удалите кэш.

### Сравнение версий через semverCompare

Для логических проверок версий используется функция `semverCompare`.

**Критическая деталь:** Всегда используйте суффикс `-0` в строках сравнения (например, `^1.22-0`). Это гарантирует, что версии с метаданными (например, `1.22.0-gke.100` или пре-релизы `1.23.0-alpha`) будут обработаны корректно согласно спецификации SemVer.

| Задача | Синтаксис |
|--------|-----------|
| Кластер 1.22 или выше | `semverCompare ">=1.22-0" .Capabilities.KubeVersion.Version` |
| Кластер строго 1.25.x | `semverCompare "1.25.x" .Capabilities.KubeVersion.Version` |

### Жизненный цикл API в Kubernetes

При написании адаптивных шаблонов необходимо учитывать этапы deprecation:

| Статус | Гарантия | Пример поведения |
|--------|----------|------------------|
| `Alpha` | Может быть удалён без предупреждения | `networking.k8s.io/v1alpha1` |
| `Beta` | Поддерживается минимум 3 релиза | `batch/v1beta1/CronJob` |
| `Stable (GA)` | Постоянная поддержка | `apps/v1/Deployment` |
| `Deprecated` | Планируется удаление, предупреждение в релизных нотах | `extensions/v1beta1/Ingress` |
| `Removed` | Удалён из кода API-сервера | Деплой с `apiVersion: extensions/v1beta1` падает с `no matches` |

**Практический совет:** Никогда не проверяйте deprecation-статус через `semverCompare` по версии K8s. Используйте `.Capabilities.APIVersions.Has`, так как API может быть отключён через feature-gate независимо от версии ядра.

### Эмуляция возможностей в CLI

При использовании `helm template` (оффлайн-режим) Helm не подключается к кластеру и использует встроенные значения по умолчанию. Для корректной разработки адаптивных шаблонов необходимо эмулировать среду:

```bash
# Эмуляция версии кластера
helm template my-release . --kube-version 1.25.0

# Эмуляция доступных API (можно указывать несколько раз)
helm template my-release . \
  --api-versions "networking.k8s.io/v1/Ingress" \
  --api-versions "batch/v1/CronJob" \
  --api-versions "policy/v1/PodDisruptionBudget"

# Комбинированный dry-run с реальным кластером (server-side)
helm install my-release . --dry-run=server
```

### Взаимодействие с субчартами

Объект `.Capabilities` заполняется глобально для всего релиза. Все чарты (родительский и субчарты) видят одни и те же значения `.Capabilities`, соответствующие целевому кластеру. Это гарантирует консистентность выбора API между чартами.

---

## Практические сценарии

### Выбор API для Ingress

Ingress — наиболее частый пример миграции API. Рекомендуется проверять наличие API-ресурса, а не версию Kubernetes.

```yaml
{{- if .Capabilities.APIVersions.Has "networking.k8s.io/v1/Ingress" }}
apiVersion: networking.k8s.io/v1
{{- else if .Capabilities.APIVersions.Has "networking.k8s.io/v1beta1/Ingress" }}
apiVersion: networking.k8s.io/v1beta1
{{- else }}
apiVersion: extensions/v1beta1
{{- end }}
kind: Ingress
```

### Миграция CronJob

Ресурс `CronJob` перешёл в `batch/v1` в версии 1.21.

```yaml
apiVersion: {{ if .Capabilities.APIVersions.Has "batch/v1/CronJob" }}batch/v1{{ else }}batch/v1beta1{{ end }}
kind: CronJob
metadata:
  name: {{ include "myapp.fullname" . }}-job
```

### Адаптация HorizontalPodAutoscaler (HPA)

В современных кластерах (1.23+) используется `autoscaling/v2`, который заменил `v2beta1` и `v2beta2`.

```yaml
apiVersion: {{ if .Capabilities.APIVersions.Has "autoscaling/v2/HorizontalPodAutoscaler" }}autoscaling/v2{{ else }}autoscaling/v2beta2{{ end }}
kind: HorizontalPodAutoscaler
spec:
  # Синтаксис метрик в v2 отличается от beta-версий
  metrics:
  {{- if .Capabilities.APIVersions.Has "autoscaling/v2/HorizontalPodAutoscaler" }}
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: {{ .Values.hpa.cpuLimit }}
  {{- else }}
    - type: Resource
      resource:
        name: cpu
        targetAverageUtilization: {{ .Values.hpa.cpuLimit }}
  {{- end }}
```

### Условное использование ingressClassName

Поле `ingressClassName` появилось в 1.18. Для старых кластеров необходимо использовать аннотацию.

```yaml
metadata:
  annotations:
    {{- if and .Values.ingress.className (not (semverCompare ">=1.18-0" .Capabilities.KubeVersion.Version)) }}
    kubernetes.io/ingress.class: {{ .Values.ingress.className | quote }}
    {{- end }}
spec:
  {{- if and .Values.ingress.className (semverCompare ">=1.18-0" .Capabilities.KubeVersion.Version) }}
  ingressClassName: {{ .Values.ingress.className }}
  {{- end }}
```

### Адаптация PodDisruptionBudget (policy/v1)

Ресурс `PodDisruptionBudget` перешёл в `policy/v1` в версии 1.21.

```yaml
{{- if .Capabilities.APIVersions.Has "policy/v1/PodDisruptionBudget" }}
apiVersion: policy/v1
{{- else }}
apiVersion: policy/v1beta1
{{- end }}
kind: PodDisruptionBudget
metadata:
  name: {{ include "myapp.fullname" . }}
spec:
  minAvailable: {{ .Values.pdb.minAvailable }}
  selector:
    matchLabels:
      app.kubernetes.io/name: {{ include "myapp.name" . }}
```

### Работа с CustomResourceDefinition (CRD)

Проверяйте наличие CRD перед созданием зависящих от него ресурсов:

```yaml
{{- if .Capabilities.APIVersions.Has "cert-manager.io/v1/Certificate" }}
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: {{ include "myapp.fullname" . }}-tls
spec:
  secretName: {{ include "myapp.fullname" . }}-tls
  issuerRef:
    name: {{ .Values.certManager.issuer }}
    kind: {{ .Values.certManager.kind }}
  dnsNames:
    {{- range .Values.ingress.hosts }}
    - {{ .host }}
    {{- end }}
{{- end }}
```

### Валидация через kubectl api-resources

Для аудита возможностей кластера используйте стандартные утилиты `kubectl`:

```bash
# Список всех доступных API-версий
kubectl api-versions | sort

# Проверка доступности конкретного ресурса
kubectl api-resources | grep -i ingress
# → NAME                              SHORTNAMES   APIVERSION                         NAMESPACED   KIND
# → ingresses                         ing          networking.k8s.io/v1              true         Ingress

# Проверка версии API-сервера
kubectl version --short
# → Server Version: v1.30.2

# Проверка зарегистрированных CRD
kubectl get crd | grep cert-manager.io
# → certificates.cert-manager.io   cert-manager.io/v1   2024-01-15
```

### CI/CD: Валидация API-совместимости в пайплайне

Интегрируйте проверку API-версий в pipeline для предотвращения деплоя несовместимых чартов:

```bash
#!/bin/bash
set -euo pipefail

RELEASE_NAME="myapp"
CHART_PATH="./my-chart"
VALUES_FILE="-f values/production.yaml"

# Получение реальных API-версий с целевого кластера
TARGET_CLUSTER_API=$(kubectl api-versions --context=prod-cluster | sort)

# Рендеринг чарта с явным указанием возможностей
RENDERED=$(helm template ${RELEASE_NAME} ${CHART_PATH} ${VALUES_FILE} \
  --api-versions $(echo "${TARGET_CLUSTER_API}" | sed 's/$/\//' | tr '\n' ' '))

# Проверка: все ресурсы должны иметь поддерживаемые apiVersion
echo "${RENDERED}" | grep -E '^apiVersion:' | sort | uniq -c

# Дополнительная проверка через yq
echo "${RENDERED}" | yq eval '.*.apiVersion' - | sort | uniq
```

### Multi-cluster совместимость

Для чартов, развёртываемых в кластерах разных версий, поддерживайте матрицу совместимости:

```bash
#!/bin/bash
# validate_api_compatibility.sh
# Проверяет, что чарт рендерится корректно для списка целевых версий K8s

CHART_PATH="./my-chart"
VALUES_FILE="-f values/defaults.yaml"

K8S_VERSIONS=("1.22.0" "1.25.0" "1.28.0" "1.30.0")

for version in "${K8S_VERSIONS[@]}"; do
  echo "=== Testing against K8s ${version} ==="
  helm template myapp "${CHART_PATH}" ${VALUES_FILE} \
    --kube-version "${version}" \
    --api-versions "networking.k8s.io/v1/Ingress" \
    --api-versions "batch/v1/CronJob" \
    --api-versions "policy/v1/PodDisruptionBudget" \
    --api-versions "autoscaling/v2/HorizontalPodAutoscaler" \
    > "/tmp/rendered-${version}.yaml"

  if [ $? -eq 0 ]; then
    echo "OK: ${version}"
  else
    echo "FAIL: ${version}"
    exit 1
  fi
done
```

---

## Дополнительная информация

### Лучшие практики

1. **Приоритет API над версией:** Всегда проверяйте `.Capabilities.APIVersions.Has` вместо версии ядра через `semverCompare`. API-группы могут быть включены/выключены или установлены через CRD независимо от версии K8s.

2. **Обработка Dry-run:** Помните, что при `helm install --dry-run=client` или `helm template` Helm использует дефолтные значения `.Capabilities`. Для точной валидации используйте `--dry-run=server` или явно задавайте флаги `--kube-version` и `--api-versions`.

3. **Изоляция в хелперы:** Если проверка API используется многократно, вынесите логику в `_helpers.tpl`:

   ```yaml
   {{- define "myapp.ingress.apiVersion" -}}
   {{- if .Capabilities.APIVersions.Has "networking.k8s.io/v1/Ingress" -}}
   networking.k8s.io/v1
   {{- else if .Capabilities.APIVersions.Has "networking.k8s.io/v1beta1/Ingress" -}}
   networking.k8s.io/v1beta1
   {{- else -}}
   extensions/v1beta1
   {{- end -}}
   {{- end -}}
   ```

   Использование:

   ```yaml
   apiVersion: {{ include "myapp.ingress.apiVersion" . }}
   kind: Ingress
   ```

4. **Правило одного API-версии на ресурс:** Не смешивайте проверки версии Kubernetes и API-версий для одного и того же ресурса. Если проверяете `.Capabilities.APIVersions.Has`, не дублируйте проверку через `semverCompare`.

5. **CI reproducibility:** В CI/CD пайплайнах всегда указывайте `--api-versions` явно, чтобы получить детерминированный рендеринг, не зависящий от дефолтов Helm.

6. **Тестирование на всех целевых версиях:** Автоматизируйте проверку чарта на всех поддерживаемых версиях Kubernetes перед выпуском релиза.

### Устранение неисправностей

| Проблема | Вероятная причина | Решение |
|----------|-------------------|---------|
| `Has` возвращает `false` в `template` | Оффлайн-режим использует дефолты | Используйте флаг `--api-versions` или `--dry-run=server` |
| Ошибка сравнения GKE/EKS версий | Отсутствие суффикса `-0` | Добавьте `-0` в строку версии (например, `1.22-0`) |
| API доступно в кластере, но чарт падает | Устаревший discovery cache | Удалите кэш Helm или используйте `--dry-run --debug` |
| `--dry-run=client` даёт другой результат, чем `server` | В client-mode `.Capabilities` дефолтны | Используйте `--dry-run=server` для проверки или явно задайте `--api-versions` |
| CRD установлен, но `Has` возвращает `false` | CRD не установлен в namespace релиза | Убедитесь, что CRD глобальный (cluster-scoped) или установлен в нужном namespace |
| Адаптивный шаблон падает при миграции кластера | Жёсткая привязка к версии через `semverCompare` | Замените проверку версии на `.Capabilities.APIVersions.Has` |
| Конфликт conversion webhook | CRD имеет разные версии conversion | Проверьте `crdConversion` в API-сервере и используйте единую версию в чарте |

### См. также

- [Обзор сценариев шаблонизации](./overview.md) — архитектура рендеринга и ограничения оффлайн-режима.
- [Продвинутые сценарии Helm](../Advanced/scenarios.md) — адаптивные чарты, Gateway API, Istio, OCI.
- [Встроенные объекты Helm](../objects.md) — полный справочник по `.Capabilities`, `.Release`, `.Chart`.

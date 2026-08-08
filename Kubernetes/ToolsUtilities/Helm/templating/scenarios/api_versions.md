# Проверка версий API и возможностей кластера

---

## Определения

**API-группы и версии** — иерархическая структура ресурсов Kubernetes (например, `apps/v1`, `networking.k8s.io/v1`). Версионность позволяет внедрять новые функции (Alpha, Beta) и плавно выводить устаревшие.

**.Capabilities** — встроенный объект Helm, предоставляющий метаданные о целевом кластере: версию ядра Kubernetes, список поддерживаемых API-ресурсов и версию клиента Helm.

**Интроспекция (Introspection)** — процесс программного анализа среды выполнения (кластера) для динамической адаптации манифестов во время рендеринга.

---

## Основные концепции

### Объект .Capabilities

Helm позволяет адаптировать манифесты под конкретное окружение, используя свойства объекта `.Capabilities`:

*   **`.Capabilities.KubeVersion`**: Объект с версией Kubernetes.
    *   `.Version`: Полная строка версии (например, `v1.30.2`).
    *   `.Major`: Мажорная версия (обычно `1`).
    *   `.Minor`: Минорная версия (например, `30`).
*   **`.Capabilities.APIVersions.Has`**: Метод для проверки наличия конкретной группы/версии/ресурса. Примеры:
    *   `"batch/v1/CronJob"` — проверка ресурса.
    *   `"networking.k8s.io/v1"` — проверка группы и версии.

### Эмуляция возможностей в CLI

При использовании `helm template` (оффлайн-режим) Helm не подключается к кластеру и использует встроенные значения по умолчанию (обычно последнюю стабильную версию). Для корректной разработки адаптивных шаблонов необходимо эмулировать среду:

```bash
# Эмуляция версии кластера
helm template my-release . --kube-version 1.25.0

# Эмуляция доступных API (через запятую)
helm template my-release . --api-versions "networking.k8s.io/v1/Ingress" --api-versions "batch/v1"
```

### Сравнение версий через semverCompare

Для логических проверок версий используется функция `semverCompare`. 

**Критическая деталь:** Всегда используйте суффикс `-0` в строках сравнения (например, `^1.22-0`). Это гарантирует, что версии с метаданными (например, `1.22.0-gke.100` или пре-релизы `1.23.0-alpha`) будут обработаны корректно согласно спецификации SemVer.

| Задача | Синтаксис |
|--------|-----------|
| Кластер 1.22 или выше | `semverCompare ">=1.22-0" .Capabilities.KubeVersion.Version` |
| Кластер строго 1.25.x | `semverCompare "1.25.x" .Capabilities.KubeVersion.Version` |

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

---

## Дополнительная информация

### Лучшие практики

1.  **Приоритет API над версией:** Всегда проверяйте `.Capabilities.APIVersions.Has` вместо версии ядра через `semverCompare`. API-группы могут быть включены/выключены или установлены через CRD независимо от версии K8s.
2.  **Обработка Dry-run:** Помните, что при `helm install --dry-run` Helm подключается к кластеру и получает реальные значения `.Capabilities`.
3.  **Изоляция в хелперы:** Если проверка API используется многократно (например, для `apiVersion`), вынесите логику в `_helpers.tpl`.

### Устранение неисправностей

| Проблема | Причина | Решение |
|----------|---------|---------|
| `Has` возвращает `false` в `template` | Оффлайн-режим использует дефолты | Используйте флаг `--api-versions` |
| Ошибка сравнения GKE/EKS версий | Отсутствие суффикса `-0` | Добавьте `-0` в строку версии (например, `1.22-0`) |
| API доступно, но ресурс не создается | Кэширование `discovery` в Helm | При разработке используйте `--dry-run --debug` для принудительного обновления |

### См. также
- [Встроенные объекты Helm](../objects.md) — справочник по свойствам `.Capabilities`.
- [Функции Helm-шаблонов](../functions.md) — детально про `semverCompare`.
- [Синтаксис Helm-шаблонов](../syntax.md) — управляющие конструкции `if/else`.
- [Обзор сценариев шаблонизации](./overview.md) — каталог практических примеров.

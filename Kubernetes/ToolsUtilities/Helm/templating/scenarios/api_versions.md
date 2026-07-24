# Проверка версий API и возможностей кластера

---

## Определения

**API (Application Programming Interface)** — в контексте Kubernetes это интерфейс, через который осуществляется управление ресурсами (Deployment, Service, Ingress и др.). API разделены на группы и версии (например, `apps/v1`, `networking.k8s.io/v1`).

**`.Capabilities`** — встроенный объект Helm, предоставляющий информацию о версии Kubernetes, поддерживаемых API-версиях и других возможностях целевого кластера.

**SemVer (Semantic Versioning)** — стандарт семантического версионирования (`MAJOR.MINOR.PATCH`), используемый для сравнения версий кластера и чартов.

---

## Базовые концепции

### Объект .Capabilities

Helm позволяет адаптировать манифесты под конкретное окружение, используя свойства объекта `.Capabilities`:

- `.Capabilities.KubeVersion.Version` — строка с полной версией Kubernetes (например, `v1.28.3`).
- `.Capabilities.KubeVersion.Major` — мажорная версия (1).
- `.Capabilities.KubeVersion.Minor` — минорная версия (28).
- `.Capabilities.APIVersions.Has "group/version/Kind"` — логическая проверка наличия конкретного ресурса в кластере.

### Особенности работы в оффлайн-режиме

При выполнении команды `helm template` (без подключения к кластеру) объект `.Capabilities` будет содержать значения по умолчанию (обычно последнюю стабильную версию). Для корректного тестирования адаптивных шаблонов необходимо передавать флаги:
- `--kube-version` — эмуляция версии Kubernetes.
- `--api-versions` — список доступных API-групп.

### Сравнение версий через semverCompare

Для гибкой проверки версий используется функция `semverCompare`. Важной деталью является использование суффикса `-0` (например, `^1.20-0`), который позволяет корректно обрабатывать пре-релизные версии Kubernetes (alpha/beta).

| Сравнение | Описание |
|-----------|----------|
| `semverCompare ">=1.19-0" .Capabilities.KubeVersion.Version` | Проверка, что версия кластера 1.19 или выше. |
| `semverCompare "<1.22-0" .Capabilities.KubeVersion.Version` | Проверка, что версия ниже 1.22. |

---

## Практические сценарии

### Выбор API-версии для Ingress

Интерфейс Ingress является классическим примером изменения API-групп. Рекомендуется проверять наличие конкретного API, а не версию Kubernetes, так как это более надежно.

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

### Адаптация PodDisruptionBudget (PDB)

Переход от `policy/v1beta1` к `policy/v1` (стабилен с K8s 1.21).

```yaml
{{- if .Capabilities.APIVersions.Has "policy/v1/PodDisruptionBudget" }}
apiVersion: policy/v1
{{- else }}
apiVersion: policy/v1beta1
{{- end }}
kind: PodDisruptionBudget
```

### Горизонтальное масштабирование (HPA)

Адаптация под современные версии `autoscaling/v2` (заменил `v2beta2` в K8s 1.23+).

```yaml
apiVersion: {{ if .Capabilities.APIVersions.Has "autoscaling/v2/HorizontalPodAutoscaler" }}autoscaling/v2{{ else }}autoscaling/v2beta2{{ end }}
kind: HorizontalPodAutoscaler
metadata:
  name: {{ include "myapp.fullname" . }}
spec:
  # Синтаксис метрик может отличаться между v2beta2 и v2
  metrics:
    {{- toYaml .Values.autoscaling.metrics | nindent 4 }}
```

### Адаптивный Ingress с ingressClassName

В версиях Kubernetes ниже 1.18 класс Ingress указывался через аннотацию. Начиная с 1.18 рекомендуется использовать поле `spec.ingressClassName`.

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

1. **Приоритет API над Версией:** Всегда отдавайте предпочтение проверке `.Capabilities.APIVersions.Has` вместо сравнения версии ядра кластера через `semverCompare`. Конкретные API-группы могут быть включены или выключены независимо от версии Kubernetes.
2. **Обработка Dry-run:** Помните, что при `helm install --dry-run` Helm подключается к кластеру и получает реальные значения `.Capabilities`, в то время как `helm template` использует дефолты.
3. **Использование суффикса -0:** Всегда добавляйте `-0` в строках сравнения `semverCompare`, чтобы избежать ошибок с версиями типа `1.22.0-gke.100`.

### См. также
- [Встроенные объекты Helm](../objects.md) — подробное описание свойств `.Capabilities`.
- [Функции Helm](../functions.md) — работа с `semverCompare` и другими функциями.
- [Синтаксис шаблонов](../syntax.md) — управляющие конструкции `if/else`.

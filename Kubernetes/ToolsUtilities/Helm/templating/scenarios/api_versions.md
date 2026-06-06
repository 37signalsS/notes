# Проверка версий API в Helm

---

## Определения

**API (Application Programming Interface)** — интерфейс программирования приложений, набор правил и протоколов для взаимодействия компонентов Kubernetes.

**`.Capabilities`** — встроенный объект Helm для получения информации о версии Kubernetes и доступных API-ресурсах кластера. Подробнее: [Встроенные объекты Helm](../objects.md).

**SemVer (Semantic Versioning)** — семантическое версионирование, формат версий `MAJOR.MINOR.PATCH`.

---

## Базовые концепции

Helm адаптирует манифесты под версию Kubernetes через объект `.Capabilities`:

- `.Capabilities.KubeVersion.Version` — полная версия Kubernetes (например, `v1.28.3`).
- `.Capabilities.KubeVersion.Major` — мажорная версия (`1`).
- `.Capabilities.KubeVersion.Minor` — минорная версия (`28`).
- `.Capabilities.APIVersions.Has "group/version/Kind"` — проверка доступности конкретного ресурса API.

Для сравнения версий используется функция `semverCompare`. Она позволяет выполнять логические проверки (например, `>=1.20-0`) для адаптации манифестов к различным версиям кластера.

---

## Практические сценарии

### Выбор API версии для Ingress

Интерфейс Ingress API менялся несколько раз: `extensions/v1beta1` → `networking.k8s.io/v1beta1` → `networking.k8s.io/v1`. Шаблон ниже автоматически выбирает корректную версию:

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

### Сравнение версий Kubernetes

Применение условной логики в зависимости от версии кластера:

```yaml
{{- if semverCompare ">=1.20-0" .Capabilities.KubeVersion.Version }}
# Логика для K8s 1.20+
{{- else }}
# Логика для старых версий
{{- end }}
```

### Проверка нескольких API одновременно

```yaml
{{- if and
  (.Capabilities.APIVersions.Has "networking.k8s.io/v1/Ingress")
  (.Capabilities.APIVersions.Has "metrics.k8s.io/v1beta1")
}}
# Оба API доступны
{{- end }}
```

### Адаптивный Ingress с `ingressClassName`

До Kubernetes версии 1.18 класс Ingress указывался через аннотацию, начиная с 1.18 — через поле `spec.ingressClassName`:

```yaml
metadata:
  annotations:
    {{- if and .Values.ingress.className (not (semverCompare ">=1.18-0" .Capabilities.KubeVersion.Version)) }}
    {{- if not (hasKey .Values.ingress.annotations "kubernetes.io/ingress.class") }}
    {{- $_ := set .Values.ingress.annotations "kubernetes.io/ingress.class" .Values.ingress.className }}
    {{- end }}
    {{- end }}
spec:
  {{- if and .Values.ingress.className (semverCompare ">=1.18-0" .Capabilities.KubeVersion.Version) }}
  ingressClassName: {{ .Values.ingress.className }}
  {{- end }}
```

Подробнее об адаптивных шаблонах: [Сценарии Helm](../../Advanced/scenarios.md).

---

## Дополнительная информация

- [Встроенные объекты Helm](../objects.md) — полный список свойств `.Capabilities`
- [Функции Helm](../functions.md) — справочник по функциям шаблонизации
- [Сценарии Helm](../../Advanced/scenarios.md) — продвинутые примеры адаптивных манифестов

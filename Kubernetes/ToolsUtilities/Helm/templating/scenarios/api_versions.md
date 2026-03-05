# Проверка API версий кластера

---

## Определения

**Объект .Capabilities** — встроенный объект для получения информации о возможностях кластера (версия Kubernetes, доступные API).

---

## Использование .Capabilities

Helm позволяет адаптировать манифесты под версию Kubernetes в кластере:

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

---

## Доступные проверки

- `.Capabilities.KubeVersion.Version` — версия Kubernetes
- `.Capabilities.KubeVersion.Major` — мажорная версия
- `.Capabilities.KubeVersion.Minor` — минорная версия
- `.Capabilities.APIVersions.Has "group/version"` — проверка доступности API

---

## Примеры

### Проверка версии K8s

```yaml
{{- if gt (semver .Capabilities.KubeVersion.Version | trimPrefix "v") "1.19" }}
# Логика для K8s 1.20+
{{- else }}
# Логика для старых версий
{{- end }}
```

### Проверка нескольких API

```yaml
{{- if and (.Capabilities.APIVersions.Has "networking.k8s.io/v1/Ingress") (.Capabilities.APIVersions.Has "metrics.k8s.io/v1beta1") }}
# Оба API доступны
{{- end }}
```

---

## Дополнительные ссылки

- [Встроенные объекты](../objects.md) — подробнее о .Capabilities
- [ helm_templating](../helm_templating.md) — обзорная страница

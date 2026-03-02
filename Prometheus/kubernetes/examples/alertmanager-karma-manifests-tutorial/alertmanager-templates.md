# Шаблоны сообщений Alertmanager

Создадим отдельный `ConfigMap` для Go-шаблонов, которые форматируют сообщения для Telegram и почты.

**`alertmanager-templates.yaml`**
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: alertmanager-templates
  namespace: monitoring
data:
  telegram.default.html.tmpl: |
    {{ define "telegram.default.html" }}
    <b>{{ .Status | toUpper }}</b>
    {{ range .Alerts }}
    <b>Alert:</b> {{ .Annotations.summary }}
    <b>Description:</b> {{ .Annotations.description }}
    <b>Severity:</b> {{ .Labels.severity }}
    {{ end }}
    {{ end }}
```

## Смотрите также

- [Конфигурация Alertmanager](./03-alertmanager-config.md) — подключение шаблонов
- [Alertmanager StatefulSet](./05-alertmanager-statefulset.md) — монтирование шаблонов

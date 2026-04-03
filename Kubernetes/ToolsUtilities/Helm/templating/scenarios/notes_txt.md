# NOTES.txt Post-Install Instructions

---

## Definitions

**NOTES.txt** — специальный шаблон в `templates/NOTES.txt`, содержимое которого рендерится и выводится в консоль после `helm install` или `helm upgrade`. Не создаёт Kubernetes-ресурсов.

---

## Basic Concepts

NOTES.txt — единственный файл в директории `templates/`, который **не рендерится в YAML-манифест**. Его вывод отображается пользователю как информационное сообщение.

### Особенности

- **Не создаёт ресурсы** — содержимое выводится в stdout, а не отправляется в Kubernetes API.
- **Полноценный шаблон** — поддерживает все конструкции Helm: `if/else`, `range`, `include`, функции.
- **Один файл** — Helm ожидает ровно один `templates/NOTES.txt`.
- **Подавление вывода** — пустой файл или `--no-hooks` не влияют; для подавления используется `helm install --render-subchart-notes` или удаление содержимого.

### Когда применять

| Сценарий | Содержание NOTES.txt |
|----------|---------------------|
| LoadBalancer | Команда `kubectl get svc -w` для ожидания IP |
| NodePort | URL с `kubectl port-forward` |
| ClusterIP | Инструкция по port-forward |
| Ingress | Список хостов и URL |
| Многокомпонентный чарт | Предупреждения о дополнительных шагах (миграции, секреты) |

---

## Practical Scenarios

### Базовый NOTES.txt с условной логикой

```
Thank you for installing {{ .Chart.Name }}.

Your release is named {{ .Release.Name }}.

To learn more about the release, try:

  $ helm status {{ .Release.Name }}
  $ helm get all {{ .Release.Name }}

{{- if .Values.ingress.enabled }}
{{- range .Values.ingress.hosts }}
  {{ .name }}:
    http://{{ .name }}
{{- end }}
{{- else if eq .Values.service.type "LoadBalancer" }}
  NOTE: It may take a few minutes for the LoadBalancer IP to be available.
  To watch the status, run:

  $ kubectl get svc -w {{ .Release.Name }}
{{- else if eq .Values.service.type "NodePort" }}
  To access your application:

  $ export NODE_PORT=$(kubectl get svc {{ .Release.Name }} -o jsonpath='{.spec.ports[0].nodePort}')
  $ export NODE_IP=$(kubectl get nodes -o jsonpath='{.items[0].status.addresses[0].address}')
  $ echo http://$NODE_IP:$NODE_PORT
{{- else }}
  To access your application:

  $ kubectl port-forward svc/{{ .Release.Name }} {{ .Values.service.port }}:{{ .Values.service.port }}
{{- end }}
```

### NOTES.txt с извлечением IP из Service

Получение реального IP LoadBalancer после деплоя:

```
{{- $svc := lookup "v1" "Service" .Release.Namespace (include "myapp.fullname" .) }}
{{- if and $svc (eq $svc.spec.type "LoadBalancer") }}
{{- $ip := index $svc.status.loadBalancer.ingress 0 }}
  Application URL: http://{{ $ip.ip }}
{{- else }}
  NOTE: LoadBalancer IP not yet assigned. Run:
  $ kubectl get svc {{ .Release.Name }} -w
{{- end }}
```

Функция `lookup` позволяет прочитать текущее состояние кластера во время рендеринга. Работает только при `helm install`/`upgrade`, не работает при `helm template`.

### NOTES.txt для многокомпонентного чарта

```
{{- $fullName := include "myapp.fullname" . -}}

Components installed:
  - Web Application: svc/{{ $fullName }}
{{- if .Values.redis.enabled }}
  - Redis: svc/{{ $fullName }}-redis
{{- end }}
{{- if .Values.postgresql.enabled }}
  - PostgreSQL: svc/{{ $fullName }}-postgresql
{{- end }}

{{- if .Values.postgresql.enabled }}

IMPORTANT: PostgreSQL password is stored in secret "{{ $fullName }}-postgresql".
Retrieve it with:

  $ kubectl get secret {{ $fullName }}-postgresql -o jsonpath='{.data.postgres-password}' | base64 -d
{{- end }}
```

### NOTES.txt с использованием именованных шаблонов

Определение блока заметок в `_helpers.tpl`:

```go
{{- define "myapp.notes" -}}
{{- if .Values.ingress.enabled -}}
Access the application via:
{{- range .Values.ingress.hosts }}
  - http://{{ .name }}
{{- end }}
{{- else }}
Run `kubectl port-forward svc/{{ include "myapp.fullname" . }} 8080:{{ .Values.service.port }}`
{{- end }}
{{- end }}
```

Использование в `NOTES.txt`:

```
{{ include "myapp.notes" . }}
```

---

## Additional Information

Синтаксис шаблонов — в [Синтаксис Helm-шаблонов](../syntax.md). Именованные шаблоны — в [Именованные шаблоны и хелперы](../_helpers.md). Функция `lookup` — в [Функции Helm](../functions.md).

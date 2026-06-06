# Инструкции NOTES.txt после установки

---

## Определения

**NOTES.txt** — специальный шаблон в директории `templates/NOTES.txt`, содержимое которого рендерится и выводится в CLI (Command Line Interface) после выполнения команд `helm install` или `helm upgrade`. Не создаёт ресурсов в Kubernetes.

---

## Базовые концепции

`NOTES.txt` — единственный файл в директории `templates/`, который **не рендерится в YAML (YAML Ain't Markup Language) манифест**. Его вывод отображается пользователю как информационное сообщение.

### Особенности

- **Не создаёт ресурсы** — содержимое выводится в стандартный поток вывода (stdout), а не отправляется в API (Application Programming Interface) Kubernetes.
- **Полноценный шаблон** — поддерживает все конструкции Helm: `if/else`, `range`, `include`, функции.
- **Один файл** — Helm ожидает ровно один файл `templates/NOTES.txt`.
- **Подавление вывода** — пустой файл или флаг `--no-hooks` не влияют на вывод заметок; для управления отображением в субчартах используется флаг `helm install --render-subchart-notes`.

### Когда применять

| Сценарий | Содержание NOTES.txt |
|----------|---------------------|
| LoadBalancer | Команда `kubectl get svc -w` для ожидания IP (Internet Protocol) адреса |
| NodePort | URL (Uniform Resource Locator) с использованием `kubectl port-forward` |
| ClusterIP | Инструкция по настройке port-forward |
| Ingress | Список хостов и внешних URL |
| Многокомпонентный чарт | Предупреждения о дополнительных шагах (миграции баз данных, секреты) |

---

## Практические сценарии

### Базовый NOTES.txt с условной логикой

```text
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

### NOTES.txt с извлечением IP из Service через lookup

Функция `lookup` позволяет прочитать текущее состояние кластера во время рендеринга. Работает только при `helm install`/`upgrade`, не работает при `helm template`.

```text
{{- $svc := lookup "v1" "Service" .Release.Namespace (include "myapp.fullname" .) }}
{{- if and $svc (eq $svc.spec.type "LoadBalancer") }}
{{- $ip := index $svc.status.loadBalancer.ingress 0 }}
  Application URL: http://{{ $ip.ip }}
{{- else }}
  NOTE: LoadBalancer IP not yet assigned. Run:
  $ kubectl get svc {{ .Release.Name }} -w
{{- end }}
```

### NOTES.txt для многокомпонентного чарта

Вывод информации о компонентах и способах получения паролей из секретов:

```text
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

Использование в файле `NOTES.txt`:

```text
{{ include "myapp.notes" . }}
```

---

## Дополнительная информация

- [Синтаксис Helm-шаблонов](../syntax.md) — базовые конструкции `if/else` и `range`
- [Именованные шаблоны и хелперы](../_helpers.md) — работа с `define` и `include`
- [Функции Helm](../functions.md) — подробнее о функции `lookup`
- [Обзор сценариев шаблонизации](./overview.md) — оглавление практических примеров

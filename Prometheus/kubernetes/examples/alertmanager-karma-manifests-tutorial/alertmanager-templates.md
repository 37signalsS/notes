# Шаблоны сообщений Alertmanager (Go Templates)

## Определения

**Go-шаблоны Alertmanager** — файлы с расширением `.tmpl`, содержащие шаблоны на языке Go template для форматирования уведомлений перед отправкой в каналы (Telegram, Email, Slack, PagerDuty). Подключаются в `alertmanager.yml` через блок `templates` и вызываются через `{{ template "имя.шаблона" . }}`.

## Основные концепции

### Как работают шаблоны в Alertmanager

| Этап | Описание |
|---|---|
| **1. Подключение** | Блок `templates: ['/etc/alertmanager/templates/*.tmpl']` в `alertmanager.yml` загружает все `.tmpl`-файлы |
| **2. Определение** | Каждый `.tmpl` содержит один или несколько `{{ define "имя" }}...{{ end }}` блоков |
| **3. Вызов** | В `receiver_configs` указывается `message: '{{ template "имя" . }}'` |

### Доступные данные в шаблоне

| Объект | Тип | Описание |
|---|---|---|
| `.Status` | `string` | Статус группы: `firing` или `resolved` |
| `.Alerts` | `[]Alert` | Список алертов в группе |
| `.CommonLabels` | `map[string]string` | Метки, общие для всех алертов |
| `.GroupLabels` | `map[string]string` | Метки группировки |
| `.Annotations` | `map[string]string` | Аннотации из alert rule (summary, description) |

### Особенности форматирования для Telegram

- Telegram поддерживает **HTML** и **MarkdownV2** — требуется `parse_mode: 'HTML'` или `parse_mode: 'MarkdownV2'`
- Для HTML-режима: используйте теги `<b>`, `<i>`, `<code>`, `<a href="...">`
- Для MarkdownV2: экранируйте спецсимволы (`_`, `*`, `[`, `]`, `(`, `)`, `~`, `` ` ``, `>`, `#`, `+`, `-`, `=`, `|`, `{`, `}`, `.`, `!`)

## Практические сценарии

### ConfigMap с шаблоном для Telegram/HTML

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

### Разбор шаблона

| Конструкция | Назначение |
|---|---|
| `{{ define "telegram.default.html" }}` | Именованный блок шаблона — вызывается из `message` в `telegram_configs` |
| `.Status \| toUpper` | Статус группы (`firing`/`resolved`) в верхнем регистре — **FIRING** / **RESOLVED** |
| `{{ range .Alerts }}` | Итерация по всем алертам в группе |
| `.Annotations.summary` | Краткое описание из alert rule |
| `.Annotations.description` | Развёрнутое описание из alert rule |
| `.Labels.severity` | Метка severity (critical, warning, info) |

### Подключение шаблона в Alertmanager

Шаблон подключается в `alertmanager-config.md`:

```yaml
templates:
  - '/etc/alertmanager/templates/*.tmpl'
```

А в `telegram_configs` вызывается через:

```yaml
telegram_configs:
  - bot_token: '##TELEGRAM_TOKEN##'
    chat_id: ##TELEGRAM_CHAT_ID##
    parse_mode: 'HTML'
    message: '{{ template "telegram.default.html" . }}'
```

### Расширенный шаблон с ссылками

Для добавления ссылки на Grafana/Prometheus:

```go
{{ define "telegram.default.html" }}
<b>{{ .Status | toUpper }: {{ .GroupLabels.alertname }}</b>
{{ range .Alerts }}
<b>Alert:</b> {{ .Annotations.summary }}
<b>Instance:</b> {{ .Labels.instance }}
<b>Severity:</b> {{ .Labels.severity }}
<b>Runbook:</b> {{ .Annotations.runbook_url }}
{{ end }}
{{ end }}
```

### Монтирование в StatefulSet

В `alertmanager-statefulset.md` ConfigMap монтируется как `readOnly`:

```yaml
volumeMounts:
  - name: templates
    mountPath: /etc/alertmanager/templates
    readOnly: true
```

## Дополнительная информация

- [ConfigMap-шаблон](./alertmanager-config.md) — блок `templates` в конфигурации Alertmanager
- [Alertmanager StatefulSet](./alertmanager-statefulset.md) — монтирование ConfigMap с шаблонами в под
- [Секреты Kubernetes](./secrets.md) — токены и пароли для получателей уведомлений

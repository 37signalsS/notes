# Шаблоны сообщений Alertmanager: Go Templates

## Определения

**Go-шаблоны Alertmanager** — файлы с расширением `.tmpl`, содержащие логику форматирования уведомлений на языке Go template. Они позволяют настраивать визуальное представление алертов для различных каналов доставки (Telegram, Email, Slack). Подключаются в `alertmanager.yml` через блок `templates` и вызываются через функцию `{{ template "имя" . }}`.

> **См. также:** [Правила и шаблоны в Alertmanager](../../rules.md).

---

## Основные концепции

### Механизм работы шаблонов

| Этап | Описание |
| :--- | :--- |
| **Подключение** | Блок `templates: ['/etc/alertmanager/templates/*.tmpl']` загружает файлы в память процесса. |
| **Определение** | Внутри файла используются блоки `{{ define "имя.шаблона" }}...{{ end }}`. |
| **Вызов** | В конфигурации ресивера указывается ссылка на имя шаблона в поле `message`. |

### Структура данных (Pipeline)

В шаблоны передается объект, содержащий:
*   `.Status`: Состояние группы (`firing` или `resolved`).
*   `.Alerts`: Массив всех активных оповещений в данной группе.
*   `.GroupLabels`: Метки, по которым произошла группировка.
*   `.Annotations`: Описания и ссылки из правил сбора (Alert Rules).

---

## Практические сценарии

### Шаблон для Telegram (HTML)

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

### Подключение и вызов

В файле `alertmanager.yml` (через ConfigMap):

```yaml
receivers:
  - name: 'telegram-receiver'
    telegram_configs:
      - bot_token: '${TELEGRAM_TOKEN}'
        chat_id: ${TELEGRAM_CHAT_ID}
        parse_mode: 'HTML'
        message: '{{ template "telegram.default.html" . }}'
```

---

## Дополнительная информация

- **[Конфигурация (ConfigMap)](./alertmanager-config.md)** — блок `templates` в настройках.
- **[Манифест StatefulSet](./alertmanager-statefulset.md)** — монтирование файлов шаблонов.
- **[Секреты Kubernetes](./secrets.md)** — токены для доступа к API Telegram.
- **[Reliability Scores](../../../../GEMINI.md)** — методология оценки достоверности (Score: 10).

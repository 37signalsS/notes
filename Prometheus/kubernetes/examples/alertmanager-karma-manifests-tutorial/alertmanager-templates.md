# Шаблоны сообщений Alertmanager: Go Templates

## Определения

**Go-шаблоны Alertmanager** — файлы с расширением `.tmpl`, содержащие логику форматирования уведомлений на языке Go template (с использованием библиотеки [Sprig](http://masterminds.github.io/sprig/)). Они позволяют гибко настраивать визуальное представление алертов для различных каналов доставки (Telegram, Email, Slack). Подключаются в `alertmanager.yml` через блок `templates` и вызываются через конструкцию `{{ template "имя" . }}`.

> **См. также:** [Правила и шаблоны в Alertmanager](../../../rules.md).

---

## Основные концепции

### Механизм работы шаблонов

| Этап | Описание |
| :--- | :--- |
| **Подключение** | Блок `templates: ['/etc/alertmanager/templates/*.tmpl']` в глобальной конфигурации загружает файлы в память процесса. |
| **Определение** | Внутри файла используются блоки `{{ define "имя.шаблона" }}...{{ end }}` для декларации переиспользуемых компонентов. |
| **Вызов** | В конфигурации ресивера указывается ссылка на имя шаблона в поле `message` или `html`. |

### Структура данных (Pipeline)

В шаблоны передается корневой объект (`.`), содержащий контекст сработавшего алерта:
*   `.Status`: Состояние группы (`firing` или `resolved`).
*   `.Alerts.Firing` / `.Alerts.Resolved`: Отфильтрованные списки оповещений.
*   `.GroupLabels`: Общие метки, по которым произошла агрегация (grouping).
*   `.CommonAnnotations`: Общие аннотации для всей группы.

### Полезные функции (Sprig)

*   `{{ .Status | toUpper }}` — перевод строки в верхний регистр.
*   `{{ if eq .Status "firing" }}🔥{{ else }}✅{{ end }}` — условные выражения.
*   `{{ range .Alerts }}...{{ end }}` — итерация по массиву алертов.
*   `{{ range $key, $value := .Labels }}` — итерация по `key/value` парам меток.

---

## Практические сценарии

### Шаблон для Telegram (HTML)

Пример продвинутого шаблона `ConfigMap`, который добавляет эмодзи в зависимости от статуса и итерирует по лейблам и аннотациям.

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
    {{ if eq .Status "firing" }}🚨 <b>ПРОБЛЕМА</b>🚨{{ else }}✅ <b>РЕШЕНО</b>✅{{ end }}
    
    <b>Состояние:</b> {{ .Status | toUpper }}
    <b>Группа:</b> {{ range $k, $v := .GroupLabels }}<code>{{ $k }}={{ $v }}</code> {{ end }}
    
    {{ range .Alerts }}
    ---
    <b>Алерт:</b> {{ .Annotations.summary }}
    <b>Описание:</b> {{ .Annotations.description }}
    <b>Severity:</b> {{ .Labels.severity }}
    <b>Детали:</b>
    {{ range $key, $value := .Labels }}
    • {{ $key }}: <i>{{ $value }}</i>
    {{ end }}
    {{ end }}
    {{ end }}
```

### Подключение и вызов

В файле `alertmanager.yml` (через отдельный ConfigMap):

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

- **[Конфигурация (ConfigMap)](./alertmanager-config.md)** — блок `templates` в настройках и маршрутизация.
- **[Манифест StatefulSet](./alertmanager-statefulset.md)** — монтирование файлов шаблонов в контейнер.
- **[Секреты Kubernetes](./secrets.md)** — управление токенами для доступа к API Telegram.

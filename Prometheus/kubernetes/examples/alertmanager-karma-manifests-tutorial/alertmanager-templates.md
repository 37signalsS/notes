# Шаблоны сообщений Alertmanager: Go Templates

## Определения

**Go-шаблоны Alertmanager** — файлы с расширением `.tmpl`, содержащие логику форматирования уведомлений на языке Go template (с использованием библиотеки [Sprig](http://masterminds.github.io/sprig/)). Они позволяют гибко настраивать визуальное представление алертов для различных каналов доставки (Telegram, Email, Slack). Подключаются в `alertmanager.yml` через блок `templates` и вызываются через конструкцию `{{ template "имя" . }}`.

> **См. также:** [Правила и шаблоны в Alertmanager](../../../rules.md).

---

## Предварительные требования

Перед созданием и применением кастомных шаблонов убедитесь, что:

- Namespace `monitoring` существует.
- Alertmanager развернут и работает (`kubectl get pods -n monitoring -l app=alertmanager`).
- Подготовлен ConfigMap с конфигурацией `alertmanager.yml` (см. [Конфигурация Alertmanager](./alertmanager-config.md)).
- Secret с токенами для каналов доставки создан (см. [Секреты Kubernetes](./secrets.md)).
- Файлы шаблонов будут храниться в отдельном ConfigMap `alertmanager-templates` и монтироваться в `/etc/alertmanager/templates` (см. [Манифест StatefulSet](./alertmanager-statefulset.md)).

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
*   `.CommonLabels`: Общие метки для всей группы.
*   `.ExternalURL`: Внешний URL, через который доступен Alertmanager (используется для генерации ссылок в уведомлениях).

### Доступные функции (Sprig)

Библиотека [Sprig](http://masterminds.github.io/sprig/) предоставляет более 70 функций для работы со строками, датами, коллекциями и т.д.:

*   `{{ .Status | toUpper }}` — перевод строки в верхний регистр.
*   `{{ if eq .Status "firing" }}[FIRING]{{ else }}[RESOLVED]{{ end }}` — условные выражения.
*   `{{ range .Alerts }}...{{ end }}` — итерация по массиву алертов.
*   `{{ range $key, $value := .Labels }}` — итерация по `key/value` парам меток.
*   `{{ now | date "2006-01-02 15:04:05" }}` — форматирование текущей даты.
*   `{{ .Alerts | len }}` — получение количества алертов в группе.
*   `{{ .Annotations.description | trunc 100 }}` — обрезка строки до указанной длины.
*   `{{ $val | default "N/A" }}` — значение по умолчанию, если переменная пустая.

### Соглашения по именованию

Рекомендуется использовать префикс с именем канала или receiver для избежания конфликтов:

```
telegram.default.html
telegram.default.text
email.default.subject
email.default.html
slack.default.text
```

### Встроенные шаблоны

Alertmanager поставляется с набором встроенных шаблонов, которые используются по умолчанию, если не указан кастомный. При загрузке пользовательских файлов из ConfigMap они переопределяют встроенные для соответствующих имен. При проблемах с отображением проверяйте, что имена шаблонов совпадают с вызовами в конфигурации.

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
    {{ if eq .Status "firing" }}[ALERT] <b>ПРОБЛЕМА</b>[ALERT]{{ else }}[OK] <b>РЕШЕНО</b>[OK]{{ end }}
    
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

### Шаблон для Email (HTML)

Пример шаблона для email-уведомлений с табличным оформлением.

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: alertmanager-templates
  namespace: monitoring
data:
  email.default.html.tmpl: |
    {{ define "email.default.html" }}
    <!DOCTYPE html>
    <html>
    <body style="font-family: Arial, sans-serif;">
    <h2 style="color: {{ if eq .Status "firing" }}#cc0000{{ else }}#00aa00{{ end }};">
      {{ if eq .Status "firing" }}ПРОБЛЕМА{{ else }}РЕШЕНО{{ end }}
    </h2>
    <p><b>Статус:</b> {{ .Status | toUpper }}</p>
    <p><b>Группа:</b> {{ range $k, $v := .GroupLabels }}{{ $k }}={{ $v }} {{ end }}</p>
    <table border="1" cellpadding="6" cellspacing="0">
    <tr style="background-color: #f2f2f2;">
      <th>Алерт</th><th>Severity</th><th>Описание</th><th>Инстанс</th>
    </tr>
    {{ range .Alerts }}
    <tr>
      <td>{{ .Annotations.summary }}</td>
      <td>{{ .Labels.severity }}</td>
      <td>{{ .Annotations.description }}</td>
      <td>{{ .Labels.instance }}</td>
    </tr>
    {{ end }}
    </table>
    <hr/>
    <small>Alertmanager · {{ now | date "2006-01-02 15:04:05" }}</small>
    </body>
    </html>
    {{ end }}
```

### Подключение и вызов

В файле `alertmanager.yml` (через отдельный ConfigMap):

```yaml
global:
  templates:
    - '/etc/alertmanager/templates/*.tmpl'

receivers:
  - name: 'telegram-receiver'
    webhook_configs:
      - url: 'http://alertmanager-bot:9090/alert'
        send_resolved: true
        message: '{{ template "telegram.default.html" . }}'

  - name: 'email-receiver'
    email_configs:
      - to: 'ops@example.com'
        from: 'alertmanager@example.com'
        smarthost: 'smtp.example.com:587'
        html: '{{ template "email.default.html" . }}'
```

### Применение и первичная валидация

```bash
# Создание ConfigMap с шаблонами
kubectl apply -f alertmanager-templates.yaml -n monitoring

# Проверка создания
kubectl get configmap alertmanager-templates -n monitoring -o yaml

# Проверка, что ConfigMap смонтирован в StatefulSet
kubectl describe statefulset alertmanager -n monitoring | grep -A5 "Volumes:"

# Проверка наличия файлов в подах
kubectl exec -n monitoring alertmanager-0 -- ls -la /etc/alertmanager/templates/
# → telegram.default.html.tmpl
# → email.default.html.tmpl
```

### Проверка шаблонов изнутри пода

```bash
# Получение имени пода
kubectl get pods -n monitoring -l app=alertmanager

# Просмотр смонтированного файла
kubectl exec -n monitoring alertmanager-0 -- cat /etc/alertmanager/templates/telegram.default.html.tmpl

# Проверка логов на ошибки парсинга шаблонов
kubectl logs -n monitoring alertmanager-0 -c alertmanager | grep -i "template\|parse\|error"
# → (пусто, если ошибок нет)

# Проверка статуса пода
kubectl get pods -n monitoring -l app=alertmanager
# → NAME            READY   STATUS    RESTARTS   AGE
# → alertmanager-0  2/2     Running   0          10m
```

### Горячая перезагрузка после изменения шаблонов

После обновления ConfigMap `alertmanager-templates` требуется перезагрузка Alertmanager:

```bash
# Через SIGHUP (требует exec в контейнер)
POD=$(kubectl get pods -n monitoring -l app=alertmanager -o jsonpath='{.items[0].metadata.name}')
kubectl exec -n monitoring $POD -c alertmanager -- kill -SIGHUP 1

# Или через HTTP API
kubectl port-forward -n monitoring svc/alertmanager 9093:9093 &
curl -X POST http://localhost:9093/-/reload
# → "Alert configuration reloaded"

# Проверка логов
kubectl logs -n monitoring $POD -c alertmanager | tail -5
```

### Валидация шаблонов

```bash
# Проверка валидности Go-шаблона через утилиту go-template
echo '{{ define "test" }}{{ .Status | toUpper }}{{ end }}' | go run github.com/alecthomas/go-template@latest

# Проверка через Alertmanager API (если конфигурация загружена)
kubectl port-forward -n monitoring svc/alertmanager 9093:9093 &
curl -s http://localhost:9093/-/status/config | grep -A5 "templates:"
```

### Отладка синтаксических ошибок

При ошибках парсинга шаблонов Alertmanager логирует сообщения вида:

```
template: telegram.default.html:4: unexpected "}" in operand
```

**Диагностика:**

```bash
# 1. Получить логи пода
kubectl logs -n monitoring $POD -c alertmanager | grep -i "template"

# 2. Проверить синтаксис шаблона локально
# Установите go-template или используйте онлайн-валлидатор

# 3. Проверить, что ConfigMap смонтирован корректно
kubectl exec -n monitoring $POD -- mount | grep templates
# → /etc/alertmanager/templates on /var/lib/kubelet/pods/.../volumes/... type tmpfs (ro,...)

# 4. Проверить права на файлы
kubectl exec -n monitoring $POD -- ls -la /etc/alertmanager/templates/
# → должны быть readable для пользователя alertmanager
```

### Управление через amtool

```bash
# Просмотр активных алертов (проверка, что алерты доходят до Alertmanager)
amtool --alertmanager.url=http://alertmanager.monitoring:9093 alert

# Создание сайленса (временное отключение алерта для тестирования)
amtool --alertmanager.url=http://alertmanager.monitoring:9093 silence add \
  --duration=1h \
  --comment="Тестирование шаблона" \
  --matcher="severity=critical" \
  --matcher="alertname=NodeDown"

# Просмотр активных сайленсов
amtool --alertmanager.url=http://alertmanager.monitoring:9093 silence

# Удаление сайленса
amtool --alertmanager.url=http://alertmanager.monitoring:9093 silence expire <silence_id>
```

---

## Рекомендации

*   **Версионирование:** Храните ConfigMap `alertmanager-templates` в Git alongside с `alertmanager-config` и манифестами инфраструктуры. Это позволяет отслеживать изменения шаблонов и быстро откатываться при проблемах.
*   **Immutable ConfigMap:** Используйте immutable ConfigMap для шаблонов, если изменения происходят только через GitOps. Это предотвращает случайные локальные модификации.
*   **Labels в receivers:** Добавляйте `continue: true` в маршруты, если требуется доставка в несколько каналов одновременно. Без этого флага доставка прекращается на первом совпадении.
*   **Область видимости переменных:** Переменные окружения `${TELEGRAM_TOKEN}` подставляются только в блоке `global` конфигурации Alertmanager. Внутри Go-шаблонов они недоступны — используйте аннотации Prometheus для передачи данных.
*   **CHANGELOG:** Ведите лог изменений шаблонов. При каждом изменении указывайте, какой receiver и канал был затронут.
*   **Routing Tree Editor:** Используйте [Routing Tree Editor](https://www.prometheus.io/webtools/alerting/routing-tree-editor/) для визуализации маршрутизации и проверки, что алерты доходят до нужных receivers.
*   **Тестирование:** Создавайте тестовые алерты через `promtool` или `amtool` для проверки отображения шаблонов перед применением в production.

---

## Очистка ресурсов

```bash
# Удалить ConfigMap с шаблонами
kubectl delete configmap alertmanager-templates -n monitoring

# Проверить отсутствие
kubectl get configmap alertmanager-templates -n monitoring
# → Error from server (NotFound): configmaps "alertmanager-templates" not found

# Примечание: StatefulSet и Secret не удаляются при удалении ConfigMap.
# При необходимости полностью очистить namespace:
kubectl delete -f alertmanager-statefulset.yaml -n monitoring
kubectl delete -f secrets.yaml -n monitoring
```

---

## Дополнительная информация

- **[Конфигурация (ConfigMap)](./alertmanager-config.md)** — блок `templates` в настройках и маршрутизация.
- **[Манифест StatefulSet](./alertmanager-statefulset.md)** — монтирование файлов шаблонов в контейнер.
- **[Секреты Kubernetes](./secrets.md)** — управление токенами для доступа к API Telegram.
- **[Alertmanager — управление оповещениями](../../../alertmanager.md)** — общая справка по конфигурации и архитектуре Alertmanager.

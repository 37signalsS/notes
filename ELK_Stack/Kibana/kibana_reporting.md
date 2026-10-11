# Kibana: Reporting

> **Актуально для:** Kibana 8.19 / 9.x (scheduled reports — с 9.1)

Reporting подсистема Kibana генерирует PDF, PNG и CSV из дашбордов, визуализаций, Canvas workpads и Discover-сессий. PDF/PNG — платная возможность (subscription), PDF/PNG недоступны в Elastic Cloud Serverless; CSV доступен всем.

## Определения

* **Reporting** — подсистема Kibana, выполняющая экспорт контента в файл. Генерация выполняется на сервере Kibana как фоновая задача (background task), результат очереди хранится в Elasticsearch.
* **POST URL** — адрес вида `/api/reporting/generate/<exportType>?jobParams=...`, на который отправляется HTTP POST для запуска генерации из скрипта или Watcher. Параметры `jobParams` кодируются Rison (сжатый JSON).
* **Export type** — тип экспорта, определяющий формат и источник: `printablePdfV2` (PDF), PNG, `csv` (CSV из Discover-сессии). В коде также различают `csv_searchsource`, `csv_v2`.
* **Scheduled report** — отчёт по расписанию, создаваемый в Kibana и доставляемый по email; выполняется через Task Manager.
* **Screenshotting** — внутренний плагин Kibana, управляющий headless Chromium: он открывает страницу Kibana и делает снимок. Для PDF/PNG обязателен; для CSV не используется.
* **Network policy** — белый список (`xpack.screenshotting.networkPolicy.rules`) для запросов, которые headless-браузер может отправлять при рендере страницы.
* **Хранилище отчётов** — data stream `.kibana-reporting*` (index template и component template называются `.kibana-reporting` / `kibana-reporting@custom`); в старых версиях отчёты лежали в индексах `.reporting-*`. Жизненный цикл данных управляет встроенная ILM-политика `kibana-reporting`.
* **Job (задача)** — единица работы в очереди; статусы: `pending` → `processing` → `completed` | `failed`. Хранится в Elasticsearch, что позволяет отслеживать состояние из нескольких инстансов Kibana.

## Основные концепции

### Как устроена генерация

1. Запрос на `/api/reporting/generate/...` создаёт задачу (job) и записывает её в хранилище reporting (data stream `.kibana-reporting*`) в Elasticsearch.
2. Одна или несколько инстанс Kibana опрашивают очередь (`xpack.reporting.queue.pollInterval`, по умолчанию `3s`) и забирают задачу на исполнение: статус меняется с `pending` на `processing`.
3. Задача выполняется в фоновом планировщике; для CSV это поиск с постраничной выгрузкой, для PDF/PNG — запуск Chromium и снимок страницы. В Task Manager reporting-задачи выполняются **по одной за раз**.
4. Статус становится `completed` (или `failed` после исчерпания повторов); результат скачивается GET-запросом по адресу из поля `path` ответа (`/api/reporting/jobs/download/<job-id>`).

Аутентификация запросов на генерацию выполняется **API keys, а не session cookie** (GA с 9.1): API key несёт привилегии роли (role privileges), а не только учётные данные пользователя, и живёт дольше короткоживущей cookie — поэтому automation не рассыпается при истечении сессии. В curl-примерах официальной документации используется basic auth (`-u user:password`).

### Доступ и привилегии

Права выдаются через **Kibana application privileges** (feature privileges), а не через роль `reporting_user`:

* Настройка `xpack.reporting.roles.enabled` (доступна в 7.14–9.0) управляла legacy-моделью на основе роли `reporting_user`; она **удалена в 9.0** — доступ теперь определяется исключительно application privileges.
* Типовые feature privileges: `generate_report` (генерация PDF/PNG) и `download_csv_report` (CSV); выдаются для приложений `dashboard_v2`, `discover_v2`, `visualize_v2`, `canvas` (в примере role API из документации CSV-привилегия указана у `dashboard_v2`).
* На **Basic-лицензии** суб-привилегии (sub-feature privileges) недоступны — в роли нужно выбирать `All` для приложения целиком.
* Для CSV по index-алиасам нужны права `read` и `view_index_metadata` на лежащие в основе индексы (для стратегии `pit` — права на сами индексы/data stream'ы).
* Чтобы управлять чужими отчётами и расписаниями (а не только своими), нужна привилегия **Manage Scheduled Reports**; без неё можно отправлять отчёты только себе.
* Привилегия на генерацию даёт и право видеть свои отчёты в разделе Reporting; пользователи видят только свои отчёты.

### Очередь и фоновые задачи

* `xpack.reporting.queue.pollEnabled: true` (по умолчанию) — инстанс забирает задачи из очереди. Значение `false` делает инстанс «только UI»: он создаёт задачи, листает их и отдаёт готовые файлы, но не исполняет — так разгружают выделенные UI-узлы за балансировщиком.
* Выполнение reporting-задач планируется через Task Manager; reporting-задачи выполняются **по одной за раз** на инстанс, поэтому при многих расписаниях отчёты отправляются с опозданием — конкуренция с правилами alerting и прочими scheduled-задачами описана в [Alerting](../Elasticsearch/elasticsearch_alerting.md).
* `xpack.reporting.queue.indexInterval` (deprecated с 8.15) не используется: ротация данных отчётов управляется встроенной ILM-политикой `kibana-reporting` (в stateful-деплоиментах; настройки lifecycle переопределяются через component template `kibana-reporting@custom`).
* Общая HA-схема (одинаковые ключи за балансировщиком, выделенные background-узлы `node.roles: [background_tasks]`) — в [Эксплуатация в production](./kibana_production_operations.md).

## Практические сценарии

### Предварительные требования

* Для PDF/PNG: минимум **2 ГБ RAM** на инстанс Kibana (для CSV требования к RAM нет); при нехватке памяти отчёт падает с `Error: Page crashed!`.
* Роль с feature privileges на reporting.
* Для scheduled reports — лицензия из набора: trial, standard (Cloud), gold, platinum, enterprise (константа `SCHEDULED_REPORT_VALID_LICENSES` в исходниках). **Basic-лицензия не подходит.**
* Для scheduled reports по email нужен default preconfigured email connector (см. раздел «Scheduled reports»).
* Elasticsearch должен устанавливать встроенные шаблоны: `stack.templates.enabled: true` (значение по умолчанию) — на нём Reporting держит mapping template своего data stream'а.

**OS-зависимости headless Chromium** (self-managed; в Docker-образе уже учтены):

```bash
# RHEL/CentOS
sudo yum install xorg-x11-fonts-100dpi xorg-x11-fonts-75dpi xorg-x11-utils \
  xorg-x11-fonts-cyrillic xorg-x11-fonts-Type1 xorg-x11-fonts-misc \
  vlgothic-fonts fontconfig freetype

# Ubuntu/Debian (минимум: библиотеки NSS + шрифты)
sudo apt-get install fonts-liberation libfontconfig1 libnss3
```

Также необходимы пакеты Network Security Service (NSS) и хотя бы один пакет со шрифтами: без шрифтов подписи панелей выводятся пустыми прямоугольниками, для CJK-символов нужен шрифт с этими глифами. Ограничения среды: **SELinux и fapolicyd не поддерживаются**, Linux-версии в стадии EOL не поддерживаются; Chromium использует user namespaces (ядро ≥ 3.8) — если sandbox не отключён явно и namespaces недоступны, Chromium падает при инициализации. Перед апгрейдом в production проверяйте сценарии PDF/PNG на pre-production — зависимости Chromium меняются между релизами.

### Настройки server.host для headless-браузера

Chromium открывает Kibana по локальному интерфейсу. В production предпочтительно:

```yaml
server.host: "0.0.0.0"   # браузер достучится по локальному адресу, снаружи слушает все интерфейсы
```

При `connection refused` / `unable to connect` проверьте именно этот параметр и файрвол: локальным сервисам должен быть доступен адрес, на котором слушает Kibana.

### Генерация через POST URL

```bash
# CSV: очередь генерации, затем скачивание
curl -XPOST \
  -u elastic:$PASSWORD \
  -H 'kbn-xsrf: true' \
  'https://kibana.example.com:5601/api/reporting/generate/csv?jobParams=...'
# → {"path":"/api/reporting/jobs/download/jxzaofkc0ykpf4062305t068",
#    "job":{"id":"...","jobtype":"csv","created_by":"elastic","timeout":120000,"max_attempts":3}}

# Скачивание готового отчёта
curl -u elastic:$PASSWORD -OJ \
  'https://kibana.example.com:5601/api/reporting/jobs/download/jxzaofkc0ykpf4062305t068'
```

* `kbn-xsrf` — обязательный заголовок для всех POST-запросов к Kibana; без него (или с не-POST методом) Kibana вернёт **400**.
* `jobParams` — Rison-кодированные параметры отчёта (источник, колонки, часовой пояс); удобнее всего скопировать из UI через «Copy POST URL»: Dashboards/Visualize → Export → Copy POST URL, Discover → Export → CSV / Share → Export, Canvas → Share → PDF Reports → Advanced options.
* Параметр `&sync` (держал запрос до готовности файла) **больше не поддерживается** — не используйте его в скриптах и Watcher.
* **Deprecated URL объектов** (`/api/reporting/generate/dashboard/<id>`, `/api/reporting/generate/visualization/<id>`, `/api/reporting/generate/search/<session-id>`) — после апгрейда Kibana они могут перестать работать; пересоздайте POST URL из UI.

**HTTP-коды для автоматизации** (генерация асинхронна: 200 означает лишь успешную постановку в очередь):

| Код | Значение | Действие в скрипте |
| :--- | :--- | :--- |
| `200` | Задача поставлена в очередь / файл скачан | Для генерации — перейти к опросу `path` |
| `400` | Не POST-метод или нет `kbn-xsrf` | Исправить запрос |
| `503` | Скачивание до готовности файла; в ответе заголовок `Retry-After` | Подождать указанное число секунд и повторить |
| `500` | Генерация завершилась ошибкой | Смотреть статус в Stack Management → Reporting и логи Kibana |

```bash
# Ожидание готовности: 200 — готово, 503 — ещё генерируется, 500 — ошибка
while :; do
  code=$(curl -s -o report.csv -w '%{http_code}' -u elastic:$PASSWORD \
    'https://kibana.example.com:5601/api/reporting/jobs/download/<job-id>')
  case $code in
    200) break ;;           # файл сохранён в report.csv
    503) sleep 5 ;;         # не готов; точное значение — в заголовке Retry-After
    *)   echo "report failed: HTTP $code"; exit 1 ;;
  esac
done
```

### Watcher: email-вложение с отчётом

```bash
PUT _watcher/watch/error_report
{
  "trigger": { "schedule": { "interval": "1h" } },
  "actions": {
    "email_admin": {
      "email": {
        "to": "'Recipient Name recipient@example.com'",
        "subject": "Error Monitoring Report",
        "attachments": {
          "error_report.pdf": {
            "reporting": {
              "url": "https://kibana.example.com:5601/api/reporting/generate/printablePdfV2?jobParams=...",
              "retries": 40,
              "interval": "15s",
              "auth": {
                "basic": { "username": "elastic", "password": "changeme" }
              }
            }
          }
        }
      }
    }
  }
}
```

Watcher опрашивает URL до `retries` раз (по умолчанию `40`) с интервалом `interval` (по умолчанию `15s`), пока файл не готов. Reporting интегрирован с Watcher **только как тип вложения email-действия**; аккаунт email настраивается отдельно — см. [Alerting и Watcher](../Elasticsearch/elasticsearch_alerting.md).

**Self-managed: доверие TLS.** Elasticsearch должен доверять сертификату Kibana, иначе Watcher не сможет скачать отчёт по https. Укажите CA в `elasticsearch.yml`:

```yaml
# PEM-цепочка (или truststore: xpack.http.ssl.truststore.path/type/password)
xpack.http.ssl.certificate_authorities: ["/path/to/kibana-ca.pem"]
```

**Ловушки `jobParams`:** дата-math-выражения в URL содержат фигурные скобки `{}`, из-за которых watch падает с `parse_exception` — убирайте скобки и URL-кодируйте выражение. После апгрейда пересоздавайте POST URL из UI, если watch перестал получать отчёт.

### Scheduled reports

> Функция появилась в Kibana 9.1 — в 8.19 расписания отчётов недоступны.

* UI: **Stack Management → Reporting** — `/app/management/insightsAndAlerting/reporting`; расписания — `/app/management/insightsAndAlerting/reporting/schedules`.
* Создание: открыть дашборд/визуализацию/saved Discover session → Export → Schedule export; задаются дата старта, часовой пояс расписания, периодичность и (опционально) отправка по email (To/Cc/Bcc, тема и текст с поддержкой Markdown и Mustache-шаблонов).
* Генерация запускается по расписанию через Task Manager, результат отправляется по email. Reporting-задачи в Task Manager выполняются по одной, поэтому кучное расписание отчётов даёт отправки с опозданием.
* Лицензии (константа `SCHEDULED_REPORT_VALID_LICENSES` в исходниках): `trial`, `standard`, `gold`, `platinum`, `enterprise` — без `basic`.

**Предпосылка — email connector.** Шаринг отчётов за пределы Kibana требует default preconfigured email connector. На self-managed он задаётся только в `kibana.yml` (через UI preconfigured-коннектор не создаётся):

```yaml
xpack.actions.preconfigured:
  my-email:
    name: my-email
    actionTypeId: .email
    config:
      service: other          # или встроенный провайдер
      from: reports@example.com
      host: smtp.example.com
      port: 587
      secure: false
      hasAuth: true
    secrets:
      user: reports@example.com
      password: "<пароль SMTP>"

notifications.connectors.default.email: my-email   # сделать коннектор дефолтным для email
# Опционально: кому разрешено слать письма
xpack.actions.email.domain_allowlist: ["example.com"]
```

**Управление расписаниями** (вкладка Schedules): disable (расписание выключается, запись остаётся), enable, edit, delete (удаление невосстановимо). Привилегия **Manage Scheduled Reports** нужна, чтобы видеть и менять чужие расписания и слать отчёты другим адресатам; без неё — только отчёты самому себе.

**Ограничения scheduled reports:**

* Вложение письма ограничено **10 МБ** — Kibana может не прикрепить отчёт крупнее.
* Расписание Canvas workpad'ов не поддерживается (Canvas в режиме maintenance mode), расписание CSV из Lens не поддерживается.
* Много расписаний на одно время + прочие Task Manager-задачи (alerting, индексы) → отправки с опозданием: следите за нагрузкой Task Manager ([Monitoring Kibana](./kibana_overview.md)).

### Ключевые настройки (kibana.yml)

```yaml
# Включить reporting (true по умолчанию; отключение не рекомендуется —
# ограничивайте доступ через роли и Spaces)
xpack.reporting.enabled: true

# Статический ключ шифрования: без него при каждом старте генерируется
# случайный, и НЕЗАВЕРШЁННЫЕ отчёты падают после рестарта.
# На всех инстансах за LB ключи ДОЛЖНЫ совпадать (иначе инстанс,
# забравший задачу, не сможет расшифровать её метаданные)
xpack.reporting.encryptionKey: "минимум 32 символа alphanumeric"

# Очередь
xpack.reporting.queue.pollInterval: 3s      # период опроса очереди
xpack.reporting.queue.timeout: 4m           # лимит времени на одну задачу
xpack.reporting.queue.pollEnabled: true     # false — инстанс не забирает задачи
xpack.reporting.capture.maxAttempts: 3      # число повторов при ошибке

# CSV
xpack.reporting.csv.scroll.strategy: pit     # по умолчанию pit; scroll — лимит 500 шардов, при недоступных шардах отдаёт partial
xpack.reporting.csv.scroll.size: 500         # максимум 10000
xpack.reporting.csv.scroll.duration: 120s    # с 9.0 поднято с 30s; допустимо auto — контекст держат до истечения queue.timeout
xpack.reporting.csv.maxConcurrentShardRequests: 5
xpack.reporting.csv.maxSizeBytes: 250mb      # обрезка файла сверх лимита
xpack.reporting.csv.maxRows: 10000           # обрезка строк сверх лимита (GA с 9.3)
xpack.reporting.csv.checkForFormulas: true   # предупреждение о CSV-инъекции (=, -, +, @)
xpack.reporting.csv.escapeFormulaValues: false  # экранировать такие значения апострофом
xpack.reporting.csv.useByteOrderMarkEncoding: false

# PDF/PNG: таймауты снимка страницы (при срабатывании отчёт всё равно
# сохраняется, но с предупреждением о неполной отрисовке)
xpack.screenshotting.capture.timeouts.openUrl: 1m
xpack.screenshotting.capture.timeouts.waitForElements: 1m
xpack.screenshotting.capture.timeouts.renderComplete: 2m
xpack.screenshotting.browser.chromium.disableSandbox: false  # на CentOS/Debian/RHEL по умолчанию true

# Страница, которую открывает Chromium (важно за reverse proxy)
xpack.reporting.kibanaServer.hostname: "kibana.example.com"
xpack.reporting.kibanaServer.protocol: "https"
xpack.reporting.kibanaServer.port: 5601

# Сетевая политика браузера (networkPolicy.enabled: true по умолчанию):
# правила читаются сверху вниз; если ни одно не подошло — запрос запрещён.
# Протокол file: запрещён всегда, даже без явной политики.
xpack.screenshotting.networkPolicy:
  rules:
    - { allow: true, host: "kibana.example.com" }
    - { allow: true, host: "elastic.co" }
    - { deny: true }
```

Настройки `xpack.reporting.kibanaServer.*` необязательны, но их неверное значение — частая причина падения PDF/PNG: полный URL, который Reporting пытается открыть, пишется в логи сервера.

### Проверка

```bash
curl -s -u elastic:$PASSWORD -H 'kbn-xsrf: true' \
  -XPOST 'https://kibana.example.com:5601/api/reporting/generate/csv?jobParams=...'
# → 200 и поле "path" — задача поставлена в очередь
curl -s -u elastic:$PASSWORD 'https://kibana.example.com:5601/api/reporting/jobs/download/<job-id>' -o report.csv
# → файл CSV
```

### Мониторинг и диагностика

* **Stack Management → Reporting** — листинг задач со статусами (`pending`, `processing`, `completed`, `failed`): основная точка проверки «ушёл ли отчёт» после автоматизации.
* **Built-in диагностика:** на Report Listing page кнопка **Run reporting diagnostics** — проверяет типовые проблемы деплоя (зависимости, шрифты, подключение) и выдаёт рекомендации.
* **Inspect query:** в листинге у отчёта → иконка ⓘ → Actions → Inspect query — открывает Dev Tools Console с фактическим запросом к Elasticsearch; полезно, когда CSV собирается медленно.
* **Логи браузера:** при подозрении на проблему со стороны Chromium запустите Kibana с отладкой Puppeteer:

```bash
env DEBUG="puppeteer:*" ./bin/kibana
# → протокол DevTools-трафика браузера; логи очень подробные и могут содержать чувствительные данные
```

* **Состояние хранилища:**

```bash
GET .kibana-reporting*/_count      # рост данных отчётов (легаси-индексы: .reporting-*)
GET _ilm/policy/kibana-reporting   # встроенная ILM-политика, управляющая ротацией
```

* **Нагрузка:** если отчёты отправляются с опозданием — смотрите Task Manager (конкурируют alerting, индексы, scheduled reports) и фоновые задачи в целом ([Эксплуатация в production](./kibana_production_operations.md)).
* **Очистка:** удалением старых отчётов занимается ILM-политика `kibana-reporting` — не чистите data stream вручную и не отключайте ILM.

## Troubleshooting

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| Отчёты падают после рестарта Kibana | Не задан `xpack.reporting.encryptionKey` — ключ генерируется случайно при старте | Задать статический ключ в keystore/`kibana.yml` одинаково на всех инстансах |
| Один инстанс создаёт отчёты, другой их не исполняет | Разные `xpack.reporting.encryptionKey` (и `xpack.security.encryptionKey`) за LB | Привести ключи к одинаковым значениям |
| HTTP 403 на генерацию | Нет feature privilege `generate_report`/`download_csv_report` или нет прав на Space/индекс | **Stack Management → Roles** → добавить Kibana privilege; для CSV — `read` на индексы |
| PDF/PNG не готовится, в логах ошибка подключения браузера | Неверные `xpack.reporting.kibanaServer.*`, не задан `server.host: 0.0.0.0` или Kibana недоступен по локальному адресу | Проверить hostname/port/protocol, `server.host`, файрвол; полный URL, который пытается открыть Reporting, логируется при генерации |
| Report помечен failed, запрос браузера не ушёл | Нарушен networkPolicy Chromium (хост не в `rules`, порядок сверху вниз) | Добавить хост в `networkPolicy.rules` до правила `deny` |
| Файл скачался, но визуализации пустые/недорисованные, есть warning | Истёк один из таймаутов `xpack.screenshotting.capture.timeouts.*` — Kibana сохраняет скриншот с предупреждением | Увеличить `openUrl`/`waitForElements`/`renderComplete`, сузить дашборд |
| Скачивание по `path` возвращает 503 | Отчёт ещё генерируется — это не ошибка | Повторять запрос через число секунд из заголовка `Retry-After` |
| Watch падает с `parse_exception` | Фигурные скобки `{}` date-math-выражений в `jobParams` | Убрать скобки, URL-кодировать выражение (см. раздел Watcher) |
| После апгрейда POST URL вернул ошибку | Используется deprecated URL вида `/api/reporting/generate/dashboard/<id>` | Пересоздать POST URL через UI (Export → Copy POST URL) |
| CSV падает с `security_exception: token expired` (SAML) | Генерация дольше срока жизни токена (`xpack.security.authc.token.timeout`, по умолчанию `20m`) | Меньшие отчёты (сегментировать диапазон), увеличить токен-таймаут, для автоматизации — auth без истечения (Basic) или выгрузка напрямую из Elasticsearch |
| `socket hangup` при выгрузке CSV | Прокси/Elasticsearch закрывает соединение при больших страницах или высокой латентности | Уменьшить `csv.scroll.size` (напр. `50`), увеличить `csv.scroll.duration` (напр. `2m`) |
| Отчёт падает с `Error: Page crashed!` | Не хватает RAM инстансу Kibana под Chromium | Увеличить память инстанса до 2+ ГБ, разбить дашборд |
| Подписи панелей — пустые прямоугольники | На хосте нет доступных шрифтов | Установить пакеты шрифтов (см. «Предварительные требования»); для CJK — шрифт с нужными глифами |
| В PDF таблица показывает только первые строки | Известное ограничение data table visualization: в PDF попадает только видимая страница строк | Использовать CSV-выгрузку или разбить таблицу |
| «Failed to generate report», машина медленная | Превышен `xpack.reporting.queue.timeout` (4m) | Увеличить timeout, сузить дашборд |
| CSV неполный (частично) | Стратегия `scroll` при недоступных шардах; CCS/высокая латентность | Перейти на `pit`, увеличить `csv.scroll.duration` или `auto` |
| CSV обрезан на 250 МБ / 10 000 строк | Лимиты `csv.maxSizeBytes`, `csv.maxRows` | Разбить выгрузку на несколько отчётов или выгружать напрямую через Elasticsearch API |
| Пустой PDF, ошибок нет | `disableSandbox: true/false` не соответствует системе; не установлены OS-зависимости Chromium | Использовать Docker-образ Kibana; проверить системные зависимости |
| Задача падает после нескольких попыток | Исчерпаны повторы (`capture.maxAttempts`, по умолчанию 3); фактический лимит времени = `queue.timeout` × (число попыток) | Увеличить `xpack.reporting.capture.maxAttempts` и/или `queue.timeout` |

## Best Practices

* **Не используйте Reporting как инструмент bulk-выгрузки.** Для больших объёмов — Scroll API, Point in time API, ES|QL или SQL с CSV-ответом напрямую из Elasticsearch (официальные clients).
* **HA:** несколько инстанс за балансировщиком с одинаковыми `xpack.reporting.encryptionKey` и `xpack.security.encryptionKey`; выделенные UI-узлы — с `pollEnabled: false`.
* **Ресурсы:** 2+ ГБ RAM на инстанс, генерирующий PDF/PNG; дашборды с сотнями панелей лучше разбивать — снимок большого полотна ест CPU и память.
* **Очистка:** данные отчётов ротируются встроенной ILM-политикой `kibana-reporting`; не отключайте ILM, не правьте `queue.indexInterval` (deprecated с 8.15) и не выключайте `stack.templates.enabled` — Reporting держит на нём шаблон своего data stream'а.
* **Безопасность:** выдавайте reporting-привилегии точечно (только нужные Spaces), не включайте legacy `xpack.reporting.roles.enabled` (в 9.0 удалён), не публикуйте Kibana в интернет — Reporting не рассчитан на публичный доступ.
* **Надёжность PDF/PNG:** для self-managed предпочитайте Docker-образ (зависимости Chromium и шрифтов собраны); тестовые сценарии генерации прогоняйте на pre-production перед апгрейдом Kibana.
* **Scheduled reports:** не кучите расписания на одно время, держите вложения до 10 МБ, наличие email-коннектора проверяйте заранее — эти три причины закрывают почти всю статистику «отчёт не пришёл».

## Дополнительная информация

* **[Kibana: Обзор](./kibana_overview.md)** — ресурсы, `kibana.yml`, мониторинг.
* **[Kibana: Эксплуатация в production](./kibana_production_operations.md)** — HA-ключи, `node.roles`, фоновые задачи.
* **[Kibana: Поиск, визуализация и управление](./kibana_search_and_visualization.md)** — Saved Objects, NDJSON, ES|QL REST API для выгрузок.
* **[Alerting: Kibana Alerting и Watcher](../Elasticsearch/elasticsearch_alerting.md)** — Watcher, email action, connectors.
* **[Fleet и Elastic Agent](../Elasticsearch/elastic_agent_and_fleet.md)** — фоновые задачи Kibana и Task Manager.
* [Reporting and sharing (официально)](https://www.elastic.co/docs/explore-analyze/report-and-share) — форматы и способы экспорта.
* [Reporting settings (официально)](https://www.elastic.co/docs/reference/kibana/configuration-reference/reporting-settings) — полный справочник настроек.
* [Configure Kibana reporting (официально)](https://www.elastic.co/docs/deploy-manage/kibana-reporting-configuration) — привилегии, TLS для Watcher, OS-зависимости Chromium.
* [Automatically generate reports (официально)](https://www.elastic.co/docs/explore-analyze/report-and-share/automating-report-generation) — POST URL, HTTP-коды, scheduled reports.
* [Troubleshoot PDF/PNG (официально)](https://www.elastic.co/docs/explore-analyze/report-and-share/reporting-troubleshooting-pdf) и [CSV (официально)](https://www.elastic.co/docs/explore-analyze/report-and-share/reporting-troubleshooting-csv) — диагностика, sandbox, шрифты, токены.

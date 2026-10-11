# Grafana: Отчёты (Reporting) — плановые PDF/CSV

**Актуально для:** Grafana 13.2.x / 12.x (LTS)

Практическое руководство по генерации и рассылке отчётов по дашбордам и по рендерингу дашбордов средствами API. Reporting как планировщик PDF/CSV/изображений — функция Grafana Enterprise (требует лицензии); для OSS приведён рабочий обходной путь через Rendering API + cron. Облачные и ИИ-функции не рассматриваются.

## Определения

- **Report (отчёт)** — запланированная выгрузка одного или нескольких дашбордов в PDF (и/или CSV, встроенное изображение) с расписанием (однократно, ежечасно, ежедневно, еженедельно, ежемесячно, в последний день месяца, по интервалу) и списком получателей.
- **grafana-image-renderer** — внешний сервис на headless Chromium, который Grafana вызывает для отрисовки дашборда/панели в изображение или PDF. Обязательная зависимость отчётов, PDF-экспорта дашборда и картинок в уведомлениях.
- **Rendering API** — HTTP-эндпоинты Grafana `GET /render/d/:uid/:slug` (дашборд) и `GET /render/d-solo/:uid/:slug` (панель), возвращающие PNG; доступны и в OSS при настроенном renderer'е.
- **Rendering API renderer'а** — HTTP-эндпоинты самого сервиса: `POST /render`, `POST /render/csv`, а также служебные `GET /healthz`, `GET /version`, `GET /metrics`. Grafana обращается к ним от имени инициатора рендеринга.
- **CSV export** — вложение к отчёту: CSV-файл на каждую табличную панель (Enterprise). Не путать с выгрузкой «Download CSV» отдельной панели, доступной в OSS.
- **Report branding (брендирование)** — общеорганизационные настройки логотипа и подвала письма/PDF отчёта (`/api/reports/settings`).
- **`[reporting]`** — секция конфигурации Grafana Enterprise, управляющая генерацией отчётов (таймаут, лимиты, шрифты, допустимые домены).

## Базовые концепции

Как устроен отчёт:

1. По расписанию встроенный планировщик Grafana (Enterprise) открывает целевой дашборд «как пользователь» с заданным диапазоном времени и значениями переменных.
2. Дашборд рендерится через `grafana-image-renderer` (Chromium): панели выполняют запросы к источникам данных, страница отрисовывается, результат печатается в PDF (или собирается CSV/изображение).
3. Вложение отправляется по SMTP получателям; в письмо опционально встраивается изображение дашборда и ссылка на дашборд.

Важные детали механизма:

- **Таймзона.** У расписания есть явное поле `timeZone`. Отображаемое время панели берётся из таймзоны дашборда: если у дашборда выставлено **Browser Time**, отчёт рендерится в таймзоне сервера Grafana, иначе — в фиксированной таймзоне дашборда. Браузер renderer'а по умолчанию работает в `Etc/UTC` (флаг `--browser.timezone`), поэтому для предсказуемого времени фиксируйте таймзону дашборда, а не полагайтесь на UTC по умолчанию.
- **Таймауты.** Таймаут одного запроса на рендеринг передаётся renderer'у параметром URL `timeout` (в секундах). Для Enterprise-отчётов общий лимит на генерацию задаёт `[reporting] rendering_timeout` (по умолчанию `10s`), а готовность страницы в самом renderer'е ограничивает `--browser.readiness.timeout` (по умолчанию `30s`). При «Rendering timed out» эти значения согласовывают.
- **Ограничение размера вложения.** Вложения больше `[reporting] max_attachment_size_mb` (по умолчанию `10` МБ) не отправляются, чтобы почтовые серверы не отклоняли письмо.
- **Временные файлы.** Сгенерированные вложения (`data/pdf`, `data/csv`, `data/png`) временно лежат в каталоге `data`; фоновая задача раз в 10 минут удаляет устаревшие, срок хранения — `[paths] temp_data_lifetime` (по умолчанию `24h`).

Практические следствия:

- **Без работающего renderer'а отчётов нет** — проверка его доступности всегда первый шаг диагностики.
- Отчёт наследует права создателя: если у сервисного аккаунта-создателя нет доступа к источнику, панели будут пустыми.
- Тяжёлые дашборды = долгий рендер: число панелей, повторы и переменные с большим числом значений увеличивают и время генерации, и размер PDF.
- В HA-кластере узлы должны иметь синхронизированное время (NTP); расхождение часов приводит к смещению расписания и возможным дублям (см. [Высокая доступность](high_availability.md)).

## Практические сценарии

### Предварительные требования

- Grafana Enterprise с действующей лицензией — для планировщика отчётов и форматов CSV/image. Rendering API (`/render/...`) доступен и в OSS.
- Настроен `grafana-image-renderer` (см. [Рендеринг изображений](grafana_image_rendering.md)): `[rendering] server_url` указывает на сервис, `callback_url` — на внешний адрес Grafana, `renderer_token` совпадает с токеном renderer'а.
- Настроен SMTP (`[smtp] enabled = true`, `host`, `from_address`) и проверена отправка тестового письма.
- Учётная запись или сервисный аккаунт с доступом ко всем источникам данных целевого дашборда.

### Сценарий 1. Проверка готовности инфраструктуры отчётов

```bash
# 1. Renderer доступен (health-эндпоинт самого сервиса)
curl -sS "http://renderer:8081/healthz"
# → OK

# 2. Версия renderer'а и браузера
curl -sS "http://renderer:8081/version" | jq .
# → {"version":"...","browser":{...}}

# 3. Рендеринг тестовой панели через Grafana
#    Эндпоинт /render/* защищён: нужен токен сервисного аккаунта или сессия
curl -sS -H "Authorization: Bearer $TOKEN" \
  -o /tmp/test.png -w "%{http_code} %{size_download}\n" \
  "$GRAFANA/render/d-solo/<dashboard-uid>/panel?panelId=4&from=now-1h&to=now&width=1000&height=500"
# → 200 и размер >20000 байт (файл /tmp/test.png открывается как изображение)

# 4. SMTP (для Enterprise-рассылки): отправить тестовое письмо себе
#    POST /api/reports/test-email (см. сценарий 3) либо UI: Schedule report → Send preview
```

### Сценарий 2. Создание отчёта через UI (Enterprise)

1. Открыть дашборд → **Share → Schedule report** (либо **Dashboards → Reporting → + Create a new report**).
2. Заполнить разделы:
   - **Dashboards** — источник, диапазон времени (пусто = сохранить диапазон дашборда), значения переменных.
   - **Schedule** — «сразу»/«позже», частота, таймзона, дата начала и окончания, «только будни», «последний день месяца».
   - **Email settings** — тема, тело письма, reply-to, встраивание изображения и ссылки на дашборд.
   - **Recipients** — адреса через запятую или точку с запятой.
   - **Attachments** — PDF (ориентация, layout grid/simple, zoom, объединение дашбордов в один файл) и CSV на табличные панели.
3. Нажать **Schedule report**; проверить появление отчёта в **Dashboards → Reporting**.

Проверка: нажать **Send preview**/**Send now** либо дождаться времени отправки; письмо с вложением приходит, PDF содержит актуальные данные панелей.

### Сценарий 3. Управление отчётами через API (Enterprise)

> Reporting API не стабилизирован и находится в активной разработке. Начиная с Grafana 13 эндпоинты `/api` постепенно вытесняются маршрутом `/apis`; действующие `/api/reports/*` продолжают работать и не ломаются.

```bash
# Список отчётов
curl -sS "$GRAFANA/api/reports" -H "Authorization: Bearer $TOKEN" \
  | jq '.items[] | {id, name, state, schedule, formats}'
```

Создание ежедневного отчёта по дашборду `uid=prod-overview`:

```bash
curl -sS -X POST "$GRAFANA/api/reports" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{
    "name": "Ежедневный обзор продакшена",
    "recipients": "oncall@example.com, sre@example.com",
    "replyTo": "grafana@example.com",
    "message": "Отчёт по дашборду за сутки во вложении.",
    "schedule": {
      "startDate": "2026-08-25T06:00:00+03:00",
      "endDate": null,
      "frequency": "daily",
      "workdaysOnly": true,
      "timeZone": "Europe/Moscow"
    },
    "options": {"orientation": "landscape", "layout": "grid"},
    "enableDashboardUrl": true,
    "dashboards": [
      {
        "dashboard": {"uid": "prod-overview"},
        "timeRange": {"from": "now-24h", "to": "now"},
        "reportVariables": {}
      }
    ],
    "formats": ["pdf", "csv"]
  }'
# → {"id": 3, "message": "Report created"}
```

Ключевые поля схемы:

- `recipients`, `replyTo` — строки с адресами через запятую (не массив).
- `schedule.timeZone` (заглавная `Z`), `schedule.startDate`/`endDate`, `schedule.frequency` — `once`, `hourly`, `daily`, `weekly`, `monthly`, `last` (последний день месяца), `custom`; для `custom` — `intervalFrequency` (`hours`/`days`/`weeks`/`months`) и `intervalAmount`.
- `dashboards` — массив дашбордов; идентификатор задаётся как `dashboard.uid` (не `dashboardId`), диапазон — `timeRange`, переменные — `reportVariables`.
- `formats` — `pdf` (по умолчанию), `csv` (файл на каждую табличную панель), `image` (изображение дашборда в теле письма).
- `options` — `orientation` (`portrait`/`landscape`) и `layout` (`grid`/`simple`).

Отправить сейчас и отправить тестовое письмо:

```bash
# Немедленная отправка существующего отчёта
curl -sS -X POST "$GRAFANA/api/reports/email" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"id": "3", "useEmailsFromReport": true}'
# → {"message":"Report was sent"}

# Тестовое письмо (не сохраняется в БД): тело — тот же объект отчёта, что и при создании
curl -sS -X POST "$GRAFANA/api/reports/test-email" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{ ...объект отчёта... }'
```

Обновление и удаление:

```bash
curl -sS -X PUT "$GRAFANA/api/reports/3" -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" -d '{ ...новый объект отчёта... }'
# → {"message": "Report updated"}

curl -sS -X DELETE "$GRAFANA/api/reports/3" -H "Authorization: Bearer $TOKEN"
# → {"message": "Report config was removed"}
```

Пауза и возобновление отчёта выполняются только в UI (страница **Reporting** или drawer **Update report**); отдельных эндпоинтов pause/resume у Reporting API нет.

Брендирование (глобальные настройки организации, применяются ко всем отчётам):

```bash
curl -sS "$GRAFANA/api/reports/settings" -H "Authorization: Bearer $TOKEN" | jq .branding

curl -sS -X POST "$GRAFANA/api/reports/settings" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"branding": {
        "reportLogoUrl": "https://example.com/logo.png",
        "emailLogoUrl": "https://example.com/email-logo.png",
        "emailFooterMode": "sent-by",
        "emailFooterText": "Example Corp",
        "emailFooterLink": "https://example.com/"
      }}'
# → {"message":"Report settings saved"}
```

Права (RBAC): `reports:read`, `reports:create`, `reports:write`, `reports:delete`, `reports:send`, `reports.settings:read`, `reports.settings:write`. По умолчанию создавать отчёты может только администратор организации (см. [Fine-grained RBAC](grafana_rbac_fine_grained.md)).

### Сценарий 4. OSS-обходной путь: cron + Rendering API + почта

Плановый PNG-отчёт без Enterprise:

```bash
#!/usr/bin/env bash
set -euo pipefail
GRAFANA="https://grafana.example.internal"
TOKEN="<sa-token-viewer>"
OUT="/var/www/status/status-$(date +%F-%H%M).png"

curl -sS -H "Authorization: Bearer $TOKEN" \
  -o "$OUT" \
  "$GRAFANA/render/d/prod-overview/main?from=now-24h&to=now&width=1920&height=1080&kiosk&timeout=30"

[ "$(stat -c%s "$OUT")" -gt 50000 ] || { echo "PNG подозрительно мал"; exit 1; }

mail -s "Статус за сутки" -A "$OUT" oncall@example.com <<< "Автоматический отчёт."
```

В crontab: `0 6 * * * /usr/local/bin/grafana-report.sh`. Проверка: свежий файл появляется в каталоге, письмо доставляется, размер изображения стабилен изо дня в день.

Для табличных данных вместо скриншота надёжнее выгружать CSV напрямую запросом `POST /api/ds/query` (скриптом) — результат не зависит от Chromium.

### Сценарий 5. Конфигурация отчётности и рендеринга

Секции Grafana Enterprise:

```ini
[reporting]
enabled = true
# Лимит времени на генерацию PDF/CSV/изображения (по умолчанию 10s)
rendering_timeout = 30s
# Одновременные запросы к renderer'у (по умолчанию 4)
concurrent_render_limit = 4
# Масштаб изображения: 2 — мониторы, 4 — печать (по умолчанию 2)
image_scale_factor = 2
# Максимальный размер вложения письма, МБ (по умолчанию 10)
max_attachment_size_mb = 10
# Домены получателей; * — любые (по умолчанию *)
allowed_domains = example.com, example.org

[paths]
# Сколько хранить временные файлы отчётов в каталоге data/ (по умолчанию 24h)
temp_data_lifetime = 24h
```

Подключение renderer'а и SMTP:

```ini
[rendering]
server_url = http://renderer:8081/render
callback_url = https://grafana.example.internal/
renderer_token = <токен renderer'а>

[smtp]
enabled = true
host = smtp.example.com:587
user = grafana@example.com
password = <пароль>
from_address = grafana@example.com
from_name = Grafana
startTLS_policy = OpportunisticStartTLS
```

Таймаут конкретного запроса `/render/...` задаётся параметром URL `timeout` (в секундах). Готовность страницы на стороне renderer'а ограничивает `--browser.readiness.timeout` (по умолчанию `30s`).

### Сценарий 6. Диагностика «пустых» или оборванных отчётов

```bash
# Логи Grafana по отчётам и рендерингу
journalctl -u grafana-server | grep -iE "reporting|rendering" | tail -20
# → ищите "Rendering timed out", "failed to send email", "unauthorized"

# Подробные логи подсистем отчётов: добавить в [log] и перезапустить Grafana
# filters = rendering:debug,report.api:debug,report.render:debug,report.scheduler:debug,report.sender:debug,report.service:debug

# Ручной прогон того же URL, что использует отчёт, с увеличенным таймаутом
curl -v -H "Authorization: Bearer $TOKEN" \
  -o /tmp/r.png \
  "$GRAFANA/render/d/prod-overview/main?from=now-1d&to=now&width=1600&height=900&timeout=60" 2>&1 | grep "< HTTP"
```

Типовые причины пустых панелей: SA-создатель без доступа к источнику; переменные с дефолтами «All» при выключенном `includeAll`; диапазон времени, где данных нет; renderer'у не хватило времени на медленный источник (смотрите `--browser.readiness.timeout` и `[reporting] rendering_timeout`).

## Дополнительная информация

### Рекомендации по эксплуатации

- Выносите image-renderer в отдельный сервис/под: рендеринг прожорлив по памяти (Chromium).
- Для стабильности PDF фиксируйте в отчёте диапазон времени и переменные, а не «текущее состояние» дашборда.
- Время расписания задавайте явно с таймзоной; в дашборде используйте фиксированную таймзону вместо Browser Time, иначе отчёт берёт таймзону сервера Grafana.
- Ограничивайте список получателей рассылкой группой (mailing list), а не перечислением людей; при необходимости сужайте `allowed_domains`.
- Мониторьте метрики renderer'а (`/metrics`, `process_resident_memory_bytes`) и логи `reporting` — рост памяти говорит об утечках Chromium (лечится рестартом контейнера).
- Держите размер вложений меньше `max_attachment_size_mb`: большие таблицы лучше отдавать CSV-вложением, а не PDF.

### Типичные ошибки и их решение

| Симптом | Причина | Решение |
| --- | --- | --- |
| Пустые панели в PDF | Нет прав у автора отчёта на источник данных | Дать SA-автору права на источник (см. RBAC) |
| `Rendering timed out` | Дашборд тяжёлый, лимит времени мал | Поднять `[reporting] rendering_timeout` и/или `--browser.readiness.timeout`, упростить дашборд |
| Письмо не приходит | Не настроен `[smtp]`; домен получателя не в `allowed_domains`; вложение > `max_attachment_size_mb` | Проверить SMTP отправкой, домены и размер вложения |
| Отчёт пришёл дважды | HA: часы узлов расходятся | NTP на всех узлах (см. [Высокая доступность](high_availability.md)) |
| CSV пустой | В отчёте нет табличных панелей | Добавить table panel или убрать формат csv |
| OSS: раздел Reporting отсутствует | Функция лицензионная | Использовать cron + `/render/...` (сценарий 4) |
| Отчёт в неверной таймзоне | У дашборда выставлено Browser Time | Задать фиксированную таймзону дашборда |

### Ограничения и особые случаи

- Scheduled reporting, CSV- и image-форматы — только Enterprise; Rendering API (`/render/...`) — OSS.
- Reporting API не стабилизирован и может меняться; пауза/возобновление отчёта — только через UI.
- Renderer должен видеть Grafana по `callback_url`, а Grafana — renderer по `server_url`: ошибки сети выглядят как «таймаут рендеринга», а не как ошибка доступа.
- Повторяющиеся панели и переменные с большим числом значений увеличивают число страниц PDF.
- Аутентификация renderer↔Grafana: Grafana выдаёт renderer'у краткоживущий render key (`[rendering] render_key_lifetime`, по умолчанию `5m`); при auth proxy/SSO убедитесь, что `callback_url` доступен renderer'у согласно вашей схеме безопасности.
- До версии Grafana 13 существовал плагинный режим renderer'а; начиная с 13 он полностью удалён — renderer разворачивается только как отдельный сервис.

### Очистка и откат изменений

- Неиспользуемые отчёты удаляйте (`DELETE /api/reports/{id}`) — планировщик продолжает их исполнять.
- Временные файлы отчётов чистятся автоматически; срок регулируется `[paths] temp_data_lifetime`.
- Старые PNG из OSS-обходного пути чистите ротацией: `find /var/www/status -name '*.png' -mtime +30 -delete`.

### Актуальность и статус

Reporting присутствует только в Grafana Enterprise и актуален для 13.x / 12.x LTS. Reporting API помечен как нестабильный (активная разработка); с Grafana 13 эндпоинты `/api` постепенно вытесняются маршрутом `/apis` (legacy-маршруты сохраняются). Rendering API (`/render/...`) стабилен и доступен в OSS. Плагинный режим image-renderer'а удалён в Grafana 13.

### Связанные темы

- [Рендеринг изображений (grafana-image-renderer)](grafana_image_rendering.md)
- [Высокая доступность](high_availability.md)
- [Fine-grained RBAC](grafana_rbac_fine_grained.md)
- [Дашборды](grafana-dashboards.md)

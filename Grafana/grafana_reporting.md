# Grafana: Отчёты (Reporting) — плановые PDF/CSV

Практическое руководство по генерации и рассылке отчётов по дашбордам. Reporting как планировщик PDF/CSV — функция Enterprise (лицензия); для OSS приведён рабочий обходной путь через Rendering API + cron. Облачные и ИИ-функции не рассматриваются.

## Определения

- **Report (отчёт)** — запланированная выгрузка дашборда в PDF (или таблиц в CSV) с расписанием (однократно, ежедневно, еженедельно, ежемесячно) и списком получателей.
- **grafana-image-renderer** — внешний сервис на headless Chromium, который Grafana вызывает для отрисовки дашборда в изображение/PDF. Обязательная зависимость любого отчёта.
- **Rendering API** — HTTP-эндпоинты `/render/d/...` и `/render/d-solo/...`, возвращающие PNG всего дашборда или отдельной панели; доступны и в OSS.
- **CSV export** — выгрузка данных табличных панелей отчёта в CSV (Enterprise).
- **Report branding** — подстановка логотипа и подписи организации в шапку/подвал PDF.

## Базовые концепции

Как устроен отчёт:

1. По расписанию (внутренний планировщик Grafana, время — по UTC) Grafana открывает целевой дашборд «как пользователь» с заданным диапазоном времени и переменными.
2. Дашборд рендерится через `grafana-image-renderer` (Chromium): панели выполняют запросы к источникам данных, страница отрисовывается, результат печатается в PDF.
3. PDF отправляется по SMTP получателям и/или сохраняется локально (последнее зависит от версии/лицензии).

Практические следствия:

- **Без работающего renderer'а отчётов нет** — проверка его доступности всегда первый шаг диагностики.
- Отчёт наследует права создателя: если у сервисного аккаунта-создателя нет доступа к источнику, панели будут пустыми.
- Тяжёлые дашборды = долгий рендер: таймауты `[rendering]` и `[reporting]` нужно согласовывать.
- Планировщик живёт в каждом узле HA-кластера; дубликаты предотвращаются распределённой блокировкой (см. high_availability.md), но время на узлах должно быть синхронизировано (NTP).

## Практические сценарии

### Предварительные требования

- Настроен `grafana-image-renderer` (см. [Рендеринг изображений](grafana_image_rendering.md)): `[rendering] server_url` и `callback_url` отвечают.
- Для Enterprise-рассылки: настроен SMTP (`[smtp] enabled = true ...`) и лицензия Enterprise.
- Учетная запись/SA, имеющая доступ ко всем источникам целевого дашборда.

### Сценарий 1. Проверка готовности инфраструктуры отчётов

```bash
# 1. Renderer доступен Grafana
curl -sS "http://renderer:8081/render/health"
# → {"status":"ok"} или пустой 200

# 2. Рендеринг тестовой панели через Grafana
curl -sS -o /tmp/test.png -w "%{http_code} %{size_download}\n" \
  "$GRAFANA/render/d-solo/<dashboard-uid>/panel?panelId=4&from=now-1h&to=now&width=1000&height=500"
# → 200 и размер >20000 байт (файл /tmp/test.png открывается как изображение)

# 3. SMTP (для Enterprise-рассылки)
curl -sS "$GRAFANA/api/health" | jq .database   # база ок
# письмо проверяется реальной отправкой отчёта себе
```

### Сценарий 2. Создание разового отчёта через UI (Enterprise)

1. Открыть дашборд → **Share → Report**.
2. Задать формат (PDF), ориентацию, layout (grid/simple), диапазон времени, переменные.
3. Добавить получателей (email), расписание (например, каждый будний день 08:00 UTC).
4. Сохранить; проверить появление в **Dashboards → Reports** (раздел меню при наличии лицензии).

Проверка: дождаться времени отправки либо нажать **Send now**; письмо с вложением PDF приходит, PDF содержит актуальные данные панелей.

### Сценарий 3. Управление отчётами через API (Enterprise)

```bash
# Список отчётов
curl -sS "$GRAFANA/api/reports" -H "Authorization: Bearer $TOKEN" | jq '.items[] | {id, name, lastSentAt}'

# Создать ежедневный отчёт по дашборду uid=prod-overview
curl -sS -X POST "$GRAFANA/api/reports" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{
    "dashboardId": 42,
    "name": "Ежедневный обзор продакшена",
    "recipients": ["oncall@example.com"],
    "formats": ["pdf", "csv"],
    "schedule": {
      "start": "2026-08-25T06:00:00Z",
      "frequency": "daily",
      "timezone": "Europe/Moscow"
    },
    "options": {"orientation": "landscape", "timeRange": {"from": "now-24h", "to": "now"}}
  }'
# → {"id": 3, "message": "Report created"}

# Поставить на паузу / возобновить
curl -sS -X POST "$GRAFANA/api/reports/3/pause"  -H "Authorization: Bearer $TOKEN"
curl -sS -X POST "$GRAFANA/api/reports/3/resume" -H "Authorization: Bearer $TOKEN"
```

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
  "$GRAFANA/render/d/prod-overview/main?from=now-24h&to=now&width=1920&height=1080&kiosk"

[ "$(stat -c%s "$OUT")" -gt 50000 ] || { echo "PNG подозрительно мал"; exit 1; }

mail -s "Статус за сутки" -A "$OUT" oncall@example.com <<< "Автоматический отчёт."
```

В crontab: `0 6 * * * /usr/local/bin/grafana-report.sh`. Проверка: свежий файл появляется в каталоге, письмо доставляется, размер изображения стабилен изо дня в день.

Для табличных данных вместо скриншота надёжнее выгружать CSV напрямую запросом `/api/ds/query` (скриптом) — не зависит от Chromium.

### Сценарий 5. Диагностика «пустых» или оборванных отчётов

```bash
# Логи Grafana по отчётам и рендерингу
journalctl -u grafana-server | grep -iE "reporting|rendering" | tail -20
# → ищите "Rendering timed out", "failed to send email", "unauthorized"

# Ручной прогон того же URL, что использует отчёт (тот же time range и переменные)
curl -v -o /tmp/r.pdf "$GRAFANA/api/reports/render/pdf/<uid>" 2>&1 | grep "< HTTP"
```

Типовые причины пустых панелей: SA-создатель без доступа к источнику; переменные с дефолтами «All» при выключенном `includeAll`; диапазон времени, где данных нет.

## Дополнительная информация

### Рекомендации по эксплуатации

- Выносите image-renderer в отдельный сервис/под: рендеринг прожорлив по памяти (Chromium).
- Для стабильности PDF фиксируйте в отчёте диапазон времени и переменные, а не «текущее состояние» дашборда.
- Время расписания задавайте явно с таймзоной; помните, что внутренний планировщик работает по UTC.
- Ограничивайте список получателей рассылкой группой (mailing list), а не перечислением людей.
- Мониторьте метрики renderer (`process_resident_memory_bytes`) и логи `reporting` — рост памяти говорит о утечках Chromium (лечится рестартом контейнера).

### Типичные ошибки и их решение

| Симптом | Причина | Решение |
| --- | --- | --- |
| Пустые панели в PDF | Нет прав у автора отчёта на источник данных | Дать SA-автору права на источник (см. RBAC) |
| `Rendering timed out` | Дашборд тяжёлый, таймаут мал | Увеличить `[rendering] timeout` / упростить дашборд |
| Письмо не приходит | Не настроен `[smtp]` | Заполнить секцию SMTP, проверить отправкой тестового письма |
| Отчёт пришёл дважды | HA: часы узлов расходятся / блокировки не работают | NTP на всех узлах, одинаковый `secret_key` (см. high_availability.md) |
| CSV пустой | В отчёте нет табличных панелей | Добавить table panel или убрать формат csv |
| OSS: раздел Reports отсутствует | Функция лицензионная | Использовать cron + `/render/...` (сценарий 4) |

### Ограничения и особые случаи

- Scheduled reporting и CSV export — только Enterprise; Rendering API — OSS.
- Renderer должен видеть Grafana по `callback_url`, а Grafana — renderer по `server_url`: ошибки сети выглядят как «таймаут рендеринга», а не как ошибка доступа.
- Повторяющиеся панели и переменные с большим числом значений увеличивают число страниц PDF.
- Аутентификация renderer↔Grafana: при auth proxy/SSO убедитесь, что служебный URL доступен токеном/анонимно согласно вашей схеме безопасности.

### Очистка и откат изменений

- Неиспользуемые отчёты удаляйте (`DELETE /api/reports/{id}`) — планировщик продолжает их исполнять.
- Старые PNG из OSS-обходного пути чистите ротацией: `find /var/www/status -name '*.png' -mtime +30 -delete`.

### Актуальность и статус

Reporting API и форматы актуальны для 12.x LTS/13.x; Rendering API стабилен с 8.x. Расписание с таймзонами и CSV — с 9.x.

### Связанные темы

- [Рендеринг изображений (grafana-image-renderer)](grafana_image_rendering.md)
- [Высокая доступность](high_availability.md)
- [Fine-grained RBAC](grafana_rbac_fine_grained.md)
- [Дашборды](grafana-dashboards.md)

# Рендеринг изображений (grafana-image-renderer)

Практическое руководство по компоненту `grafana-image-renderer`, который генерирует изображения дашбордов и панелей. Версии: Grafana 13.x актуальная, 12.x LTS, 11.x — EOL (июнь 2026); сервис рендеринга версионируется независимо (ветка v5.x). Облачные и ИИ-функции не рассматриваются.

## Определения

- **grafana-image-renderer** — внешний сервис (Go + headless Chromium), который по HTTP рендерит дашборд или панель Grafana в PNG, PDF или CSV. Единственный поддерживаемый способ рендеринга начиная с Grafana 13.
- **Grafana Rendering API** — HTTP-эндпоинты самой Grafana: `GET /render/d/:uid/:slug` (дашборд) и `GET /render/d-solo/:uid/:slug` (панель), которые проксируют запрос в сервис рендеринга. Доступны и в OSS при настроенном рендерере.
- **API сервиса рендеринга** — эндпоинты самого сервиса: `GET /render`, `GET /render/csv`, а также служебные `GET /healthz`, `GET /version`, `GET /render/version`, `GET /metrics`.
- **callback URL** — адрес Grafana, по которому сервис рендеринга открывает дашборд как браузер (обычно внешний `root_url`). Задаётся на стороне Grafana в `[rendering] callback_url`.
- **renderer_token / AUTH_TOKEN** — общий секрет: Grafana передаёт его в заголовке `X-Auth-Token`, сервис проверяет токен перед рендерингом. По умолчанию у сервиса задан единственный токен `-`.
- **render key** — краткоживущий ключ, который Grafana выдаёт сервису рендеринга для аутентификации при открытии приватного дашборда.
- **Headless Chromium** — браузер без GUI, потребляющий заметные CPU/память при рендеринге тяжёлых дашбордов (пиково — гигабайты на один скриншот).

## Базовые концепции

### Зачем нужен рендерер

Рендеринг изображений нужен для:

- картинок панелей в уведомлениях алертинга (Slack, Telegram, Email) — `[unified_alerting.screenshots]`;
- PDF/PNG-экспорта дашборда и плановых отчётов (отчёты — функция Grafana Enterprise, см. [Отчёты](grafana_reporting.md));
- предпросмотра дашборда и внешних снимков (snapshots).

Сам Grafana рисовать дашборд в картинку не умеет — это всегда делает внешний сервис `grafana-image-renderer`. Исторически функциональность поставлялась как плагин Grafana (с движком phantomjs, позже Chromium); плагинный режим устарел и полностью удалён в Grafana 13, поэтому на 11.x/12.x/13.x сервис разворачивается как отдельный процесс или контейнер.

### Как устроен поток рендеринга

1. Grafana получает запрос на изображение (алерт, снимок, отчёт, PDF-экспорт).
2. Grafana отправляет сервису рендеринга запрос на `server_url` (по умолчанию `http://localhost:8081/render`), передавая URL дашборда, диапазон времени, значения переменных, размеры и `timeout` через параметры URL.
3. Сервис запускает headless Chromium, открывает дашборд по адресу, собранному из `callback_url` (то есть обращается к самой Grafana как пользователь), дожидается готовности страницы и снимает изображение.
4. Результат (PNG/PDF/CSV) возвращается Grafana и вставляется в уведомление, отчёт или отдаётся клиенту.

Из потока следуют два обязательных требования к сети: Grafana должна достигать сервис по `server_url`, а сервис — достигать Grafana по `callback_url` и источники данных дашборда. При неверном `callback_url` сервис открывает недоступный адрес и возвращает таймаут или пустую картинку.

### Две стороны конфигурации

Рендеринг настраивается в двух независимых местах, и их легко перепутать:

| Сторона | Где | Что задаётся |
| :--- | :--- | :--- |
| Grafana | `grafana.ini`, секция `[rendering]` (env `GF_RENDERING_*`) | `server_url`, `callback_url`, `renderer_token`, `concurrent_render_request_limit`, TLS к сервису, размеры по умолчанию |
| Сервис рендеринга | CLI-флаги, переменные окружения или `config.yaml`/`config.json` в рабочем каталоге | адрес прослушивания, токен, путь к браузеру, таймзону, лимиты Chromium, rate-limit, tracing |

Ключевые параметры `[rendering]` в Grafana:

| Параметр | Назначение | По умолчанию |
| :--- | :--- | :--- |
| `server_url` | URL эндпоинта `/render` сервиса | `http://localhost:8081/render` |
| `callback_url` | Внешний URL Grafana, по которому её откроет сервис | наследуется от `root_url` |
| `renderer_token` | Токен, который Grafana передаёт сервису (`GF_RENDERING_RENDERER_TOKEN`) | `-` |
| `concurrent_render_request_limit` | Максимум одновременных запросов на эндпоинт `/render` | `30` |
| `ca_cert_file_path` | CA-сертификат для подключения к сервису по TLS | пусто |
| `default_image_width` / `default_image_height` | Размер изображения по умолчанию | `1000` / `500` |
| `default_image_scale` | Масштаб изображения по умолчанию | `1` |

### Аутентификация

- **Grafana → сервис:** Grafana добавляет заголовок `X-Auth-Token` со значением `renderer_token`; сервис принимает только запросы с одним из настроенных у него токенов (`--server.auth-token`, env `AUTH_TOKEN`). По умолчанию обе стороны используют `-`, что небезопасно при доступе к сервису извне — задайте собственный длинный токен.
- **Сервис → Grafana:** для приватных дашбордов Grafana выдаёт сервису краткоживущий render key, поэтому сервис должен иметь сетевой доступ к `callback_url` по вашей схеме аутентификации (auth proxy/SSO).

### Ресурсы и параллелизм

- **Ресурсы.** Документация Grafana рекомендует выделять сервису рендеринга **не менее 16 GiB памяти и 4 CPU-ядер**; один тяжёлый рендеринг может пиково потребовать несколько гигабайт и много ядер. На малых узлах ограничивайте параллелизм, а не только память.
- **GOMEMLIMIT.** При лимите памяти контейнера задавайте `GOMEMLIMIT` ниже самого лимита (примерно **1 GiB на каждые 8 GiB лимита**), оставляя запас для Chromium. Устанавливать `GOMEMLIMIT` равным лимиту нельзя — браузеру нужна свободная память.
- **Rate-limit сервиса (v5).** Сервис сам ограничивает число одновременных рендеров по доступной памяти (`--rate-limit.*`): `min-limit` (по умолчанию `3`), `min-memory-per-browser` (по умолчанию 64 MiB), `headroom` (по умолчанию 32 MiB). Ограничение можно полностью отключить `--rate-limit.disabled=true`.
- **Сторона Grafana.** `concurrent_render_request_limit` (по умолчанию `30`) ограничивает общее число одновременных запросов к сервису через эндпоинт `/render`. Для картинок в уведомлениях отдельно действует `[unified_alerting.screenshots] max_concurrent_screenshots`.
- **Совместимость версий.** Сервис версионируется независимо от Grafana (текущая ветка — v5.x). Поддерживается только последняя версия сервиса; в проде фиксируйте конкретный тег, а не `latest`.

## Практические сценарии

### Предварительные требования

- Работающая Grafana 11.x+ и доступ к Docker либо возможность запускать бинарник (Linux/Windows).
- Сетевой доступ между Grafana и сервисом: Grafana → `server_url` (порт 8081 по умолчанию), сервис → `callback_url` Grafana.
- Заданный `callback_url` — тот же внешний адрес, что и `root_url` Grafana.
- Выделенный узел или контейнер под сервис с запасом памяти (см. «Ресурсы и параллелизм»).
- При использовании картинок в алертах — включённый `[unified_alerting.screenshots] capture = true`.

### Сценарий 1. Установка сервиса и подключение Grafana (Docker Compose)

```yaml
services:
  renderer:
    image: grafana/grafana-image-renderer:5.12.6
    environment:
      # Токен, который Grafana передаёт в X-Auth-Token; должен совпасть с renderer_token
      AUTH_TOKEN: <renderer-token>
      # Лимит Go-кучи ниже лимита контейнера (Chromium нужна свободная память)
      GOMEMLIMIT: 2GiB
    deploy:
      resources:
        limits:
          cpus: "4.0"
          memory: 16G

  grafana:
    image: grafana/grafana:13.2.3
    ports:
      - "3000:3000"
    environment:
      GF_RENDERING_SERVER_URL: http://renderer:8081/render
      GF_RENDERING_CALLBACK_URL: https://grafana.example.internal/
      GF_RENDERING_RENDERER_TOKEN: <renderer-token>
```

Сервис рендеринга не требует собственного адреса callback в переменных: адрес Grafana задаёт сама Grafana в `[rendering] callback_url` и передаёт в запросе. У сервиса настраивается только токен (и, при необходимости, адрес прослушивания, путь к браузеру, таймзона, лимиты).

### Сценарий 2. Настройка Grafana через grafana.ini

```ini
[rendering]
# URL эндпоинта рендеринга сервиса (по умолчанию http://localhost:8081/render)
server_url = http://renderer:8081/render
# Внешний URL Grafana, по которому её откроет сервис (обычно равен root_url)
callback_url = https://grafana.example.internal/
# Должен совпадать с --server.auth-token / AUTH_TOKEN сервиса
renderer_token = <renderer-token>
# Максимум одновременных запросов к /render (по умолчанию 30)
concurrent_render_request_limit = 30

[unified_alerting.screenshots]
# Включить картинки панелей в уведомлениях (по умолчанию выключено)
capture = true
# Таймаут съёмки одного скриншота, максимум 30s
capture_timeout = 10s
# Не более стольких скриншотов одновременно
max_concurrent_screenshots = 3
```

Через переменные окружения те же параметры задаются как `GF_RENDERING_SERVER_URL`, `GF_RENDERING_CALLBACK_URL`, `GF_RENDERING_RENDERER_TOKEN`.

Проверка — отправить тестовый алерт со включённым «Include image» или сделать снимок/PDF-экспорт дашборда; в уведомлении или файле появляется изображение.

### Сценарий 3. Быстрый запуск (официальный пример)

```bash
docker network create grafana
docker run --network grafana --name renderer --rm --detach grafana/grafana-image-renderer:5.12.6

docker run --network grafana --name grafana --rm --detach -p 3000:3000 \
  --env GF_RENDERING_SERVER_URL=http://renderer:8081/render \
  --env GF_RENDERING_CALLBACK_URL=http://grafana:3000/ \
  grafana/grafana:13.2.3
# → оба контейнера в одной Docker-сети; Grafana видит renderer по имени
```

### Сценарий 4. Установка из бинарника

```bash
# Бинарник не содержит браузер — Chromium нужно установить отдельно
./grafana-image-renderer server \
  --server.addr=:8081 \
  --server.auth-token='<renderer-token>' \
  --browser.path=/usr/bin/chromium \
  --browser.timezone=Europe/Moscow
# → сервис слушает :8081 с указанным токеном и браузером
```

Бинарники выпускаются для Linux и Windows (amd64/arm64); macOS не поддерживается — используйте Docker Desktop. Полный список флагов и их значений по умолчанию: `./grafana-image-renderer server --help`.

### Сценарий 5. Установка через Helm

```bash
helm repo add grafana-community https://grafana-community.github.io/helm-charts
helm repo update
helm upgrade grafana grafana-community/grafana --version 13.5.0 -n monitoring \
  --set "imageRenderer.enabled=true" \
  --set "imageRenderer.renderingCallbackURL=https://grafana.example.internal/"
# → деплоится отдельный Deployment/Service рендерера, Grafana настраивается автоматически
```

Чарт сам создаёт Deployment, Service (порт 8081), при желании `ServiceMonitor` (эндпоинт `/metrics`) и probes (`healthcheckPath` по умолчанию `/healthz`). Полезные значения: `imageRenderer.image.tag` (по умолчанию `latest` — зафиксируйте версию), `imageRenderer.grafanaProtocol`/`grafanaSubPath` для корректного callback, `imageRenderer.env` для дополнительных переменных.

### Сценарий 6. Проверка связи

```bash
# 1) Сервис рендеринга доступен (в v5 health-эндпоинт — /healthz)
curl -sI http://renderer:8081/healthz
# → HTTP/1.1 200 OK

# 2) Версия сервиса и браузера
curl -s http://renderer:8081/version | jq .
# → JSON с версией сервиса и встроенного браузера

# 3) Grafana исправна (доступна ли БД)
curl -s https://grafana.example.internal/api/health
# → {"database":"ok","version":"13.2.x"}

# 4) Прямой рендеринг панели через Grafana (нужен токен или сессия)
curl -s -o panel.png \
  -H "Authorization: Bearer $GRAFANA_TOKEN" \
  "https://grafana.example.internal/render/d-solo/<uid>/<slug>?panelId=1&width=1000&height=500&from=now-1h&to=now"
# → файл panel.png с изображением панели
```

### Сценарий 7. Тюнинг рендеринга

```bash
# Сервис: увеличить время ожидания готовности страницы и ограничить размеры
./grafana-image-renderer server \
  --browser.readiness.timeout=60s \
  --browser.max-width=2000 \
  --browser.max-height=1500 \
  --log.level=debug
# → debug-логи рендеринга (для диагностики; верните info после)

# Перхостоверный (per-URL) оверрайд для конкретного медленного дашборда
./grafana-image-renderer server \
  --browser.override='^https://slow\.example\.com/.*=--browser.readiness.timeout=90s'
# → для URL, подходящих под regex, применяется более длинный таймаут
```

Ключевые флаги сервиса: `--browser.readiness.timeout` (по умолчанию `30s`), `--browser.timezone` (по умолчанию `Etc/UTC`), `--browser.min-width`/`min-height` (1000/500), `--browser.max-width`/`max-height` (3000), `--browser.page-scale-factor`/`max-page-scale-factor` (1/4), `--browser.sandbox`, `--browser.gpu`, `--server.addr` (`:8081`), `--server.auth-token`, `--log.level`, `--log.format`.

## Дополнительная информация

### Рекомендации по эксплуатации

- Выносите сервис рендеринга в отдельный контейнер/под с лимитами памяти: тяжёлые дашборды могут потреблять сотни МБ–гигабайты на один скриншот и конкурировать за память с Grafana.
- Задавайте `GOMEMLIMIT` ниже лимита контейнера (ориентир — 1 GiB на 8 GiB лимита) и не превышайте рекомендованный запас по памяти.
- Используйте отдельный длинный `renderer_token` вместо значения по умолчанию `-`; не публикуйте сервис рендеринга во внешнюю сеть.
- `callback_url` должен совпадать с внешним `root_url` Grafana (с учётом sub-path), иначе сервис не откроет дашборд.
- Включайте «Include image» только там, где картинка реально нужна (Slack/Telegram/Email) — каждый скриншот нагружает сервис.
- Мониторьте `/healthz`, `/version` и метрики сервиса (`/metrics`, `process_resident_memory_bytes`); рост памяти говорит об утечках Chromium — помогает рестарт контейнера.
- Фиксируйте конкретный тег сервиса и обновляйте его; поддерживается только последняя версия.
- Подключите Prometheus к `/metrics` сервиса (в Helm — `imageRenderer.serviceMonitor.enabled=true`) и используйте готовый дашборд «Grafana Image Renderer».

### Типичные ошибки и их решение

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| Алерты/отчёты без картинки | Сервис не настроен или недоступен | Проверить `[rendering] server_url`, `curl /healthz` сервиса |
| `401` при рендеринге | Несовпадение `renderer_token` Grafana и `AUTH_TOKEN` сервиса | Привести токены к одному значению |
| `timeout` при рендеринге, пустая картинка | Тяжёлый дашборд, занижен `--browser.readiness.timeout` (30s) | Увеличить таймаут или использовать per-URL `--browser.override`, упростить дашборд |
| Сервис не открывает дашборд | Неверный `callback_url` или нет доступа сервиса к Grafana | Указать внешний `callback_url`, проверить сеть и auth proxy/SSO |
| OOM / падение контейнера | Мало памяти, `GOMEMLIMIT` равен лимиту | Увеличить память, поставить `GOMEMLIMIT` ниже лимита, снизить параллелизм |
| `Failed to launch the browser process` / `chrome_crashpad: --database is required` | У Chromium нет записываемого домашнего каталога в контейнере | Задать `XDG_CONFIG_HOME`/`XDG_CACHE_HOME` (например `/tmp/.chromium`) или `HOME` |
| Картинка «белая», панели недогружены | Панели не успели отрисоваться, источник медленный | Увеличить `--browser.readiness.timeout`, проверить доступность источников данных |
| `502` от сервиса | Сервис упал или не запущен | `docker compose ps`, логи сервиса |
| `/healthz` возвращает 404 | Версия сервиса старше v5 (у неё health-эндпоинт `/`) | Обновить сервис до v5.x и использовать `/healthz` |

### Ограничения и особые случаи

- Сервис требует исходящий доступ к Grafana по `callback_url` и к источникам данных дашборда: он открывает дашборд как браузер и выполняет запросы панелей.
- Headless Chromium ресурсоёмок: рендеринг тяжёлых дашбордов даёт пиковое потребление памяти и CPU; на малых узлах ограничивайте параллелизм.
- Для приватных дашбордов сервис должен уметь авторизоваться (Grafana выдаёт краткоживущий render key) — иначе картинка будет пустой или отдастся по правам анонима.
- Бинарная установка не содержит браузер — Chromium/Chrome/Edge нужно установить и указать через `--browser.path`.
- Плагинный режим рендеринга удалён в Grafana 13; на 11.x/12.x/13.x применяется только внешний сервис.
- Параметры `[plugin.grafana-image-renderer]` (`rendering_mode`, `rendering_args` и т. п.) относятся к устаревшему плагинному режиму и в Grafana 13 инертны — используйте соответствующие флаги/переменные сервиса.

### Очистка и откат изменений

- Отключить картинки без удаления сервиса — выключить «Include image» в нужных contact points или `[unified_alerting.screenshots] capture = false`.
- Полностью отключить рендеринг — убрать `server_url` из `[rendering]` (Grafana вернётся к текстовым уведомлениям).
- Удалить сервис рендеринга — `docker compose rm -sf renderer` или в Helm `imageRenderer.enabled=false`.
- Ресурсы, выделенные сервису, освободить после отключения (лимиты CPU/памяти в Compose/Helm).

### Актуальность и статус

Модель внешнего `grafana-image-renderer` актуальна для Grafana 11.x/12.x/13.x; плагинный режим удалён в Grafana 13. Сервис версионируется независимо от Grafana (текущая ветка — v5.x, v5.12.6 на октябрь 2026), поддерживается только последняя версия. В проде фиксируйте конкретный тег, а не `latest`.

### Связанные темы

- [Отчёты Grafana (Reporting)](grafana_reporting.md)
- [Диагностика и устранение неполадок](grafana_troubleshooting.md)
- [Производительность и тюнинг](grafana_performance_tuning.md)
- [Унифицированный алертинг (концепции)](alerting/concepts.md)

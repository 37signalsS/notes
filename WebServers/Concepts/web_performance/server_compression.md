# Компрессия контента на веб-сервере

## Определения

**Компрессия (сжатие) контента** — процесс уменьшения объема передаваемых данных (преимущественно текстовых или структурированных бинарных) перед их отправкой клиенту по сети. В модели OSI относится к уровню представления (L6). Это один из наиболее критичных методов оптимизации веб-производительности, позволяющий сократить объем трафика на 50–90% и снизить метрики LCP (Largest Contentful Paint) и FCP (First Contentful Paint).

**Content-Encoding** — HTTP-заголовок ответа, указывающий алгоритм сжатия, примененный к телу ответа. Стандартные значения: `gzip`, `br`, `zstd`, `identity`.

**Accept-Encoding** — HTTP-заголовок запроса, через который клиент сообщает серверу, какие алгоритмы сжатия он поддерживает. Может включать весовые коэффициенты (`q-values`): `Accept-Encoding: gzip;q=1.0, *;q=0.5`.

**q-value (quality factor)** — числовое значение от 0 до 1 в заголовке `Accept-Encoding`, указывающее предпочтительность алгоритма. Чем выше значение, тем приоритетнее алгоритм для клиента.

**Vary: Accept-Encoding** — HTTP-заголовок ответа, обязательный при вариативном контенте. Информирует промежуточные кэши (прокси, CDN) о том, что ответ зависит от `Accept-Encoding`. Без него кэш может отдать сжатую версию клиенту, который не поддерживает сжатие.

**Предварительное сжатие (pre-compression / static compression)** — процесс сжатия файлов на этапе сборки или CI/CD с последующим сохранением с расширениями `.gz`, `.br` или `.zst`. Nginx/Angie отдает готовые файлы через системный вызов `sendfile()` без дополнительной нагрузки на CPU.

**Фильтр сжатия (compression filter)** — модуль веб-сервера, перехватывающий тело ответа в конвейере обработки запроса и применяющий алгоритм сжатия перед отправкой клиенту.

**Уровень сжатия (compression level)** — параметр алгоритма, определяющий соотношение между степенью сжатия и затратами CPU. Для большинства алгоритмов диапазон 1–9 или 1–22; более высокий уровень дает меньший размер, но увеличивает время сжатия.

**Основные алгоритмы сжатия (Статус 2026):**

- **Gzip:** классический алгоритм на базе DEFLATE (LZ77 + Кодирование Хаффмана). Используется как универсальный **fallback** для старых систем, ботов и легаси-инфраструктуры.
- **Brotli (`br`):** алгоритм от Google, использующий статический словарь часто встречающихся слов в вебе (HTML/CSS теги и т.д.). Обеспечивает лучшую плотность сжатия для текстовой статики.
- **Zstd (Zstandard / `zstd`):** высокопроизводительный алгоритм от Meta, использующий Finite State Entropy (FSE). С 2024–2026 годов стал **Baseline** (поддерживается всеми актуальными браузерами). Лидер по скорости декомпрессии и гибкости настройки уровней сжатия.

## Основные концепции / Архитектура

### Типы реализации компрессии

| Тип | Описание | Оптимальное применение |
| :--- | :--- | :--- |
| **Статическая (AOT)** | Сжатие выполняется заранее на этапе CI/CD или сборки проекта. | CSS, JS, шрифты (WOFF2), SVG, PDF. Позволяет использовать экстремальные уровни (Brotli 11, Zstd 19-22). |
| **Динамическая (JIT)** | Сжатие «на лету» в момент обработки запроса сервером. | HTML-документы, JSON API, персонализированные ответы. Требует низких уровней для сохранения TTFB (Zstd 3, Gzip 4). |

### Согласование контента (Content Negotiation)

Выбор алгоритма происходит через механизм заголовков HTTP/1.1+:

1.  **Запрос клиента:** `Accept-Encoding: zstd, br, gzip;q=0.5`. Параметр `q` указывает на приоритет (по умолчанию 1.0).
2.  **Ответ сервера:** выбор наиболее эффективного из общих алгоритмов и указание в `Content-Encoding: zstd`.
3.  **Заголовок Vary:** Сервер **ОБЯЗАН** отправлять `Vary: Accept-Encoding`. Это сигнализирует CDN и кэширующим прокси, что ресурс имеет разные копии под разные методы сжатия. Без этого заголовка клиент, не поддерживающий Brotli, может получить бинарный «мусор» из кэша.

### Влияние на HTTP-кэширование и ETags

Сжатие контента изменяет тело ответа, что влияет на валидаторы кэша:
- **Слабые ETags:** При динамическом сжатии Nginx/Angie автоматически превращают сильный ETag в «слабый» (например, `W/"506d70e..."`). Это позволяет выполнять условные запросы (`If-None-Match`), но не гарантирует побайтового совпадения файлов.
- **Нормализация:** Современные прокси (Varnish, Apache Traffic Server) нормализуют заголовок `Accept-Encoding`, чтобы избежать дублирования кэша для идентичных по сути запросов.
- **Решение:** Для критичных ресурсов используйте статическое сжатие (`gzip_static`, `brotli_static`, `zstd_static`), чтобы сохранить сильный ETag.

### Что НЕ следует сжимать

Повторное сжатие уже сжатых форматов неэффективно и может привести к увеличению размера файла за счет метаданных:
- **Изображения:** JPEG, PNG, WebP, AVIF.
- **Видео:** MP4, WebM.
- **Архивы:** ZIP, RAR, 7z.
- **Шрифты:** WOFF2 (уже сжат Brotli внутри).

### Shared Dictionary Transport (RFC 9509)

Механизм использования внешних словарей для сжатия:
- Клиент сообщает о наличии словаря (предыдущей версии файла) через `Available-Dictionary`.
- Сервер отправляет только **разницу (delta)**, сжатую с использованием этого словаря.
- **Результат:** Обновление JS-бандла весом 1 МБ может занять всего 10–20 КБ трафика.

### Аппаратное ускорение и Kernel TLS (KTLS)

Для снижения нагрузки на CPU в высоконагруженных системах применяются:
- **Intel QAT:** делегирование компрессии на специализированные чипы.
- **Kernel TLS (KTLS):** перенос шифрования в ядро ОС. Важно: сжатие должно выполняться в user-space **ДО** передачи данных в KTLS, так как зашифрованные данные несжимаемы.

### Сжатие в HTTP/3 (QPACK)

В отличие от HPACK (HTTP/2), QPACK в HTTP/3 оптимизирован для работы в условиях потери пакетов (устранение Head-of-Line Blocking). Он сжимает заголовки запросов и ответов, что критично для мобильных сетей, где размер заголовков (Cookie, User-Agent) может превышать размер полезной нагрузки API.

## Практические сценарии / Установка и настройка / Конфигурация

### Сценарий 1: Базовый fallback через Gzip

Настройте Gzip как обязательный минимум для всех текстовых MIME-типов. Детальная конфигурация Nginx/Angie описана в [Оптимизация сжатия в Nginx](../../Nginx/Performance/nginx_compression.md).

```nginx
http {
    gzip on;
    gzip_comp_level 4;
    gzip_min_length 1024;
    gzip_types
        text/plain
        text/css
        application/javascript
        application/json
        application/xml
        image/svg+xml;
    gzip_vary on;
    gzip_proxied any;
    gzip_http_version 1.1;
}
# → конфигурация принята, gzip активен для text/css application/javascript application/json
```

### Сценарий 2: Тройное статическое сжатие (Gzip + Brotli + Zstd)

На диске должны присутствовать `style.css`, `style.css.br` и `style.css.zst`. Nginx/Angie выберет лучший файл через `sendfile()` без участия CPU в runtime.

```bash
# Создание предварительно сжатых файлов
gzip -k -9 dist/assets/*.css dist/assets/*.js
brotli -k -q 11 dist/assets/*.css dist/assets/*.js
zstd -k -3 dist/assets/*.css dist/assets/*.js

# → созданы файлы: style.css, style.css.gz, style.css.br, style.css.zst
```

### Сценарий 3: Динамическое сжатие для API (Zstd)

Zstd оптимален для высоконагруженных API благодаря экстремальной скорости декомпрессии.

```nginx
load_module modules/ngx_http_zstd_filter_module.so;
load_module modules/ngx_http_zstd_static_module.so;

http {
    zstd on;
    zstd_comp_level 3;
    zstd_min_length 256;
    zstd_types text/plain text/css application/javascript application/json;
    zstd_vary on;
}
# → zstd активен, уровень 3 (баланс скорости/сжатия для динамики)
```

### Сценарий 4: Интеграция с CI/CD пайплайном

Добавьте предварительное сжатие в этап сборки:

```bash
#!/bin/bash
# build.sh — CI/CD этап
DIST_DIR="dist/assets"

# Сжатие статики
find "$DIST_DIR" -name "*.css" -exec gzip -k -9 {} +
find "$DIST_DIR" -name "*.js" -exec gzip -k -9 {} +
find "$DIST_DIR" -name "*.css" -exec brotli -k -q 11 {} +
find "$DIST_DIR" -name "*.js" -exec brotli -k -q 11 {} +

# Проверка результатов
ls -lh "$DIST_DIR"/main.*
# → -rw-r--r--  1 user  staff  245K Sep 23 12:00 main.css
# → -rw-r--r--  1 user  staff   52K Sep 23 12:00 main.css.gz
# → -rw-r--r--  1 user  staff   38K Sep 23 12:00 main.css.br
```

### Сценарий 5: Мониторинг компрессии в production

Настройте сбор метрик эффективности сжатия через `log_format` и `curl`:

```bash
# Проверка соотношения сжатия
curl -sI -H "Accept-Encoding: gzip, br, zstd" https://example.com/style.css | grep -i content-length
# → content-length: 38214

curl -sI https://example.com/style.css | grep -i content-length
# → content-length: 245120

# Экономия: (245120 - 38214) / 245120 = 84.4%
```

### Сценарий 6: Защита от BREACH/CRIME для чувствительных данных

Отключите сжатие для эндпоинтов, возвращающих JSON с токенами:

```nginx
location /api/auth/ {
    gzip off;
    brotli off;
    zstd off;
    # или отфильтровывайте через types
    gzip_types text/plain text/css; # только безопасные типы
}
# → для /api/auth/ сжатие отключено, защита от побочных каналов
```

## Операции и команды

### Проверка поддерживаемых алгоритмов

```bash
# Запрос с приоритетом Zstd
curl -I -H "Accept-Encoding: zstd, br, gzip" https://example.com
# → Content-Encoding: zstd
# → Vary: Accept-Encoding

# Запрос только Gzip (проверка fallback)
curl -I -H "Accept-Encoding: gzip" https://example.com
# → Content-Encoding: gzip

# Запрос без Accept-Encoding (несжатый ответ)
curl -I https://example.com
# → Content-Encoding отсутствует
```

### Диагностика конкретного ресурса

```bash
# Проверка CSS-файла
curl -sI -H "Accept-Encoding: gzip, br, zstd" https://example.com/style.css | grep -i "content-encoding\|content-length\|vary"
# → content-encoding: br
# → content-length: 38156
# → vary: Accept-Encoding

# Проверка размера несжатого файла (через Range или прямой запрос без Accept-Encoding)
curl -sI https://example.com/style.css | grep -i content-length
# → content-length: 245120

# Расчет экономии
echo "scale=1; (245120 - 38156) / 245120 * 100" | bc
# → 84.4
```

### Валидация конфигурации Nginx/Angie

```bash
# Проверка синтаксиса
nginx -t
# → nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

# Проверка загруженных модулей сжатия
nginx -V 2>&1 | grep -E "brotli|zstd|gzip"
# → --add-module=../ngx_brotli
# → --add-module=../ngx_zstd

# Проверка активных директив
grep -E "gzip|brotli|zstd" /etc/nginx/nginx.conf /etc/nginx/conf.d/*.conf
# → http { gzip on; gzip_comp_level 4; ... }
# → server { brotli on; zstd on; ... }
```

### Бенчмарк сжатия через wrk

```bash
# Сжатие gzip
wrk -t4 -c100 -d30s -H "Accept-Encoding: gzip" https://example.com/style.css
# → Latency 1.24ms, Requests/sec: 34567.89

# Сжатие brotli
wrk -t4 -c100 -d30s -H "Accept-Encoding: br" https://example.com/style.css
# → Latency 1.18ms, Requests/sec: 36892.15

# Без сжатия
wrk -t4 -c100 -d30s https://example.com/style.css
# → Latency 3.45ms, Requests/sec: 12890.44
```

### Логирование компрессии

```bash
# Логи с указанием размера ответа
tail -f /var/log/nginx/access.log | awk '{print $10}' | sort | uniq -c
# → 245120  # несжатый размер
# → 38214   # сжатый размер

# Формат лога с compression ratio
log_format compression '$remote_addr - $remote_user [$time_local] '
                       '"$request" $status $body_bytes_sent '
                       '"$http_accept_encoding"';
```

### Интеграция с Prometheus (psi-exporter)

```python
# psi_exporter.py — сбор метрик компрессии
from prometheus_client import start_http_server, Gauge
import requests, time

COMPRESSION_RATIO = Gauge('compression_ratio', 'Compression ratio', ['url', 'algorithm'])
COMPRESSION_SAVINGS = Gauge('compression_savings_percent', 'Traffic savings %', ['url'])

def collect_compression_metrics(url):
    headers = {"Accept-Encoding": "gzip, br, zstd"}
    r = requests.head(url, headers=headers)
    compressed_size = int(r.headers.get('Content-Length', 0))

    r_raw = requests.head(url)
    raw_size = int(r_raw.headers.get('Content-Length', 0))

    if raw_size > 0:
        ratio = compressed_size / raw_size
        savings = (1 - ratio) * 100
        COMPRESSION_RATIO.labels(url=url, algorithm=r.headers.get('Content-Encoding')).set(ratio)
        COMPRESSION_SAVINGS.labels(url=url).set(savings)

if __name__ == '__main__':
    start_http_server(9091)
    while True:
        collect_compression_metrics('https://example.com/style.css')
        time.sleep(60)
```

## Диагностика ошибок

| Проблема | Симптом | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Отсутствует Content-Encoding** | `curl -I` не возвращает `Content-Encoding` для текстовых ресурсов | `curl -sI -H "Accept-Encoding: gzip" https://example.com/style.css \| grep content-encoding` | Проверить `gzip on;` / `brotli on;` / `zstd on;`, убедиться что файл больше `min_length` |
| **Слабый ETag при динамическом сжатии** | ETag начинается с `W/` | `curl -sI https://example.com/api/data.json \| grep etag` | Перейти на статическое сжатие (`gzip_static`, `brotli_static`) для ресурсов, где важен ETag |
| **Клиент получает несжатый контент из кэша** | Размер ответа близок к оригиналу, хотя `Content-Encoding` присутствует | `curl -sI -H "Accept-Encoding: gzip" \| grep content-length` | Убедиться что заголовок `Vary: Accept-Encoding` присутствует в ответе |
| **Высокий CPU при сжатии** | `top` показывает высокую нагрузку на `nginx worker` | `pidstat -u 1` или `perf top` | Снизить `comp_level` для динамики (gzip 1-2, zstd 1-3), перейти на статическое сжатие |
| **Сжатие чувствительных данных (BREACH/CRIME)** | В ответе `application/json` с токенами присутствует `Content-Encoding` | `curl -sI https://example.com/api/auth \| grep -E "content-encoding\|content-type"` | Отключить сжатие для location с чувствительными данными: `gzip off; brotli off; zstd off;` |
| **Расхождение Lab/Field метрик после включения сжатия** | Lighthouse показывает высокий savings, а реальные пользователи жалуются на медленную загрузку | Сравнить `content-length` через `curl` с реальным временем загрузки в Chrome DevTools | Проверить TTFB: высокий `comp_level` может увеличить TTFB больше, чем экономия от сжатия |
| **Отсутствует Vary: Accept-Encoding** | `curl -sI` не показывает заголовок `Vary` | `curl -sI https://example.com/resource \| grep vary` | Добавить `gzip_vary on;` / `brotli_vary on;` / `zstd_vary on;` |
| **Zstd/Brotli модуль не загружен** | Ошибка `unknown directive "zstd on"` в `nginx -t` | `nginx -V 2>&1 | grep zstd` | Собрать модуль из исходного кода или использовать Angie с нативной поддержкой |
| **Сжатие слишком маленьких файлов** | Файлы < 1 КБ имеют больший размер после сжатия | `ls -l dist/assets/*.gz` и сравнить с оригиналом | Увеличить `gzip_min_length` / `zstd_min_length` до 1024, для API снизить до 256 |
| **Double compression (сжатие уже сжатого)** | Размер `.gz.gz` больше чем `.gz` | `gzip -k -9 file.css.gz && ls -l file.css.gz*` | Добавить исключения в CI/CD скрипт: `find . -name "*.gz" -o -name "*.br" -o -name "*.zst"` |

### Методология диагностики

1. **Определите тип проблемы:** конфигурация, контент, кэш или инфраструктура?
2. **Соберите метрики:** используйте `curl -I`, `curl -sI`, `nginx -t`, `grep` в логах.
3. **Валидируйте конфигурацию:** убедитесь что директивы соответствуют загруженным модулям.
4. **Внесите изменения:** примените конфигурацию, проверьте синтаксис, выполните `systemctl reload nginx`.
5. **Верифицируйте:** повторите диагностику, убедитесь что проблема устранена.

## Рекомендации

### Чеклист SRE/SysAdmin для работы с компрессией

- [ ] **Baseline метрики:** Зафиксируйте текущий compression ratio для топ-20 ресурсов до любых изменений.
- [ ] **Алгоритмы:** Gzip как fallback, Zstd для динамики (уровень 1-3), Brotli/Zstd статическое для статики.
- [ ] **Заголовки:** Убедитесь что `Vary: Accept-Encoding` отправляется для всех вариативных ресурсов.
- [ ] **ETag:** Для критичных ресурсов используйте статическое сжатие для сохранения сильного ETag.
- [ ] **Безопасность:** Отключите сжатие для location с чувствительными данными (JSON API с токенами).
- [ ] **Мониторинг:** Настройте сбор метрик compression ratio через Prometheus или cron + curl.
- [ ] **CI/CD:** Интегрируйте предварительное сжатие в пайплайн сборки.
- [ ] **Регрессия:** После каждого деплоя проверяйте `Content-Encoding` и `Content-Length` через `curl -I`.

### Оптимальные уровни сжатия

| Алгоритм | Динамика | Статика | Примечание |
| :--- | :--- | :--- | :--- |
| **Gzip** | 1–4 | 5–9 | Уровень 4 — баланс для API, уровень 9 — для статики в CI/CD |
| **Brotli** | 4–5 | 11 | Уровень 5 для динамики, 11 для статики |
| **Zstd** | 1–3 | 19–22 | Уровень 3 — оптимален для высоконагруженных API |

### Мониторинг и алертинг

```bash
# Cron-задача для сбора метрик compression ratio
# /etc/cron.d/compression-monitor
0 * * * * ops /opt/scripts/compression_check.sh >> /var/log/compression-monitor.log 2>&1
```

```bash
#!/bin/bash
# /opt/scripts/compression_check.sh
URLS=("https://example.com/style.css" "https://example.com/app.js")
THRESHOLD=50  # минимальная экономия в %

for url in "${URLS[@]}"; do
    compressed=$(curl -sI -H "Accept-Encoding: gzip, br, zstd" "$url" | grep -i content-length | awk '{print $2}' | tr -d '\r')
    raw=$(curl -sI "$url" | grep -i content-length | awk '{print $2}' | tr -d '\r')

    if [ -n "$compressed" ] && [ -n "$raw" ] && [ "$raw" -gt 0 ]; then
        savings=$(( (raw - compressed) * 100 / raw ))
        if [ "$savings" -lt "$THRESHOLD" ]; then
            echo "ALERT: $url compression savings ${savings}% < ${THRESHOLD}%"
        fi
    fi
done
```

### Откат и бэкап конфигурации

```bash
# Бэкап конфигурации перед изменением
tar czf /backup/nginx-conf-$(date +%F).tar.gz /etc/nginx/conf.d/

# Применение изменений
nginx -t && systemctl reload nginx

# Валидация
curl -sI -H "Accept-Encoding: gzip, br, zstd" https://example.com/style.css | grep content-encoding

# Откат при проблемах
git checkout /etc/nginx/conf.d/example.com.conf
systemctl reload nginx
```

### Производительность диагностических инструментов

| Инструмент | Влияние на production | Рекомендация |
| :--- | :--- | :--- |
| `curl -I` | Без влияния (HEAD запрос) | Без ограничений |
| `nginx -t` | Без влияния (только чтение конфига) | Обязательно перед reload |
| `wrk` / `ab` | Умеренная нагрузка | Использовать staging или off-peak часы |
| `pidstat` / `top` | Без влияния | Без ограничений |

## Дополнительная информация

### См. также

- **[Оптимизация сжатия в Nginx/Angie](../../Nginx/Performance/nginx_compression.md)** — детальная конфигурация модулей Gzip, Brotli, Zstd.
- **[Кэширование контента](./caching.md)** — взаимодействие компрессии с `Vary`, ETags и HTTP-кэшированием.
- **[Протоколы HTTP/2 и HTTP/3](./http2_http3.md)** — роль QPACK и HPACK в сжатии заголовков.
- [Zero-Downtime Deployment](./zero_downtime_deployment.md) — cache warming после reload.
- [Structured Logging для Performance](./structured_logging_for_performance.md) — мониторинг compression ratio через логи.

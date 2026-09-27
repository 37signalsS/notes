# Модуль image_filter в Angie: безопасность и защита от DoS

## Определения

**DoS-атака на image_filter** — тип атаки на отказ в обслуживании, при которой злоумышленник генерирует большое количество запросов с произвольными или экстремальными параметрами трансформации изображений для исчерпания ресурсов CPU и оперативной памяти сервера.

**Безопасная трансформация** — комплекс мер, включающий валидацию параметров, ограничение скорости обработки и изоляцию вычислительных ресурсов для обеспечения стабильности системы под нагрузкой.

**Cache Busting (сброс кэша)** — техника обхода кэширующего прокси, при которой злоумышленник генерирует уникальные значения параметров трансформации для каждого запроса (например, `100x100`, `100x101`, `100x102`), заставляя сервер обрабатывать каждый запрос заново вместо отдачи закэшированного результата.

**Ограничение соединений (Connection Limiting)** — механизм контроля максимального количества одновременных запросов с одного клиента, предотвращающий исчерпание пула воркеров.

**Внутренний location** — блок конфигурации с директивой `internal`, доступный только для внутренних запросов (subrequest) и недоступный для прямого доступа из внешней сети.

**Двойное проксирование как граница безопасности** — архитектурный паттерн, при котором внешний фронтенд выполняет все функции валидации и фильтрации, а внутренний сервер, принимающий запросы только через Unix-сокет или `127.0.0.1`, не имеет прямого выхода в сеть.

**Проверка подписи (secure_link)** — механизм криптографической валидации параметров запроса с использованием HMAC, полностью исключающий подбор или подделку параметров трансформации.

**Отравление кэша (Cache Poisoning)** — ситуация, при которой в кэш попадает неверный объект (например, изображение в формате AVIF для клиента, поддерживающего только JPEG), из-за некорректного ключа кэша или отсутствия заголовка `Vary: Accept`.

## Базовые концепции

### Уязвимости модуля

Модуль `image_filter` выполняет крайне ресурсоёмкие операции (resize, crop, конвертация в WebP/AVIF/HEIC) в реальном времени. Без должной защиты он становится критической точкой отказа:

- **Бесконечные вариации (Cache Busting):** Злоумышленник может менять размеры в URL (например, `100x100`, `100x101`), обходя кэш и заставляя сервер генерировать новую версию изображения для каждого уникального запроса.
- **Экстремальные размеры:** Запросы на генерацию очень больших изображений могут мгновенно забить буфер (`image_filter_buffer`) и перегрузить CPU.
- **Специфика современных кодеков:** Декомпрессия и кодирование AVIF и HEIC в Angie требуют значительно больше ресурсов CPU, чем JPEG, что делает их приоритетной целью для атак на истощение ресурсов.
- **Атаки на переполнение буфера:** Отправка аномально больших исходных файлов может привести к нехватке памяти, если `image_filter_buffer` настроен некорректно.
- **Исчерпание файловых дескрипторов:** Массовая генерация временных файлов при обработке может привести к достижению системных лимитов на количество открытых файлов.
- **Сторонние CVE в libgd:** Модуль использует библиотеку `libgd` для работы с пиксельной матрицей. Уязвимости в парсере форматов (например, буферные переполнения в WebP/AVIF/HEIC декодерах) могут привести к отказу или, в редких случаях, к выполнению произвольного кода. Регулярно применяйте патчи ОС.

### Модель угроз для image_filter

| Угроза | Цель | Вектор атаки | Воздействие |
|:-------|:-----|:-------------|:------------|
| CPU DoS через параметры | Исчерпание CPU | URL-параметры resize без валидации | Таймауты для всех клиентов |
| Memory DoS через оригиналы | Исчерпание RAM | Запрос/загрузка очень больших файлов | OOM Killer, перезапуск воркеров |
| Cache Poisoning | Отравление кэша | Отсутствие `Vary: Accept` или некорректный `proxy_cache_key` | Отдача неверного формата клиентам |
| SSRF через внешний бэкенд | Сканирование внутренней сети | `proxy_pass` на внешний источник без изоляции | Утечка информации о внутренней инфраструктуре |
| Rate Limit Bypass | Обход защиты | Распределение запросов с нескольких IP | Сохранение доступа к тяжелым операциям |

### Основные методы защиты

1. **Валидация параметров** — использование белых списков разрешённых размеров и форматов.
2. **Внутренний location** — изоляция фильтра на `127.0.0.1` или Unix-сокет с директивой `internal`, исключающая прямой доступ.
3. **Криптографическая подпись** — применение модуля `secure_link` для верификации параметров запроса.
4. **Ограничение частоты и соединений (Rate & Connection Limiting)** — лимитирование запросов и параллельных соединений к CPU-интенсивным локациям.
5. **Двухслойное кэширование** — обязательное кэширование результата трансформации на фронтенде.
6. **Мониторинг и алертинг** — отслеживание метрик через `status_zone` и API Angie.

### Архитектура безопасности

```
Клиент → [Фронтенд: limit_req + limit_conn + валидация] → [Внутренний прокси (internal/unix socket)]
                                                              ↓
                                                        [image_filter: трансформация]
                                                              ↓
                                                        [Оригинал в хранилище]
```

Ключевой принцип: фронтенд — это единственный публичный интерфейс, выполняющий все проверки. Внутренний сервер не должен быть доступен напрямую.

---

## Практические сценарии

### Сценарий: Белый список размеров через map

Наиболее производительный способ проверки множества разрешенных комбинаций параметров.

```nginx
# Определение разрешенных размеров в контексте http
map $arg_size $is_valid_size {
    default 0;
    "100x100" 1;
    "200x200" 1;
    "400x400" 1;
    "800x600" 1;
}

server {
    location ~* ^/img/ {
        if ($is_valid_size = 0) {
            return 400; # Bad Request
        }

        # Проксирование на внутренний фильтр
        proxy_pass http://127.0.0.1:8081$uri?size=$arg_size;
    }
}
```

**Валидация:**
```bash
# Проверка отклонения невалидного размера
curl -I "https://img.example.com/photo.jpg?size=999x999"
# → HTTP/1.1 400

# Проверка допустимого размера
curl -I "https://img.example.com/photo.jpg?size=400x300"
# → HTTP/1.1 200
```

### Сценарий: Защита через secure_link

Модуль `ngx_http_secure_link_module` позволяет проверять цифровую подпись запроса, сформированную приложением, что полностью исключает подбор параметров.

```nginx
location ~* ^/img/(.*)$ {
    secure_link $arg_md5,$arg_expires;
    secure_link_md5 "$secure_link_expires$uri secret_key";

    if ($secure_link = "") { return 403; } # Доступ запрещен
    if ($secure_link = "0") { return 410; } # Ссылка просрочена

    proxy_pass http://127.0.0.1:8081$uri;
}
```

**Валидация:**
```bash
# Без подписи — доступ запрещен
curl -I "https://img.example.com/img/photo.jpg"
# → HTTP/1.1 403

# С корректной подписью (сгенерированной приложением)
curl -I "https://img.example.com/img/photo.jpg?md5=abc123&expires=1700000000"
# → HTTP/1.1 200
```

### Сценарий: Жесткая валидация через регулярные выражения

Блокировка невалидных запросов на этапе сопоставления с `location` без использования `if`.

```nginx
# Разрешаем только конкретные размеры в URL: /img/100x100/photo.jpg
location ~* ^/img/(100|200|400)x(100|200|400)/(.*)$ {
    set $width $1;
    set $height $2;
    set $file_path $3;

    proxy_pass http://127.0.0.1:8081/vp/img/$width/$height/$file_path;
}
```

**Валидация:**
```bash
# Невалидный размер — 404 (location не matched)
curl -I "https://img.example.com/img/500x500/photo.jpg"
# → HTTP/1.1 404

# Валидный размер
curl -I "https://img.example.com/img/400x300/photo.jpg"
# → HTTP/1.1 200
```

### Сценарий: Rate Limiting и Connection Limiting для операций трансформации

Поскольку `image_filter` потребляет много CPU и создает нагрузку на память, для него следует устанавливать более строгие лимиты, чем для отдачи статики.

```nginx
http {
    # Ограничение частоты запросов
    limit_req_zone $binary_remote_addr zone=image_ops:10m rate=5r/s;
    
    # Ограничение одновременных соединений
    limit_conn_zone $binary_remote_addr zone=image_conns:10m;

    server {
        location /resize/ {
            limit_req zone=image_ops burst=10 nodelay;
            limit_req_status 429;
            
            limit_conn image_conns 5;
            limit_conn_status 503;
            
            proxy_pass http://127.0.0.1:8081;
        }
    }
}
```

**Валидация:**
```bash
# Превышение rate limit — 429
ab -n 100 -c 20 https://img.example.com/resize/400x300/photo.jpg
# grep "429" access.log

# Превышение connection limit — 503
curl -I https://img.example.com/resize/400x300/photo.jpg
# → HTTP/1.1 503 (при 5+ одновременных запросах с одного IP)
```

### Сценарий: Ограничение размера тела запроса

Защита от загрузки аномально больших оригиналов, которые могут исчерпать `image_filter_buffer`.

```nginx
server {
    # Ограничение размера загружаемого файла (например, 50M)
    client_max_body_size 50M;
    client_body_buffer_size 128k;

    location /upload/ {
        proxy_pass http://backend_upload;
    }
    
    location ~* ^/img/ {
        # Защита внутреннего сервера от переполнения буфера
        proxy_read_timeout 5s;
        proxy_send_timeout 5s;
        
        proxy_pass http://127.0.0.1:8081;
    }
}
```

**Валидация:**
```bash
# Попытка загрузить файл >50M
curl -X POST -F "file=@big_image.jpg" https://img.example.com/upload/
# → HTTP/1.1 413 Payload Too Large
```

### Сценарий: Изоляция через Unix-сокет с ограничением прав

Исключение сетевого оверхеда и прямого доступа к внутреннему фильтру.

```bash
# Создание сокета с правами только для пользователя angie
sudo mkdir -p /var/run/angie
sudo chown angie:angie /var/run/angie
sudo chmod 755 /var/run/angie
```

```nginx
# Внутренний сервер
server {
    listen unix:/var/run/angie/angie_img_filter.sock;
    server_name localhost;
    
    # Критично: без этого блок server может быть доступен напрямую
    # (в зависимости от версии Angie/Nginx)
    allow 127.0.0.1;
    allow ::1;
    deny all;
    
    root /var/www/images/originals;
    status_zone image_filter_backend;
    
    location ~* ^/resize/(?<w>\d+)x(?<h>\d+)/(?<file>.+)$ {
        internal;
        image_filter resize $w $h;
        image_filter_buffer 20M;
        
        error_page 415 = @empty;
    }
    
    location @empty {
        empty_gif;
    }
}
```

**Валидация:**
```bash
# Проверка прав на сокет
ls -la /var/run/angie/angie_img_filter.sock
# → srw-r----- 1 angie angie ... angie_img_filter.sock

# Проверка недоступности извне
curl --unix-socket /var/run/angie/angie_img_filter.sock http://localhost/resize/400x300/photo.jpg
# → 403 (если не из trusted контекста)

# Проверка работы через фронтенд
curl -I https://img.example.com/resize/400x300/photo.jpg
# → HTTP/2 200
```

### Сценарий: Мониторинг и алертинг через API Angie

Настройка метрик и алертов для обнаружения атак в реальном времени.

```nginx
# Внутренний сервер
server {
    listen unix:/var/run/angie/angie_img_filter.sock;
    server_name localhost;
    status_zone image_filter_backend;
    
    location ~* ^/resize/(?<w>\d+)x(?<h>\d+)/(?<file>.+)$ {
        internal;
        image_filter resize $w $h;
        image_filter_buffer 20M;
    }
}

# Фронтенд с API мониторинга
server {
    listen 127.0.0.1:8080;
    server_name localhost;
    
    location /status {
        api /status/;
        allow 127.0.0.1;
        deny all;
    }
    
    location /p8s {
        prometheus;
    }
}
```

**Prometheus-запросы для алертов:**

```yaml
# Предупреждение: рост ошибок 415 (нехватка буфера)
- alert: ImageFilterBufferExhaustion
  expr: angie_zone_responses_codes{code="415", zone="image_filter_backend"} > 5
  for: 2m
  labels:
    severity: warning
  annotations:
    summary: "Нехватка image_filter_buffer на {{ $labels.instance }}"
    description: "Более 5 ошибок 415 за 2 минуты. Проверьте размер оригиналов."

# Критично: рост latency AVIF (возможна атака)
- alert: ImageFilterLatencyHigh
  expr: histogram_quantile(0.95, sum(rate(angie_zone_responses_time_bucket{zone="image_filter_backend"}[5m])) by (le)) > 0.5
  for: 5m
  labels:
    severity: critical
  annotations:
    summary: "Latency image_filter P95 > 500ms на {{ $labels.instance }}"
    description: "Возможна атака или перегрузка AVIF-конвертером."

# Предупреждение: превышение rate limit (возможный флуд)
- alert: ImageFilterRateLimitRejected
  expr: rate(angie_zone_requests_total{zone="image_ops", status="rejected"}[1m]) > 10
  for: 1m
  labels:
    severity: warning
  annotations:
    summary: "Отброшено >10 req/s в зоне image_ops"
    description: "Возможен флуд или атака на image_filter."
```

**Валидация:**
```bash
# Проверка статуса зоны
curl -s http://127.0.0.1:8080/api/6/http/status_zones/image_filter_backend | jq '.responses | {time: .time, codes: .codes}'

# Проверка Prometheus-метрик
curl -s http://127.0.0.1:8080/p8s | grep -E "angie_zone|image_filter"
```

## Операции и команды

```bash
# Проверка статуса зоны rate limiting
curl -s http://127.0.0.1:8080/api/6/http/status_zones/image_filter_backend | jq '.responses | {time: .time, codes: .codes}'

# Проверка активных соединений в зоне лимита
curl -s http://127.0.0.1:8080/api/6/http/limit_conns/image_ops/ | jq

# Проверка, что `internal`-локации защищены (недоступны снаружи)
curl -s -o /dev/null -w "%{http_code}\n" https://img.example.com/_internal/origin.jpg
# → 404 (internal) или 403

# Проверка подписи secure_link
curl -s -o /dev/null -w "%{http_code}\n" "https://img.example.com/resize/400x300/photo.jpg?md5=...&expires=..."
# → 200 (с валидной подписью) / 403 (без)
```

## Устранение неисправностей (Troubleshooting)

| Симптом | Причина | Решение |
|:---|:---|:---|
| CPU DoS при массовых запросах уникальных размеров | Нет ограничения комбинаций размеров | Ограничить regex в `location` или использовать `secure_link` |
| 403 у легитимных клиентов | `secure_link` неправильная подпись / истекший `expires` | Проверить алгоритм MD5 и время; `$secure_link_expires` |
| Внутренний сервер доступен извне | Нет `internal` / `allow 127.0.0.1; deny all;` | Добавить `internal` и ограничить доступ по IP |
| Повышенная зона limit_req срабатывает на легитимных | Слишком строгий `rate` / burst | Проанализировать трафик, поднять `burst` |

## Лучшие практики

1.  **Всегда `internal`** для локаций с оригиналами и внутренним фильтром — недоступность извне обязательна.
2.  **Ограничивайте размеры** через `map`/regex или `secure_link` — иначе злоумышленник исчерпает CPU бесконечными уникальными ресайзами.
3.  **SSRF-защита** при скачивании оригиналов с внешних хостов: whitelist `proxy_pass`, публичный DNS-резолвер, `internal` (подробнее в Доп. информации).
4.  **Rate limiting** на публичном эндпоинте + `status_zone` для алертов: защищаете CPU и видите флуд (см. Доп. информация, а также [dos_protection.md](../dos_protection.md)).

## Дополнительная информация

### Защита от SSRF при работе с внешними бэкендами

Если Angie скачивает оригиналы с внешних ресурсов, злоумышленник может попытаться просканировать вашу внутреннюю сеть.

- **Белый список доменов:** Ограничивайте `proxy_pass` только доверенными хостами.
- **Изоляция резолвера:** Используйте публичные DNS (например, `resolver 8.8.8.8`) во внутреннем `location`, чтобы исключить разрешение имен внутренней сети.
- **Internal location:** Всегда помечайте `location`, запрашивающий оригиналы, как `internal`.

### Тюнинг ресурсов для image_filter

На уровне ОС и Angie для защиты от исчерпания ресурсов:

```bash
# Увеличение лимита открытых файловых дескрипоров
sudo sysctl -w fs.file-max=100000
echo "angie soft nofile 65536" | sudo tee -a /etc/security/limits.conf
echo "angie hard nofile 65536" | sudo tee -a /etc/security/limits.conf

# Ограничение памяти через cgroups (если используется systemd)
# /etc/systemd/system/angie.service.d/override.conf
[Service]
MemoryMax=4G
CPUQuota=400%
TasksMax=256
```

```nginx
# В основном контексте
worker_processes auto;
worker_rlimit_nofile 65536;

events {
    worker_connections 1024;
    use epoll;
    multi_accept on;
}

http {
    # Отключение буферизации для быстрого отвода ресурсов
    proxy_buffering off;
    
    server {
        location /resize/ {
            proxy_pass http://127.0.0.1:8081;
            proxy_read_timeout 5s;
            proxy_send_timeout 5s;
            
            # При ошибках фильтра возвращаем оригинал
            proxy_intercept_errors on;
            error_page 502 503 504 = @fallback;
        }
        
        location @fallback {
            internal;
            root /var/www/images/originals;
            expires 7d;
        }
    }
}
```

### Мониторинг безопасности через API Angie

Использование `status_zone` позволяет выявлять атаки в реальном времени:

1. **Метрики ошибок:** Резкий рост 415 (Unsupported Media Type) может указывать на попытки загрузки «тяжелых» файлов для перегрузки памяти.
2. **Ограничения (Rate Limit):** Отслеживайте количество отброшенных запросов в зоне `image_ops`.
3. **Время ответа (Latencies):** В Angie Pro анализируйте время обработки в зоне `status_zone image_filter_backend`. Рост среднего времени обработки AVIF сигнализирует о необходимости масштабирования или атаке.
4. **Параллельные трансформации:** Метрика `requests.current` показывает текущую нагрузку. Если она постоянно упирается в `worker_connections`, требуется горизонтальное масштабирование.

### Типовой инцидент и реагирование (Runbook)

**Симптом:** Рост latency внутреннего фильтра выше 500 мс (P95), ошибки 415 или 503, или отброс запросов в `image_ops`.

**Диагностика:**
```bash
# 1. Проверка состояния воркеров
systemctl status angie
ps aux | grep angie | wc -l

# 2. Проверка утилизации CPU и памяти
mpstat -P ALL 1 5
free -m

# 3. Проверка ошибок 415 (буфер)
curl -s http://127.0.0.1:8080/api/6/http/status_zones/image_filter_backend | jq '.responses.codes."415"'

# 4. Проверка отклоненных rate limit
curl -s http://127.0.0.1:8080/api/6/http/limit_reqs/image_ops | jq .

# 5. Проверка открытых файловых дескрипторов
cat /proc/$(pgrep -o angie)/limits | grep "open files"
ls /proc/$(pgrep -o angie)/fd | wc -l
```

**Решение (по приоритету):**
1. **При росте 415:** Увеличить `image_filter_buffer` до 20M–30M или ограничить доступные размеры через `map`.
2. **При росте latency AVIF:** Уменьшить `image_filter_avif_quality` или увеличить `image_filter_avif_speed`.
3. **При исчерпании FD/воркеров:** Увеличить `worker_rlimit_nofile` и `worker_connections`, рассмотреть горизонтальное масштабирование.
4. **При атаке Cache Busting:** Внедрить `secure_link` или жёсткую валидацию через регулярные выражения.
5. **При перегрузке ОЗУ:** Добавить `client_max_body_size` и проверить размеры оригиналов (`find /var/www/images -size +10M`).

### Очистка и откат изменений

Для отключения динамической трансформации без остановки сервиса:
1. Замените блоки с `image_filter` на статический `root` и `try_files`.
2. Очистите кэш результатов трансформации через `proxy_cache_purge` или удалите директорию кэша.
3. Убедитесь, что фронтенд корректно отдает статические файлы.

### Рекомендации по настройке буферов

- **`image_filter_buffer`:** Устанавливайте значение адекватно вашим оригиналам (обычно `15M–20M`). Избегайте слишком больших значений, так как память выделяется на каждый процесс обработки.
- **Внутренняя сеть:** Слушайте внутренним сервером только `127.0.0.1` или Unix-сокет, чтобы закрыть прямой доступ к ресайзеру.

### См. также

- [Обзор модуля image_filter](./overview.md)
- [Защита от DoS-атак в Angie](../dos_protection.md)
- [Производительность и масштабирование](./performance.md)

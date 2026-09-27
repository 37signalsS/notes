# Модуль image_filter в Angie: конфигурация внутреннего сервера

## Определения

**Внутренний сервер фильтрации (Image Filter Backend)** — изолированный экземпляр или блок `server` в Angie, предназначенный исключительно для выполнения ресурсозатратных операций трансформации медиаконтента. Работает на внутреннем порту (например, 8081) или через Unix-сокет, что исключает прямой доступ пользователей к оригиналам.

**Внутренняя трансформация** — архитектурный паттерн доставки контента, при котором внешний фронтенд выполняет роль интеллектуального кэширующего прокси, а внутренний сервер — роль специализированного графического процессора для CPU-интенсивной обработки.

**Директива `internal`** — механизм безопасности Angie/Nginx, который запрещает прямой доступ к location из внешних запросов. Даже если Unix-сокет или TCP-порт внутреннего сервера будут экспонированы, запросы напрямую получат 403/404, что критично для предотвращения обхода фронтенда.

## Базовые концепции

### Модель памяти и параллелизм

Модуль `image_filter` работает в контексте воркера Angie. Каждый воркер обрабатывает ровно одну трансформацию за раз. Директива `image_filter_buffer` выделяет память из стека/кучи процесса воркера, а не из разделяемой памяти между воркерами. Это означает:

- **Нет гонок за память:** Две параллельные трансформации в разных воркерах используют изолированные буферы.
- **Влияние на cgroup:** При ограничении памяти через cgroup v2 (`MemoryMax`), суммарное потребление всех воркеров должна укладываться в лимит. Для трансформации AVIF изображения 20МБ буфера может потреблять до 80–120 МБ RSS из-за промежуточных представлений в libgd.
- **Правило масштабирования:** При увеличении количества воркеров линейно увеличивается потенциальное потребление оперативной памяти. Для `worker_processes auto` на 8-ядерном сервере с буфером 20M максимальное теоретическое потребление: 8 воркеров × 120 МБ = ~1 ГБ только для трансформаций.

### Модель libgd и thread-safety

Библиотека libgd, на которой построен `image_filter`, не является полностью thread-safe в старых версиях. Angie обходит это, используя модель **один воркер — один запрос**, и никогда не обрабатывает два изображения в одном потоке одновременно. Однако:

- Версия libgd в системе должна совпадать с той, против которой собирался модуль `image_filter`. Mismatch может привести к падениям (SIGSEGV) при работе с определенными форматами.
- Поддержка AVIF/HEIC требует libgd с патчами или сборкой через libavif/libheif. Проверка поддерживаемых форматов:
  ```bash
  angie -V 2>&1 | grep -E "image_filter|libgd"
  # или через LD_PREVIEW:
  ldd /usr/lib/angie/modules/ngx_http_image_filter_module.so | grep -E "gd|avif|heif"
  ```

### Жизненный цикл запроса трансформации

```
1. Клиент → Фронтенд (Accept: image/avif)
2. Фронтенд: MISS в кэше → proxy_pass на Unix-сокет
3. Внутренний сервер: принимает запрос через сокет
4. Воркер загружает оригинал из root в RAM
5. Декомпрессия оригинала (JPEG/PNG/WebP → bitmap)
   - Размер bitmap = ширина × высота × 4 байта (RGBA)
   - Для 4032×3024 (12 МП): ~46 МБ uncompressed
6. Применение операций: resize, crop, rotate, sharpen
7. Кодирование в целевой формат (AVIF/WebP/HEIC)
8. Отправка результата фронтенду
9. Фронтенд: запись в proxy_cache, отдача клиенту
```

Важно: на шаге 5 декомпрессия может превысить `image_filter_buffer`, если оригинал имеет высокое разрешение и буфер установлен ниже размера uncompressed bitmap. Директива `image_filter_buffer` защищает только от переполнения, но не от преждевременной ошибки, если буфер меньше оригинала.

### Unix-сокет против TCP loopback

| Критерий | Unix-сокет | TCP (127.0.0.1) |
|:---------|:-----------|:-----------------|
| Оверхед | Нет (AF_UNIX) | SYN/SYN-ACK/ACK + TCP state machine |
| TIME_WAIT | Нет | Да, при частых переподключениях |
| Пропускная способность | Ограничена только fs.file-max и sock buffers | Дополнительно net.ipv4.tcp_rmem/tcp_wmem |
| Безопасность | Права на файл сокета (chmod/chown) | Необходимы firewall/iptables rules |
| Мониторинг | `ss -xl` | `ss -xl` и `ss -tnp` |
| Производительность | +15–20% по latency и throughput | Базовый уровень |

Unix-сокет предпочтителен для High Load, так как исключает TCP handshake overhead и проблемы с исчерпанием портов (TIME_WAIT exhaustion).

### Архитектурные принципы

**Single Responsibility Principle:** Внутренний сервер должен выполнять ТОЛЬКО трансформации. В нем не должно быть:
- SSL/TLS termination (если не требуется end-to-end шифрование)
- Gzip/Brotli сжатия (лишний CPU при уже сжатых AVIF/WebP)
- rate limiting (это задача фронтенда)
- кэширования (ответ внутреннего сервера кэшируется фронтендом)

**Правило `internal`:** Все location с `image_filter` должны иметь директиву `internal`. Это предотвращает прямой доступ к внутреннему серверу, даже если сокет意外но станет доступен извне.

### Трейдофы форматов кодирования

| Формат | Скорость encode | Размер файла | Поддержка браузерами | Особенности libgd |
|:-------|:---------------|:-------------|:---------------------|:------------------|
| JPEG | Базовая | Высокий | 100% | Нет прогрессивного по умолчанию |
| WebP | Быстрая | Средний | Chrome, Firefox, Edge | Нужен libgd с WebP support |
| AVIF | Медленная (speed 0–10) | Низкий | Chrome 85+, Firefox 125+ | Нужен libavif, CPU-intensive |
| HEIC | Средняя | Низкий | Safari, iOS | Нужен libheif, патенты Apple |

Для High Load рекомендуется AVIF с `image_filter_avif_speed 8–10` (быстрее, чуть больше размер) или WebP как баланс между скоростью и сжатием.

## Практические сценарии

### Сценарий 1: Комплексная конфигурация через Unix-сокет

Пример высокопроизводительной конфигурации, поддерживающей современные форматы и нативный мониторинг.

```nginx
server {
    # Слушаем Unix-сокет для снижения нагрузки на CPU
    listen unix:/var/run/angie_img_filter.sock;
    server_name localhost;

    # Путь к исходным изображениям высокого качества
    root /var/www/images/originals;

    # Общая зона мониторинга для всех операций фильтрации
    status_zone image_filter_backend;

    # Ограничение доступа: только из локального пространства
    allow 127.0.0.1;
    allow ::1;
    deny all;

    # 1. Изменение размера JPEG с прогрессивной загрузкой
    location ~* ^/resize/(?<w>\d+)/(?<h>\d+)/(?<file>.+\.jpg)$ {
        internal;
        alias /var/www/images/originals/$file;
        image_filter resize $w $h;
        image_filter_jpeg_quality 85;
        image_filter_interlace on;
        image_filter_sharpen 1;
        image_filter_buffer 15M;

        error_page 415 = @empty;
    }

    # 2. Конвертация в AVIF (оптимально для современных браузеров)
    location ~* ^/convert/avif/(?<file>.+\.(png|jpg))$ {
        internal;
        alias /var/www/images/originals/$file;
        image_filter convert avif;
        # Качество 60, скорость кодирования 8 (баланс CPU/размер)
        image_filter_avif_quality 60 8;
        image_filter_buffer 20M;

        error_page 415 = @empty;
    }

    # 3. Конвертация в HEIC (высокая эффективность сжатия)
    location ~* ^/convert/heic/(?<file>.+\.png)$ {
        internal;
        alias /var/www/images/originals/$file;
        image_filter convert heic;
        image_filter_heic_quality 75;
        image_filter_buffer 20M;

        error_page 415 = @empty;
    }

    # Возврат прозрачного пикселя 1x1 при ошибках трансформации
    location @empty {
        internal;
        default_type image/gif;
        return 200 "\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\xff\xff\xff\x21\xf9\x04\x01\x00\x00\x00\x00\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02\x44\x01\x00\x3b";
    }
}
```

**Валидация:**
```bash
# Проверка прав на сокет
ls -la /var/run/angie_img_filter.sock
# → srw-r----- 1 angie angie ... angie_img_filter.sock

# Прямой доступ должен быть запрещен
curl --unix-socket /var/run/angie_img_filter.sock http://localhost/resize/400x300/photo.jpg
# → 403 Forbidden (location имеет internal)

# Проверка работы через фронтенд
curl -I https://img.example.com/resize/400x300/photo.jpg
# → HTTP/2 200
```

### Сценарий 2: systemd-интеграция и cgroup v2

Angie запускается через systemd. Для изоляции ресурсов внутреннего сервера (который является частью того же процесса) используются параметры systemd slice и параметры Angie:

```ini
# /etc/systemd/system/angie.service.d/override.conf
[Service]
# Квота CPU: максимум 4 ядра на 100%
CPUQuota=400%

# Лимит памяти: с запасом под воркеры и кэши
MemoryMax=4G
MemorySwapMax=0

# Количество открытых файлов для тысяч параллельных запросов
LimitNOFILE=65536

# Приоритет планировщика (nice = -5 для выше приоритета)
Nice=-5
IOSchedulingClass=real-time
IOSchedulingPriority=2

# Включение cgroup v2 delegation
Delegate=yes
```

```bash
# Применение изменений
systemctl daemon-reload
systemctl restart angie

# Проверка cgroup
systemctl show angie -p MemoryMax,CPUQuota,LimitNOFILE
# → MemoryMax=4G CPUQuota=400% LimitNOFILE=65536
```

**Важно:** `image_filter_buffer` не ограничивает совокупное потребление памяти всеми воркерами. Если `worker_processes auto` создаст 8 воркеров, каждый с буфером 20M, потенциальное потребление составит 8 × (буфер + libgd overhead). cgroup лимит защищает от OOM.

### Сценарий 3: Логирование трансформаций

Добавление кастомного `log_format` для детального аудита операций `image_filter`:

```nginx
http {
    log_format filter_trace escape=json '{'
        '"time": "$time_iso8601", '
        '"remote_addr": "$remote_addr", '
        '"request": "$request", '
        '"status": $status, '
        '"body_bytes_sent": $body_bytes_sent, '
        '"request_time": $request_time, '
        '"upstream_response_time": "$upstream_response_time", '
        '"upstream_addr": "$upstream_addr", '
        '"image_filter_op": "$image_filter", '
        '"image_filter_buffer": "$image_filter_buffer", '
        '"content_type": "$content_type", '
        '"content_length": "$content_length", '
        '"http_accept": "$http_accept", '
        '"http_x_forwarded_for": "$http_x_forwarded_for"'
    '}';

    server {
        listen unix:/var/run/angie_img_filter.sock;
        server_name localhost;

        access_log /var/log/angie/filter_backend.log filter_trace;
        error_log /var/log/angie/filter_backend.error.log warn;

        status_zone image_filter_backend;

        location ~* ^/resize/(?<w>\d+)/(?<h>\d+)/(?<file>.+\.jpg)$ {
            internal;
            image_filter resize $w $h;
            image_filter_jpeg_quality 85;
            image_filter_interlace on;
            image_filter_sharpen 1;
            image_filter_buffer 15M;
            error_page 415 = @empty;
        }
    }
}
```

**Анализ логов:**
```bash
# Топ-10 самых долгих трансформаций
awk -F'"' '{print $4, $12, $16}' /var/log/angie/filter_backend.log | \
  sort -t' ' -k3 -nr | head -10

# Частота ошибок 415 по часам
grep '"status": 415' /var/log/angie/filter_backend.log | \
  awk -F'"' '{print $2}' | cut -d: -f1-2 | \
  sort | uniq -c
```

### Сценарий 4: Health Check и readiness probe

Добавление эндпоинтов для оркестраторов и мониторинга доступности внутреннего сервера:

```nginx
server {
    listen unix:/var/run/angie_img_filter.sock;
    server_name localhost;

    # Health check: проверяем, что модуль загружен
    location = /health {
        internal;
        return 200 'OK';
        add_header Content-Type text/plain;
    }

    # Readiness: проверяем, что можем обработать трансформацию
    # (опционально: тестовый resize маленького изображения)
    location = /ready {
        internal;
        # Можно вернуть 200 только если /health доступен
        return 200 'READY';
        add_header Content-Type text/plain;
    }
}
```

**Использование:**
```bash
# Проверка через сокет
curl --unix-socket /var/run/angie_img_filter.sock http://localhost/health
# → OK

# Для systemd health check (в override.conf):
# HealthCheckIntervalSec=10
# HealthCheckStartupIntervalSec=5
```

### Сценарий 5: Развертывание через Ansible

Пример роли Ansible для конфигурации внутреннего фильтра:

```yaml
# tasks/main.yml
- name: Ensure filter socket directory exists
  file:
    path: /var/run/angie
    state: directory
    owner: angie
    group: angie
    mode: '0755'

- name: Deploy filter backend configuration
  template:
    src: filter_backend.conf.j2
    dest: /etc/angie/conf.d/filter_backend.conf
    owner: root
    group: root
    mode: '0644'
  notify: Reload angie

- name: Ensure log directory exists
  file:
    path: /var/log/angie
    state: directory
    owner: angie
    group: angie
    mode: '0755'

- name: Set image_filter_buffer fact based on target env
  set_fact:
    filter_buffer: "{{ '20M' if ansible_processor_vcpus > 4 else '10M' }}"

# handlers/main.yml
- name: Reload angie
  systemd:
    name: angie
    state: reloaded
```

### Сценарий 6: Диагностика неработающих трансформаций

Пошаговый план диагностики, когда трансформация возвращает 415 или 500:

```bash
# 1. Проверка доступности модуля
angie -V 2>&1 | grep image_filter
# → --with-http_image_filter_module

# 2. Проверка libgd и поддержки форматов
ldd /usr/lib/angie/modules/ngx_http_image_filter_module.so | grep -E "gd|avif|heif"
# → должны быть найдены libgd.so, libavif.so, libheif.so

# 3. Проверка размера оригинального изображения
file /var/www/images/originals/photo.jpg
# → JPEG image data, Exif standard, aspect ratio, density 300x300, segments
identify -verbose /var/www/images/originals/photo.jpg | grep -E "Geometry|Filesize|Depth"
# → Geometry: 4032x3024, Filesize: 4.2MB, Depth: 8-bit

# 4. Проверка прав на файл
ls -la /var/www/images/originals/photo.jpg
# → -rw-r--r-- 1 angie angie ... photo.jpg

# 5. Тест через Unix-сокет напрямую
curl --unix-socket /var/run/angie_img_filter.sock "http://localhost/resize/400/300/photo.jpg" -I
# → HTTP/1.1 200 (если internal не блокирует, что не должно происходить)

# 6. Проверка статус-зоны
curl -s http://127.0.0.1:8080/api/6/http/status_zones/image_filter_backend | jq .
# → ищем рост codes.415

# 7. Проверка логов
tail -f /var/log/angie/filter_backend.error.log | grep -E "image_filter|gdImage|AVIF|HEIC"
# → ищем libgd errors, memory allocation failures
```

**Типичные ошибки и решения:**

| Симптом | Причина | Решение |
|:--------|:--------|:--------|
| HTTP 415 | `image_filter_buffer` меньше размера оригинала | Увеличить буфер или ограничить доступные размеры через `map` |
| HTTP 500, libgd error | Некорректный оригинал (CMYK JPEG, 16-bit PNG) | Конвертировать оригиналы в sRGB 8-bit перед ingest |
| Высокий CPU | Неудачная `image_filter_avif_speed` (0–3) | Увеличить speed до 8–10 для AVIF |
| OOM Killer убил Angie | Суммарный буфер воркеров + кэш превышает RAM | Уменьшить `worker_processes` или `image_filter_buffer` |
| Пустой ответ | `error_page 415` сработал на большом файле | Проверить `image_filter_buffer` и размер оригиналов |

### Сценарий 7: cgroup v2 и ограничение памяти

Если Angie работает в контейнере или на системе с cgroup v2, важно настроить delegation и лимиты:

```bash
# Включение cgroup v2 (если не включено)
grubby --update-kernel=ALL --args="systemd.unified_cgroup_hierarchy=1"

# Создание slice для Angie
systemctl set-property angie.service MemoryMax=4G CPUQuota=400%

# Проверка
systemctl show angie.service -p MemoryMax,CPUQuota
# → MemoryMax=4294967296 CPUQuota=400%

# Мониторинг потребления памяти
systemd-cgtop -b
# или
cat /sys/fs/cgroup/angie.service/memory.current
```

**Расчет лимитов:**
- `image_filter_buffer` × `worker_processes` × коэффициент overhead (3–5 для libgd)
- Пример: 8 воркеров × 20M буфер × 4 overhead = 640 МБ только для буферов
- Добавить кэш proxy_cache: 1–2 ГБ
- Итого: 3–4 ГБ для High Load backend

### Сценарий 8: Альтернативный fallback: SVG-плейсхолдер

Вместо GIF 1x1 можно использовать SVG для векторного placeholder с поддержкой прозрачности и масштабирования:

```nginx
location @empty {
    internal;
    default_type image/svg+xml;
    return 200 '<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1" viewBox="0 0 1 1"><rect width="1" height="1" fill="%23cccccc"/></svg>';
}
```

**Сравнение:**
- GIF 1x1: 43 байта, поддерживается везде, но не масштабируется без потерь
- SVG placeholder: ~120 байт, векторный, поддерживает цвет из URL параметра (если реализовать через subrequest)
- Transparent PNG 1x1: 68 байт, подходит для PNG fallback

Для production рекомендуется GIF или PNG 1x1 из-за кэшируемости и предсказуемости размера.

## Операции и команды

```bash
# Смоук-тесты различных трансформаций
curl -s -o /dev/null -w "%{http_code} %{content_type}\n" \
  https://img.example.com/resize/400x300/photo.jpg         # → 200 image/jpeg
curl -s -o /dev/null -w "%{http_code} %{content_type}\n" \
  -H "Accept: image/webp" https://img.example.com/resize/400x300/photo.jpg   # → 200 image/webp

# Проверка ограничений размеров (regex в location)
curl -s -o /dev/null -w "%{http_code}\n" \
  https://img.example.com/resize/999999x999999/photo.jpg   # → 403/404 (regex не совпал)

# Статусы фильтра через Status API (как в Дополнительной информации)
curl -s http://127.0.0.1:8080/api/6/http/location_zones/img_filter/ | jq '.responses.codes'
```

## Устранение неисправностей (Troubleshooting)

| Симптом | Причина | Решение |
|:---|:---|:---|
| `415 Unsupported Media Type` | Оригинал больше `image_filter_buffer` | Поднять `image_filter_buffer` до 20M |
| Пустой placeholder вместо картинки | Трансформация упала, сработал `@empty` | Проверить `error_log`; увеличить таймаут `proxy_read_timeout` на фронте |
| `403` при запросе слишком большого размера | Regex-ограничения в location отклонили | Сообщить клиенту допустимые размеры (в коде) |
| Медленный ответ на больших AVIF | `avif_speed` слишком низкий (сжатие медленное) | Поднять `avif_speed` в ущерб сжатию, уменьшить размеры |

## Лучшие практики

1.  **Всегда комбинируйте** ограничение размеров (regex/map) + `image_filter_buffer` + placeholder fallback — это закрывает CPU DoS и даёт предсказуемый UX.
2.  **Placeholder через `@`-location** (`internal`) — долго живёт в кэше и не требует статических файлов; используйте SVG/PNG 1x1.
3.  **Таймауты фронта** ставьте с запасом: генерация AVIF может занимать сотни мс (`proxy_read_timeout 5s` упоминается в Доп. информации).
4.  **Следите за `responses.codes.415`** в Status API — рост значит нехватку буфера или плохие оригиналы.

## Дополнительная информация

### Наблюдаемость через API Angie

Включение `status_zone` позволяет отслеживать работу сервера в реальном времени:
- **`responses.time`**: Среднее время обработки бэкенда (фильтра). Важно для тюнинга `avif_speed`.
- **`responses.codes.415`**: Количество ошибок Unsupported Media Type (часто указывает на нехватку `image_filter_buffer`).
- **`requests.current`**: Текущее количество активных трансформаций.

### Рекомендации по оптимизации

- **Таймауты:** Устанавливайте адекватные `proxy_read_timeout` на фронтенде (например, 5s), так как генерация тяжелого AVIF может занимать сотни миллисекунд.
- **Буфер:** Директива `image_filter_buffer` критична. Если размер оригинала больше буфера, трансформация не произойдет. В 2026 году устанавливайте не менее `20M`.
- **Безопасность:** Доступ к внутреннему серверу должен быть ограничен через `allow 127.0.0.1; deny all;` или использование Unix-сокетов с ограниченными правами доступа. Директива `internal` обязательна.
- **Воркеры:** Для CPU-интенсивных трансформаций AVIF используйте `worker_processes` равным количеству физических ядер. Избегайте hyper-threading для этих воркеров.
- **Кэширование:** Никогда не размещайте `image_filter` и `proxy_cache` в одном location. Это антипаттерн, приводящий к кэшированию необработанного оригинала.

### См. также

- [Безопасность и защита от DoS](./security.md)
- [Производительность и масштабирование](./performance.md)
- [Конфигурация фронтенда и кэширование](./site_configuration.md)

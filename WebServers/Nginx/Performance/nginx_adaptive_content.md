# Адаптивная доставка изображений в Nginx (AVIF, WebP, JPEG XL)

**Актуально для:** Nginx 1.26+ / 1.30+

## Определения

**Адаптивная (условная) доставка изображений (Adaptive Image Delivery)** — архитектурная стратегия оптимизации веб-производительности, при которой веб-сервер Nginx анализирует заголовок запроса `Accept` и прозрачно отдает клиенту наиболее компактный и эффективный формат сжатия (AVIF, WebP, JPEG XL) из предварительно подготовленных копий на диске, сохраняя единый публичный URL ресурса.

**Content Negotiation (согласование контента)** — стандартизированный механизм протокола HTTP (RFC 9110, раздел 12.5.1), позволяющий клиенту и серверу согласовать оптимальное представление ресурса на основе возможностей клиентского ПО, указанных в заголовках `Accept`, `Accept-Encoding` и весовых коэффициентах качества (`q-values`).

**AVIF (AV1 Image File Format)** — современный формат растровой графики на базе открытого видеокодека AV1 (спецификация RFC 9297). Обеспечивает максимальную плотность сжатия: в среднем на 20–35% компактнее WebP и на 50–70% компактнее JPEG при идентичном визуальном качестве (метрики SSIMULACRA2, Butteraugli). Поддерживает 10/12-битный цвет, HDR и прозрачность. Поддерживается в Chrome 85+, Edge 121+, Firefox 93+, Safari 16.4+.

**WebP** — формат сжатия изображений от Google (спецификация RFC 9561), использующий алгоритмы сжатия VP8 (lossy) и LZ77/Хаффмана (lossless). Выступает универсальным стандартом и обязательным fallback-форматом для браузеров и мобильных WebView, не поддерживающих кодек AV1. Поддерживается во всех актуальных браузерах (Chrome 32+, Firefox 65+, Safari 16+, Edge 18+).

**JPEG XL (JXL)** — формат растровых изображений (ISO/IEC 18181), поддерживающий побайтовое обратимое пережатие существующих JPEG без потерь данных (lossless transcoding), прогрессивное декодирование и широкую цветовую гамму. В 2026 году поддержка в браузерах остаётся фрагментированной (Safari 17+, Chrome за флагом `#enable-jxl-image-format`, Firefox за флагом `image.jxl.enabled`). Применяется в production только при подтверждённой аудитории.

**Vary: Accept** — обязательный HTTP-заголовок ответа (RFC 9110, раздел 12.5.5), информирующий промежуточные кэширующие прокси (Nginx reverse proxy, Varnish, Squid) и локальные кэши браузеров о том, что бинарное тело ответа по данному URL зависит от значения клиентского заголовка `Accept`. Без этого заголовка возникает дефект отравления кэша.

**Отравление кэша (Cache Poisoning)** — архитектурный сбой промежуточного или браузерного кэша, при котором вариант ответа, сгенерированный для современного клиента (например, `image/avif` для Chrome), сохраняется под общим URL без разделения по `Accept` и ошибочно отдается клиенту, не поддерживающему этот формат (например, устаревшему клиенту или боту), что приводит к поломке отображения графики.

**Статическая адаптивная доставка (AOT Image Delivery)** — подход, при котором полный набор вариантов сжатия (AVIF, WebP, оптимизированный JPEG) генерируется заблаговременно (Ahead-of-Time) на этапе сборки проекта, в CI/CD пайплайне или локальным системным демоном на сервере. Веб-сервер Nginx выполняет исключительно проверку наличия файла на диске и отдачу контента, исключая вычислительную нагрузку на процессор (CPU) в момент обработки пользовательского запроса.

**Zero-Copy (sendfile)** — механизм ядра Linux, позволяющий передавать данные из страничного кэша (Page Cache) напрямую в буфер сетевого сокета через системный вызов `sendfile(2)`, минуя копирование данных в адресное пространство пользовательского процесса Nginx и сокращая переключения контекста.

**open_file_cache** — механизм Nginx для кэширования дескрипторов открытых файлов, их размеров, времени модификации и информации о существовании каталогов в оперативной памяти процесса worker. Исключает лавину системных вызовов `stat(2)` при последовательной проверке вариантов в директиве `try_files`.

**Stat-storm (лавина системных вызовов)** — резкий всплеск системных вызовов `stat(2)` или `newfstatat(2)`, возникающий при проверке множества альтернативных путей файлов в директиве `try_files` под высоким RPS, приводящий к деградации производительности подсистемы VFS ядра Linux при отсутствии или неправильной настройке `open_file_cache`.

---

## Основные концепции

### Жизненный цикл запроса в архитектуре Nginx

В чистом Nginx OSS отсутствует встроенный модуль для динамической модификации растровых изображений (в отличие от Angie с модулем `image_filter` или специализированных сервисов вроде `imgproxy`). Поэтому высокопроизводительная адаптивная доставка строится на комбинации директив `map`, `try_files` и статического модуля `ngx_http_static_module`.

```
[ HTTP-запрос клиента ] 
      │ Header: Accept: image/avif,image/webp,image/*,*/*;q=0.8
      ▼
┌─────────────────────────────────────────────────────────────┐
│ 1. NGX_HTTP_REWRITE_PHASE (Директива map)                   │
│    • Ленивое вычисление переменной $img_suffix              │
│    • Анализ первого совпадения regex по Accept              │
│    • Результат: $img_suffix = ".avif" (или ".webp" / "")    │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ 2. NGX_HTTP_PRECONTENT_PHASE (Директива try_files)          │
│    • Проверка пути 1: /images/photo.jpg.avif                │
│      ├── Проверка через open_file_cache (VFS / Inode)       │
│      └── Если найден ──> Переход к отдаче                   │
│    • Проверка пути 2 (fallback): /images/photo.jpg          │
│      └── Если найден ──> Переход к отдаче                   │
│    • Если ничего не найдено ──> 404 Not Found               │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ 3. NGX_HTTP_CONTENT_PHASE (ngx_http_static_module)          │
│    • Определение Content-Type по финальному расширению      │
│      (из mime.types: .avif -> image/avif)                   │
│    • Вызов sendfile(2) для передачи байтов из Page Cache    │
│    • Добавление заголовков: Vary: Accept, Cache-Control     │
└─────────────────────────────────────────────────────────────┘
```

1. **Фаза сопоставления (`NGX_HTTP_REWRITE_PHASE`):** При первом обращении к переменной `$img_suffix` Nginx выполняет ленивую оценку директивы `map`. Строка клиентского заголовка `$http_accept` сопоставляется с регулярными выражениями. Первое совпавшее правило фиксирует значение суффикса.
2. **Фаза проверки доступности (`NGX_HTTP_PRECONTENT_PHASE`):** Обработчик `ngx_http_try_files_handler` последовательно тестирует существование файлов на диске. Если активен `open_file_cache`, проверка выполняется по хэш-таблице в памяти воркера; при промахе выполняется системный вызов `newfstatat(2)`.
3. **Фаза генерации ответа (`NGX_HTTP_CONTENT_PHASE`):** Статический модуль открывает файл, извлекает MIME-тип из глобальной таблицы `mime.types` по расширению отдаваемого файла и формирует заголовки.
4. **Передача по сети:** Через системные вызовы `sendfile(2)` и `writev(2)` ядро упаковывает HTTP-заголовки и тело изображения в TCP-сегменты с учетом директив `tcp_nopush` и `tcp_nodelay`.

---

### Системный уровень: Ядро Linux, Page Cache и дисковый ввод-вывод

Для инженера SRE и системного администратора отдача статических медиафайлов под нагрузкой упирается в системные вызовы ядра, пропускную способность шины памяти и дисковый I/O.

#### 1. Zero-Copy и оптимизация сетевого стека

```nginx
sendfile    on;
tcp_nopush  on;
tcp_nodelay on;
```

*   **`sendfile on;`**: Передача данных происходит целиком внутри ядра Linux: данные считываются с диска в страничный кэш (Page Cache), после чего DMA-контроллер копирует их напрямую в кольцевой буфер сетевой карты (ring buffer NIC). Контекст процессора не переключается между режимом ядра и пространством пользователя, исключая двойное копирование данных в буфер Nginx.
*   **`tcp_nopush on;`**: На Linux активирует сокетную опцию `TCP_CORK`. Nginx накапливает данные и отправляет полный HTTP-заголовок ответа и начальные сегменты файла в одном максимально заполненном TCP-пакете (MSS — Maximum Segment Size), предотвращая фрагментацию сети.
*   **`tcp_nodelay on;`**: Отключает алгоритм Нагла для keep-alive соединений. В связке с `tcp_nopush` Nginx отправляет полные пакеты без задержек, а для финального неполного пакета сбрасывает флаг `TCP_CORK`, обеспечивая минимальный Time to First Byte (TTFB).

#### 2. Защита от Stat-Storm через open_file_cache

Директива `try_files $uri$img_suffix $uri =404;` при каждом входящем запросе выполняет до двух проверок существования файлов. При потоке в $15\,000\text{ RPS}$ веб-сервер генерирует до $30\,000\text{ syscalls/sec}$ (`newfstatat`). Это приводит к деградации dentry cache и скачку `sys%` CPU.

```nginx
open_file_cache          max=50000 inactive=60s;
open_file_cache_valid    30s;
open_file_cache_min_uses 2;
open_file_cache_errors   on;
```

*   **`max=50000`**: Максимальное количество элементов (дескрипторы, метаданные inode, ошибки 404) в LRU-кэше воркера. Память: около $1\text{ КБ}$ на запись ($\approx 50\text{ МБ}$ RAM на рабочий процесс).
*   **`inactive=60s`**: Время, по истечении которого неиспользуемый дескриптор вытесняется из кэша.
*   **`open_file_cache_valid 30s`**: Интервал валидации актуальности метаданных файла на диске. В течение 30 секунд Nginx вообще не обращается к файловой системе при повторных запросах.
*   **`open_file_cache_min_uses 2`**: Порог обращений внутри интервала `inactive` для сохранения дескриптора в кэше.
*   **`open_file_cache_errors on`**: Кэширование негативных результатов (ENOENT). Предотвращает повторные дисковые поиски несуществующих файлов вариантов.

#### 3. Эффективность Page Cache и файловые системы

*   **Плотность Page Cache:** Замена JPEG ($1.2\text{ МБ}$) на AVIF ($380\text{ КБ}$) снижает объем требуемой памяти для хранения горячего набора (working set) в 3 раза. На сервере с $64\text{ ГБ}$ RAM в страничном кэше удерживается втрое больше уникальных изображений, сводя дисковые чтения к нулю ($100\%$ cache hit ratio в RAM).
*   **Опции монтирования хранилища:** Директории с медиаконтентом на файловых системах ext4/XFS необходимо монтировать с опцией `noatime`. Это предотвращает операцию записи метаданных времени доступа (`atime`) при каждом чтении изображения через `sendfile`.

---

### Сравнение форматов и поддержка клиентами

| Формат | MIME-тип | Сжатие относительно JPEG | Алгоритм / Кодек | Поддержка браузерами (2026) | Роль в контуре доставки |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **AVIF** | `image/avif` | **-50% ... -70%** | AV1 (intra-frame, 10-bit) | Chrome 85+, Firefox 93+, Safari 16.4+, Edge 121+ | **Приоритетный:** максимальное сжатие для фото и баннеров |
| **WebP** | `image/webp` | **-25% ... -40%** | VP8 / VP8L | Практически 100% современных браузеров | **Универсальный fallback:** для старых клиентов и Android Webview |
| **JPEG XL** | `image/jxl` | **-55% ... -75%** | VarDCT / Modular | Safari 17+, Chrome/Firefox за флагами | **Опциональный:** для специфичных клиентов при проверке |
| **JPEG** | `image/jpeg` | **0% (базовый)** | DCT (MozJPEG) | 100% клиентов, консольные утилиты, боты | **Базовый оригинал:** гарантированная отдача при сбое |
| **PNG** | `image/png` | **Базовый (lossless)**| DEFLATE | 100% клиентов | Оригинал для схем, скриншотов, иконок |

---

### Стратегии именования файлов: Append vs Replacement

В практике системного администрирования и DevOps применяются две схемы размещения вариантов на файловой системе:

```
[ Стратегия 1: Добавление суффикса (Append) ]
URL запроса: /images/photo.jpg
Файлы на диске:
  ├── photo.jpg          (оригинал)
  ├── photo.jpg.avif     (AVIF-вариант)
  └── photo.jpg.webp     (WebP-вариант)

[ Стратегия 2: Замена расширения (Replacement) ]
URL запроса: /images/photo.jpg
Файлы на диске:
  ├── photo.jpg          (оригинал)
  ├── photo.avif         (AVIF-вариант)
  └── photo.webp         (WebP-вариант)
```

| Критерий | Стратегия 1: Добавление суффикса (Append) | Стратегия 2: Замена расширения (Replacement) |
| :--- | :--- | :--- |
| **Шаблон `try_files`** | `try_files $uri$img_suffix $uri =404;` | `try_files $base_path$img_suffix $uri =404;` |
| **Конфигурация Nginx** | Простой location по расширению, минимальный оверхед CPU. | Требует именованного регулярного выражения для захвата базового пути. |
| **Коллизии имен** | Исключены: `logo.png.webp` и `logo.jpg.webp` не пересекаются. | Возможны коллизии, если в одной папке лежат `logo.png` и `logo.jpg`. |
| **Интеграция с CI/CD** | Тривиальна: скрипты просто дописывают суффикс к целевому пути. | Требует парсинга и замены расширения файла. |
| **Рекомендация** | **Стандарт для Highload:** максимальная скорость и надежность. | Допустимо при жестких требованиях к структуре диска. |

---

### Архитектурное ограничение: Контракт AOT-генерации

В директиве `map` сопоставление регулярных выражений выполняется до первого совпадения:

```nginx
map $http_accept $img_suffix {
    default        "";
    "~*image/avif" ".avif";
    "~*image/webp" ".webp";
}
```

Если клиент отправляет `Accept: image/avif,image/webp,*/*`, переменная `$img_suffix` получает значение `.avif`. Директива `try_files $uri$img_suffix $uri =404;` проверяет только:
1. `photo.jpg.avif`
2. `photo.jpg` (оригинал)

Если файл `.avif` по какой-либо причине отсутствует на диске, Nginx не выполняет вторичный поиск `.webp`, а сразу отдает исходный JPEG, даже если файл `.webp` физически присутствует.

> [!IMPORTANT]
> **Контракт AOT-пайплайна:** Для статической доставки изображений в Nginx генерация вариантов является атомарной операцией «все или ничего». Скрипты сборки обязаны создавать все заявленные форматы одновременно. Если публикация вариантов нарушена, клиент откатывается к оригиналу без промежуточных попыток.

---

## Практические сценарии

### Сценарий 1: Базовая production-конфигурация (Append-стратегия)

Конфигурация сервера Nginx для отдачи статических изображений с нормализацией заголовка `Accept`, кэшированием дескрипторов и защитой от отравления кэша.

**Шаг 1.** Настройте контекст `http` и виртуальный хост в `/etc/nginx/conf.d/images.conf`:

```nginx
# /etc/nginx/conf.d/images.conf

# Сопоставление клиентского заголовка Accept с расширением файла.
# Регулярные выражения проверяются последовательно сверху вниз.
map $http_accept $img_suffix {
    default        "";
    "~*image/avif" ".avif";
    "~*image/webp" ".webp";
}

server {
    listen 80;
    listen [::]:80;
    server_name static.example.com;

    root /var/www/static;

    # Системные оптимизации отдачи статики
    sendfile    on;
    tcp_nopush  on;
    tcp_nodelay on;

    # Кэширование системных метаданных файлов в памяти
    open_file_cache          max=50000 inactive=60s;
    open_file_cache_valid    30s;
    open_file_cache_min_uses 2;
    open_file_cache_errors   on;

    # Локация для обработки растровых изображений
    location ~* \.(jpe?g|png)$ {
        # Проверка: оригинал.суффикс -> оригинал -> 404
        try_files $uri$img_suffix $uri =404;

        # Защита промежуточных кэшей от отдачи несовместимого формата
        add_header Vary "Accept" always;

        # Долгосрочное неизменяемое кэширование в браузере (1 год)
        # no-transform запрещает промежуточным провайдерам пережимать картинки
        add_header Cache-Control "public, max-age=31536000, immutable, no-transform" always;

        # Защита от MIME-sniffing
        add_header X-Content-Type-Options "nosniff" always;

        # Отключение логирования успешных запросов для снижения I/O на дисках логов
        access_log off;
        log_not_found off;
    }

    # Локация для уже сконвертированных файлов при прямом запросе по URL
    location ~* \.(avif|webp)$ {
        add_header Cache-Control "public, max-age=31536000, immutable, no-transform" always;
        add_header X-Content-Type-Options "nosniff" always;
        access_log off;
    }
}
```

**Шаг 2.** Убедитесь, что в файле `/etc/nginx/mime.types` присутствуют нужные сопоставления:

```nginx
types {
    image/avif                            avif;
    image/webp                            webp;
    image/jpeg                            jpeg jpg;
    image/png                             png;
}
```

**Шаг 3.** Структура файлов на диске сервера:

```text
/var/www/static/products/
├── item123.jpg         # Исходный файл (1.2 MB, 0644, www-data:www-data)
├── item123.jpg.avif    # Вариант AVIF (340 KB, 0644, www-data:www-data)
└── item123.jpg.webp    # Вариант WebP (510 KB, 0644, www-data:www-data)
```

**Шаг 4.** Валидация и перезагрузка конфигурации:

```bash
nginx -t
# → nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

systemctl reload nginx
# → процесс перечитывает конфигурацию без сброса активных соединений
```

---

### Сценарий 2: Конфигурация с заменой расширения (Replacement-стратегия)

Если пайплайн сборки генерирует файлы с заменой расширения (`photo.avif` вместо `photo.jpg.avif`), используется именованное регулярное выражение для извлечения пути:

```nginx
# /etc/nginx/conf.d/images_replacement.conf

map $http_accept $img_suffix {
    default        "";
    "~*image/avif" ".avif";
    "~*image/webp" ".webp";
}

server {
    listen 80;
    server_name media.example.com;
    root /var/www/media;

    sendfile on;
    tcp_nopush on;

    open_file_cache max=30000 inactive=60s;
    open_file_cache_valid 30s;
    open_file_cache_errors on;

    # Захват пути без исходного расширения в переменную $img_path
    location ~* ^(?<img_path>.+)\.(jpe?g|png)$ {
        # Если $img_suffix = ".avif", ищется $img_path.avif, затем исходный $uri
        try_files $img_path$img_suffix $uri =404;

        add_header Vary "Accept" always;
        add_header Cache-Control "public, max-age=31536000, immutable, no-transform" always;
        add_header X-Content-Type-Options "nosniff" always;

        access_log off;
    }
}
```

Структура каталогов на сервере для данного сценария:
```text
/var/www/media/banners/
├── hero.jpg     # Запрашиваемый клиентом URL: /banners/hero.jpg
├── hero.avif    # Отдается клиенту с Accept: image/avif
└── hero.webp    # Отдается клиенту с Accept: image/webp
```

---

### Сценарий 3: On-Premises автоматизация AOT-генерации (systemd + inotify)

В локальной инфраструктуре (bare-metal серверы, выделенные хранилища) загрузка изображений часто происходит через SFTP, rsync или локальный сервис бэкенда. Для автоматической фоновой конвертации настраивается связка из `systemd.path` (на базе ядра Linux `inotify`) и сервиса генерации с жесткой изоляцией ресурсов через cgroups v2.

**Шаг 1.** Создайте unit пути `/etc/systemd/system/image-optimizer.path`:

```ini
[Unit]
Description=Monitor media uploads for image optimization
After=network.target

[Path]
# Мониторинг появления новых файлов в каталоге загрузок
DirectoryNotEmpty=/var/www/static/uploads/pending
Unit=image-optimizer.service

[Install]
WantedBy=multi-user.target
```

**Шаг 2.** Создайте unit сервиса `/etc/systemd/system/image-optimizer.service`:

```ini
[Unit]
Description=Batch AOT Image Optimizer (AVIF / WebP)
After=network.target

[Service]
Type=oneshot
User=www-data
Group=www-data
UMask=0022
ExecStart=/usr/local/bin/optimize-images.sh

# Защита ресурсов хоста через cgroups v2 (SRE Governance)
# Процессы сжатия никогда не должны вытеснять воркеры Nginx
Nice=19
CPUSchedulingPolicy=idle
CPUQuota=200%
MemoryMax=2G
MemoryHigh=1.8G

# Безопасность процесса
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/www/static
PrivateTmp=true
```

**Шаг 3.** Создайте скрипт обработки `/usr/local/bin/optimize-images.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

# Каталоги входящих и готовых медиафайлов
SRC_DIR="/var/www/static/uploads/pending"
DEST_DIR="/var/www/static/uploads"

# Обработка входящих файлов JPEG/PNG с помощью утилит cwebp и cavif (или libvips)
find "$SRC_DIR" -type f \( -iname "*.jpg" -o -iname "*.jpeg" -o -iname "*.png" \) | while read -r file; do
    rel_name=$(basename "$file")
    target_orig="${DEST_DIR}/${rel_name}"
    
    # Перемещение оригинала в целевую директорию с правильными правами
    mv "$file" "$target_orig"
    chmod 0644 "$target_orig"

    # Генерация WebP (качество 80, многопоточный режим)
    cwebp -q 80 -m 4 "$target_orig" -o "${target_orig}.webp" >/dev/null 2>&1
    chmod 0644 "${target_orig}.webp"

    # Генерация AVIF (скорость 6, качество 65 для баланса размера и времени)
    cavif -q 65 --speed 6 --overwrite "$target_orig" -o "${target_orig}.avif" >/dev/null 2>&1
    chmod 0644 "${target_orig}.avif"
done
```

**Шаг 4.** Активируйте и запустите монитор:

```bash
chmod +x /usr/local/bin/optimize-images.sh
systemctl daemon-reload
systemctl enable --now image-optimizer.path
# → Created symlink /etc/systemd/system/multi-user.target.wants/image-optimizer.path
```

---

### Сценарий 4: Наблюдаемость (Observability) и мониторинг формата

Для SRE критически важно понимать, какая доля трафика приходится на современные форматы, какой объем исходящей полосы экономится и нет ли деградации отдачи кэша.

**Шаг 1.** Настройте специализированный формат логов в контексте `http`:

```nginx
# /etc/nginx/conf.d/logging.conf

log_format images_analytics escape=json '{'
    '"time_local":"$time_iso8601",'
    '"remote_addr":"$remote_addr",'
    '"request_uri":"$uri",'
    '"status":$status,'
    '"bytes_sent":$body_bytes_sent,'
    '"request_time":$request_time,'
    '"negotiated_suffix":"$img_suffix",'
    '"content_type":"$sent_http_content_type",'
    '"http_accept":"$http_accept",'
    '"user_agent":"$http_user_agent"'
'}';
```

**Шаг 2.** Подключите логирование для аналитической выборки (или сэмплирования) в виртуальном хосте:

```nginx
location ~* \.(jpe?g|png)$ {
    try_files $uri$img_suffix $uri =404;
    add_header Vary "Accept" always;
    add_header Cache-Control "public, max-age=31536000, immutable, no-transform" always;

    # Лог только для мониторинга согласования форматов
    access_log /var/log/nginx/images_access.log images_analytics;
}
```

**Шаг 3.** Расчет метрик эффективности (SRE KPI):

$$\text{Egress Bandwidth Savings (\%)} = \left( 1 - \frac{\sum \text{Bytes}_{\text{AVIF}} + \sum \text{Bytes}_{\text{WebP}}}{\sum \text{Bytes}_{\text{Original JPEG}}} \right) \times 100\%$$

Однострочник для быстрого анализа распределения форматов на боевом сервере:

```bash
awk -F'"content_type":"' '{print $2}' /var/log/nginx/images_access.log | awk -F'"' '{print $1}' | sort | uniq -c | sort -nr
# →  84520 image/avif
# →  41230 image/webp
# →   5140 image/jpeg
```

В данном примере $66.4\%$ запросов обслуживаются через AVIF, $32.4\%$ — через WebP, и только $1.2\%$ клиентов получают тяжелые JPEG.

---

### Сценарий 5: Сквозная валидация Content Negotiation через curl

Проверка корректности работы серверной части выполняется имитацией различных заголовков браузеров.

```bash
# 1. Запрос от современного браузера (Chrome, Safari, Firefox): поддержка AVIF и WebP
curl -I -H "Accept: image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8" http://static.example.com/products/item123.jpg
# → HTTP/1.1 200 OK
# → Content-Type: image/avif
# → Vary: Accept
# → Cache-Control: public, max-age=31536000, immutable, no-transform
# → X-Content-Type-Options: nosniff

# 2. Запрос от браузера с поддержкой только WebP
curl -I -H "Accept: image/webp,image/png,image/svg+xml,image/*;q=0.8,*/*;q=0.5" http://static.example.com/products/item123.jpg
# → HTTP/1.1 200 OK
# → Content-Type: image/webp
# → Vary: Accept

# 3. Запрос от устаревшего клиента, curl или поискового краулера (без поддержки современных форматов)
curl -I -H "Accept: image/jpeg,image/png,*/*" http://static.example.com/products/item123.jpg
# → HTTP/1.1 200 OK
# → Content-Type: image/jpeg
# → Vary: Accept

# 4. Проверка поведения при отсутствии AVIF-файла на диске (проверка fallback на оригинал)
curl -I -H "Accept: image/avif,*/*" http://static.example.com/products/missing_variant.jpg
# → HTTP/1.1 200 OK
# → Content-Type: image/jpeg
# → Vary: Accept
```

---

## Операции и команды

| Задача | Команда CLI / Процедура | Ожидаемый результат / Примечание |
| :--- | :--- | :--- |
| **Синтаксическая проверка** | `nginx -t` | `syntax is ok` и `test is successful` |
| **Бесшовная перезагрузка** | `systemctl reload nginx` (или `nginx -s reload`) | Обновление воркеров без разрыва активных соединений |
| **Проверка MIME-типов** | `grep -E "avif|webp|jxl" /etc/nginx/mime.types` | Наличие записей `image/avif`, `image/webp`, `image/jxl` |
| **Тест заголовка Vary** | `curl -sI -H "Accept: image/avif,*/*" http://localhost/test.jpg \| grep -i vary` | `Vary: Accept` присутствует в заголовках |
| **Тест отдачи AVIF** | `curl -sI -H "Accept: image/avif,*/*" http://localhost/test.jpg \| grep -i content-type` | `Content-Type: image/avif` |
| **Тест отдачи WebP** | `curl -sI -H "Accept: image/webp,*/*" http://localhost/test.jpg \| grep -i content-type` | `Content-Type: image/webp` |
| **Проверка статуса демона** | `systemctl status image-optimizer.path` | `Active: active (waiting)` |
| **Проверка прав файлов** | `ls -ld /var/www/static/products/*` | Права `0644`, владелец `www-data:www-data` |
| **Анализ форматов в логе** | `grep -oP '"content_type":"\K[^"]+' /var/log/nginx/images_access.log \| sort \| uniq -c` | Вывод счетчиков по каждому отданному MIME-типу |
| **Трассировка системных вызовов** | `strace -fp $(pgrep -f "nginx: worker" \| head -n1) -e trace=stat,newfstatat,openat,sendfile` | Контроль отсутствия лишних вызовов `stat` при активном `open_file_cache` |

---

## Устранение неполадок

### 1. Браузер получает JPEG вместо AVIF/WebP

**Симптом:** Браузер Chrome передает `Accept: image/avif,image/webp`, однако сервер возвращает `Content-Type: image/jpeg`.

**Диагностика:**
1. Проверьте физическое наличие оптимизированного файла на диске:
   ```bash
   ls -la /var/www/static/products/item123.jpg*
   # Должны присутствовать item123.jpg, item123.jpg.avif, item123.jpg.webp
   ```
2. Проверьте права на чтение для пользователя воркеров Nginx:
   ```bash
   sudo -u www-data test -r /var/www/static/products/item123.jpg.avif && echo "OK" || echo "Permission Denied"
   # → OK
   ```
3. Проверьте значение переменной `$img_suffix` через временный заголовок:
   ```nginx
   # Временная отладка в location:
   add_header X-Debug-Suffix "$img_suffix" always;
   ```
   Выполните запрос: `curl -I -H "Accept: image/avif,*/*" http://localhost/products/item123.jpg`. Если заголовок пустой, проверьте синтаксис директивы `map`.

**Решение:** Сгенерируйте недостающие файлы с правами `0644` (`chmod 0644 ...`), исправьте опечатки в регулярных выражениях `map`.

---

### 2. Отсутствует заголовок Vary: Accept

**Симптом:** При выполнении `curl -I` заголовок `Vary: Accept` отсутствует, что приводит к отравлению кэша в корпоративных прокси и браузерах.

**Причина:**
1. В директиве `add_header` не указан параметр `always`.
2. Директива `add_header` объявлена на уровне `server`, но переопределена другой директивой `add_header` внутри блока `location` (стандартное поведение наследования директив Nginx).

**Решение:**
Объявляйте заголовок непосредственно внутри блока `location` с модификатором `always`:
```nginx
location ~* \.(jpe?g|png)$ {
    try_files $uri$img_suffix $uri =404;
    add_header Vary "Accept" always;
    # ...
}
```

---

### 3. Некорректный Content-Type: application/octet-stream

**Симптом:** Файл `.avif` или `.webp` отдается с `Content-Type: application/octet-stream`, из-за чего браузер скачивает картинку на диск вместо отображения.

**Причина:** Отсутствует строка `image/avif avif;` или `image/webp webp;` в файле `/etc/nginx/mime.types`, либо файл `mime.types` не подключен директивой `include mime.types;` в блоке `http`.

**Решение:**
Добавьте MIME-типы в `/etc/nginx/mime.types` или явно внутри блока `http`:
```nginx
http {
    include mime.types;
    types {
        image/avif avif;
        image/webp webp;
        image/jxl  jxl;
    }
}
```

---

### 4. Всплеск I/O wait и деградация CPU (Stat-Storm)

**Симптом:** При росте RPS утилизация процессора в режиме `sys%` резко возрастает, утилизация диска по `iostat` достигает $100\%$, увеличивается TTFB.

**Причина:** Директива `open_file_cache` отключена или имеет слишком малый объем `max`. Каждый запрос к `try_files` заставляет ядро выполнять дисковые операции поиска по дереву каталогов (VFS directory traversal).

**Диагностика:**
```bash
# Проверка частоты вызовов stat через pidstat
pidstat -v -p $(pgrep -d',' -f "nginx: worker") 1
# Трассировка частоты системных вызовов
strace -c -p $(pgrep -f "nginx: worker" | head -n1)
```

**Решение:**
Включите и увеличьте лимиты `open_file_cache`:
```nginx
open_file_cache          max=100000 inactive=120s;
open_file_cache_valid    60s;
open_file_cache_min_uses 1;
open_file_cache_errors   on;
```

---

### 5. Новые файлы не отдаются после генерации (open_file_cache_errors)

**Симптом:** Пайплайн создал файл `photo.jpg.avif`, однако Nginx продолжает отдавать исходный `photo.jpg` в течение 30–60 секунд.

**Причина:** Директива `open_file_cache_errors on;` закэшировала отрицательный результат (ENOENT — файл не найден) при предыдущем обращении клиента. Кэш сбрасывается только по истечении таймаута `open_file_cache_valid`.

**Решение:**
1. Если контент на сайте обновляется динамически в реальном времени, уменьшите `open_file_cache_valid` до $10\text{s}$–$15\text{s}$.
2. Если файлы загружаются пачками, выполняйте предварительную генерацию вариантов в скрытом буферном каталоге и атомарно перемещайте всю группу файлов (`.jpg`, `.jpg.avif`, `.jpg.webp`) в рабочий каталог через `mv`.

---

### 6. Зацикливание или ошибка 500 при неверном try_files

**Симптом:** При обращении к картинке сервер возвращает `500 Internal Server Error`, в логе ошибок `error.log` появляется запись: `rewrite or internal redirection cycle while internally redirecting to /index.php`.

**Причина:** Последний параметр директивы `try_files` по ошибке указывает на URI роутера (например, `/index.html` или `/index.php`), вместо явного кода ошибки `=404`.

**Решение:**
Для статических медиаресурсов последним аргументом `try_files` всегда должен быть строгий код ошибки `=404`:
```nginx
# Корректно:
try_files $uri$img_suffix $uri =404;

# Некорректно для статики (приведет к отдаче HTML вместо картинки):
# try_files $uri$img_suffix $uri /index.php;
```

---

## Рекомендации

1. **Используйте модификатор `always`:** HTTP-заголовок `Vary: Accept` обязан добавляться с ключевым словом `always`, чтобы предотвратить сбои в кэшах при нестандартных статусах ответа.
2. **Атомарная генерация в AOT:** Всегда создавайте варианты WebP и AVIF одновременно с оригиналом. Не полагайтесь на ступенчатый fallback в Nginx, так как директива `map` детерминирована и вычисляет суффикс однократно.
3. **Изолируйте фоновую обработку:** Инструменты сжатия (`cavif`, `cwebp`, `libvips`) являются экстремально ресурсоемкими по CPU. При запуске на одном сервере с Nginx изолируйте их через systemd cgroups v2 (`Nice=19`, `CPUSchedulingPolicy=idle`, `MemoryMax=...`).
4. **Оптимизируйте системный ввод-вывод:** Для хранилища медиафайлов используйте связку `sendfile on;`, `tcp_nopush on;`, `tcp_nodelay on;` и опцию монтирования дисков `noatime`.
5. **Тюнингуйте `open_file_cache`:** Размер кэша дескрипторов должен превышать количество активных уникальных файлов минимум в $1.5$ раза.
6. **Добавляйте `no-transform` в `Cache-Control`:** Это исключает искажение и пережатие графики промежуточными операторами связи и сотовыми сетями.
7. **Используйте долгосрочное кэширование с хэшами:** Для статических файлов с уникальными хэшами версий (content hashing) выставляйте `Cache-Control: public, max-age=31536000, immutable`.
8. **Исключите динамическую генерацию в Nginx OSS:** Если проекту критически необходима трансформация на лету (ресайз, кроп, наложение водяных знаков), используйте форк [Angie с модулем image_filter](../../Angie/High_Load/image_filter/overview.md) или локальный демон `imgproxy`.

---

## Дополнительная информация

### Сравнение подходов: Nginx (AOT) vs Angie (JIT image_filter)

| Характеристика | Nginx OSS (Статическая доставка AOT) | Angie (Динамический модуль image_filter JIT) |
| :--- | :--- | :--- |
| **Принцип работы** | Отдача готовых файлов с диска через `sendfile` | Генерация форматов и размеров «на лету» в памяти |
| **Нагрузка на CPU сервера** | Нулевая (только сетевой ввод-вывод) | Высокая (требует пула воркеров и резерва ядер) |
| **Дисковое пространство** | Требует $2.5\times$–$3\times$ объема под все форматы | Хранит только оригиналы + кэш востребованных вариантов |
| **Задержка первого запроса** | Минимальная ($< 5\text{ ms}$, чтение из Page Cache) | Увеличенная ($50\text{ ms}$–$400\text{ ms}$ на время кодирования) |
| **Гибкость размеров** | Фиксированная сетка файлов | Произвольные размеры, кроп, поворот, размытие |
| **Сфера применения** | Высоконагруженная статика, каталоги, медиа-архивы | Динамический пользовательский контент (UGC), соцсети |

### Связанные материалы в базе знаний

*   [Image Optimization Pipeline для веб-производительности](../../Concepts/web_performance/image_optimization_pipeline.md) — сквозная архитектура AOT/JIT-пайплайнов, бенчмарки кодеков и защита от атак Pixel Flood.
*   [Тюнинг производительности Nginx](nginx_performance_tuning.md) — системные вызовы ядра Linux, настройка сетевых буферов и kTLS.
*   [Клиентское кэширование в Nginx и Angie](./Caching/client_caching.md) — заголовки Cache-Control, ETag, условные запросы и валидация.
*   [Обзор кэширования в Nginx](./Caching/overview.md) — директивы proxy_cache, уровни группировки каталогов и очистка кэша.
*   [Модуль image_filter в Angie: обзор](../../Angie/High_Load/image_filter/overview.md) — динамическая обработка и конвертация графики.
*   [Конфигурация фронтенд-шлюза image_filter в Angie](../../Angie/High_Load/image_filter/site_configuration.md) — двухконтурная архитектура и нормализация кэш-ключей.

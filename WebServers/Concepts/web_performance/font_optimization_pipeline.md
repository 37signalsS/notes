# Font Optimization Pipeline для веб-производительности

**Актуально для:** Nginx 1.26+, Angie 1.4+ / 1.8+, WOFF2 (RFC 8081), CSS Fonts Module Level 4, Linux Kernel 5.15+ / 6.x

## Определения

- **Font Optimization Pipeline (Конвейер оптимизации веб-шрифтов)** — совокупность инженерных процессов конвертации, сабсеттинга (нарезки глифов), предварительной загрузки и кэширования типографических ресурсов для минимизации задержек первого рендеринга страницы и исключения сдвигов макета.
- **WOFF2 (Web Open Font Format 2.0)** — современный стандарт бинарного сжатия шрифтов (RFC 8081), использующий алгоритм сжатия Brotli на уровне таблицы контуров глифов. Обеспечивает на 30–50% меньший размер файла по сравнению с WOFF и до 70% по сравнению с TTF/OTF. Является стандартом де-факто для веб-производительности и поддерживается 98%+ браузеров.
- **Font Subsetting (Сабсеттинг шрифтов)** — процедура удаления неиспользуемых глифов (символов, диакритических знаков, редких языковых блоков) из исходного шрифтового файла. Позволяет сократить размер универсального шрифта с 2–5 МБ до 15–35 КБ для конкретного набора символов.
- **`unicode-range`** — дескриптор директивы CSS `@font-face`, определяющий диапазон кодовых точек Unicode (например, `U+0400-045F` для кириллицы), для которых должен загружаться конкретный файл шрифта. Браузер инициирует сетевой запрос за шрифтом **только в том случае**, если на странице обнаружен текст с символами из указанного диапазона.
- **FOIT (Flash of Invisible Text)** — нежелательное поведение браузера при загрузке внешнего шрифта, при котором текст остается невидимым (скрытым) до завершения скачивания шрифтового файла или истечения тайм-аута блокировки (в Chromium/Firefox — до 3 секунд). Критически ухудшает метрику **LCP (Largest Contentful Paint)**.
- **FOUT (Flash of Unstyled Text)** — поведение, при котором браузер немедленно отображает текст базовым системным шрифтом (fallback font), а затем перерисовывает его после загрузки кастомного веб-шрифта. Предотвращает задержку чтения контента, но при несовпадении метрик шрифтов вызывает скачок верстки, ухудшая метрику **CLS (Cumulative Layout Shift)**.
- **FOFT (Flash of Faux Text)** — двухэтапная стратегия оптимизации шрифтов: сначала загружается только базовое начертание (Regular) малого размера, а жирные (Bold) и наклонные (Italic) начертания временно синтезируются браузером («faux fonts») до загрузки соответствующих полноценных файлов.
- **`font-display`** — CSS-свойство директивы `@font-face`, управляющее жизненным циклом рендеринга шрифта (периоды блокировки, подмены и отказа): `swap`, `optional`, `fallback`, `block`.
- **Self-Hosting Fonts (Локальный хостинг шрифтов)** — архитектурная практика размещения файлов шрифтов на собственных серверах/обратных прокси (Nginx/Angie) вместо подключения внешних сервисов (Google Fonts, Adobe Typekit). Устраняет дополнительные RTT на DNS, TCP и TLS рукопожатия к сторонним доменам и исключает Single Point of Failure (SPOF).
- **Font Preload** — декларативная инструкция браузеру `<link rel="preload" as="font" type="font/woff2" crossorigin>` для немедленного старта сетевой загрузки критического шрифта на раннем этапе разбора HTML до того, как парсер CSS обнаружит селекторы с `@font-face`.
- **`size-adjust` и метрики выравнивания шрифтов** — CSS-дескрипторы `@font-face` (`size-adjust`, `ascent-override`, `descent-override`), позволяющие точно подогнать геометрию системного резервного шрифта (Arial, Georgia) под пропорции загружаемого веб-шрифта, полностью устраняя сдвиг верстки при подмене (Zero CLS).

---

## Основные концепции и архитектура

### Влияние шрифтов на Critical Rendering Path и Core Web Vitals

Шрифты являются ресурсами, блокирующими отображение текста (Render-blocking resources):

```
[ HTML Parser ] ───► [ Найдена ссылка на CSS ] ───► [ Загрузка и парсинг CSSOM ]
                                                              │
                                                              ▼
[ Блокировка рендеринга текста ] ◄── [ Найден @font-face: сетевой запрос WOFF2 ]
             │
             ├──► font-display: block ──► FOIT (текст невидим до 3с) ──► Рост LCP!
             │
             ├──► font-display: swap  ──► FOUT (текст виден сразу,      ──► Риск высокого CLS!
             │                            затем заменяется на веб-шрифт)
             │
             └──► font-display: optional + preload ──► Идеальный баланс:
                                                       нет FOIT, нет CLS.
```

| Метрика | Влияние неоптимизированных шрифтов | Решение через Font Pipeline |
| :--- | :--- | :--- |
| **LCP (Largest Contentful Paint)** | Если заголовок `<h1>` или ключевой блок текста оформлен веб-шрифтом с FOIT (`font-display: block`), LCP задерживается до полного скачивания шрифта по сети. | `preload` критического шрифта + `font-display: swap` или `optional`. |
| **CLS (Cumulative Layout Shift)** | При подмене системного шрифта (FOUT) текст меняет высоту строк, ширину символов и переносится, сдвигая кнопки и блоки. | Калибровка fallback через `size-adjust`, `ascent-override`, `descent-override`. |
| **FCP (First Contentful Paint)** | Внешние CSS со сторонних доменов (`fonts.googleapis.com`) блокируют построение CSSOM. | Self-hosting: раздача CSS и WOFF2 с одного домена/прокси без внешних RTT. |

---

### Архитектурное сравнение: Self-Hosting против сторонних CDN (Google Fonts)

Подключение шрифтов через сторонние сервисы (Google Fonts) несет скрытые издержки производительности и надежности:

```
[ Вариант 1: Внешний CDN (Google Fonts) ]
Браузер ──(1. DNS + TCP + TLS)──► fonts.googleapis.com (Загрузка CSS)
Браузер ──(2. DNS + TCP + TLS)──► fonts.gstatic.com   (Загрузка WOFF2)
Итого: до 4–6 дополнительных RTT, зависимость от внешнего провайдера (SPOF),
утечка IP-адресов пользователей (противоречит GDPR и корпоративным политикам).

[ Вариант 2: Self-Hosted на Nginx/Angie ]
Браузер ──(Существующее HTTP/2 или HTTP/3 соединение)──► Собственный Reverse Proxy
Итого: 0 дополнительных DNS/TLS-хэндшейков, отправка WOFF2 в первом же окне перегрузки.
```

---

### Стратегии `font-display` и их применение

Спецификация CSS Fonts Module определяет 4 ключевые стратегии:

| Значение | Период блокировки (невидимости) | Период подмены (swap) | Рекомендация для SRE / Production |
| :--- | :--- | :--- | :--- |
| **`swap`** | Очень короткий (0–100 мс) | Бесконечный (заменяется сразу по готовности) | **Рекомендуется для контентных сайтов**, где чтение текста важнее идеальной верстки в первую секунду. Требует калибровки fallback-метрик против CLS. |
| **`optional`** | Очень короткий (0–100 мс) | Нулевой (если шрифт не успел скачаться за ~100 мс, используется fallback на всю сессию; шрифт кэшируется для следующей страницы) | **Рекомендуется для мобильных сетей и жестких SLO**. Полностью исключает FOUT и CLS. |
| **`fallback`** | Короткий (~100 мс) | Короткий (~3 с) | Компромисс: если сеть медленная, браузер перестает пытаться подменить шрифт. |
| **`block`** | Длинный (до 3 с) | Бесконечный | **Антипаттерн** для обычного текста. Допустим только для иконочных шрифтов, где fallback-символ бессмысленен. |

---

## Практические сценарии и конфигурация

### Сценарий 1: Автоматизированный CI/CD пайплайн сабсеттинга и конвертации (Python `fonttools`)

Исходные дизайнерские шрифты формата OTF/TTF часто содержат тысячи символов (иероглифы, математические символы, исторические алфавиты). На этапе сборки выполняется их разбиение на компактные срезы по кодовым диапазонам Unicode с компрессией в WOFF2.

#### Шаг 1. Установка утилиты на сборочном узле

```bash
# Установка компилятора fonttools с поддержкой сжатия Brotli
pip install --no-cache-dir fonttools brotli
```

#### Шаг 2. Скрипт пакетного сабсеттинга для латиницы и кириллицы

```bash
#!/usr/bin/env bash
set -euo pipefail

INPUT_FONT="Inter-Regular.ttf"
OUTPUT_DIR="./dist/fonts"
mkdir -p "$OUTPUT_DIR"

# 1. Кириллический сабсет (Cyrillic + Cyrillic Extended)
pyftsubset "$INPUT_FONT" \
  --output-file="$OUTPUT_DIR/inter-cyrillic.woff2" \
  --flavor=woff2 \
  --unicodes="U+0400-045F,U+0490-0491,U+04B0-04B1,U+2116" \
  --layout-features='kern,liga' \
  --desubroutinize \
  --no-hinting

# 2. Базовый латинский сабсет (Latin + Latin Extended + цифры и пунктуация)
pyftsubset "$INPUT_FONT" \
  --output-file="$OUTPUT_DIR/inter-latin.woff2" \
  --flavor=woff2 \
  --unicodes="U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+2000-206F,U+2074,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD" \
  --layout-features='kern,liga' \
  --desubroutinize \
  --no-hinting

echo "Результат оптимизации:"
ls -lh "$INPUT_FONT" "$OUTPUT_DIR"/*.woff2
# → Исходный: Inter-Regular.ttf (~310 KB)
# → inter-cyrillic.woff2: (~14 KB)
# → inter-latin.woff2: (~18 KB)
```

---

### Сценарий 2: Оптимальная конфигурация раздачи шрифтов в Nginx / Angie

Файлы WOFF2 уже сжаты алгоритмом Brotli внутри формата, поэтому повторное динамическое сжатие gzip/brotli на сервере **строго отключается** во избежание бесполезной траты CPU.

```nginx
# /etc/nginx/conf.d/fonts.conf

# 1. Гарантируем регистрацию правильного IANA MIME-типа
types {
    font/woff2 woff2;
    font/woff  woff;
}

server {
    listen 443 ssl http2;
    server_name example.com;

    # Директория со статикой
    root /var/www/example.com;

    location ~* \.woff2$ {
        # Шрифты версионируются через хэш в имени (inter-latin.a1b2c3.woff2)
        # Устанавливаем максимальный срок кэширования и маркер неизменяемости
        expires 1y;
        add_header Cache-Control "public, max-age=31536000, immutable";

        # Шрифты, запрашиваемые через @font-face и preload, требуют обязательных CORS-заголовков
        add_header Access-Control-Allow-Origin "*";
        add_header Access-Control-Allow-Methods "GET, OPTIONS";

        # Отключаем повторную компрессию на лету (WOFF2 уже сжат Brotli)
        gzip off;
        brotli off;

        # Разрешаем системный вызов sendfile без копирования в user-space
        sendfile on;
        sendfile_max_chunk 512k;
        tcp_nodelay on;

        # Кэширование дескрипторов
        open_file_cache max=1000 inactive=120s;
        open_file_cache_valid 300s;
        open_file_cache_errors on;

        # Отключаем логирование успешных запросов статики для экономии IOPS
        access_log off;
        log_not_found off;
    }
}
```

---

### Сценарий 3: Настройка CSS и Zero-CLS Fallback

Для устранения FOUT и скачков макета (CLS) в CSS используются дескрипторы сопоставления метрик системного шрифта (`size-adjust`).

```css
/* 1. Настройка системного fallback-шрифта с калибровкой метрик */
@font-face {
  font-family: 'Inter Fallback';
  src: local('Arial');
  ascent-override: 90%;
  descent-override: 22%;
  line-gap-override: 0%;
  size-adjust: 107%;
}

/* 2. Кириллический сабсет */
@font-face {
  font-family: 'Inter';
  font-style: normal;
  font-weight: 400;
  font-display: swap;
  src: url('/fonts/inter-cyrillic.a1b2c3.woff2') format('woff2');
  unicode-range: U+0400-045F, U+0490-0491, U+04B0-04B1, U+2116;
}

/* 3. Латинский сабсет */
@font-face {
  font-family: 'Inter';
  font-style: normal;
  font-weight: 400;
  font-display: swap;
  src: url('/fonts/inter-latin.d4e5f6.woff2') format('woff2');
  unicode-range: U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC;
}

/* 4. Применение: резервный шрифт идеально соответствует размерам Inter */
body {
  font-family: 'Inter', 'Inter Fallback', sans-serif;
}
```

#### Настройка HTML Preload для критического шрифта

В блоке `<head>` HTML-документа помещается инструкция для немедленной загрузки основного латинского/кириллического среза:

```html
<!-- Атрибут crossorigin ОБЯЗАТЕЛЕН для шрифтов, даже если они загружаются с того же домена -->
<link rel="preload" 
      href="/fonts/inter-latin.d4e5f6.woff2" 
      as="font" 
      type="font/woff2" 
      crossorigin>
```

> [!WARNING]
> Если в теге `<link rel="preload" as="font">` пропущен атрибут `crossorigin`, браузер в соответствии со спецификацией W3C загрузит шрифт **дважды**: первый раз без CORS-контекста по предзагрузке, а второй раз — с CORS-контекстом для применения в `@font-face`.

---

## Диагностика и устранение неисправностей

| Симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **В консоли браузера: `Access to font ... has been blocked by CORS policy`** | Шрифт загружается с поддомена (CDN) или через `preload` без разрешающего заголовка `Access-Control-Allow-Origin`. | `curl -I https://example.com/fonts/inter.woff2` | Добавить `add_header Access-Control-Allow-Origin "*";` в конфигурацию Nginx для location со шрифтами. |
| **Высокий CLS (> 0.1) при смене системного шрифта на веб-шрифт** | Геометрия символов Arial/Times отличается по ширине и высоте от кастомного шрифта (FOUT). | Запись сессии в Chrome DevTools Performance → дорожка Experience / Layout Shifts. | Добавить калибровку fallback через `size-adjust` и `ascent-override` в `@font-face`. |
| **Шрифт скачивается дважды (двойной сетевой запрос)** | В теге `<link rel="preload" as="font">` забыт атрибут `crossorigin`. | Анализ вкладки Network в DevTools: два запроса к одному `.woff2`. | Добавить атрибут `crossorigin` (или `crossorigin="anonymous"`). |
| **Задержка LCP из-за ожидания шрифта** | Шрифт блокирует текст, предзагрузка отсутствует, `font-display: block`. | Lighthouse аудит: `Ensure text remains visible during webfont load`. | Использовать `preload` для 1–2 критических шрифтов первого экрана и выставить `font-display: swap` или `optional`. |
| **Высокая нагрузка на CPU веб-сервера при раздаче статики** | Включено динамическое сжатие `gzip on;` или `brotli on;` для MIME-типа `font/woff2`. | `top` / `perf top`: циклы CPU сжигаются в `deflate` / `brotli`. | Отключить сжатие для расширения `.woff2` (`gzip off; brotli off;`), так как формат уже упакован алгоритмом Brotli. |

---

## Чеклист оптимизации шрифтов для SRE / Production

- [ ] Все шрифты конвертированы в формат **WOFF2**; устаревшие форматы (TTF, OTF, EOT, WOFF) удалены из продакшна.
- [ ] Выполнен сабсеттинг (`fonttools / pyftsubset`) под целевые алфавиты (отдельно Latin и Cyrillic через `unicode-range`).
- [ ] Шрифты хостятся локально (Self-Hosted), внешние запросы к Google Fonts исключены.
- [ ] Для 1–2 критических файлов первого экрана настроен `<link rel="preload" as="font" type="font/woff2" crossorigin>`.
- [ ] Задано свойство `font-display: swap` (или `optional` для мобильных интерфейсов).
- [ ] Заголовки ответов содержат `Cache-Control: public, max-age=31536000, immutable` (при версионировании имен через хэш).
- [ ] Настроен заголовок `Access-Control-Allow-Origin: *`.
- [ ] Динамическое сжатие Nginx для `.woff2` выключено.

---

## Дополнительная информация

### Связанные темы в базе знаний
- [Обзор оптимизации веб-производительности](./overview.md)
- [Ключевые метрики пользовательского опыта (Web Vitals)](./web_vitals.md)
- [Лучшие практики веб-производительности](./best_practices.md)
- [Image Optimization Pipeline](./image_optimization_pipeline.md)
- [Сжатие контента на веб-сервере](./server_compression.md)

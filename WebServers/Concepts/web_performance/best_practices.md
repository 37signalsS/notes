# Лучшие практики оптимизации производительности веб-приложений

## Определения

**Лучшие практики оптимизации производительности** — совокупность проверенных архитектурных и технических подходов к минимизации времени загрузки и повышения интерактивности страниц. Основной фокус направлен на устранение ресурсов, блокирующих рендеринг, оптимизацию доставки медиаконтента, контроль сторонних зависимостей и приторитизацию критического пути загрузки.

**Критический путь рендеринга (Critical Rendering Path)** — последовательность шагов, которые проходит браузер для преобразования HTML, CSS и JavaScript в видимые пиксели на экране.

**Performance Budget (Бюджет производительности)** — максимально допустимые значения метрик и размеров ресурсов, при превышении которых сборка или деплой блокируется.

**SLO (Service Level Objective)** — целевое значение метрики надежности. В контексте производительности: доля посещений с LCP ≤ 2.5 с, INP ≤ 200 мс, CLS ≤ 0.1 за скользящее окно.

## Основные концепции

### Ключевые принципы оптимизации (2026)

* **Минимизация блокирующих ресурсов** — каждый файл стилей CSS и синхронный скрипт JavaScript в секции `<head>` откладывает начало отрисовки контента (метрики FCP и LCP).
* **Контроль выполнения JavaScript** — длительное выполнение скриптов блокирует основной поток (main thread), что критично для метрики **INP**.
* **Сжатие нового поколения** — переход с Gzip на **Brotli** и **Zstd** (поддерживается в Chrome 123+) для текстовых ресурсов.
* **Общие словари (Shared Dictionaries)** — использование механизма `Use-As-Dictionary` (RFC 9509) для сжатия дельт при обновлении SPA-приложений, что радикально снижает объем передаваемых данных.
* **Приоритизация ресурсов** — использование **Fetch Priority API** для управления порядком загрузки (например, повышение приоритета для LCP-изображений).
* **Ленивая загрузка (Lazy Loading)** — использование нативного `loading="lazy"` для изображений и фреймов, а также `content-visibility: auto` с `contain-intrinsic-size` для сложных блоков CSS.
* **Спекулятивная загрузка** — внедрение **Speculative Rules API** для предзагрузки (prefetch) или полной отрисовки (prerender) страниц, к которым пользователь с высокой вероятностью перейдет.

### Оптимизация шрифтов и CSS

Шрифты и стили часто становятся причиной задержки отображения текста или нежелательных сдвигов макета (CLS).

* **Использование `font-display: swap`** — предотвращает FOIT (Flash of Invisible Text).
* **Предварительная загрузка (Preload)** — обязательна для критических шрифтов через `<link rel="preload" as="font">`.
* **Критический CSS (Critical CSS)** — инлайнинг минимально необходимого набора стилей для отрисовки первого экрана (above-the-fold) непосредственно в HTML.
* **Подстройка размеров (Size Adjust)** — использование CSS-дескрипторов `ascent-override`, `descent-override` и `line-gap-override` для минимизации CLS при переключении с системного шрифта на кастомный.

### Границы ответственности по уровням

| Уровень | Компонент | Ответственный |
| :--- | :--- | :--- |
| **Клиент** | Браузер, Critical Rendering Path, Main Thread | Frontend |
| **Сеть** | CDN / Edge, HTTP/3, Early Hints, TLS | DevOps / SysAdmin |
| **Прокси** | Nginx / Angie, сжатие, кэширование, заголовки, буферизация | SysAdmin / DevOps |
| **Сервер** | Бэкенд, DB queries, кэширование, код | Backend |
| **Инфраструктура** | ОС / Сеть, TCP tuning, CPU, память, диски | SysAdmin |

## Практические сценарии

### Сценарий: Устранение блокирующих ресурсов и Early Hints

В 2026 году **103 Early Hints** полностью заменили Server Push. Сервер отправляет заголовки `Link` сразу, пока генерирует основной ответ.

**Шаги:**
1. Настроить веб-сервер (Nginx/Angie) на отправку `103 Early Hints` для критического CSS и шрифтов.
2. Использовать атрибут `fetchpriority="high"` для ресурсов в `Early Hints`.
3. Основной JS-бандл загружать с атрибутом `defer` или `type="module"`.

### Сценарий: Оптимизация JavaScript и Service Workers

Длительные задачи (>50 мс) — главный враг интерактивности.

**Шаги:**
* **Yielding to Main Thread:** разделение длинных задач с помощью `scheduler.yield()` или `setTimeout(0)`.
* **Web Workers:** перенос тяжелых расчетов (криптография, обработка данных) в фоновые потоки.
* **Service Workers:** внедрение стратегий `Cache-first` или `Stale-while-revalidate` для мгновенной загрузки приложения при повторных визитах и работы в оффлайн-режиме.

### Сценарий: Работа с изображениями и видео

**Шаги:**
* **Современные форматы:** AVIF является приоритетным форматом, WebP — запасным.
* **Адаптивность:** использование тега `<picture>` с поддержкой различных разрешений.
* **LCP-оптимизация:** для главного изображения (Hero Image) всегда устанавливать `fetchpriority="high"` и `loading="eager"`. Запрещено использовать `loading="lazy"` для LCP-элемента.

### Сценарий: Сетевая и серверная оптимизация

**Шаги:**
* **Внедрение HTTP/3 (QUIC):** Устраняет проблему блокировки очереди (HOL Blocking) на уровне транспорта.
* **DNS HTTPS Record:** Публикация записи типа 65 (HTTPS) для информирования браузера о поддержке H3 и параметров ECH без предварительного запроса по HTTP/1.1.
* **Тюнинг буферов сервера:** Настройка `proxy_buffers` и `fastcgi_buffers` в Nginx/Angie для предотвращения записи временных файлов на диск при больших ответах бэкенда, что критично для TTFB.

## Операции и команды

### Валидация производительности через curl

```bash
# Проверка заголовков производительности
curl -sI https://example.com/style.css | grep -iE "cache-control|age|content-encoding|server|x-cache"
# → cache-control: public, max-age=31536000, immutable
# → content-encoding: br
# → age: 300
# → x-cache: HIT
```

### Проверка Early Hints (103)

```bash
# Проверка Early Hints
curl -sI -H "Prefer: safe" https://example.com/ | head -5
# → HTTP/2 103
# → link: </css/main.css>; rel=preload; as=style, </fonts/main.woff2>; rel=preload; as=font; type=font/woff2; crossorigin
```

### Диагностика HTTP/3 и QUIC

```bash
# Проверка UDP-порта 443
ss -ulpn | grep :443
# → UNCONN 0 0 0.0.0.0:443 ... users:(("nginx",pid=1234,fd=8))

# Проверка ALPN для HTTP/3
openssl s_client -connect example.com:443 -alpn h3 -servername example.com -brief
# → ALPN protocol: h3
# → ALPN protocol: h2
# → ALPN protocol: http/1.1

# Проверка MTU для QUIC
ping -M do -s 1400 example.com
# → 1400 bytes from example.com ... time=45.2 ms
```

### Настройка производительности Nginx/Angie

```nginx
http {
  # LCP: Zero-Copy для статики
  sendfile on;
  sendfile_max_chunk 512k;
  tcp_nopush on;

  # LCP/INP: асинхронный дисковый I/O
  aio threads=default;

  # LCP: кэширование дескрипторов
  open_file_cache max=10000 inactive=20s;
  open_file_cache_valid 60s;
  open_file_cache_min_uses 2;

  # TTFB: буферизация ответов бэкенда
  proxy_buffers 128 16k;
  proxy_buffer_size 32k;
  fastcgi_buffers 128 16k;
  fastcgi_buffer_size 32k;
}
```

### Нагрузочное тестирование производительности

```bash
# Установка httpstat для измерения времени на каждом этапе
curl -o /usr/local/bin/httpstat https://raw.githubusercontent.com/dunglas/httpstat/master/httpstat && chmod +x /usr/local/bin/httpstat
httpstat https://example.com/
# → DNS Resolution: 12 ms
# → TCP Handshake: 45 ms
# → TLS Handshake: 89 ms
# → Server Processing: 67 ms
# → Content Transfer: 123 ms

# Нагрузочное тестирование HTTP/2
h2load -n 10000 -c 100 --warm-up-time 2 https://example.com/
# → 10000 reqs, 100 concurrency, 12.5 MB total
# → transferred: 1234 MB/s, RPS: 87654
```

### CI/CD: Performance Budget

```yaml
# .performance-budget.yaml
metrics:
  LCP: 2.5
  INP: 200
  CLS: 0.1
  JS: 500KB
  CSS: 200KB

# GitHub Actions integration
- name: Performance Budget
  uses: siteimprove/performance-budget-action@v2
  with:
    url: ${{ env.STAGING_URL }}
    config: .performance-budget.yaml
```

## Диагностика ошибок

| Проблема | Симптом | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Высокий LCP** | LCP > 2.5 с, медленная загрузка основного контента | Chrome DevTools → Network → фильтр по LCP | `fetchpriority="high"`, кэширование, сжатие, CDN |
| **Высокий TTFB** | LCP > 2.5 с, медленный первый байт | `curl -o /dev/null -s -w "TTFB: %{time_starttransfer}s" URL` | Оптимизация запросов к БД, кэширование, kTLS |
| **HTTP/2 не активируется** | `curl -I` возвращает HTTP/1.1 | `openssl s_client -connect example.com:443 -alpn h2 -servername example.com` | Обновить Nginx до 1.25.1+, проверить OpenSSL 1.1.1+ |
| **HTTP/3 недоступен** | `curl --http3` возвращает ошибку | `ss -ulpn | grep :443`, `nginx -V | grep http_v3_module` | Открыть UDP 443, собрать Nginx с `http_v3_module`, использовать Angie |
| **High INP** | INP > 200 мс, задержка интерактивности | Chrome DevTools → Performance → Main Thread | `scheduler.yield()`, Web Workers, отложенная загрузка JS |
| **High CLS** | CLS > 0.1, сдвиги макета | Chrome DevTools → Performance → Layout Shifts | `aspect-ratio`, размеры изображений, `font-display: swap` |
| **Cache Stampede** | Всплеск нагрузки на Origin | Мониторинг Origin CPU/RPS | `proxy_cache_lock on;`, Jitter TTL, `stale-while-revalidate` |
| **Domain Sharding в коде** | Использование `static1.`, `static2.` | Аудит HTML/CSS/JS | Удалить разделение по поддоменам — антипаттерн в 2026 году |

## Рекомендации

### Базовые правила

1. **Приоритизируйте LCP-ресурс:** Используйте `fetchpriority="high"` для Hero-image, `preload` для критических шрифтов.
2. **Включайте HTTP/2 на всех HTTPS-серверах:** Минимальная конфигурация — `listen 443 ssl http2;`.
3. **Включайте HTTP/3 только после валидации:** Проверьте поддержку UDP 443 на целевых сетях. Используйте Alt-Svc с `ma=86400` (сутки).
4. **Отключайте Domain Sharding:** Используйте один домен с HTTP/2 multiplexing.
5. **Используйте 103 Early Hints вместо Server Push:** Server Push удалён из HTTP/3 и игнорируется браузерами.
6. **Настройте TLS 1.3:** Уберите TLS 1.0/1.1. TLS 1.3 сокращает handshake до 1 RTT.
7. **Используйте 0-RTT только для идемпотентных операций:** Разрешайте Early Data только для GET/HEAD.
8. **Настраивайте Alt-Svc с разумным `ma`:** Сутки (`86400`) — оптимально.
9. **Мониторьте ALPN adoption:** Отслеживайте процент клиентов, использующих h2 vs h3, через логи (`$ssl_alpn`).
10. **Включайте BBRv3:** Для серверов с высокой пропускной способностью и сетями с потерями пакетов.

### Для DevOps/SRE/SysAdmin

*   **Валидация после деплоя:** Проверяйте заголовки Alt-Svc, ALPN и статус протокола через `curl -I` после каждого деплоя.
*   **Мониторинг UDP-порта 443:** Убедитесь, что firewall не блокирует UDP/443 на всех промежуточных балансировщиках и серверах.
*   **QUIC eBPF для стабильности:** Включайте `quic_bpf on;` для сохранения активных HTTP/3 сессий при `reload` конфигурации. Требует Linux 5.7+.
*   **QUIC GSO для производительности:** Включайте `quic_gso on;` для снижения количества системных вызовов при передаче UDP-пакетов.
*   **TCP Tuning:** Настройте `initcwnd` на 14–30 сегментов для доставки небольших ответов за 1 RTT. Включите `tcp_fastopen` для снижения задержки рукопожатия.
*   **Kernel TLS (kTLS):** Включайте для снижения нагрузки на CPU при отдаче статики и кэшированных ответов. Требует OpenSSL 3.0+ и Linux 5.10+.
*   **Мониторинг QUIC-потоков:** Используйте `ss -u -a` для мониторинга UDP-соединений. Отслеживайте `stateless reset` и `connection close` в логах.
*   **Нагрузочное тестирование:** Используйте `h2load` для HTTP/2/3 бенчмарков. Для HTTP/3 тестирования на основе libcurl используйте `curl --http3`.
*   **Аудит Domain Sharding:** Регулярно проверяйте код фронтенда на наличие разделения статики по поддоменам (`static1.`, `static2.`). Удалите при обнаружении.
*   **Алертинг на HTTP/3 Adoption:** Настройте алерты при падении доли HTTP/3 ниже ожидаемого уровня — это может указывать на проблемы с сетью или балансировщиками.

## Дополнительная информация

### Связанные темы

* [Обзор производительности веб-приложений](./overview.md) — фундаментальные аспекты.
* [Ключевые метрики Web Vitals](./web_vitals.md) — детали LCP, INP, CLS.
* [Протоколы HTTP/2 и HTTP/3](./http2_http3.md) — детали на уровне транспорта.
* [Инструментарий Chrome DevTools](./chrome_devtools.md) — диагностика производительности.
* [Работа с PageSpeed Insights](./pagespeed_insights.md) — анализ и рекомендации.
* [WebPageTest — инструмент синтетического тестирования](./webpagetest.md) — лабораторная диагностика.
* [Upstream Keepalive и Connection Pooling](./upstream_keepalive_and_pooling.md) — пул соединений с бэкендом.
* [Zero-Downtime Deployment](./zero_downtime_deployment.md) — graceful reload и worker_shutdown_timeout.
* [Circuit Breaker и Degradation](./circuit_breaker_and_degradation.md) — отказоустойчивость и fallback.
* [Health Checks и Readiness](./health_checks_and_readiness.md) — proactive обнаружение сбоев.
* [Image Optimization Pipeline](./image_optimization_pipeline.md) — CI/CD и AVIF/WebP.
* [Structured Logging для Performance](./structured_logging_for_performance.md) — логи и анализ.

### Внешние источники

* [Core Web Vitals Optimization 2026](https://medium.com/@tamzidulhaque/core-web-vitals-optimization-2026-easy-fixes-to-boost-rankings-speed-save-your-site-30da60a6d587)
* [Lighthouse 13 Release Notes](https://developer.chrome.com/blog/lighthouse-13-release/)
* [HTTP/3 and QUIC: The Future of Web Performance 2025](https://www.catchpoint.com/blog/http-3-quic)

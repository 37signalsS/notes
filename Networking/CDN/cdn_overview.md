# CDN — Обзор сети доставки контента

## Определения

- **CDN (Content Delivery Network)**: Географически распределенная сетевая инфраструктура (платформа облачного исполнения), предназначенная для ускорения доставки контента и выполнения кода максимально близко к пользователю.
- **PoP (Point of Presence) / Edge Node**: Узел (сервер или кластер), расположенный в определенном географическом регионе. PoP кэширует контент, обрабатывает запросы и выполняет Edge-логику.
- **Origin Server (Исходный сервер)**: Источник данных, где хранится оригинальная версия вашего сайта или приложения. CDN-узлы запрашивают контент с Origin, если его нет в их кэше ([Cache Miss](#кэширование-и-ключевые-понятия)).
- **Origin Shield (Шилдинг)**: Промежуточный уровень кэширования между пограничными узлами и источником, защищающий Origin от лавинообразных запросов.
- **Tiered Caching (Многоуровневое кэширование)**: Иерархическая структура кэширования (Edge -> Regional -> Shield), минимизирующая запросы к источнику и снижающая затраты на исходящий трафик (Egress).
- **Cache Hit / Miss**: «Cache Hit» означает, что контент найден в кэше PoP и отдан напрямую. «Cache Miss» означает, что контент в кэше отсутствует, и PoP должен запросить его с источника.
- **Cache Key**: Уникальный идентификатор ресурса в кэше. Формируется как хеш от URL, но может включать заголовки, куки и параметры запроса (подробнее — в разделе [Формирование Cache Key](#формирование-cache-key)).
- **Purge (Очистка)**: Механизм удаления контента из кэша пограничных узлов для его принудительного обновления из источника.
- **TTL (Time To Live)**: Период времени, в течение которого объект считается актуальным в кэше пограничного узла до выполнения нового запроса к источнику.
- **Caching Rule (Правило кэширования)**: Инструкция, определяющая, какой контент и на какое время (TTL) должен сохраняться на пограничном уровне.
- **Restriction (Ограничение)**: Правило доступа к контенту в кэше (например, ограничение по IP-адресам, регионам или доменам).
- **TLS Termination**: Процесс расшифровки TLS/SSL-соединения на стороне CDN на edge-узле, а не на Origin-сервере. Снижает нагрузку на бэкенд и позволяет CDN выполнять инспекцию трафика.
- **HTTP/3 (QUIC)**: Стандартный транспортный протокол 2026 года на базе UDP, минимизирующий задержки при установке соединения (0-RTT) и устраняющий проблему блокировки начала очереди (Head-of-Line Blocking).
- **Zstandard (ZSTD)**: Основной высокоэффективный алгоритм сжатия (от Meta), обеспечивающий превосходное соотношение скорости и степени сжатия. Стандарт для CDN в 2026 году.
- **Edge AI Inference**: Выполнение легковесных ИИ-моделей (SLM) непосредственно на узлах CDN для мгновенной обработки данных (персонализация, модерация) без обращения к центральному облаку.
- **Signed URLs / Signed Cookies**: Механизм временной авторизации доступа к приватному контенту через подпись URL или куки с использованием секретного ключа. Позволяет раздавать защищенный контент без постоянного перенаправления на бэкенд.
- **Cache Purge API**: Программный интерфейс для управления кэшем CDN — удаление объектов по URL, тегам (Surrogate Keys) или шаблонам (Wildcard). Время инвалидации для современных CDN (Cloudflare, Fastly) — <200 мс глобально.
- **Content Purge / Tag-Based Purge**: Массовая инвалидация контента по логическим меткам (Surrogate Keys). Сервер-источник прикрепляет к ответу заголовок `Surrogate-Key: category_laptops brand_apple`, а при изменении данных отправляется один API-запрос для удаления всех связанных объектов.

---

## История появления и эволюция

Технология CDN возникла как решение проблемы разделения статического и динамического контента для снижения нагрузки на серверы. Первой организацией, начавшей предоставлять услуги CDN, стала компания **Akamai**, основанная в 1998 году Дэниелом Левином и Томсоном Лейтоном.

С тех пор технология прошла путь от простого кэширования картинок до сложных платформ:
1. **Первое поколение**: Кэширование статики (изображения, файлы).
2. **Второе поколение**: Стриминг видео, динамическое ускорение, базовая защита.
3. **Третье поколение (Современность 2026)**: Edge Computing, программируемые сети (Wasm), глубокая интеграция с безопасностью (WAAP), Edge AI и поддержка протоколов реального времени (WebRTC через CDN).

---

## Типы контента и методы доставки

### Статический контент
Это файлы, которые остаются неизменными (или меняются крайне редко) при каждом запросе: изображения, видео, HTML-файлы, CSS и JavaScript.
- **Как работает:** CDN сохраняет копию файла в кэше. Это позволяет отдавать файл с ближайшего к пользователю узла, значительно сокращая время загрузки.
- **Cache-Control для статики**: Рекомендуется максимальный TTL с immutable-флагом при использовании хешированных имен файлов:
  ```http
  Cache-Control: public, max-age=31536000, immutable
  ```
  При изменении файла меняется его имя (например, `app.a1b2c3.js`), что делает старые версии автоматически невалидными.

### Динамический контент и ускорение (Dynamic Content Acceleration)
Содержимое, которое генерируется скриптами и меняется в зависимости от пользователя, времени или местоположения.
- **Оптимизация маршрутов**: CDN использует собственные магистральные сети для передачи запросов от PoP к Origin, минуя общественный интернет с его заторами.
- **TCP/QUIC Tuning**: Пограничные узлы поддерживают «горячие» соединения с Origin и используют агрессивные настройки окна передачи (высокий `initcwnd`) для ускорения ответов.
- **Рекомендуемые заголовки**:
  ```http
  CDN-Cache-Control: s-maxage=300, stale-while-revalidate=3600
  Cache-Control: no-cache
  ```
  `s-maxage` устанавливает TTL для CDN выше, чем для браузера. `stale-while-revalidate` позволяет отдавать устаревший контент, пока CDN обновляет его в фоне.

### Потоковое мультимедиа
Оптимизация для видео высокого разрешения (4K/8K) и онлайн-трансляций.
- **L-HLS / LL-DASH**: Протоколы с низкой задержкой, позволяющие достичь задержек в трансляции менее 2-3 секунд через стандартную инфраструктуру CDN.
- **CMAF (Common Media Application Format)**: Единый формат сегментов для HLS и DASH, повышающий эффективность кэширования.
- **Adaptive Bitrate (ABR)**: CDN автоматически подбирает битрейт на основе сетевых условий клиента, предотвращая буферизацию.

### Протоколы реального времени и API
- **gRPC через CDN**: Современные CDN (Cloudflare, Fastly) поддерживают терминацию gRPC-соединений на edge-узлах. Используется для связи микросервисов и мобильных клиентов с минимальной задержкой.
- **WebSocket через CDN**: Проксирование long-lived соединений для чатов, уведомлений и обновлений в реальном времени. CDN поддерживает соединение на протяжении всего времени жизни сессии.
- **GraphQL**: CDN может кэшировать ответы GraphQL-запросов при использовании детерминированных ключей (сортировка полей в запросе, нормализация variables).

---

## Современные технологии доставки (2026)

### Поддержка HTTP/3 и QUIC
Использование HTTP/3 на границе сети (Edge) позволяет мобильным пользователям (5G/6G) и пользователям с нестабильным соединением получать контент быстрее за счет быстрого восстановления пакетов и отсутствия блокировок TCP. В 2026 году это стандарт для более чем 60% глобального трафика.

**Почему HTTP/3 быстрее HTTP/2:**
- **0-RTT**: Повторное соединение без задержки на handshake (при условии сохранения PSK на клиенте).
- **Нет Head-of-Line Blocking**: Потеря одного пакета не блокирует доставку остальных потоков.
- **Миграция соединений**: Плавный переход между сетями (Wi-Fi -> 5G) без разрыва TCP.

**Включение HTTP/3 на стороне Origin:**
```nginx
# Nginx 1.25+ (с поддержкой HTTP/3)
listen 443 quic reuseport;
listen 443 ssl;
add_header Alt-Svc 'h3=":443"; ma=86400';
```

### Сжатие и форматы нового поколения
- **Zstandard (ZSTD)**: Повсеместное внедрение ZSTD обеспечило снижение TTFB на 15-20% по сравнению с Brotli при сопоставимом сжатии. Для включения на Origin:
  ```nginx
  # Nginx с ZSTD-модулем
  gzip on;
  gzip_comp_level 6;
  zstd_comp_level 3;
  location ~* \.(js|css|html|json)$ {
      add_header Vary "Accept-Encoding";
  }
  ```
- **AVIF**: Основной формат изображений 2026 года, обеспечивающий на 30% лучшее сжатие, чем WebP, при сохранении высокого качества (HDR). CDN автоматически транскодируют изображения в AVIF на лету.
- **Brotli (br)**: Все основные CDN поддерживают Brotli для текстовых ресурсов. Степень сжатия достигает 25% лучше, чем gzip (на высоких уровнях компрессии).

### Early Hints (HTTP 103)
Механизм, позволяющий серверу отправить предварительные заголовки (preconnect, preload) до того, как основной ответ будет сформирован. CDN кэширует эти подсказки и отдает клиенту сразу после первого обращения.

**Настройка на Origin:**
```nginx
location /index.html {
    add_header Link "</style.css>; rel=preload; as=style";
    add_header Link "</app.js>; rel=preload; as=script";
    # ... основная логика
}
```

**Эффект:** Браузер начинает загрузку критических CSS/JS и установку соединений с CDN на 100-500 мс раньше.

### HTTP Relay и Preconnect
- **102 Processing**: CDN может возвращать промежуточные ответы, информируя клиент о ходе обработки (особенно полезно для долгих API-запросов).
- **Preconnect Hints**: CDN автоматически определяет, какие подключения будут нужны клиенту, и инициирует их заранее.

---

## Кэширование и ключевые понятия

### Приоритет инструкций кэширования
Современные CDN-платформы следуют строгой иерархии (от высшего к низшему):
1. **Edge Rules (Панель управления)**: Глобальные правила провайдера.
2. **`CDN-Cache-Control` (RFC 9213)**: Инструкции для CDN, не затрагивающие браузерный кэш.
3. **`Cache-Control: s-maxage`**: Стандартная инструкция для shared-кэшей.
4. **`Cache-Control: max-age`**: Общая инструкция для всех уровней.
5. **`Expires`**: Устаревший метод (HTTP/1.0), использующий абсолютную дату.

### Формирование Cache Key
Cache Key — это уникальный идентификатор объекта в кэше. От правильности его формирования напрямую зависит Cache Hit Ratio.

**Стандартная нормализация (2026):**
| Параметр | Метод нормализации | Результат |
| :--- | :--- | :--- |
| Query-параметры | Сортировка + удаление `utm_*`, `gclid`, `fbclid` | `?b=2&a=1` -> `?a=1&b=2` |
| Accept-Encoding | Отдельные ключи для `gzip`, `br`, `zstd` | Два объекта для одного URL |
| Accept | Использование заголовка `Vary: Accept` | Разные версии для AVIF/WebP/JPEG |
| Регистр пути | Приведение к нижнему регистру | `/Image.PNG` -> `/image.png` |

**Настройка Cache Key в Cloudflare (пример):**
```bash
# Включение Host и Query String в ключе через API
curl -X PATCH "https://api.cloudflare.com/client/v4/zones/{zone_id}/cache/cache_keys" \
  -H "Authorization: Bearer {api_token}" \
  -d '{"query_string":{"ignore":false,"sort":true}}'
```

---

## Критерии эффективности и применимости

CDN не является универсальным решением для любого сайта. Его использование оправдано только при соблюдении ряда условий.

### Условия для максимальной отдачи
1. **Географическая распределенность аудитории**: Пользователи заходят из разных регионов или стран.
2. **Массовость и частота запросов**: Высокий трафик обеспечивает наполненность кэша (High Cache Hit Ratio). При низком трафике данные вытесняются из кэша.
3. **Единообразие контента**: Большинство пользователей запрашивает одни и те же файлы (статику).
4. **Наличие статического контента**: Изображения, CSS/JS, видео, PDF — всё, что может быть закэшировано.
5. **Высокий TTFB на Origin**: Если время отклика бэкенда превышает 200 мс, CDN существенно снизит задержку для удаленных пользователей.

### Сценарии, где CDN малоэффективен
- **Низкая посещаемость**: Файлы не успевают закрепиться в кэше и удаляются по истечении TTL или из-за редких обращений.
- **Узколокальная аудитория**: Если все пользователи находятся в одном городе с сервером-источником, лишнее звено в виде CDN только добавит задержку на DNS-резолвинг.
- **Преимущественно уникальный/архивный контент**: Если каждый пользователь запрашивает уникальные файлы, к которым больше никто не обращается, кэширование не принесет пользы.
- **Контент с высокой деградацией по TTL**: Если данные меняются каждые несколько секунд (биржевые котировки, игровое состояние), короткий TTL нивелирует преимущества кэширования.

---

## Бизнес-сценарии использования

| Отрасль / Тип проекта | Роль CDN | Примечание |
| :--- | :--- | :--- |
| **E-commerce / Маркетплейсы** | Раздача каталогов, карточек товаров и изображений. | Стабильный трафик и большой объем статики делают CDN критически важным. |
| **Online-игры** | Доставка обновлений (патчей) и игровых ассетов. | Пользователи одновременно загружают одни и те же пакеты данных. |
| **Медиа и СМИ** | Оперативная раздача новостей, фото- и видеорепортажей. | Высокая виральность контента создает пиковые нагрузки, которые гасит CDN. |
| **Стриминг и OTT** | Потоковое вещание аудио и видео (Live/VOD). | Минимизация буферизации и поддержка высокого разрешения (4K/8K). |
| **AI и Персонализация** | Запуск SLM-моделей на границе (Edge AI). | Мгновенная адаптация контента под пользователя без нагрузки на Origin. |
| **Разработка ПО** | Дистрибуция инсталляторов и обновлений. | Защита основного сервера от «эффекта толпы» в момент релиза. |
| **SaaS-платформы** | Глобальная доставка API-ответов и статики SPA. | Снижение TTFB для пользователей на удаленных континентах. |

---

## CDN и мобильные сети (5G/6G)

При использовании мобильного интернета (особенно в сетях 5G/6G) задержки на «последней миле» минимальны, поэтому географическая удаленность сервера становится основным фактором торможения.
- **MEC (Multi-access Edge Computing)**: Интеграция узлов CDN напрямую в инфраструктуру операторов связи, что позволяет достичь задержек менее 10 мс.
- **Open Caching**: Стандарт взаимодействия CDN с сетями сервис-провайдеров для кэширования контента глубоко внутри операторских сетей.
- **QUIC + 5G**: Комбинация HTTP/3 и 5G обеспечивает мгновенное восстановление соединений при переключении между Wi-Fi и мобильной сетью.

---

## Архитектурные концепции

### Как CDN находит «ближайший» сервер?

1. **GeoDNS**: DNS-сервер CDN определяет геолокацию пользователя на основе его IP-адреса и возвращает IP-адрес ближайшего PoP. Критически важна поддержка **[ECS (EDNS Client Subnet)](../Protocols/DNS/dns_advanced.md#edns-client-subnet-ecs)**.
2. **Anycast Routing**: Решение на уровне протокола **[BGP](../Protocols/bgp.md)**. CDN анонсирует один и тот же IP-адрес из всех своих PoP. Маршрутизаторы направляют трафик по кратчайшему топологическому пути. Обеспечивает мгновенный фейловер при отказе PoP.
3. **GSLB (Global Server Load Balancing)**: Эволюционировал в сторону Cloud Balancing, учитывающего не только географию, но и текущую загрузку узлов и стоимость трафика.

**Разница подходов:**
- **GeoDNS** работает на уровне L7 (DNS-резолвинг) и может учитывать ECS для определения локации клиента.
- **Anycast** работает на уровне L3 (BGP) и маршрутизирует трафик по топологическому расстоянию, что быстрее, но не учитывает текущую загрузку узла.
- **GSLB** работает на уровне L7 и комплексно оценивает географию, загрузку, стоимость и здоровье узлов.

### Защита Origin: Шилдинг (Origin Shield) и Tiered Caching

Шилдинг — это промежуточный уровень кэширования между Origin и пограничными узлами. В 2026 году это часть стратегии **Tiered Caching**:
1. Пограничные узлы при Cache Miss обращаются к региональному хабу или шилдингу.
2. Шилдинг делает ОДИН запрос к Origin, сохраняет результат и раздает его всем запрашивающим PoP.

**Преимущества:** Предотвращает эффект «лавинообразных запросов» (Thundering Herd) и снижает нагрузку на основной сервер до 99%.

**Пример конфигурации Tiered Caching (Cloudflare):**
```bash
# Включение в панели управления или через API
curl -X PATCH "https://api.cloudflare.com/client/v4/zones/{zone_id}/cache/tiered_cache" \
  -H "Authorization: Bearer {api_token}" \
  -d '{"value":"smart"}'
```

### TLS Termination и Early Data

CDN выполняет.terminate TLS-соединения на edge-узлах, снижая нагрузку на Origin:

- **TLS 1.3**: Стандарт 2026 года. Упрощенный handshake (1 RTT вместо 2 в TLS 1.2), поддержка 0-RTT для повторных соединений.
- **OCSP Stapling**: CDN кэширует сертификаты и отправляет клиентам актуальный статус, избегая задержек на проверку OCSP.
- **Certificate Management**: Автоматическое обновление сертификатов через протокол ACME (Let's Encrypt, DigiCert). CDN-провайдеры управляют сертификатами автоматически.

**Настройка TLS на Origin (рекомендации):**
```nginx
# Минимальная версия TLS — 1.3
ssl_protocols TLSv1.3;
ssl_prefer_server_ciphers off;

# OCSP Stapling
ssl_stapling on;
ssl_stapling_verify on;
resolver 1.1.1.1 8.8.8.8 valid=300s;

# Защита от BEAST/POODLE (хотя TLS 1.3 не уязвим)
ssl_session_cache shared:SSL:10m;
ssl_session_timeout 1d;
```

---

## Программируемая граница: Edge Computing и AI

### WebAssembly (Wasm) на Edge

Использование Wasm позволяет запускать высокопроизводительный код (Rust, Go) на пограничных узлах. Применяется для:
- Трансформации изображений и видео «на лету».
- Выполнения A/B тестирования и Edge Rendering.
- Сложной авторизации (Zero Trust Edge).
- Фильтрации ботов и IP-ограничений до обращения к Origin.

**Пример: Edge-функция на Cloudflare Workers (_bot-moderation):**
```javascript
// src/index.js
export default {
  async fetch(request, env) {
    const userAgent = request.headers.get("User-Agent") || "";

    // Блокировка известных ботов на границе
    const blockedBots = /scrapy|curl|wget|headless/i;
    if (blockedBots.test(userAgent)) {
      return new Response("Access Denied", { status: 403 });
    }

    // Пропуск легитимных запросов к Origin
    return fetch(request);
  }
};
```

**Пример: Edge-функция на Fastly Compute (image-transform):**
```rust
// src/main.rs
use fastly::{Error, Request, Response};

#[fastly::main]
fn main(req: Request) -> Result<Response, Error> {
    let path = req.get_path().to_string();

    if path.starts_with("/images/") && path.ends_with(".jpg") {
        // Трансформация изображения на edge
        let width = req.get_query_parameter::<String>("w")
            .unwrap_or_else(|| "800".to_string());

        // Логика ресайза (упрощенно)
        let mut resp = Response::from_status(200);
        resp.set_body(format!("Transformed image: {} width={}", path, width));
        resp.set_header("Content-Type", "image/jpeg");
        return Ok(resp);
    }

    // Delegation на Origin для остальных запросов
    let backend_req = Request::new("origin", req.get_method(), req.get_path(), req.into_body());
    Ok(backend_req.send("origin_backend")?)
}
```

### Edge AI

Развертывание компактных моделей (SLM) на узлах CDN с GPU-ускорением:
- Персонализация рекомендаций в реальном времени.
- Автоматическая модерация комментариев и контента.
- Оптимизация битрейта видео на основе анализа сетевых условий пользователя.

**Пример: AI-инференс на edge (Cloudflare Workers AI):**
```javascript
export default {
  async fetch(request, env) {
    const prompt = await request.text();

    // Запуск SLM-модели прямо на edge-узле
    const result = await env.AI.run("@cf/meta/llama-3.1-8b-instruct", {
      messages: [{ role: "user", content: prompt }]
    });

    return new Response(JSON.stringify(result), {
      headers: { "Content-Type": "application/json" }
    });
  }
};
```

---

## Безопасность и защита инфраструктуры

- **WAAP (Web Application and API Protection)**: Объединение WAF, защиты от ботов и защиты API в едином Edge-слое. Подробнее — в разделе [WAF: Web Application Firewall](../../Security/ApplicationSecurity/waf.md).
- **Сокрытие IP (IP Cloaking)**: Реальный IP Origin скрыт за Anycast-сетью. Ни один внешний запрос не достигает Origin напрямую, что делает прямые атаки невозможными.
- **Защита от DDoS (L3/L4/L7)**: Поглощение атак терабитного уровня за счет распределенной емкости сети. Подробнее — в разделе [DDoS: Распределённые атаки](../../Security/ApplicationSecurity/ddos_overview.md).
- **Bot Management**: Поведенческий анализ для блокировки парсеров и атак Brute Force на границе.
- **Signed URLs**: Временные подписанные ссылки для доступа к приватному контенту:
  ```bash
  # Генерация Signed URL (пример для Cloudflare)
  EXPIRES=$(($(date +%s) + 3600))  # Истекает через 1 час
  TOKEN=$(echo -n "${EXPIRES}/путь/к/файлу" | openssl dgst -sha256 -hmac "secret_key" | awk '{print $2}')
  echo "https://cdn.example.com/path/to/file?token=${TOKEN}&expires=${EXPIRES}"
  ```
- **IP Allowlisting**: Ограничение доступа к Origin только с IP-диапазонов CDN-провайдера:
  ```nginx
  # Nginx: разрешить только Cloudflare
  allow 103.21.244.0/22;
  allow 103.22.200.0/22;
  allow 103.31.4.0/22;
  deny all;
  ```
- **Rate Limiting**: Ограничение частоты запросов по IP, сессии или API-ключу для защиты от brute-force:
  ```nginx
  limit_req_zone $binary_remote_addr zone=api:10m rate=10r/s;
  location /api/ {
      limit_req zone=api burst=20 nodelay;
  }
  ```
- **Content Security Policy (CSP)**: Защита от XSS-инъекций через заголовок CSP, раздающийся CDN:
  ```http
  Content-Security-Policy: default-src 'self'; script-src 'self' cdn.example.com; img-src * data:
  ```

---

## Стратегии развертывания

- **Multi-CDN**: Использование нескольких провайдеров одновременно (например, Cloudflare + Akamai) для обеспечения 100% доступности и оптимизации цен.
  - **Weighted DNS**: Распределение трафика между CDN с весами (например, 70% Cloudflare, 30% Akamai).
  - **Failover**: Автоматическое переключение на резервный CDN при отказе основного.
  - **Cost Optimization**: Направление дешевого трафика на менее дорогой CDN.
- **Hybrid CDN**: Сочетание публичного CDN с собственной инфраструктурой в критических регионах. Кастомные PoP-серверы размещаются рядом с Origin для минимальных задержек.
- **P2P CDN (PeerCDN)**: Использование ресурсов других пользователей для раздачи. Экономит пропускную способность CDN для массовых событий (стримы, шоу).
- **Split-Tier CDN**: Сочетание CDN для статики (Cloudflare, Akamai) и кастомного решения для динамических API (собственный reverse proxy с BGP Anycast).

---

## Метрики и SLA

### Ключевые показатели эффективности

| Метрика | Описание | Целевое значение (2026) |
| :--- | :--- | :--- |
| **Cache Hit Ratio (CHR)** | Процент запросов, обслуженных из кэша | >98% (статика), >60% (динамика) |
| **Origin Offload** | Процент трафика, НЕ дошедший до Origin | >95% |
| **TTFB (Time To First Byte)** | Время до получения первого байта ответа | <50 мс (edge), <200 мс (origin) |
| **LCP (Largest Contentful Paint)** | Время загрузки основного контента | <2.5 сек (Core Web Vitals) |
| **Invalidation Latency** | Время глобальной инвалидации | <200 мс (Cloudflare, Fastly) |
| **Uptime** | Доступность CDN-сети | 99.99% (реже 52 мин простоя/год) |
| **Error Rate (5xx)** | Доля серверных ошибок CDN | <0.01% |

### SLA-показатели провайдеров

| Провайдер | SLA Uptime | Гарантия компенсации |
| :--- | :--- | :--- |
| **Cloudflare** | 100% (Enterprise) | 100x кредит за каждый час простоя |
| **Akamai** | 100% (Enterprise) | Договорная компенсация |
| **Fastly** | 100% | 20x кредит за каждый час простоя |
| **AWS CloudFront** | 99.9% | 10% кредит за каждый час простоя |

---

## Диагностика работы CDN

### Основные HTTP-заголовки

| Заголовок | Значение | Описание |
| :--- | :--- | :--- |
| `X-Cache` / `CF-Cache-Status` | `HIT` / `MISS` | Статус кэширования (устаревший; предпочтение — `Cache-Status`) |
| `Cache-Status` | `hit` / `miss` / `stale` / `bypass` | Стандартный RFC 9211 заголовок статуса кэша |
| `Age` | Число (секунды) | Время жизни объекта в кэше |
| `Alt-Svc` | `h3=":443"; ma=86400` | Поддержка HTTP/3 (QUIC) |
| `Server-Timing` | `edge;dur=12, origin;dur=45` | Детали времени обработки на каждом этапе |
| `CF-Ray` / `X-Request-ID` | UUID | Идентификатор запроса для трассировки |

### Диагностические команды

**Проверка DNS-резолвинга:**
```bash
# Определение IP-адреса PoP через DNS
dig +short example.com

# Проверка ECS (EDNS Client Subnet)
dig +short example.com +subnet=8.8.8.0/24

# Проверка ANAME/CNAME для корня домена
dig +short example.com CNAME
```

**Проверка HTTP-заголовков:**
```bash
# Базовая проверка заголовков CDN
curl -sI https://example.com | grep -iE "cache-status|age|alt-svc|cf-ray|server-timing"

# Проверка HTTP/3 поддержки
curl -sI --http3 https://example.com 2>&1 | grep -i "alt-svc"

# Проверка сжатия
curl -sI -H "Accept-Encoding: zstd" https://example.com/style.css | grep -i "content-encoding"

# Проверка TLS версии
curl -sI --tlsv1.3 --tls-max 1.3 https://example.com 2>&1 | grep -i "ssl"
```

**Проверка статуса кэша:**
```bash
# Детальный вывод кэша (Cloudflare)
curl -sD- https://example.com/image.jpg | grep -i "cf-cache-status"

# Проверка TTL в кэше
curl -sI https://example.com/static/app.js | grep -i "age\|cache-control\|expires"

# Проверка Surrogate Keys
curl -sI https://example.com/product/123 | grep -i "surrogate-key"
```

**Отладка TLS и протоколов:**
```bash
# Проверка версии TLS
openssl s_client -connect example.com:443 -tls1_3 </dev/null 2>/dev/null | grep "Protocol"

# Проверка OCSP Stapling
openssl s_client -connect example.com:443 -status </dev/null 2>/dev/null | grep "OCSP"

# Проверка сертификата
echo | openssl s_client -connect example.com:443 2>/dev/null | openssl x509 -noout -dates
```

---

## Типичные проблемы и их решение

### Проблемы с кэшированием

| Проблема | Симптом | Решение |
| :--- | :--- | :--- |
| **Низкий Cache Hit Ratio** | Много `MISS` в `Cache-Status`, высокая нагрузка на Origin | Проверить Cache Key, увеличить TTL, включить tiered caching, проверить `Cache-Control` на Origin |
| **Stale Content** | Пользователи видят устаревший контент после обновления | Уменьшить TTL, настроить `stale-while-revalidate`, использовать Purge API или Surrogate Keys |
| **Thundering Herd** | Всплеск нагрузки на Origin после истечения TTL популярного объекта | Включить Origin Shield, использовать `stale-if-error`, увеличить TTL |
| **Incorrect Cache Key** | Один и тот же URL кэшируется под разными ключами | Нормализовать query-параметры, проверить `Vary`-заголовки, использовать единый Cache Key |
| **Cache Poisoning** | CDN отдает некорректный/вредоносный контент | Включить `Origin Verification`, очищать URL от нерелевантных параметров |

### Проблемы с доставкой

| Проблема | Симптом | Решение |
| :--- | :--- | :--- |
| **Высокий TTFB** | `Server-Timing: origin;dur > 200ms` | Проверить маршрутизацию, оптимизировать Origin, включить `TCP Tuning` |
| **CORS ошибки** | Браузер блокирует запросы с другого домена | Добавить `Access-Control-Allow-Origin` в Origin или Edge Rules |
| **Mixed Content** | HTTP-ресурсы на HTTPS-странице | Включить `Always Use HTTPS`, автоматическую перезапись URL |
| **WebSocket отключается** | Разрыв long-lived соединений | Проверить timeout в CDN (обычно 100 сек для Cloudflare), увеличить Keep-Alive |

### Проблемы с безопасностью

| Проблема | Симптом | Решение |
| :--- | :--- | :--- |
| **Origin IP обнаружен** | Прямые атаки на Origin, минуя CDN | Сменить IP Origin, ограничить доступ через IP Allowlisting |
| **DDoS-атака** | Экстремальная нагрузка на edge-узлы | Включить DDOS Protection Level 5, активировать Under Attack Mode |
| **Бот-трафик** | Скачивание данных, рефлексия inventory | Включить Bot Management, настроить Rate Limiting |
| **SSL-ertificate Mismatch** | Ошибки TLS, предупреждения браузера | Проверить SAN/CNAME, обновить сертификат, включить SSL/TLS Full (Strict) |

---

## Практические аспекты

### CDN и SEO
- **Важно**: Используйте канонические ссылки (`rel="canonical"`) для предотвращения дублирования.
- **Core Web Vitals**: CDN напрямую улучшает LCP (Largest Contentful Paint) и TTFB.
- **Canonical URL через CDN**: Убедитесь, что CDN отдает правильные `Link`-заголовки:
  ```http
  Link: <https://example.com/page>; rel="canonical"
  ```

### Типовой процесс подключения

#### Шаг 1: Настройка DNS
```bash
# Вариант 1: CNAME (рекомендуется для поддоменов)
www.example.com -> CNAME -> cdn.example.com.cdn.cloudflare.net

# Вариант 2: ALIAS/ANAME (для корня домена)
example.com -> ALIAS -> cdn.example.com.cdn.cloudflare.net

# Вариант 3: Flat CNAME (Cloudflare) — CNAME на корне домена
example.com -> CNAME -> example.com.cdn.cloudflare.net
```

**Проверка после настройки:**
```bash
# Убедитесь, что домен резолвится в IP CDN
dig +short example.com

# Проверьте, что сайт доступен
curl -sI https://example.com | head -1
# → HTTP/2 200
```

#### Шаг 2: Подключение Origin
```bash
# Настройка Origin URL в панели CDN
# Cloudflare: Speed > Origin > Origin IP/Hostname
# Пример: 203.0.113.10 или origin.example.com

# Проверка доступности Origin из CDN
curl -sI -H "Host: example.com" https://203.0.113.10 | head -1
```

#### Шаг 3: Настройка SSL/TLS
```bash
# Рекомендуемый режим: Full (Strict) — проверка сертификата Origin
# Cloudflare: SSL/TLS > Overview > Full (Strict)

# Проверка SSL-режима
curl -sI https://example.com | grep -i "strict-transport-security"
```

#### Шаг 4: Правила кэширования
```bash
# Пример: минимальные правила для старта
# Cloudflare: Caching > Configuration > Browser Cache TTL = Respect Existing Headers

# Проверка кэширования
curl -sD- https://example.com/static/style.css | grep -iE "cache-status|age|cache-control"
# → cache-status: hit; ttl=86400
```

#### Шаг 5: Проверка работоспособности
```bash
# Полная диагностика
curl -sD- https://example.com \
  -H "Accept-Encoding: zstd" \
  | grep -iE "cache-status|cf-ray|server-timing|content-encoding|alt-svc"

# Ожидаемый результат:
# cache-status: hit
# cf-ray: 8a1b2c3d4e5f-LAX
# server-timing: edge;dur=3, origin;dur=0
# content-encoding: zstd
# alt-svc: h3=":443"; ma=86400
```

---

## Сертификаты и SSL/TLS через CDN

### Режимы SSL/TLS

| Режим | Описание | Использование |
| :--- | :--- | :--- |
| **Off** | Клиент ↔ CDN защищён, CDN ↔ Origin — по HTTP | Только для отладки (никогда в продакшене) |
| **Flexible** | Клиент ↔ CDN защищён TLS, CDN ↔ Origin — по HTTP | Origin не поддерживает TLS (крайний случай) |
| **Full** | Клиент ↔ CDN защищён TLS, CDN ↔ Origin защищён TLS (самоподписанный сертификат) | Origin имеет самоподписанный сертификат |
| **Full (Strict)** | Клиент ↔ CDN защищён TLS, CDN ↔ Origin защищён TLS (валидный сертификат) | Рекомендуется для production |

**Как это работает:**
1. Клиент устанавливает TLS с CDN (Edge).
2. CDN использует Universal Certificate (Cloudflare) или Custom Certificate для домена.
3. CDN подключается к Origin по TLS (в режиме Full/Full Strict).
4. TLS Termination происходит на CDN — Origin получает расшифрованный HTTP (или повторно шифрует).

**Certificate Management (автоматический):**
- **Cloudflare**: Universal SSL — автоматическое обновление через Let's Encrypt / DigiCert. Включается в 24 часа.
- **Fastly**: TLS для доменов через Let's Encrypt. Автоматическое обновление.
- **Akamai**: Managed Certificate — управляется через Support Portal. Обновление вручную или через API.
- **CloudFront**: ACM (AWS Certificate Manager) — автоматическое обновление для всех сертификатов.

**Origin Certificate:**
```
Рекомендация: создать отдельный сертификат для Origin
(самоподписанный или от внутреннего CA)
+ включить IP Allowlisting для доступа только с IP CDN.
```

### DNS для CDN: CNAME Flattening и ANAME

**Проблема:** Согласно RFC, CNAME не может существовать одновременно с другими записями для того же имени. Корневой домен (example.com) обычно требует SOA, NS и другие записи, что исключает использование CNAME.

**Решения:**

| Метод | Описание | Провайдеры |
| :--- | :--- | :--- |
| **CNAME Flattening** | Рекурсивный CNAME → A/AAAA перед возвратом клиенту | Cloudflare, NS1 |
| **ALIAS / ANAME** | Специальная тип DNS-записи, которая разрешает CNAME на корневом домене | DNSimple, Dyn |
| **Flat CNAME** | Cloudflare-специфичный: CNAME на корне домена через технологию Cloudflare | Cloudflare |
| **Proxy A/AAAA** | CDN-провайдер возвращает A-записи вместо CNAME | Akamai, Fastly |

**Примеры конфигурации:**
```bash
# Вариант 1: CNAME для поддомена (стандарт)
www.example.com. IN CNAME cdn.example.com.cdn.cloudflare.net.

# Вариант 2: ALIAS/ANAME для корня домена
example.com. IN ALIAS cdn.example.com.cdn.cloudflare.net.

# Вариант 3: Flat CNAME (Cloudflare)
# В панели Cloudflare: example.com → CNAME → example.com.cdn.cloudflare.net
# Cloudflare автоматически конвертирует в A-записи

# Вариант 4: DNS с ECS (EDNS Client Subnet)
dig +short example.com +subnet=8.8.8.0/24
# → 104.16.132.229 (IP ближайшего PoP к клиенту)
```

**TTL для CDN:**
- Рекомендуемый TTL DNS: **60 секунд** (позволяет быстрое переключение).
- При Failover: **30 секунд** (ещё быстрее переключение).
- При стабильной конфигурации: **300 секунд** (снижает нагрузку на DNS).

### Bot Management: классификация и действия

**Классификация ботов:**

| Тип | Описание | Действие |
| :--- | :--- | :--- |
| **Good Bots** | Поисковые роботы (Googlebot, Bingbot), мониторинг (Pingdom) | Разрешить, добавить в allowlist |
| **Neutral Bots** | API-клиенты, скрейперы, мониторинг | Разрешить с Rate Limiting |
| **Bad Bots** | Парсеры, атакующие боты, загрузчики контента | Блокировать |
| **Malicious Bots** | DDoS-ботнеты, Credential Stuffing | Блокировать + логировать |

**Методы обнаружения:**
- **JS Challenge**: Браузер должен выполнить JavaScript для доказательства «живости».
- **Managed Challenge**: Автоматический тест (Cloudflare): паттерн.cookie, behavior fingerprint.
- **CAPTCHA**: Требование ввода CAPTCHA (reCAPTCHA, hCaptcha).
- **Behavioral Analysis**: Анализ паттернов поведения (частота запросов, User-Agent, Accept headers).
- **IP Reputation**: Проверка IP в базах данных репутации (Spamhaus, AbuseIPDB).
- **TLS Fingerprinting (JA3/JA4)**: Уникальный «отпечаток» TLS-клиента.

**Cloudflare Bot Management API:**
```bash
# Настройка правил для ботов
curl -X POST "https://api.cloudflare.com/client/v4/zones/{zone_id}/firewall/rules" \
  -H "Authorization: Bearer {api_token}" \
  -H "Content-Type: application/json" \
  --data '[{
    "filter": {"expression": "cf.bot_management.score lt 30"},
    "action": "managed_challenge",
    "description": "Challenge suspicious bots"
  }]'
# → {"result":{"id":"...","action":"managed_challenge"}}

# Создание allowlist для Googlebot
curl -X POST "https://api.cloudflare.com/client/v4/zones/{zone_id}/firewall/rules" \
  -H "Authorization: Bearer {api_token}" \
  -H "Content-Type: application/json" \
  --data '[{
    "filter": {"expression": "cf.bot_management.verified_bot eq true and cf.bot_management.bot_name eq \"googlebot\""},
    "action": "allow",
    "description": "Allow Googlebot"
  }]'
```

**Rate Limiting для ботов:**
```nginx
# Nginx: Rate Limiting по IP и User-Agent
map $http_user_agent $is_bot {
    default 0;
    ~*bot 1;
    ~*crawler 1;
    ~*spider 1;
}

limit_req_zone $binary_remote_addr zone=global:10m rate=100r/s;
limit_req_zone $is_bot zone=bots:10m rate=10r/s;

server {
    location / {
        limit_req zone=global burst=200 nodelay;
        limit_req zone=bots burst=20 nodelay;
        limit_req_status 429;

        proxy_pass http://backend;
    }
}
```

### CDN и видео (HLS/DASH/CMAF/LL-HLS)

**Форматы потокового видео:**

| Формат | Описание | Задержка | Поддержка CDN |
| :--- | :--- | :--- | :--- |
| **HLS (HTTP Live Streaming)** | Apple-стандарт. Сегменты .ts, манифест .m3u8. | 6-30 сек | Все CDN |
| **DASH (MPEG-DASH)** | Открытый стандарт. Сегменты .m4s, манифест .mpd. | 6-30 сек | Все CDN |
| **CMAF** | Единый формат сегментов для HLS и DASH (.cmfv, .cmfa, .cmfmc). | 6-30 сек | Все CDN |
| **LL-HLS** | Low-Latency HLS: сегменты .ts/.cmfv с частичными загрузками. | 2-4 сек | Cloudflare, Fastly, Akamai |
| **LL-DASH** | Low-Latency DASH. | 2-4 сек | Ограниченная |

**Что кэширует CDN в видео:**
- **Сегменты (.ts/.m4s/.cmfv)**: Кэшируются с длинным TTL. Один сегмент = 2-10 сек видео.
- **Манифесты (.m3u8/.mpd)**: Кэшируются с коротким TTL (1-60 сек) для обновления списка сегментов.
- **Ключи шифрования (.key)**: Кэшируются. Используются для DRM (AES-128).

**CMAF — единый формат:**
```
CMAF (Common Media Application Format)
├── Video: H.264/H.265/AV1 в формате .cmfv
├── Audio: AAC/Opus в формате .cmfa
├── Subtitles: WebVTT в формате .cmft
└── Metadata: В .cmfv заголовке
```
Преимущество: один сегмент используется и для HLS, и для DASH → CDN кэширует один раз.

**ABR (Adaptive Bitrate):**
```
Клиент → CDN → Манифест (список качеств)
Клиент выбирает качество на основе:
  - Bandwidth (пропускная способность)
  - Buffer (уровень буфера)
  - Latency (задержка)
```

**Низкая задержка через CDN:**
```bash
# LL-HLS: Partial Segments
# Сегмент разбивается на части (partial segments)
# Клиент загружает partial segment до завершения формирования

# Пример URL для LL-HLS
https://cdn.example.com/live/stream.m3u8?_HLS_msn=1234&_HLS_part=3
# _HLS_msn = номер сегмента
# _HLS_part = номер partial segment
```

### Edge Computing: ограничения и архитектура

**Ограничения Edge Functions (2026):**

| Параметр | Cloudflare Workers | Fastly Compute | Akamai EdgeWorkers |
| :--- | :--- | :--- | :--- |
| **Runtime** | V8 (JavaScript/TypeScript, Wasm) | Wasm (Rust, Go, JS) | V8 (JavaScript) |
| **CPU Time** | 10 мс (Free), 30 сек (Enterprise) | 120 сек | 5 сек |
| **Memory** | 128 МБ | 128 МБ | 64 МБ |
| **Disk Space** | 0 (stateless) | 0 (stateless) | 0 (stateless) |
| **Connections** | 6 (HTTP), 6 (WebSocket) | Нет лимита (keep-alive) | 4 |
| **Subrequests** | 50/запрос | Нет лимита | 10/запрос |
| **Cold Start** | 0 мс (V8 Isolates) | 0 мс (Wasm) | 0 мс (V8) |
| **Edge KV** | 1 ГБ (KV), 10 ГБ (R2) | 0 | 5 МБ (EdgeKV) |

**Модель изоляции:**
- **V8 Isolates (Cloudflare Workers)**: Каждый запрос — изолированный isolate. Мгновенный холодный старт (0 мс). Разделяемая память через V8.
- **Wasm Modules (Fastly Compute)**: Каждый запрос — отдельный Wasm-модуль. Полная изоляция. Мгновенный старт.
- **V8 Isolates (Akamai EdgeWorkers)**: Аналогично Cloudflare, но с меньшими лимитами.

**Пример: Edge Function для авторизации (Cloudflare Workers):**
```javascript
export default {
  async fetch(request, env) {
    const token = request.headers.get('Authorization');
    
    if (!token) {
      return new Response('Unauthorized', { status: 401 });
    }
    
    // Верификация JWT на edge (без запроса к Origin)
    const payload = await verifyJWT(token, env.JWT_SECRET);
    
    if (!payload) {
      return new Response('Invalid token', { status: 403 });
    }
    
    // Добавление метаданных пользователя в заголовки
    const modifiedRequest = new Request(request);
    modifiedRequest.headers.set('X-User-ID', payload.sub);
    modifiedRequest.headers.set('X-User-Role', payload.role);
    
    return fetch(modifiedRequest);
  }
};
```

**Edge KV Store:**
```javascript
// Cloudflare Workers KV — key-value store на edge
export default {
  async fetch(request, env) {
    const key = new URL(request.url).searchParams.get('key');
    
    // Чтение из KV (edges遍布 мире)
    const value = await env.MY_KV.get(key);
    
    if (!value) {
      return new Response('Not found', { status: 404 });
    }
    
    return new Response(value);
  }
};
```

---

## Дополнительная информация

### Типы CDN-архитектур

| Тип | Описание | Сценарий использования |
| :--- | :--- | :--- |
| **Pull Zone** | CDN сам забирает контент при первом обращении. | Универсальный вариант для большинства сайтов. |
| **Push Zone** | Вы заранее загружаете файлы на серверы CDN. | Тяжелые файлы, игровые патчи, инсталляторы. |
| **P2P CDN** | Использование ресурсов других пользователей для раздачи. | Масштабные Live-трансляции, снижение стоимости трафика. |
| **Reverse Proxy CDN** | CDN выступает обратным прокси для всего трафика (не только статики). | Сайты с высоким процентом динамического контента. |

### Преимущества и недостатки

**(+) Преимущества:**
- **Производительность**: Минимизация задержек и высокая скорость доставки.
- **Масштабируемость**: Обработка пиковых нагрузок без масштабирования Origin.
- **Экономия**: Снижение нагрузки на полосу пропускания Origin и стоимость Egress.
- **Безопасность**: Встроенная защита от DDoS, WAF и ботов.
- **Доступность**: Автоматический failover при отказе PoP.

**(-) Недостатки:**
- **Стоимость**: Расходы на трафик и дополнительные фичи безопасности.
- **Инвалидация**: Задержки при обновлении контента (Propagation Delay).
- **Сложность отладки**: Проблемы могут возникать на промежуточных узлах.
- **Vendor Lock-in**: Проприетарные API усложняют миграцию между провайдерами.
- **Ошибки кэширования**: Неправильные заголовки на Origin могут привести к раздаче устаревшего контента.

### Популярные провайдеры (2026)

| Провайдер | Сила | Слабость |
| :--- | :--- | :--- |
| **Cloudflare** | Лидер в Edge AI (Workers), WAF и безопасности. Бесплатный план. | Дорогие Enterprise-функции, сложная цена-политика. |
| **Akamai** | Крупнейшее покрытие (~4100 PoP), лидер в Enterprise и видео (ESPN, Netflix). | Высокая стоимость, сложная конфигурация. |
| **Gcore** | Высокая производительность, лидер в Edge AI и игровых сервисах. | Менее развитая экосистема CDN по сравнению с Cloudflare. |
| **Fastly** | Максимальная программируемость (Compute), быстрая инвалидация (<150 мс). | Ограниченное покрытие, дороже для базового кэширования. |
| **Amazon CloudFront** | Глубокая интеграция с AWS (Lambda@Edge, S3). | Привязка к AWS, менее гибкая конфигурация, ограниченная программируемость. |
| **Yandex CDN** | Локализация для СНГ, интеграция с Yandex Cloud. | Ограниченное глобальное покрытие, меньший функционал Edge Computing. |

---

## См. также

- [Политики кэширования и инвалидации в CDN](cdn_caching_and_invalidation.md) — Cache-Control, Purge, Surrogate Keys, SWR.
- [Health Checks, Circuit Breaker и Origin Failover](cdn_origin_health_checks.md) — мониторинг Origin, отказоустойчивость.
- [Оптимизация стоимости CDN](cdn_cost_optimization.md) — Egress pricing, Reserved Capacity, Cost Routing.
- [Логирование, Tracing и Observability](cdn_logging_and_tracing.md) — CF-Ray, traceparent, structured logging.
- [WebSocket, SSE и gRPC через CDN](cdn_websocket_sse_grpc.md) — long-lived соединения, streaming.
- [Реализация Multi-CDN](cdn_multi_cdn_implementation.md) — Weighted DNS, Failover, Cost Routing.
- [HTTP-кэширование](../Protocols/HTTP/http_caching.md) — заголовки Cache-Control, ETag, Conditional Requests.
- [Edge Computing](../../Concepts/edge_computing_overview.md) — выполнение кода на CDN.
- [Защита от DDoS (L7)](../../Security/ApplicationSecurity/ddos_overview.md) — CDN и DDoS.
- [BGP и Anycast](../Protocols/bgp.md) — маршрутизация через CDN.

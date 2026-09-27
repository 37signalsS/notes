# DNS over HTTPS (DoH) в Angie

## Определения

**DNS over HTTPS (DoH, RFC 8484)** — протокол инкапсуляции DNS-запросов в HTTPS-трафик (порт 443/TCP). Шифрует DNS-сообщения на транспортном уровне, предотвращая перехват, подмену ответов и цензуру на уровне сети. DoH маскирует DNS-активность под обычный HTTPS-трафик, что затрудняет его блокировку и анализ.

**Модуль `doh` в Angie** — прокси-модуль, реализующий функциональность DoH-сервера. Доступен начиная с версии Angie 1.12. Модуль позволяет принимать DNS-запросы по протоколу HTTPS, проксировать их на вышестоящие DNS-резолверы и возвращать ответы клиентам в формате `application/dns-message`.

## Базовые концепции

### Архитектура и принцип работы

Модуль `doh` относится к классу прокси-модулей контекста `http`. Его работа включает следующие этапы:

1. **Приём запроса:** Клиент отправляет DNS-запрос методом POST (или GET) по адресу `https://<host>/dns-query` с заголовком `Content-Type: application/dns-message`.
2. **Обработка:** Angie извлекает DNS-сообщение из тела запроса и проксирует его на вышестоящий DNS-сервер через `doh_pass`.
3. **TTL и кэширование:** Время жизни записи (TTL) из DNS-ответа передаётся через HTTP-заголовок `Cache-Control: max-age=<ttl>`. Это позволяет промежуточным кэширующим прокси корректно учитывать TTL DNS-записей.
4. **Ответ:** Angie возвращает клиенту DNS-ответ с заголовком `Content-Type: application/dns-message`.

### Ключевые директивы

| Директива | Контекст | Назначение |
| :--- | :--- | :--- |
| `doh_pass` | `location` | Направляет DoH-запросы на upstream-группу DNS-серверов. |
| `doh_bind` | `location` | Привязывает обработку DoH-запросов к указанному IP-адресу/порту (опционально). |
| `doh_transport` | `http`, `server`, `location` | Ограничивает транспорт для запросов к апстриму: `udp` (по умолчанию) или `tcp`. |
| `doh_insecure` | `http`, `server`, `location` | Разрешает работу с самоподписанными или невалидными сертификатами на стороне апстрима (если апстрим работает по HTTPS). |

### Особенности TTL

В классическом DNS TTL указывается в секундах и управляет кэшированием записи резолверами. В DoH TTL передаётся через стандартный HTTP-заголовок кэширования:

```nginx
add_header Cache-Control "max-age=394";
```

где `394` — значение TTL в секундах, полученное из DNS-ответа. Angie автоматически может использовать переменные для формирования этого заголовка.

## Практические сценарии

### Сценарий 1: Базовая конфигурация DoH-сервера

Настройка DoH-сервера с проксированием на внешние или внутренние DNS-резолверы. В качестве транспорта по умолчанию используется UDP.

```nginx
http {
    resolver 1.1.1.1 8.8.8.8 valid=300s;

    upstream dns_upstream {
        server 192.168.1.10:53;
        server 192.168.1.11:53;

        # Keepalive поддерживает постоянные TCP-соединения,
        # что актуально при использовании doh_transport tcp
        keepalive 32;
    }

    server {
        listen 443 ssl;
        server_name doh.example.com;

        # Статические сертификаты или переменные ACME (см. Сценарий 2)
        ssl_certificate     /etc/angie/ssl/doh.example.com.crt;
        ssl_certificate_key /etc/angie/ssl/doh.example.com.key;

        # Локация по умолчанию обрабатывает DoH-запросы
        location / {
            doh_pass dns_upstream;
            # Необходимый заголовок для корректной обработки DoH
            add_header Content-Type "application/dns-message";
        }
    }
}
```

### Сценарий 2: DoH с автоматическими сертификатами ACME

Использование встроенного модуля `acme` для автоматической выдачи и продления TLS-сертификатов. Исключает необходимость ручного управления сертификатами и убирает статические пути.

```nginx
http {
    resolver 1.1.1.1 8.8.8.8 valid=300s;

    # Объявление ACME-клиента
    acme_client doh_acme {
        directory https://acme-v02.api.letsencrypt.org/directory;
        challenge http;
        key_type ecdsa;
    }

    upstream dns_upstream {
        server 192.168.1.10:53;
        server 192.168.1.11:53;
        keepalive 32;
    }

    server {
        listen 443 ssl;
        server_name doh.example.com;

        # Подключение ACME-клиента внутри сервера
        acme doh_acme;

        # Использование переменных вместо статических путей
        ssl_certificate     $acme_cert_doh_acme;
        ssl_certificate_key $acme_cert_key_doh_acme;

        location / {
            doh_pass dns_upstream;
            add_header Content-Type "application/dns-message";
        }
    }
}
```

### Сценарий 3: Ограничение транспорта TCP

Использование директивы `doh_transport tcp` для принудительного использования TCP при проксировании запросов на апстрим. Полезно в сетях с фрагментацией UDP или при необходимости гарантированной доставки.

```nginx
http {
    upstream dns_upstream {
        server 192.168.1.10:53;
        keepalive 32;
    }

    server {
        listen 443 ssl;
        server_name doh.example.com;

        acme doh_acme;
        ssl_certificate     $acme_cert_doh_acme;
        ssl_certificate_key $acme_cert_key_doh_acme;

        # Ограничение транспорта до TCP для апстрима
        doh_transport tcp;

        location / {
            doh_pass dns_upstream;
            add_header Content-Type "application/dns-message";

            # Включение TCP_NODELAY на исходящих соединениях
            tcp_nodelay on;
        }
    }
}
```

### Сценарий 4: Валидация и тестирование

Проверка работоспособности DoH-сервера с помощью `curl`. Метод HEAD позволяет получить заголовки без загрузки тела ответа, что удобно для отладки.

```bash
curl -I "https://doh.example.com/dns-query?name=yandex.ru&type=A"
```

Ожидаемые результаты успешного запроса:

*   HTTP/2 200 (или HTTP/1.1 200).
*   Заголовок `Content-Type: application/dns-message`.
*   Заголовок `Cache-Control: max-age=<ttl>`, где `<ttl>` соответствует TTL DNS-записи (например, `394`).
*   В теле ответа (при использовании GET/POST) — бинарный DNS-ответ, который можно расшифровать утилитами `dig` или `doggo`.

Для проверки с игнорированием проблем с сертификатом (самоподписанные, неправильный домен) можно использовать флаг `insecure`:

```bash
curl -I --insecure "https://doh.example.com/dns-query?name=yandex.ru&type=A"
```

Для детального анализа DNS-ответа удобно использовать утилиту `doggo`:

```bash
doggo yandex.ru --nameserver https://doh.example.com/dns-query
```

## Операции и команды

### Диагностика через `curl`

Проверка заголовков и формата ответа:

```bash
curl -I "https://doh.example.com/dns-query?name=example.com&type=A"
# → HTTP/2 200
# → Content-Type: application/dns-message
# → Cache-Control: max-age=394

# Проверка с игнорированием проблем с сертификатом
curl -I --insecure "https://doh.example.com/dns-query?name=example.com&type=A"
```

### Проверка DNS-ответа

Декодирование бинарного DNS-ответа:

```bash
curl -s "https://doh.example.com/dns-query?name=example.com&type=A" | \
  doggo --format text
```

Или с утилитой `dig` через прокси:

```bash
dig @127.0.0.1 -p 53 example.com A +dnssec
```

### Проверка конфигурации

```bash
# Проверка синтаксиса конфигурации
sudo angie -t
# → angie: the configuration file /etc/angie/angie.conf syntax is ok
# → angie: configuration file /etc/angie/angie.conf test is successful
```

### Проверка статуса ACME-сертификата

```bash
# Поиск событий ACME в логах
grep -i acme /var/log/angie/error.log | tail -20

# Принудительное обновление сертификата
sudo systemctl reload angie
# Или удаление файлов для принудительного перевыпуска
sudo rm -rf /var/lib/angie/acme/doh_acme*
sudo systemctl reload angie
```

### Проверка upstream DNS

```bash
# Резолвинг напрямую через апстрим (UDP)
dig @192.168.1.10 -p 53 example.com A +short
# → 93.184.215.14

# Резолвинг через DoH-эндпоинт
curl -s "https://doh.example.com/dns-query?name=example.com&type=A" | \
  doggo --format text
```

### Проверка слушаемых портов

```bash
ss -tlnp | grep angie
# → LISTEN 0 128 0.0.0.0:443
```

## Устранение неисправностей

### Пустой или некорректный DNS-ответ

**Симптом:** `curl` возвращает 200, но `Content-Type` отсутствует или ответ пустой.

**Диагностика:**
```bash
curl -I "https://doh.example.com/dns-query?name=example.com&type=A"
```

**Причины:**
*   Отсутствует директива `add_header Content-Type "application/dns-message";` в `location`.
*   Upstream-сервер недоступен или возвращает невалидный DNS-ответ.
*   Конфигурация `resolver` не указана или указан неверный IP.

**Решение:** Добавьте заголовок, проверьте доступность upstream, убедитесь в корректности `resolver`.

### Ошибка сертификата TLS

**Симптом:** `curl: (60) SSL certificate problem: unable to get local issuer certificate`.

**Диагностика:**
```bash
openssl s_client -connect doh.example.com:443 -servername doh.example.com -showcerts
```

**Причины:**
*   Сертификат просрочен или не соответствует домену.
*   ACME-клиент не смог обновить сертификат.
*   Цепочка сертификатов неполная (отсутствует промежуточный CA).

**Решение:** Обновите сертификат, проверьте конфигурацию ACME, добавьте промежуточный сертификат через `ssl_trusted_certificate`.

### TTL не передаётся клиенту

**Симптом:** Заголовок `Cache-Control` отсутствует или имеет значение `max-age=0`.

**Диагностика:**
```bash
curl -I "https://doh.example.com/dns-query?name=example.com&type=A" | grep -i cache
```

**Причины:**
*   Upstream-сервер не возвращает TTL в DNS-ответе.
*   Промежуточный прокси (например, CDN) перезаписывает заголовки.

**Решение:** Убедитесь, что upstream-резолвер корректно возвращает TTL. Настройте `proxy_hide_header` и `add_header` на уровне Angie, если требуется принудительное значение.

### Upstream DNS недоступен

**Симптом:** DoH-сервер возвращает 502 Bad Gateway или DNS-запросы зависают.

**Диагностика:**
```bash
dig @192.168.1.10 -p 53 example.com A +short
# Проверка доступности апстрима на порт 53/UDP
nc -zv 192.168.1.10 53
# → Connection succeeded!
```

**Причины:**
*   DNS-резолвер не отвечает.
*   Брандмауэр блокирует порт 53/UDP или 53/TCP между Angie и upstream.
*   Неверный IP-адрес upstream в конфигурации.

**Решение:** Проверьте доступность upstream, настройте `resolver` в Angie, откройте порт 53 в брандмауэре.

### ACME-сертификат не обновляется

**Симптом:** В `error.log` появляются ошибки `acme: certificate renewal failed`.

**Диагностика:**
```bash
grep -i acme /var/log/angie/error.log | tail -20
```

**Причины:**
*   Порты 80/443 заняты другим процессом (ACME-HTTP-01 challenge).
*   Лимиты Let's Encrypt исчерпаны (50 сертификатов/неделю на домен).
*   DNS-запись не прописана для домена.

**Решение:** Освободите порты, используйте Staging-сервер для тестирования, проверьте DNS-запись домена.

## Лучшие практики

### Производительность

*   **TCP-транспорт для апстрима:** При использовании `doh_transport tcp` включайте `keepalive` в upstream-группе. Это снижает накладные расходы на установку TCP-соединений при высокой частоте запросов.
*   **Ограничение размера запроса:** DoH-запросы по RFC 8484 ограничены 65535 байт. Angie автоматически обрабатывает это ограничение, но убедитесь, что промежуточные прокси не обрезают тело запроса.
*   **Кэширование:** Используйте промежуточные кэширующие прокси (например, Varnish или CDN) с учётом заголовка `Cache-Control: max-age=<ttl>`. Это снижает нагрузку на DoH-сервер и upstream-резолвер.

### Безопасность

*   **Валидные сертификаты:** Используйте сертификаты от доверенного CA. Для production исключите `doh_insecure`.
*   **Ограничение сети:** Если DoH-сервер предназначен только для внутренних клиентов, ограничьте доступ через `allow/deny` или брандмауэр.
*   **ACME-режим:** Для тестирования используйте Staging-сервер Let's Encrypt, чтобы избежать исчерпания лимитов.
*   **Аудит:** Регулярно проверяйте `error.log` на наличие ошибок ACME и TLS-handshake.

### Эксплуатация

*   **Мониторинг upstream:** Настройте health-check для upstream-группы DNS-резолверов. При недоступности резолвера DoH-сервер должен корректно обрабатывать ошибки (502/503).
*   **Логирование:** Включите `access_log` для DoH-локации с переменными `$request_id` и `$status` для отслеживания запросов.
*   **Резервирование:** Используйте несколько upstream-резолверов (например, 1.1.1.1, 8.8.8.8, внутренний резолвер) для отказоустойчивости.
*   **Тестирование после изменений:** После изменения конфигурации всегда выполняйте `angie -t` и проверяйте ответ через `curl` перед применением `reload`.

## Дополнительная информация

### Требования и ограничения

*   **Версия Angie:** Модуль `doh` доступен начиная с версии **Angie 1.12**.
*   **Транспорт:** По умолчанию запросы к апстриму отправляются по UDP. Для использования TCP применяйте `doh_transport tcp`.
*   **Keepalive:** При использовании TCP рекомендуется включать `keepalive` в upstream-группе для снижения накладных расходов на установку соединений.
*   **Доверенная сеть:** DNS-серверы, на которые проксируются запросы, должны находиться в доверенной сети и быть под вашим контролем. Это исключает риск подмены ответов на следующем этапе обычного DNS-запроса.
*   **Сертификаты:** Для production-сред рекомендуется использовать валидные сертификаты. Для тестирования с самоподписанными сертификатами можно применять `doh_insecure`.

### Безопасность

*   DoH защищает от перехвата и подмены DNS-трафика в пути между клиентом и DoH-сервером.
*   Angie не обходит ограничения CA при использовании ACME (лимиты Let's Encrypt: 50 сертификатов в неделю на домен). Для тестирования используйте Staging-сервер.
*   Убедитесь, что порт 443/TCP доступен для клиентов. В корпоративных сетях с жёстким файрволом может потребоваться дополнительная конфигурация.

### RFC и стандарты

*   **RFC 8484:** DNS over HTTPS (DoH) — основная спецификация протокола.
*   **RFC 9230:** Oblivious DNS over HTTPS (ODoH) — расширение DoH с промежуточным прокси для разделения идентификации клиента и содержания запроса.
*   **RFC 8467:** Padding for DNS Messages to Reduce Blocking — выравнивание размера сообщений для предотвращения анализа трафика по размеру.

## См. также

*   **[Автоматические TLS-сертификаты в Angie: модуль ACME](./angie_acme_module.md)**
*   **[Настройка TLS в Angie](./angie_tls_setup.md)**
*   **[Безопасность DNS: DoH, DoT, DoQ](../../Networking/Protocols/DNS/dns_security.md)**
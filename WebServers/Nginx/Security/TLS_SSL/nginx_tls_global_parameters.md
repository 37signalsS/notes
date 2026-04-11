# Глобальные параметры TLS в Nginx

## Определения

### Глобальные параметры TLS

Параметры TLS, которые применяются ко всем виртуальным хостам Nginx. Размещаются в `nginx.conf` внутри блока `http`, в отличие от параметров виртуального хоста, которые задаются в блоке `server`.

### Кэш сессий TLS (Session Cache)

Механизм хранения параметров TLS-сессий на стороне сервера. Позволяет клиентам выполнять сокращённое рукопожатие (resumed handshake) при повторных подключениях, избегая полного TLS handshake. Используется для TLS 1.2 и ниже.

### Билеты сессий (Session Tickets)

Альтернативный механизм возобновления сессий, при котором зашифрованная информация о сессии хранится на стороне клиента. Является основным для TLS 1.3, но может использоваться и для TLS 1.2.

### OCSP Stapling

Механизм, при котором сервер сам получает подписанный OCSP-ответ от центра сертификации (CA) и прикрепляет его к TLS-рукопожатию. Избавляет клиента от отдельного запроса к OCSP-серверу, ускоряя установку соединения.

## Основные понятия

### Требования к OpenSSL

Для полной поддержки TLS 1.3 и современных шифров Nginx должен быть собран с OpenSSL версии 1.1.1 или выше. Проверить версию можно командой:

```bash
nginx -V  # Искать строку "built with OpenSSL ..."
```

Если используется старая версия, может потребоваться пересборка Nginx или использование PPA с более свежей сборкой.

### Keep-Alive и TLS

Длительные keep-alive соединения позволяют клиентам повторно использовать одно TCP-соединение для нескольких HTTP-запросов, что сокращает задержки, связанные с установкой новых соединений и TLS-рукопожатий.

```nginx
http {
    keepalive_timeout 120s;
    keepalive_requests 10000;
}
```

- `keepalive_timeout` — таймаут для keep-alive соединения.
- `keepalive_requests` — максимальное количество запросов через одно keep-alive соединение.

### Кэширование сессий TLS

#### Кэш на стороне сервера (`ssl_session_cache`)

Механизм для TLS 1.2 и ниже. Создаёт общую для всех worker-процессов зону в памяти.

```nginx
http {
    # 10 МБ ≈ 40 000 сессий
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 1d;
}
```

#### Билеты сессий (`ssl_session_tickets`)

```nginx
ssl_session_tickets off;
```

**Компромисс `off` vs `on`:**

- `on` — улучшает производительность повторных подключений (восстановление без полного handshake). Для кластера настраивается общий ключ через `ssl_session_ticket_key`.
- `off` (рекомендуется) — более безопасный подход. Билеты сессий имели проблемы с безопасностью и могут ослабить Perfect Forward Secrecy (PFS): при компрометации ключа шифрования билетов можно расшифровать все сессии, зашифрованные с его помощью.

### Протоколы и шифры

#### `ssl_protocols`

Жёстко ограничивает версии протоколов:

```nginx
http {
    ssl_protocols TLSv1.2 TLSv1.3;
}
```

Запрещает устаревшие протоколы (SSLv2, SSLv3, TLS 1.0, TLS 1.1), уязвимые к атакам POODLE, BEAST и др.

#### `ssl_ciphers` (TLS 1.2 и ниже)

Определяет набор шифров (cipher suite) — алгоритмов для защиты соединения:

```nginx
ssl_ciphers 'ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305:DHE-RSA-AES128-GCM-SHA256:DHE-RSA-AES256-GCM-SHA384';
```

- **AES** (AES128-GCM, AES256-GCM) — аппаратное ускорение на большинстве десктопных процессоров.
- **ChaCha20** (CHACHA20-POLY1305) — лучшая производительность на мобильных устройствах без аппаратной поддержки AES.

Для генерации актуальной конфигурации используйте [Mozilla TLS Configurator](https://ssl-config.mozilla.org/).

#### `ssl_prefer_server_ciphers`

Определяет, кто выбирает финальный шифр — сервер или клиент:

- `on` (старый подход) — сервер выбирает первый подходящий шифр из своего списка.
- `off` (современный подход) — сервер учитывает предпочтения клиента. Современные браузеры выбирают не только самый безопасный, но и самый производительный шифр.

Для TLS 1.3 набор шифров стандартизирован (`TLS_AES_128_GCM_SHA256`, `TLS_AES_256_GCM_SHA384`, `TLS_CHACHA20_POLY1305_SHA256`) и не требует ручной настройки.

### `ssl_buffer_size`

Размер буфера TLS-записи. По умолчанию 16k — оптимально для большинства случаев (соответствует размеру TLS-записи, избегает фрагментации). Уменьшение (до 8k) может улучшить TTFB для динамического контента, но незначительно увеличит нагрузку на CPU.

```nginx
ssl_buffer_size 8k;
```

### `ssl_dhparam`

Указывает путь к файлу с параметрами для алгоритма обмена ключами Диффи-Хеллмана (DHE, не ECDHE). Использование заранее сгенерированных параметров (2048 бит) повышает безопасность и необходимо для PFS.

```bash
openssl dhparam -out /etc/nginx/dhparam.pem 2048
```

```nginx
ssl_dhparam /etc/nginx/dhparam.pem;
```

Не требуется для конфигураций, использующих только ECDHE и/или TLS 1.3.

### `ssl_early_data` (0-RTT для TLS 1.3)

Включает 0-RTT для TLS 1.3, ускоряя повторные соединения. Несёт риск replay-атак — данные первого пакета могут быть перехвачены и воспроизведены.

```nginx
ssl_early_data on;
```

## Практические сценарии

### Полная глобальная конфигурация TLS

Размещается в `nginx.conf` внутри блока `http`:

```nginx
http {
    # Keep-Alive
    keepalive_timeout 120s;
    keepalive_requests 10000;

    # Кэш сессий TLS
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 1d;
    ssl_session_tickets off;

    # Протоколы и шифры
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers 'ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305:DHE-RSA-AES128-GCM-SHA256:DHE-RSA-AES256-GCM-SHA384';
    ssl_prefer_server_ciphers off;

    # Буфер TLS
    ssl_buffer_size 8k;

    # DHE параметры (не требуется для ECDHE-only / TLS 1.3)
    # ssl_dhparam /etc/nginx/dhparam.pem;

    # 0-RTT (с осторожностью — риск replay-атак)
    # ssl_early_data on;

    # OCSP Stapling
    ssl_stapling on;
    ssl_stapling_verify on;
    resolver 8.8.8.8 8.8.4.4 valid=300s;
    resolver_timeout 5s;
}
```

### Настройка OCSP Stapling

OCSP Stapling требует DNS-резолвер. Рекомендуется использовать надёжные публичные DNS или внутренние:

```nginx
ssl_stapling on;
ssl_stapling_verify on;
resolver 8.8.8.8 8.8.4.4 valid=300s;
resolver_timeout 5s;
```

## Дополнительная информация

- [Оптимальная настройка TLS/SSL в Nginx](./nginx_tls_ssl_overview.md) — обзор концептов TLS/SSL
- [Конфигурация виртуальных хостов TLS](./nginx_tls_virtual_host_config.md) — настройка на уровне `server`
- [Протокол TLS](../../../../Networking/Protocols/tls.md) — теория протокола
- [Mozilla TLS Configurator](https://ssl-config.mozilla.org/) — генератор конфигурации

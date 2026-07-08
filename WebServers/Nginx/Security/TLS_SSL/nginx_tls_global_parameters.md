# Глобальные параметры TLS в Nginx

## Определения

**Глобальные параметры TLS** — настройки протокола безопасности, которые задаются в блоке `http` файла `nginx.conf` и применяются ко всем виртуальным хостам сервера. Централизованное управление этими параметрами обеспечивает единообразную политику безопасности и производительности для всех сайтов.

**Возобновление сессии (Session Resumption)** — механизмы, позволяющие клиенту и серверу повторно использовать ранее согласованные параметры безопасности, избегая полного процесса рукопожатия.

* **[Механизмы возобновления сессии](../../../../Networking/Protocols/tls.md#возобновление-сессии-session-resumption)** (теория).

**OCSP Stapling** — технология оптимизации, при которой сервер самостоятельно запрашивает статус валидности своего сертификата у центра сертификации и передает его клиенту в процессе TLS-рукопожатия.

* **[Механизмы отзыва сертификатов](../../../../Security/Concepts/pki_overview.md#механизмы-отзыва-сертификатов)** (теория).

## Базовые понятия

### Требования к окружению

Для поддержки современных стандартов (TLS 1.3, 0-RTT, современные наборы шифров) Nginx должен быть собран с **OpenSSL 1.1.1+**.

* Проверка версии: `nginx -V` (искать `built with OpenSSL`).

### Управление сессиями

#### Кэширование на стороне сервера (`ssl_session_cache`)

Основной механизм для TLS 1.2 и ниже. Создает разделяемую зону памяти между всеми рабочими процессами Nginx.

* `shared:SSL:10m` — 10 МБ памяти вмещают около 40 000 сессий.

#### Билеты сессий (`ssl_session_tickets`)

Механизм, при котором состояние сессии хранится у клиента в зашифрованном виде.

* **Рекомендация:** `off`. Использование билетов может ослабить **[Perfect Forward Secrecy (PFS)](../../../../Networking/Protocols/tls.md#perfect-forward-secrecy-pfs)** при компрометации ключа шифрования билетов.

### Протоколы и шифры

#### `ssl_protocols`

Определяет разрешенные версии протоколов.

* **Безопасный выбор:** `TLSv1.2 TLSv1.3`.
* Устаревшие протоколы (SSLv3, TLS 1.0, 1.1) запрещены из-за известных уязвимостей.

#### `ssl_ciphers`

Список алгоритмов шифрования для TLS 1.2. Для TLS 1.3 наборы шифров фиксированы и не настраиваются через эту директиву.

* Рекомендуется использовать наборы с поддержкой **[PFS](../../../../Networking/Protocols/tls.md#perfect-forward-secrecy-pfs)** (например, на базе ECDHE).
* Актуальные списки шифров предоставляет [Mozilla TLS Configurator](https://ssl-config.mozilla.org/).

#### `ssl_prefer_server_ciphers`

* `on`: сервер навязывает свой приоритет шифров.
* `off`: сервер учитывает предпочтения клиента (рекомендуется для современных систем, чтобы клиент мог выбрать наиболее производительный алгоритм, например, ChaCha20 на мобильных устройствах).

#### `ssl_conf_command`

Позволяет передавать произвольные конфигурационные команды библиотеке OpenSSL. Применяется для управления TLS 1.3, так как `ssl_ciphers` не влияет на этот протокол.

```nginx
# Управление наборами шифров для TLS 1.3
ssl_conf_command Ciphersuites TLS_AES_256_GCM_SHA384:TLS_AES_128_GCM_SHA256;

# Приоритизация ChaCha20 для мобильных клиентов
ssl_conf_command Options PrioritizeChaCha;
```

* **Совместимость:** поддерживается в OpenSSL, но **недоступна** в альтернативных библиотеках (AWS-LC, BoringSSL) и может привести к ошибке при запуске nginx.
* В OpenSSL 3.0+ также доступна через `SSL_CTX_set_ciphersuites()`.

### Оптимизация и безопасность

* **`ssl_buffer_size`**: размер буфера для передачи данных. Уменьшение до `4k` или `8k` может снизить задержку первого байта (TTFB) для динамического контента.
* **`ssl_dhparam`**: путь к параметрам Диффи-Хеллмана. Необходимо для поддержки DHE-шифров с ключом 2048+ бит. Не требуется для ECDHE и TLS 1.3.
* **`ssl_early_data`**: включает режим **[0-RTT](../../../../Networking/Protocols/tls.md#0-rtt-zero-round-trip-time)** для TLS 1.3. Ускоряет повторные соединения, но требует защиты от атак повторного воспроизведения (replay attacks) на уровне приложения.

* **`ssl_log_params`**: включает логирование согласованного набора шифров и параметров TLS в access-лог. Полезно для диагностики и верификации при тестировании производительности — позволяет убедиться, что клиент и сервер используют ожидаемый шифр.

  ```nginx
  log_format tls_test '$remote_addr [$time_local] "$request" $status'
                       'ssl_cipher:$ssl_cipher ssl_protocol:$ssl_protocol';
  server {
      access_log /var/log/nginx/tls_test.log tls_test;
      ssl_log_params on;
  }
  ```

  > Важно: в продуктивной среде рекомендуется отключать для снижения нагрузки на диск и экономии места.

## Практические сценарии

### Эталонная глобальная конфигурация (nginx.conf)

```nginx
http {
    # Keep-Alive оптимизация
    keepalive_timeout 65;
    keepalive_requests 1000;

    # Управление сессиями
    ssl_session_timeout 1d;
    ssl_session_cache shared:SSL:10m;
    ssl_session_tickets off;

    # Протоколы и шифры
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers 'ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305:DHE-RSA-AES128-GCM-SHA256:DHE-RSA-AES256-GCM-SHA384';
    ssl_prefer_server_ciphers off;

    # Оптимизация TTFB
    ssl_buffer_size 4k;

    # OCSP Stapling
    ssl_stapling on;
    ssl_stapling_verify on;
    # Системный или публичный DNS для проверки сертификатов
    resolver 8.8.8.8 8.8.4.4 valid=300s;
    resolver_timeout 5s;
}
```

### Генерация параметров Диффи-Хеллмана

Если ваша конфигурация должна поддерживать старые клиенты через DHE-шифры:

```bash
openssl dhparam -out /etc/nginx/ssl/dhparam.pem 2048
```

Затем добавьте в `http`:

```nginx
ssl_dhparam /etc/nginx/ssl/dhparam.pem;
```

## Дополнительная информация

### См. также

* [Обзор TLS/SSL в Nginx](./nginx_tls_ssl_overview.md)
* [Конфигурация виртуальных хостов TLS](./nginx_tls_virtual_host_config.md)
* [Оптимизация TLS для производительности](../../../Concepts/web_performance/tls_optimization.md)
* [Протокол TLS (теория)](../../../../Networking/Protocols/tls.md)
* [Mozilla TLS Configurator](https://ssl-config.mozilla.org/) — генератор конфигураций

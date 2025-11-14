# Аутентификация по клиентским SSL-сертификатам в Nginx (mTLS)

Аутентификация по клиентским сертификатам (также известная как Mutual TLS или mTLS) — это мощный механизм безопасности, при котором не только клиент проверяет сертификат сервера, но и сервер проверяет сертификат клиента. Это гарантирует, что к вашему сервису могут подключаться только доверенные клиенты, имеющие действительный сертификат, выданный вашим центром сертификации (CA).

Это руководство предполагает, что у вас уже есть:
1.  Созданный [центр сертификации (CA)](../../Security/Tools/openssl_ca_management.md).
2.  Сертификат для вашего сервера (например, `server.crt`), подписанный вашим CA.
3.  Сертификат для клиента (например, `client.crt`), подписанный вашим CA.

## 1. Базовая конфигурация SSL в Nginx

Сначала настроим стандартный HTTPS-сервер.

```nginx
server {
    listen 443 ssl http2;
    server_name your.domain.com;

    # Пути к сертификату и ключу сервера
    ssl_certificate /path/to/your/server.crt;
    ssl_certificate_key /path/to/your/server.key;

    # Базовые настройки SSL для безопасности
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers 'TLS_AES_128_GCM_SHA256:TLS_AES_256_GCM_SHA384:ECDHE-RSA-AES128-GCM-SHA256';
    ssl_prefer_server_ciphers on;

    root /var/www/html;
    index index.html;

    location / {
        try_files $uri $uri/ =404;
    }
}
```

## 2. Включение проверки клиентских сертификатов

Теперь добавим директивы для включения mTLS.

1.  `ssl_client_certificate`: Указывает путь к корневому сертификату вашего CA. Nginx будет использовать его для проверки подписи клиентских сертификатов.
2.  `ssl_verify_client`: Включает проверку.
    *   `on`: Проверка обязательна. Если клиент не предоставляет валидный сертификат, соединение разрывается (ошибка `400 Bad Request`).
    *   `optional`: Проверка не обязательна. Сервер запрашивает сертификат, но не разрывает соединение, если он не предоставлен. Статус проверки доступен в переменной `$ssl_client_verify`. Это полезно, если вы хотите разрешать доступ, но по-разному обрабатывать аутентифицированных и анонимных пользователей.
    *   `off`: (По умолчанию) Сертификат не запрашивается.

Добавим эти директивы в блок `server`:

```nginx
server {
    listen 443 ssl http2;
    server_name your.domain.com;

    ssl_certificate /path/to/your/server.crt;
    ssl_certificate_key /path/to/your/server.key;

    # --- НАСТРОЙКИ mTLS ---
    # 1. Указываем корневой сертификат для проверки клиентов
    ssl_client_certificate /path/to/your/ca.crt;

    # 2. Включаем обязательную проверку
    ssl_verify_client on;
    # ----------------------

    # ... остальные настройки
}
```

После внесения изменений перезагрузите конфигурацию Nginx: `sudo nginx -s reload`.

## 3. Тестирование с помощью `curl`

`curl` — отличный инструмент для проверки mTLS.

*   **Попытка подключения без сертификата (ожидается ошибка):**

```bash
curl https://your.domain.com
```
Nginx вернет ошибку, так как сертификат не был предоставлен. В логах Nginx вы увидите сообщение `no required SSL certificate was sent`.

*   **Успешное подключение с валидным сертификатом:**

```bash
curl https://your.domain.com \
  --cert /path/to/client.crt \
  --key /path/to/client.key \
  --cacert /path/to/ca.crt
```
*   `--cert`: Путь к сертификату клиента.
*   `--key`: Путь к приватному ключу клиента.
*   `--cacert`: (Опционально, но рекомендуется) Путь к корневому сертификату CA для проверки сервера.

Эта команда должна выполниться успешно.

## 4. Использование списка отозванных сертификатов (CRL)

Если вы отозвали сертификат клиента, Nginx по умолчанию не узнает об этом. Чтобы Nginx отвергал клиентов с отозванными сертификатами, необходимо указать путь к файлу Certificate Revocation List (CRL).

1.  Сгенерируйте CRL в вашем CA (см. [руководство по OpenSSL](../../Security/Tools/openssl_ca_management.md)).
2.  Добавьте директиву `ssl_crl` в конфигурацию Nginx:

```nginx
server {
    # ...
    ssl_client_certificate /path/to/your/ca.crt;
    ssl_verify_client on;

    # Путь к списку отозванных сертификатов
    ssl_crl /path/to/your/crl.pem;
    # ...
}
```

3.  Перезагрузите конфигурацию Nginx.

Теперь, если клиент попытается подключиться с сертификатом, который находится в `crl.pem`, Nginx разорвет соединение. `curl` вернет ошибку, например, `curl: (35) error:14094418:SSL routines:ssl3_read_bytes:tlsv1 alert unknown ca`.

## 5. Передача данных о сертификате клиента в бэкенд

Nginx предоставляет информацию из сертификата клиента бэкенд-сервисам через переменные. Это позволяет реализовать логику авторизации на уровне приложения.

Основные переменные:
*   `$ssl_client_verify`: Статус проверки (`SUCCESS`, `FAILED:reason`, `NONE`).
*   `$ssl_client_s_dn`: Полное `distinguished name` (DN) субъекта сертификата (например, `/C=RU/O=MyOrg/CN=client1`).
*   `$ssl_client_s_dn_cn`: Common Name (CN) из DN субъекта.
*   `$ssl_client_serial`: Серийный номер сертификата.

Пример передачи данных в FastCGI/proxy:

```nginx
location / {
    proxy_pass http://my_backend;
    proxy_set_header X-Client-Verify $ssl_client_verify;
    proxy_set_header X-Client-DN $ssl_client_s_dn;
    proxy_set_header X-Client-CN $ssl_client_s_dn_cn;
}
```

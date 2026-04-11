# Аутентификация клиентов в Angie с помощью TLS-сертификатов (mTLS)

## Определения

**Взаимная аутентификация TLS (Mutual TLS, mTLS)** — это механизм безопасности, при котором не только клиент проверяет подлинность сервера с помощью его TLS-сертификата, но и сервер, в свою очередь, проверяет подлинность клиента по его сертификату.

## Основные концепции

mTLS обеспечивает значительно более высокий уровень безопасности по сравнению с традиционными методами (логин/пароль), так как доступ могут получить только клиенты, обладающие валидным сертификатом, выданным доверенным центром сертификации (Certificate Authority, CA). Этот подход является стандартным для организации безопасного межсервисного взаимодействия в [микросервисных архитектурах](../../Concepts/monolith_vs_microservices.md) и для защиты критически важных внутренних API.

### Предварительные требования

Для настройки mTLS необходимы:

1. Созданный центр сертификации (CA) — корневой (Root CA) или промежуточный (Intermediate CA)
2. Сертификат для сервера Angie, подписанный вашим CA
3. Сертификат для клиента, подписанный вашим CA

### Ключевые директивы в Angie

**`ssl_client_certificate`** — указывает путь к файлу с доверенными сертификатами CA. Используется для проверки подлинности сертификата клиента. При двухуровневой архитектуре здесь указывается цепочка `промежуточный_сертификат + корневой_сертификат`.

**`ssl_crl`** — указывает путь к файлу со списком отозванных сертификатов (Certificate Revocation List, CRL). Angie будет отвергать клиентов с отозванными сертификатами.

**`ssl_verify_client`** — включает режим проверки сертификата клиента:

| Режим | Описание |
|:------|:---------|
| `off` | (По умолчанию) Сертификат не запрашивается |
| `on` | Проверка обязательна. Если клиент не предоставляет валидный сертификат (доверенный и не отозванный), соединение немедленно разрывается |
| `optional` | Сертификат запрашивается, но не является обязательным. Результат проверки доступен в переменной `$ssl_client_verify`, что позволяет реализовать разную логику в `location` |
| `optional_no_ca` | Запрашивать сертификат, но не проверять его по CA. Используется в редких случаях, когда проверка выполняется на уровне приложения |

**`ssl_verify_depth`** — глубина проверки цепочки сертификата клиента. Значение по умолчанию: 1. Для Intermediate CA требуется минимум 2.

### Переменные данных клиентского сертификата

Angie предоставляет информацию из сертификата клиента через переменные, доступные в конфигурации:

| Переменная | Описание |
|:-----------|:---------|
| `$ssl_client_verify` | Статус проверки (`SUCCESS`, `FAILED:reason`, `NONE`) |
| `$ssl_client_s_dn` | Полное `distinguished name` (DN) субъекта сертификата (например, `/C=RU/O=MyOrg/CN=client1`) |
| `$ssl_client_s_dn_cn` | Common Name (CN) из DN субъекта |
| `$ssl_client_serial` | Серийный номер сертификата |

## Практический сценарий: Настройка с Easy-RSA

В данном руководстве мы рассмотрим сквозной практический пример настройки mTLS в [Angie](./angie_overview.md) с использованием утилиты **Easy-RSA** для создания необходимой инфраструктуры открытых ключей (Public Key Infrastructure, PKI).

### Шаг 1: Установка и инициализация Easy-RSA

Easy-RSA — это утилита командной строки для управления PKI, являющаяся удобной оберткой над OpenSSL.

1. **Установка:**

    ```bash
    sudo apt update
    sudo apt install easy-rsa
    ```

2. **Инициализация PKI:**

    ```bash
    mkdir ~/easy-rsa-ca
    cd ~/easy-rsa-ca
    ln -s /usr/share/easy-rsa/* .

    # Инициализируем PKI
    ./easyrsa init-pki
    ```

    Это создаст структуру каталогов `pki/` для хранения ключей и сертификатов.

### Шаг 2: Создание Центра Сертификации (CA)

Создадим корневой ключ и сертификат для нашего CA.

```bash
# Создаем CA без пароля для ключа (для автоматизации)
./easyrsa build-ca nopass
```

Вам будет предложено ввести `Common Name` (CN) для вашего CA.

### Шаг 3: Генерация сертификатов для сервера и клиента

1. **Сертификат сервера Angie:**

    ```bash
    ./easyrsa build-server-full server nopass
    ```

    Система запросит подтверждение `Common Name` (по умолчанию `server`). На этом этапе вы можете указать реальный домен вашего сервера.

2. **Сертификат клиента:**

    ```bash
    ./easyrsa build-client-full client nopass
    ```

3. **Список отозванных сертификатов (CRL):**

    ```bash
    ./easyrsa gen-crl
    ```

После этого в директории `pki/` будут созданы все необходимые файлы (`ca.crt`, `server.crt`, `server.key`, `client.crt`, `client.key`, `crl.pem`).

### Шаг 4: Настройка Angie

1. **Скопируйте файлы на сервер с Angie:**

    ```bash
    sudo mkdir -p /etc/angie/ssl
    sudo cp pki/ca.crt /etc/angie/ssl/
    sudo cp pki/issued/server.crt /etc/angie/ssl/
    sudo cp pki/private/server.key /etc/angie/ssl/
    sudo cp pki/crl.pem /etc/angie/ssl/
    ```

2. **Настройте виртуальный хост в Angie:**

    ```nginx
    server {
        listen 443 ssl http2;
        server_name your.domain.com;

        # --- Базовые настройки TLS ---
        ssl_certificate /etc/angie/ssl/server.crt;
        ssl_certificate_key /etc/angie/ssl/server.key;

        # --- НАСТРОЙКИ mTLS ---
        ssl_client_certificate /etc/angie/ssl/ca.crt;    # 1. Сертификат CA для проверки
        ssl_crl /etc/angie/ssl/crl.pem;                   # 2. Список отозванных сертификатов
        ssl_verify_client on;                             # 3. Включаем обязательную проверку

        # Для отладки можно добавить переменные в заголовки
        add_header X-SSL-Client-Verify $ssl_client_verify;
        add_header X-SSL-Client-DN $ssl_client_s_dn;

        root /var/www/html;
        location / {
            try_files $uri $uri/ =404;
        }
    }
    ```

3. **Проверьте и перезагрузите Angie:**

    ```bash
    sudo angie -t
    sudo systemctl reload angie
    ```

### Шаг 5: Тестирование и использование

#### Тестирование с `curl`

- **Без сертификата (ошибка):**

    ```bash
    curl https://your.domain.com --insecure
    # Ошибка: ... sslv3 alert bad certificate
    # В логах Angie: "client SSL certificate required"
    ```

- **С сертификатом (успех):**

    ```bash
    curl https://your.domain.com --insecure \
      --cert client.crt \
      --key client.key
    ```

    `--insecure` используется, так как наш CA является самоподписанным.

#### Использование в браузере

1. **Конвертируйте сертификат в формат `.p12`:**

    ```bash
    openssl pkcs12 -export -out client.p12 -inkey pki/private/client.key -in pki/issued/client.crt -certfile pki/ca.crt
    ```

2. **Импортируйте `client.p12` в ваш браузер** (например, через `Настройки` → `Безопасность` → `Управление сертификатами`).
3. **Добавьте `ca.crt`** в доверенные корневые сертификаты вашей ОС или браузера, чтобы избежать предупреждений безопасности.

### Сценарий: Конфигурация с промежуточным CA (production)

В production-среке корневой CA не используется для прямой подписи сертификатов. Вместо этого создаётся промежуточный CA (Intermediate CA), который подписывает серверные и клиентские сертификаты.

1. **Подготовьте файл с полной цепочкой серверного сертификата:**

    ```bash
    cat server.crt intermediate-ca/ca-chain.crt > server.fullchain.crt
    ```

2. **Конфигурация Angie:**

    ```nginx
    server {
        listen 443 ssl http2;
        server_name your.domain.com;

        # Сертификат сервера с полной цепочкой
        ssl_certificate /etc/angie/ssl/server.fullchain.crt;
        ssl_certificate_key /etc/angie/ssl/server.key;

        # --- mTLS ---
        ssl_client_certificate /etc/angie/ssl/ca-chain.crt;  # Цепочка доверенных CA
        ssl_crl /etc/angie/ssl/crl.pem;                       # Список отозванных
        ssl_verify_client on;
        ssl_verify_depth 2;                                   # Для Intermediate CA

        # Передача данных клиентского сертификата в бэкенд
        location / {
            proxy_pass http://backend;
            proxy_set_header X-Client-Verify $ssl_client_verify;
            proxy_set_header X-Client-DN $ssl_client_s_dn;
            proxy_set_header X-Client-CN $ssl_client_s_dn_cn;
            proxy_set_header X-Client-Serial $ssl_client_serial;
        }
    }
    ```

Параметр `ssl_verify_depth 2` необходим, так как Angie должна проверить цепочку: `client.crt → intermediate-ca.crt → root-ca.crt`.

## Дополнительная информация

### См. также

- [Оптимальная настройка TLS/SSL в Nginx](../Nginx/Security/TLS_SSL/nginx_tls_ssl_overview.md) — теория TLS, продвинутные сценарии настройки
- [Настройка mTLS в Nginx](../Nginx/Security/TLS_SSL/nginx_mtls_configuration.md) — аналогичное руководство для Nginx
- [PKI Overview](../../Security/Concepts/pki_overview.md) — теория инфраструктуры открытых ключей

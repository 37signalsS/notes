# Создание защищённого APT-репозитория с Nginx и mTLS

## 1. Определения

**Защищённый APT-репозиторий** — хранилище пакетов Debian/Ubuntu, доступ к которому ограничен на уровне сетевого протокола и разрешён только аутентифицированным клиентам.

**mTLS (Mutual TLS)** — механизм взаимной проверки подлинности, при котором и сервер, и клиент предъявляют SSL/TLS-сертификаты. Подробнее: **[Настройка mTLS в Nginx](../Security/TLS_SSL/nginx_mtls_configuration.md)**.

**reprepro** — инструмент для создания и управления локальными репозиториями пакетов `.deb`. Он автоматически формирует структуру каталогов и файлы метаданных (`Packages`, `Sources`, `Release`).

**Инфраструктура открытых ключей (PKI — Public Key Infrastructure)** — система управления цифровыми сертификатами, включающая центр сертификации (CA), ключи и процедуры выпуска/отзыва.

## 2. Базовые концепции

Сценарий объединяет управление пакетами и сетевую безопасность для создания доверенной среды распространения ПО:

1. **Доверие (PKI):** настраивается собственный CA (Certificate Authority), выпускающий сертификаты для сервера и каждого авторизованного клиента.
2. **Хранение (reprepro):** формируется структура репозитория, пакеты подписываются GPG-ключом (GNU Privacy Guard) для проверки целостности на стороне клиента.
3. **Публикация (Nginx):** веб-сервер раздаёт файлы репозитория. Доступ к основному содержимому закрыт через `ssl_verify_client on`.
4. **Аутентификация (Client):** клиентская утилита `apt` настраивается на использование персонального сертификата для подключения к защищённому HTTPS-эндпоинту.

## 3. Практический сценарий

### 3.1. Создание центра сертификации (CA)

Для работы mTLS необходим собственный CA, так как публичные центры (например, Let's Encrypt) не выпускают клиентские сертификаты для произвольных нужд аутентификации.

Необходимо подготовить:

* Корневой сертификат CA (`ca.crt`).
* Сертификат и ключ сервера (`server.crt`, `server.key`).
* Сертификат и ключ клиента (`client.crt`, `client.key`).

> **Подробное руководство:** **[Управление собственным CA с помощью OpenSSL](../../../Security/Tools/openssl_ca/single_tier/overview.md)**.

### 3.2. Настройка приватного APT-репозитория

Репозиторий создаётся с помощью `reprepro`. Важно подписать репозиторий GPG-ключом, чтобы `apt` не выдавал предупреждений о небезопасном источнике.

1. Инициализируйте структуру `reprepro`.
2. Добавьте пакеты в репозиторий.

> **Подробные руководства:**
>
> * **[Источники пакетов и репозитории в deb-система](../../../Linux/PackageManagement/deb_repositories_sources_list.md)**.
> * **[Создание простого .deb пакета](../../../Linux/PackageManagement/package_build/definitions.md)**.

### 3.3. Конфигурация Nginx

Nginx настраивается на работу в двух режимах:

1. **HTTP (порт 80):** открытая раздача публичного GPG-ключа (не требует защиты, так как ключ сам является инструментом проверки).
2. **HTTPS (порт 443):** защищённая раздача пакетов с проверкой клиентского сертификата.

```nginx
# Сервер для раздачи GPG-ключа и редиректа
server {
    listen 80;
    server_name repo.example.com;

    root /var/www/my-repo;

    # Публичный доступ только к ключу
    location /repo.key {
        try_files $uri =404;
    }

    # Остальное — на HTTPS
    location / {
        return 301 https://$host$request_uri;
    }
}

# Защищённый HTTPS-сервер с mTLS
server {
    listen 443 ssl http2;
    server_name repo.example.com;

    root /var/www/my-repo;

    # Сертификаты сервера
    ssl_certificate     /etc/nginx/ssl/server.crt;
    ssl_certificate_key /etc/nginx/ssl/server.key;

    # Настройка mTLS
    ssl_client_certificate /etc/nginx/ssl/ca.crt; # Доверенный CA
    ssl_verify_client      on;                  # Обязательная проверка
    ssl_crl                /etc/nginx/ssl/crl.pem; # Список отзыва

    location / {
        autoindex on;
        
        # Защита внутренних директорий reprepro
        location ~ /(db|conf)/ {
            deny all;
            return 404;
        }
    }
}
```

### 3.4. Настройка apt-клиента

На стороне клиента необходимо выполнить три действия: импортировать GPG-ключ, добавить CA в системное хранилище и настроить аутентификацию для `apt`.

#### Шаг 1: Добавление источника и GPG-ключа

```bash
# Импорт GPG-ключа (через открытый HTTP)
curl -fsSL http://repo.example.com/repo.key | sudo gpg --dearmor -o /etc/apt/keyrings/my-repo.gpg

# Добавление репозитория
echo "deb [signed-by=/etc/apt/keyrings/my-repo.gpg] https://repo.example.com focal main" | \
    sudo tee /etc/apt/sources.list.d/my-repo.list
```

#### Шаг 2: Доверие к собственному CA

Чтобы клиент доверял сертификату сервера, подписанному вашим CA:

```bash
sudo cp ca.crt /usr/local/share/ca-certificates/my-ca.crt
sudo update-ca-certificates
```

#### Шаг 3: Настройка клиентского сертификата

Создайте файл `/etc/apt/apt.conf.d/99-my-repo-auth` для передачи сертификата при HTTPS-запросах:

```conf
Acquire::https::repo.example.com {
    SslCert "/etc/apt/ssl/client.crt";
    SslKey  "/etc/apt/ssl/client.key";
};
```

> **Важно:** права на `client.key` должны быть ограничены (`chmod 600`), а сам файл должен принадлежать `root`.

#### Шаг 4: Проверка

```bash
sudo apt update
# → Hit:1 https://repo.example.com focal InRelease
```

## 4. Дополнительная информация

### Управление приоритетами (Pinning)

Если пакеты в вашем репозитории имеют те же имена, что и в официальных зеркалах, используйте `Apt Pinning`, чтобы приоритезировать ваши версии.

> **Подробное руководство:** **[Управление приоритетами пакетов в apt (Pinning)](../../../Linux/PackageManagement/deb_apt_pinning.md)**.

### См. также

* **[Настройка mTLS в Nginx](../Security/TLS_SSL/nginx_mtls_configuration.md)**
* **[Обзор TLS/SSL в Nginx](../Security/TLS_SSL/nginx_tls_ssl_overview.md)**
* **[Безопасность Nginx](../Security/nginx_security_guide.md)**

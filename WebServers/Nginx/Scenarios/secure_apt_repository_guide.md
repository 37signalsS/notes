# Создание защищённого APT-репозитория с Nginx и mTLS

## 1. Определения

**Защищённый APT-репозиторий** — хранилище пакетов Debian/Ubuntu, доступ к которому ограничен на уровне сетевого протокола и разрешён только аутентифицированным клиентам.

**mTLS (Mutual TLS)** — механизм взаимной проверки подлинности, при котором и сервер, и клиент предъявляют SSL/TLS-сертификаты. Подробнее: **[Настройка mTLS в Nginx](../Security/TLS_SSL/nginx_mtls_configuration.md)**.

**reprepro** — специализированный инструмент для создания и управления локальными репозиториями пакетов `.deb`. Он автоматически формирует структуру каталогов и файлы метаданных (`Packages`, `Sources`, `Release`).

**Инфраструктура открытых ключей (PKI — Public Key Infrastructure)** — система управления цифровыми сертификатами, включающая центр сертификации (CA), ключи и процедуры выпуска/отзыва.

## 2. Базовые концепции

Сценарий объединяет управление пакетами и сетевую безопасность для создания доверенной среды распространения ПО:

1.  **Доверие (PKI):** настраивается собственный CA (Certificate Authority), выпускающий сертификаты для сервера и каждого авторизованного клиента.
2.  **Хранение (reprepro):** формируется структура репозитория, пакеты подписываются GPG-ключом (GNU Privacy Guard) для проверки целостности на стороне клиента.
3.  **Публикация (Nginx):** веб-сервер раздаёт файлы репозитория. Доступ к основному содержимому закрыт через `ssl_verify_client on`.
4.  **Аутентификация (Client):** клиентская утилита `apt` настраивается на использование персонального сертификата для подключения к защищённому HTTPS-эндпоинту.

## 3. Практический сценарий

### 3.1. Создание центра сертификации (CA)

Для работы mTLS необходим собственный CA, так как публичные центры (например, Let's Encrypt) не выпускают клиентские сертификаты для произвольных нужд аутентификации.

Необходимо подготовить:
*   Корневой сертификат CA (`ca.crt`).
*   Сертификат и ключ сервера (`server.crt`, `server.key`).
*   Сертификат и ключ клиента (`client.crt`, `client.key`).

> **Подробное руководство:** **[Управление собственным CA с помощью OpenSSL](../../../Security/Tools/openssl_ca/single_tier/overview.md)**.

### 3.2. Настройка приватного APT-репозитория

Репозиторий создаётся с помощью `reprepro`. Важно подписать репозиторий GPG-ключом, чтобы `apt` не выдавал предупреждений о небезопасном источнике.

1.  Установите `reprepro` и `gnupg`.
2.  Создайте структуру директорий и файл `conf/distributions`.
3.  Сгенерируйте GPG-ключ и укажите его идентификатор в `SignWith`.

> **Подробное руководство по reprepro:** **[Приватный APT-репозиторий: Практические сценарии](../../../Linux/PackageManagement/deb_private_apt_repository_reprepro/practical_scenarios.md)**.

### 3.3. Конфигурация Nginx

Nginx 1.27+ настраивается на работу в двух режимах: открытая раздача ключа и защищённая раздача пакетов.

```nginx
# Сервер для раздачи GPG-ключа и редиректа
server {
    listen 80;
    listen [::]:80;
    server_name repo.example.com;

    root /var/www/my-repo;

    # Публичный доступ только к GPG-ключу (для первичной настройки клиента)
    location /public.gpg {
        try_files $uri =404;
    }

    # Остальное — принудительный редирект на HTTPS
    location / {
        return 301 https://$host$request_uri;
    }
}

# Защищённый HTTPS-сервер с mTLS
server {
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name repo.example.com;

    # Включение HTTP/2 (актуально для Nginx 1.27+)
    http2 on;

    root /var/www/my-repo;

    # Сертификаты сервера
    ssl_certificate     /etc/nginx/ssl/server.crt;
    ssl_certificate_key /etc/nginx/ssl/server.key;

    # Настройка безопасности TLS
    ssl_protocols TLSv1.3;
    ssl_prefer_server_ciphers off;
    
    # HSTS (Strict Transport Security)
    add_header Strict-Transport-Security "max-age=63072000" always;

    # Конфигурация mTLS
    ssl_client_certificate /etc/nginx/ssl/ca.crt; # Доверенный CA для клиентов
    ssl_verify_client      on;                  # Обязательная проверка сертификата
    ssl_crl                /etc/nginx/ssl/crl.pem; # Список отзыва (опционально)

    location / {
        autoindex on;
        
        # Запрет доступа к служебным директориям reprepro
        location ~ ^/(conf|db) {
            deny all;
            return 404;
        }
    }
}
```

### 3.4. Настройка APT-клиента

На стороне клиента необходимо импортировать GPG-ключ, настроить доверие к CA и добавить сертификат аутентификации.

#### Шаг 1: Добавление GPG-ключа и источника

Современный стандарт APT требует использования директории `keyrings` и опции `signed-by`.

```bash
# Импорт GPG-ключа через открытый HTTP (или HTTPS, если CA уже в системе)
curl -fsSL http://repo.example.com/public.gpg | sudo gpg --dearmor -o /etc/apt/keyrings/my-repo.gpg

# Добавление репозитория
echo "deb [signed-by=/etc/apt/keyrings/my-repo.gpg] https://repo.example.com jammy main" | \
    sudo tee /etc/apt/sources.list.d/my-repo.list
```

#### Шаг 2: Доверие к собственному CA

Если сертификат сервера подписан вашим приватным CA, клиент должен ему доверять:

```bash
sudo cp ca.crt /usr/local/share/ca-certificates/my-ca.crt
sudo update-ca-certificates
```

#### Шаг 3: Настройка клиентского сертификата для mTLS

Создайте файл конфигурации для `apt` в `/etc/apt/apt.conf.d/99-my-repo-auth`. Это позволит `apt` автоматически предъявлять сертификат при обращении к домену репозитория.

```conf
Acquire::https::repo.example.com {
    SslCert "/etc/apt/ssl/client.crt";
    SslKey  "/etc/apt/ssl/client.key";
};
```

**Важно:** права на файл `client.key` должны быть максимально ограничены (`chmod 600`), а владельцем должен быть `root`.

#### Шаг 4: Проверка

```bash
sudo apt update
# → Hit:1 https://repo.example.com jammy InRelease
```

Если сертификат неверный или отсутствует, сервер вернёт ошибку `400 Bad Request (No required SSL certificate was sent)`.

## 4. Дополнительная информация

### Управление приоритетами (Pinning)

Если пакеты в вашем репозитории перекрывают версии из официальных зеркал, используйте `Apt Pinning` для принудительного выбора ваших сборок.

> **Подробное руководство:** **[Управление приоритетами пакетов в apt (Pinning)](../../../Linux/PackageManagement/deb_apt_pinning.md)**.

### См. также

*   **[Настройка mTLS в Nginx](../Security/TLS_SSL/nginx_mtls_configuration.md)**
*   **[Обзор TLS/SSL в Nginx](../Security/TLS_SSL/nginx_tls_ssl_overview.md)**
*   **[Безопасность Nginx](../Security/nginx_security_guide.md)**
*   **[Приватный APT-репозиторий: Практические сценарии](../../../Linux/PackageManagement/deb_private_apt_repository_reprepro/practical_scenarios.md)**

---
**Достоверность:** 10 (Внутренняя верификация + Практические тесты) | **Актуальность:** Nginx 1.27, Ubuntu 24.04 (Noble)

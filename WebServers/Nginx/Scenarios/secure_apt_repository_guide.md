# Создание защищённого APT-репозитория с Nginx и mTLS

## 1. Определения

**Защищённый APT-репозиторий** — хранилище пакетов Debian/Ubuntu, доступ к которому ограничен на транспортном уровне (L4/L7) и разрешён только аутентифицированным клиентам с валидными сертификатами.

**mTLS (Mutual TLS)** — механизм взаимной проверки подлинности, при котором и сервер, и клиент предъявляют SSL/TLS-сертификаты. Это исключает несанкционированный доступ даже при знании URL-адреса репозитория. Подробнее: **[Настройка mTLS в Nginx](../Security/TLS_SSL/nginx_mtls_configuration.md)**.

**reprepro** — специализированный инструмент командной строки для управления локальными репозиториями пакетов `.deb`. Он генерирует статическую структуру индексов (`Packages`, `Sources`, `Release`), что позволяет использовать любой веб-сервер для раздачи.

**GPG-подпись (GNU Privacy Guard)** — механизм обеспечения целостности и подлинности пакетов. В отличие от mTLS (защищающего доступ), GPG гарантирует, что содержимое репозитория не было изменено третьей стороной.

## 2. Базовые концепции

Сценарий реализует эшелонированную защиту («Defense in Depth») для распространения внутреннего ПО:

1.  **Сетевой уровень (mTLS):** Nginx блокирует любые запросы без клиентского сертификата, подписанного доверенным CA (Certificate Authority).
2.  **Уровень аутентификации:** Проверка серийного номера или Common Name (CN) сертификата клиента (опционально через `$ssl_client_s_dn`).
3.  **Уровень целостности (GPG):** Клиент `apt` проверяет подпись файла `Release`, подтверждая, что пакеты получены от доверенного владельца репозитория.
4.  **Уровень изоляции:** Использование `reprepro` для разделения кодовых имен (codenames) и архитектур (`amd64`, `arm64`), а также блокировка доступа к служебным БД (`dbs/`) и конфигурациям (`conf/`).

## 3. Практический сценарий

### 3.1. Подготовка инфраструктуры PKI

Для mTLS требуется собственный центр сертификации. Использование публичных CA (Let's Encrypt) для аутентификации клиентов не рекомендуется из-за сложности контроля выпуска.

**Необходимые компоненты:**
- `ca.crt`: Корневой сертификат вашего CA.
- `server.crt / server.key`: Сертификат сервера репозитория.
- `client.crt / client.key`: Индивидуальные ключи для каждой клиентской машины или группы.

> **Инструкции по созданию:** **[Двухуровневый CA на OpenSSL](../../../../Security/Tools/openssl_ca/two_tier/overview.md)**.

### 3.2. Настройка репозитория (reprepro)

Репозиторий должен поддерживать актуальные архитектуры и быть подписан GPG-ключом.

1.  **Установка**: `sudo apt update && sudo apt install -y reprepro gnupg`.
2.  **Генерация ключа**: Используйте неинтерактивный режим для CI/CD.
    ```bash
    # См. Сценарий 1 в:
    # [Приватный Apt-репозиторий: Практические сценарии](../../../Linux/PackageManagement/deb_private_apt_repository_reprepro/practical_scenarios.md)
    ```
3.  **Конфигурация `conf/distributions`**:
    ```text
    Origin: InternalRepo
    Label: Private Packages
    Codename: noble
    Architectures: amd64 arm64 source
    Components: main
    Description: Защищенный репозиторий для Ubuntu 24.04
    SignWith: <ID_ВАШЕГО_GPG_КЛЮЧА>
    ```

### 3.3. Конфигурация Nginx (1.27+)

Настройка разделяет публичную зону (для GPG-ключа) и защищённую зону (для пакетов).

```nginx
# Переменная для логирования идентификатора клиента
log_format mtls_repo '$remote_addr - $ssl_client_s_dn_cn [$time_local] '
                     '"$request" $status $body_bytes_sent';

server {
    listen 80;
    listen [::]:80;
    server_name repo.example.com;

    root /var/www/apt-repo;

    # Публичный доступ только к открытому GPG-ключу
    location = /public.gpg {
        try_files $uri =404;
    }

    # Все остальные запросы принудительно на HTTPS
    location / {
        return 301 https://$host$request_uri;
    }
}

server {
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name repo.example.com;

    http2 on; # Стандарт для Nginx 1.27+
    root /var/www/apt-repo;
    access_log /var/log/nginx/repo_access.log mtls_repo;

    # TLS Сертификаты сервера
    ssl_certificate     /etc/nginx/ssl/server.crt;
    ssl_certificate_key /etc/nginx/ssl/server.key;

    # Настройки mTLS
    ssl_client_certificate /etc/nginx/ssl/ca.crt;
    ssl_verify_client      on;
    ssl_verify_depth       2;
    
    # Список отзыва (CRL) — критично для блокировки утерянных ключей
    ssl_crl                /etc/nginx/ssl/crl.pem;

    # Оптимизация безопасности
    ssl_protocols TLSv1.3;
    ssl_prefer_server_ciphers off;
    add_header Strict-Transport-Security "max-age=63072000" always;

    location / {
        autoindex on; # Разрешить просмотр структуры (опционально)
        
        # Защита служебных директорий reprepro
        location ~ ^/(conf|db) {
            deny all;
            return 404;
        }
    }
}
```

### 3.4. Настройка клиента APT

Клиент должен доверять GPG-ключу и CA, а также предъявлять свой сертификат.

#### Шаг 1: Добавление GPG-ключа
Современный метод (без `apt-key`):
```bash
curl -fsSL http://repo.example.com/public.gpg | sudo gpg --dearmor -o /etc/apt/keyrings/internal-repo.gpg
```

#### Шаг 2: Настройка источника
```bash
echo "deb [signed-by=/etc/apt/keyrings/internal-repo.gpg] https://repo.example.com noble main" | \
    sudo tee /etc/apt/sources.list.d/internal-repo.list
```

#### Шаг 3: Настройка аутентификации (mTLS)
Создайте файл `/etc/apt/apt.conf.d/99internal-repo`:
```conf
Acquire::https::repo.example.com {
    SslCert "/etc/apt/ssl/client.crt";
    SslKey  "/etc/apt/ssl/client.key";
    CaInfo  "/etc/apt/ssl/ca.crt"; # Доверие к вашему CA
};
```
**Безопасность**: `sudo chmod 600 /etc/apt/ssl/client.key`.

## 4. Дополнительная информация

### Управление отзывом сертификатов (CRL)

Если клиентский сертификат скомпрометирован, его необходимо отозвать:
1.  Выпустите обновлённый `crl.pem` на вашем CA.
2.  Скопируйте его в `/etc/nginx/ssl/crl.pem`.
3.  Выполните `nginx -s reload`. Nginx начнёт выдавать `400 Bad Request` для отозванного сертификата.

### Диагностика (White spots)

- **Ошибка `400 Bad Request`**: APT не отправил сертификат. Проверьте путь в файле конфигурации `apt.conf.d`.
- **Ошибка `GnuTLS: A TLS fatal alert has been received`**: Обычно означает несоответствие версий TLS или отсутствие общего набора шифров. Убедитесь, что на сервере разрешён TLS 1.3.
- **Логирование**: В `access_log` с форматом `mtls_repo` (см. конфиг выше) будет отображаться CN клиента, что позволяет отслеживать, кто и когда скачивал пакеты.

### Автоматизация CI/CD

Для автоматического добавления пакетов в защищенный репозиторий используйте SSH-туннель или временное разрешение доступа по IP для сборочного сервера, так как `reprepro` требует локального доступа к файловой системе для выполнения команд.

### См. также

*   **[Настройка mTLS в Nginx](../Security/TLS_SSL/nginx_mtls_configuration.md)**
*   **[Приватный Apt-репозиторий: Практические сценарии](../../../Linux/PackageManagement/deb_private_apt_repository_reprepro/practical_scenarios.md)**
*   **[Управление приоритетами пакетов в apt (Pinning)](../../../Linux/PackageManagement/deb_apt_pinning.md)**
*   **[Двухуровневый CA на OpenSSL](../../../../Security/Tools/openssl_ca/two_tier/overview.md)**

# Автоматические TLS-сертификаты в Angie: модуль ACME

## Определения

**Модуль `acme` в Angie** — встроенное решение для автоматического получения и обновления [SSL/TLS-сертификатов](../../Networking/Protocols/tls.md) от центров сертификации (CA), использующих протокол ACME (например, Let's Encrypt). Модуль интегрирует управление сертификатами непосредственно в конфигурацию веб-сервера, исключая зависимость от внешних утилит (Certbot, acme.sh).

Общие понятия протокола ACME, принципы работы Let's Encrypt и типы сертификатов (включая Wildcard) описаны в основном руководстве:
> **[Let's Encrypt и Certbot: общие принципы и методы авторизации](../Concepts/https_with_certbot.md)**

## Базовые концепции

### Преимущества встроенного модуля ACME

* **Полная автоматизация:** Angie самостоятельно инициирует выпуск, продлевает сертификаты и применяет изменения без внешних скриптов.
* **Отсутствие внешних зависимостей:** Не требует установки и настройки Certbot, acme.sh или других клиентов.
* **Бесшовная перезагрузка:** Обновление сертификатов происходит в оперативной памяти, что исключает разрыв соединений при перезагрузке конфигурации.
* **Централизованное управление:** Настройки доменов и параметры SSL находятся в едином конфигурационном файле.

### Методы верификации (Challenges)

Angie поддерживает два основных метода подтверждения владения доменом:

1. **HTTP-01 Challenge:** Верификация через HTTP-запрос (порт 80). Рекомендуется для большинства стандартных сертификатов.
2. **DNS-01 Challenge:** Верификация через TXT-записи в DNS. Необходима для выпуска Wildcard-сертификатов (`*.example.com`).

#### Поддержка External Account Binding (EAB)
Angie поддерживает механизм EAB, необходимый для работы с такими удостоверяющими центрами, как **ZeroSSL** или **Google Trust Services**. Параметры EAB указываются непосредственно в директиве `acme_client`.

#### ACME в модуле Stream (L4)
Модуль ACME полностью поддерживается в блоке `stream`. Это позволяет автоматически получать TLS-сертификаты для проксирования TCP/UDP соединений (например, для баз данных или почтовых серверов).

### Ограничения и лимиты

* **Рейтлимитинг:** При использовании Let's Encrypt применяются стандартные ограничения. Подробнее: **[Рейтлимиты Let's Encrypt](../Concepts/https_with_certbot.md#рейтлимиты-lets-encrypt)**.
* **Изоляция клиентов:** Каждый `acme_client` жестко привязан к одному аккаунту и набору параметров.
* **Требование Resolver:** Для выполнения ACME-запросов и проверки DNS-записей в соответствующем контексте (`http` или `stream`) обязательно должна быть определена директива `resolver`.

## Практические сценарии

### Сценарий 1: Базовая настройка (HTTP-01)

Самый распространенный сценарий для одиночных доменов.

**1. Глобальная конфигурация (`http` блок):**

```nginx
http {
    # Резолвер обязателен для работы ACME-клиента
    resolver 1.1.1.1 8.8.8.8 valid=300s;
    resolver_timeout 5s;

    # Описание клиента Let's Encrypt
    acme_client letsencrypt {
        directory "https://acme-v02.api.letsencrypt.org/directory";
        # Для отладки используйте staging:
        # directory "https://acme-staging-v02.api.letsencrypt.org/directory";
    }
}
```

**2. Настройка виртуального хоста (`server` блок):**

```nginx
server {
    listen 80;
    server_name example.com www.example.com;

    # Angie автоматически обрабатывает запросы в /.well-known/acme-challenge/
    location / {
        return 301 https://$host$request_uri;
    }
}

server {
    listen 443 ssl;
    server_name example.com www.example.com;

    # Использование переменных модуля ACME для сертификатов
    acme letsencrypt;
    ssl_certificate $acme_cert_letsencrypt;
    ssl_certificate_key $acme_cert_key_letsencrypt;

    # Рекомендуемые параметры безопасности
    # [Оптимальная настройка TLS/SSL в Nginx](../Nginx/Security/TLS_SSL/nginx_tls_ssl_overview.md)
}
```

### Сценарий 3: Использование External Account Binding (EAB)

Необходимо для коммерческих CA (ZeroSSL, Google Trust Services). Требуется идентификатор ключа (KID) и HMAC-ключ.

```nginx
http {
    resolver 8.8.8.8;

    # Настройка клиента с EAB
    # Ключ должен быть в формате base64url
    acme_client zerossl {
        directory "https://acme.zerossl.com/v2/DV90";
        eab kid=YOUR_KID:key=YOUR_HMAC_KEY;
    }

    server {
        listen 443 ssl;
        server_name example.com;

        acme zerossl;
        ssl_certificate     $acme_cert_zerossl;
        ssl_certificate_key $acme_cert_key_zerossl;
    }
}
```

### Сценарий 4: ACME в модуле Stream (L4)

Пример автоматического получения сертификата для проксирования базы данных по TLS.

```nginx
stream {
    resolver 1.1.1.1;

    acme_client stream_le {
        directory "https://acme-v02.api.letsencrypt.org/directory";
    }

    server {
        listen 5432 ssl; # Порт PostgreSQL с TLS
        
        acme stream_le;
        ssl_certificate     $acme_cert_stream_le;
        ssl_certificate_key $acme_cert_key_stream_le;

        proxy_pass db_backend;
    }
}
```

## Дополнительная информация

### Диагностика и отладка

* **Логирование:** Статус получения и обновления сертификатов записывается в `error.log`. Для детального анализа рекомендуется уровень `notice`:
  `error_log /var/log/angie/error.log notice;`
* **Хранение данных:** По умолчанию сертификаты сохраняются в `/var/lib/angie/acme/<client_name>/`.
* **Обновление:** Angie автоматически проверяет необходимость обновления за 30 дней до истечения срока действия сертификата.

## См. также

* **[Настройка TLS в Angie](./angie_tls_setup.md)**
* **[Let's Encrypt и Certbot: общие принципы](../Concepts/https_with_certbot.md)**
* **[Обзор TLS/SSL в Nginx](../Nginx/Security/TLS_SSL/nginx_tls_ssl_overview.md)**

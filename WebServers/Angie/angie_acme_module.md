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

Подробное сравнение методов и их применимость: **[Методы авторизации ACME](../Concepts/https_with_certbot.md#методы-авторизации)**.

#### Особенности реализации DNS-01 в Angie

* **Встроенный DNS-сервер:** Angie может выступать в роли мини-DNS сервера на порту 53 (UDP/TCP) для ответа на проверочные запросы CA. Это требует делегирования поддомена `_acme-challenge` на IP-адрес сервера с Angie.
* **acme_dns_hook:** Позволяет вызывать внешние скрипты для взаимодействия с API DNS-провайдеров, если прямое делегирование невозможно.

### Ограничения и лимиты

* **Рейтлимитинг:** При использовании Let's Encrypt применяются стандартные ограничения (50 сертификатов на домен в неделю). Подробнее: **[Рейтлимиты Let's Encrypt](../Concepts/https_with_certbot.md#рейтлимиты-lets-encrypt)**.
* **Изоляция клиентов:** Каждый `acme_client` в Angie жестко привязан к одному сертификату. Для разных доменных имен (не входящих в один SAN-сертификат) требуется описание отдельных клиентов.
* **Отсутствие пост-обновляемых хуков:** Встроенный модуль не умеет выполнять команды после обновления сертификата (например, для уведомления других сервисов).

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

### Сценарий 2: Wildcard-сертификаты (DNS-01 через встроенный сервер)

Требует делегирования записи `_acme-challenge.example.com` на ваш сервер.

```nginx
http {
    resolver 1.1.1.1;

    acme_client letsencrypt_dns {
        directory "https://acme-v02.api.letsencrypt.org/directory";
        challenge_type dns-01;
    }

    server {
        listen 443 ssl;
        server_name *.example.com;

        acme letsencrypt_dns;
        ssl_certificate $acme_cert_letsencrypt_dns;
        ssl_certificate_key $acme_cert_key_letsencrypt_dns;

        # Активация DNS-сервера для верификации
        acme_dns_server {
            listen 53 udp;
            listen 53; # TCP
        }
    }
}
```

## Дополнительная информация

### Диагностика и отладка

* **Логирование:** Статус получения и обновления сертификатов записывается в `error.log`. Для детального анализа рекомендуется уровень `notice`:
  `error_log /var/log/angie/error.log notice;`
* **Хранение данных:** По умолчанию сертификаты сохраняются в `/var/lib/angie/acme/<client_name>/`.
* **Обновление:** Angie автоматически проверяет необходимость обновления за 30 дней до истечения срока действия сертификата.

### См. также

* **[Настройка TLS в Angie](./angie_tls_setup.md)** — особенности TLS-конфигурации Angie.
* **[Let's Encrypt и Certbot](../Concepts/https_with_certbot.md)** — универсальное руководство по ACME.
* **[Оптимальная настройка TLS/SSL в Nginx](../Nginx/Security/TLS_SSL/nginx_tls_ssl_overview.md)** — база для настройки безопасного HTTPS.

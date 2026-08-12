# Автоматические TLS-сертификаты в Angie: модуль ACME

## Определения

**Модуль `acme` в Angie** — встроенный полнофункциональный клиент для автоматизации жизненного цикла [SSL/TLS-сертификатов](../../Networking/Protocols/tls.md) по протоколу ACME (Automated Certificate Management Environment). 

В отличие от Nginx, где требуются внешние утилиты (Certbot, acme.sh), Angie интегрирует логику получения, проверки и обновления сертификатов непосредственно в ядро. Это позволяет управлять безопасностью соединений исключительно через конфигурационные файлы веб-сервера без развертывания дополнительного ПО.

Общие принципы работы Let's Encrypt, лимиты и типы проверок описаны в SSoT-руководстве:
> **[Let's Encrypt и Certbot: общие принципы и методы авторизации](../Concepts/https_with_certbot.md)**

## Базовые концепции

### Преимущества встроенного модуля

*   **Нативная интеграция:** Отсутствие зависимостей от Python (Certbot) или Bash-скриптов.
*   **Динамическое применение:** Сертификаты обновляются в памяти рабочих процессов без прерывания соединений и необходимости `reload`.
*   **Встроенный DNS-responder:** Для проверки DNS-01 (Wildcard) Angie сам может выступать в роли временного DNS-сервера.
*   **Поддержка Stream:** Автоматизация TLS доступна не только для HTTP, но и для TCP/UDP проксирования (блок `stream`).

### Параметры ACME-клиента

Настройка клиента выполняется в блоке `http` или `stream` через директиву `acme_client`. Основные параметры:

| Параметр | Описание | Значение по умолчанию |
| :--- | :--- | :--- |
| `directory` | URL ACME-сервера (Let's Encrypt, ZeroSSL и др.). | Обязателен |
| `challenge` | Метод верификации: `http` (HTTP-01) или `dns` (DNS-01). | `http` |
| `key_type` | Тип закрытого ключа: `rsa` или `ecdsa`. | `ecdsa` |
| `key_bits` | Размер ключа (RSA: 2048/4096, ECDSA: 256/384). | `256` (для ECDSA) |
| `renew` | Срок до истечения, при котором начинается обновление. | `30d` |

### Переменные модуля

После успешного получения сертификата становятся доступны следующие переменные (где `<name>` — имя клиента):
*   `$acme_cert_<name>` — путь к файлу сертификата (полная цепочка).
*   `$acme_cert_key_<name>` — путь к файлу закрытого ключа.
*   `$acme_cert_chain_<name>` — путь к файлу цепочки CA.

## Практические сценарии

### Сценарий 1: Стандартный сертификат (HTTP-01)

Рекомендуется для большинства сайтов. Требует открытого порта 80 для входящих запросов проверки.

```nginx
http {
    resolver 1.1.1.1 8.8.8.8 valid=300s;

    acme_client le_http {
        directory https://acme-v02.api.letsencrypt.org/directory;
        challenge http;
        key_type ecdsa;
    }

    server {
        listen 80;
        server_name example.com;

        # Angie автоматически перехватывает запросы в /.well-known/acme-challenge/
        location / {
            return 301 https://$host$request_uri;
        }
    }

    server {
        listen 443 ssl;
        server_name example.com;

        acme le_http;
        ssl_certificate     $acme_cert_le_http;
        ssl_certificate_key $acme_cert_key_le_http;

        # [Обзор TLS/SSL в Nginx/Angie](../Nginx/Security/TLS_SSL/nginx_tls_ssl_overview.md)
    }
}
```

### Сценарий 2: Wildcard-сертификат (DNS-01)

Позволяет защитить домен и все его поддомены (`*.example.com`). Требует делегирования поддомена `_acme-challenge` на IP-адрес сервера Angie.

**1. Настройка в DNS:**
Создайте NS-запись: `_acme-challenge.example.com. IN NS <IP_вашего_сервера>`

**2. Конфигурация Angie:**
```nginx
http {
    resolver 1.1.1.1;
    
    # Порт для приема DNS-запросов от CA (Let's Encrypt)
    acme_dns_port 53;

    acme_client le_wildcard {
        directory https://acme-v02.api.letsencrypt.org/directory;
        challenge dns;
    }

    server {
        listen 443 ssl;
        server_name example.com *.example.com;

        acme le_wildcard;
        ssl_certificate     $acme_cert_le_wildcard;
        ssl_certificate_key $acme_cert_key_le_wildcard;
    }
}
```

### Сценарий 3: Использование External Account Binding (EAB)

Необходимо для коммерческих CA (ZeroSSL, Google Trust Services).

```nginx
http {
    resolver 8.8.8.8;

    acme_client zerossl {
        directory https://acme.zerossl.com/v2/DV90;
        # kid и key предоставляются провайдером
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

Автоматизация TLS для не-HTTP сервисов (например, PostgreSQL или Mail сервера).

```nginx
stream {
    resolver 1.1.1.1;

    acme_client db_le {
        directory https://acme-v02.api.letsencrypt.org/directory;
    }

    server {
        listen 5432 ssl;
        
        acme db_le;
        ssl_certificate     $acme_cert_db_le;
        ssl_certificate_key $acme_cert_key_db_le;

        proxy_pass pg_backend;
    }
}
```

## Дополнительная информация

### Хранение и безопасность

*   **Директория данных:** По умолчанию сертификаты и ключи аккаунтов сохраняются в `/var/lib/angie/acme/`.
*   **Права доступа:** Убедитесь, что рабочий пользователь Angie (`angie` или `www-data`) имеет права на чтение и запись в эту директорию.
*   **Ключ аккаунта:** Если у вас уже есть аккаунт Let's Encrypt, вы можете импортировать его ключ через директиву `acme_account_key`.

### Диагностика

Статус процесса получения сертификата можно отследить в `error.log`. 
Для принудительного обновления сертификата можно использовать директиву `acme_renew on;` (временно) или удалить файлы сертификатов из `/var/lib/angie/acme/` и выполнить `reload`.

### Ограничения

*   **DNS-01:** Встроенный DNS-responder поддерживает только базовую верификацию. Для сложных топологий с несколькими серверами за балансировщиком может потребоваться внешняя синхронизация директории `/var/lib/angie/acme/`.
*   **Лимиты CA:** Angie не обходит лимиты Let's Encrypt (например, 50 сертификатов в неделю на домен). Используйте Staging-сервер для тестов.

## См. также

*   **[Настройка TLS в Angie](./angie_tls_setup.md)**
*   **[Обзор TLS/SSL в Nginx](../Nginx/Security/TLS_SSL/nginx_tls_ssl_overview.md)**
*   **[Let's Encrypt и Certbot: общие принципы](../Concepts/https_with_certbot.md)**

# Автоматические TLS-сертификаты в Angie: модуль ACME

## Определения

### ACME и Let's Encrypt

**Протокол ACME (Automated Certificate Management Environment)** — стандарт автоматизированного получения и обновления TLS-сертификатов (RFC 8555). Разработан для автоматизации процесса выдачи сертификатов без участия человека.

**Let's Encrypt** — некоммерческий центр сертификации (Certificate Authority, CA), предоставляющий бесплатные SSL/TLS-сертификаты. Поддерживает протокол ACME.

**Модуль `acme`** в Angie — встроенное решение для автоматического получения и обновления [SSL/TLS-сертификатов](../../Networking/Protocols/tls.md) от CA, использующих протокол ACME (Let's Encrypt и др.). Интегрирует процесс управления сертификатами в конфигурацию веб-сервера, устраняя необходимость во внешних утилитах (Certbot, acme.sh).

### Ключевые термины

**Wildcard-сертификат** — сертификат вида `*.example.com`, защищающий основной домен и все поддомены первого уровня (app, blog, api и т.д.).

**OctoDNS** — инструмент управления DNS-записями по принципу Infrastructure as Code. Позволяет декларативно описывать зоны в YAML-файлах и синхронизировать их с провайдерами (Cloudflare, AWS Route53 и др.).

## Базовые концепции

### Преимущества встроенного модуля ACME

* **Полная автоматизация:** Angie самостоятельно получает, продлевает сертификаты и перезагружает конфигурацию.
* **Отсутствие внешних зависимостей:** Не требуется Certbot или acme.sh.
* **Бесшовная перезагрузка:** Обновление сертификатов происходит в памяти без полного рестарта.
* **Единое место конфигурации:** Настройка доменов и SSL находится в одном месте.

### Методы верификации домена (ACME Challenges)

#### HTTP-01 Challenge

* **Принцип:** CA запрашивает специальный файл по адресу `http://domain.com/.well-known/acme-challenge/TOKEN`.
* **Требования:** Открытый 80-й порт, доступность сервера из интернета.
* **Ограничение:** Не поддерживает Wildcard-сертификаты.

#### DNS-01 Challenge

* **Принцип:** CA проверяет наличие TXT-записи `_acme-challenge.domain.com` в DNS-зоне.
* **Преимущества:**
  * Поддержка Wildcard-сертификатов (`*.example.com`).
  * Не требует доступности сервера извне (работает за NAT/Firewall).
* **Реализация в Angie:**
  * **NS-делегирование:** Angie работает как DNS-сервер на 53-м порту и отвечает на запросы верификации. Требует делегирования поддомена `_acme-challenge` на IP сервера.
  * **API Hook:** Angie вызывает внешний скрипт (`acme_hook`), который через API DNS-провайдера создаёт TXT-запись. Применяется, если 53-й порт занят или нет возможности менять NS-записи.

### Рейтлимитинг Let's Encrypt

Let's Encrypt применяет ограничения на получение сертификатов. Некорректная настройка ACME может привести к временной блокировке домена.

| Лимит | Значение |
|-------|----------|
| Duplicate Certificate | 50 сертификатов на домен в неделю |
| Registration Rate Limit | 5 регистраций аккаунта на IP в час |
| Verification Rate Limit | 30 проверок авторизации на домен в час |

**Рекомендация:** Используйте staging-окружение для тестирования:

```nginx
acme_client letsencrypt {
    # Staging — без рейтлимитов
    directory "https://acme-staging-v02.api.letsencrypt.org/directory";
}

# Production — после успешного тестирования
acme_client letsencrypt {
    directory "https://acme-v02.api.letsencrypt.org/directory";
}
```

## Практические сценарии

### Сценарий 1: HTTP-01 верификация (для обычных сертификатов)

Это самый простой способ. Он требует, чтобы ваш сервер был доступен из интернета по 80-му порту.

**Шаг 1: Глобальная настройка `acme_client`**
В `angie.conf` в блоке `http` необходимо определить ACME-клиента и `resolver`.

```nginx
# /etc/angie/angie.conf
http {
    # ...

    # Определяем DNS-резолвер для ACME-клиента (обязательно)
    # Можно использовать публичные DNS, например, Cloudflare (1.1.1.1) или Google (8.8.8.8).
    resolver 1.1.1.1 8.8.8.8 valid=300s;
    resolver_timeout 5s;

    # Определяем клиента для Let's Encrypt
    acme_client letsencrypt {
        directory "https://acme-v02.api.letsencrypt.org/directory";
        # Для тестирования используйте staging-окружение, чтобы не исчерпать лимиты:
        # directory "https://acme-staging-v02.api.letsencrypt.org/directory";
    }

    # Можно определить несколько клиентов, например, для RSA и ECDSA ключей
    acme_client letsencrypt_rsa {
        directory "https://acme-v02.api.letsencrypt.org/directory";
        key_type rsa;
    }
    # ...
}
```

**Шаг 2: Настройка сервера (в блоке `server`)**
Укажите, что сервер должен использовать ACME для получения сертификата.

```nginx
# /etc/angie/http.d/example.com.conf
server {
    listen 80;
    server_name example.com www.example.com;

    # Для HTTP-01 challenge Angie автоматически обрабатывает .well-known/acme-challenge.
    # Убедитесь, что 80-й порт открыт и доступен.
    # Можно использовать редирект, но listen 80 должен быть активен.
    location / {
        return 301 https://$host$request_uri;
    }
}

server {
    listen 443 ssl http2;
    server_name example.com www.example.com;

    # Метод 1: Современный способ с использованием переменных Angie (рекомендуется)
    # Указываем, что сертификат и ключ будут предоставлены модулем ACME через переменные.
    ssl_certificate $acme_cert_letsencrypt;
    ssl_certificate_key $acme_cert_key_letsencrypt;
    # Включаем ACME, ссылаясь на ранее определенного клиента. Angie автоматически
    # управляет файлами сертификатов.
    acme letsencrypt; # или letsencrypt_rsa

    # Метод 2: Классический способ с явным указанием путей к файлам (также поддерживается)
    # Angie создаст файлы сертификатов по указанным путям при первом запуске.
    # ssl_certificate /etc/angie/ssl/example.com.crt;
    # ssl_certificate_key /etc/angie/ssl/example.com.key;
    # Включаем ACME и указываем клиента, если явно прописаны пути к сертификатам.
    # acme on;
    # acme_client letsencrypt;

    # ... остальная конфигурация HTTPS
    # Общие принципы настройки TLS описаны в руководстве
    # [Настройка TLS в Angie: безопасность и скорость](./angie_tls_setup.md)
}
```

### Сценарий 2: Несколько доменов

Рассмотрим пример с поддоменами `mail.zeroxzed.ru` и `webmail.zeroxzed.ru`. Необходимо определить по одному `acme_client` на каждый сертификат.

**Шаг 1: Глобальная настройка**

```nginx
# /etc/angie/angie.conf
http {
    # ...
    resolver 62.76.76.62 62.76.62.76;

    # Создаем по одному клиенту на каждый домен
    acme_client webmail {
        directory "https://acme-v02.api.letsencrypt.org/directory";
    }
    acme_client mail {
        directory "https://acme-v02.api.letsencrypt.org/directory";
    }
    # ...
}
```

**Шаг 2: Настройка серверов**

```nginx
# /etc/angie/http.d/webmail.conf
server {
    listen 443 ssl;
    server_name webmail.zeroxzed.ru;

    root /var/www/webmail;
    index index.php index.html;

    # Используем переменные, связанные с именем клиента
    acme webmail;
    ssl_certificate $acme_cert_webmail;
    ssl_certificate_key $acme_cert_key_webmail;
    # ...
}
server { listen 80; server_name webmail.zeroxzed.ru; return 301 https://$host$request_uri; }

# /etc/angie/http.d/mail.conf
server {
    listen 443 ssl;
    server_name mail.zeroxzed.ru;

    root /var/www/mail;
    index index.html;

    acme mail;
    ssl_certificate $acme_cert_mail;
    ssl_certificate_key $acme_cert_key_mail;
    # ...
}
server { listen 80; server_name mail.zeroxzed.ru; return 301 https://$host$request_uri; }
```

После перезапуска файлы сертификатов появятся в `/var/lib/angie/acme/`.

### Сценарий 3: DNS-01 верификация (Wildcard-сертификаты)

Для получения сертификатов вида `*.example.com` требуется подтверждение владения доменом через DNS.

**Шаг 1: Настройка `acme_client` для DNS**

```nginx
# /etc/angie/angie.conf
http {
    # ...
    resolver 1.1.1.1; # Или другие DNS-серверы

    acme_client letsencrypt_dns {
        directory "https://acme-v02.api.letsencrypt.org/directory";
        # Указываем, что для верификации будет использоваться DNS
        challenge_type dns-01;
    }
    # ...
}
```

**Шаг 2: Настройка сервера**

```nginx
# /etc/angie/sites-enabled/wildcard
server {
    listen 443 ssl;
    server_name *.example.com;

    ssl_certificate /etc/angie/ssl/wildcard.example.com.crt;
    ssl_certificate_key /etc/angie/ssl/wildcard.example.com.key;

    # Включаем ACME для этого сервера
    acme on;
    acme_client letsencrypt_dns;

    # Настраиваем обработчик DNS-запросов
    # Angie будет работать как мини-DNS-сервер на 53 порту для ответа на верификационные запросы
    acme_dns_server {
        listen 53 udp;
        listen 53; # TCP
    }
}
```

Для работы этого механизма необходимо делегировать обработку `_acme-challenge.example.com` на сервер, где запущен Angie, путем создания NS-записи:

```
# В настройках зоны example.com
_acme-challenge.example.com. IN NS ns1.acme.example.com.
ns1.acme.example.com.       IN A  <IP-адрес вашего Angie-сервера>
```

Альтернативой является `acme_dns_hook` для вызова внешнего скрипта, который работает с API DNS-провайдера.

## Дополнительная информация

### Отладка и эксплуатация

* **Логи:** Информация о процессе записывается в `error.log` на уровне `notice`. Подробнее: **[Логирование в Angie](./angie_logging.md)**.
* **Мониторинг:** Осуществляется через стандартные средства: **[Мониторинг Angie](./angie_monitoring.md)**.
* **Расположение файлов:** По умолчанию `/var/lib/angie/acme/<client_name>/`. Путь можно изменить директивой `acme_path`.
* **Автоматическое обновление:** Angie обновляет сертификаты примерно за 30 дней до истечения срока.
* **Тестовый запуск (dry-run):** Доступен для проверки конфигурации без фактической выдачи сертификата.

### Ограничения модуля ACME в Angie

* **Один клиент — один сертификат:** Нет возможности использовать одного `acme_client` для выпуска разных сертификатов для разных `server_name`. Требуется отдельный клиент на каждый сертификат.
* **Отсутствие хуков после обновления:** Модуль не предоставляет механизма для выполнения команд после обновления сертификата (например, перезагрузки Postfix или Dovecot).
  * **Возможное решение:** Использовать внешние инструменты (`incron`, `systemd.path`) для отслеживания изменений в `/var/lib/angie/acme/` и запуска скриптов.

### См. также

* **[Настройка TLS в Angie](./angie_tls_setup.md)**
* **[Использование Let's Encrypt с Certbot](../Concepts/https_with_certbot.md)**
* **[Использование acme.sh](../Concepts/acme_sh.md)**

# Автоматические TLS-сертификаты в Angie: Обзор модуля ACME

## Определения

**Модуль `acme`** в Angie — это встроенное решение для автоматического получения и обновления [SSL/TLS сертификатов](../../Networking/Protocols/tls.md) от центров сертификации (CA), использующих протокол **ACME (Automated Certificate Management Environment)**, таких как Let's Encrypt. Это избавляет от необходимости использовать внешние утилиты и интегрирует процесс управления сертификатами непосредственно в конфигурацию веб-сервера.

* **Let's Encrypt** — некоммерческий центр сертификации, предоставляющий бесплатные SSL/TLS сертификаты.
* **Wildcard-сертификат** — сертификат вида `*.example.com`, который защищает основной домен и все его поддомены первого уровня (app, blog, api и т.д.).
* **OctoDNS** — инструмент управления DNS-записями (Infrastructure as Code), позволяющий декларативно описывать зоны в YAML-файлах и синхронизировать их с различными провайдерами (Cloudflare, AWS Route53 и др.).

## Основные концепции

### Как работает ACME?

Протокол **ACME (RFC 8555)** автоматизирует процесс получения и обновления TLS-сертификатов, исключая ручную работу.

**Процесс в двух словах:**

1. **ACME-клиент** (например, Angie) запрашивает сертификат у **ACME-сервера** (например, Let's Encrypt).
2. Сервер выдает "испытание" (**challenge**), чтобы проверить, что клиент действительно владеет доменом.
3. Клиент выполняет испытание.
4. Сервер проверяет результат и, если все верно, выдает сертификат.

### Методы верификации домена (ACME Challenges)

#### 1. HTTP-01 Challenge

* **Принцип:** CA запрашивает специальный файл по адресу `http://domain.com/.well-known/acme-challenge/TOKEN`.
* **Требования:** Открытый 80 порт, доступность сервера извне.
* **Ограничение:** Не поддерживает Wildcard-сертификаты.

#### 2. DNS-01 Challenge

* **Принцип:** CA проверяет наличие специальной TXT-записи `_acme-challenge.domain.com` в DNS-зоне домена.
* **Преимущества:**
  * **Поддержка Wildcard-сертификатов (`*.example.com`).**
  * Не требует доступности сервера извне (может работать за NAT/Firewall).
* **Реализация в Angie:**
  * **NS-делегирование (простой метод):** Angie сама работает как мини-DNS сервер на 53 порту и отвечает на запросы верификации. Требует делегирования поддомена `_acme-challenge` на IP сервера.
  * **API Hook (продвинутый метод):** Angie вызывает внешний скрипт (`acme_hook`), который через API DNS-провайдера (например, через OctoDNS) создает нужную TXT-запись. Подходит, если 53 порт занят или нет возможности менять NS-записи.

### Преимущества встроенного модуля ACME в Angie

* **Полная автоматизация:** Angie самостоятельно инициирует получение, продлевает сертификаты и перезагружает конфигурацию.
* **Отсутствие внешних зависимостей:** Не требуется Certbot или acme.sh.
* **Бесшовная перезагрузка:** Обновление сертификатов происходит в памяти без полного рестарта.
* **Единый источник истины (SSoT):** Конфигурация доменов и их SSL находится в одном месте.

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

### 2. Сценарий для нескольких доменов

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

### 3. Настройка для DNS-01 (Wildcard-сертификаты)

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

### Отладка и продвинутые детали

* **Логи:** Информация о процессе пишется в `error.log` на уровне `notice`. Подробнее: **[Логирование в Angie](./angie_logging.md)**.
* **Статус:** Мониторинг осуществляется через стандартные средства: **[Мониторинг Angie](./angie_monitoring.md)**.
* **Расположение файлов:** По умолчанию `/var/lib/angie/acme/<client_name>/`. Путь можно изменить директивой `acme_path`.
* **Автоматическое обновление:** Angie обновляет сертификаты примерно за 30 дней до истечения.
* **Лимиты Let's Encrypt:** Для тестирования настоятельно рекомендуется использовать staging-окружение (`directory "https://acme-staging-v02.api.letsencrypt.org/directory"`), чтобы не исчерпать "боевые" лимиты на количество запросов (например, 50 сертификатов на домен в неделю).

### Ограничения модуля ACME в Angie

* **Один клиент на несколько доменов:** Нет элегантного способа использовать одного `acme_client` для выпуска разных сертификатов для разных `server_name`. Приходится создавать по одному клиенту на каждый сертификат.
* **Отсутствие хуков после обновления:** Модуль не предоставляет механизма для выполнения команд после обновления сертификата (например, для перезагрузки Postfix или Dovecot).
  * **Возможное решение:** Использовать внешние инструменты (`incron`, `systemd.path`) для отслеживания изменений в `/var/lib/angie/acme/` и запуска скриптов.

### Альтернативы и смежные решения

* **Certbot и acme.sh:** Классические утилиты командной строки. `certbot` имеет плагины для Nginx (см. **[Использование Let's Encrypt с Nginx в Docker](../Nginx/Scenarios/nginx_with_letsencrypt.md)**), а `acme.sh` известен широкой поддержкой DNS API.
* **Traefik:** Современный обратный прокси со встроенной автоматической поддержкой Let's Encrypt. См. **[обзор Traefik](../Traefik/traefik_overview.md)**.
* **Cert-manager:** Стандарт де-факто для управления TLS-сертификатами в Kubernetes. См. **[Cert-manager](../../Kubernetes/ToolsUtilities/cert_manager.md)**.

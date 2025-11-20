# Автоматические TLS-сертификаты с модулем ACME в Angie

Angie, форк Nginx, предлагает встроенный модуль `acme` для автоматического получения и обновления SSL/TLS сертификатов от центров сертификации, поддерживающих протокол ACME (например, Let's Encrypt). Это упрощает управление сертификатами, интегрируя процесс непосредственно в конфигурацию веб-сервера и исключая необходимость во внешних утилитах.

## 1. Let's Encrypt и преимущества бесплатных сертификатов

Let's Encrypt — это центр сертификации, предоставляющий бесплатные SSL/TLS сертификаты.
- **Цель:** Сделать HTTPS повсеместным, устраняя финансовые и технические барьеры для использования шифрования.
- **Доступность:** Сертификаты Let's Encrypt работают во всех основных операционных системах и браузерах.
- **Типы сертификатов:** Поддерживает как RSA, так и ECDSA сертификаты. Возможно одновременное использование обоих для максимальной совместимости.
- **Wildcard-сертификаты:** Позволяет выпускать Wildcard-сертификаты (например, `*.example.com`), которые могут покрывать неограниченное количество субдоменов третьего уровня.
- **Срок действия:** Сертификаты выдаются на 90 дней, что стимулирует автоматизацию процесса их обновления и снижает риски в случае утечки ключей.
- **Протокол ACME:** Использует протокол Automated Certificate Management Environment для автоматизации взаимодействия с ЦС.

## 2. Методы верификации домена (Challenges)

Для подтверждения владения доменом ACME протокол использует "вызовы" (challenges):

### 2.1. HTTP-01 Challenge

-   **Принцип:** Сервер ACME предоставляет токен, который необходимо разместить по определенному URL на вашем веб-сервере (например, `http://your-domain.com/.well-known/acme-challenge/YOUR_TOKEN`).
-   **Проверка:** Сервер ACME отправляет HTTP-запрос по этому URL. Если он получает ожидаемый токен, владение доменом считается подтвержденным.
-   **Требования:** Веб-сервер должен быть доступен из интернета по 80-му порту.
-   **Ограничения:** Не подходит для Wildcard-сертификатов.

### 2.2. DNS-01 Challenge

-   **Принцип:** Сервер ACME предоставляет токен, который необходимо добавить в виде TXT-записи в DNS-записи вашего домена (например, `_acme-challenge.your-domain.com IN TXT "YOUR_TOKEN"`).
-   **Проверка:** Сервер ACME выполняет DNS-запрос для этой TXT-записи. Если он получает ожидаемый токен, владение доменом считается подтвержденным.
-   **Преимущества:** Подходит для выпуска Wildcard-сертификатов. Не требует доступности веб-сервера по 80-му порту извне.
-   **Особенности:** Требует автоматизированного управления DNS-записями (через API DNS-провайдера или делегирование DNS).

## 3. Модуль `acme` в Angie

Встроенный модуль `acme` в Angie позволяет полностью интегрировать процесс получения и обновления сертификатов, устраняя потребность в сторонних инструментах типа Certbot или acme.sh.

### 3.1. Преимущества модуля `acme`

-   **Полная автоматизация:** Angie самостоятельно получает и продлевает сертификаты, включая перезагрузку конфигурации для их применения.
-   **Отсутствие внешних зависимостей:** Вся логика встроена в веб-сервер.
-   **Простота конфигурации:** Управление через декларативные директивы в конфигурационных файлах Angie.
-   **Гибкость:** Поддержка `http-01` и `dns-01` для обычных и Wildcard-сертификатов.

### 3.2. Настройка для HTTP-01 верификации (стандартные сертификаты)

1.  **Глобальная настройка (в `http` блоке `angie.conf`):**
    ```nginx
    # /etc/angie/angie.conf
    http {
        # ...
        # Определяем DNS-резолвер для ACME-клиента (обязательно)
        resolver 1.1.1.1 8.8.8.8 valid=300s;
        resolver_timeout 5s; # Пример из презентации
        # Для локальных DNS-серверов: resolver 127.0.0.53; (для systemd-resolved)

        # Определяем клиента для Let's Encrypt (для RSA)
        acme_client rsacert {
            directory "https://acme-v02.api.letsencrypt.org/directory";
            key_type rsa; # Явно указываем тип ключа
            # Для тестирования используйте staging-окружение:
            # directory "https://acme-staging-v02.api.letsencrypt.org/directory";
        }
        
        # Определяем клиента для Let's Encrypt (для ECDSA - по умолчанию)
        acme_client ecdsacer {
            directory "https://acme-v02.api.letsencrypt.org/directory";
            # key_type ec; # По умолчанию, можно не указывать
        }
        # ...
    }
    ```
    - `resolver`: Указывает DNS-серверы, используемые Angie для взаимодействия с ACME-сервером.
    - `acme_client`: Блок, описывающий ACME-клиента. `rsacert` и `ecdsacer` — произвольные имена.
    - `directory`: URL директории ACME-сервера.

2.  **Настройка сервера (в `server` блоке вашего сайта):**
    ```nginx
    # /etc/angie/sites-enabled/your_domain.conf
    server {
        listen 80;
        server_name your-domain.com www.your-domain.com; # Домены, для которых получаем сертификат

        # Для HTTP-01 challenge Angie автоматически обрабатывает .well-known/acme-challenge
        # Убедитесь, что 80-й порт открыт и доступен из интернета.
        # Можно использовать редирект на HTTPS, но listen 80 должен быть активен.
        location / {
            return 301 https://$host$request_uri;
        }
    }

    server {
        listen 443 ssl http2;
        server_name your-domain.com www.your-domain.com;

        # Включаем ACME для этого сервера, ссылаясь на ранее определенного клиента
        acme ecdsacer; # Или rsacert, если нужен RSA сертификат

        # Пути к сертификату и ключу, которые Angie сгенерирует и будет управлять
        ssl_certificate /var/lib/angie/acme/ecdsacer/your-domain.com/fullchain.pem;
        ssl_certificate_key /var/lib/angie/acme/ecdsacer/your-domain.com/privkey.pem;

        # ... остальная конфигурация HTTPS
    }
    ```
    - `acme`: Включает ACME для данного сервера и указывает используемый `acme_client`.
    - `ssl_certificate`, `ssl_certificate_key`: Пути, по которым Angie будет хранить сгенерированные сертификаты.
    - **Важно:** 80-й порт должен быть доступен для валидации.

### 3.3. Настройка для DNS-01 верификации (Wildcard-сертификаты)

Для Wildcard-сертификатов требуется DNS-01 верификация.

1.  **Глобальная настройка (в `http` блоке `angie.conf`):**
    ```nginx
    # /etc/angie/angie.conf
    http {
        # ...
        resolver 1.1.1.1 8.8.8.8 valid=300s;

        acme_client wildcard_client {
            directory "https://acme-v02.api.letsencrypt.org/directory";
            challenge_type dns-01; # Указываем тип вызова
            # Для тестирования используйте staging-окружение:
            # directory "https://acme-staging-v02.api.letsencrypt.org/directory";
        }
        # ...
    }
    ```
    - `challenge_type dns-01`: Указывает клиенту использовать DNS-верификацию.

2.  **Настройка сервера и делегирование DNS (в `server` блоке вашего сайта):**
    ```nginx
    # /etc/angie/sites-enabled/wildcard_domain.conf
    server {
        listen 443 ssl http2;
        server_name *.your-domain.com your-domain.com; # Домены, включая Wildcard

        acme wildcard_client;

        ssl_certificate /var/lib/angie/acme/wildcard_client/*.your-domain.com/fullchain.pem;
        ssl_certificate_key /var/lib/angie/acme/wildcard_client/*.your-domain.com/privkey.pem;

        # Настраиваем Angie для работы в качестве мини-DNS-сервера для ACME-запросов
        acme_dns_server {
            listen 53 udp; # UDP для DNS
            listen 53;     # TCP для DNS
        }

        # ... остальная конфигурация HTTPS
    }
    ```
    - `acme_dns_server`: Эта директива заставляет Angie работать как мини-DNS-сервер на 53 порту для ответа на верификационные запросы от Let's Encrypt.
    - **Делегирование DNS:** Для работы этого механизма необходимо делегировать обработку поддомена `_acme-challenge.your-domain.com` на сервер, где запущен Angie. Это делается путем создания NS-записи в настройках вашего домена, указывающей на IP-адрес Angie-сервера.
        ```dns
        # В настройках зоны your-domain.com
        _acme-challenge.your-domain.com. IN NS ns1.acme.your-domain.com.
        ns1.acme.your-domain.com.       IN A  <IP-адрес вашего Angie-сервера>
        ```
    - **Firewall:** Убедитесь, что 53-й порт (TCP и UDP) открыт на вашем Angie-сервере.

### 3.4. Использование `acme_dns_hook` для внешних DNS-провайдеров

Если делегирование DNS невозможно или неудобно, можно использовать `acme_dns_hook` для вызова внешнего скрипта, который будет взаимодействовать с API вашего DNS-провайдера для создания/удаления TXT-записей.

```nginx
# /etc/angie/angie.conf
http {
    # ...
    acme_client external_dns_hook {
        directory "https://acme-v02.api.letsencrypt.org/directory";
        challenge_type dns-01;
        
        # Указываем location, который будет обрабатывать хуки
        acme_hook_location @acme_dns_hook;
    }
    # ...
}

server {
    # ...
    location / {
        # ...
    }

    # Именованный location для обработки хуков
    location @acme_dns_hook {
        internal; # Доступен только для внутренних запросов Angie
        proxy_pass http://127.0.0.1:9000; # Пример: проксирование на локальный скрипт/сервис
        # Переменные с данными для скрипта
        proxy_set_header X-ACME-DOMAIN $acme_domain;
        proxy_set_header X-ACME-TOKEN $acme_token;
        proxy_set_header X-ACME-KEY-AUTH $acme_key_auth;
        proxy_set_header X-ACME-CONTEXT $acme_context; # 'add' или 'clean'
    }
}
```
-   `acme_hook_location`: Указывает именованный `location`, который будет вызван Angie при необходимости выполнить DNS-операции.
-   В этот `location` будут переданы переменные с необходимой информацией (`$acme_domain`, `$acme_token` и т.д.) для взаимодействия со скриптом.

## 4. Мониторинг и отладка

-   **Логи:** Вся информация о процессе получения и обновления сертификатов записывается в `error.log` на уровне `notice`.
-   **Расположение файлов:** Сертификаты хранятся в `/var/lib/angie/acme/<client_name>/<domain>/` по умолчанию. Путь можно изменить с помощью `acme_path`.
-   **Автоматическое обновление:** Angie самостоятельно отслеживает срок действия сертификатов и обновляет их, когда до истечения срока остается около 30 дней. При обновлении конфигурация перезагружается.
-   **Лимиты Let's Encrypt:** Будьте внимательны к лимитам Let's Encrypt (например, 50 сертификатов на домен в неделю, 5 ошибок авторизации в час). Используйте staging-окружение для тестирования (`directory "https://acme-staging-v02.api.letsencrypt.org/directory"`), чтобы не исчерпать боевые лимиты.

## 5. См. также

*   [Обзор модуля ACME в Angie](./angie_acme_module_overview.md)
*   [Настройка TLS в Angie: безопасность и скорость](./angie_tls_setup.md)
*   [Обзор Angie](./angie_overview.md)
*   [Установка Angie из пакетов](./angie_installation.md)
*   [Почему стоит переходить на Angie](./angie_why_migrate.md)

# Автоматические TLS-сертификаты в Angie: модуль ACME

## Определения

**Модуль `acme` в Angie** — встроенный полнофункциональный клиент для автоматизации жизненного цикла [SSL/TLS-сертификатов](../../Networking/Protocols/tls.md) по протоколу ACME (Automated Certificate Management Environment). 

В отличие от Nginx, где требуются внешние утилиты (Certbot, acme.sh), Angie интегрирует логику получения, проверки и обновления сертификатов непосредственно в ядро. Это позволяет управлять безопасностью соединений исключительно через конфигурационные файлы веб-сервера без развертывания дополнительного ПО.

Общие принципы работы Let's Encrypt, лимиты и типы проверок описаны в базовом руководстве:
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

## Операции и команды

### Управление процессами Angie

```bash
# Проверка конфигурации перед применением
sudo angie -t
# → angie: the configuration file /etc/angie/angie.conf syntax is ok
# → angie: configuration file /etc/angie/angie.conf test is successful

# Проверка конфигурации с тестовой загрузкой сертификатов
sudo angie -T
# → показывает загруженные конфиги, ACME-клиенты и сертификаты

# Применение конфигурации (zero downtime)
sudo angie -s reload

# Перезапуск worker процессов
sudo angie -s reopen

# Остановка сервера
sudo angie -s stop

# Принудительная остановка
sudo angie -s quit
```

### Управление ACME через CLI

```bash
# Просмотр логов ACME в реальном времени
sudo tail -f /var/log/angie/error.log | grep -i acme
# → [acme] certificate obtained for example.com
# → [acme] certificate renewed for example.com
# → [acme] challenge failed for example.com

# Проверка доступности директории ACME-сервера
curl -I https://acme-v02.api.letsencrypt.org/directory
# → HTTP/2 200

# Проверка доступности staging-окружения
curl -I https://acme-staging-v02.api.letsencrypt.org/directory
# → HTTP/2 200
```

### Управление сертификатами и данными ACME

```bash
# Просмотр списка сертификатов в директории
ls -la /var/lib/angie/acme/
# → letsencrypt/
# → zerossl/

# Просмотр конкретного сертификата
sudo ls -la /var/lib/angie/acme/letsencrypt/example.com/
# → example.com.crt
# → example.com.key
# → example.com.chain.pem

# Проверка срока действия сертификата
echo | openssl s_client -connect example.com:443 -servername example.com 2>/dev/null | openssl x509 -noout -dates
# → notBefore=...
# → notAfter=...

# Резервное копирование ACME-данных
sudo tar -czf /backup/angie-acme-$(date +%Y%m%d).tar.gz /var/lib/angie/acme/

# Восстановление из резервной копии
sudo tar -xzf /backup/angie-acme-20260921.tar.gz -C /

# Очистка устаревших сертификатов (старше 30 дней)
sudo find /var/lib/angie/acme/ -name "*.crt" -mtime +30 -exec ls -la {} \;
```

### Принудительное обновление сертификатов

```bash
# Способ 1: Временная активация renew через конфиг (если поддерживается)
# Добавить в http/stream блок: acme_renew on;
sudo angie -s reload
# После обновления удалить директиву и reload

# Способ 2: Удаление файлов сертификата (принудительный перевыпуск)
sudo rm -f /var/lib/angie/acme/letsencrypt/example.com.crt
sudo rm -f /var/lib/angie/acme/letsencrypt/example.com.key
sudo angie -s reload

# Способ 3: Полная очистка ACME-данных (использовать с осторожностью)
sudo rm -rf /var/lib/angie/acme/letsencrypt/*
sudo angie -s reload
```

### Переключение между Staging и Production

```bash
# Staging для тестов (не влияет на rate limits)
# В конфигурации:
acme_client le_test {
    directory https://acme-staging-v02.api.letsencrypt.org/directory;
    challenge http;
}

# Production
acme_client le_prod {
    directory https://acme-v02.api.letsencrypt.org/directory;
    challenge http;
}

# Проверка текущего окружения через API
curl -s http://127.0.0.1/api/v1/http/acme_clients/ | jq '.clients[] | {name, directory}'
```

### Мониторинг через API Angie

```bash
# Список всех ACME-клиентов
curl -s http://127.0.0.1/api/v1/http/acme_clients/ | jq .

# Статус конкретного клиента
curl -s http://127.0.0.1/api/v1/http/acme_clients/le_http/ | jq .
# → показывает домены, сроки действия, статус

# Проверка всех сертификатов
curl -s http://127.0.0.1/api/v1/http/acme/ | jq '.certs[] | {domain, expires, serial}'
# → {"domain": "example.com", "expires": "2026-12-21T...", "serial": "..."}
```

## Устранение неисправностей

### Ошибка ACME challenge failed

**Симптом:** В `error.log` появляется `[acme] challenge failed for example.com`.

**Диагностика:**
```bash
# Проверка доступности ACME-сервера
curl -I https://acme-v02.api.letsencrypt.org/directory
# → HTTP/2 200

# Для HTTP-01: проверка доступности порта 80
sudo ss -tlnp | grep :80
curl -s http://example.com/.well-known/acme-challenge/test

# Для DNS-01: проверка делегирования
dig +short _acme-challenge.example.com NS
dig @<IP_сервера> _acme-challenge.example.com TXT

# Проверка DNS-резолвера
dig +short example.com
```

**Причины и решения:**
1. **Порт 80 заблокирован:** Убедитесь что порт 80 открыт для входящих соединений из интернета. Проверьте брандмауэр (`sudo nft list ruleset | grep 80`).
2. **DNS-01 delegation:** Проверьте NS-запись для `_acme-challenge.example.com` и что сервер Angie отвечает на порту 53/UDP.
3. **Rate limit:** Используйте staging-окружение для тестов. Let's Encrypt ограничивает 50 сертификатов/неделю на домен.
4. **Прокси/CDN:** Если перед Angie стоит прокси, убедитесь что запросы `/.well-known/acme-challenge/*` достигают Angie без изменений.

### Сертификат не обновляется автоматически

**Симптом:** `error.log` не содержит записей об автоматическом обновлении, сертификат истекает.

**Диагностика:**
```bash
# Проверка статуса ACME через API
curl -s http://127.0.0.1/api/v1/http/acme_clients/ | jq .

# Проверка срока действия текущего сертификата
echo | openssl s_client -connect example.com:443 2>/dev/null | openssl x509 -noout -dates

# Проверка настроек renew в конфигурации
grep -r "acme_client" /etc/angie/ | grep -v "^#"
```

**Причины и решения:**
1. **Отсутствует параметр `renew`:** Убедитесь что в `acme_client` указан параметр `renew` (по умолчанию `30d`).
2. **Права доступа:** Рабочий пользователь `angie` должен иметь права на запись в `/var/lib/angie/acme/`.
3. **Сертификат не найден:** Angie не может обновить сертификат если не может его найти по пути из переменной `$acme_cert_<name>`.
4. **Ошибка в challenge:** Проверьте `error.log` на наличие ошибок `[acme] challenge failed`.

### Ошибки прав доступа к директории ACME

**Симптом:** `[acme] cannot open file: /var/lib/angie/acme/... Permission denied`.

**Диагностика:**
```bash
# Проверка прав на директорию
ls -la /var/lib/angie/acme/
# → drwxr-xr-x  angie angie  ... acme/

# Проверка пользователя Angie
ps -o user,pid,cmd -C angie | head -5
# → angie  1234 angie: master process /usr/sbin/angie
```

**Решение:**
```bash
# Исправление прав доступа
sudo chown -R angie:angie /var/lib/angie/acme/
sudo chmod 700 /var/lib/angie/acme/

# SELinux (если применимо)
sudo restorecon -Rv /var/lib/angie/acme/
```

### Rate limit Let's Encrypt

**Симптом:** `[acme] error: too many certificates already issued for: example.com`.

**Диагностика:**
```bash
# Проверка оставшихся лимитов через API
curl -s https://acme-v02.api.letsencrypt.org/directory | jq .
```

**Решение:**
1. Используйте staging-окружение для разработки и тестирования.
2. Для production используйте единый `acme_client` для всех поддоменов.
3. Для wildcard-сертификатов `*.example.com` используйте DNS-01, так как он покрывает все поддомены одним сертификатом.
4. Если лимит исчерпан — ждите 7 дней или используйте альтернативный CA (ZeroSSL, Buypass).

### DNS-01: Не работает делегирование

**Симптом:** `[acme] DNS-01 challenge failed: timeout` или `NXDOMAIN`.

**Диагностика:**
```bash
# Проверка NS-записи для _acme-challenge
dig +short _acme-challenge.example.com NS
# → <IP_вашего_сервера>

# Проверка что Angie слушает порт 53/UDP
sudo ss -u lnp | grep :53
# → UNCONN 0 0 *:domain *:* (users:(("angie",pid=1234,fd=10)))

# Тестовый DNS-запрос
dig @<IP_сервера> -p 53 _acme-challenge.example.com TXT
```

**Решение:**
1. Проверьте NS-запись в родительской зоне: `dig +short example.com NS`.
2. Убедитесь что `acme_dns_port 53;` указан в конфигурации.
3. Проверьте что порт 53/UDP открыт в брандмауэре.
4. Для нескольких серверов за балансировщиком настройте синхронизацию `/var/lib/angie/acme/`.

### Конфликт портов 80/443

**Симптом:** `[acme] port 80 already in use` или `[acme] cannot bind to port`.

**Диагностика:**
```bash
# Проверка занятости порта 80
sudo ss -tlnp | grep :80
# → LISTEN 0 128 0.0.0.0:80  users:(("nginx",pid=5678,fd=6))

# Проверка конфликтующих служб
sudo systemctl list-units --type=service --state=running | grep -E "nginx|httpd|caddy"
```

**Решение:**
1. Остановите конфликтующий веб-сервер: `sudo systemctl stop nginx`.
2. Используйте порт переадресации на уровне файрвола для ACME-челленджей.
3. Настройте `acme_client` на отдельном IP-адресе через `acme_bind`.

## Лучшие практики

### Безопасность

*   **Staging для тестов:** Используйте `https://acme-staging-v02.api.letsencrypt.org/directory` при разработке и отладке. Это предотвращает исчерпание rate limits в production.
*   **Права доступа:** Директория `/var/lib/angie/acme/` должна иметь права `700` и принадлежать пользователю `angie:angie`. Файлы ключей — `600`, сертификатов — `644`.
*   **Резервное копирование:** Регулярно копируйте `/var/lib/angie/acme/` для восстановления после сбоев. Включите ACME-данные в общую стратегию бэкапов сертификатов.
*   **Аудит сертификатов:** Периодически проверяйте срок действия сертификатов через API или `openssl s_client`.

### Эксплуатация

*   **Мониторинг:** Настройте мониторинг срока действия сертификатов через API `/status/http/acme_clients/<client>/`. При nearing expiry (например, <7 дней) отправляйте алерты.
*   **Единый клиент:** Для инфраструктуры с множеством поддоменов используйте один `acme_client` с wildcard-сертификатом (DNS-01) вместо множества отдельных HTTP-01 клиентов.
*   **Синхронизация multi-node:** При использовании нескольких серверов Angie синхронизируйте `/var/lib/angie/acme/` через NFS, rsync или shared storage. Иначе каждый узел будет пытаться получить собственный сертификат, что приведет к rate limit.
*   **Log rotation:** Настройте ротацию `error.log` через `logrotate`, чтобы логи ACME не занимали всё дисковое пространство.
*   **Тестирование после изменений:** После изменения конфигурации ACME всегда выполняйте `angie -t` и проверяйте статус через API перед `reload`.

### Производительность

*   **Кэширование переменных:** При использовании динамических путей к сертификатам включите `ssl_certificate_cache` для снижения накладных расходов на чтение файлов.
*   **Resolver кэширование:** Укажите `valid=300s` (или больше) в `resolver` для снижения количества DNS-запросов при проверке ACME-челленджей.
*   **Keepalive upstream:** Для DNS-01 challenge настройте `keepalive` в upstream-группе DNS-серверов для снижения задержек.

### Ограничения и известные проблемы

*   **Rate limits:** Let's Encrypt ограничивает 50 сертификатов/неделю на домен и 5 дубликатов в неделю. Используйте wildcard + DNS-01 для масштабных инфраструктур.
*   **Multi-server:** Встроенный DNS-responder для DNS-01 не поддерживает автоматическую синхронизацию между несколькими серверами. Требуется внешняя координация.
*   **ACME-совместимость:** Модуль поддерживает ACME v2 (RFC 8555). ACME v1 устарел и не поддерживается.

## Дополнительная информация

### Требования и ограничения

*   **Версия Angie:** Модуль `acme` доступен начиная с версии **Angie 1.10**.
*   **Поддерживаемые CA:** Let's Encrypt, ZeroSSL, Buypass и любые ACME v2-совместимые CA.
*   **Типы проверок:** HTTP-01 (порт 80) и DNS-01 (порт 53/UDP).
*   **Ключи:** Поддерживаются RSA (2048/4096) и ECDSA (256/384).
*   **Stream:** Автоматизация TLS доступна для TCP/UDP сервисов (блок `stream`).

### Диагностика

Статус процесса получения сертификата отслеживается в `error.log`. Для принудительного обновления можно использовать директиву `acme_renew on;` (временно) или удалить файлы сертификатов из `/var/lib/angie/acme/` и выполнить `reload`.

### Хранение и безопасность

*   **Директория данных:** По умолчанию сертификаты и ключи аккаунтов сохраняются в `/var/lib/angie/acme/`.
*   **Права доступа:** Убедитесь, что рабочий пользователь Angie (`angie` или `www-data`) имеет права на чтение и запись в эту директорию.
*   **Ключ аккаунта:** Если у вас уже есть аккаунт Let's Encrypt, вы можете импортировать его ключ через директиву `acme_account_key`.

### Взаимодействие с другими модулями

*   **DoH:** При использовании DNS-over-HTTPS для ACME-проверок может потребоваться отдельная политика DNS-резолвинга для запросов к ACME-серверам.
*   **TLS:** Сертификаты, полученные через ACME, автоматически используются в директивах `ssl_certificate` и `ssl_certificate_key`.

## См. также

*   **[Настройка TLS в Angie](./angie_tls_setup.md)**
*   **[Let's Encrypt и Certbot: общие принципы](../Concepts/https_with_certbot.md)**
*   **[DNS over HTTPS (DoH) в Angie](./angie_doh_module.md)**

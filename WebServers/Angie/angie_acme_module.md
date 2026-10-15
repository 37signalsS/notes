# Автоматические TLS-сертификаты в Angie: модуль ACME

**Актуально для:** Angie 1.12.x (модуль включен в базовую поставку начиная с Angie 1.10.x)

## Определения

**Модуль `acme` в Angie** — встроенный полнофункциональный клиент для автоматизации полного жизненного цикла [SSL/TLS-сертификатов](../../Networking/Protocols/tls.md) по протоколу ACME (Automated Certificate Management Environment, RFC 8555). В отличие от Nginx, где для выпуска и продления требуются внешние демоны и утилиты (Certbot, `acme.sh`, cron-скрипты), Angie интегрирует протокольную логику получения, прохождения проверок (challenges) и обновления сертификатов непосредственно в серверное ядро.

**ACME v2 Directory** — точка входа сервера сертификации (CA), возвращающая JSON со списком доступных ресурсов и методов авторизации (`newOrder`, `newAccount`, `newNonce`).

**HTTP-01 Challenge** — метод валидации владения доменом через протокол HTTP. Центр сертификации запрашивает уникальный проверочный токен по пути `http://<domain>/.well-known/acme-challenge/<token>`. Angie перехватывает такие запросы на порту 80 аппаратно в ядре без создания статических файлов на диске.

**DNS-01 Challenge** — метод валидации через публикацию одноразовой криптографической TXT-записи `_acme-challenge.<domain>`. Необходим для выпуска Wildcard-сертификатов (`*.example.com`) и для хостов, закрытых корпоративным файрволом от входящего HTTP-трафика.

**Встроенный DNS-responder** — встроенный в Angie легковесный DNS-сервер на базе директивы `acme_dns_port`, способный отвечать на проверочные TXT-запросы Let's Encrypt напрямую при делегировании NS-записи, без взаимодействия с внешними DNS-провайдерами или API.

**EAB (External Account Binding)** — механизм привязки ACME-аккаунта к предварительно зарегистрированной учетной записи в корпоративном или коммерческом CA (ZeroSSL, Entrust, Sectigo, внутренний HashiCorp Vault / Step-CA) с использованием пары идентификатора (`kid`) и криптографического HMAC-ключа (`hmac_key`).

**Atomic In-Memory Hot-Reload** — механизм Angie, при котором обновленные сертификаты и закрытые ключи загружаются в разделяемую память рабочих процессов (`worker`) на лету. В отличие от связки Nginx + Certbot, операция не требует выполнения `systemctl reload angie`, не порождает новых worker-процессов и не обрывает существующие Keepalive/WebSocket/gRPC-соединения.

Общие принципы протокола ACME, типы проверок и лимиты Let's Encrypt описаны в базовом руководстве:
> **[Let's Encrypt и Certbot: общие принципы и методы авторизации](../Concepts/https_with_certbot.md)**

---

## Базовые концепции и архитектура

### Внутренний жизненный цикл и архитектура процессов

Встроенный клиент ACME функционирует в контексте многопроцессной архитектуры Angie:

```
[ Master Process ]
       │
       ├─► 1. Фоновый таймер ревизии сертификатов (период проверки)
       ├─► 2. Генерация локального закрытого ключа (ECDSA/RSA)
       ├─► 3. Отправка заявки (CSR) к ACME Directory (Let's Encrypt / Step-CA)
       ├─► 4. Сохранение выданных данных в /var/lib/angie/acme/
       │
[ Worker Processes (Shared Memory) ]
       │
       ├─► HTTP-01: Перехват входящих /.well-known/acme-challenge/ (L7)
       ├─► DNS-01:  Встроенный mini-DNS responder на порту 53/UDP (L4)
       └─► Zero-Downtime: Мгновенное применение нового X.509 из памяти
```

1. **Инициализация:** При старте мастер-процесс Angie считывает параметры блоков `acme_client` в контекстах `http` или `stream`. Если сертификаты в локальном хранилище отсутствуют, генерируются приватные ключи аккаунта и домена, формируется CSR и отправляется запрос в ACME Directory.
2. **Маршрутизация проверок:** 
   - Для **HTTP-01** worker-процессы автоматически перехватывают URI с префиксом `/.well-known/acme-challenge/` на виртуальных серверах, где активирована директива `acme <name>;`. Перенаправления (редиректы на HTTPS) не ломают проверку, так как перехват выполняется до пользовательских блоков `location`.
   - Для **DNS-01** Angie слушает UDP/TCP-порт (по умолчанию 53 или заданный в `acme_dns_port`) и динамически генерирует TXT-ответ на DNS-запрос центра сертификации.
3. **Хранилище на диске:** Все артефакты сохраняются в защищенном системном каталоге `/var/lib/angie/acme/`.
4. **Бесшовное обновление:** За `renew` дней (по умолчанию 30 дней) до истечения срока действия мастер-процесс запускает процедуру ротации. После успешного получения новый сертификат атомарно монтируется в TLS-контекст рабочих процессов.

### Директивы конфигурации

Настройка клиента выполняется на глобальном уровне в блоке `http` или `stream` через директиву `acme_client`:

```nginx
acme_client <name> {
    directory   <url>;
    challenge   http | dns;
    key_type    rsa | ecdsa;
    key_bits    <size>;
    renew       <time>;
    contact     <uri>;
    eab         kid=<key_id>:key=<hmac_key>;
    account_key <path>;
}
```

#### Параметры блока `acme_client`

| Параметр | Описание | Значение по умолчанию | Допустимые значения |
| :--- | :--- | :--- | :--- |
| `directory` | Точка входа ACME Directory API. | **Обязателен** | URL (HTTPS) |
| `challenge` | Метод подтверждения владения доменом. | `http` | `http`, `dns` |
| `key_type` | Алгоритм генерации закрытого ключа сертификата. | `ecdsa` | `ecdsa`, `rsa` |
| `key_bits` | Длина ключа в битах. | `256` (для ECDSA) / `2048` (для RSA) | ECDSA: `256`, `384`; RSA: `2048`, `4096` |
| `renew` | Временной порог до окончания действия, запускающий обновление. | `30d` | Временные интервалы (`14d`, `30d`, `720h`) |
| `contact` | Контактный URI для оповещений от CA о проблемах безопасности. | Отсутствует | `mailto:admin@example.corp` |
| `eab` | Параметры External Account Binding для авторизованных CA. | Отсутствует | `kid=...:key=...` |
| `account_key` | Пользовательский путь к закрытому ключу аккаунта ACME. | Автоматически в хранилище | Абсолютный путь к файлу ключа |

#### Вспомогательные директивы контекста `http` и `stream`

*   `acme <client_name>;` — активирует привязку виртуального сервера (`server`) к указанному клиенту ACME. Серверный блок использует доменные имена из директивы `server_name` для формирования списка SAN (Subject Alternative Names).
*   `acme_dns_port <port>;` — задает сетевой порт для встроенного DNS-сервера проверок DNS-01 (по умолчанию 53).

### Переменные модуля

После завершения выпуска или загрузки сертификата из локального хранилища модуль регистрирует динамические переменные (где `<name>` — имя клиента из `acme_client`):

*   `$acme_cert_<name>` — абсолютный путь к файлу полного сертификата хоста (включая промежуточные сертификаты CA).
*   `$acme_cert_key_<name>` — абсолютный путь к файлу приватного ключа хоста.
*   `$acme_cert_chain_<name>` — абсолютный путь к цепочке доверия издателя (Intermediate CA).

Данные переменные передаются стандартным директивам Nginx/Angie:
```nginx
ssl_certificate     $acme_cert_myclient;
ssl_certificate_key $acme_cert_key_myclient;
```

---

## Практические сценарии

### Сценарий 1: Стандартный HTTP-01 сертификат с SAN и авторедиректом

Классический сценарий для веб-серверов в публичном контуре. Запросы на порт 80 автоматически перенаправляются на HTTPS, при этом системный endpoint `/.well-known/acme-challenge/` обслуживается Angie без помех.

```nginx
http {
    # Резолвер необходим Angie для разрешения имени ACME Directory
    resolver 127.0.0.53 1.1.1.1 valid=300s ipv6=off;

    # Конфигурация ACME-клиента
    acme_client letsencrypt_prod {
        directory https://acme-v02.api.letsencrypt.org/directory;
        challenge http;
        key_type  ecdsa;
        key_bits  256;
        renew     30d;
        contact   mailto:security@example.com;
    }

    # Сервер HTTP: обработка вызовов валидации и перенаправление пользователей
    server {
        listen 80;
        server_name example.com www.example.com;

        # Angie перехватывает /.well-known/acme-challenge/ автоматически,
        # глобальный редирект не блокирует валидацию Let's Encrypt
        location / {
            return 301 https://$host$request_uri;
        }
    }

    # Защищенный виртуальный хост HTTPS
    server {
        listen 443 ssl;
        http2 on;
        server_name example.com www.example.com;

        # Привязка к ACME клиенту
        acme letsencrypt_prod;
        ssl_certificate     $acme_cert_letsencrypt_prod;
        ssl_certificate_key $acme_cert_key_letsencrypt_prod;

        # Базовая оптимизация TLS (см. ../Nginx/Security/TLS_SSL/nginx_tls_ssl_overview.md)
        ssl_protocols TLSv1.2 TLSv1.3;
        ssl_session_timeout 1d;
        ssl_session_cache shared:SSL:10m;

        location / {
            root /var/www/html;
            index index.html;
        }
    }
}
```

### Сценарий 2: Wildcard-сертификат через встроенный DNS-01 responder

Позволяет выпустить единый сертификат на домен и все поддомены (`example.com`, `*.example.com`). Метод не требует открывать порт 80.

#### 1. Делегирование NS-записи на DNS-сервере домена
В авторитетной DNS-зоне домена настраивается перенаправление поддомена проверок на публичный IP-адрес хоста Angie:
```text
; DNS зона example.com
_acme-challenge.example.com.   IN  NS  acme-ns.example.com.
acme-ns.example.com.           IN  A   198.51.100.10
```

#### 2. Перенаправление порта 53 на непривилегированный (Linux Sysadmin)
Если Angie запускается от непривилегированного пользователя без capability `CAP_NET_BIND_SERVICE`, настраивается перенаправление через `nftables`:
```bash
sudo nft add table inet nat
sudo nft add chain inet nat prerouting '{ type nat hook prerouting priority -100; }'
sudo nft add rule inet nat prerouting udp dport 53 redirect to :5353
sudo nft add rule inet nat prerouting tcp dport 53 redirect to :5353
```

#### 3. Конфигурация Angie
```nginx
http {
    resolver 1.1.1.1 8.8.8.8 valid=60s;

    # Слушаем перенаправленный порт DNS
    acme_dns_port 5353;

    acme_client le_wildcard {
        directory https://acme-v02.api.letsencrypt.org/directory;
        challenge dns;
        key_type  ecdsa;
        contact   mailto:admin@example.com;
    }

    server {
        listen 443 ssl;
        server_name example.com *.example.com;

        acme le_wildcard;
        ssl_certificate     $acme_cert_le_wildcard;
        ssl_certificate_key $acme_cert_key_le_wildcard;

        location / {
            proxy_pass http://internal_backend;
        }
    }
}
```

### Сценарий 3: Интеграция с внутренним Private CA (Smallstep / HashiCorp Vault)

В закрытых корпоративных контурах без доступа в Интернет выпуск сертификатов организуется через локальный ACME CA (Smallstep `step-ca` или HashiCorp Vault ACME backend).

```nginx
http {
    # Внутренний корпоративный DNS
    resolver 192.168.10.2 192.168.10.3 valid=120s;

    # Конфигурация клиента с корпоративным CA
    acme_client internal_ca {
        directory https://ca.corp.internal:9000/acme/acme/directory;
        challenge http;
        key_type  ecdsa;
        renew     10d;

        # Если внутренний CA требует External Account Binding
        eab kid=08f7b2c9e4a1:key=7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a;
    }

    server {
        listen 80;
        server_name portal.corp.internal;

        location / {
            return 301 https://$host$request_uri;
        }
    }

    server {
        listen 443 ssl;
        server_name portal.corp.internal;

        acme internal_ca;
        ssl_certificate     $acme_cert_internal_ca;
        ssl_certificate_key $acme_cert_key_internal_ca;

        # Указание доверенной корневой цепочки корпоративного CA
        ssl_trusted_certificate /etc/ssl/certs/corp-internal-root-ca.pem;

        location / {
            proxy_pass http://127.0.0.1:8080;
        }
    }
}
```

> **Важно:** Для успешного подключения Angie к внутреннему CA корневой сертификат CA должен быть установлен в общесистемное хранилище ОС:
> ```bash
> sudo cp corp-internal-root-ca.pem /usr/local/share/ca-certificates/
> sudo update-ca-certificates
> # Для RHEL/CentOS/Astra:
> # sudo cp corp-internal-root-ca.pem /etc/pki/ca-trust/source/anchors/
> # sudo update-ca-trust
> ```

### Сценарий 4: ACME в модуле Stream (L4 TCP/UDP TLS Termination)

Автоматизация шифрования для не-HTTP сервисов: защищенные базы данных (PostgreSQL), брокеры сообщений (MQTT) или корпоративная почта.

```nginx
stream {
    resolver 1.1.1.1 valid=300s;

    acme_client stream_le {
        directory https://acme-v02.api.letsencrypt.org/directory;
        # В блоке stream доступен только challenge dns
        challenge dns;
        key_type  rsa;
        key_bits  4096;
    }

    server {
        listen 5432 ssl;

        acme stream_le;
        ssl_certificate     $acme_cert_stream_le;
        ssl_certificate_key $acme_cert_key_stream_le;

        ssl_protocols TLSv1.2 TLSv1.3;
        ssl_ciphers HIGH:!aNULL:!MD5;

        proxy_pass postgresql_cluster;
    }

    upstream postgresql_cluster {
        server 192.168.20.11:5432 max_fails=3 fail_timeout=10s;
        server 192.168.20.12:5432 backup;
    }
}
```

### Сценарий 5: Высокая доступность (HA) в Multi-Node кластере (Keepalived / VRRP)

При работе кластера из нескольких серверов под общим виртуальным IP (VRRP) запросы HTTP-01 от Let's Encrypt могут поступить на `BACKUP`-ноду, которая не инициировала вызов.

#### Рекомендуемая архитектура синхронизации:
1. Выпуск сертификатов делегируется исключительно узлу `MASTER` (или через DNS-01, доступный всем узлам).
2. Директория хранилища `/var/lib/angie/acme/` синхронизируется на вспомогательные ноды через защищенный `rsync` по SSH по триггеру `systemd.path`.

**Конфигурация systemd unit на MASTER (`/etc/systemd/system/angie-acme-sync.service`):**
```ini
[Unit]
Description=Sync Angie ACME certificates to secondary nodes
After=network.target

[Service]
Type=oneshot
ExecStart=/usr/bin/rsync -a --delete -e "ssh -o StrictHostKeyChecking=accept-new" /var/lib/angie/acme/ root@192.168.1.102:/var/lib/angie/acme/
ExecStartPost=/usr/bin/ssh root@192.168.1.102 "chown -R angie:angie /var/lib/angie/acme && angie -s reload"
```

**Монитор изменений файловой системы (`/etc/systemd/system/angie-acme-sync.path`):**
```ini
[Unit]
Description=Monitor Angie ACME storage directory for certificate renewals

[Path]
PathModified=/var/lib/angie/acme/
Unit=angie-acme-sync.service

[Install]
WantedBy=multi-user.target
```

---

## Операции и команды

### Проверка конфигурации и запуск

```bash
# Синтаксическая валидация конфигурационных файлов
sudo angie -t
# → angie: the configuration file /etc/angie/angie.conf syntax is ok
# → angie: configuration file /etc/angie/angie.conf test is successful

# Проверка конфигурации с подробным дампом загруженных директив ACME
sudo angie -T | grep -E "acme_client|ssl_certificate"
# → acme_client letsencrypt_prod {
# →     ssl_certificate $acme_cert_letsencrypt_prod;

# Перезагрузка конфигурации без обрыва соединений
sudo angie -s reload
# → [ok] configuration reloaded successfully
```

### Мониторинг состояния ACME через REST API Angie

Статус клиентов ACME инспектируется через встроенный API (см. [Мониторинг Angie — API](./angie_monitoring/angie_monitoring_api.md)):

```bash
# Просмотр списка и статуса всех сконфигурированных ACME клиентов
curl -s http://127.0.0.1:8080/status/http/acme_clients/ | jq .
# → {
# →   "letsencrypt_prod": {
# →     "directory": "https://acme-v02.api.letsencrypt.org/directory",
# →     "challenge": "http",
# →     "status": "ready"
# →   }
# → }

# Детальная информация по конкретному клиенту и выпущенным доменам
curl -s http://127.0.0.1:8080/status/http/acme_clients/letsencrypt_prod/ | jq .
# → {
# →   "domains": {
# →     "example.com": {
# →       "status": "valid",
# →       "valid_from": "2026-09-01T12:00:00Z",
# →       "valid_to": "2026-11-30T12:00:00Z",
# →       "days_left": 47,
# →       "key_type": "ECDSA",
# →       "sans": ["example.com", "www.example.com"]
# →     }
# →   }
# → }

# Мониторинг клиентов уровня L4 (Stream)
curl -s http://127.0.0.1:8080/status/stream/acme_clients/ | jq .
```

### Проверка и инспекция сертификатов на диске

```bash
# Просмотр структуры каталогов хранилища
ls -la /var/lib/angie/acme/
# → drwx------ 4 angie angie 4096 Sep 14 10:00 .
# → drwxr-xr-x 3 angie angie 4096 Sep 14 10:00 letsencrypt_prod

# Проверка срока действия и атрибутов сертификата через OpenSSL
openssl x509 -in /var/lib/angie/acme/letsencrypt_prod/example.com/cert.pem -noout -issuer -dates -subject
# → issuer=C = US, O = Let's Encrypt, CN = E1
# → notBefore=Sep 14 09:30:15 2026 GMT
# → notAfter=Dec 13 09:30:14 2026 GMT
# → subject=CN = example.com

# Проверка альтернативных имен субъекта (SAN)
openssl x509 -in /var/lib/angie/acme/letsencrypt_prod/example.com/cert.pem -noout -ext subjectAltName
# → X509v3 Subject Alternative Name: 
# →     DNS:example.com, DNS:www.example.com

# Проверка параметров открытого ключа (ECDSA кривая)
openssl x509 -in /var/lib/angie/acme/letsencrypt_prod/example.com/cert.pem -noout -text | grep -A 2 "Public Key Algorithm"
# → Public Key Algorithm: id-ecPublicKey
# →     Public-Key: (256 bit)
# →     ASN1 OID: prime256v1
```

### Экстренная ротация и принудительное обновление

```bash
# Способ 1: Удаление текущего сертификата для форсирования перевыпуска
sudo rm -f /var/lib/angie/acme/letsencrypt_prod/example.com/cert.pem
sudo angie -s reload

# Способ 2: Полная очистка данных клиента (перерегистрация аккаунта)
sudo rm -rf /var/lib/angie/acme/letsencrypt_prod/
sudo angie -s reload

# Мониторинг процесса выпуска в реальном времени
sudo tail -n 50 -f /var/log/angie/error.log | grep -i acme
# → 2026/09/14 10:15:02 [notice] 14201#14201: [acme] order created for example.com
# → 2026/09/14 10:15:05 [notice] 14201#14201: [acme] challenge verified for example.com
# → 2026/09/14 10:15:08 [notice] 14201#14201: [acme] certificate successfully obtained
```

### Резервное копирование и восстановление

```bash
# Создание зашифрованного резервного архива ключей и сертификатов
sudo tar -C /var/lib/angie/ -czf /backup/angie_acme_$(date +%F).tar.gz acme/
sudo chmod 600 /backup/angie_acme_*.tar.gz

# Восстановление из резервной копии
sudo tar -xzf /backup/angie_acme_2026-09-14.tar.gz -C /var/lib/angie/
sudo chown -R angie:angie /var/lib/angie/acme/
sudo chmod 700 /var/lib/angie/acme/
sudo angie -s reload
```

---

## Устранение неисправностей

### 1. Ошибка верификации HTTP-01: Challenge Failed (404 Not Found)

**Симптом:** Сертификат не выпускается. В `/var/log/angie/error.log` фиксируется сообщение:
`[acme] challenge failed for domain example.com: Invalid response from http://example.com/.well-known/acme-challenge/...: 404`

**Диагностика:**
```bash
# 1. Проверка доступности порта 80 из внешней сети
curl -I -L http://example.com/.well-known/acme-challenge/test-probe
# → HTTP/1.1 301 Moved Permanently (или 404/502)

# 2. Проверка, слушает ли Angie внешний интерфейс
sudo ss -tlpn | grep :80
# → LISTEN 0 511 0.0.0.0:80 users:(("angie",pid=14202,fd=7))

# 3. Проверка правил межсетевого экрана (nftables / iptables)
sudo nft list chain inet filter input | grep -E "dport 80"
# → tcp dport 80 accept
```

**Причины и решение:**
1. **Кастомный `location` перехватывает путь:** В блоке `server { listen 80; }` задан строгий регулярный `location ^~ /.` или `location ~ \.`, который отменяет дефолтный роутинг Angie. Убедитесь, что нет конфликтующих директив `return` или `rewrite`, блокирующих путь `/.well-known/acme-challenge/`.
2. **Внешний Reverse Proxy / Балансировщик:** Если перед Angie расположен внешний балансировщик (L4/L7), запросы к `/.well-known/acme-challenge/` должны безусловно проксироваться на порт 80 бэкенда Angie.
3. **Блокировка GeoIP / WAF:** Проверьте директивы `geo` или модуль безопасности Angie, отсекающие трафик от валидационных серверов Let's Encrypt (запросы на проверку исходят из распределенных пулов IP по всему миру).

---

### 2. Ошибка DNS-01: Зависание или Timeout резолвинга

**Симптом:** Лог содержит ошибки таймаута:
`[acme] DNS-01 challenge failed for *.example.com: DNS query timed out or SERVFAIL`

**Диагностика:**
```bash
# 1. Проверка наличия делегирования в родительской зоне
dig +short _acme-challenge.example.com NS
# → acme-ns.example.com.

# 2. Проверка ответа встроенного DNS responder Angie
dig @127.0.0.1 -p 5353 _acme-challenge.example.com TXT
# → ;; ANSWER SECTION:
# → _acme-challenge.example.com. 0 IN TXT "2bN7...token"

# 3. Проверка прослушивания порта DNS
sudo ss -ulpn | grep -E ":53|:5353"
# → UNCONN 0 0 0.0.0.0:5353 users:(("angie",pid=14201,fd=12))
```

**Причины и решение:**
1. **Конфликт с локальным DNS-резолвером:** Если на сервере запущен `systemd-resolved` или `named/bind9`, порт `53` занят на `127.0.0.53:53` или `0.0.0.0:53`.
   - Решение: Настройте `acme_dns_port 5353;` в Angie и используйте правило DNAT в файрволе для перенаправления входящего трафика с 53 на 5353 (см. Сценарий 2).
2. **Фильтрация UDP-трафика:** Межсетевые экраны часто фильтруют входящий UDP/53. Убедитесь, что протоколы UDP и TCP открыты для входящих пакетов.

---

### 3. Ошибки прав доступа к локальному хранилищу

**Симптом:** В логе фиксируется:
`[emerg] or [error]: [acme] open() "/var/lib/angie/acme/..." failed (13: Permission denied)`

**Диагностика:**
```bash
# Проверка владельца и атрибутов директории
ls -ld /var/lib/angie/acme/
# → drwxr-xr-x 3 root root 4096 Sep 14 09:00 /var/lib/angie/acme/

# Проверка пользователя, под которым работают worker-процессы
ps -eo user,group,comm | grep angie
# → root     root     angie (master)
# → angie    angie    angie (worker)
```

**Решение:**
Мастер-процесс создает файлы под учетной записью воркера либо воркер пытается прочитать закрытый ключ. Задайте корректные права:
```bash
sudo chown -R angie:angie /var/lib/angie/acme/
sudo chmod 700 /var/lib/angie/acme/
sudo find /var/lib/angie/acme/ -type f -name "*.key" -exec chmod 600 {} \;
sudo find /var/lib/angie/acme/ -type f -name "*.pem" -exec chmod 644 {} \;

# Если используется SELinux:
sudo restorecon -Rv /var/lib/angie/acme/
```

---

### 4. Ошибка лимитов Let's Encrypt (Rate Limit 429)

**Симптом:**
`[acme] error from directory: 429 urn:ietf:params:acme:error:rateLimited: too many certificates already issued for exact set of domains`

**Диагностика:**
```bash
# Проверка лога на количество повторных запросов
grep -c "rateLimited" /var/log/angie/error.log
# → 14
```

**Решение:**
1. **Переключение на Staging для отладки конфигурации:**
   Замените URL в `directory` на тестовый стенд Let's Encrypt:
   ```nginx
   directory https://acme-staging-v02.api.letsencrypt.org/directory;
   ```
2. **Объединение доменов (SAN):** Вместо выпуска отдельных сертификатов для каждого сервиса (`api.example.com`, `auth.example.com`, `www.example.com`) используйте группировку в одном `server_name` или перейдите на Wildcard-сертификат по DNS-01.
3. **Использование альтернативного CA:** Если лимит исчерпан в production, переключитесь на альтернативный ACME-совместимый удостоверяющий центр (ZeroSSL, Buypass) через директиву `directory`.

---

## Лучшие практики

### Безопасность и хранение ключей

*   **Алгоритм ECDSA по умолчанию:** Используйте `key_type ecdsa; key_bits 256;`. Ключи на базе эллиптических кривых P-256 обеспечивают эквивалентную стойкость 3072-битному RSA, сокращая нагрузку на CPU при хэндшейках в 3–4 раза.
*   **Изоляция каталога хранения:** Каталог `/var/lib/angie/acme/` должен иметь права доступа строго `700` (`drwx------`) и принадлежать системному пользователю демона (`angie:angie`).
*   **systemd Hardening:** В unit-файле `/etc/systemd/system/angie.service.d/override.conf` укажите права на запись только в каталог ACME:
    ```ini
    [Service]
    ProtectSystem=strict
    ReadWritePaths=/var/log/angie /var/lib/angie/acme /run
    CapabilityBoundingSet=CAP_NET_BIND_SERVICE CAP_SETUID CAP_SETGID
    ```

### Эксплуатация и SRE-надежность

*   **Интервал обновления (`renew`):** Устанавливайте `renew 30d;` при 90-дневном сроке жизни сертификатов. Это гарантирует 30-дневный резерв времени для устранения сбоев сети, DNS или багов CA до фактической деградации сервиса.
*   **Кэширование путей к сертификатам:** При использовании переменных `$acme_cert_<name>` в высоконагруженных окружениях включайте директиву `ssl_certificate_cache`:
    ```nginx
    http {
        ssl_certificate_cache max=1000 inactive=1d;
    }
    ```
    Это предотвращает повторные системные вызовы `stat()` и чтение файлов сертификатов с диска на каждый SSL-хэндшейк.
*   **Ограничение частоты DNS-запросов:** Для `resolver` задавайте параметр `valid=300s` и резервные адреса DNS, чтобы сбои одного резолвера не препятствовали получению сертификатов.

### Мониторинг и алертинг (Prometheus / Blackbox)

*   **Prometheus Alertmanager Rule:** Используйте blackbox-проверку срока действия TLS:
    ```yaml
    - alert: TLSCertificateExpiringSoon
      expr: probe_ssl_earliest_cert_expiry{job="blackbox"} - time() < 86400 * 14
      for: 1h
      labels:
        severity: warning
      annotations:
        summary: "TLS certificate for {{ $labels.instance }} expires in less than 14 days"
    ```
*   **API Healthcheck:** Настройте периодический опрос Angie API:
    ```bash
    curl -sf http://127.0.0.1:8080/status/http/acme_clients/letsencrypt_prod/ | jq -e '.domains[].days_left > 7' > /dev/null
    ```

---

## Дополнительная информация

### Сводные системные требования

*   **Версия:** Angie 1.10.0 и новее (рекомендуется стабильная ветка 1.12.x).
*   **Поддерживаемые RFC:** RFC 8555 (ACME v2), RFC 8737 (ALPN challenge — через внешние связки), RFC 7633. Протокол ACME v1 признан устаревшим и не поддерживается.
*   **Сетевые требования:** 
    - Для HTTP-01: доступность входящего TCP-порта 80 из глобальной сети.
    - Для DNS-01: доступность входящего UDP/TCP-порта 53 (или перенаправленного через `acme_dns_port`).
    - Исходящий HTTPS-трафик на порт 443 к ACME Directory CA.

### См. также

*   **[Настройка TLS в Angie](./angie_tls_setup.md)** — параметры протоколов, шифры, HTTP/3 (QUIC) и кэширование сертификатов
*   **[Let's Encrypt и Certbot: общие принципы и методы авторизации](../Concepts/https_with_certbot.md)** — архитектура ACME, типы проверок, цепочки доверия и лимиты
*   **[Мониторинг Angie — API](./angie_monitoring/angie_monitoring_api.md)** — эндпоинты `/status/http/acme_clients/` и сбор диагностических метрик
*   **[Обзор TLS/SSL в Nginx/Angie](../Nginx/Security/TLS_SSL/nginx_tls_ssl_overview.md)** — протоколы, ciphers, HSTS и OCSP Stapling
*   **[Отказоустойчивость Angie с Keepalived](./angie_ha_with_keepalived.md)** — архитектура High Availability, плавающие IP и кластерная синхронизация

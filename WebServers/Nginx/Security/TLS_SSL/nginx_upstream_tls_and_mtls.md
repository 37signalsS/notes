# Защита Upstream TLS и взаимная аутентификация (mTLS) к бэкендам в Nginx

**Актуально для:** Nginx 1.26+ (OSS/Plus) / 1.28+ – 1.30.x (Mainline), OpenSSL 3.0+

## Определения

**Upstream TLS** — механизм криптографической защиты сетевого канала между пограничным сервером Nginx (выступающим в роли TLS-клиента) и вышестоящими серверами приложений (Upstream / Backend). Обеспечивает конфиденциальность, целостность данных и защиту от атак Man-in-the-Middle (MitM) внутри инфраструктурного периметра.

**Backend mTLS (Mutual TLS к апстримам)** — двусторонняя криптографическая аутентификация, при которой не только Nginx проверяет подлинность сертификата бэкенда, но и бэкенд требует и валидирует клиентский X.509-сертификат, предъявляемый Nginx. Ключевой компонент архитектуры нулевого доверия (Zero-Trust).

**`proxy_ssl_verify`** — директива Nginx, активирующая обязательную криптографическую валидацию цепочки доверия X.509-сертификата, предъявляемого сервером апстрима. При значении `off` Nginx игнорирует ошибки срока действия, самоподписанные сертификаты и несоответствие имен, что делает канал уязвимым для MitM-перехвата.

**Upstream SNI (`proxy_ssl_server_name`)** — директива, предписывающая Nginx передавать имя целевого хоста в расширении Server Name Indication (SNI) пакета `ClientHello` при установлении TLS-соединения с бэкендом. Критически необходима, если бэкенд обслуживает несколько виртуальных хостов на одном IP:порту.

**`proxy_ssl_name`** — директива, явно задающая доменное имя для расширения SNI и сопоставления с именами Subject Alternative Name (SAN) в сертификате бэкенда. По умолчанию принимает значение заголовка `$proxy_host`.

**`proxy_ssl_trusted_certificate`** — путь к файлу в формате PEM, содержащему доверенные корневые (Root CA) и промежуточные (Intermediate CA) сертификаты, используемые для проверки подлинности бэкендов.

**`proxy_ssl_session_reuse`** — директива включения повторного использования параметров TLS-сессий (Session Resumption) при проксировании к апстримам. Сокращает задержку (RTT) и нагрузку на CPU бэкендов за счет исключения полного асимметричного рукопожатия при повторных запросах.

---

## Архитектура и основные концепции

### Модель Zero-Trust и роль Upstream TLS

В традиционных архитектурах Nginx терминирует TLS на внешнем периметре и передает трафик к бэкендам в открытом виде по HTTP/1.1 через внутреннюю сеть (DMZ / Private VLAN). В современных распределенных системах и требованиях регуляторов (PCI-DSS, 152-ФЗ, ISO 27001) такой подход считается уязвимым:

1. **Компрометация сегмента сети:** Злоумышленник, получивший доступ к соседнему хосту или контейнеру в том же L2-сегменте, способен осуществлять ARP-спуфинг и пассивный перехват незашифрованного внутреннего трафика (включая персональные данные, сессионные токены и API-ключи).
2. **Подмена бэкенда:** Без валидации сертификата (`proxy_ssl_verify on`) вредоносный узел может перехватить трафик к бэкенду через отравление DNS-кэша или манипуляцию с таблицей маршрутизации.

```text
Клиент ──[ HTTPS / TLS 1.3 ]──► [ Nginx (Reverse Proxy) ] ──[ HTTPS / mTLS ]──► [ Бэкенд / Microservice ]
                                (TLS Server)               (TLS Client)         (TLS Server)
                                Слушает: 443               Клиентский сокет     Слушает: 8443
                                Сертификат: public.crt     proxy_ssl_cert: app  Проверяет: Nginx CA
                                Валидация: WebPKI          Валидация: Corp CA   Валидация: Client CN
```

### Жизненный цикл TLS-рукопожатия между Nginx и Upstream

Когда Nginx обрабатывает директиву `proxy_pass https://...`:

1. **Инициализация соединения:** Nginx открывает TCP-сокет к IP-адресу апстрима.
2. **ClientHello с расширением SNI:** Если включена директива `proxy_ssl_server_name on;`, Nginx добавляет в `ClientHello` имя хоста из `proxy_ssl_name`. Бэкенд выбирает правильный сертификат из своей конфигурации.
3. **Получение и валидация сертификата бэкенда:**
   - Если `proxy_ssl_verify on;`, Nginx сверяет цепочку сертификата бэкенда со списком доверенных центров из `proxy_ssl_trusted_certificate`.
   - Глубина проверки ограничивается директивой `proxy_ssl_verify_depth` (по умолчанию `1`).
   - Nginx проверяет, что имя хоста из `proxy_ssl_name` совпадает с одним из значений в расширении `X509v3 Subject Alternative Name (SAN)` сертификата бэкенда.
4. **Взаимная аутентификация (при mTLS):**
   - Если бэкенд запрашивает клиентский сертификат (`CertificateRequest`), Nginx отправляет сертификат, заданный в `proxy_ssl_certificate`, и подписывает рукопожатие закрытым ключом `proxy_ssl_certificate_key`.
5. **Согласование симметричных ключей:** Завершение рукопожатия и переход к безопасной передаче HTTP-запросов внутри TLS-туннеля.

### Проблема SNI и виртуальных хостов бэкенда

Распространенная производственная ошибка — отсутствие директивы `proxy_ssl_server_name on;`. 

По умолчанию Nginx **не передает SNI** на бэкенд. Если бэкенд обслуживает несколько защищенных сервисов (например, Ingress-контроллер, разделяемый веб-сервер или шлюз API), бэкенд отдает сертификат по умолчанию (default server), который часто не совпадает с запрашиваемым именем хоста. В результате Nginx аварийно разрывает соединение с ошибкой:

```text
upstream SSL certificate does not match "my-backend.corp"
```

Включение `proxy_ssl_server_name on;` является обязательным базовым требованием для production.

---

## Практические сценарии

### Сценарий 1: Строгая верификация TLS бэкенда с корпоративным CA

Конфигурация Nginx в качестве защищенного шлюза, отправляющего трафик на внутренний сервис с проверкой подлинности по закрытому корпоративному удостоверяющему центру (Internal Root CA).

Файл `/etc/nginx/conf.d/upstream_secure.conf`:

```nginx
# Определение пула бэкендов
upstream backend_payment_service {
    server 192.168.10.25:8443 max_fails=3 fail_timeout=10s;
    server 192.168.10.26:8443 max_fails=3 fail_timeout=10s;

    # Пул постоянных соединений для снижения накладных расходов на TLS
    keepalive 32;
}

server {
    listen 443 ssl;
    server_name payment-gateway.corp.example;

    ssl_certificate     /etc/ssl/certs/gateway_public.crt;
    ssl_certificate_key /etc/ssl/private/gateway_public.key;

    location /api/v1/payments/ {
        # Проксирование по HTTPS
        proxy_pass https://backend_payment_service;

        # Протокол взаимодействия к апстриму
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host payment-service.internal.corp;

        # --- Харденинг Upstream TLS ---
        # 1. Принудительная верификация сертификата бэкенда
        proxy_ssl_verify on;

        # 2. Глубина проверки цепочки (Leaf -> Intermediate CA -> Root CA = 2)
        proxy_ssl_verify_depth 2;

        # 3. Доверенный бандл внутренних центров сертификации
        proxy_ssl_trusted_certificate /etc/ssl/certs/corp_internal_ca_bundle.crt;

        # 4. Передача SNI и проверка соответствия имени хоста
        proxy_ssl_server_name on;
        proxy_ssl_name payment-service.internal.corp;

        # 5. Ограничение допустимых протоколов и шифров к апстриму
        proxy_ssl_protocols TLSv1.2 TLSv1.3;
        proxy_ssl_ciphers ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384;

        # 6. Кэширование параметров сессий для снижения задержки
        proxy_ssl_session_reuse on;

        # Таймауты установки защищенного соединения
        proxy_connect_timeout 5s;
        proxy_read_timeout 30s;
        proxy_send_timeout 10s;
    }
}
```

---

### Сценарий 2: Двусторонняя аутентификация (mTLS) от Nginx к микросервисам

В высокозащищенных контурах (платежные шлюзы, базы данных с TLS-интерфейсом, внутренние gRPC-сервисы) бэкенд не принимает подключения без валидного клиентского сертификата. Nginx авторизуется перед бэкендом собственным сертификатом.

Файл `/etc/nginx/conf.d/upstream_mtls.conf`:

```nginx
upstream auth_cluster {
    server 10.200.0.11:9443;
    server 10.200.0.12:9443;
    keepalive 16;
}

server {
    listen 443 ssl;
    server_name api.corp.example;

    ssl_certificate     /etc/ssl/certs/api_public.crt;
    ssl_certificate_key /etc/ssl/private/api_public.key;

    location /v2/auth/ {
        proxy_pass https://auth_cluster;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host auth-core.internal;

        # Верификация сервера бэкенда
        proxy_ssl_verify on;
        proxy_ssl_verify_depth 2;
        proxy_ssl_trusted_certificate /etc/ssl/certs/internal_root_ca.crt;
        proxy_ssl_server_name on;
        proxy_ssl_name auth-core.internal;

        # --- Клиентский сертификат Nginx для авторизации на бэкенде ---
        proxy_ssl_certificate     /etc/ssl/certs/nginx_egress_client.crt;
        proxy_ssl_certificate_key /etc/ssl/private/nginx_egress_client.key;

        # Защита приватного ключа: если ключ защищен паролем
        # proxy_ssl_password_file /etc/nginx/ssl_passwords.txt;

        # Повторное использование сессий mTLS
        proxy_ssl_session_reuse on;
    }
}
```

---

### Сценарий 3: Проверка отзыва сертификатов бэкендов через CRL (`proxy_ssl_crl`)

При выводе серверов из эксплуатации или компрометации приватного ключа одного из узлов бэкенда Nginx обязан немедленно блокировать соединение, сверяясь со списком отзыва (Certificate Revocation List).

Файл `/etc/nginx/conf.d/upstream_crl.conf`:

```nginx
location /secure-backend/ {
    proxy_pass https://192.168.50.10:8443;

    proxy_ssl_verify on;
    proxy_ssl_verify_depth 2;
    proxy_ssl_trusted_certificate /etc/ssl/certs/internal_ca.crt;

    # Список отозванных сертификатов в формате PEM
    proxy_ssl_crl /etc/ssl/crl/internal_ca_revoked.crl;

    proxy_ssl_server_name on;
    proxy_ssl_name backend-node-01.corp.internal;
}
```

---

### Сценарий 4: Оптимизация производительности: Upstream Keepalive + TLS Session Reuse

TLS-рукопожатие к апстриму на каждый HTTP-запрос добавляет от 2 до 15 мс сетевой задержки и нагружает CPU криптографическими операциями. Сочетание `keepalive` в блоке `upstream` и `proxy_ssl_session_reuse on;` минимизирует накладные расходы.

Файл `/etc/nginx/conf.d/optimized_upstream_tls.conf`:

```nginx
upstream highload_backend {
    server 10.10.1.50:8443;
    server 10.10.1.51:8443;

    # Максимальное количество неактивных постоянных соединений на каждый воркер Nginx
    keepalive 128;

    # Максимальное число запросов, передаваемых по одному постоянному соединению
    keepalive_requests 10000;

    # Время удержания открытого постоянного соединения при отсутствии трафика
    keepalive_timeout 60s;
}

server {
    listen 80;
    server_name fast-proxy.corp.internal;

    location / {
        proxy_pass https://highload_backend;

        # Обязательные директивы для работы keepalive с upstream
        proxy_http_version 1.1;
        proxy_set_header Connection "";

        # Включение кэширования параметров TLS-сессии
        proxy_ssl_session_reuse on;

        proxy_ssl_verify on;
        proxy_ssl_trusted_certificate /etc/ssl/certs/corp_ca.crt;
        proxy_ssl_server_name on;
    }
}
```

---

## Операции и команды

### 1. Верификация доступности и сертификата бэкенда через `openssl s_client`

Перед включением строгой проверки в Nginx проверьте ответ бэкенда из командной строки сервера Nginx:

```bash
# Эмуляция проверки сертификата бэкенда с использованием внутреннего CA
openssl s_client -connect 192.168.10.25:8443 -servername payment-service.internal.corp -CAfile /etc/ssl/certs/corp_internal_ca_bundle.crt
# → CONNECTED(00000003)
# → depth=2 CN = Corporate Root CA
# → verify return:1
# → depth=1 CN = Intermediate Issuing CA
# → verify return:1
# → depth=0 CN = payment-service.internal.corp
# → verify return:1
# → Verify return code: 0 (ok)
```

### 2. Тестирование mTLS к бэкенду с клиентским сертификатом Nginx

```bash
# Проверка рукопожатия с предъявлением клиентского сертификата и ключа
openssl s_client -connect 10.200.0.11:9443 \
    -servername auth-core.internal \
    -CAfile /etc/ssl/certs/internal_root_ca.crt \
    -cert /etc/ssl/certs/nginx_egress_client.crt \
    -key /etc/ssl/private/nginx_egress_client.key
# → Acceptable client certificate CA names
# → CN = Corporate Internal Client CA
# → Client certificate
# → SSL handshake has read 3412 bytes and written 2145 bytes
# → Verification: OK
```

### 3. Проверка прав доступа к файлам ключей

Приватный ключ клиентского сертификата Nginx должен быть доступен для чтения пользователю, под которым работают воркеры Nginx (например, `nginx` или `www-data`):

```bash
# Проверка прав доступа
ls -la /etc/ssl/private/nginx_egress_client.key
# → -rw-r----- 1 root nginx 1704 Oct 17 14:00 /etc/ssl/private/nginx_egress_client.key

# Проверка синтаксиса Nginx и применения
nginx -t
# → nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

systemctl reload nginx
```

---

## Устранение неполадок

| Код ошибки / Сообщение в `error.log` | Причина сбоя | Метод локализации | Решение |
| :--- | :--- | :--- | :--- |
| `upstream SSL certificate verify error: (20:unable to get local issuer certificate)` | Nginx не может построить цепочку доверия до корневого сертификата. В файле `proxy_ssl_trusted_certificate` отсутствует промежуточный или корневой CA. | `openssl verify -CAfile /etc/ssl/certs/ca.crt /tmp/backend.crt` | Собрать полный бандл доверенных CA (Root + Intermediates) в файл `proxy_ssl_trusted_certificate`. |
| `upstream SSL certificate does not match "backend_pool"` | Не настроена передача SNI или имя хоста в `proxy_ssl_name` не совпадает с SAN сертификата бэкенда. | `openssl s_client -connect IP:PORT </dev/null \| openssl x509 -noout -text \| grep -A1 "Subject Alternative Name"` | Добавить `proxy_ssl_server_name on;` и явно указать `proxy_ssl_name <dns_name>;`. |
| `upstream SSL certificate verify error: (10:certificate has expired)` | Истек срок действия X.509-сертификата на сервере бэкенда. | `echo \| openssl s_client -connect IP:PORT 2>/dev/null \| openssl x509 -noout -dates` | Обновить сертификат на бэкенде или продлить его через внутренний CA/ACME. |
| `SSL_do_handshake() failed (SSL: error:0A0000C1:SSL routines::no shared cipher)` | Несовпадение поддерживаемых версий протоколов (TLS 1.2 vs 1.3) или шифронаборов между Nginx и бэкендом. | Сравнить директиву `proxy_ssl_protocols` / `proxy_ssl_ciphers` с конфигурацией TLS на бэкенде. | Привести `proxy_ssl_protocols` и `proxy_ssl_ciphers` к совместимым стандартам (например, `TLSv1.2 TLSv1.3`). |
| `peer did not return a certificate` (на бэкенде) / `403 Forbidden` | Бэкенд требует mTLS, но Nginx не отправил клиентский сертификат, либо путь к ключу недоступен воркеру. | Проверить журнал ошибок бэкенда и права на `proxy_ssl_certificate_key`. | Указать корректные директивы `proxy_ssl_certificate` и `proxy_ssl_certificate_key`, выставить `chmod 640` владельцу `root:nginx`. |
| `certificate revoked` | Сертификат бэкенда отозван и числится в файле `proxy_ssl_crl`. | Проверить серийный номер сертификата: `openssl crl -in /etc/ssl/crl/revoked.crl -text -noout`. | Выпустить новый валидный сертификат для узла бэкенда. |

---

## Рекомендации и лучшие практики (Production & SRE)

1. **Никогда не оставляйте `proxy_ssl_verify off;` в продакшене:** Выключение проверки превращает TLS в фикцию, защищающую лишь от пассивного прослушивания, но уязвимую к активным атакам и спуфингу во внутренней сети.
2. **Всегда включайте `proxy_ssl_server_name on;`:** Это предотвращает 90% инцидентов с несовпадением сертификатов при миграциях бэкендов в Kubernetes, облака или виртуальные хосты.
3. **Используйте `keepalive` в связке с `proxy_ssl_session_reuse on;`:** Удержание постоянных соединений к апстримам снижает CPU-нагрузку обоих узлов и устраняет задержки повторного асимметричного рукопожатия.
4. **Контролируйте глубину цепочки (`proxy_ssl_verify_depth`):** Значение по умолчанию `1` проверяет только сертификаты, подписанные напрямую корневым CA. Если в корпоративной сети используется промежуточный центр сертификации (Issuing CA), установите значение `2` или `3`.
5. **Централизованно обновляйте бандл `proxy_ssl_trusted_certificate`:** Синхронизируйте доверенные CA через инструменты управления конфигурацией (Ansible, Puppet, SaltStack) до плановой ротации корневых ключей.

---

## Дополнительная информация

### Связанные темы в базе знаний

- [Клиентский mTLS в Nginx](nginx_mtls_configuration.md) — взаимная аутентификация входящих клиентских соединений.
- [Глобальные параметры TLS/SSL в Nginx](nginx_tls_global_parameters.md) — настройка протоколов, шифров и ротации сессионных тикетов.
- [Диагностика TLS/SSL и совместимость клиентов](nginx_tls_troubleshooting_and_compatibility.md) — утилиты проверки сертификатов и траблшутинг рукопожатий.
- [Ядро Reverse Proxy в Nginx](../Proxy/nginx_reverse_proxy_core.md) — базовые директивы проксирования, буферизация и тайм-ауты.
- [Практическая конфигурация балансировки](../Proxy/Load_Balancing/practical_configuration.md) — настройка пулов апстримов и мониторинг состояния.

### Официальная документация

- [Модуль ngx_http_proxy_module (директивы proxy_ssl_*)](https://nginx.org/en/docs/http/ngx_http_proxy_module.html)
- [OpenSSL: проверка цепочек сертификатов (s_client, verify)](https://docs.openssl.org/master/man1/openssl-s_client/)

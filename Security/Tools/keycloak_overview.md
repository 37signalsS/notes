# Keycloak

**Актуально для:** Keycloak 26.x

## Определения

**Keycloak** — open-source система управления идентификацией и доступом (Identity and Access Management, IAM). Обеспечивает централизованную аутентификацию, авторизацию, федерацию пользователей и единый вход (SSO) для веб-приложений, микросервисов и инфраструктурных сервисов. Разрабатывается Red Hat, базируется на Quarkus (начиная с версии 17). Поддерживает OIDC, OAuth 2.0, SAML 2.0 и SCIM 2.0.

**Realm** — изолированный логический домен внутри Keycloak. Каждый Realm имеет собственный набор пользователей, ролей, клиентов, политик безопасности и поставщиков идентичности. Realm можно рассматривать как тенант.

**Client (клиент)** — сущность, которая запрашивает аутентификацию у Keycloak. Типы: `confidential` (серверные приложения, хранящие секрет), `public` (SPA, мобильные приложения, без секрета), `bearer-only` (только принимает токены, без входа).

**Client Scope** — набор стандартных или кастомных `claims`, протокольных сопоставлений и настроек, которые наследуются клиентами для исключения дублирования конфигурации.

**User Federation (Федерация пользователей)** — механизм интеграции с внешними каталогами (LDAP, AD). Подробности: [Keycloak LDAP Federation](./keycloak_ldap_federation.md).

**Identity Provider (IdP)** — внешний провайдер аутентификации, которому Keycloak делегирует вход пользователя (Identity Brokering).

**Authorization Services** — механизм тонкой авторизации на основе ресурсов, областей (scopes), политик и разрешений (permissions).

---

## Основные концепции

### Аутентификация и Авторизация (AuthN/AuthZ)

Keycloak разделяет зоны ответственности:
- **Аутентификация (Authentication, AuthN):** Процесс подтверждения личности (кто это?). Поддерживает пароли, OTP, Passkeys (FIDO2), WebAuthn и внешние IdP.
- **Авторизация (Authorization, AuthZ):** Управление доступом к ресурсам (что разрешено?). Включает ролевую модель (RBAC) и атрибутивную модель (ABAC) через Authorization Services.

### Поддерживаемые протоколы и стандарты

| Протокол / Стандарт | Описание |
| :--- | :--- |
| **OpenID Connect (OIDC)** | Слой идентификации поверх OAuth 2.0, стандарт для современных приложений. |
| **OAuth 2.0** | Фреймворк авторизации (access, refresh и ID токены). |
| **SAML 2.0** | Протокол для Enterprise-интеграций (XML-based). |
| **SCIM 2.0** | Стандарт для автоматизированного управления пользователями (provisioning). |
| **SSF (Shared Signals Framework)** | Экспериментальная функция Keycloak (`--features=ssf`, включается с 26.x). Реализует роль Transmitter для передачи сигналов безопасности (Security Event Tokens, SET) по RFC 8417/8935/8936. Поддерживает профили CAEP и RISC. |

### Типы клиентов и потоки

- **Authorization Code Flow:** Основной поток для confidential клиентов с PKCE.
- **Implicit Flow:** Устаревший, не рекомендуется.
- **Client Credentials Flow:** Для service-to-service коммуникации (machine users).
- **Direct Access Grants (Resource Owner Password):** Для legacy-систем, требует включения явно.

### Аналоги и альтернативы

| Решение | Отличия от Keycloak |
| :--- | :--- |
| **Authentik** | Более легкий IdP на Python, популярный в self-hosted сообществе. |
| **Zitadel** | Ориентирован на multi-tenancy и облачную нативность, написан на Go. |
| **Authelia** | Компактный портал аутентификации, часто используется с Nginx/Traefik. |
| **Okta / Auth0** | Коммерческие SaaS-решения (вендор-лок, но минимум обслуживания). |

---

## Архитектура и компоненты

### Ключевые компоненты

- **User Federation:** Интеграция с внешними каталогами (LDAP, AD). Подробности: [Keycloak LDAP Federation](./keycloak_ldap_federation.md).
- **Identity Brokering:** Делегирование входа внешним провайдерам (Google, GitHub, корпоративные IdP).
- **Client Scopes:** Определение набора атрибутов (claims), передаваемых в токенах.
- **Authorization Services:** Тонкая настройка политик доступа (ресурсы, области, разрешения).
- **Event Listener SPI:** Позволяет перехватывать события аутентификации, входов и управления пользователями для внешних систем аудита.
- **User Storage SPI:** Механизм кастомных поставщиков пользователей (пользовательские базы, NoSQL).

### Режимы развёртывания

1. **Stateless Mode (`--features=stateless`, Keycloak 26.7+):** Поддерживается (promoted из preview в supported начиная с 26.8). Сессии, action tokens и brute-force counters хранятся в базе данных вместо Infinispan/JGroups, что упрощает горизонтальное масштабирование и multi-cluster развёртывания без внешнего кеша. Требует `--cache-embedded-cluster-name` (уникальное значение на каждый cluster).
2. **Cluster Mode (Legacy):** Использование встроенного Infinispan для репликации сессий в памяти. Требует настройки JGroups (UDP/TCP). Фича `multi-site` (multi-cluster v1) устарела (deprecated), рекомендуется миграция на `stateless`.
3. **Quarkus Runtime:** Современная база (вместо WildFly). Быстрый запуск (cold start ~2 сек). Базовое потребление памяти — около 1250 MiB для 10 000 сессий; 70% от лимита контейнера выделяется под heap.

### Конфигурация и запуск (Quarkus)

В современных версиях управление осуществляется через утилиту `kc.sh` (или `kc.bat` для Windows).

- **Сборка (Build):** Оптимизация образа под конкретные настройки (БД, функции, метрики).
  ```bash
  ./kc.sh build --db=postgres --metrics-enabled=true
  ```
- **Запуск в продакшн:**
  ```bash
  ./kc.sh start --optimized --hostname=auth.example.com --proxy-headers=xforwarded
  ```
- **Режим разработки:**
  ```bash
  ./kc.sh start-dev
  ```
- **Перечень ключевых опций `start`:**
  - `--hostname`: внешнее имя хоста (полный URL или hostname). Обязательно для production.
  - `--hostname-strict`: отключает динамическое разрешение hostname из заголовков запросов (по умолчанию `true`). Устанавливайте `false` только для тестовых сред.
  - `--proxy-headers`: источник заголовков X-Forwarded-* от reverse proxy (`forwarded` или `xforwarded`). Критично при TLS-termination.
  - `--http-enabled`: включение HTTP-порта (только за балансировщиком с TLS-termination).
  - `--https-port`: кастомный порт HTTPS (по умолчанию `8443`).
  - `--db`: драйвер БД (`postgres`, `mysql`, `mariadb`, `mssql`, `oracle`, `tidb`). Для dev: `dev-file`, `dev-mem`.
  - `--http-management-port`: порт управления (по умолчанию `9000`); эндпоинты `/health`, `/metrics`, `/info`.

---

## Управление жизненным циклом

### Экспорт и импорт Realm

Keycloak поддерживает перенос конфигурации Realm через JSON-файлы.

**Экспорт:**
```bash
/opt/keycloak/bin/kc.sh export \
  --dir /backup/keycloak \
  --realm internal \
  --users realm_file
```
- `--realm`: имя экспортируемого Realm.
- `--users`: стратегия экспорта пользователей (`realm_file` — вместе с Realm, `skip` — без пользователей, `different_files`/`same_file` — в отдельные файлы).
- `--users realm_file` в production без необходимости сохранять пароли в plaintext не рекомендуется; предпочтительнее `--users skip` и отдельный механизм резервного копирования БД.

**Импорт:**
```bash
/opt/keycloak/bin/kc.sh import \
  --dir /backup/keycloak
```
Импорт требует остановки инстанса. Используйте `--override false` для сохранения существующих Realm или `--override true` (по умолчанию) для перезаписи.

### Обновление версий

1. **Проверка совместимости:** Изучить release notes и notes on migration guide для целевой версии.
2. **Бэкап:** Экспорт всех Realm и дамп БД.
3. **Сборка:** Пересобрать образ с новой версией и драйвером БД.
   ```bash
   ./kc.sh build --db=postgres --metrics-enabled=true
   ```
4. **Миграция БД:** Keycloak выполняет автоматическую миграцию схемы при первом запуске. Для production рекомендуется использовать инструменты миграции БД (Liquibase/Flyway) вручную для контроля версий.
5. **Валидация:** Проверка `/health/ready` и `/metrics` после запуска (на порту управления `9000`).

---

## Безопасность и жёсткая настройка

### Политика паролей и защита от брутфорса

- **Brute Force Detection:** Включите в **Realm Settings → Security Defenses → Brute Force Detection**. Начиная с Keycloak 26.8, данные о неудачных логинах хранятся в базе данных по умолчанию (фича `login-failures:v2`), что сохраняет блокировки пользователей даже после перезапуска кластера. Настройте:
  - `Maximum Login Failures`: 5–10 попыток.
  - `Quick Login Check Milli Seconds`: 1000–5000 мс (задержка между попытками).
  - `Wait Increment Milliseconds`: 1000 мс.
  - Для восстановления прежнего in-memory поведения: `--features=login-failures:v1` (устарело, несовместимо с `stateless`).
- **Password Policy:** Настройте в **Realm Settings → Authentication → Password Policy**:
  - `Length` (мин. 12 символов).
  - `Digits` и `Special Characters`.
  - `Password History` (запрет повторного использования последних N паролей).
  - `Expiration` (ротация раз в 90 дней для админов).

### Управление сессиями

- **Access Token Lifespan:** 5–15 минут для production.
- **Refresh Token Lifespan:** 1–12 часов в зависимости от сценария.
- **SSO Session Idle:** 4–8 часов.
- **SSO Session Max:** 12–24 часа.
- **Revoke Refresh Token:** Включите для принудительной ротации.

### Защита административного доступа

- **Separate Admin Realm:** Не используйте `master` Realm для обычных пользователей. Создайте отдельный Realm для администраторов.
- **MFA для админов:** Обязательный TOTP или WebAuthn (Passkeys) для всех аккаунтов с ролью `admin`.
- **Только VPN/ bastion:** Разместите Keycloak в закрытом контуре, доступном только через корпоративный VPN или jump-сервер.

### Ограничение доступа по сети

- **Firewall / NetworkPolicy:** Разрешите порт 8080 (или 8443) только сервисам, которым нужна аутентификация. Порт управления (`9000`) — только для health checks и метрик (внутренний доступ).
- **Admin Console:** Доступ к `/admin` строго через VPN или защищённый reverse proxy с IP-allowlist.

### Content Security Policy

При размещении Admin Console за reverse proxy настройте CSP-заголовки для предотвращения XSS и injection:
```
Content-Security-Policy: default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline';
```

---

## Обратный прокси и TLS

Keycloak не должен быть доступен напрямую из интернета без reverse proxy, выполняющего TLS-termination.

Keycloak запускается с `--proxy-headers=xforwarded` для корректной работы за reverse proxy с TLS-termination:
```bash
./kc.sh start --optimized --hostname=auth.example.com --proxy-headers=xforwarded --http-enabled=true
```

### Nginx

```nginx
server {
    listen 443 ssl http2;
    server_name auth.example.com;

    ssl_certificate     /etc/nginx/ssl/auth.example.com.crt;
    ssl_certificate_key /etc/nginx/ssl/auth.example.com.key;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;

    client_max_body_size 10M;

    location / {
        proxy_pass http://keycloak.internal:8080;
        proxy_set_header Host              $host;
        proxy_set_header X-Forwarded-For   $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host  $host;

        # WebSocket для Realms с административными событиями
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }

    # Health checks на управляемом порту (по умолчанию 9000)
    location /health {
        proxy_pass http://keycloak.internal:9000/health;
        allow 10.0.0.0/8;
        deny all;
    }
}
```

### Traefik

```yaml
http:
  routers:
    keycloak:
      rule: Host(`auth.example.com`)
      service: keycloak
      tls:
        certResolver: myresolver
      middlewares:
        - keycloak-headers
  middlewares:
    keycloak-headers:
      forwardedHeaders:
        trustForwardHeader: true
  services:
    keycloak:
      loadBalancer:
        servers:
          - url: http://keycloak.internal:8080
```

### Apache httpd

```apache
<VirtualHost *:443>
    ServerName auth.example.com

    SSLEngine on
    SSLCertificateFile    /etc/httpd/ssl/auth.example.com.crt
    SSLCertificateKeyFile /etc/httpd/ssl/auth.example.com.key

    ProxyPreserveHost On
    ProxyPass / http://keycloak.internal:8080/
    ProxyPassReverse / http://keycloak.internal:8080/
    RequestHeader set X-Forwarded-Proto "https"
    RequestHeader set X-Forwarded-Port "443"
</VirtualHost>
```

### Примечания по TLS

- В production terminate TLS на reverse proxy: `--http-enabled=true` и `--proxy-headers=xforwarded` на Keycloak.
- Для `kc.sh start --optimized` порт по умолчанию — 8080 (HTTP). Если требуется HTTPS на стороне Keycloak, используйте `--https-port`, `https-key-store-file` и связанные опции.
- `--hostname-strict=false` только для тестовых сред; в production используйте точное имя хоста.

---

## Резервное копирование и восстановление

### Экспорт Realm

```bash
# Экспорт конфигурации Realm с пользователями
/opt/keycloak/bin/kc.sh export \
  --dir /backup/keycloak \
  --realm internal \
  --users realm_file

# Экспорт без пользователей (только конфигурация Realm)
/opt/keycloak/bin/kc.sh export \
  --dir /backup/keycloak \
  --realm internal \
  --users skip
```

### Импорт Realm

```bash
# Импорт Realm из директории (перезапись по умолчанию)
/opt/keycloak/bin/kc.sh import --dir /backup/keycloak

# Импорт без перезаписи существующего Realm
/opt/keycloak/bin/kc.sh import --dir /backup/keycloak --override false
```

### Бэкап базы данных

Keycloak хранит все данные в БД (PostgreSQL recommended). Резервное копирование самой БД — основной способ защиты от катастроф.

**PostgreSQL (pg_dump):**
```bash
pg_dump -U keycloak -h postgres.internal keycloak \
  -F c -f /backup/keycloak-db-$(date +%Y%m%d).dump
```

**PostgreSQL (continuous archiving + WAL):**
Для PITR (Point-in-Time Recovery) включите `archive_mode = on` и настройте `archive_command`.

### Восстановление после сбоя

1. Остановка Keycloak.
2. Восстановление БД из дампа.
3. Импорт актуальных Realm-файлов (если дамп устарел).
4. Запуск Keycloak с той же версией, что и до сбоя.
5. Проверка `KC_DB_URL_HOST`, `KC_DB_USERNAME`, `KC_DB_PASSWORD`.
6. Валидация через `/health/ready` (порт `9000`) и проверка входа администратора.

### Автоматизация бэкапов

- **Cron:** Ежедневный дамп БД и экспорт Realm через cron.
- **Velero / Kanister:** Для Kubernetes — snapshot PVC и ресурсов Keycloak.
- **Версионирование:** Храните бэкапы с временными метками и ротацией (например, 7 дней).

---

## Мониторинг, журналирование и аудит

### Метрики Prometheus

Метрики включаются на этапе сборки флагом `--metrics-enabled=true` и доступны на управляемом интерфейсе (порт по умолчанию `9000`) по пути `/metrics`:
```bash
curl -s http://localhost:9000/metrics
```

Ключевые метрики:
- `keycloak_login_protocol_success_total` / `failure_total`: успешные и неуспешные входы.
- `keycloak_active_sessions`: количество активных сессий.
- `jvm_memory_used_bytes`: потребление памяти JVM.
- `process_cpu_seconds_total`: нагрузка на CPU.
- `hikaricp_connections_active` / `idle`: пул соединений к БД.

### Health Checks

Эндпоинты доступны на управляемом интерфейсе (порт по умолчанию `9000`):

| Эндпоинт | Назначение |
| :--- | :--- |
| `/health/live` | Проверка работоспособности процесса (liveness). |
| `/health/ready` | Проверка готовности принимать трафик (readiness — БД, сеть). |

### Журналирование

Keycloak (Quarkus) выводит логи в stdout/stderr. Через systemd это попадает в `journald`. Для структурированных логов используйте:
- **JSON (structured):** `quarkus.log.console.json=true` — для ELK/Loki.
- **Syslog:** Перенаправление stdout/stderr в удалённый syslog-сервер (Rsyslog, Graylog).
- **File:** Включение файлового логирования через `quarkus.log.file.enable=true` с ротацией внутри Quarkus.

**Пример `keycloak.conf` (conf/keycloak.conf):**
```properties
quarkus.log.console.json=true
quarkus.log.console.json.pretty-print=false
quarkus.log.category."org.keycloak".level=INFO
quarkus.log.category."org.infinispan".level=WARN

# Файловое логирование с ротацией
quarkus.log.file.enable=true
quarkus.log.file.dir=/var/log/keycloak
quarkus.log.file.log-rotate.max-file-size=10M
quarkus.log.file.log-rotate.max-backup-index=5
```

### События и аудит

Keycloak генерирует события для:
- `LOGIN` / `LOGOUT`
- `REGISTER`
- `UPDATE_PASSWORD`
- `UPDATE_EMAIL`
- `ADMIN` (изменения через Admin Console / Admin API)

Для экспорта событий используйте:
- **Event Listener SPI** (кастомный listener в виде JAR).
- **SYSLOG** listener (встроенный).
- **RabbitMQ / Kafka** (через кастомный SPI).

Метрики событий (на порту управления `9000`):
- `keycloak_user_events_total{realm, event, error}`: счетчик событий пользователей (LOGIN, REGISTER, UPDATE_PASSWORD и др.).

---

## Производительность и масштабирование

### Рекомендации по ресурсам (on-prem)

| Компонент | Минимум | Рекомендуется (production) |
| :--- | :--- | :--- |
| **CPU** | 2 cores | 4+ cores |
| **RAM** | 1250 MiB (база: Realm cache + 10 тыс. сессий) | 2–4 GiB+ (масштаб зависит от нагрузки) |
| **Диск** | 10 GiB SSD | 50+ GiB SSD (для БД и логов) |
| **Сеть** | 1 Gbps | 10 Gbps (между Keycloak и БД) |

### Пул соединений к БД

Для настройки пула соединений используйте first-class опции Keycloak (по умолчанию HikariCP через Quarkus):
```properties
# keycloak.conf
db-pool-max-size=50
db-pool-min-size=10
db-pool-initial-size=10
```
Увеличивайте размер пула при высокой частоте запросов (WebAuthn, LDAP federation). Максимум — 100 по умолчанию.

### Кэширование

- **Режимы кэша:** `--cache=local` (локальный, без кластеризации — для dev/test) или `--cache=ispn` (встроенный Infinispan с кластеризацией — для production). При `--features=stateless` volatile данные (сессии, action tokens) сохраняются в БД, Infinispan используется только как локальный кеш с инвалидацией.
- **Static Cache:** Кэширование JWKS и OpenID-configuration через reverse proxy (Nginx `proxy_cache` или CDN).

### Горизонтальное масштабирование

В **Stateless Mode** разворачивайте несколько инстансов за балансировщиком (L4/L7). Убедитесь, что:
- Все инстансы указывают на одну и ту же БД.
- `--hostname` (или `KC_HOSTNAME`) идентичен для всех инстансов.
- Сессии не хранятся в локальной памяти (Infinispan отключён, volatile данные в БД).

---

## Эксплуатация на Linux

### Systemd-сервис

Создайте unit-файл для управления Keycloak как системной службой:

```ini
[Unit]
Description=Keycloak Identity Provider
After=network.target postgresql.service
Wants=postgresql.service

[Service]
Type=simple
User=keycloak
Group=keycloak
ExecStart=/opt/keycloak/bin/kc.sh start --optimized --hostname=auth.example.com --proxy-headers=xforwarded
ExecStop=/opt/keycloak/bin/kc.sh stop
Restart=on-failure
RestartSec=10
LimitNOFILE=10240
Environment=KEYCLOAK_ADMIN=admin
Environment=KEYCLOAK_ADMIN_PASSWORD_FILE=/etc/keycloak/admin.password

[Install]
WantedBy=multi-user.target
```

Пароль администратора храните в файле с правами `600`:
```bash
echo "change-me" > /etc/keycloak/admin.password
chmod 600 /etc/keycloak/admin.password
```

### Ротация логов

Если используется файловое логирование (см. `quarkus.log.file.dir` в секции Журналирование), ротация через `logrotate`:
```bash
# /etc/logrotate.d/keycloak
/var/log/keycloak/*.log {
    daily
    rotate 30
    compress
    missingok
    notifempty
    copytruncate
    delaycompress
}
```
В systemd-развёртывании по умолчанию логи идут в `journald` (`journalctl -u keycloak -f`), отдельный logrotate не требуется.

### Интеграция с Vault

Не храните `KEYCLOAK_ADMIN_PASSWORD` и `KC_DB_PASSWORD` в plaintext. Используйте:
- **Vault Agent Injector** (Kubernetes) — sidecar с сертификатами и секретами.
- **Systemd `EnvironmentFile`** с защищёнными правами (on-prem VM).
- **SOPS + AGE** — шифрование секретов в репозитории с автоматической дешифровкой на целевом хосте.

---

## Устранение неполадок

### Типичные ошибки

| Симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **500 Internal Server Error при логине** | Невалидный issuer URL или JWKS | `curl -v http://localhost:8080/realms/<realm>` | Проверить `KC_HOSTNAME` и `KC_HOSTNAME_STRICT` |
| **504 Gateway Timeout** | Таймаут на WebAuthn или LDAP | Логи Keycloak + tcpdump | Увеличить `proxy_read_timeout` на Nginx; проверить доступность LDAP |
| **OutOfMemoryError** | Недостаточно heap для сессий | `jmap -histo <pid>` | Увеличить `-Xmx` (например, до 2g); перейти на Stateless Mode |
| **Locked account** | Brute Force Detection сработал | `journalctl -u keycloak -f` (или файл `quarkus.log`) | Разблокировать через Admin API: `POST /admin/realms/<realm>/users/{id}/unlock` |
| **Login loop (SAML)** | Несовпадение `Entity ID` или `ACS URL` | Логи браузера + метаданные IdP/SP | Сверить `Entity ID` на стороне Keycloak и SAML-клиента |
| **DB connection pool exhaustion** | Слишком много одновременных запросов | Метрики `hikaricp_connections_active` | Увеличить `--db-pool-max-size`; оптимизировать запросы |
| **Token expired сразу после выдачи** | Часовой пояс сервера | `date` на хосте Keycloak | Синхронизировать время через NTP (`chrony` или `systemd-timesyncd`) |

### Диагностические команды

```bash
# Статус сервиса
systemctl status keycloak

# Логи в реальном времени
journalctl -u keycloak -f

# Проверка открытых портов (8080 — приложение, 9000 — управление)
ss -tlnp | grep -E '8080|9000'

# Проверка пула соединений к БД (на управляемом порту 9000)
curl -s http://localhost:9000/metrics | grep -E 'hikaricp|agroal'

# Разблокировка пользователя (Admin API)
TOKEN=$(curl -s -d "client_id=admin-cli" \
  -d "username=admin" \
  -d "password=change-me" \
  "http://localhost:8080/realms/master/protocol/openid-connect/token" | jq -r .access_token)

curl -X POST "http://localhost:8080/admin/realms/internal/users/{user-id}/unlock" \
  -H "Authorization: Bearer $TOKEN"
```

---

## Практические сценарии

### Единый вход (SSO)

Реализация Single Sign-On позволяет пользователю один раз пройти аутентификацию в Keycloak и получить доступ ко всем подключенным приложениям без повторного ввода учетных данных. При выходе из одного приложения пользователь разлогинивается из всех (Single Logout, SLO).

### Защита API и Микросервисов

Использование Keycloak как центра сертификации токенов. Сервисы проверяют подпись JWT токена (через публичный ключ IdP), не обращаясь к Keycloak при каждом запросе. Для introspection используйте `/protocol/openid-connect/token/introspect`.

### Интеграция с Grafana

Grafana поддерживает OIDC, SAML и аутентификацию через прокси. Для OIDC:
1. В Keycloak создайте Client с типом `confidential`.
2. Включите `Standard Flow Enabled`.
3. В Grafana укажите `auth.generic_oauth` или `auth.openid` параметры.

### Интеграция с SaltStack / Ansible

Keycloak может выступать OAuth2-провайдером для Salt-API или Ansible Automation Platform. Для SaltStack настройте `providers` в `master` с `issuer_url` и `jwks_url` Keycloak.

### Защита привилегированного доступа (SSPR)

Настройка Self-Service Password Reset (SSPR) в Keycloak позволяет пользователям восстанавливать пароли через email или SMS без участия администратора. Включите в **Realm Settings → Login → Forgot Password**.

---

## Дополнительная информация

### Рекомендуемые практики

1. **База данных:** Использовать PostgreSQL, MySQL, MariaDB, MSSQL или Oracle. H2 — только для тестирования.
2. **Безопасность:**
   - Включение **Brute Force Detection** в настройках Realm.
   - Использование **Passkeys** вместо классических паролей для критических систем.
   - Настройка короткого времени жизни Access Token (5–15 минут).
3. **Наблюдаемость:** Использование встроенного экспортера **OpenTelemetry** для сбора трасс (traces) и метрик.
4. **Аудит:** Включите запись событий `ADMIN` и `LOGIN` для критических Realm.
5. **Изоляция:** Для разных сред (dev/staging/prod) используйте отдельные Realm или инстансы.

### Мониторинг и наблюдаемость

Keycloak предоставляет:
- **Метрики:** `/metrics` в формате OpenMetrics/Prometheus (на управляемом порту `9000`, включают `--metrics-enabled=true` при сборке).
- **Health Checks:** `/health/live` и `/health/ready` (на управляемом порту `9000`).
- **Журналирование:** Структурированные логи в формате JSON для интеграции с ELK/Loki.

### Лицензирование

Keycloak распространяется под лицензией **Apache 2.0**. Ранние версии (до Quarkus, < 17) также использовали Apache 2.0. Для коммерческого использования на условиях поддержки Red Hat доступна подписка на Red Hat build of Keycloak.

### См. также

- [Keycloak — LDAP Federation](./keycloak_ldap_federation.md) — детальная настройка интеграции с LDAP.
- [OAuth2 Overview](../Concepts/oauth2_overview.md) — основы протоколов OAuth 2.0 и OIDC.
- [Authentication in Kubernetes](../../Kubernetes/Security/authentication.md) — интеграция с API-сервером K8s.

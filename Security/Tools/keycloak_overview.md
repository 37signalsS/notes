# Keycloak

## Определения

**Keycloak** — open-source система управления идентификацией и доступом (Identity and Access Management, IAM). Обеспечивает централизованную аутентификацию, авторизацию, федерацию пользователей и единый вход (SSO) для веб-приложений, микросервисов и инфраструктурных сервисов. Разрабатывается Red Hat, базируется на Quarkus (начиная с версии 17). Поддерживает OIDC, OAuth 2.0, SAML 2.0 и SCIM 2.0.

**Realm** — изолированный логический домен внутри Keycloak. Каждый Realm имеет собственный набор пользователей, ролей, клиентов, политик безопасности и поставщиков идентичности. Realm можно рассматривать как тенант.

**Client (клиент)** — сущность, которая запрашивает аутентификацию у Keycloak. Типы: `confidential` (серверные приложения, хранящие секрет), `public` (SPA, мобильные приложения, без секрета), `bearer-only` (только принимает токены, без входа).

**Client Scope** — набор стандартных или кастомных `claims`, протокольных сопоставлений и настроек, которые наследуются клиентами для исключения дублирования конфигурации.

**User Federation (Федерация пользователей)** — механизм интеграции с внешними каталогами (LDAP, AD). Подробности: [Keycloak LDAP Federation](./keycloak_ldap_federation.md).

**Identity Provider (IdP)** — внешний провайдер аутентификации, которому Keycloak делегирует вход пользователя (Identity Brokering).

**Authorization Services** — механизм тонкой авторизации на основе ресурсов, областей (scopes), политик и разрешений (permissions).

**ID-JAG (Identity Assertion)** — механизм передачи личности пользователя внешним системам (включая ИИ-агентов) с сохранением контекста авторизации.

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
| **MCP (Model Context Protocol)** | (v26+) Протокол для авторизации ИИ-агентов и обмена контекстом. |
| **SSF (Shared Signals)** | Передача сигналов безопасности между системами в реальном времени. |

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
- **Identity Assertion (ID-JAG):** Механизм передачи личности пользователя ИИ-агентам для безопасного выполнения задач.
- **Event Listener SPI:** Позволяет перехватывать события аутентификации, входов и управлений пользователями для внешних систем аудита.
- **User Storage SPI:** Механизм кастомных поставщиков пользователей (пользовательские базы, NoSQL).

### Режимы развёртывания

1. **Stateless Mode (Keycloak 26+):** Рекомендуемый режим для высоконагруженных сред. Сессии хранятся в базе данных (PostgreSQL), что исключает необходимость в Infinispan/JGroups и упрощает горизонтальное масштабирование за балансировщиком.
2. **Cluster Mode (Legacy):** Использование Infinispan для репликации сессий в памяти. Требует тонкой настройки сетевых протоколов (UDP/TCP Multicast) и стабильного multicast-маршрутизирования между узлами.
3. **Quarkus Runtime:** Современная база (вместо WildFly), обеспечивающая быстрый запуск (cold start < 2 сек) и низкое потребление памяти (от 256 MiB).

### Конфигурация и запуск (Quarkus)

В современных версиях управление осуществляется через утилиту `kc.sh` (или `kc.bat` для Windows).

- **Сборка (Build):** Оптимизация образа под конкретные настройки (БД, функции).
  ```bash
  ./kc.sh build --db=postgres
  ```
- **Запуск в продакшн:**
  ```bash
  ./kc.sh start --optimized --hostname=auth.example.com
  ```
- **Режим разработки:**
  ```bash
  ./kc.sh start-dev
  ```
- **Перечень ключевых опций `start`:**
  - `--hostname`: внешнее имя хоста.
  - `--hostname-strict`: отключение проверки Strict-Transport-Security (только для тестовых сред).
  - `--http-enabled`: включение HTTP-порта (только за балансировщиком с TLS-termination).
  - `--https-port`: кастомный порт HTTPS (по умолчанию 8443 в dev, 8080 в optimized).
  - `--db`: драйвер БД (`postgres`, `mysql`, `mariadb`, `cockroachdb`).

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
- `--users realm_file`: пользователи включаются в JSON-файл (альтернатива `realm_file` — `skip_users`, `realm_db`).
- Включение `--users realm_file` в production без необходимости сохранять пароли в plaintext не рекомендуется; предпочтительнее `skip_users` и отдельный механизм резервного копирования БД.

**Импорт:**
```bash
/opt/keycloak/bin/kc.sh import \
  --dir /backup/keycloak \
  --realm internal.json
```
Импорт требует остановки инстанса или использования `--if-realm-exists skip|overwrite`.

### Обновление версий

1. **Проверка совместимости:** Изучить release notes и notes on migration guide для целевой версии.
2. **Бэкап:** Экспорт всех Realm и дамп БД.
3. **Сборка:** Пересобрать образ с новой версией и драйвером БД.
   ```bash
   ./kc.sh build --db=postgres
   ```
4. **Миграция БД:** Keycloak выполняет автоматическую миграцию схемы при первом запуске. Для production рекомендуется использовать инструменты миграции БД (Liquibase/Flyway) вручную для контроля версий.
5. **Валидация:** Проверка `/health/ready` и `/metrics` после запуска.

---

## Безопасность и жёсткая настройка

### Политика паролей и защита от брутфорса

- **Brute Force Detection:** Включите в **Realm Settings → Security Defenses → Brute Force Detection**. Настройте:
  - `Maximum Login Failures`: 5–10 попыток.
  - `Quick Login Check Milli Seconds`: 1000–5000 мс (задержка между попытками).
  - `Wait Increment Milliseconds`: 1000 мс.
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

- **Firewall / NetworkPolicy:** Разрешите порт 8080 (или 8443) только сервисам, которым нужна аутентификация.
- **Admin Console:** Доступ к `/admin` строго через VPN или защищённый reverse proxy с IP-allowlist.

### Content Security Policy

При размещении Admin Console за reverse proxy настройте CSP-заголовки для предотвращения XSS и injection:
```
Content-Security-Policy: default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline';
```

---

## Обратный прокси и TLS

Keycloak не должен быть доступен напрямую из интернета без reverse proxy, выполняющего TLS-termination.

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

    location /health {
        proxy_pass http://keycloak.internal:8080/health;
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
</VirtualHost>
```

### Примечания по TLS

- В production используйте `--https-port` или `--http-enabled=false` и terminate TLS на reverse proxy.
- Для `kc.sh start --optimized` порт по умолчанию — 8080 (HTTP). Если требуется HTTPS на стороне Keycloak, используйте `https-key-store-file` и связанные опции.
- Настройте `--hostname-strict=false` только для тестовых сред; в production используйте точное имя хоста.

---

## Резервное копирование и восстановление

### Экспорт Realm

```bash
# Экспорт конфигурации Realm (без пользователей)
/opt/keycloak/bin/kc.sh export \
  --dir /backup/keycloak \
  --realm internal \
  --users realm_file

# С пользователями в отдельном файле
/opt/keycloak/bin/kc.sh export \
  --dir /backup/keycloak \
  --realm internal \
  --users realm_file \
  --realm-role-mappings realm_file
```

### Импорт Realm

```bash
/opt/keycloak/bin/kc.sh import \
  --dir /backup/keycloak \
  --realm internal.json \
  --if-realm-exists skip
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
5. Проверка `KC_DB_URL_HOST`, `KC_DB_USER`, `KC_DB_PASSWORD`.
6. Валидация через `/health/ready` и проверка входа администратора.

### Автоматизация бэкапов

- **Cron:** Ежедневный дамп БД и экспорт Realm через cron.
- **Velero / Kanister:** Для Kubernetes — snapshot PVC и ресурсов Keycloak.
- **Версионирование:** Храните бэкапы с временными метками и ротацией (например, 7 дней).

---

## Мониторинг, журналирование и аудит

### Метрики Prometheus

Keycloak экспортирует метрики на `/metrics`:
```bash
curl -s http://localhost:8080/realms/master/metrics | head
```

Ключевые метрики:
- `keycloak_login_protocol_success_total` / `failure_total`: успешные и неуспешные входы.
- `keycloak_active_sessions`: количество активных сессий.
- `jvm_memory_used_bytes`: потребление памяти JVM.
- `process_cpu_seconds_total`: нагрузка на CPU.
- `hikaricp_connections_active` / `idle`: пул соединений к БД.

### Health Checks

| Эндпоинт | Назначение |
| :--- | :--- |
| `/health/live` | Проверка работоспособности процесса (liveness). |
| `/health/ready` | Проверка готовности принимать трафик (readiness — БД, сеть). |

### Журналирование

Keycloak поддерживает несколько форматов и output targets через Quarkus:
- **JSON (structured):** ` quarkus.log.console.json=true` — для ELK/Loki.
- **Syslog:** Перенаправление в удалённый syslog-сервер (например, Rsyslog или Graylog).
- **File:** Ротация через `logrotate` или встроенную ротацию Quarkus (`quarkus.log.console.json`).

**Пример `application.properties`:**
```properties
quarkus.log.console.json=true
quarkus.log.console.json.pretty-print=false
quarkus.log.category."org.keycloak".level=INFO
quarkus.log.category."org.jgroups".level=WARN
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

---

## Производительность и масштабирование

### Рекомендации по ресурсам (on-prem)

| Компонент | Минимум | Рекомендуется (production) |
| :--- | :--- | :--- |
| **CPU** | 2 cores | 4+ cores |
| **RAM** | 1 GiB | 2–4 GiB |
| **Диск** | 10 GiB SSD | 50+ GiB SSD (для БД и логов) |
| **Сеть** | 1 Gbps | 10 Gbps (между Keycloak и БД) |

### Пул соединений к БД

Для PostgreSQL рекомендуется использовать HikariCP (используется Quarkus по умолчанию):
```properties
quarkus.datasource.jdbc.max-size=50
quarkus.datasource.jdbc.min-size=10
quarkus.datasource.jdbc.initial-size=10
```
Увеличивайте размер пула при высокой частоте запросов (WebAuthn, LDAP federation).

### Кэширование

- **Offline Session:** Долгоживущие токены хранятся в БД; контроль `--cache=local` или `--cache=ispn`.
- **Static Cache:** Кэширование JWKS и OpenID-configuration через reverse proxy (Nginx `proxy_cache` или CDN).

### Горизонтальное масштабирование

В **Stateless Mode** разворачивайте несколько инстансов за балансировщиком (L4/L7). Убедитесь, что:
- Все инстансы указывают на одну и ту же БД.
- `kc_hostname` идентичен для всех инстансов.
- Сессии не хранятся в локальной памяти (Infinispan отключён).

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
ExecStart=/opt/keycloak/bin/kc.sh start --optimized --hostname=auth.example.com
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

```bash
# /etc/logrotate.d/keycloak
/opt/keycloak/standalone/log/*.log {
    daily
    rotate 30
    compress
    missingok
    notifempty
    copytruncate
    delaycompress
}
```

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
| **Locked account** | Brute Force Detection сработал | Логи `keycloak-server.log` | Разблокировать через Admin API: `POST /admin/realms/<realm>/users/{id}/unlock` |
| **Login loop (SAML)** | Несовпадение `Entity ID` или `ACS URL` | Логи браузера + метаданные IdP/SP | Сверить `Entity ID` на стороне Keycloak и SAML-клиента |
| **DB connection pool exhaustion** | Слишком много одновременных запросов | Метрики `hikaricp_connections_active` | Увеличить `quarkus.datasource.jdbc.max-size`; оптимизировать запросы |
| **Token expired сразу после выдачи** | Часовой пояс сервера | `date` на хосте Keycloak | Синхронизировать время через NTP (`chrony` или `systemd-timesyncd`) |

### Диагностические команды

```bash
# Статус сервиса
systemctl status keycloak

# Логи в реальном времени
journalctl -u keycloak -f

# Проверка открытых портов
ss -tlnp | grep 8080

# Проверка пула соединений HikariCP
curl -s http://localhost:8080/realms/master/metrics | grep hikaricp

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

1. **База данных:** Использовать PostgreSQL или CockroachDB (для Stateless режима). H2 — только для тестирования.
2. **Безопасность:**
   - Включение **Brute Force Detection** в настройках Realm.
   - Использование **Passkeys** вместо классических паролей для критических систем.
   - Настройка короткого времени жизни Access Token (5–15 минут).
3. **Наблюдаемость:** Использование встроенного экспортера **OpenTelemetry** для сбора трасс (traces) и метрик.
4. **Аудит:** Включите запись событий `ADMIN` и `LOGIN` для критических Realm.
5. **Изоляция:** Для разных сред (dev/staging/prod) используйте отдельные Realm или инстансы.

### Мониторинг и наблюдаемость

Keycloak предоставляет:
- **Метрики:** `/metrics` в формате Prometheus.
- **Health Checks:** `/health/live` и `/health/ready`.
- **Журналирование:** Структурированные логи в формате JSON для интеграции с ELK/Loki.

### Лицензирование

Keycloak распространяется под лицензией **Apache 2.0** (начиная с версии 17). Ранние версии использовали **EPL 2.0**. Для коммерческого использования на условиях поддержки Red Hat доступна подписка на RHEL.

### См. также

- [Keycloak — LDAP Federation](./keycloak_ldap_federation.md) — детальная настройка интеграции с LDAP.
- [OAuth2 Overview](../Concepts/oauth2_overview.md) — основы протоколов OAuth 2.0 и OIDC.
- [Authentication in Kubernetes](../../Kubernetes/Security/authentication.md) — интеграция с API-сервером K8s.

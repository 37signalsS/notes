# Безопасность и жёсткая настройка Grafana

Приведены практические меры защиты самоуправляемой (self-hosted) Grafana. Облачные и ИИ-возможности не рассматриваются. Версии: актуальная — 13.2.x, LTS — 12.4.x, 11.x — EOL (25 июня 2026). Все примеры — для `grafana.ini` (основной конфиг) и обратного прокси; полная настройка прокси вынесена в отдельный документ (см. «Связанные темы»).

## Определения

- **Hardening (жёсткая настройка)** — совокупность мер по снижению поверхности атаки: отключение ненужного, принудительное шифрование, минимизация привилегий.
- **secret_key** — ключ в секции `[security]`; используется для подписи сессионных cookie и шифрования секретов источников данных. Формат шифрования — **AES-256 в режиме CFB**. Должен быть длинным, случайным, постоянным между перезапусками и одинаковым на всех репликах в HA.
- **cookie_secure / cookie_samesite** — атрибуты сессионной cookie Grafana; защищают от перехвата и CSRF. Допустимые значения `cookie_samesite`: `lax`, `strict`, `none`, `disabled` (по умолчанию `lax`).
- **CSP (Content Security Policy)** — заголовок `Content-Security-Policy`, ограничивающий источники загружаемых скриптов и стилей; основной механизм защиты от XSS. Управляется `content_security_policy` и шаблоном `content_security_policy_template`.
- **HSTS (HTTP Strict Transport Security)** — заголовок, заставляющий браузер обращаться только по HTTPS; управляется `strict_transport_security` и связанными параметрами.
- **CSRF (Cross-Site Request Forgery)** — подделка межсайтовых запросов. Grafana защищается токеном; за обратным прокси при внешней аутентификации требуется `csrf_trusted_origins`.
- **SSRF (Server-Side Request Forgery)** — риск при режиме доступа источника данных `Browser` (браузер клиента обращается к источнику напрямую, минуя Grafana) и при неограниченном проксировании URL источников сервером Grafana.
- **Brute-force protection** — встроенная защита от перебора пароля: блокировка входа на 5 минут, если число попыток за 5-минутное окно превышено.
- **disable_gravatar** — отключение загрузки аватаров с внешнего сервиса Gravatar (устраняет утечку email и внешний сетевой вызов).

## Базовые концепции

Защита Grafana строится послойно; пропуск одного слоя не должен обрушивать остальные:

1. **Сеть.** Доступ только через обратный прокси с терминацией TLS; прямой порт 3000 не должен быть публичным. В продакшене Grafana слушает `localhost`, фронтенд — прокси.
2. **Транспорт.** Только HTTPS (HSTS). Mixed content (HTTP-картинки/скрипты) ломает дашборды и плагины.
3. **Аутентификация.** Саморегистрация отключена; вход только через проверенный провайдер (OAuth/LDAP/SAML/JWT) или централизованный auth proxy. Анонимный доступ — только если явно нужен read-only дашборд.
4. **Авторизация.** Пользователям назначены минимально необходимые роли; включены тонкие права на источники данных и папки.
5. **Секреты.** `secret_key` и пароль администратора вынесены в секреты (переменные окружения/файлы), не хранятся в конфиге и репозитории.
6. **Данные.** Ограничен исходящий доступ сервера, отключены внешние вызовы (Gravatar, публикация снимков, телеметрия), задан allowlist проксирования источников.
7. **Наблюдаемость.** Включён журнал аудита (Enterprise) либо централизованный сбор логов и метрик (`/metrics`).

### HTTP-заголовки безопасности

Grafana умеет отдавать защитные заголовки сама, без прокси:

| Заголовок | Управляется | Поведение |
| --- | --- | --- |
| `X-Frame-Options: deny` | `[security] allow_embedding` | По умолчанию `allow_embedding = false` → запрет встраивания (защита от clickjacking). |
| `Content-Security-Policy` | `[security] content_security_policy` | Включается явно (`true`); шаблон — `content_security_policy_template` (в нём `$NONCE` подставляет случайный nonce). Есть режим только отчёта — `content_security_policy_report_only`. |
| `Strict-Transport-Security` | `[security] strict_transport_security` | По умолчанию выключен; включают за TLS-прокси. |
| `X-Content-Type-Options: nosniff` | `[security] x_content_type_options` | Включён по умолчанию (`true`). |
| `X-XSS-Protection` | `[security] x_xss_protection` | Включён по умолчанию (`true`). |

### Сессии, токены и перебор

- Сессия — подписанная cookie (имя по умолчанию `grafana_session`); подпись проверяется через `secret_key`. Срок жизни ограничивается двумя параметрами в `[auth]`: `login_maximum_inactive_lifetime_duration` (по умолчанию `7d`) и `login_maximum_lifetime_duration` (по умолчанию `30d`). Токены ротируются каждые `token_rotation_interval_minutes` (по умолчанию `10`) минут активности.
- Встроенная защита от перебора: `disable_brute_force_login_protection` (по умолчанию `false`) и `brute_force_login_protection_max_attempts` (по умолчанию `5`). При превышении вход блокируется на 5 минут. Отдельно управляются проверка по имени (`disable_username_login_protection`) и по IP-адресу (`disable_ip_address_login_protection`).
- **2FA в Grafana отсутствует.** Второй фактор реализуется на стороне провайдера (OAuth/SAML) или обратного прокси.

### Защита от SSRF

Grafana проксирует запросы к источникам данных (режим `Server`). Чтобы сервер не стал инструментом SSRF, ограничьте, куда ему разрешено ходить:

- `[security] data_source_proxy_whitelist` — allowlist адресов/доменов с портами в формате `<IP>` или `<DOMAIN>:<PORT>` через пробел. Если список пуст, проксирование не ограничено. Ограничение не действует на PostgreSQL, MySQL и MSSQL — они не используют прокси Grafana.
- Сетевой уровень: firewall/egress-политика пускает сервер Grafana только к разрешённым источникам.
- Не используйте режим источника данных `Browser` без необходимости — при нём браузер клиента обращается к источнику напрямую, что раскрывает внутренние адреса.

## Практические сценарии

### Предварительные требования

- Доступ к `grafana.ini` (обычно `/etc/grafana/grafana.ini`) или возможность переопределять значения переменными окружения `GF_<SECTION>_<KEY>`.
- Права перезапуска службы (`systemctl restart grafana-server` или `docker compose restart grafana`).
- Настроенный обратный прокси (см. [Nginx как обратный прокси для Grafana](../WebServers/Nginx/Scenarios/nginx_as_reverse_proxy_for_grafana.md)) с валидным TLS-сертификатом.
- Резервная копия `grafana.ini` и базы перед изменениями.

### Сценарий 1. Базовый хардинг grafana.ini

Минимальный набор для внутреннего контура, опубликованного через прокси по HTTPS.

```ini
[server]
# Канонический внешний URL: обязателен за прокси, иначе cookie, CSRF и редиректы ломаются
root_url = https://grafana.example.internal/
# Не слушать публично, если передача идёт через прокси на той же машине
http_addr = 127.0.0.1
http_port = 3000
protocol = http
# Перенаправлять на правильный домен при несовпадении заголовка Host (защита от DNS rebinding)
enforce_domain = true
# Если TLS терминируется в самой Grafana (protocol = https/h2), ограничиваем протоколы:
# min_tls_version = TLS1.3

[security]
# Сгенерировать: openssl rand -hex 32 ; в проде задать переменной GF_SECURITY_SECRET_KEY
# Шифрование секретов источников данных: AES-256 CFB
secret_key = <сгенерированный-32-байтный-HEX>
disable_gravatar = true
# Cookie только по HTTPS, иначе сессия перехватывается при MITM
cookie_secure = true
# lax совместим с OAuth/SAML; strict ломает сценарии входа, none требует Secure и нужен только для iframe
cookie_samesite = lax
# Запрет встраивания (X-Frame-Options: deny)
allow_embedding = false
# CSP: защита от XSS. При поломке легитимных плагинов расширяйте шаблон, а не отключайте CSP
content_security_policy = true
# HSTS: заставляет браузер всегда ходить по HTTPS
strict_transport_security = true
strict_transport_security_max_age_seconds = 31536000
strict_transport_security_preload = false
strict_transport_security_subdomains = false
# Доверенные источники для CSRF-проверки при внешней аутентификации/обратном прокси
csrf_trusted_origins = https://grafana.example.internal

[users]
# Саморегистрация и создание организаций отключены
allow_sign_up = false
allow_org_create = false
auto_assign_org = true
# Роль по умолчанию для новых пользователей (Viewer по умолчанию и так)
auto_assign_org_role = Viewer

[auth]
# Ограничение времени жизни сессий
login_maximum_inactive_lifetime_duration = 7d
login_maximum_lifetime_duration = 30d
token_rotation_interval_minutes = 10

[auth.anonymous]
enabled = false
```

> `strict_transport_security_max_age_seconds` по умолчанию `86400`; для продакшена обычно поднимают до полугода–года. Значение выше приведено для примера.

Валидация заголовков и cookie:

```bash
curl -sI https://grafana.example.internal/login \
  | grep -iE "strict-transport-security|content-security-policy|x-frame-options|x-content-type-options|set-cookie"
# → strict-transport-security: max-age=31536000
# → content-security-policy: script-src 'self' 'nonce-...'; ...
# → x-frame-options: deny
# → x-content-type-options: nosniff
# → set-cookie: grafana_session=...; Secure; HttpOnly; SameSite=Lax
```

### Сценарий 2. Публикация через обратный прокси

Grafana за прокси отдаёт TLS-терминацию фронтенду, а сама слушает `http_addr = 127.0.0.1`. Ключевое для безопасности — прокси обязан пробрасывать реальный протокол и хост, иначе Grafana генерирует HTTP-ссылки и cookie без `Secure`:

```nginx
location / {
    proxy_pass          http://127.0.0.1:3000;
    proxy_set_header    Host              $host;
    proxy_set_header    X-Real-IP         $remote_addr;
    proxy_set_header    X-Forwarded-For   $proxy_add_x_forwarded_for;
    proxy_set_header    X-Forwarded-Proto $scheme;
    proxy_set_header    X-Forwarded-Port  $server_port;
    proxy_redirect      off;
}
```

Полный сценарий (TLS, sub-path, WebSocket, auth proxy, allowlist, лимиты) — в [Nginx как обратный прокси для Grafana](../WebServers/Nginx/Scenarios/nginx_as_reverse_proxy_for_grafana.md). Общие принципы защиты HTTP/TLS — в [Защита HTTP](../Networking/Protocols/HTTP/http_security_hardening.md).

Без `X-Forwarded-Proto` Grafana считает соединение HTTP и выставляет cookie без `Secure`, а редиректы и ссылки ломаются. При `cookie_samesite = none` обязательны `cookie_secure = true` и корректный `X-Forwarded-Proto`.

### Сценарий 3. Безопасность учётных записей

Отключение неконтролируемого создания аккаунтов:

```ini
[users]
allow_sign_up = false
allow_org_create = false

[auth.anonymous]
enabled = false
```

Защита от перебора и ограничение времени жизни сессий:

```ini
[security]
disable_brute_force_login_protection = false
brute_force_login_protection_max_attempts = 5

[auth]
login_maximum_inactive_lifetime_duration = 7d
login_maximum_lifetime_duration = 30d
```

При первом запуске Grafana создаёт пользователя `admin`/`admin`. В продакшене его пароль задают заранее и больше не оставляют по умолчанию:

```bash
# Пароль admin задаётся при первом старте; храните его в секрете
export GF_SECURITY_ADMIN_PASSWORD="$(openssl rand -base64 24)"
```

Если стандартная учётная запись не нужна, её создание можно отключить (`[security] disable_initial_admin_creation = true`, доступно с Grafana 9.5), но тогда администратора нужно завести декларативно (через provisioned-провайдера или внешний каталог), иначе в управлении не будет администратора.

```ini
[security]
# Не создавать admin/admin при первом старте (нужен заранее настроенный администратор)
disable_initial_admin_creation = true
```

### Сценарий 4. Аутентификация и вход

Хардинг сужает способы входа. Полные процедуры — в SSoT: [Управление пользователями и аутентификация](grafana_user_management_and_authentication.md) (OAuth, LDAP, auth proxy, сервисные аккаунты) и [Enterprise SSO — SAML, JWT, LDAP](grafana_sso_saml_jwt.md).

Что относится именно к харденингу:

- **Скрытие локальной формы входа** при переходе на SSO:

  ```ini
  [auth]
  disable_login_form = true
  signout_redirect_url = https://grafana.example.internal/
  ```

  `disable_login_form = true` опасно при недоступности провайдера — оставьте запасной вход для Grafana Admin (сброс пароля CLI, см. «Очистка и откат»).

- **auth proxy.** Grafana безусловно доверяет заголовку с именем пользователя (`X-WEBAUTH-USER`). Прокси обязан отсекать заголовок, приходящий от клиента, и подставлять его только после успешной аутентификации; иначе личность подделывается:

  ```nginx
  proxy_hide_header X-WEBAUTH-USER;   # запретить клиенту протащить свой заголовок
  ```

  При auth proxy скрывают и меню выхода: `[auth] disable_signout_menu = true`.

- **Отключение HTTP Basic Auth для API** (если он не используется): `[auth.basic] enabled = false`. Базовый вход в UI через логин/пароль при этом сохраняется формой входа.

- **2FA** реализуется на стороне провайдера (OAuth/SAML) или прокси, а не в Grafana.

### Сценарий 5. Защита источников данных от SSRF

Используйте режим доступа `Server` (проксирование через Grafana), а не `Browser`: запросы к источникам идут с сервера Grafana, браузер клиента не видит внутренние адреса. Затем ограничьте, куда серверу Grafana разрешено проксировать запросы:

```ini
[security]
# Allowlist проксирования источников: IP или DOMAIN:PORT через пробел.
# Пустое значение означает отсутствие ограничения.
data_source_proxy_whitelist = 10.0.0.10 prometheus.internal:9090 loki.internal:3100
```

Ограничение не действует на PostgreSQL, MySQL и MSSQL. На сетевом уровне дополнительно ограничьте исходящий доступ сервера Grafana. Общая теория SSRF — в [SSRF](../WebServers/Concepts/ssrf.md); управление правами на источники — в [Управление пользователями](grafana_user_management_and_authentication.md) и [Fine-grained RBAC](grafana_rbac_fine_grained.md).

Секреты источников данных шифруются ключом `secret_key` в БД; при смене `secret_key` ранее сохранённые секреты перестанут расшифровываться (см. [Высокая доступность](high_availability.md)).

### Сценарий 6. Отключение внешних вызовов и утечек

Grafana по умолчанию обращается к внешним сервисам. Для закрытого контура их отключают:

```ini
[security]
disable_gravatar = true

[analytics]
# Не отправлять анонимную статистику на stats.grafana.org
reporting_enabled = false
# Не проверять обновления Grafana и плагинов из интернета
check_for_updates = false
check_for_plugin_updates = false
# Убрать ссылки обратной связи из UI
feedback_links_enabled = false

[snapshots]
# Публикация снимков на внешний сервис (snapshots.raintank.io) выключена
external_enabled = false
# Не разрешать анонимное создание/удаление снимков
public_mode = false
```

Плагины выполняются в браузере; фронтенд-песочницу для плагинов задают списком их ID в `[security] enable_frontend_sandbox_for_plugins`.

### Сценарий 7. Аудит и логирование

Журнал аудита — функция **Grafana Enterprise**:

```ini
[audit_logs]
enabled = true
```

В OSS для контроля доступа используйте уровень логов и централизованный сбор:

```ini
[log]
level = info
mode = console file
# Точечная отладка (включать ненадолго): filters = auth:debug
```

Метрики Grafana (`/metrics`) и логи подаются в сборщик (Promtail/Vector) с ограничением доступа (см. [Устранение неполадок Grafana](grafana_troubleshooting.md)). Признаки перебора — сообщения о неудачной аутентификации в логах и рост соответствующих счётчиков.

### Сценарий 8. Харденинг хоста и процесса (Linux)

Grafana не должна работать от root, а её конфиг с секретами должен быть закрыт от посторонних:

```bash
# Конфиг с secret_key читает только владелец (обычно root или группа grafana)
sudo chown root:grafana /etc/grafana/grafana.ini
sudo chmod 640 /etc/grafana/grafana.ini

# Проверить пользователя службы (по умолчанию — grafana, не root)
systemctl show grafana-server -p User
# → User=grafana
```

Ограничение привилегий процесса через systemd drop-in:

```ini
# /etc/systemd/system/grafana-server.service.d/override.conf
[Service]
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/grafana /var/log/grafana /var/run/grafana
```

```bash
sudo systemctl daemon-reload
sudo systemctl restart grafana-server
```

> Директива `ProtectSystem=strict` делает корневую ФС только для чтения; вынесите в `ReadWritePaths` все каталоги, куда Grafana пишет (данные, логи, плагины). Проверяйте после установки новых плагинов.

На сетевом уровне закройте порт 3000 от всех, кроме прокси: пользуйтесь firewall (nftables/ufw) или bind на `127.0.0.1`.

## Дополнительная информация

### Рекомендации по эксплуатации

- `secret_key` задавайте через `GF_SECURITY_SECRET_KEY` или `$__file{...}`, храните в менеджере секретов (HashiCorp Vault, см. [Vault](../Vault/zero_trust.md)); не коммитьте в `grafana.ini` и репозиторий.
- В HA все реплики должны иметь одинаковый `secret_key`, иначе сессии и расшифровка секретов ломаются при балансировке (см. [Высокая доступность](high_availability.md)).
- Держите `allow_sign_up = false` и анонимный доступ отключённым, пока бизнес не потребует иначе.
- Включите CSP (`content_security_policy = true`); при поломке легитимных плагинов расширяйте `content_security_policy_template`, а не отключайте CSP.
- Ограничьте проксирование источников (`data_source_proxy_whitelist`) и исходящий сетевой доступ сервера Grafana.
- Регулярно обновляйте Grafana — большинство инцидентов связано с устаревшими версиями (см. [Обновление и миграция](grafana_upgrade_migration.md)).
- Выдавайте минимальные роли и используйте сервисные аккаунты вместо широких `Admin`/`Editor`.

### Типичные ошибки и их решение

| Симптом | Причина | Решение |
| --- | --- | --- |
| Дашборды грузятся по HTTP, браузер блокирует mixed content | `root_url` указывает на `http://` или нет `X-Forwarded-Proto` | `root_url = https://...`, проксируйте `X-Forwarded-Proto $scheme` |
| Cookie не ставится, вечный редирект входа | `cookie_secure = true`, но соединение до Grafana — HTTP без `X-Forwarded-Proto` | Проксируйте `X-Forwarded-Proto`; убедитесь, что браузер на HTTPS |
| CSRF-ошибка при сохранении дашборда или входе через IdP | Grafana видит внешний origin, его нет в `csrf_trusted_origins` | Добавьте внешний origin в `csrf_trusted_origins` (при необходимости — `csrf_additional_headers`) |
| После входа через OAuth/SAML бесконечный редирект | `cookie_samesite = strict` | Выставьте `cookie_samesite = lax` |
| Пользователь «исчезает» из Grafana после входа через прокси | Прокси не подставляет заголовок аутентификации | Проверьте заголовок (`X-WEBAUTH-USER`) в логах `auth.proxy: ...`; убедитесь, что клиентский заголовок отсекается |
| Брутфорс не блокируется | Защита отключена или лимит слишком высок | `disable_brute_force_login_protection = false`, снизьте `brute_force_login_protection_max_attempts` |
| Источник данных работает, но не через прокси, либо «блокируется» | `data_source_proxy_whitelist` не содержит адрес (или наоборот) | Дополните allowlist; помните, что PostgreSQL/MySQL/MSSQL прокси не используют |
| После смены `secret_key` источники данных «пустые»/ошибки | Секреты зашифрованы старым ключом | Верните прежний `secret_key` или пересохраните секреты источников |
| Плагин не рендерится, CSP-ошибки в консоли | Жёсткий CSP блокирует скрипт плагина | Дополните `content_security_policy_template`; при необходимости — `enable_frontend_sandbox_for_plugins` |
| Аватары не грузятся / есть внешний сетевой вызов | `disable_gravatar = false` | `disable_gravatar = true` |
| Утечка версии и телеметрия в закрытом контуре | Аналитика и проверки обновлений включены | `reporting_enabled = false`, `check_for_updates = false`, `check_for_plugin_updates = false` |
| Grafana недоступна после `ProtectSystem=strict` | Каталог записи не добавлен в `ReadWritePaths` | Дополните `ReadWritePaths` (данные, логи, плагины), перезапустите |

### Ограничения и особые случаи

- Журнал аудита и envelope encryption (управление ключами) — функции Grafana Enterprise; в OSS используйте экспорт логов и метрик.
- `cookie_samesite = none` технически требует `Secure`; нужен только для легитимного кросс-сайтного встраивания (iframe) и повышает риск. Для OAuth/SAML требуется `lax`.
- Режим `Browser` источника данных обоснован редко (например, когда Grafana не должна иметь сетевого доступа к источнику); в проде предпочтителен `Server`.
- `data_source_proxy_whitelist` не распространяется на PostgreSQL, MySQL и MSSQL.
- `disable_login_form = true` скрывает только локальную форму входа, но не анонимный доступ и не SSO; при недоступности провайдера локальный вход администратора должен оставаться возможным.
- Ограничения `ProtectSystem`/`ReadWritePaths` в systemd могут конфликтовать с плагинами, которым нужна запись в нестандартные пути.
- За обратным прокси Grafana должна доверять заголовкам (`X-Forwarded-*`) — иначе она «видит» всех пользователей под одним IP.

### Очистка и откат изменений

- Перед правкой сохраните `grafana.ini` (например, `grafana.ini.bak`); откат — восстановление бэкапа и перезапуск, затем проверка `/api/health`.
- Отключить метод аутентификации: `enabled = false` в соответствующей секции `[auth.*]`.
- Вернуть стандартную защиту/вход: `disable_brute_force_login_protection = true`, `disable_login_form = false`.
- При недоступности входа после `disable_login_form = true` или утери пароля — сброс через CLI:

  ```bash
  grafana cli admin reset-admin-password <new_password>
  # → Admin password changed successfully
  ```

- Откат systemd-ограничений: удалите drop-in `override.conf`, `systemctl daemon-reload && systemctl restart grafana-server`.
- Отключение внешних вызовов и allowlist можно вернуть к значениям по умолчанию (`reporting_enabled = true`, пустой `data_source_proxy_whitelist`).

### Связанные темы

- [Обзор Grafana](grafana_overview.md) — архитектура, раздел безопасности
- [Управление пользователями и аутентификация](grafana_user_management_and_authentication.md) — OAuth/LDAP/auth proxy, сервисные аккаунты, RBAC
- [Enterprise SSO — SAML, JWT, LDAP](grafana_sso_saml_jwt.md)
- [Fine-grained RBAC](grafana_rbac_fine_grained.md)
- [Высокая доступность и отказоустойчивость](high_availability.md) — синхронизация `secret_key`
- [Источники данных](grafana_datasources.md)
- [Обновление и миграция](grafana_upgrade_migration.md)
- [Устранение неполадок Grafana](grafana_troubleshooting.md)
- [Nginx как обратный прокси для Grafana](../WebServers/Nginx/Scenarios/nginx_as_reverse_proxy_for_grafana.md)
- [Защита HTTP](../Networking/Protocols/HTTP/http_security_hardening.md)
- [SSRF](../WebServers/Concepts/ssrf.md)

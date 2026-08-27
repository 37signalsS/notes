# Безопасность и жёсткая настройка Grafana

Приведены практические меры защиты самоуправляемой (self-hosted) Grafana. Облачные и ИИ-возможности не рассматриваются. Версии: актуальная 13.x, LTS — 12.x, 11.x находится в стадии EOL (июнь 2026). Все примеры — для `grafana.ini` (основной конфиг) и обратного прокси на nginx.

## Определения

- **Hardening (жёсткая настройка)** — совокупность мер по снижению поверхности атаки: отключение ненужного, принудительное шифрование, минимизация привилегий.
- **secret_key** — симметричный ключ в `[security]`; используется для подписи сессий, шифрования секретов источников данных и токенов. Должен быть длинным, случайным, постоянным между перезапусками и одинаковым на всех репликах в HA.
- **cookie_secure / cookie_samesite** — атрибуты сессионной cookie Grafana; защищают от перехвата и CSRF.
- **CSRF (Cross-Site Request Forgery)** — подделка межсайтовых запросов; Grafana защищается токеном, но требует корректных `csrf_trusted_origins` за обратным прокси.
- **SSRF (Server-Side Request Forgery)** — риск при режиме доступа источника данных `Browser`: браузер клиента обращается напрямую к БД/API, минуя Grafana, что раскрывает внутренние адреса и может дать доступ к приватным сетям.
- **disable_gravatar** — отключение загрузки аватаров с внешнего сервиса Gravatar (устраняет утечку email и внешний сетевой вызов).

## Базовые концепции

Защита Grafana строится послойно; пропуск одного слоя не должен обрушивать остальные:

1. **Сеть.** Доступ только через обратный прокси (nginx) с терминацией TLS; прямой порт 3000 не должен быть публичным. В продакшене Grafana слушает `localhost`, фронтенд — nginx.
2. **Транспорт.** Только HTTPS (HSTS). Mixed content (HTTP-картинки/скрипты) ломает дашборды и плагины.
3. **Аутентификация.** Саморегистрация отключена; вход только через проверенный провайдер (OAuth/LDAP/SAML/JWT) или централизованный auth proxy. Анонимный доступ — только если явно нужен read-only дашборд, иначе `enabled = false`.
4. **Авторизация.** RBAC включён, пользователям назначены минимально необходимые роли; включены тонкие права на источники данных/папки/дашборды.
5. **Секреты.** `secret_key` сгенерирован и сохранён вне репозитория (например, через переменную окружения `GF_SECURITY_SECRET_KEY`); секреты источников данных шифруются в БД.
6. **Аудит и мониторинг.** Логи уровня `info`/`warn`, метрики `/metrics` уходят во внешний мониторинг, при наличии Enterprise — журнал аудита.

Ключевые угрозы для self-hosted Grafana: неавторизованный доступ (открытая регистрация/аноним), утечка дашбордов (в них часто — запросы с именами баз/таблиц/метрик), XSS через панели (HTML-панели, непроверенные шаблоны), SSRF через режим `Browser` источника данных, перехват сессии по незащищённой cookie.

## Практические сценарии

### Предварительные требования

- Доступ к `grafana.ini` (обычно `/etc/grafana/grafana.ini`) или возможность переопределять значения переменными окружения `GF_<SECTION>_<KEY>`.
- Права перезапуска службы (`systemctl restart grafana-server` или `docker compose restart grafana`).
- Настроенный обратный прокси (см. связанные темы) с валидным TLS-сертификатом.
- Резервная копия `grafana.ini` и базы перед изменениями.

### Сценарий 1. Базовый хардинг grafana.ini

Минимальный набор для публично недоступного, но внутреннего контура. Правим секции:

```ini
[server]
# Канонический внешний URL — обязателен за прокси, иначе cookie/CSRF и редиректы сломаются
root_url = https://grafana.example.internal/
# Не слушать публично, если передача идёт через nginx на той же машине
http_addr = 127.0.0.1
protocol = http
http_port = 3000
# HSTS: заставляет браузер всегда ходить по HTTPS
strict_transport_security = true
strict_transport_security_max_age_seconds = 86400
strict_transport_security_preload = false
strict_transport_security_subdomains = false

[security]
# Сгенерировать: openssl rand -hex 32 ; задать переменной GF_SECURITY_SECRET_KEY в проде
secret_key = <сгенерированный-32-байтный-HEX>
disable_gravatar = true
# Cookie только по HTTPS, иначе сессия перехватывается при MITM
cookie_secure = true
# none допустимо только при cookie_secure=true и кросс-сайтном встраивании; иначе lax
cookie_samesite = lax
# Блокировать встраивание в чужие сайты (защита от clickjacking)
content_security_policy = true
# Разрешённые origin для CSRF-токена (если Grafana видит внешний host через прокси)
csrf_trusted_origins = https://grafana.example.internal

[users]
# Закрыть публичную регистрацию — критично
allow_sign_up = false
# Куда попадает новый пользователь при первом входе через SSO
auto_assign_org = true
auto_assign_org_role = Viewer

[auth.anonymous]
enabled = false
```

Проверка. После перезапуска состояние здоровья и заголовки:

```bash
curl -sI https://grafana.example.internal/api/health
# → HTTP/2 200
# → strict-transport-security: max-age=86400
# → set-cookie: grafana_session=...; Path=/; HttpOnly; Secure; SameSite=Lax

curl -s https://grafana.example.internal/api/health
# → {"commit":"...","database":"ok","version":"13.1.0","status":"ok"}
```

Если на странице входа нет кнопки «Sign up» — `allow_sign_up` применён. Cookie с флагом `Secure` означает `cookie_secure = true`.

### Сценарий 2. TLS-терминация и редирект на nginx

Grafana за прокси не должна сама терминировать TLS (проще централизовать сертификаты на nginx). Минимальный блок:

```nginx
server {
    listen 80;
    server_name grafana.example.internal;
    # Жёсткий редирект на HTTPS (без исключений для здоровья — /api/health тоже по HTTPS)
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    server_name grafana.example.internal;

    ssl_certificate     /etc/nginx/tls/grafana.crt;
    ssl_certificate_key /etc/nginx/tls/grafana.key;
    ssl_protocols       TLSv1.2 TLSv1.3;

    location / {
        proxy_pass          http://127.0.0.1:3000;
        # Важно: проксируем реальный протокол и host, иначе Grafana генерирует HTTP-ссылки
        proxy_set_header    Host              $host;
        proxy_set_header    X-Real-IP         $remote_addr;
        proxy_set_header    X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header    X-Forwarded-Proto $scheme;
        proxy_set_header    X-Forwarded-Port  $server_port;
        proxy_redirect      off;
    }
}
```

Без `X-Forwarded-Proto` Grafana считает соединение HTTP и выставляет cookie без `Secure`, а редиректы и ссылки ломаются. При `cookie_samesite = none` обязателен `cookie_secure = true` и корректный `X-Forwarded-Proto`.

### Сценарий 3. Принудительный SSO и скрытие формы входа

Чтобы пользователи не могли зайти по локальному паролю (если аккаунты заведены), а попадали сразу в провайдер:

```ini
[auth.generic_oauth]
enabled = true
auto_login = true          # редирект на провайдера при заходе на /

[users]
allow_sign_up = false

[auth]
disable_login_form = false # не скрываем форму полностью, чтобы Grafana Admin мог войти локально при сбое SSO
signout_redirect_url = https://grafana.example.internal/
```

Для полной блокировки локального входа (только SSO) выставляют `disable_login_form = true`, но это опасно при недоступности провайдера — оставьте запасной вход для Grafana Admin через `grafana-cli` сбросом пароля.

### Сценарий 4. Аудит и защита от перебора

Ограничение попыток входа (встроенное):

```ini
[auth]
login_maximum_attempts = 5
login_maximum_inactive_lifetime_days = 7
```

Включение журнала аудита (требуется Grafana Enterprise; в OSS используйте внешнее логирование и метрики `/metrics`):

```ini
[audit_logs]
enabled = true
```

Проверка брутфорса: в логах Grafana появляются `Failed to authenticate user` и временная блокировка; метрика `grafana_login_access_attempt_count` растёт.

### Сценарий 5. Защита источников данных от SSRF и утечки

Используйте режим доступа `Server` (проксирование через Grafana), а не `Browser`: тогда запросы к БД/API идут с сервера Grafana, браузер клиента не видит внутренние адреса, и можно ограничить исходящие соединения на уровне сети.

```ini
[datasources]
# Запретить пользователям создавать источники данных с режимом Browser без контроля
# (управляется правами RBAC: datasources:create)
```

Секреты источников данных шифруются ключом `secret_key` в БД; при смене `secret_key` ранее сохранённые секреты перестанут расшифровываться — делайте смену только с последующим пересохранением секретов.

## Дополнительная информация

### Рекомендации по эксплуатации

- `secret_key` задавайте через `GF_SECURITY_SECRET_KEY`, храните в менеджере секретов; не коммитьте в `grafana.ini`.
- В HA все реплики должны иметь одинаковый `secret_key`, иначе сессии и расшифровка секретов ломаются при балансировке.
- Держите `allow_sign_up = false` и аноним отключённым, пока бизнес не потребует иначе.
- Регулярно обновляйте Grafana (см. связанные темы) — большинство инцидентов связано с устаревшими версиями.
- Ограничьте исходящий сетевой доступ сервера Grafana до списка разрешённых источников данных (защита от SSRF).
- Включите CSP (`content_security_policy = true`); при поломке легитимных плагинов расширьте `content_security_policy_template`, а не отключайте CSP.

### Типичные ошибки и их решение

| Симптом | Причина | Решение |
| --- | --- | --- |
| Дашборды грузятся по HTTP, браузер блокирует mixed content | `root_url` указывает на `http://` или нет `X-Forwarded-Proto` | `root_url = https://...`, проксируйте `X-Forwarded-Proto $scheme` |
| Cookie не ставится, вечный редирект входа | `cookie_secure = true`, но соединение до Grafana — HTTP без `X-Forwarded-Proto` | Проксируйте `X-Forwarded-Proto`, убедитесь, что браузер на HTTPS |
| CSRF-ошибка при сохранении дашборда за прокси | Grafana видит внешний origin, он не в `csrf_trusted_origins` | Добавьте внешний origin в `csrf_trusted_origins` |
| После смены `secret_key` источники данных «пустые»/ошибки | Секреты зашифрованы старым ключом | Верните прежний `secret_key` или пересохраните секреты источников |
| Плагин не рендерится, CSP-ошибки в консоли | Жёсткий CSP блокирует скрипт плагина | Дополните `content_security_policy_template`, не отключайте CSP |
| Аватары не грузятся, утечка email наружу | `disable_gravatar = false` | `disable_gravatar = true` |

### Ограничения и особые случаи

- Журнал аудита — функция Enterprise; в OSS используйте экспорт логов и метрик.
- `cookie_samesite = none` технически требует `Secure`; нужен только для легитимного кросс-сайтного встраивания (iframe) и повышает риск.
- Режим `Browser` источника данных обоснован редко (например, когда Grafana не должна иметь сетевого доступа к БД); в проде предпочтителен `Server`.
- За обратным прокси Grafana должна доверять заголовкам (`X-Forwarded-*`) — иначе она «видит» всех пользователей под одним IP.

### Очистка и откат изменений

- Сохраняйте предыдущий `grafana.ini` (например, `grafana.ini.bak`) перед правкой.
- Откат: восстановите бэкап конфига, перезапустите службу, проверьте `/api/health`.
- При невозможности входа после `disable_login_form = true` — сбросьте пароль Grafana Admin через `grafana-cli admin reset-admin-password <new>` и временно верните `disable_login_form = false`.

### Актуальность и статус

Описанные секции `grafana.ini` стабильны начиная с 8.x и актуальны для 11.x/12.x/13.x. Атрибуты cookie и CSP могут уточняться в release notes при мажорных обновлениях — сверяйтесь перед апгрейдом.

### Связанные темы

- [Обратный прокси и сетевое развёртывание](grafana_overview.md)
- [Аутентификация и управление доступом](grafana_user_management_and_authentication.md)
- [Высокая доступность и отказоустойчивость](high_availability.md)

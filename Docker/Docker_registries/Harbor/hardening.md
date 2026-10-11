# Harbor: Hardening и защита инстанса

**Актуально для:** Harbor 2.15.x

## Определения

* **Hardening**: Сокращение поверхности атаки инстанса Harbor — явная настройка RBAC, TLS, учётных данных и политик. Harbor не защищён «из коробки»: по заявлению SECURITY.md проекта, оператор обязан явно сконфигурировать настройки, RBAC и ресурсные политики — Harbor не реагирует на раскрытия, связанные с отсутствием безопасных дефолтов.
* **Self-registration**: Возможность незарегистрированных пользователей создать учётную запись самостоятельно. По умолчанию **выключена**; включается только в Database-режиме аутентификации.
* **Anonymous access**: Анонимный (неавторизованный) пользователь — read-only доступ к публичным проектам, нет доступа к приватным.
* **Security Officer**: Системная роль Harbor — управление политиками безопасности (отдельно от System Admin).

## Основные концепции

### Конфигурация ключей и шифрования (SRE)

Harbor шифрует чувствительные данные, но использует **один общий ключ** для всех слоёв — это главный SRE-недочёт, который нужно компенсировать вручную.

| Ключ | Где хранится | Что шифрует | Проблема |
| :--- | :--- | :--- | :--- |
| **`secretKey`** (16+ символов) | `harbor.yml` → `keyval` таблица БД / `core.secret` (Helm) | Сессии, токены, `keyval`-записи | По умолчанию `not-a-secure-key` (Helm) — **никогда не используйте дефолт** |
| **`core.secret`** (16 символов) | `core.secret` (Helm) / `harbor.yml` | Токены Registry (upload state) | Отдельный от `secretKey`, но тоже генерируется случайно при отсутствии |
| **`core.xsrfKey`** (32 символа) | `core.xsrfKey` (Helm) | XSRF-токены | Генерируется `randAlphaNum(32)` при отсутствии |
| **`core.tokenKey`** (TLS-пара) | `core.secretName` (K8s Secret) | JWT-токены Registry | Генерируется из `genCA` при отсутствии |

**Ключевое ограничение:** при смене `secretKey` **все существующие зашифрованные данные становятся недоступны** — `keyval` не перешифровывается автоматически. Планируйте ключ как часть жизненного цикла инстанса, а не как runtime-настройку. Ротация = downtime для метаданных.

**Рекомендации:**
- Генерируйте ключи через `openssl rand -base64 32` (для `secretKey` — минимум 16, но 32 предпочтительнее).
- Храните в Secrets-менеджере (Vault, Sealed Secrets, K8s Secret), **не в `harbor.yml` на диске** (см. ниже).
- Для Helm: задавайте `existingSecretSecretKey` вместо `secretKey` в `values.yaml`.
- `chmod 600 harbor.yml` — файл содержит пароли и ключи; не коммитьте в git.

### Модель угроз и исторический пример

**CVE-2019-16097** (Harbor 1.7.0–1.8.2): при включённой self-registration не-admin пользователь мог создать учётку с admin-правами через `POST /api/users` с полем `has_admin_role: true`. Исправлено в 1.7.6/1.8.3. Урок для production:

1. Self-registration — вектор привилегирования, держите выключенной.
2. Дефолтные учётные данные (`admin` / `Harbor12345`) — первое, что меняют при установке.
3. Открытый в интернет инстанс с дефолтами — критический риск (Unit 42 обнаружила ~1300 открытых уязвимых инстансов Harbor).

### Актуальные уязвимости (2024–2025)

Последние релизы Harbor получили несколько CVE, связанных с проверкой прав и раскрытием информации. Все исправлены в patch-релизах; для инстансов ниже указанных версий — обновление **обязательно**:

| CVE | Версии до исправления | Суть | Исправлено |
| :--- | :--- | :--- | :--- |
| **CVE-2024-22278** | < 2.9.5, = 2.10.0–< 2.10.3 | Роль `maintainer` обходила проверку прав при создании/изменении/удалении метаданных проекта через `PUT/POST/DELETE /projects/{id}/metadatas/{name}`. Атакующий с ролью `maintainer` мог менять конфигурацию чужого проекта. Требуется аутентификация, область — только свой проект. | 2.9.5, 2.10.3, 2.11.0 |
| **CVE-2025-30086** | < 2.13.1, < 2.12.4 | ORM Leak в `/api/v2.0/users`: параметр `q` позволял фильтровать по любому столбцу, включая `password_hash`. Администратор мог раскрывать хэши паролей посимвольно через `password=~`. | 2.12.4, 2.13.1 |
| **CVE-2025-32019** | ≤ 2.11.2, ≤ 2.12.2, < 2.13.1 | XSS в поле «Информация о репозитории» (markdown-поле на вкладке info). Внедрённый скрипт выполнялся у других пользователей. | 2.11.3, 2.12.3, 2.13.1 |
| **GHSA-33p6-fx42-7rf5** (SSRF) | не указаны | Ограниченный SSRF: через API «Test Endpoint» в настройках веб-хуков проекта атакующий мог сканировать TCP-порты хостов во внутренней сети Harbor. | срочно исправлено |

**Правило:** отслеживайте [SECURITY.md](https://github.com/goharbor/harbor/blob/main/SECURITY.md) и [релизные заметки](https://github.com/goharbor/harbor/releases); при обнаружении CVE — обновляйтесь в ближайшем patch-релизе, а не ждите major.

### Слои защиты Harbor

```text
Сеть:        TLS (HTTPS), изоляция инстанса в доверенной сети
Учётки:      сменённый пароль admin, выключенная self-registration, LDAP/AD или OIDC
Доступ:      RBAC (Guest/Developer/Project Admin), робот-аккаунты для CI/CD
Артефакты:   Deployment Security (порог CVE), CVE allowlist с expiry, immutable-теги, подписи Cosign/Notation
Аудит:       Audit Log + форвардинг в SIEM
Эксплуатация: мониторинг (harbor_up), регулярные апгрейды, бэкапы
```

## Практические сценарии

### Сценарий 1: Чек-лист hardening при вводе в эксплуатацию

1. **Смените пароль admin** сразу после установки (дефолт `Harbor12345`; `harbor_admin_password` в `harbor.yml` применяется только при первом запуске).
2. **Self-registration выключена** — проверьте: Administration → Configuration → Authentication → Allow Self Registration (должно быть снято).
3. **HTTPS в production** — HTTP допустим только в air-gapped test/dev-контурах без внешнего интернета (см. [certificates.md](./certificates.md)).
4. **Права на `harbor.yml`** — `chmod 600` (файл содержит пароли); не храните в git.
5. **Робот-аккаунты для CI/CD** вместо пользовательских учёток: минимальные права (Pull, Push требует Pull), expiration, ротация (см. [usage.md, сценарий 2](./usage.md#сценарий-2-использование-робот-аккаунтов-в-cicd)).
6. **RBAC по ролям**: Guest (pull в приватном), Developer (push), Project Admin (управление проектом); системные роли — System Admin и Security Officer.
7. **Deployment Security**: включите scan on push и порог severity (Critical) в production-проектах (см. [security_policies.md](./security_policies.md)).
8. **CVE allowlist с expiry** — не «навсегда»; мониторьте даты в Security Hub.
9. **Аудит-лог**: включите ротацию и форвардинг в syslog/SIEM (см. [operations.md, сценарий 3](./operations.md#сценарий-3-аудит-логи)).
10. **Сетевая изоляция**: Harbor доступен только из доверенных сетей; учитывайте, что анонимный пользователь видит публичные проекты — делайте production-проекты приватными.
11. **Регулярные апгрейды** — патчи безопасности выходят в patch/minor-релизах (см. [upgrade_backup.md](./upgrade_backup.md)).
12. **Мониторинг**: алерты на `harbor_up == 0` и `harbor_health != 1` (см. [operations.md, сценарий 2](./operations.md#сценарий-2-мониторинг-и-алерты-prometheus)).
13. **Ключи шифрования** — `secretKey` (минимум 16 символов, рекомендуется 32), храните в Secrets-менеджере, не в `harbor.yml` на диске; при ротации ключа старые сессии инвалидируются автоматически (см. [сценарий 4](#сценарий-4-ротация-secretkey-жизненный-цикл-ключа)).
14. **Патчи безопасности** — отслеживайте [SECURITY.md](https://github.com/goharbor/harbor/blob/main/SECURITY.md) и обновляйтесь при появлении CVE; последнее известное на момент написания — CVE-2025-30086 (ORM Leak, < 2.13.1) и CVE-2024-22278 (maintainer bypass, < 2.9.5/2.10.3) (см. [сценарий 5](#сценарий-5-проверка-на-соответствие-последним-cve)).

### Сценарий 2: Проверка self-registration и auth mode

```bash
# Auth mode и версия
curl -sk "https://harbor.corp.local/api/v2.0/systeminfo" | jq '{auth_mode, harbor_version}'
# → {"auth_mode":"db_auth","harbor_version":"2.15.0"}

# Self-registration — через метрику harbor_system_info (лейбл self_registration)
curl -s http://harbor.corp.local:9090/metrics | grep harbor_system_info
# → harbor_system_info{auth_mode="db_auth",harbor_version="2.15.0",self_registration="false"} 1
```

### Сценарий 3: Безопасная структура проектов

* **Приватные проекты** для production — анонимный доступ только read-only к публичным.
* **Разделение сред**: отдельные проекты/инстансы для dev, stage, prod; репликация Dev→Prod вместо общего проекта.
* **Робот-аккаунт на команду/пайплайн**, не один общий на всю организацию.
* **Именование**: `<team>-<env>` или `<app>-<env>` — предсказуемая структура для RBAC и квот.

### Сценарий 4: Ротация `secretKey` (жизненный цикл ключа)

Ключ шифрует `keyval`-таблицу (сессии, токены, конфигурация). При смене ключа **все существующие зашифрованные записи становятся недоступны** — автоматического перешифрования нет. Планируйте ротацию как часть плана инцидентов, а не как runtime-настройку.

```bash
# 1. Сгенерируйте новый ключ (минимум 16 символов, рекомендуется 32)
openssl rand -base64 32
# → например: 4f8a3c2e9b1d7f6a5e4d3c2b1a0f9e8d7c6b5a4f3e2d1c0b9a8f7e6d5c4b3a2

# 2. Обновите harbor.yml (секция keyval) и перезапустите
#    Старые сессии и токены инвалидируются — clients перелогиниваются автоматически

# 3. Проверьте, что инстанс健康
curl -sk "https://harbor.corp.local/api/v2.0/health"
# → {"status":"healthy"}
```

**Важно:** для Helm-деплоя используйте `existingSecretSecretKey` вместо прямого `secretKey` в `values.yaml` — ключ живёт в K8s Secret, а не в chart-конфиге.

### Сценарий 5: Проверка на соответствие последним CVE

Для инстансов ниже указанных версий — обновление **обязательно**:

```bash
# Текущая версия инстанса
curl -sk "https://harbor.corp.local/api/v2.0/systeminfo" | jq '.harbor_version'

# Проверка: инстанс уязвим к CVE-2025-30086 (ORM Leak, < 2.13.1)?
# → если версия ниже 2.13.1 — обновляйтесь до 2.13.1+
# Проверка: инстанс уязвим к CVE-2024-22278 (maintainer bypass, < 2.9.5)?
# → если версия 2.10.0–2.10.2 — обновляйтесь до 2.10.3+
```

**Источники:** [SECURITY.md](https://github.com/goharbor/harbor/blob/main/SECURITY.md), [релизные заметки](https://github.com/goharbor/harbor/releases), [GitHub Advisories](https://github.com/goharbor/harbor/security/advisories).

## Валидация

```bash
# 1. HTTPS работает, сертификат валиден
openssl s_client -connect harbor.corp.local:443 -servername harbor.corp.local -CAfile ca.crt 2>/dev/null | \
  grep "Verify return code"
# → Verify return code: 0 (ok)

# 2. Self-registration выключена (метрика harbor_system_info)
curl -s http://harbor.corp.local:9090/metrics | grep harbor_system_info | grep -o 'self_registration="[a-z]*"'
# → self_registration="false"

# 3. Анонимный доступ не даёт лишнего
curl -sk -o /dev/null -w "%{http_code}" "https://harbor.corp.local/api/v2.0/projects?name=production"
# → 401 (приватный проект без auth)

# 4. Робот-аккаунт имеет только заявленные права
curl -sk -o /dev/null -w "%{http_code}" -u 'robot$production+ci-bot:' \
  "https://harbor.corp.local/api/v2.0/projects"
# → 403 (системный эндпоинт требует System Admin)
```

## Troubleshooting

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| Self-registration включена случайно | Включена при настройке или по умолчанию в старой версии | Administration → Configuration → Authentication → снять Allow Self Registration |
| Не удаётся сменить auth mode | В БД есть локальные пользователи (кроме admin) | Удалите/мигрируйте локальных пользователей, затем смените режим |
| Аноним видит проект | Проект публичный | Сделайте проект приватным (Projects → Configuration → Public/Private) |
| `docker login` по HTTP отказывается | Docker блокирует небезопасные реестры | Только для air-gapped: `insecure-registries` в daemon.json (см. [installation.md](./installation.md)) |
| Пароль admin утерян | Пароль задаётся только при первом запуске | Сброс через UI (Administration → Users → Reset Password) в Database-режиме |
| После смены `secretKey` инстанс не запускается | `keyval`-таблица зашифрована старым ключом | Восстановите ключ из бэкапа или перешифруйте данные вручную (автоматического перешифрования нет) |
| `harbor_up == 0` после обновления | Компонент не прошёл health-check | См. [operations.md, сценарий 2](./operations.md#сценарий-2-мониторинг-и-алерты-prometheus) |

## Граничные случаи

* **SAML не поддерживается** — только Database, LDAP/AD, OIDC; для SAML-требований используйте IdP-брокер (Dex как OIDC-провайдер).
* **Смена auth mode** заблокирована при наличии локальных пользователей (кроме `admin`).
* **Анонимный пользователь** — не ошибка конфигурации, а часть модели: read-only к публичным проектам. Учитывайте при выборе public/private для проекта.
* **`harbor_admin_password` игнорируется** после первого запуска — пароль администратора управляется в Harbor Portal.
* **Ротация `secretKey` необратима** — автоматического перешифрования `keyval`-таблицы нет; после смены ключа старые зашифрованные записи (сессии, токены, конфигурация) становятся недоступны. Планируйте ключ как часть жизненного цикла инстанса, а не как runtime-настройку.
* **Hardening ≠ сканирование уязвимостей образов** — это защита самого инстанса Harbor; сканирование артефактов — [security_policies.md](./security_policies.md).

## Дополнительная информация

* Официальная документация: [Managing Users](https://goharbor.io/docs/2.15.0/administration/managing-users/), [SECURITY.md](https://github.com/goharbor/harbor/blob/main/SECURITY.md).
* **TLS и сертификаты** — [certificates.md](./certificates.md).
* **RBAC и аутентификация** — [authentication.md](./authentication.md).
* **Политики безопасности артефактов** — [security_policies.md](./security_policies.md).
* **Аудит-лог** — [operations.md, сценарий 3](./operations.md#сценарий-3-аудит-логи).
* **Мониторинг и алерты** — [operations.md, сценарий 2](./operations.md#сценарий-2-мониторинг-и-алерты-prometheus).
* **Обновления и бэкапы** — [upgrade_backup.md](./upgrade_backup.md).
* **Конфигурация harbor.yml** — [overview.md, раздел «Конфигурация harbor.yml (SRE)»](./overview.md#конфигурация-harbor.yml-sre).
* **GitHub Advisories (CVE- tracker)** — [goharbor/harbor/security](https://github.com/goharbor/harbor/security/advisories).

### Связанные документы

* **[Обзор Harbor](./overview.md)** — модель безопасности.
* **[Установка](./installation.md)** — требования и первый запуск.
* **[Аутентификация](./authentication.md)** — LDAP/AD, OIDC, RBAC.
* **[Работа с Harbor](./usage.md)** — робот-аккаунты.
* **[Вопросы на собеседованиях](./harbor_interview_qa.md)** — Q&A по Harbor (в т.ч. CVE-2019-16097).

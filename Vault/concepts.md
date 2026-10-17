# Архитектура и основные концепции

**Актуально для:** Vault 2.x (latest 2.1.2; ветка 1.21.x поддерживается)

Общее описание технологии — в [Vault Overview](overview.md).

## Предварительные требования

* **Vault:** развернутый кластер (OSS или Enterprise) версии 2.x или 1.16+ для использования всех описанных функций. Минимальная версия для базовых функций — 1.13+.
* **TLS:** Production-развёртывание требует TLS для всех соединений (API, UI, межузловая коммуникация Raft).
* **Audit logging:** включённый audit device (File или Syslog) обязателен для compliance и troubleshooting.
* **Capabilities:** для выполнения сценариев в этом файле требуется token с `read` на `sys/mounts`, `sys/leader` и т.п. — или root-токен для тестовых целей.
* **CLI:** Vault CLI версии 1.16+ для использования новых подкоманд (`vault transit`, `vault events`, `vault operator raft`).

## Определения

**Основные концепции Vault** — фундаментальные компоненты и механизмы, составляющие архитектуру и логику работы системы управления жизненным циклом безопасности (Security Lifecycle Management, SLM). Ключевые элементы: процесс Seal/Unseal, интегрированное хранилище (Raft), система идентификации (Identity Store), методы аутентификации, [авторизация и политики](./authorization.md), движки секретов, жизненный цикл токенов и аудит.

**Security Lifecycle Management (SLM)** — расширенная концепция Vault (начиная с версий 1.16+ и 2.0), охватывающая весь жизненный цикл секретов: от обнаружения (Vault Radar) до централизованного управления и синхронизации с внешними хранилищами (Secrets Sync).

**Identity Store** — централизованный реестр субъектов (сущностей), позволяющий объединять различные методы аутентификации под одной личностью для унификации политики доступа.

**Cubbyhole** — внутренний бэкенд Vault, привязанный к конкретному токену. Каждый токен получает изолированное пространство имен `cubbyhole/`, секреты в котором недоступны для других токенов, даже обладающих `sudo`-правами. Используется для временного хранения данных в контексте конкретного запроса (например, при обертывании ответов Response Wrapping).

**Барьер (Barrier)** — криптографический механизм Vault, гарантирующий, что все данные перед записью в Storage Backend шифруются главным ключом (Master Key), хранящимся только в оперативной памяти в состоянии Unsealed. Барьер также верифицирует целостность (HMAC) при чтении, обнаруживая подделку или повреждение данных на уровне бэкенда.

**Raft (Consensus Protocol)** — протокол консенсуса, используемый Integrated Storage для репликации данных между узлами кластера. Обеспечивает согласованность данных (strong consistency для записей) и автоматический failover лидер-реплики.

## Архитектура

Vault имеет **плагинную архитектуру (Pluggable Architecture)**, состоящую из ядра и подключаемых плагинов.

1.  **Vault Core (Ядро):** Управляет логикой работы, безопасностью и связью между компонентами. Ядро включает механизм Barrier (шифрование/дешифрование данных), обработку API-запросов и координацию плагинов.
2.  **Vault API:** Весь доступ к Vault (через CLI, UI или SDK) осуществляется исключительно через API.
3.  **Плагины (Plugins):**
    *   **Secret Engines:** Реализуют логику хранения или динамической генерации секретов.
    *   **Auth Methods:** Отвечают за идентификацию пользователей и машин, выступая **посредником доверия (Trust Broker)** между Vault и внешними поставщиками идентичности (K8s, LDAP, OIDC).
    *   **Audit Devices:** Ведут подробные журналы всех операций (запросов и ответов).
    *   **Storage Backends:** Физически сохраняют зашифрованные данные.

**Принцип Barrier:** независимо от выбранного бэкенда (Raft, Consul, S3), Vault всегда шифрует данные перед записью. Даже при получении прямого доступа к хранилищу (например, к файлам Raft или снапшоту), злоумышленник увидит только шифротекст без доступа к Master Key в памяти.

## Основные концепции

### Процесс запечатывания (Seal) и распечатывания (Unseal)

Это ключевой механизм безопасности Vault, который гарантирует, что даже при получении доступа к физическому хранилищу данных, злоумышленник не сможет их расшифровать без ключей, находящихся в памяти.

#### Состояния Vault

Vault может находиться в одном из двух состояний:

1.  **Запечатанное (Sealed):** Состояние по умолчанию при запуске с **Shamir seal** (без Auto-unseal). Vault знает расположение хранилища, но не может расшифровать данные. Все операции, кроме проверки статуса и распечатывания, заблокированы. С Shamir seal Vault автоматически переходит в это состояние при каждом перезапуске — требует ручного или автоматического (Auto-unseal) распечатывания. При **Auto-unseal** (через KMS/HSM) Vault автоматически распечатывается при старте, не требуя ручного ввода ключей.
2.  **Распечатанное (Unsealed):** Рабочее состояние. Главный ключ (Master Key) или Ключ Барьера (Barrier Key) загружается в оперативную память для расшифровки данных и обслуживания запросов. Ключ никогда не хранится в постоянном хранилище и собирается при распечатывании.

#### Как работает распечатывание: Алгоритм Шамира

При инициализации (`vault operator init`) Vault генерирует главный ключ шифрования и, вместо его сохранения, использует **алгоритм разделения секрета Шамира (Shamir's Secret Sharing)**.

1.  **Разделение ключа:** Главный ключ делится на `N` частей (по умолчанию `N=5`), которые называются **ключами распечатывания (Unseal Keys)**.
2.  **Пороговое значение (Threshold):** Устанавливается пороговое количество ключей `K` (по умолчанию `K=3`), необходимое для восстановления исходного главного ключа.

Для распечатывания Vault необходимо предоставить `K` **любых** из `N` сгенерированных ключей. Это лежит в основе важной операционной практики — **распределения ответственности** ("кворум"), когда ключи раздаются разным сотрудникам.

#### Автоматическое распечатывание (Auto-unseal)

Для упрощения эксплуатации в production-средах используется механизм **Auto-unseal**, который интегрируется с внешними доверенными сервисами для автоматического извлечения ключа при старте:
* **HSM:** Аппаратные модули безопасности (через PKCS#11).
* **Transit Engine:** Использование другого кластера Vault для распечатывания текущего.

> При использовании Auto-unseal вместо главного ключа применяется **Recovery Key** — она используется только для восстановления доступа к Vault после экстренной переустановки (например, при утрате настроек интеграции с KMS) и не участвует в штатном процессе распечатывания. Проверить механизм распечатывания можно командой `vault status` (поле `Seal Type`).

#### Ручное запечатывание (Manual Seal) и Rekey

Помимо автоматического перехода в запечатанное состояние при перезапуске, администратор может принудительно запечатать Vault для остановки обслуживания запросов, не останавливая процесс:

```bash
# Ручное запечатывание (Vault остаётся в памяти, но блокирует все операции)
vault operator seal
```

**Rekey** — смена ключей распечатывания и главного ключа (Master Key) без нарушения работы динамических секретов (lease сохраняются). Требует подачи текущих Unseal Keys для запуска и финального порога новых ключей для завершения:

```bash
# Инициировать rekey со схемой 5 из 3 (выведет Nonce и новые ключи-заготовки)
vault operator rekey -init -key-shares=5 -key-threshold=3
# Продолжить, подавая старые ключи от каждого из доверенных лиц
vault operator rekey -key-share=<unseal_key_part>
```

Новый главный ключ после rekey отличается от старого, что снижает риск при компрометации ранее выданных ключей. Команда `vault operator rekey` также используется для пересборки ключей внутреннего механизма шифрования барьера. В конфигурации с Auto-unseal rekey переносит контроль на новые Recovery Keys (для внешних KMS/HSM ключевые материалы генерируются заново).

#### Восстановление после потери кворума

Потеря более половины ключей (`K` или больше) делает расшифровку невозможной. В этом случае единственный вариант — восстановление из снапшота Raft-хранилища, созданного до потери ключей. На этапе инициализации рекомендуется сразу настроить автоматическое резервное копирование (Snapshot Agent в Enterprise или cron-задача с `vault operator raft snapshot save` в OSS).

### Бэкенды хранения (Storage Backends)

Vault делегирует хранение зашифрованных данных внешнему персистентному хранилищу. Vault всегда шифрует данные перед записью, поэтому бэкенд отвечает только за их физическое хранение и доступность.

| Бэкенд | Тип | HA | Рекомендация |
| :--- | :--- | :--- | :--- |
| **Raft (Integrated Storage)** | Локальное хранилище | Да | **Стандарт (De-facto)**. Не требует внешних зависимостей, поддерживает точечное восстановление секретов из снапшота (Secret Recovery, Enterprise 1.20+). |
| **Consul** | Координационная система | Да | Проверенное решение, рекомендуется при наличии существующей инфраструктуры Consul. |
| **Etcd** | Координационная система | Да | Альтернатива Consul, часто используется в Kubernetes-средах. |
| **AWS S3 / GCS / Azure Blob** | Облачное хранилище | Нет | Только для single-node, требует внешнего HA механизма. |
| **PostgreSQL / MySQL** | Реляционная БД | Поддерживается | Поддерживается, требует дополнительной настройки для HA. |
| **Filesystem (`file`)** | Локальное хранилище | Нет | **Не для production**, только для разработки и тестирования. |
| **`inmem`** | Оперативная память | Нет | Только для `vault server -dev`; данные теряются при остановке процесса. |

Для Consul-бэкенда есть отдельное руководство — [Vault с Consul backend](./guides/vault_with_consul_backend.md).

Помимо физического хранилища, в Vault существует внутренний бэкенд **cubbyhole**, привязанный к конкретному токену (секреты недоступны для других токенов даже с sudo-правами).

### Высокая доступность (HA) и репликация

Vault является master-slave системой: одновременно только один узел кластера активен (Active) и обслуживает все запросы (чтение и запись).

* **Active/Standby:** Остальные узлы кластера работают в режиме Standby и синхронизируются с лидером через Raft (Integrated Storage) или Consul. Standby-узлы автоматически берут на себя роль лидера при сбое текущего, перенаправляя при этом запросы на активный узел. Переход лидера не требует участия оператора.
* **Performance Standby (Enterprise):** Узлы, которые обслуживают запросы на чтение (read-only) локально, не перенаправляя их лидеру; запросы на запись всё равно пересылаются на активный узел. Обеспечивают горизонтальное масштабирование операций чтения (KV, Transit). Требует лицензии Vault Enterprise 2.x (в OSS недоступна).
* **Репликация между кластерами (Enterprise):** два режима — **DR Replication** (аварийное восстановление во второй region) и **Performance Replication** (распределение чтения/записи по нескольким кластерам). Кластеры-реплики имеют те же механизмы распечатывания и политик, что и географический лидер.
* **Namespace (Enterprise):** логическая изоляция сред внутри одного физического кластера — аналог мультиарендности, позволяющий разделять среды (dev/prod) и их политики и токены без развертывания отдельных кластеров.

**Read Consistency:** Для операций чтения в кластере Raft Vault поддерживает два уровня:
* **strong (по умолчанию):** запрос перенаправляется на лидера, гарантируя актуальность данных.
* **stale:** запрос обслуживается локально standby-узлом, что снижает задержку, но позволяет получить устаревшие данные (до 100 мс отставания). Заголовок `X-Vault-Stale-Read` не используется — stale reads достигаются простым запросом к standby-узлу.

Подробнее о подходах высокой доступности при развертывании в Kubernetes — в [Руководстве по Kubernetes](./guides/vault_kubernetes_integration.md).

### Система идентификации (Identity Store)

Identity Store позволяет Vault оперировать понятиями пользователей и приложений независимо от метода их входа.

* **Entities (Сущности):** Представляют уникального субъекта. К одной сущности можно привязать несколько **Aliases** (например, логин из LDAP и токен из Kubernetes), что позволяет сохранять идентификацию при смене метода аутентификации.
* **Groups (Группы):** Коллекции сущностей.
    * **Internal Groups:** Управляются внутри Vault.
    * **External Groups:** Синхронизируются из внешних источников (Okta, Azure AD через SCIM).
* **Метаданные:** К сущностям и группам можно привязывать произвольные метаданные (например, `team=dev`), которые затем используются в шаблонах политик.

### Типы токенов (Tokens)

Vault выдает токены после успешной аутентификации. Тип токена влияет на отслеживание в индексе, возможность продления и создание дочерних токенов:

| Тип | Хранение в индексе | Дочерние токены | Продление | Когда использовать |
| :--- | :--- | :--- | :--- | :--- |
| `service` | Да | Да | Да | Интерактивные сервисы, требующие создания вложенных токенов. |
| `batch` | Нет | Нет | Нет | **Рекомендуется для M2M** по официальной документации. Меньше следов в памяти и в индексе. |
| `periodic` | Да | Нет | Да (до `max_ttl`) | Долгоживущие сервисы, где требуется постоянная валидность без ручного продления. |

Для типов `batch` и `periodic` параметр `token_num_uses` обычно оставляют `0` (неограниченно до истечения TTL).

### Методы аутентификации

**Методы аутентификации** проверяют личность клиентов и выдают им **токен**.

| Для кого | Методы | Описание |
| :--- | :--- | :--- |
| **Люди** | `userpass`, `ldap`, `oidc`/`jwt`, `github`, `okta` | Аутентификация через существующие системы управления учётными данными. |
| **Машины и приложения** | `approle`, `kubernetes`, `aws`, `gcp`, `azure`, `jwt` | Автоматическая аутентификация через метаданные платформы. |

**Workload Identity Federation (WIF):** Современный метод (Secret Zero), позволяющий Vault обмениваться OIDC-токенами с облачными провайдерами для получения временных прав доступа без использования статических "root" ключей провайдера.

Подробнее о методах аутентификации — [AppRole](./guides/vault_auth_approle.md), [LDAP](./guides/vault-auth-ldap.md), [OIDC/SSO](./guides/vault-auth-oidc-sso.md), [MFA](./guides/vault-mfa.md).

### Авторизация и политики доступа (Policies)

**Авторизация** в Vault определяет разрешенные действия. Основной инструмент — **политики** (HCL).

Основные механизмы:
* **ACL-политики:** Управление доступом на основе путей и возможностей (`read`, `create`, `update`, `delete`, `list`, `sudo`, `deny`). Модель: Deny-by-default.
* **Sentinel (Enterprise):** Управление доступом на основе логики (Policy as Code) с учетом контекста (время, IP, использование MFA). Подробнее — [Sentinel-политики (RGP/EGP)](./guides/sentinel-policies.md).
* **Control Groups (Enterprise):** Механизм многостороннего одобрения (принцип "четырех глаз") критических операций.

Подробное описание — в разделе **[Авторизация в Vault](./authorization.md)**.

### Движки Секретов (Secret Engines)

Движки секретов управляют жизненным циклом данных. Vault выступает в роли **брокера**, взаимодействуя с целевыми системами для создания временных учетных данных.

| Движок | Тип | Описание |
| :--- | :--- | :--- |
| **`kv` (v1/v2)** | Статические секреты | Хранилище «ключ-значение». v2 поддерживает версионирование (по умолчанию 10 версий), мягкое удаление с восстановлением (`undelete`) и атрибуцию изменений (поле `created_by`, `deleted_by` в метаданных версии). |
| **`database`** | Динамические секреты | Временные учётные данные для БД (PostgreSQL, MySQL, MongoDB, Oracle). Поддерживает статические (static) и динамические (dynamic) роли. Снижают риск: если пароль попадет в логи, он быстро истечет. |
| **`pki`** | Динамические сертификаты | Внутренний CA для выдачи TLS-сертификатов. Поддерживает ACME. Позволяет использовать короткоживущие сертификаты (часы/минуты), упрощая процесс ротации. |
| **`transit`** | Шифрование как сервис | Криптографические операции без хранения данных в Vault. Идеально для защиты **PII (Personal Identifiable Information)**: данные в БД остаютются зашифрованными даже при компрометации доступа к ней. |
| **`aws`/`gcp`/`azure`** | Облачные секреты | Временные IAM-учётные данные для облачных провайдеров (только Enterprise). |
| **`totp`** | Одноразовые пароли | Генерация и валидация TOTP-кодов для MFA. |
| **`ssh`** | SSH-сертификаты | Управление SSH-ключами и сертификатами доступа. Динамическая генерация исключает использование одного долгоживущего `.pem` файла для всей инфраструктуры. |
| **`rabbitmq`** | Очереди сообщений | Динамические credentials для RabbitMQ. |
| **`kubernetes`** | K8s токены | Выдача токенов сервисных аккаунтов Kubernetes. |
| **`kmip`** | Управление ключами | (Enterprise) Выдача и управление криптографическими ключами через KMIP-протокол. |

> **Примечание:** **Secrets Sync** (синхронизация секретов в AWS Secrets Manager, Azure Key Vault, GCP Secret Manager, GitHub Actions, Vercel) — это функция Vault Enterprise (1.16+), а не mounted secrets engine. Она управляется через API `/sys/sync/destinations/*` и не включается через `vault secrets enable`. Подробности — в [SLM, Vault Radar, Secrets Sync](./guides/slm_radar_secrets_sync.md).

**Сравнение моделей:**

| Критерий | KV (статические) | Динамические |
| :--- | :--- | :--- |
| Источник | Хранятся в Vault | Генерируются на лету |
| Время жизни | Без TTL (обычно) | TTL/lease обязательно |
| Отзыв | Удаление/перезапись | Мгновенный revoke в целевой системе |
| Ротация | Ручная/внешняя | Встроенная через роли |

#### Управление версиями KV v2

KV v2 хранит историю версий каждого секрета. Доступ к данным осуществляется через сегмент `/data/`, а метаданные — через `/metadata/`. Это важно для настройки ACL-политик (подробно — в [KV v2](./guides/kv-v2.md)):

```bash
# Запись новой версии (CAS — check-and-set, только если версия совпадает)
vault kv put -mount=secret -cas=2 my-secret api_key="new_key"

# Чтение последней версии
vault kv get -mount=secret my-secret

# Чтение конкретной версии
vault kv get -mount=secret -version=1 my-secret

# Список ключей (требует capability list на путь /metadata/)
vault kv list -mount=secret

# Просмотр метаданных (версии, времена, статус)
vault kv metadata get -mount=secret my-secret
```

**Операции удаления** — три уровня:

| Операция | CLI | API путь | Эффект |
| :--- | :--- | :--- | :--- |
| **Soft delete** | `vault kv delete -mount=secret -versions=2 my-secret` | `POST /:mount/delete/:path` | Помечает версию удалённой (deletion_time). Данные сохранены, можно восстановить через `undelete`. |
| **Undelete** | `vault kv undelete -mount=secret -versions=2 my-secret` | `POST /:mount/undelete/:path` | Восстанавливает ранее soft-deleted версию. |
| **Destroy (permanent)** | `vault kv destroy -mount=secret -versions=2 my-secret` | `POST /:mount/destroy/:path` | Полностью удаляет данные. Необратимо. |

**Конфигурация KV v2:**

| Параметр | Команда | Описание |
| :--- | :--- | :--- |
| `max_versions` | `vault write secret/config max_versions=20` | Максимум версий на ключ. Старше — автоматически уничтожаются. По умолчанию 10 (0 = неограниченно, но рекомендуется установить лимит для контроля роста хранилища). |
| `cas_required` | `vault write secret/config cas_required=true` | Требовать CAS (check-and-set) для всех записей. Предотвращает случайные перезаписи. |
| `delete_version_after` | `vault write secret/config delete_version_after="24h"` | Автоматически удалять (soft delete) версии старше указанного TTL. |

### Жизненный цикл: Токены, Lease и Revoke

Любой динамический секрет или токен сопровождается **lease** (арендой) с ограничением по времени (TTL).

* **Токены:** Основные объекты идентичности. Бывают `service` (стандартные, хранятся в индексе), `batch` (легковесные, без хранения в индексе и аудита), `periodic` (обновляются неограниченно, но без дочерних токенов). Префиксы токенов: `hvs.` — service, `hvb.` — batch, `hvr.` — recovery (начиная с Vault 1.10+).
* **Orphan Tokens (осиротевшие токены):** Токены без родителя — начало собственного дерева токенов. Не отзываются при истечении TTL родительского токена. Создаются через `/auth/token/create-orphan` (требует root/sudo) или `-orphan` флаг в CLI. Используются для долгоживущих сервисов (CI/CD, приложения), где родительский токен может быть отозван, но сервис должен продолжать работать.
* **TTL и Max TTL:** Два связанных значения — `ttl` (изначальный срок жизни) и `max_ttl` (абсолютный потолок, который не преодолевается при повторных продлениях). Учёт через `vault read /auth/token/lookup-self` или `vault token lookup`.
* **Accessor:** Публичный идентификатор токена. Позволяет проверять статус или отзевать токен, не передавая само секретное значение.
* **Локальные (Local) и глобальные (Global) токены:** Глобальные видны во всех кластерах DR Replication, локальные — только в текущем.
* **Продление (Renew):** Увеличение TTL до максимально разрешенного значения. Periodic-токены могут продляться бесконечно (до `explicit_max_ttl`, если задан), service-токены — до `max_ttl`. Batch-токены не поддерживают продление.
* **Отзыв (Revoke):** Досрочное аннулирование секрета, инициирующее удаление данных в целевой системе. Каскадная отмена действует на дочерние токены и связанные lease. Для отзыва токена без затрагивания дочерних — используйте `vault token revoke -mode=orphan <token>` (создаёт из дочерних токенов осиротевшие).
* **Автоматическая очистка (Tidy):** Периодическая чистка истёкших lease и «осиротевших» токенов по истечении TTL для уменьшения хранилища.

### Обертывание ответов (Response Wrapping)

Механизм безопасной доставки. Vault возвращает временный одноразовый токен, содержащий итоговый секрет.

* **Принцип "Первого развертывания":** Токен можно развернуть (`unwrap`) строго один раз.
* **Обнаружение компрометации:** Если легитимный получатель получает ошибку "already unwrapped", это сигнал перехвата токена злоумышленником.

### Аудит и события (Vault Events)

*   **Audit Devices (Устройства аудита):** Запись всех запросов и ответов (File, Syslog, Socket). Аналог камер видеонаблюдения: фиксируют, кто, когда и какой секрет запрашивал, включая ошибки. Рекомендуется минимум два устройства. Чувствительные данные в логах хэшируются с солью (HMAC-SHA256).
*   **Vault Events (Enterprise, GA с 1.16+, бета в 1.15):** Позволяет внешним системам подписываться на события в Vault (создание секрета, изменение политики) через WebSocket-поток. Подписка выполняется через endpoint `/v1/sys/events/subscribe/{eventType}` (поддерживаются wildcard-паттерны, например `kv-v2/data-*`) или команду CLI `vault events subscribe`. По умолчанию события передаются в бинарном protobuf-формате, опционально — как JSON (`?json=true`). Для потребления событий без поля `path` требуется root-токен. События доступны только в разрешённом namespace и защищены политиками (capability `subscribe`, поле `subscribe_event_types`).
*   **Forensic analysis:** Audit логи позволяют трассировать цепочку доступа по `request.id` (связь request ↔ response), определять радиус поражения и находить аномалии (bulk-read, mass-revoke, root-токен из неизвестного IP). Подробности — в [Анализ audit логов](./guides/audit_log_analysis.md).

### Барьер и шифрование данных (Encryption at Rest)

Vault гарантирует, что все данные в Storage Backend хранятся в зашифрованном виде. Механизм **Barrier** отвечает за прозрачное шифрование/дешифрование:

1.  **При записи:** Данные сериализуются, хэшируются (HMAC) для контроля целостности, шифруются AES-256-GCM с использованием Master Key и записываются в бэкенд.
2.  **При чтении:** Vault читает шифротекст, проверяет HMAC, дешифрует и десериализует данные.
3.  **Master Key:** Генерируется при инициализации, никогда не покидает оперативную память в состоянии Unsealed. При Sealed состоянии Master Key недоступен, и Barrier не может расшифровать данные.

В конфигурации с Auto-unseal Master Key заменяется на Recovery Key, которая управляется внешним KMS/HSM. В этом случае KMS отвечает за шифрование/дешифрование Barrier ключа, а не самого Master Key.

### Операционные команды и управление кластером

Для ежедневного обслуживания Vault используются стандартные CLI-команды:

```bash
# Список смонтированных движков секретов и auth-методов
vault secrets list
vault auth list

# Включение/отключение движка или метода аутентизации
vault secrets enable -path=secret kv-v2
vault secrets disable secret
vault auth enable kubernetes
vault auth disable ldap

# Тонкая настройка параметров без пересоздания
vault auth tune -path=approle token_type=batch token_ttl=1h
vault secrets tune -path=secret max_lease_ttl_seconds=86400

# KV v2: чтение, запись, CAS, удаление/восстановление/уничтожение
vault kv get -mount=secret my-secret
vault kv put -mount=secret -cas=1 my-secret key="value"
vault kv delete -mount=secret -versions=1 my-secret
vault kv undelete -mount=secret -versions=1 my-secret
vault kv destroy -mount=secret -versions=1 my-secret
vault kv list -mount=secret

# Управление токенами
vault token create -policy=app-policy -ttl=1h -max-ttl=24h
vault token create -orphan -policy=ci-policy -ttl=30m
vault token lookup <token_accessor>
vault token revoke <token>
vault token revoke -mode=orphan <token>  # отозвать токен, но не дочерние

# Проверка работоспособности (health check)
vault status
# → Seal Type       shamir
# → Initialized     true
# → Sealed          false
# → Cluster Name    vault-cluster
# → HA Cluster      active (self)

# Проверка лидера и пиров (только для Raft)
vault read sys/leader
vault operator raft list-peers
```

**Важно:** команды `vault secrets list` и `vault auth list` требуют capability `read` на `sys/mounts`. В Production ограничьте доступ к `sys/*` через политики.

### Обновление и обслуживание

**Обновление версии Vault** (OSS/Enterprise) выполняется заменой бинарного файла и перезапуском systemd-сервиса. При обновлении на мажорную версию проверьте [Release Notes](https://developer.hashicorp.com/vault/docs/upgrade) на предмет breaking changes (например, изменения в формате снапшотов или параметрах конфигурации).

**Алгоритм обновления для HA-кластера:**
1.  Обновить standby-реплики по очереди (rolling restart).
2.  Лидер автоматически переключается на обновленную реплику.
3.  Обновить бывшего лидера.
4.  Проверить `vault status` и `vault operator raft list-peers`.

Пошаговая процедура обслуживания (step-down, покатный апгрейд, коды `/sys/health`) — в [Обслуживание кластера](./guides/cluster-maintenance.md).

**Seal Migration:** Переход между механизмами seal (например, Shamir → Auto-unseal) выполняется через `vault operator rekey` и `vault operator unseal -migrate` без потери данных и изменения корневого токена. Подробности — в [Руководстве по установке](./guides/vault_installation.md).

## Практические сценарии

### Инициализация и распечатывание (Shamir)

1.  **Инициализация:**
    ```bash
    vault operator init
    # → Unseal Key 1: <base64_1>
    # → Unseal Key 2: <base64_2>
    # → Unseal Key 3: <base64_3>
    # → Unseal Key 4: <base64_4>
    # → Unseal Key 5: <base64_5>
    # → Initial Root Token: <root_token>
    ```
    Получаем 5 Unseal Keys и Root Token. **Важно:** Root Token и ключи выводятся однократно, поэтому их необходимо сразу сохранить в безопасном месте (например, в менеджере паролей или через `vault operator init -format=json`).

2.  **Распечатывание (3 из 5):**
    ```bash
    vault operator unseal <key_1>
    # → Unseal Progress: 1/3
    vault operator unseal <key_2>
    # → Unseal Progress: 2/3
    vault operator unseal <key_3>
    # → Sealed: false (Vault распечатан)
    ```

### Использование lease и отзыв динамического секрета

Выдача динамического секрета всегда возвращает lease, который можно проверить и отозвать:

```bash
vault read database/creds/app
# → Key         Value
# → lease_id    database/creds/app/xxxx
# → lease_duration  1h
# → password    <сгенерированный>

# Продлить аренду
vault lease renew database/creds/app/xxxx

# Принудительно отозвать (удаляет пользователя в целевой БД)
vault lease revoke database/creds/app/xxxx
```

### Работа с Raft кластером

Для присоединения узла к существующему кластеру Raft:
```bash
vault operator raft join http://vault-active-node:8200
```
Проверка состояния кластера:
```bash
vault operator raft list-peers
# → Node                                    Address   State     Voter
# → 2de…8f2                                 10.0.0.1   leader    true
# → 8a1…9c0                                 10.0.0.2   follower  true
```

### Использование Identity для политик

Пример политики, использующей метаданные сущности:
```hcl
path "secret/data/{{identity.entity.metadata.team}}/*" {
  capabilities = ["read", "list"]
}
```

### CI/CD интеграция (без облака)

Vault полностью самостоятельно (self-hosted) подходит для CI/CD без привязки к облачным провайдерам. Два проверенных паттерна:

#### Паттерн 1: AppRole для CI/CD раннеров

```bash
# 1. Создание политики для пайплайна
vault policy write ci-deploy - <<EOF
# Доступ только к своей ветке
path "secret/data/ci/app/*" {
  capabilities = ["read"]
}
path "database/creds/ci-role" {
  capabilities = ["read"]
}
EOF

# 2. Создание AppRole с коротким TTL
vault write auth/approle/role/ci-deploy \
    token_policies="ci-deploy" \
    token_ttl=15m \
    token_max_ttl=30m \
    secret_id_ttl=30m \
    secret_id_num_uses=1

# 3. Получение RoleID (хранится в CI как static config)
vault read auth/approle/role/ci-deploy/role-id
# → role_id: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx

# 4. Получение SecretID с Response Wrapping (передаётся в CI безопасно)
vault write -wrap-ttl=10m -f auth/approle/role/ci-deploy/secret-id
# → wrapping_token: s.xxxxxxxx

# 5. В CI/CD пайплайне (GitLab CI пример):
#    1) vault unwrap $WRAPPING_TOKEN → SecretID
#    2) vault write auth/approle/login role_id=$ROLE_ID secret_id=$SECRET_ID → токен
#    3) vault kv get secret/ci/app/config → секреты
#    4) Токен автоматически истекает через 15 мин
```

#### Паттерн 2: JWT/OIDC для self-hosted CI (GitLab, Jenkins)

Для self-hosted CI, поддерживающего OIDC-выдачу (GitLab CI 16.0+, Jenkins с plugins), используется JWT auth method без облака:

```bash
# 1. Настройка JWT auth method (self-hosted OIDC provider)
vault auth enable jwt

# 2. Конфигурация с bounds на issuer и audience
vault write auth/jwt/config \
    jwks_url="https://gitlab.example.com/-/jwks" \
    bound_issuer="https://gitlab.example.com/" \
    default_role="ci-deploy"

# 3. Роль с привязкой к CI-переменным (namespace, project)
vault write auth/jwt/role/ci-deploy \
    role_type="jwt" \
    bound_audiences="https://gitlab.example.com" \
    bound_claims='{"namespace":"production"}' \
    token_policies="ci-deploy" \
    token_ttl=15m \
    token_max_ttl=30m \
    claim_mappings='{"sub":"resource"}'

# 4. В пайплайне: получить JWT от CI, войти в Vault через /auth/jwt/login
#    vault write auth/jwt/login role=ci-deploy jwt=$CI_JOB_JWT
```

#### Управление токенами в production

Для долгоживущих сервисов используйте комбинацию orphan + periodic токенов:

```bash
# Создание periodic orphan service token (для приложения без parent)
vault token create \
    -orphan \
    -policy=app-policy \
    -period=24h \
    -max-leases-to-attach=0 \
    -explicit-max-ttl=720h

# Проверить статус токена (по accessor)
vault token lookup -prefix=$(vault token lookup <token> -format=json | jq -r .data.accessor)
# или по accessor напрямую:
vault token lookup <accessor>
```

**Best practice для production:**
- `batch`-токены для M2M (короткий TTL, без индексирования)
- `service` + `orphan` + `periodic` для долгоживущих сервисов (самостоятельное продление через Vault Agent)
- `explicit_max_ttl` для batch-токенов — ограничивает максимальный TTL даже с renew

### Ежедневные проверки работоспособности (Health Checks)

SRE-практика предполагает автоматизированные проверки состояния Vault:

```bash
# Health check (доступен без аутентификации)
curl -sk https://vault.example.com:8200/v1/sys/health
# → {"initialized":true,"sealed":false,"standby":false,...}

# Проверка лидера (только для Raft)
vault read sys/leader
# → {"ha_enabled":true,"is_self":true,...}

# Проверка смонтированных движков
vault secrets list -detailed
# → Path          Type        Accessor           ...
# → secret/       kv-v2       kv_8a3b...         ...
# → database/     database    db_9c2d...         ...

# Проверка audit devices
vault audit list
# → Path     Type    Description
# → file/    file    file audit log
# → syslog/  syslog  syslog audit
```

### Валидация резервной копии (Snapshot Verification)

Регулярно проверяйте целостность снапшотов Raft:

Создание, проверка целостности (`snapshot inspect`) и тестовое восстановление покрыты в **[Стратегиях резервного копирования и восстановления Vault](./guides/backup_restore_strategies.md#сценарий-1-создание-и-хранение-snapshot)**.

### Сисадмин операции (systemd, TLS, логи)

**systemd сервис для bare-metal / VM:**

```ini
# /etc/systemd/system/vault.service
[Unit]
Description=HashiCorp Vault
Documentation=https://developer.hashicorp.com/vault/docs
After=network-online.target
Wants=network-online.target

[Service]
Type=notify
User=vault
Group=vault
ExecStart=/usr/local/bin/vault server -config=/etc/vault.d/vault.hcl
ExecReload=/bin/kill -HUP $MAINPID
CapabilityBoundingSet=CAP_IPC_LOCK
SecureBits=lock:ptrace
User=vault
Group=vault
NoNewPrivileges=yes
LockPersonality=true
MemoryDenyWriteExecute=true
ProtectSystem=full
ProtectHome=read-only
PrivateTmp=true
PrivateDevices=false
PrivateUsers=true
ProtectHostname=true
ProtectKernelLogs=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictSUIDSGID=true
ReadWritePaths=
ProtectKernelTunables=true
RestrictRealtime=true
RestrictNamespaces=true
SystemCallFilter=@system-service
SystemCallFilter=add_key
SystemCallFilter=syslog
SystemCallFilter=prctl
SystemCallErrorNumber=EPERM
SystemCallArchitectures=native
UAIMap=yes
LimitNOFILE=65536
LimitMEMLOCK=infinity
TasksMax=infinity

[Install]
WantedBy=multi-user.target
```

**Включить и запустить:**
```bash
systemctl daemons-reload
systemctl enable vault
systemctl start vault
systemctl status vault
```

**Ротация TLS-сертификатов для Vault:**

Vault требует TLS для всех production-соединений. Ротация сертификата требует reload конфигурации:

```bash
# 1. Поместите новые сертификаты на диск
cp new.crt /etc/vault.d/certs/tls.crt
cp new.key /etc/vault.d/certs/tls.key

# 2. Перезапустите Vault (reload TLS без полного restart)
vault operator reload
# → TLS certificates reloaded successfully
```

**Ротация audit-логов (logrotate):**

```bash
# /etc/logrotate.d/vault
/var/log/vault/audit.log {
    daily
    rotate 30
    compress
    delaycompress
    missingok
    notifempty
    postrotate
        systemctl kill -s HUP vault.service
    endscript
}
```

**Емкость и планирование (capacity planning):**

| Параметр | Минимум | Рекомендуется |
| :--- | :--- | :--- |
| Память | 4 ГБ | 8+ ГБ на узел |
| CPU | 2 vCPU | 4+ vCPU на узел |
| Диск (Raft) | 10 ГБ | 100+ ГБ (зависит от audit volume и KV версий) |
| `max_lease_ttl_seconds` | — | Установите лимит, чтобы не допустить залипания долгоживущих lease |
| `default_lease_ttl` | — | 1h для большинства динамических движков |
| `disable_mlock` | false (Linux) | true (container), используйте `LimitMEMLOCK=infinity` |

> **Примечание:** Vault использует `mlock`/`IPC_LOCK` для предотвращения выгрузки ключей в swap. В Linux-контейнерах используйте `securityContext.capabilities` с `IPC_LOCK`.

**Настройка telemetry для SRE:**

```hcl
# /etc/vault.d/vault.hcl
listener "tcp" {
  address     = "0.0.0.0:8200"
  tls_cert_file = "/etc/vault.d/certs/tls.crt"
  tls_key_file  = "/etc/vault.d/certs/tls.key"
}

storage "raft" {
  path    = "/opt/vault/data"
  node_id = "vault-1"
}

telemetry {
  prometheus_retention_time = "24h"
  disable_hostname           = true
  enable_hostname_as_label    = true
  statsd_address              = "127.0.0.1:8125"
  num_dimensions               = 1
}

api_addr = "https://vault.example.com:8200"
cluster_addr = "https://vault.example.com:8201"
cluster_name = "vault-cluster"
```

**Автоматическое резервное копирование (cron, OSS):**

```bash
# /etc/cron.d/vault-snapshot
0 */6 * * * vault vault operator raft snapshot save /backup/vault-$(date +\%F).snap
15 1 * * * vault vault operator raft snapshot inspect /backup/vault-$(date +\%F).snap
```

## Лучшие практики

**Управление ключами:**
* Never используйте root-токен для ежедневной работы. Генерируйте его однократно через `vault operator init`, сразу же создайте политику с ограниченными правами и используйте `vault token create -role=<role>` для регулярных токенов.
* Root-токен храните в зашифрованном хранилище (например, через `ansible-vault` или HSM) и регулярно проверяйте его отсутствие в логах и CI-конфигурациях через Vault Radar.
* Используйте Shamir с `key-shares=5, key-threshold=3` (или аналогичный quorum) и распределяйте Unseal Keys между разными ролями (Security Officer, Platform Admin, On-Call Engineer).

**Аудит и compliance:**
* Минимум **два** audit-устройства (File + Syslog/Socket) для защиты от потери логов при сбое одного из каналов.
* Настраивайте аудит так, чтобы `raw` (plaintext values) хэшировались с солью — по умолчанию используется HMAC.
* Регулярно проверяйте audit-логи на аномальные паттерны: bulk-read всех секретов, revoke всех токенов, доступ root-токеном из неизвестных IP.

**Токены:**
* Используйте `token_type=batch` для M2M-приложений (меньше следов в индексе, нечувствительны к перезапуску Active node).
* Устанавливайте `max_ttl` жёстче, чем `ttl` для токенов приложений — это предотвращает бессрочное продление.
* Используйте `token_bound_cidrs` для ограничения токенов конкретными подсетями (например, pod CIDR в Kubernetes).

**Хранилище и резервные копии:**
* Используйте Raft (Integrated Storage) — не требует внешних зависимостей, поддерживает `vault operator raft snapshot save` в OSS.
* Автоматизируйте snapshot через cron (OSS) или Snapshot Agent (Enterprise): `vault operator raft snapshot save /backup/vault-$(date +%F).snap` каждые 6–12 часов.
* Регулярно проверяйте снапшоты через `vault operator raft snapshot inspect /backup/vault-*.snap` и проводите тестовое восстановление в изолированном окружении.

**Мониторинг (SRE):**
* Настраивайте алерты на: `vault_core_leader_periodic_checkpoints`, `vault_rollback_attempt`, `vault_token_creation`, `vault_token_renew`.
* Используйте `/v1/sys/health` для liveness (sealed=false) и readiness (standby_ok=true) probes в orchestrator.
* Следите за метрикой `vault_threadcount_threshold_violated` — сигнал о необходимости увеличить worker threads.
* Ключевые метрики для SLO 99.9%: `vault_core_unsealed` (availability), `vault_request_count` с `status=~"5.."` (error rate), `vault_raft_commitTime` (latency). Подробнее — в [Мониторинг и алертинг](./guides/monitoring_and_alerting.md).

#### Валидация и проверка

```bash
# Проверить, что audit log включён и записывается
vault audit list
# → file/       file
# → syslog/    syslog

# Проверить, что TLS включён
vault status | grep -i "tls"
# → Seal Type       shamir

# Проверить количество токенов в индексе (batch-токены не учитываются)
vault read sys/internal/ui/mounts
```

#### Очистка и откат

```bash
# Отозвать все токены выданные определённой политикой (например, после компрометации)
vault list sys/policies/token
vault read sys/policies/token/<policy_name>/token-roles
vault token revoke -mode=orphan <compromised_parent_token>

# Очистить истёкшие lease и орфан-токены
vault write sys/retention/sweep -f

# Tidy для KV v2 (удаление soft-deleted версий, помеченных через delete_version_after)
vault write sys/retention/sweep -scope=kv -f

# Очистить старые token-lease, не связанные с активными сессиями
vault write sys/retention/sweep -scope=auth/token -f
```

### Типичные ошибки и способы восстановления (Troubleshooting)

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Sealed despite Auto-unseal** | KMS/HSM недоступен или изменён ключ. | Проверьте `vault status` (поле `Seal Type`) и логи KMS. |
| **Raft Quorum Lost** | Потеря более 50% узлов кластера. | Восстановление из снапшота или ручная правка `peers.json`. |
| **Cannot unseal with -migrate** | Не совпадает порог key-shares/recovery-threshold. | Убедитесь, что подаётся правильное количество ключей. |
| **Error locking memory** | Ошибка `mlock`. | Проверьте `CAP_IPC_LOCK` и `LimitMEMLOCK=infinity` в systemd. |
| **Root token revoked** | Root-токен одноразовый для входа. | Генерируйте новый через `vault operator generate-root` с Recovery/Unseal Keys. |
| **High API latency** | Перегрузка Active node или отсутствие Performance Standby. | Масштабируйте standby-узлы, включите Performance Standby (Enterprise). |
| **Audit log not writing** | Audit device misconfiguration или недостаточно прав. | Проверьте `vault audit list`, права на файл/сокет, формат логов. |
| **Token count high** | Приложения не отзывают токены после завершения работы. | Настройте токены с небольшим `ttl`, используйте `batch`-токены для M2M. |
| **Snapshot fails / corrupt** | Диск переполнен или I/O errors. | Проверьте свободное место (`df -h`), используйте `snapshot inspect` для проверки целостности. |
| **Performance Standby не работает** | В OSS-сборке или лицензия истекла. | Проверьте `vault license status` (Enterprise). Performance Standby доступна только в Enterprise. |
| **Vault Events не доставляются** | Подписка не имеет capability `subscribe` или `subscribe_event_types` в политике. | Добавьте `subscribe` capability и `subscribe_event_types = ["*"]` в политику. Требуется root-токен для событий без `path`. |
| **mlock ошибка в контейнере** | `IPC_LOCK` capability not granted. | В Kubernetes: `securityContext.capabilities.add: ["IPC_LOCK"]`. В systemd: `LimitMEMLOCK=infinity`. |
| **Audit log переполняет диск** | Высокая нагрузка + file audit device без rotation. | Настройте logrotate с `postrotate` (SIGHUP), либо используйте syslog/socket. |

## Дополнительная информация

* [Vault Overview](overview.md) — вводный обзор.
* [Авторизация в Vault](./authorization.md) — подробнее о политиках.
* [Vault Agent](./guides/vault_agent/basics.md) — автоматизация на стороне клиента.
* [Аутентификация через AppRole](./guides/vault_auth_approle.md) — детали машинной аутентификации (RoleID/SecretID).
* [Интеграция с Kubernetes](./guides/vault_kubernetes_integration.md) — Vault Secrets Operator и Injector.
* [SSH Secrets Engine](./guides/ssh_secrets_engine.md) — динамические SSH-ключи и сертификаты.
* [Database Secrets Engine](./guides/database_secrets_engine.md) — динамические учетные данные баз данных.
* [PKI/CA продвинутые сценарии](./guides/pki_ca_advanced.md) — Intermediate CA, ACME, CRL/OCSP.
* [Производительность и репликация](./performance_and_replication.md) — Performance Standby, DR Replication.
* [Мониторинг и алертинг](./monitoring_and_alerting.md) — Prometheus, Grafana, SLO/SLI.
* [Анализ audit логов](./audit_log_analysis.md) — SIEM, forensic, compliance.
* [Ротация секретов](./secret_rotation.md) — стратегии ротации.
* [Namespaces](./namespaces.md) — изоляция сред (Enterprise).
* [SLM, Vault Radar, Secrets Sync](./slm_radar_secrets_sync.md) — Security Lifecycle Management.
* [Производительность и тюнинг](./performance_tuning.md) — оптимизация для high-load.
* [Vault API Reference](./vault_api_reference.md) — REST API и endpoints.
* [Cubbyhole и Response Wrapping](./guides/cubbyhole_response_wrapping.md) — безопасная доставка секретов.
* [Control Groups](./control_groups.md) — multi-approval для критических операций.
* [Стратегии бэкапов и восстановления](./backup_restore_strategies.md) — RPO/RTO, disaster recovery.
* [Руководство по установке Vault](./guides/vault_installation.md) — развертывание и обслуживание.
* [Официальная документация HashiCorp Vault](https://developer.hashicorp.com/vault/docs)

# Инциденты в Vault: отклик и реагирование

> **Актуально для:** Vault 2.x (latest 2.1.2; ветка 1.21.x поддерживается)

## Определения

**Инцидент Vault** — ситуация, требующая оперативных действий: утечка или компрометация токена, утечка секрета, компрометация узла, неконтролируемый рост lease (lease explosion), отказ active-узла.

**Revocation (отзыв)** — уничтожение токена или lease. Отзыв токена убивает токен и его дочерние; отзыв lease заставляет secrets engine удалить выданный секрет в целевой системе (например, отозвать креды базы данных).

**Orphan-токен** — токен, отвязанный от родителя: при отзыве родителя дети становятся сиротами и продолжают жить. Для инцидентов дети-сироты — главный скрытый риск.

**Lease explosion** — аномальный рост числа lease (утечка в коде, отсутствие TTL), исчерпывающий ресурсы Vault. Защита — [lease count quotas](./quotas.md).

**Mass revocation** — массовый отзыв по префиксу: токенов по auth-пути (`-mode=path`) или lease по префиксу пути (`-prefix`).

## Основные концепции

### Классификация инцидентов

| Инцидент | Что скомпрометировано | Первая реакция |
| :--- | :--- | :--- |
| Утёкший сервисный токен | Один токен | `vault token revoke` (с детьми) |
| Утёкший root-токен | Высшие привилегии | Revoke всех сессий + `vault operator rekey` / `rotate` |
| Компрометация auth method (например, bind user LDAP) | Все входы через метод | Массовый отзыв токенов `-mode=path`, ротация bind |
| Утечка секрета из KV | Конкретный секрет | Отзыв lease (если есть) + ротация секрета в целевой системе |
| Утечка БД-кредов | Выданные lease | `vault lease revoke -prefix` → целевая система отзывает кред |
| Код-деплой штампит lease | Все lease mount | Настроить/поднять [quotas](./quotas.md), mass revoke |
| Active-узел недоступен | Кластер | См. [обслуживание кластера](./cluster-maintenance.md) |

### Механика отзыва: токены

`vault token revoke` отзывает токен и **все дочерние токены** по умолчанию:

```bash
vault token revoke <token>            # токен + дети
vault token revoke -mode=orphan <t>   # только токен, дети остаются сиротами
vault token revoke -accessor <acc>    # по accessor, не раскрывая значение токена
vault token revoke -self              # текущий токен
```

Массовый отзыв токенов заданного auth method — режим `-mode=path`: удаляются все токены, созданные по префиксу auth-пути, вместе с детьми:

```bash
vault token revoke -mode=path auth/ldap/
# → Success! Revoked token (if it existed)
```

Важно: `-mode=orphan` при инциденте обычно **неверный** выбор — дети продолжают работать. Используйте полный отзыв (дефолт) либо `-mode=path` для охвата всей популяции.

Существует также API `POST /sys/revoke-prefix/<path>`: по описанию в документации он отзывает все токены, созданные по этому auth-пути, **вместе с динамическими секретами, выданными этими токенами** — это рекомендуемый в документации break-glass при подозрении на компрометацию. Для auth-путей это шире, чем `token revoke -mode=path`.

### Механика отзыва: lease

```bash
vault lease revoke <lease-id>          # один lease → секрет удаляется в целевой системе
vault lease revoke -prefix database/creds   # массово по префиксу
vault lease revoke -sync -prefix <p>   # синхронно, без фоновой очереди
vault lease revoke -force -prefix <p>  # удалить lease, даже если revocation в БД упал
```

* `-sync` — дождаться завершения отзыва вместо постановки в очередь (нужно в инциденте, чтобы проверить результат сразу).
* `-force` — для ситуаций, когда секрет уже удалён руками в целевой системе и штатный revoke падает; **требует `-prefix`** и приводит к расхождению Vault с состоянием секрета (предупреждение в выводе команды).

### Почему детей-сирот находят последними

Дочерние токены создаются из родительского (`vault token create` без orphan). При отзыве с `-mode=orphan` или при некорректном отзыве они выживают, имеют свои TTL и политики. Поэтому после любого отзыва проверяют популяцию через audit-логи (accessor/паттерн), а не полагаются на дерево токенов.

### Скоупинг по audit-логам

Прежде чем массово отзывать, определяют масштаб: по audit-логам ищут accessor токена, пути, которые запрашивались, namespace и время начала. Детальная методика — [анализ audit-логов](./audit_log_analysis.md). Массовый отзыв «всего подряд» сам по себе создаёт инцидент: валидные сервисы теряют токены.

## Практические сценарии

### 1. Утёк один сервисный токен

```bash
# Найти токен по accessor (из логов/метрик), не раскрывая значение
vault token lookup -accessor=<accessor>
vault token revoke -accessor=<accessor>

# Проверить, не появились ли дети (lookup показывает parent)
vault list auth/token/accessors   # вручную или через audit
```

### 2. Утечка кредов БД, выданных Vault

```bash
# Массово отозвать все креды роли — секреты удалятся в самой БД
vault lease revoke -sync -prefix database/creds/readonly
# → Success! Revoked any leases with prefix: database/creds/readonly

# Если отдельный lease уже невосстановим (секрет удалён руками)
vault lease revoke -force -prefix database/creds/readonly/<lease-id>
# → Warning! Force-removing leases can cause Vault to become out of sync with secret engines!
```

После mass revoke приложения с полученной статикой перечитывают секреты через новые lease; «висящие» клиенты с отозванными кредами получат ошибки аутентификации в целевой БД — это ожидаемо и лечится ротацией конфигурации.

### 3. Скомпрометирован root-токен или критический auth method

1. Отозвать популяцию токенов: `vault token revoke -mode=path auth/<method>/` (или по аксессорам из audit).
2. Ротировать секреты метода: для LDAP `vault write -f auth/ldap/config/rotate-root`; для AppRole перевыпустить SecretID; сменить клиентский секрет OIDC на стороне IdP.
3. Отозвать сам скомпрометированный root-токен: им же — `vault token revoke -self`; если доступа к нему нет — выпустить новый root (`vault operator generate-root` с unseal-шардами) и отозвать утёкший этим root-токеном.
4. Если скомпрометированы сами unseal-шарды: `vault operator rekey` (новый набор unseal-ключей, требуется распечатанный кворум) и/или `vault operator rotate` — процедуры описаны в [Основных концепциях](../concepts.md) и [установке](./vault_installation.md).
5. Разобрать audit-логи за окно компрометации, зафиксировать scope в отчёте инцидента.

### 4. Lease explosion

```bash
# Сколько lease уже создано (требует sudo на sys/leases/list)
vault lease list database/creds/

# Срочно срезать популяцию по префиксу
vault lease revoke -prefix <problem-mount>/

# Долгосрочная защита — quota (Enterprise)
vault write sys/quotas/lease-count/global max_leases=300000
```

### 5. Подготовка к инциденту (заранее)

* Настроены rate limit quotas на login-пути и lease count quotas (см. [quotas](./quotas.md)).
* Audit device включён и логи идут во внешнее хранилище с ротацией (см. [audit-логи](./audit_log_analysis.md)).
* Break-glass политика: оператор с `update`,`sudo` на `sys/step-down`, `sys/rekey`, `sys/rotate` — и процедура, как им пользоваться.
* Runbook: где лежат accessors, кто держит unseal-ключи, эскалация в HashiCorp Support.

## Устранение неполадок

| Симптом | Причина | Действия |
| :--- | :--- | :--- |
| `lease count quota exceeded` (429) | Исчерпан quota | Поднять `max_leases` либо mass revoke утечки |
| `rate limit quota exceeded` (429) после mass revoke | Всплеск рестартов клиентов | Временно поднять rate quota, `-sync` для контроля |
| Отзыв БД-lease падает | Секрет уже удалён в БД | `-force -prefix` + привести в соответствие |
| Токен отозван, но доступ остаётся | Работают дети-сироты | Полный отзыв (без `-mode=orphan`), поиск детей по audit |
| Mass revoke по `-mode=path` ничего не нашёл | Неверный префикс auth-пути | `vault auth list`, префикс с завершающим `/` |
| `permission denied` на revoke | Нет capability `update` на `sys/leases/revoke*`, `auth/token/revoke` | Break-glass политика |

## Лучшие практики

* Порядок в инциденте: сначала скоупинг по audit (что утекло), потом отзыв, потом ротация в целевых системах — mass revoke без скоупа создаёт второй инцидент.
* `-mode=orphan` — только осознанно (оставить дочерние для легитимных процессов), никогда при утечке.
* `-force` — исключительный инструмент; после него — сверка состояния lease с целевой системой.
* Отзыв токенов не отзывает lease: утечка токена и утечка кредов — разные операции.
* Синхронность (`-sync`) в критичном окне: подтверждённый отзыв важнее скорости.
* После инцидента — ретроспектива: почему TTL отсутствовал, почему quota не сработал, почему audit не показал аномалию заранее.

## Дополнительная информация

* [Анализ audit-логов](./audit_log_analysis.md) — скоупинг инцидента
* [Rate limit и lease quotas](./quotas.md) — защита от перебора и lease explosion
* [Обслуживание кластера](./cluster-maintenance.md) — step-down, апгрейды, availability
* [Восстановление из бэкапа](./backup_restore_strategies.md) — потеря кластера
* [Основные концепции](../concepts.md) — токены, lease, rekey/rotate
* [Общие антипаттерны](../common_antipatterns.md) — операционные ошибки, ведущие к инцидентам

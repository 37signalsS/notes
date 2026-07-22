# Репликация в 389DS

## Определения

**Multi-Master Replication (MMR)** — топология, в которой несколько серверов (Supplier) одновременно могут принимать изменения в базу данных. Все изменения автоматически распространяются между всеми участниками кластера.

**Replica ID** — уникальное число (от 1 до 65534), идентифицирующее конкретный мастер-сервер в топологии.

**Replication Agreement (Соглашение о репликации)** — объект конфигурации на одном сервере, описывающий, как и куда отправлять изменения (на какой хост, порт, по какому протоколу и под какой учетной записью).

**Changelog** — специальный журнал изменений, используемый плагином репликации для отслеживания операций, которые необходимо передать другим узлам.

## Базовые концепции

### Роли серверов

-   **Supplier (Поставщик):** Содержит основную копию данных, ведет Changelog и может инициировать репликацию на другие узлы. В Multi-Master топологии все узлы являются Supplier.
-   **Consumer (Потребитель):** Содержит копию данных "только для чтения". Получает обновления от Supplier, но сам не инициирует их дальше.
-   **Hub (Концентратор):** Получает обновления от Supplier и пересылает их другим Consumer. Сам не хранит Changelog для своих изменений (так как работает в режиме Read-only), но хранит Changelog для пересылки.

### Разрешение конфликтов

В Multi-Master среде возможны одновременные изменения одной и той же записи. 389DS использует:
-   **CSN (Change Sequence Number):** Каждому изменению присваивается уникальный номер, включающий временную метку и Replica ID. Побеждает изменение с более поздней меткой.
-   **Conflict Entries:** Если запись была создана одновременно с одинаковым именем, одна из них переименовывается в "конфликтную" (с добавлением уникального суффикса) для ручного разбора.

### Безопасность

Для промышленной эксплуатации (Production) репликация **обязана** использовать шифрование:
-   **LDAPS (порт 636):** Соединение защищено TLS с момента установления.
-   **StartTLS (порт 389):** Переключение обычного соединения в защищенный режим.
-   **Simple Bind + TLS:** Рекомендуемый метод аутентификации менеджера репликации.

## Практические сценарии

### Настройка Multi-Master репликации (2 узла)

Предполагается, что оба сервера запущены в Docker (см. [Docker развертывание](./docker.md)) и имеют доступ друг к другу по именам `ldap-01` и `ldap-02`.

#### 1. Включение репликации на каждом узле

На **ldap-01** (Replica ID: 1):
```bash
docker exec 389ds dsconf localhost replication enable \
  --suffix "dc=example,dc=com" \
  --role supplier \
  --replica-id 1 \
  --bind-dn "cn=replication manager,cn=config" \
  --bind-passwd "StrongPassword"
```

На **ldap-02** (Replica ID: 2):
```bash
docker exec 389ds dsconf localhost replication enable \
  --suffix "dc=example,dc=com" \
  --role supplier \
  --replica-id 2 \
  --bind-dn "cn=replication manager,cn=config" \
  --bind-passwd "StrongPassword"
```

#### 2. Создание соглашений о репликации (Replication Agreements)

На **ldap-01** для отправки данных на **ldap-02**:
```bash
docker exec 389ds dsconf localhost repl-agmt create \
  --suffix "dc=example,dc=com" \
  --host "ldap-02" \
  --port 3389 \
  --conn-protocol LDAP \
  --bind-dn "cn=replication manager,cn=config" \
  --bind-passwd "StrongPassword" \
  --bind-method SIMPLE \
  "agmt-to-ldap-02"
```

На **ldap-02** для отправки данных на **ldap-01**:
```bash
docker exec 389ds dsconf localhost repl-agmt create \
  --suffix "dc=example,dc=com" \
  --host "ldap-01" \
  --port 3389 \
  --conn-protocol LDAP \
  --bind-dn "cn=replication manager,cn=config" \
  --bind-passwd "StrongPassword" \
  --bind-method SIMPLE \
  "agmt-to-ldap-01"
```

#### 3. Инициализация данных

Выполняется **только на одном** из серверов для первичной синхронизации базы.

```bash
docker exec 389ds dsconf localhost repl-agmt init \
  --suffix "dc=example,dc=com" "agmt-to-ldap-02"
```

### Мониторинг и проверка

Просмотр текущего состояния соглашения:
```bash
docker exec 389ds dsconf localhost repl-agmt status \
  --suffix "dc=example,dc=com" "agmt-to-ldap-02"
```

**Ожидаемый результат:** `Replication successfully completed` или `Incremental update succeeded`.

## Дополнительная информация

### Управление Changelog

Журнал изменений может занимать много места. Его параметры настраиваются глобально:
-   **Max age:** Время хранения изменений (рекомендуется 7-14 дней).
-   **Max entries:** Максимальное количество записей.

```bash
# Пример настройки времени хранения
dsconf localhost replication set --suffix "dc=example,dc=com" --repl-keep-history-interval "7d"
```

### Рекомендации (Best Practices)

1.  **Синхронизация времени:** Репликация критически зависит от времени. Всегда используйте NTP (Chrony) на хостах.
2.  **Уникальность Replica ID:** Никогда не используйте одинаковые ID для разных мастеров — это приведет к потере данных и конфликтам, которые невозможно разрешить автоматически.
3.  **Изоляция трафика:** По возможности используйте выделенную сеть для трафика репликации.
4.  **Фракционная репликация:** Если на некоторые узлы не нужно передавать определенные атрибуты (например, только для чтения в DMZ), используйте Fractional Replication.

### Troubleshooting

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `Can't contact LDAP server` | Сетевой экран или неверный порт | Проверьте `ping` и `telnet` на порты 3389/3636 |
| `Invalid credentials` | Ошибка в пароле Replication Manager | Обновите пароль в соглашении через `repl-agmt set` |
| `Replica has no root RUV` | Ошибка инициализации | Повторно запустите `repl-agmt init` |
| Огромные лаги (Backlog) | Медленный диск или сеть | Проверьте IOPS на разделе с `/data/db` |

### Связанные материалы

-   [Обзор 389DS](./overview.md) — базовые понятия и архитектура
-   [Docker развертывание](./docker.md) — запуск контейнеров для кластера
-   [Плагины](./plugins.md) — работа плагина репликации и Retro Changelog

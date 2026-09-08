# Плагины 389 Directory Server (389DS)

## Определения

**Плагины 389DS** — динамически загружаемые модули (Shared Objects, `.so`), расширяющие базовую функциональность LDAP-сервера. Они интегрируют логику обработки данных непосредственно в жизненный цикл операций LDAP (поиск, модификация, аутентификация).

**Бинарный плагин (Binary Plugin)** — стандартный плагин, поставляемый с дистрибутивом 389DS и скомпилированный под целевую ОС и архитектуру (x86_64, aarch64). Включает как встроенные (built-in), так и опциональные модули.

**Плагин стороннего разработчика (Custom Plugin)** — модуль, разработанный для специфических задач (например, интеграция с внутренней базой паролей). В отличие от overlays в OpenLDAP, 389DS-плагины имеют полный доступ к SLAPI и могут изменять любые атрибуты записей, включая операционные.

**SLAPI (Service Layer API)** — программный интерфейс, используемый для написания плагинов. Большинство стандартных функций 389DS (репликация, контроль доступа) реализованы через этот интерфейс. Каждый плагин должен реализовывать стандартные callback-функции: `plugin_start`, `plugin_init`, `pre_operation`, `post_operation`, `do_modify`, `do_search` и другие, в зависимости от категории.

**Жизненный цикл плагина** — последовательность этапов, через которые проходит плагин во время работы сервера:
1. **Загрузка (Load)** — чтение `.so` файла и символов из `cn=plugins,cn=config`.
2. **Инициализация (Init)** — выделение памяти, проверка параметров, установка зависимостей.
3. **Активная работа** — обработка операций в зависимости от типа (pre/post/internal).
4. **Завершение (Close)** — освобождение ресурсов при остановке экземпляра.

**Зависимости плагинов (Plugin Dependencies)** — механизм `nsslapd-plugin-depends-on-named`, гарантирующий порядок загрузки. Например, `MemberOf` зависит от ядра базы данных и должен загружаться после бэкенда LMDB, но до плагинов, изменяющих членство в группах.

**dsconf** — современная утилита командной строки для управления конфигурацией. В актуальных версиях 389DS она является предпочтительным инструментом (Single Source of Truth) для изменения настроек плагинов в `cn=config`. Утилита поддерживает atomic-операции, rollback при ошибках и экспорт/импорт в LDIF.

**Fixup-задача (Fixup Task)** — фоновая операция для приведения существующих данных в соответствие с новыми правилами плагина. Критична при включении таких механизмов, как `MemberOf` или `DNA` на уже наполненной базе. Fixup запускается как отдельный поток и не блокирует сервер на запись (thread per operation), но создает дополнительную нагрузку на I/O и LMDB-кэш.

## Базовые концепции

### Категории плагинов (Plugin Types)

Плагины классифицируются по этапу их вызова сервером:

| Тип | Описание | Примеры |
| :--- | :--- | :--- |
| **Pre-operation** | Вызываются *до* записи в базу или выполнения поиска. Могут отклонить операцию. | Проверка сложности пароля, аутентификация. |
| **Post-operation** | Вызываются *после* успешной записи. Используются для побочных эффектов. | Репликация, обновление обратных ссылок. |
| **Internal-operation** | Вызываются для операций, инициированных самим сервером (не клиентом). | Синхронизация данных плагинами. |
| **Database** | Отвечают за хранение и индексацию данных на диске. | Бэкенд LMDB. |
| **Extended-operation** | Добавляют новые OID операций (например, StartTLS или WHOAMI). | Команды администрирования. |
| **Matching rule** | Определяют логику сравнения и поиска атрибутов. | Сравнение телефонных номеров или DN. |

### Жизненный цикл и порядок выполнения

Сервер загружает плагины в порядке, определенном в `cn=plugins,cn=config`. Изменение порядка влияет на цепочку преобразований. Например, если `Attribute Uniqueness` загружен после `MemberOf`, проверка уникальности будет выполняться после добавления атрибута членства, что может привести к ложным конфликтам.

С помощью `dsconf` можно настроить явные зависимости:

```bash
dsconf -D "cn=Directory Manager" ldap://localhost:3389 plugin linked-attrs config add "Manager-Employee" \
  --link-attr managedBy \
  --managed-attr manages \
  --scope "dc=example,dc=com"
dsconf -D "cn=Directory Manager" ldap://localhost:3389 plugin linked-attrs config "Manager-Employee" set \
  --depends-on-named memberof
```

### Производительность и безопасность плагинов

Каждый активный плагин добавляет latency к операциям записи (LDAP Add/Modify/Delete). Pre-operation плагины выполняются синхронно в потоке клиентского запроса и напрямую влияют на время ответа. Post-operation плагины также синхронны, но могут быть оптимизированы через `update-delay` (как в Referential Integrity) для пакетной обработки.

Плагины, модифицирующие индексированные атрибуты (например, `memberOf`, `uidNumber`), вызывают обновление LMDB-индексов в реальном времени. При высокой частоте изменений это становится узким местом.

### Ключевые плагины и их назначение

| Плагин | Категория | Назначение |
| :--- | :--- | :--- |
| **MemberOf** | Автоматизация | Создает атрибут `memberOf` у пользователя на основе членства в группах. |
| **Referential Integrity** | Целостность | Удаляет ссылки на удаленный объект (DN) из других записей. |
| **Attribute Uniqueness** | Безопасность | Гарантирует уникальность значения атрибута (например, `mail` или `uid`) во всем дереве. |
| **DNA (Distributed Numeric Assignment)** | Автоматизация | Назначает уникальные числовые ID (`uidNumber`) в распределенной среде. |
| **USN (Update Sequence Number)** | Синхронизация | Добавляет порядковый номер изменений для каждой записи (аналог USN в Active Directory). |
| **Retro Changelog** | Аудит | Хранит историю изменений в формате LDIF для внешних коннекторов. |
| **Account Policy** | Безопасность | Управление временем жизни паролей и блокировкой неактивных аккаунтов. |
| **Linked Attributes** | Автоматизация | Создает двусторонние связи между записями (managedBy ↔ manages). |
| **Password Policy** | Безопасность | Принудительная смена пароля, история паролей, проверка сложности. |
| **7-bit Check** | Безопасность | Валидация строк на наличие 7-бит чистых ASCII-символов (устаревший при использовании UTF-8). |

## Практические сценарии

### Плагин MemberOf

Автоматически добавляет пользователю атрибут `memberOf`, содержащий DN всех групп, в которых он состоит.

**Включение и настройка:**

```bash
# Включить плагин
dsconf -D "cn=Directory Manager" ldap://localhost:3389 plugin memberof enable

# Настроить область действия (scope)
dsconf -D "cn=Directory Manager" ldap://localhost:3389 plugin memberof set --scope "dc=example,dc=com"

# Настроить группу администраторов, изменения которой отслеживаются
dsconf -D "cn=Directory Manager" ldap://localhost:3389 plugin memberof set --group-attr member

# Исключить определенные группы из автоматического обновления
dsconf -D "cn=Directory Manager" ldap://localhost:3389 plugin memberof set --skip-nested "cn=admins,dc=example,dc=com"

# Перезапуск экземпляра обязателен для активации
dsctl localhost restart
```

**Обновление существующих данных (Fixup):**
Если в базе уже есть группы и пользователи, после включения плагина нужно запустить задачу пересчета. На больших базах (более 100 000 записей) фикс должен выполняться в часы низкой нагрузки, так как генерирует значительный I/O.

```bash
# Запуск fixup с явным указанием базы (полезно при нескольких суффиксах)
dsconf -D "cn=Directory Manager" ldap://localhost:3389 plugin memberof fixup "dc=example,dc=com"

# Проверка прогресса через access log (поиск memberof fixup)
tail -f /var/log/dirsrv/slapd-localhost/access | grep --line-buffered "fixup"
```

**Валидация после включения:**

```bash
# Проверка наличия атрибута memberOf у пользователя
ldapsearch -x -LLL -H ldap://localhost:3389 -D "cn=Directory Manager" -W -b "dc=example,dc=com" "(uid=jdoe)" memberOf

# Ожидаемый вывод: memberOf: cn=developers,dc=example,dc=com
```

### Плагин Referential Integrity (Целостность ссылок)

Гарантирует, что при удалении или переименовании записи (например, пользователя) его старый DN будет удален из всех атрибутов членства в группах.

**Настройка:**

```bash
# Включение
dsconf -D "cn=Directory Manager" ldap://localhost:3389 plugin referential-integrity enable

# Настройка отслеживаемых атрибутов
dsconf -D "cn=Directory Manager" ldap://localhost:3389 plugin referential-integrity set \
  --membership-attr member \
  --membership-attr uniqueMember \
  --membership-attr manager

# Ограничение области действия (только определенный суффикс)
dsconf -D "cn=Directory Manager" ldap://localhost:3389 plugin referential-integrity set \
  --scope "dc=example,dc=com"

# Установка задержки обновления (рекомендуется 5-10 сек для снижения нагрузки)
dsconf -D "cn=Directory Manager" ldap://localhost:3389 plugin referential-integrity set --update-delay 5

# Отслеживание переименований (rename-aware)
dsconf -D "cn=Directory Manager" ldap://localhost:3389 plugin referential-integrity set --update-delay 5
```

**Валидация:**

```bash
# Создание тестового пользователя и группы
ldapmodify -x -H ldap://localhost:3389 -D "cn=Directory Manager" -W <<EOF
dn: cn=testgroup,dc=example,dc=com
changetype: modify
add: member
member: uid=testuser,dc=example,dc=com
EOF

# Удаление пользователя — member из группы должен исчезнуть автоматически
ldapdelete -x -H ldap://localhost:3389 -D "cn=Directory Manager" -W "uid=testuser,dc=example,dc=com"
```

### Плагин Attribute Uniqueness (Уникальность атрибутов)

Гарантирует, что определенные значения (например, Email или UID) не будут продублированы в дереве.

**Настройка уникальности Email и UID:**

```bash
# Добавление конфигурации для атрибута mail
dsconf -D "cn=Directory Manager" ldap://localhost:3389 plugin attribute-uniqueness add "Unique Email" \
  --attr mail \
  --base-dn "dc=example,dc=com"

# Добавление конфигурации для атрибута uid
dsconf -D "cn=Directory Manager" ldap://localhost:3389 plugin attribute-uniqueness add "Unique UID" \
  --attr uid \
  --base-dn "dc=example,dc=com"

# Включение плагина (если еще не включен)
dsconf -D "cn=Directory Manager" ldap://localhost:3389 plugin attribute-uniqueness enable

# Проверка статуса
dsconf -D "cn=Directory Manager" ldap://localhost:3389 plugin attribute-uniqueness status
```

**Важно:** Плагин проверяет уникальность только внутри указанного `--base-dn`. При наличии нескольких суффиксов требуется отдельная конфигурация для каждого.

### Плагин Linked Attributes (Связанные атрибуты)

Позволяет создавать двусторонние связи между записями. Если вы указываете `managedBy` у пользователя, плагин автоматически обновит атрибут `manages` у менеджера.

**Пример настройки:**

```bash
# Создание конфигурации связи
dsconf -D "cn=Directory Manager" ldap://localhost:3389 plugin linked-attrs config add "Manager-Employee" \
  --link-attr managedBy \
  --managed-attr manages \
  --scope "dc=example,dc=com"

# Проверка работы: при изменении managedBy у пользователя
ldapmodify -x -H ldap://localhost:3389 -D "cn=Directory Manager" -W <<EOF
dn: uid=jdoe,dc=example,dc=com
changetype: modify
add: managedBy
managedBy: cn=manager1,dc=example,dc=com
EOF

# У менеджера cn=manager1 автоматически появится uid=jdoe в атрибуте manages
```

### Плагин DNA (Автоматическое назначение ID)

Используется для генерации уникальных числовых идентификаторов (`uidNumber`, `gidNumber`). В распределенной среде (Multi-Master) крайне важно разделить диапазоны, чтобы избежать конфликтов.

**Настройка для мастера №1:**

```bash
dsconf -D "cn=Directory Manager" ldap://localhost:3389 plugin dna config "POSIX UID" add \
  --type uidNumber \
  --next-value 1000 \
  --max-value 5000 \
  --filter "(objectclass=posixAccount)" \
  --scope "dc=example,dc=com"
```

**Настройка для мастера №2:**
Те же параметры, но `--next-value 5001` и `--max-value 10000`.

**Восстановление при исчерпании диапазона:**
Если диапазон исчерпан (например, на мастере №1 добавлено 4001 пользователь), расширьте верхнюю границу или создайте новый конфиг-блок:

```bash
# Добавление дополнительного блока на том же мастере
dsconf -D "cn=Directory Manager" ldap://localhost:3389 plugin dna config "POSIX UID" add \
  --type uidNumber \
  --next-value 5001 \
  --max-value 10000 \
  --filter "(objectclass=posixAccount)" \
  --scope "dc=example,dc=com"
```

**Проверка текущих значений:**

```bash
dsconf -D "cn=Directory Manager" ldap://localhost:3389 plugin dna config "POSIX UID" show
# Вывод: type=uidNumber, nextValue=1247, magicUser=cn=magicUser,...
```

### Плагин Retro Changelog

Хранит историю изменений в суффиксе `cn=changelog`. Эти данные используются внешними системами (например, Keycloak или IDM) для синхронизации.

**Включение и оптимизация:**

```bash
# Включение
dsconf -D "cn=Directory Manager" ldap://localhost:3389 plugin retro-changelog enable

# Настройка очистки (хранить 7 дней или 100 000 записей)
dsconf -D "cn=Directory Manager" ldap://localhost:3389 plugin retro-changelog set \
  --max-age "7d" \
  --max-entries 100000

# Настройка атрибутов, которые попадают в changelog (по умолчанию все)
dsconf -D "cn=Directory Manager" ldap://localhost:3389 plugin retro-changelog set \
  --attr list uid,cn,sn,mail

# Исключение чувствительных атрибутов из changelog
dsconf -D "cn=Directory Manager" ldap://localhost:3389 plugin retro-changelog set \
  --exclude-attr userPassword,sshPublicKey
```

**Репликация changelog между мастерами:**
В MMR changelog не реплицируется автоматически. Для внешних синхронизаций используйте общий Retro Changelog на выделенном Supplier-узле или настройте `Retro Changelog Plugin` на каждом мастере с последующим агрегированием на стороне потребителя.

### Плагин Account Policy

Управляет временем жизни паролей, блокировкой неактивных аккаунтов и историей паролей. Важен для соответствия политикам безопасности (password aging).

**Включение и настройка:**

```bash
# Включение плагина
dsconf -D "cn=Directory Manager" ldap://localhost:3389 plugin account-policy-enable enable

# Настройка политики: пароль действителен 90 дней, предупреждение за 14 дней
dsconf -D "cn=Directory Manager" ldap://localhost:3389 plugin account-policy-enable set \
  --state-attr accountStatus \
  --bind-policy-bindDN "cn=Account Policy Plugin,cn=plugins,cn=config"

# Создание политики для обычных пользователей
dsconf -D "cn=Directory Manager" ldap://localhost:3389 plugin account-policy-enable policy add "Default Policy" \
  --attr accountStatus \
  --always-record-login yes \
  --expire 90 \
  --warn 14 \
  --grace 0 \
  --limit 0 \
  --scope "dc=example,dc=com"

# Проверка работы: привязка пользователя, у которого срок пароля истек
ldapwhoami -x -H ldap://localhost:3389 -D "uid=expireduser,dc=example,dc=com" -w password
# Ожидаемый вывод: error (49) или специфичный error с расширением account policy
```

## Дополнительная информация

### Безопасное включение плагинов в production

При включении плагинов на рабочем сервере выполняйте следующий протокол:

1. **Pre-flight проверка:**
   - Создайте бэкап базы (`dsctl localhost db2ldif -a backup_before_plugins.ldif`).
   - Проверьте права на файлы плагинов: `ls -l /usr/lib64/dirsrv/plugins/`.
   - Убедитесь, что требуемые индексы существуют (`dsconf -D "cn=Directory Manager" ldap://localhost:3389 backend suffix list` → `index config get`).

2. **Canary-запуск:**
   - Включите плагин на тестовом инстансе с копией production-базы.
   - Нагрузите плагин через `ldapsearch` с фильтром по ключевому атрибуту.
   - Сравните latency до и после (`time ldapsearch ...`).

3. **Мониторинг после включения:**
   - Отслеживайте `error` и `access` логи в реальном времени.
   - Следите за LRU-кэшем LMDB (`dsctl localhost memusage`).
   - Контролируйте CPU и I/O wait (`iostat -x 1`, `pidstat -p $(pgrep ns-slapd) 1`).

### Автоматизация управления плагинами

Управление плагинами через `dsconf` легко автоматизируется в скриптах и системах управления конфигурацией (Ansible, Puppet, Chef). Рекомендуемый подход — управление через LDIF-файлы для атомарных изменений:

```bash
# Экспорт текущей конфигурации плагина в LDIF
dsconf -D "cn=Directory Manager" ldap://localhost:3389 plugin memberof get > /tmp/memberof.ldif

# Применение конфигурации из LDIF
dsconf -D "cn=Directory Manager" ldap://localhost:3389 plugin memberof set --suffix "dc=example,dc=com" --update-delay 5
```

### Управление плагинами в контейнеризированной среде

При развертывании 389DS в Docker или Kubernetes сохраняйте конфигурацию плагинов в volumes, иначе изменения будут утеряны при пересоздании контейнера:

```bash
# Docker Compose: монтирование конфигурации
volumes:
  - ./ds_config:/data/config:Z

# После входа в контейнер управление идентично хостовой ОС
docker exec -it 389ds dsconf -D "cn=Directory Manager" ldap://localhost:3389 plugin memberof enable
```

### Мониторинг производительности плагинов

Для диагностики влияния плагинов используйте `access` лог с полем `etime` (время выполнения операции):

```bash
# Поиск операций, выполнявшихся более 100 мс
grep "etime=1" /var/log/dirsrv/slapd-localhost/access | awk -F'etime=' '{print $2}' | cut -d' ' -f1 | sort -rn | head -20

# Поиск операций конкретного плагина (MemberOf)
grep "plugin memberof" /var/log/dirsrv/slapd-localhost/access
```

При высокой частоте операций записи (более 1000 записей/сек) анализируйте:
- LRU-кэш LMDB (`dsctl localhost memusage`) — размер и процент попаданий (hit ratio).
- Количество отложенных операций Referential Integrity (`update-delay` не должен быть меньше времени, необходимого на обработку батча).
- Размер очереди fixup-задач (при включении плагинов на больших базах).

### Управление через Shared Config

В современных версиях 389DS настройки плагинов могут реплицироваться автоматически, если включен механизм **Shared Configuration**.

1. Настройки в `cn=config` по умолчанию локальны для каждого узла.
2. Чтобы изменения плагинов применялись на всем кластере, используйте:

```bash
# Включение shared config на всех мастерах
dsconf -D "cn=Directory Manager" ldap://localhost:3389 config replace nsslapd-shared-config=on

# После этого любые изменения плагинов через dsconf реплицируются
```

**Важно:** Shared Config реплицирует только конфигурацию `cn=config`, но не данные плагинов (например, `memberOf` генерируется локально на каждом узле и реплицируется как обычные атрибуты записей).

### Рекомендации (Best Practices)

1. **Минимизация активных плагинов:** Каждый плагин — это дополнительная задержка (latency) при операциях записи. Отключайте неиспользуемые (например, `7-bit check`, если вы используете UTF-8).
2. **Порядок выполнения (Precedence):** Сервер выполняет плагины в порядке их перечисления в `cn=plugins,cn=config`. Это важно для цепочек преобразований.
3. **Индексация:** Если плагин фильтрует данные по атрибуту (как `MemberOf` или `DNA`), убедитесь, что этот атрибут проиндексирован (`eq`), иначе производительность резко упадет.
4. **Безопасность:** Некоторые плагины (например, `Retro Changelog`) могут содержать чувствительные данные в логах. Ограничивайте доступ к `cn=changelog` через ACI.
5. **Фиксация версий конфигурации:** При развертывании через IaC фиксируйте вывод `dsconf plugin ... show` в репозитории и используйте `diff` при обновлениях, чтобы обнаруживать нежелательные изменения.
6. **Регулярный аудит:** Раз в квартал проверяйте активные плагины (`dsconf plugin list`) и удаляйте неиспользуемые.
7. **Лимиты ресурсов:** Для плагинов, обрабатывающих большие объемы данных (DNA, Retro Changelog), убедитесь, что `ulimit -n` (open files) на уровне ОС не ниже 65535, иначе фиксы будут падать с `Too many open files`.

### Troubleshooting

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `memberOf` не отображается | Плагин не включен или не запущен fixup | Включите плагин и запустите задачу `fixup`. |
| Ошибки при удалении групп | `Referential Integrity` работает слишком долго | Увеличьте `update-delay` или добавьте индексы на атрибуты `member`. |
| Дубликаты UID/GID (DNA) | Пересечение диапазонов в MMR | Проверьте `next-value` на всех мастерах; используйте непересекающиеся блоки. |
| Плагин не загружается | Ошибка прав на `.so` файл или архитектура | Проверьте `errors` лог; убедитесь, что бинарный файл плагина доступен пользователю `dirsrv`. |
| Высокая нагрузка на CPU | Слишком много Pre-op плагинов | Профилируйте время выполнения операций через `access` лог (поле `etime`). |
| Deadlock при модификации записей | Циклические зависимости между плагинами | Проверьте `nsslapd-plugin-depends-on-named` и исключите кольцевые зависимости. |
| Утечка памяти в кастомном плагине | Плагин не освобождает память в `plugin_close` | Используйте `valgrind` или `jemalloc` профилирование; обновите плагин. |
| `Too many open files` при fixup | `ulimit -n` слишком низкий для обработки большого числа записей | Увеличьте `ulimit -n` до 65536 в systemd-юните или в Docker (`--ulimit nofile=65536:65536`). |
| Плагин игнорирует изменения | Кэш конфигурации не обновлен | Выполните `dsconf ... config flush` или перезапустите экземпляр. |
| Retro Changelog не реплицируется | Плагин локальный, replication отсутствует | Настройте Retro Changelog на каждом мастере отдельно или используйте выделенный узел агрегации. |
| Account Policy не блокирует пользователя | Не настроен атрибут `accountStatus` или отсутствует политика | Проверьте наличие атрибута в записи пользователя и наличие активной политики через `dsconf ... plugin account-policy-enable policy list`. |

### Связанные материалы

- [Управление доступом (ACI)](./aci.md) — связь плагинов авторизации с правами доступа
- [Docker развёртывание](./docker.md) — использование утилит внутри контейнера
- [Репликация](./replication.md) — особенности работы плагинов в кластере
- [Обзор 389DS](./overview.md) — архитектура и жизненный цикл экземпляра

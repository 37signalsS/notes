# Репликация в 389 Directory Server (389DS)

## Определения

**Multi-Master Replication (MMR)** — топология, в которой несколько серверов (Supplier) одновременно могут принимать изменения в базу данных. Все изменения автоматически распространяются между всеми участниками кластера.

**Replica ID** — уникальное число (от 1 до 65534), идентифицирующее конкретный мастер-сервер в топологии. Должен быть уникальным в рамках всего кластера.

**CSN (Change Sequence Number)** — уникальный идентификатор каждого изменения. Состоит из временной метки, порядкового номера операции и Replica ID. Формат: `time_stamp | sequence | replica_id`. CSN генерируется на стороне мастера при изменении записи.

**RUV (Replica Update Vector)** — вектор состояния репликации, хранящий информацию о том, какие изменения (по CSN) сервер уже получил от каждого мастера. Используется для определения необходимости синхронизации и построения графа состояния кластера.

**Replication Agreement (Соглашение о репликации)** — объект конфигурации на одном сервере, описывающий, как и куда отправлять изменения (на какой хост, порт, по какому протоколу и под какой учетной записью).

**Changelog** — специальный журнал изменений, используемый плагином репликации для отслеживания операций, которые необходимо передать другим узлам. В 389DS 3.x хранится в LMDB.

**Retro Changelog** — плагин, который хранит историю изменений в суффиксе `cn=changelog`. Используется внешними системами (например, Keycloak или IDM) для синхронизации. Подробнее: [Плагины](./plugins.md).

**Fractional Replication (Фракционная репликация)** — режим, при котором из процесса репликации исключаются определенные атрибуты. Полезно для реплик в DMZ, куда не должны попадать хэши паролей или персональные данные.

**Consumer (Потребитель)** — сервер, содержащий копию данных "только для чтения". Получает обновления от Supplier, но сам не инициирует их дальше.

**Hub (Концентратор)** — сервер, получающий обновления от Supplier и пересылающий их другим Consumer. Сам не хранит Changelog для своих изменений (работает в режиме Read-only), но хранит Changelog для пересылки.

**Supplier (Поставщик)** — сервер, содержащий основную копию данных, ведущий Changelog и инициирующий репликацию на другие узлы. В Multi-Master топологии все узлы являются Supplier.

**Total Init (Полная инициализация)** — процесс первичной синхронизации, при котором Consumer получает полную копию данных от Supplier.

**Delta/Differential Init (Дельта-инициализация)** — процесс, при котором Consumer получает только изменения, начиная с момента последней успешной синхронизации.

**CleanAllRUV** — специальный плагин и процедура для безопасного удаления информации о недействующем Replica ID из всего кластера без остановки серверов.

**Split Brain** — состояние кластера, при котором часть мастеров временно утратила связь и продолжила принимать изменения независимо. При восстановлении связи происходит разрешение конфликтов по CSN.

## Базовые концепции

### Топологии репликации

| Топология | Описание | Использование |
| :--- | :--- | :--- |
| **Multi-Master (MMR)** | Все узлы являются мастерами, принимают запись и реплицируют изменения между собой. | Высокая доступность, распределенная запись, отсутствие single point of failure. |
| **Primary-Consumer (Master-Replica)** | Один мастер принимает все изменения, реплики получают обновления только для чтения. | Масштабирование чтения, Disaster Recovery, отчетные инстансы. |
| **Cascading (Каскадная)** | Master → Hub → Consumer. Hub получает изменения от Master и пересылает их Consumer. | Снижение сетевой нагрузки на Master, географически распределенные Consumer. |
| **Hub-Consumer** | Вариант каскадной топологии, где Hub не хранит данные для записи. | DMZ, филиалы, изоляция доступа. |

### Роли серверов

- **Supplier (Поставщик):** Содержит основную копию данных, ведет Changelog и может инициировать репликацию на другие узлы. В Multi-Master топологии все узлы являются Supplier.
- **Consumer (Потребитель):** Содержит копию данных "только для чтения". Получает обновления от Supplier, но сам не инициирует их дальше.
- **Hub (Концентратор):** Получает обновления от Supplier и пересылает их другим Consumer. Сам не хранит Changelog для своих изменений (так как работает в режиме Read-only), но хранит Changelog для пересылки.

### Разрешение конфликтов и CSN

В Multi-Master среде возможны одновременные изменения одной и той же записи. 389DS использует логику **"Последний записавший побеждает"** на основе CSN:
1.  **Сравнение меток:** При конфликте сервер сравнивает временные метки CSN.
2.  **Replica ID как Tie-breaker:** Если временные метки идентичны, побеждает CSN с большим Replica ID.
3.  **Conflict Entries:** Если запись была создана одновременно с одинаковым именем (DN), одна из них переименовывается в "конфликтную" (с атрибутом `nsds50vlv-conflict`) для ручного разбора.

**Важно:** Разница во времени (Clock Skew) более 1-2 секунд между мастерами приводит к неверному разрешению конфликтов. Используйте NTP.

### Инициализация репликации

При создании соглашения (`repl-agmt create`) и запуске инициализации (`repl-agmt init`) 389DS выбирает один из двух режимов:

- **Total Init:** Полная выгрузка всех данных суффикса с Supplier на Consumer. Используется при первом запуске соглашения или после поломки базы Consumer.
- **Delta Init:** Передача только изменений с момента последней успешной синхронизации. Используется по умолчанию при повторной инициализации, если RUV согласован.

**Принудительная полная инициализация:**
```bash
dsconf -D "cn=Directory Manager" ldap://localhost repl-agmt init \
  --suffix "dc=example,dc=com" \
  --init-full "agmt-to-ldap-02"
```

### Механизм RUV и CleanAllRUV

RUV является "картой" знаний сервера о состоянии всего кластера. Он содержит максимальный CSN, известный для каждого Replica ID.
- **Проблема удаленных узлов:** Если мастер-сервер удаляется из кластера навсегда, информация о его Replica ID остается в RUV всех остальных узлов, что может вызывать ошибки мониторинга.
- **CleanAllRUV:** Специальный плагин и процедура для безопасного удаления информации о недействующем Replica ID из всего кластера без остановки серверов.

### Безопасность

Для промышленной эксплуатации (Production) репликация **обязана** использовать шифрование:
- **LDAPS (порт 636):** Соединение защищено TLS с момента установления.
- **StartTLS (порт 389):** Переключение обычного соединения в защищенный режим.
- **Replication Manager:** Рекомендуется использовать выделенную учетную запись (например, `cn=replication manager,cn=config`) с минимальными правами, необходимыми для репликации.

**Минимальные права для Replication Manager:**
```bash
dsconf -D "cn=Directory Manager" ldap://localhost aci add \
  --suffix "dc=example,dc=com" \
  --id repl_mgr_aci \
  --name "Replication Manager ACI" \
  --desc "Allow replication operations" \
  --attrs "entrycsn,entryuuid,parentid,ds-sync-conflict,nsuniqueid,userpassword,aci" \
  --bindtype "all" \
  --binddn "cn=replication manager,cn=config" \
  --authz "self" \
  --allow "read,search,compare,write"
```

**Важно:** Настройте SSF (Security Strength Factor), чтобы запретить репликацию по незащищенному каналу:
```bash
dsconf -D "cn=Directory Manager" ldap://localhost config replace \
  nsslapd-minssf=128 \
  nsslapd-minssf-exclude-rootdn=off
```

### Мониторинг и диагностика

**RUV и состояние соглашений:**
```bash
# Просмотр RUV кластера (кто от кого и что получил)
dsconf -D "cn=Directory Manager" ldap://localhost replication get-ruv \
  --suffix "dc=example,dc=com"

# Проверка статуса конкретного соглашения
dsconf -D "cn=Directory Manager" ldap://localhost repl-agmt status \
  --suffix "dc=example,dc=com" "agmt-to-ldap-02"

# Детальная информация о соглашении
dsconf -D "cn=Directory Manager" ldap://localhost repl-agmt get \
  --suffix "dc=example,dc=com" "agmt-to-ldap-02"
```

**Обнаружение проблем в логах:**
```bash
# Поиск ошибок репликации в access log
grep -i "repl" /var/log/dirsrv/slapd-localhost/access | tail -n 50

# Поиск проблем с RUV в errors log
grep -i "ruv\|replica" /var/log/dirsrv/slapd-localhost/errors | tail -n 50

# Проверка размера backlog (непереданных изменений)
dsconf -D "cn=Directory Manager" ldap://localhost repl-agmt status \
  --suffix "dc=example,dc=com" "agmt-to-ldap-02" | grep -i "backlog"
```

## Практические сценарии

### Настройка Multi-Master репликации (2 узла, Bare-metal / VM)

Предполагается, что оба сервера настроены с суффиксом `dc=example,dc=com`.

#### 1. Включение роли Supplier на каждом узле

На **ldap-01** (Replica ID: 1):
```bash
dsconf -D "cn=Directory Manager" ldap://localhost replication enable \
  --suffix "dc=example,dc=com" \
  --role supplier \
  --replica-id 1 \
  --bind-dn "cn=replication manager,cn=config" \
  --bind-passwd "StrongPassword"
```

На **ldap-02** (Replica ID: 2):
```bash
dsconf -D "cn=Directory Manager" ldap://ldap-02 replication enable \
  --suffix "dc=example,dc=com" \
  --role supplier \
  --replica-id 2 \
  --bind-dn "cn=replication manager,cn=config" \
  --bind-passwd "StrongPassword"
```

#### 2. Создание защищенного соглашения (LDAPS)

На **ldap-01** для отправки данных на **ldap-02**:
```bash
dsconf -D "cn=Directory Manager" ldap://localhost repl-agmt create \
  --suffix "dc=example,dc=com" \
  --host "ldap-02.example.com" \
  --port 636 \
  --conn-protocol LDAPS \
  --bind-dn "cn=replication manager,cn=config" \
  --bind-passwd "StrongPassword" \
  --bind-method SIMPLE \
  --auto-init-method none \
  "agmt-to-ldap-02"
```

На **ldap-02** для отправки данных на **ldap-01**:
```bash
dsconf -D "cn=Directory Manager" ldap://ldap-02 repl-agmt create \
  --suffix "dc=example,dc=com" \
  --host "ldap-01.example.com" \
  --port 636 \
  --conn-protocol LDAPS \
  --bind-dn "cn=replication manager,cn=config" \
  --bind-passwd "StrongPassword" \
  --bind-method SIMPLE \
  --auto-init-method none \
  "agmt-to-ldap-01"
```

#### 3. Инициализация и валидация

```bash
# Первичная синхронизация (выполняется ОДИН раз на ОДНОМ мастере)
dsconf -D "cn=Directory Manager" ldap://localhost repl-agmt init \
  --suffix "dc=example,dc=com" "agmt-to-ldap-02"

# Проверка статуса соглашения
dsconf -D "cn=Directory Manager" ldap://localhost repl-agmt status \
  --suffix "dc=example,dc=com" "agmt-to-ldap-02"

# Просмотр всего RUV кластера
dsconf -D "cn=Directory Manager" ldap://localhost replication get-ruv \
  --suffix "dc=example,dc=com"

# Проверка логов на ошибки
tail -n 100 /var/log/dirsrv/slapd-localhost/errors | grep -i repl
```

### Настройка Multi-Master репликации (2 узла, Docker)

Предполагается, что оба сервера запущены в Docker и имеют доступ друг к другу по именам `ldap-01` и `ldap-02`.

#### 1. Включение репликации на каждом узле

На **ldap-01** (Replica ID: 1):
```bash
# Включение роли Supplier для суффикса
docker exec 389ds dsconf localhost replication enable \
  --suffix "dc=example,dc=com" \
  --role supplier \
  --replica-id 1 \
  --bind-dn "cn=replication manager,cn=config" \
  --bind-passwd "StrongPassword"
```

#### 2. Создание защищенного соглашения (TLS)

Для репликации через LDAPS (порт 636) убедитесь, что сертификаты CA импортированы на оба узла.

На **ldap-01** для отправки данных на **ldap-02**:
```bash
docker exec 389ds dsconf localhost repl-agmt create \
  --suffix "dc=example,dc=com" \
  --host "ldap-02" \
  --port 636 \
  --conn-protocol LDAPS \
  --bind-dn "cn=replication manager,cn=config" \
  --bind-passwd "StrongPassword" \
  --bind-method SIMPLE \
  "agmt-to-ldap-02"
```

#### 3. Инициализация и мониторинг

```bash
# Первичная синхронизация (выполняется ОДИН раз на ОДНОМ мастере)
docker exec 389ds dsconf localhost repl-agmt init \
  --suffix "dc=example,dc=com" "agmt-to-ldap-02"

# Проверка статуса соглашения
docker exec 389ds dsconf localhost repl-agmt status \
  --suffix "dc=example,dc=com" "agmt-to-ldap-02"

# Просмотр всего RUV кластера (кто от кого и что получил)
docker exec 389ds dsconf localhost replication get-ruv --suffix "dc=example,dc=com"
```

### Настройка каскадной репликации (Hub-Consumer)

Топология: Master → Hub → Consumer.

#### 1. Настройка Master (ldap-master)

```bash
# Включение роли Supplier
dsconf -D "cn=Directory Manager" ldap://ldap-master replication enable \
  --suffix "dc=example,dc=com" \
  --role supplier \
  --replica-id 1 \
  --bind-dn "cn=replication manager,cn=config" \
  --bind-passwd "StrongPassword"

# Создание соглашения на Hub
dsconf -D "cn=Directory Manager" ldap://ldap-master repl-agmt create \
  --suffix "dc=example,dc=com" \
  --host "ldap-hub.example.com" \
  --port 636 \
  --conn-protocol LDAPS \
  --bind-dn "cn=replication manager,cn=config" \
  --bind-passwd "StrongPassword" \
  "agmt-to-hub"

# Инициализация
dsconf -D "cn=Directory Manager" ldap://ldap-master repl-agmt init \
  --suffix "dc=example,dc=com" "agmt-to-hub"
```

#### 2. Настройка Hub (ldap-hub)

```bash
# Включение роли Supplier (для пересылки Consumer)
dsconf -D "cn=Directory Manager" ldap://ldap-hub replication enable \
  --suffix "dc=example,dc=com" \
  --role supplier \
  --replica-id 2 \
  --bind-dn "cn=replication manager,cn=config" \
  --bind-passwd "StrongPassword"

# Hub работает как Consumer для Master
dsconf -D "cn=Directory Manager" ldap://ldap-hub repl-agmt create \
  --suffix "dc=example,dc=com" \
  --host "ldap-master.example.com" \
  --port 636 \
  --conn-protocol LDAPS \
  --bind-dn "cn=replication manager,cn=config" \
  --bind-passwd "StrongPassword" \
  "agmt-to-master"

# Инициализация Hub от Master
dsconf -D "cn=Directory Manager" ldap://ldap-hub repl-agmt init \
  --suffix "dc=example,dc=com" "agmt-to-master"

# Создание Consumer на Hub для филиала
dsconf -D "cn=Directory Manager" ldap://ldap-hub repl-agmt create \
  --suffix "dc=example,dc=com" \
  --host "ldap-branch.example.com" \
  --port 636 \
  --conn-protocol LDAPS \
  --bind-dn "cn=replication manager,cn=config" \
  --bind-passwd "StrongPassword" \
  "agmt-to-branch"

# Инициализация Consumer
dsconf -D "cn=Directory Manager" ldap://ldap-hub repl-agmt init \
  --suffix "dc=example,dc=com" "agmt-to-branch"
```

### Настройка фракционной репликации для DMZ

Исключает чувствительные атрибуты из процесса репликации.

```bash
# Настройка на Supplier (исходный мастер)
dsconf -D "cn=Directory Manager" ldap://localhost repl-agmt set \
  --suffix "dc=example,dc=com" \
  --fractional-exclude "userPassword telephoneNumber employeeID nsds5replconflict" \
  "agmt-to-dmz-consumer"

# Валидация
dsconf -D "cn=Directory Manager" ldap://localhost repl-agmt get \
  --suffix "dc=example,dc=com" "agmt-to-dmz-consumer" | grep fractional
```

**Важно:** Если вы добавляете фракционную репликацию к уже существующему соглашению, Consumer требуется повторная полная инициализация:
```bash
dsconf -D "cn=Directory Manager" ldap://localhost repl-agmt init \
  --suffix "dc=example,dc=com" \
  --init-full "agmt-to-dmz-consumer"
```

### Обслуживание: Удаление узла и CleanAllRUV

Если узел `ldap-02` (ID: 2) выводится из эксплуатации, его нужно удалить из RUV всех остальных мастеров, чтобы избежать ложных алертов о лагах.

1.  Удалите соглашение о репликации на выжившем узле.
2.  Запустите задачу очистки RUV:

```bash
# На выжившем узле (ldap-01)
dsconf -D "cn=Directory Manager" ldap://localhost repl-agmt delete \
  --suffix "dc=example,dc=com" "agmt-to-ldap-02"

# Очистка RUV по всему кластеру
dsconf -D "cn=Directory Manager" ldap://localhost replication clean-all-ruv \
  --suffix "dc=example,dc=com" \
  --replica-id 2 \
  --replica-certify-all
```

Флаг `--replica-certify-all` гарантирует, что команда выполнится на всех доступных мастерах.

### Восстановление после сбоя репликации (Re-init)

Если соглашение перешло в состояние `Broken` или Consumer отстал на значительное время (большой backlog), выполните повторную инициализацию:

```bash
# Принудительная полная инициализация
dsconf -D "cn=Directory Manager" ldap://localhost repl-agmt init \
  --suffix "dc=example,dc=com" \
  --init-full \
  --skip-acceptcsn \
  "agmt-to-ldap-02"

# Или полная инициализация с проверкой CSN (медленнее, но безопаснее)
dsconf -D "cn=Directory Manager" ldap://localhost repl-agmt init \
  --suffix "dc=example,dc=com" \
  --init-full \
  --check-csn \
  "agmt-to-ldap-02"
```

**Валидация:**
```bash
dsconf -D "cn=Directory Manager" ldap://localhost repl-agmt status \
  --suffix "dc=example,dc=com" "agmt-to-ldap-02"
# Ожидаемый результат: State: Replica acquired: successfully started
```

### Мониторинг здоровья репликации

Создайте скрипт для периодической проверки:

```bash
#!/bin/bash
# check-repl.sh — мониторинг соглашений репликации

HOST="ldap://localhost"
SUFFIX="dc=example,dc=com"
AGREEMENTS="agmt-to-ldap-02 agmt-to-ldap-03"

for agmt in $AGREEMENTS; do
  STATUS=$(dsconf -D "cn=Directory Manager" "$HOST" repl-agmt status \
    --suffix "$SUFFIX" "$agmt" 2>/dev/null)
  
  if echo "$STATUS" | grep -q "Replica acquired: successfully started"; then
    echo "[OK] $agmt: running"
  elif echo "$STATUS" | grep -q "Not running or not reachable"; then
    echo "[CRITICAL] $agmt: not reachable"
    # Здесь можно добавить отправку алерта
  else
    echo "[WARN] $agmt: $STATUS"
  fi
done
```

## Дополнительная информация

### Рекомендации (Best Practices)

1.  **Синхронизация времени:** Разница во времени более 1-2 секунд между мастерами может привести к неверному разрешению конфликтов CSN. Используйте NTP.
2.  **Уникальность Replica ID:** Репликация между узлами с одинаковым ID невозможна и приведет к повреждению базы данных.
3.  **Выделенный менеджер:** Всегда используйте `cn=replication manager,cn=config` вместо `cn=Directory Manager` для соглашений.
4.  **Changelog Trimming:** Настраивайте время хранения истории (`nsslapd-changelogmaxage`) в зависимости от объема изменений и скорости восстановления из бэкапа.
5.  **Ограничение размера репликации:** Используйте fractional replication для Consumer, которым не нужны все атрибуты. Это снижает объем передаваемых данных и уязвимость при компрометации Consumer.
6.  **Изоляция Consumer:** Consumer в DMZ не должны иметь прав на запись. Настройте `nsslapd-readonly=on` на этих инстансах.

### Производительность репликации

| Параметр | Назначение | Рекомендация |
| :--- | :--- | :--- |
| `nsslapd-referral-waiting-timeout` | Таймаут ожидания перед retry | 60–120 секунд для высоконагруженных сред |
| `nsslapd-changelogmaxage` | Время хранения changelog | 7–30 дней (зависит от политики бэкапов) |
| `nsslapd-threadnum` | Количество потоков репликации | 8–32 (по умолчанию 8) |
| `nsslapd-schemacheck` | Проверка схемы при репликации | `off` в production для производительности |

**Оптимизация сети:**
- Для репликации используйте выделенный интерфейс или VLAN.
- Задержка (>5ms) между мастерами влияет на латентность операций записи.
- Настройка `busy-wait-timeout` в соглашении позволяет Consumer ждать данные, если Supplier временно недоступен.

### Устранение неполадок (Troubleshooting)

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `Can't contact LDAP server` | Сетевой экран или неверный порт | Проверьте `ping` и `telnet` на порты 3389/636. |
| `Invalid credentials` | Ошибка в пароле Replication Manager | Обновите пароль в соглашении через `repl-agmt set`. |
| `Replica has no root RUV` | Ошибка инициализации | Повторно запустите `repl-agmt init`. |
| `Certificate expired / untrusted` | Проблема с TLS | Проверьте срок действия сертификатов и наличие CA в базе NSS (`certutil -L`). |
| Огромные лаги (Backlog) | Медленный диск или сеть | Проверьте IOPS на разделе с `/var/lib/dirsrv` и пропускную способность сети. |
| Конфликты в данных | Clock Skew (разница времени) | Настройте NTP и проверьте `effectiveRights` для репликации. |
| `entryCSN` конфликты | Дубликаты Replica ID | Уникальный ID для каждого мастера (1..65534). |
| OOM при фиксе | Слишком большой update-delay | Уменьшите батчи, увеличьте RAM. |
| `Replica is busy` | Соглашение уже выполняет операцию | Дождитесь завершения или проверьте `nsslapd-threadnum`. |
| Анонимный bind работает на Consumer | `nsslapd-allow-anonymous-access` не отключен | `dsconf config replace nsslapd-allow-anonymous-access=off`. |
| Поток репликации разорван | Пакетный firewall или MTU | Проверьте `iptables -L -n` и `ping -M do -s 1400 <host>`. |

### Сравнение репликации 389DS и OpenLDAP

| Характеристика | OpenLDAP | 389 Directory Server |
| :--- | :--- | :--- |
| **Модель** | Syncrepl (pull) | Multi-master (push) |
| **Максимум мастеров** | Один (primary), несколько consumer | До 20+ мастеров в MMR |
| **Инициализация** | Полная (провизия) или инкрементальная | Total Init / Delta Init |
| **Конфликты** | Последний CSN, но нет встроенного tie-breaker | CSN + Replica ID как tie-breaker |
| **Конфигурация** | `olcSyncProvConfig` в LDIF | `dsconf repl-agmt` и API |
| **Фракционная репликация** | Нет (требуются фильтры в overlay) | Встроенная через `--fractional-exclude` |
| **Мониторинг** | `ldapsearch` на `cn=monitor` | `dsconf repl-agmt status`, RUV, logs |

### Связанные материалы

-   [Обзор 389DS](./overview.md) — базовые понятия и архитектура
-   [Плагины](./plugins.md) — работа плагина репликации и Retro Changelog
-   [Управление доступом (ACI)](./aci.md) — репликация политик доступа
-   [Kubernetes Deploy](./k8s_deploy/k8s-administration.md) — эксплуатация Multi-Master в Kubernetes
-   [Docker развертывание](./docker.md) — запуск контейнеров для кластера

# Безопасность и управление доступом в Apache Kafka

**Актуально для:** Apache Kafka 3.8.x / 3.9.x / 4.0.x (KRaft)

**Безопасность Apache Kafka** — это эшелонированный комплекс протокольных, криптографических и административных мер, обеспечивающий конфиденциальность сетевого трафика, аутентификацию брокеров и клиентов, гранулярный контроль доступа к ресурсам (топикам, консьюмер-группам, транзакциям, метаданным) и защиту от перегрузки инфраструктуры недобросовестными или аварийными клиентами (multi-tenancy quotas).

---

## Определения

- **mTLS (Mutual TLS / Двусторонний TLS):** Протокол защиты транспортного уровня, при котором шифруется сетевой канал, а брокер и клиент взаимно подтверждают свою подлинность с помощью цифровых X.509-сертификатов. Имя субъекта сертификата (`CN` или `SAN`) используется Kafka в качестве имени принципала клиента.
- **Keystore и Truststore:** Хранилища криптографических ключей в формате PKCS12 (или устаревшем JKS). Keystore содержит закрытый ключ и открытый сертификат самого узла; Truststore содержит сертификаты доверенных удостоверяющих центров (CA), выпустивших сертификаты клиентов или брокеров.
- **SASL (Simple Authentication and Security Layer):** Стандартизированный фреймворк для согласования механизмов аутентификации поверх сетевых соединений. В Kafka поддерживает механизмы `SCRAM-SHA-512`, `SCRAM-SHA-256`, `GSSAPI` (Kerberos), `OAUTHBEARER` и `PLAIN`.
- **GSSAPI / Kerberos:** Механизм единой корпоративной аутентификации на основе билетов (tickets), выдаваемых центром распределения ключей (KDC — Active Directory или FreeIPA). Позволяет сервисам аутентифицироваться без передачи паролей по сети с использованием бинарных keytab-файлов.
- **Keytab:** Файл, содержащий зашифрованные пары принципал-ключ. Используется автоматизированными демонами (брокерами Kafka, коннекторами) для неинтерактивного получения тикета `TGT` (Ticket Granting Ticket).
- **Принципал (Principal):** Аутентифицированная сущность в Kafka, представленная в формате `User:<name>`. На принципал навешиваются права доступа (ACL) и лимиты квот.
- **Super Users:** Список административных принципалов, задаваемый в конфигурации брокера через параметр `super.users`. Суперпользователи обладают безусловным доступом ко всем операциям и ресурсам кластера в обход любых проверок ACL.
- **StandardAuthorizer:** Высокопроизводительный компонент авторизации в режиме KRaft (KIP-801). В отличие от устаревшего `AclAuthorizer`, хранит списки контроля доступа напрямую в журнале метаданных кворума контроллеров (`@metadata`), обеспечивая мгновенную репликацию изменений без задержек.
- **ACL (Access Control List):** Декларативное правило доступа, связывающее принципал, ресурс (топик, группа, транзакция, кластер), операцию (`Read`, `Write`, `Create`, `Describe`, `Alter` и др.) и тип разрешения (`Allow` или `Deny`).
- **`IDEMPOTENT_WRITE`:** Специфическое право на уровне ресурса `Cluster`, необходимое продюсеру для инициализации сессии идемпотентной записи (`enable.idempotence=true`).
- **Троттлинг (Throttling / Quota Enforcement):** Механизм принудительного замедления работы клиентов, превышающих лимиты пропускной способности (`producer_byte_rate`, `consumer_byte_rate`) или частоты мутаций метаданных (`controller_mutation_rate`), реализуемый за счет искусственной задержки ответов без разрыва сетевых сокетов.

---

## Архитектура и основные концепции

### Модель эшелонированной безопасности кластера

```
┌────────────────────────────────────────────────────────────────────────┐
│                        Клиент / Приложение                             │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ 1. Сетевое подключение (TLS 1.3)
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│ Брокер Kafka: Сетевой уровень (Listeners & Advertised Listeners)       │
│  - Выделенный порт INTERNAL (межброкерный + контроллеры)               │
│  - Выделенный порт CLIENT (внешние продюсеры и консьюмеры)             │
├────────────────────────────────────────────────────────────────────────┤
│ 2. Аутентификация (Authentication Layer)                               │
│  - Проверка сертификата клиента (mTLS) ИЛИ                             │
│  - SASL handshake (GSSAPI/Kerberos, SCRAM-SHA-512, OAuth 2.0)          │
│  - Извлечение принципала: User:svc-billing                             │
├────────────────────────────────────────────────────────────────────────┤
│ 3. Авторизация (Authorization Layer — StandardAuthorizer)              │
│  - Проверка суперпользователя (super.users) ──► Разрешено              │
│  - Проверка запрещающих правил (Deny ACL)   ──► Ошибка 403 (Deny)      │
│  - Проверка разрешающих правил (Allow ACL)  ──► Разрешено              │
│  - Если совпадений нет (Deny by default)    ──► Ошибка 403             │
├────────────────────────────────────────────────────────────────────────┤
│ 4. Контроль квот (Multi-Tenancy Quotas & Throttling)                   │
│  - Замер скорости: превышен ли producer_byte_rate / consumer_byte_rate │
│  - Если превышен: инжекция искусственного таймаута (Throttle Delay)    │
├────────────────────────────────────────────────────────────────────────┤
│ 5. Запись в лог / Чтение из лога (Commit Log)                          │
└────────────────────────────────────────────────────────────────────────┘
```

### Разделение сетевых листенеров (Listener Isolation)

В production-контуре категорически запрещено использовать единый листенер для клиентов и системного взаимодействия узлов. Конфигурация брокера разделяет потоки:
1. `INTERNAL` (или `REPLICATION`): Межброкерный обмен данными репликации и запросы метаданных. Защищается строгим mTLS с закрытыми внутренними сертификатами.
2. `CONTROLLER`: Листенер кворума контроллеров KRaft. Изолируется в отдельной приватной подсети администрирования.
3. `CLIENT`: Доступ пользовательских микросервисов. Защищается mTLS либо связкой TLS + SASL (Kerberos / SCRAM).

---

### Аутентификация Kerberos / GSSAPI в Enterprise-окружении

В инфраструктурах с Active Directory или FreeIPA брокеры и клиенты используют протокол Kerberos. Взаимодействие строится через Java Generic Security Services (GSSAPI):

1. **Сервисный принципал брокера (SPN):** Формируется по шаблону `kafka/<hostname>@REALM.CORP`. Для каждого брокера генерируется персональный keytab-файл, содержащий симметричные ключи всех поддерживаемых шифров (AES-256).
2. **Файл конфигурации авторизации JAAS:** Указывает JVM-процессу, где брать keytab и как запрашивать сервисные билеты.
3. **Трансляция принципалов (`sasl.kerberos.principal.to.local.rules`):** По умолчанию Kerberos возвращает полное имя пользователя с областью (realm): `svc-orders@REALM.CORP`. Чтобы ACL в Kafka не привязывались к регистру и домену, брокер транслирует их через правила регулярных выражений:

```properties
# Преобразование User:svc-orders@REALM.CORP -> User:svc-orders
sasl.kerberos.principal.to.local.rules=RULE:[1:$1@$0](.*@REALM.CORP)s/@REALM.CORP//,DEFAULT
```

---

### Тонкости авторизации ACL и типичные ошибки на собеседованиях

#### 1. Стандартные правила проверки (Precedence Rules)
1. Если принципал входит в `super.users` — доступ разрешен немедленно.
2. Любое явное правило **Deny** безусловно перекрывает любые правила **Allow**.
3. При отсутствии совпадений действует принцип **Deny by Default** (если включен authorizer, любой доступ без явного ACL блокируется).

#### 2. Ловушка идемпотентного продюсера (`IDEMPOTENT_WRITE`)
Начиная с Apache Kafka 3.0, параметр `enable.idempotence=true` включен на клиентах по умолчанию. Идемпотентный продюсер запрашивает у брокера уникальный идентификатор сессии (Producer ID — PID).
- **Симптом:** Администратор выдает сервису права `Write` и `Describe` на топик `orders`. Продюсер пытается отправить сообщение и падает с фатальным исключением `org.apache.kafka.common.errors.ClusterAuthorizationException: Cluster authorization failed`.
- **Причина:** Инициализация Producer ID требует проверки прав на операцию **`IdempotentWrite` (или `IDEMPOTENT_WRITE`) на уровне ресурса `Cluster`**.
- **Решение:** Выдать принципалу права на операцию `IdempotentWrite` на кластер, либо использовать команду CLI со специальным профилем `--producer`, которая автоматически учитывает эти права.

#### 3. Транзакционные продюсеры
Для транзакций (`transactional.id = "order-tx-01"`) продюсеру дополнительно требуются права:
- `Write` и `Describe` на ресурс `TransactionalId` (с точным именем или префиксом).

---

### Динамическая ротация TLS-сертификатов без простоя (Zero-Downtime Cert Rotation)

Исторически для смены истекающих сертификатов требовался последовательный rolling restart брокеров. Начиная с KIP-519 (Kafka 2.4+), параметры хранилища сертификатов являются **динамическими брокерскими конфигурациями** (Dynamic Broker Configs).

Брокер слушает изменения конфигураций в реальном времени. При перезаписи путей или паролей хранилища брокер переинициализирует контекст `SSLContext` и подгружает новые сертификаты без разрыва текущих TCP-соединений клиентов:

```
[ Администратор ] ──► kafka-configs.sh --alter --entity-type brokers --add-config ssl.keystore...
                             │
                             ▼
                 [ Запись в метаданные KRaft ]
                             │
                             ▼
         [ Демон Брокера: SslFactory.reconfigure() ]
                             │
             ┌───────────────┴───────────────┐
             ▼                               ▼
  [ Загрузка нового Keystore ]    [ Атомарное обновление SSLContext ]
  (Клиенты не отключаются)        (Новые handshake на новых сертификатах)
```

---

### Механизм квот и специфика троттлинга (Quota Enforcement & Throttling)

Kafka проектировалась для предотвращения сценариев «шумного соседа» (Noisy Neighbor). Квоты определяют верхний предел потребления ресурсов отдельным пользователем или клиентским приложением:

| Тип квоты | Параметр конфигурации | Единицы измерения | Описание |
| :--- | :--- | :--- | :--- |
| **Сетевая запись (Producer Rate)** | `producer_byte_rate` | Байт/сек | Предел входящего потока данных от продюсеров принципала |
| **Сетевое чтение (Consumer Rate)** | `consumer_byte_rate` | Байт/сек | Предел исходящего потока данных потребителям принципала |
| **Процессорное время (Request Quota)**| `request_percentage` | Процент (%) | Максимальный процент времени пула потоков `KafkaRequestHandlerPool` |
| **Лимит соединений (IP Quota)** | `connection_creation_rate` | Соединений/сек | Защита от шторма открытия новых TCP-сокетов с IP-адреса |
| **Мутации метаданных (KRaft Quota)** | `controller_mutation_rate` | Операций/сек | Защита контроллеров от спама созданием/удалением топиков и партиций |

#### Механика наложения штрафа (Throttling Delay)
Когда клиент превышает выделенный `producer_byte_rate`:
1. Брокер вычисляет величину превышения и определяет штрафную задержку в миллисекундах:
   $$\text{ThrottleTimeMs} = \frac{\text{ClientRate} - \text{TargetQuota}}{\text{TargetQuota}} \times 1000$$
2. **Брокер НЕ возвращает сетевую ошибку (нет аналога HTTP 429) и НЕ рвет соединение.**
3. Брокер физически **задерживает отправку сетевого подтверждения (Ack)** клиенту на вычисленный интервал $\text{ThrottleTimeMs}$, приостанавливая обработку входящих запросов из данного сокета (`mute socket`).
4. Клиент видит рост задержки подтверждения (`request-latency-avg`) и в ответе `ProduceResponse` получает явное поле `throttle_time_ms`. Клиентские библиотеки автоматически притормаживают дальнейшую отправку пакетов.

---

## Практические сценарии

### Сценарий 1: Интеграция брокера и клиентов с Kerberos / Active Directory (GSSAPI)

#### 1. Системные требования и конфигурация `/etc/krb5.conf`
Убедитесь, что служба синхронизации времени chrony/ntp работает с расхождением $< 1$ секунды (Kerberos блокирует аутентификацию при рассинхронизации более 300 секунд).

```ini
# /etc/krb5.conf
[libdefaults]
    default_realm = REALM.CORP
    dns_lookup_realm = false
    dns_lookup_kdc = true
    ticket_lifetime = 24h
    renew_lifetime = 7d
    forwardable = true
    default_tkt_enctypes = aes256-cts-hmac-sha1-96 aes128-cts-hmac-sha1-96

[realms]
    REALM.CORP = {
        kdc = kdc01.realm.corp:88
        kdc = kdc02.realm.corp:88
        admin_server = kdc01.realm.corp:749
    }
```

#### 2. Создание файла JAAS для брокера (`kafka_server_jaas.conf`)

```properties
KafkaServer {
    com.sun.security.auth.module.Krb5LoginModule required
    useKeyTab=true
    storeKey=true
    keyTab="/etc/kafka/secrets/kafka.keytab"
    principal="kafka/kafka-node-1.realm.corp@REALM.CORP";
};

// Конфигурация для взаимодействия между контроллерами KRaft
QuorumController {
    com.sun.security.auth.module.Krb5LoginModule required
    useKeyTab=true
    storeKey=true
    keyTab="/etc/kafka/secrets/kafka.keytab"
    principal="kafka/kafka-node-1.realm.corp@REALM.CORP";
};
```

#### 3. Настройка `server.properties` брокера

```properties
# Сетевые листенеры
listeners=SASL_PLAINTEXT://kafka-node-1.realm.corp:9092,CONTROLLER://kafka-node-1.realm.corp:9093
advertised.listeners=SASL_PLAINTEXT://kafka-node-1.realm.corp:9092
listener.security.protocol.map=SASL_PLAINTEXT:SASL_PLAINTEXT,CONTROLLER:SASL_PLAINTEXT

# Механизм SASL
sasl.enabled.mechanisms=GSSAPI
sasl.mechanism.inter.broker.protocol=GSSAPI
sasl.kerberos.service.name=kafka

# Авторизация в KRaft
authorizer.class.name=org.apache.kafka.metadata.authorizer.StandardAuthorizer
super.users=User:kafka;User:admin-sre

# Правила трансляции принципалов
sasl.kerberos.principal.to.local.rules=RULE:[1:$1@$0](.*@REALM.CORP)s/@REALM.CORP//,DEFAULT
```

Запуск сервиса брокера требует передачи пути к JAAS через флаг JVM:
```bash
KAFKA_OPTS="-Djava.security.auth.login.config=/etc/kafka/config/kafka_server_jaas.conf -Djava.security.krb5.conf=/etc/krb5.conf"
```

#### 4. Валидация билета и аутентификация клиента

```bash
# Получение пользовательского Kerberos-тикета в ОС
kinit svc-orders@REALM.CORP
# → Password for svc-orders@REALM.CORP: ******

# Проверка наличия билета TGT
klist
# → Valid starting       Expires              Service principal
# → 12/10/2026 14:00:00  13/10/2026 00:00:00  krbtgt/REALM.CORP@REALM.CORP
```

Конфигурационный файл клиента `client-kerberos.properties`:
```properties
security.protocol=SASL_PLAINTEXT
sasl.mechanism=GSSAPI
sasl.kerberos.service.name=kafka
sasl.jaas.config=com.sun.security.auth.module.Krb5LoginModule required useTicketCache=true;
```

---

### Сценарий 2: Ротация TLS-сертификатов без простоя на работающем кластере

Когда подходит к концу срок действия серверных сертификатов (X.509), процедура обновления выполняется в два шага без перезапуска демона брокера:

```bash
# ШАГ 1: Подготовка нового хранилища ключей на хосте брокера 1
# Размещение нового keystore.p12 в каталоге сертификатов с правами 0400 для пользователя kafka
install -o kafka -g kafka -m 0400 /tmp/keystore-2026-new.p12 /var/private/ssl/kafka.keystore.p12

# ШАГ 2: Динамическое применение через kafka-configs.sh для конкретного брокера
kafka-configs.sh --bootstrap-server kafka-node-1.realm.corp:9092 \
    --command-config /etc/kafka/admin.properties \
    --alter --entity-type brokers --entity-name 1 \
    --add-config ssl.keystore.location=/var/private/ssl/kafka.keystore.p12,ssl.keystore.password=KeystoreSecretPass123
# → Completed updating config for broker 1.

# ШАГ 3: Верификация обновления сертификата брокера извне без разрыва трафика
openssl s_client -connect kafka-node-1.realm.corp:9093 -servername kafka-node-1.realm.corp < /dev/null 2>/dev/null | openssl x509 -noout -dates
# → notBefore=Oct 12 00:00:00 2026 GMT
# → notAfter=Oct 12 00:00:00 2027 GMT
```

> [!TIP]
> При смене доверенного корневого удостоверяющего центра (Root CA) сначала выполните динамическое обновление `ssl.truststore.location` на всех брокерах кластера (добавив в хранилище доверия оба сертификата — старый и новый CA), и только после этого обновляйте персональные Keystore брокеров и клиентов.

---

### Сценарий 3: Настройка гранулярных ACL для production-сервисов

#### 1. Выдача прав для микросервиса-продюсера с включенной идемпотентностью

```bash
# Комплексная выдача прав продюсеру через удобный шорткат --producer
# Выдает Write, Describe и Create на топик, а также право IdempotentWrite на Cluster
kafka-acls.sh --bootstrap-server localhost:9092 --command-config admin.properties --add \
    --allow-principal User:svc-orders-backend \
    --producer \
    --topic orders-stream
# → Adding ACLs for resource `ResourcePattern(resourceType=TOPIC, name=orders-stream, patternType=LITERAL)`:
# → 	(principal=User:svc-orders-backend, host=*, operation=WRITE, permissionType=ALLOW)
# → 	(principal=User:svc-orders-backend, host=*, operation=DESCRIBE, permissionType=ALLOW)
# → 	(principal=User:svc-orders-backend, host=*, operation=CREATE, permissionType=ALLOW)
# → Adding ACLs for resource `ResourcePattern(resourceType=CLUSTER, name=kafka-cluster, patternType=LITERAL)`:
# → 	(principal=User:svc-orders-backend, host=*, operation=IDEMPOTENT_WRITE, permissionType=ALLOW)
```

Если права назначаются вручную без флага `--producer`, обязательна отдельная команда для ресурса Cluster:
```bash
kafka-acls.sh --bootstrap-server localhost:9092 --command-config admin.properties --add \
    --allow-principal User:svc-orders-backend \
    --operation IdempotentWrite \
    --cluster
# → Completed adding ACLs.
```

#### 2. Выдача прав для консьюмера (чтение топика и фиксация офсетов в группе)

```bash
kafka-acls.sh --bootstrap-server localhost:9092 --command-config admin.properties --add \
    --allow-principal User:svc-billing-consumer \
    --consumer \
    --topic orders-stream \
    --group billing-processing-group
# → Adding ACLs for resource `ResourcePattern(resourceType=TOPIC, name=orders-stream, patternType=LITERAL)`:
# → 	(principal=User:svc-billing-consumer, host=*, operation=READ, permissionType=ALLOW)...
# → Adding ACLs for resource `ResourcePattern(resourceType=GROUP, name=billing-processing-group, patternType=LITERAL)`:
# → 	(principal=User:svc-billing-consumer, host=*, operation=READ, permissionType=ALLOW)...
```

#### 3. Выдача прав для транзакционного сервиса (Exactly-Once)

```bash
kafka-acls.sh --bootstrap-server localhost:9092 --command-config admin.properties --add \
    --allow-principal User:svc-payment-processor \
    --operation Write --operation Describe \
    --transactional-id payment-tx-
    --resource-pattern-type prefixed
# → Completed adding ACLs for TransactionalId prefixed: payment-tx-.
```

---

### Сценарий 4: Настройка квот (Rate Limiting) и аудит троттлинга

#### 1. Ограничение скорости входящих и исходящих данных для клиента

```bash
# Ограничение пользователя analytics-reader: 5 МБ/сек на запись, 20 МБ/сек на чтение
kafka-configs.sh --bootstrap-server localhost:9092 --command-config admin.properties --alter \
    --entity-type users --entity-name analytics-reader \
    --add-config producer_byte_rate=5242880,consumer_byte_rate=20971520
# → Completed updating config for user analytics-reader.

# Защита от шторма мутаций контроллера (максимум 10 операций создания/изменения топиков в секунду)
kafka-configs.sh --bootstrap-server localhost:9092 --command-config admin.properties --alter \
    --entity-type users --entity-name untrusted-dev-client \
    --add-config controller_mutation_rate=10
# → Completed updating config for user untrusted-dev-client.
```

#### 2. Проверка действующих квот для сущности

```bash
kafka-configs.sh --bootstrap-server localhost:9092 --command-config admin.properties --describe \
    --entity-type users --entity-name analytics-reader
# → Dynamic configs for user analytics-reader are:
# →   consumer_byte_rate=20971520
# →   producer_byte_rate=5242880
```

---

## Диагностика и устранение неисправностей (Troubleshooting)

### Матрица инцидентов безопасности

| Симптом / Ошибка | Первопричина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| `ClusterAuthorizationException: Cluster authorization failed` | Продюсер с `enable.idempotence=true` не имеет права `IdempotentWrite` на кластере | Логи клиента, поиск ошибки авторизации на кластере | Выдать принципалу право `--operation IdempotentWrite --cluster` через `kafka-acls.sh` |
| `GroupAuthorizationException: Not authorized to access group` | Консьюмер имеет права на топик, но отсутствуют права `Read` на консьюмер-группу | Лог консьюмера: отказ при отправке `JoinGroup` или `Heartbeat` | Добавить ACL: `--operation Read --group <group-name>` |
| `GSSException: No valid credentials provided (Mechanism level: Failed to find any Kerberos tgt)` | Истек тикет TGT клиента, не настроен `keyTab` в JAAS или рассинхронизировано время | `klist`<br>`chronyc tracking` | Обновить билет через `kinit` или проверить права доступа демона к `.keytab` |
| `GSSException: Checksum failed` / `Decrypt integrity check failed` | Несовпадение KVNO в keytab и на сервере KDC после смены пароля сервисной учетки | `klist -kt /etc/kafka/secrets/kafka.keytab`<br>`kvno kafka/<host>@REALM` | Перевыпустить keytab-файл на контроллере домена и обновить на хосте брокера |
| `SSLHandshakeException: Received fatal alert: certificate_unknown` | Брокер или клиент не доверяют сертификату (отсутствует CA в truststore) | Запуск клиента с флагом JVM `-Djavax.net.debug=ssl:handshake` | Импортировать корневой CA в `truststore.p12` через `keytool` |
| Резкий рост latency продюсера без ошибок (`ProduceRequest` длится секунды) | Сработал троттлинг квоты `producer_byte_rate` | Проверить JMX метрику брокера `Produce:ThrottleTimeMs` | Увеличить квоту через `kafka-configs.sh` либо оптимизировать батчинг на стороне клиента |

---

## Рекомендации и Best Practices

1. **Принцип наименьших привилегий (PoLP):** Никогда не выдавайте права `All` на весь кластер для прикладных сервисов. Используйте четко разделенные префиксы топиков (например, `orders.prod.*`) и префиксные ACL.
2. **Всегда задавайте `super.users` в `server.properties`:** Обязательно резервируйте 2 независимых административных принципала (например, `User:kafka;User:admin-sre`). Если вы потеряете доступ или допустите ошибку в правиле Deny ACL, суперпользователь сохранит возможность исправить конфигурацию.
3. **Разделяйте листенеры:** Листенер межброкерной репликации `INTERNAL` и листенер контроллеров `CONTROLLER` никогда не должны быть доступны из клиентской подсети.
4. **Включайте аудит авторизации в логах:** Настройте логирование неудачных попыток доступа в `log4j.properties`:
   ```properties
   log4j.logger.kafka.authorizer.logger=INFO, authorizerAppender
   ```
5. **Мониторьте время троттлинга:** Добавьте в Prometheus Alertmanager алерт на метрику:
   ```promql
   rate(kafka_server_clientquotamanager_throttletimems_sum[5m]) > 0
   ```
   Это позволит проактивно обнаруживать клиентов, упершихся в квоты, до того, как они начнут жаловаться на задержки.

---

## Дополнительная информация

- [CLI-инструменты для работы с Apache Kafka](./kafka_cli_tools.md) — управление ACL через `kafka-acls.sh` и квотами через `kafka-configs.sh`.
- [Развертывание Apache Kafka с помощью Ansible](./kafka_ansible_deployment.md) — автоматизация развертывания PKI и SASL/SCRAM на выделенных серверах.
- [Гарантии доставки и надежность данных](./delivery_guarantees.md) — архитектура идемпотентных и транзакционных продюсеров.
- [Troubleshooting Playbook для Apache Kafka](./kafka_troubleshooting_playbook.md) — регламенты реагирования на сбои и деградацию производительности.

# Аутентификация в Vault через AppRole

## Определения

**AppRole** — метод аутентификации (проверки подлинности) в **[HashiCorp Vault](../overview.md)**, спроектированный для взаимодействия между машинами (Machine-to-Machine, M2M). Он позволяет приложениям и сервисам получать токены доступа без участия человека, используя концепцию ролей и уникальных идентификаторов.

Метод появился как замена устаревшему App-ID (который требовал предварительного создания `SecretID` извне) и стал стандартным выбором для автоматизированных сред: CI/CD пайплайнов, контейнеров на bare metal, системных сервисов и любых сценариев, где нельзя использовать интерактивный вход человека.

Общий обзор методов аутентификации представлен в [Основных концепциях](../concepts.md#методы-аутентификации-и-токены).

## Основные концепции

### Ролевая модель и идентификаторы

В основе AppRole лежат два компонента:
*   **RoleID (Идентификатор роли):** Аналог логина. Статическое значение, привязанное к конкретному приложению.
*   **SecretID (Секретный идентификатор):** Аналог пароля. Конфиденциальное значение с ограниченным временем жизни.

При предоставлении обоих идентификаторов Vault проверяет их соответствие и выдает токен, привязанный к [политикам доступа](../authorization.md) данной роли.

### Монтирование метода аутентификации

Каждый метод аутентификации монтируется в отдельный путь (mount path) внутри логического пространства Vault. По умолчанию AppRole монтируется на `auth/approle`, но при необходимости можно указать кастомный путь:

```bash
# Монтирование на кастомный путь
vault auth enable -path=my-app approle

# Проверка списка активных методов
vault auth list
# → Path          Type        Accessor                  ...
# → my-app/       approle     a_8f3...                  ...
# → token/        token       a_123...                  ...
# → ...
```

Использование кастомного пути (`-path=...`) полезно при разделении сред внутри одного кластера или при развертывании нескольких независимых экземпляров Vault, которые должны использовать разные политики для AppRole.

### Типы выдаваемых токенов

Vault поддерживает несколько типов токенов, влияющих на отслеживание и поведение:

| Тип | Описание | Когда использовать |
| :--- | :--- | :--- |
| `service` | Стандартный токен. Сохраняется в индексе, поддерживает дочерние токены. | Интерактивные сервисы, требующие создания вложенных токенов. |
| `batch` | Легковесный токен. Не сохраняется в индексе, не имеет дочерних токенов, не учитывается в аудите. | **Рекомендуется для M2M** по официальной документации. Меньше следов в памяти и в индексе. |
| `periodic` | Токен, который автоматически продлевается до `token_max_ttl` без создания дочерних токенов. | Долгоживущие сервисы, где требуется постоянная валидность без ручного продления. |

Для типов `batch` и `periodic` параметр `token_num_uses` обычно оставляют `0` (неограниченно до истечения TTL), так как эти токены не предназначены для многократного повторного использования после отзыва.

### Настройка параметров метода через `auth tune`

Поведение метода AppRole можно тонко настроить без пересоздания роли:

```bash
# Включить user lockout для конкретного mount point
vault auth tune -path=approle \
    user_lockout="true" \
    lockout_threshold="5" \
    lockout_duration="15m" \
    lockout_counter_reset_duration="15m"
```

### Модели доставки секретов: Pull и Push

В современной практике управления секретами выделяют два подхода к доставке `SecretID`:

1.  **Pull-модель (Рекомендуемая):** Доверенный оркестратор генерирует `SecretID` через API Vault и передает его приложению через защищенный канал (например, через механизм обертывания ответов). Приложение само «забирает» (pull) данные для входа, при этом само значение `SecretID` не покидает контур Vault до момента передачи конечному клиенту.
2.  **Push-модель (Audit-only / App-ID):** Внешняя система сама задает (push) произвольное значение `SecretID` в API (эндпоинт `custom-secret-id`). Данный режим доступен для совместимости со старым методом App-ID. Менее безопасен: для создания записи требуется, чтобы внешняя система знала всю пару `RoleID`/`SecretID`, даже если затем они распространяются разными путями. В большинстве случаев Pull-модель предпочтительнее и безопаснее.

### Безопасная доставка через Response Wrapping

Для реализации архитектуры Zero Trust рекомендуется использовать механизм **Response Wrapping** («обертывание ответов»). Этот метод исключает передачу `SecretID` в открытом виде через переменные окружения или логи оркестраторов.

**Алгоритм работы:**
1.  Оркестратор запрашивает `SecretID` с флагом `-wrap-ttl` (например, на 60 секунд).
2.  Vault возвращает **Wrapping Token** — одноразовый токен доступа к временному хранилищу.
3.  Оркестратор передает этот токен приложению.
4.  Приложение выполняет операцию `unwrap`. Vault выдает реальный `SecretID` и **мгновенно аннулирует** оберточный токен.
5.  Если злоумышленник перехватит токен и попытается его использовать, легитимное приложение получит ошибку при попытке развертывания, что станет сигналом о компрометации.

### Параметры безопасности роли

| Параметр | Описание | Рекомендация |
| :--- | :--- | :--- |
| `bind_secret_id` | Требовать ли `SecretID` для входа. | `true` (обязательно для Prod) |
| `token_type` | Тип выдаваемого токена: `service`, `batch` или `periodic`. | `batch` (рекомендуется официальной документацией для M2M; меньше следов в памяти и в индексе) |
| `secret_id_num_uses` | Сколько раз можно использовать один `SecretID`. | `1` (для максимальной безопасности) |
| `secret_id_ttl` | Время жизни `SecretID`. | Минимально необходимое (5-10 мин) |
| `token_num_uses` | Сколько раз можно использовать выданный токен. | `0` (неограниченно до истечения TTL) |
| `secret_id_bound_cidrs` | IP-адреса, с которых можно создавать `SecretID`. | Сегмент управления/CI/CD |
| `token_bound_cidrs` | IP-адреса, с которых можно использовать токен. | Сегмент запуска приложения |
| `token_no_default_policy` | Отключать ли автоматическое присоединение политики `default`. | `true` (если требуется строгая модель deny-by-default) |
| `periodic_window` | Длительность окна продления для `periodic` токенов. | Оставить пустым (по умолчанию 24h) или явно задать |

## Практические сценарии

### Предварительные требования

Перед настройкой AppRole убедитесь, что:
1.  Vault инициализирован и распечатан (`vault status` → `Sealed: false`).
2.  У вас есть токен с правами на управление auth-методами (обычно `root` или политика с правами `create`/`read`/`update`/`delete` на `auth/approle/*`).
3.  Существует политика доступа, которую вы планируете привязывать к роли:

```bash
# Создание политики 'payment-policy'
vault policy write payment-policy - <<EOF
path "secret/data/payment/*" {
  capabilities = ["read", "list"]
}
EOF
```

### Включение и настройка метода

```bash
# Активация метода AppRole на стандартном пути
vault auth enable approle

# Активация на кастомном пути (если требуется изоляция)
vault auth enable -path=my-app approle
```

### Создание роли для микросервиса

Пример создания роли `payment-service` с политикой `payment-policy`, ограниченным числом использований `SecretID` и привязкой к сети.

```bash
vault write auth/approle/role/payment-service \
    secret_id_ttl="10m" \
    secret_id_num_uses=1 \
    token_ttl="1h" \
    token_max_ttl="4h" \
    token_policies="payment-policy" \
    token_type="batch" \
    bind_secret_id=true \
    token_bound_cidrs="10.0.5.0/24" \
    token_no_default_policy=false
```

### Валидация конфигурации роли

```bash
# Проверка параметров роли
vault read auth/approle/role/payment-service
# → Key                     Value
# → token_ttl               1h
# → token_max_ttl           4h
# → token_policies          [payment-policy]
# → token_type              batch
# → bind_secret_id          true
# → token_num_uses          0
# → secret_id_ttl           10m
# → secret_id_num_uses      1
# → token_bound_cidrs       [10.0.5.0/24]
```

### Получение идентификаторов оркестратором

```bash
# Получение статического RoleID (можно запечь в конфиг)
vault read auth/approle/role/payment-service/role-id
# → Key        Value
# → role_id    6b2a5c4a-...

# Генерация обернутого SecretID (wrap)
vault write -wrap-ttl=60s -f auth/approle/role/payment-service/secret-id
# → Key              Value
# → wrapping_token   hvs.CAESI...
# → wrapping_info    ...
# → wrapped_accessor  ...

# Генерация SecretID с заданным значением (Push-модель, если требуется)
vault write auth/approle/role/payment-service/custom-secret-id \
    secret_id="my-static-secret-value"
```

### Аутентификация приложения (вход)

Приложение выполняет вход, передавая пару `RoleID`/`SecretID`. Vault проверяет ограничения роли (CIDR, TTL, количество использований) и выдает токен с привязанными [политиками](../authorization.md).

```bash
# Вход через CLI (показан примерный вывод)
vault write auth/approle/login \
    role_id="6b2a5c4a-..." \
    secret_id="98e4f7b3-..."
# → Key                Value
# → token              hvs.CAES...
# → token_duration     1h
# → token_renewable    true
# → token_policies     ["default" "payment-policy"]

# Токен извлекается в переменную для дальнейших команд/скриптов
TOKEN=$(vault write -field=token auth/approle/login \
    role_id="6b2a5c4a-..." secret_id="98e4f7b3-...")

# Вход через API (например, внутри контейнера без CLI)
curl -s --request POST \
    --data '{"role_id":"...","secret_id":"..."}' \
    "$VAULT_ADDR/v1/auth/approle/login" | jq -r .auth.client_token
```

### Валидация токена после входа

```bash
# Информация о полученном токене
vault token lookup $TOKEN
# → Key                Value
# → accessor           a_1b2...
# → creation_time      2026-09-20T12:00:00Z
# → creation_ttl       1h
# → policies           [default payment-policy]
# → token_type         batch
# → renewable          false
# → num_uses           0
# → ...
```

### Продление и отзыв токена

```bash
# Продление срока действия токена (если поддерживается политикой)
vault token renew $TOKEN
# → Key                Value
# → lease_id
# → lease_duration     1h
# → ...

# Проверка текущего TTL без продления
vault token lookup -format=json $TOKEN | jq .data.ttl

# Отзыв токена по accessor (не требует самого секретного значения)
vault token revoke -accessor a_1b2...
# → Success! Token revoked.
```

### Ротация и отзыв SecretID

`SecretID` — краткоживущий. Ротация выполняется выдачей нового значения без потери роли, старые `SecretID` можно удалить точечно по `secret_id_accessor`.

```bash
# Генерация нового SecretID (не аннулирует старые)
vault write -f auth/approle/role/payment-service/secret-id
# → Key                   Value
# → --- secret_id           3e1c...b2
# → secret_id_accessor      7a6f...c9
# → secret_id_ttl           10m

# Поиск активных SecretID по роли
vault list auth/approle/role/payment-service/secret-id
# → Keys  (и их accessor'ы)
# → ---

# Вывод данных по конкретному SecretID (по accessor)
vault write auth/approle/role/payment-service/secret-id/lookup \
    secret_id_accessor="7a6f...c9"

# Тотальный отзыв SecretID как единственного: уничтожение по accessor
vault write auth/approle/role/payment-service/secret-id/destroy \
    secret_id_accessor="7a6f...c9"
```

### Практический сценарий: CI/CD пайплайн

В пайплайне CI/CD (GitLab CI, Jenkins, GitHub Actions) AppRole позволяет получать краткоживущий токен без хранения постоянных учетных данных.

```bash
# Пример шага для GitLab CI (.gitlab-ci.yml)
# variables:
#   VAULT_ADDR: "https://vault.internal:8200"
#   VAULT_ROLE_ID: "${VAULT_ROLE_ID}"  # задается как protected variable
#   VAULT_SECRET_ID: "${VAULT_SECRET_ID}"  # доставлен через оберточный токен

before_script:
  - export VAULT_TOKEN=$(vault write -field=token auth/approle/login \
      role_id="$VAULT_ROLE_ID" secret_id="$VAULT_SECRET_ID")

# Использование токена в задачах
deploy:
  script:
    - vault read secret/data/payment/db
```

Для автоматической доставки `SecretID` через Response Wrapping в пайплайне используйте промежуточный скрипт, который делает `unwrap` и передает только реальный `SecretID` в переменную окружения.

### Практический сценарий: Системный сервис на bare metal

Запуск Vault Agent как systemd-сервиса для автоматической аутентификации приложения.

**Шаг 1.** Создайте файлы с учетными данными (права `0600`, владелец `vault:vault`):

```bash
# /etc/vault.d/role-id
6b2a5c4a-...

# /etc/vault.d/secret-id  (доставлен через оберточный токен)
98e4f7b3-...
```

**Шаг 2.** Создайте конфигурацию `/etc/vault.d/agent.hcl`:

```hcl
vault {
  address = "https://vault.internal:8200"
  ca_cert = "/etc/vault.d/ca.crt"
  tls_verify = true
  retry {
    num_retries = 5
    backoff     = "5s"
  }
}

auto_auth {
  method "approle" {
    config = {
      role_id_file_path               = "/etc/vault.d/role-id"
      secret_id_file_path             = "/etc/vault.d/secret-id"
      remove_secret_id_file_after_reading = true
    }
  }

  sink "file" {
    config = {
      path = "/etc/vault.d/.vault-token"
    }
  }
}

cache {
  use_auto_auth_token = true
  persist "file" {
    path = "/var/lib/vault-agent/cache.db"
    keep_after_import = true
    exit_on_err = true
  }
}

template {
  source      = "/etc/app/config.ctmpl"
  destination = "/etc/app/config.json"
  error_on_missing_key = true
  wait {
    min = "2s"
    max = "10s"
  }
  command = "systemctl reload my-app"
}
```

**Шаг 3.** Создайте unit-файл `/etc/systemd/system/vault-agent.service`:

```ini
[Unit]
Description=HashiCorp Vault Agent
After=network-online.target
Wants=network-online.target
ConditionFileNotEmpty=/etc/vault.d/agent.hcl

[Service]
Type=simple
User=vault
Group=vault
ProtectSystem=full
ProtectHome=yes
PrivateTmp=yes
PrivateDevices=yes
NoNewPrivileges=yes
AmbientCapabilities=CAP_IPC_LOCK
CapabilityBoundingSet=CAP_IPC_LOCK
LimitMEMLOCK=infinity
LimitCORE=0
ExecStart=/usr/bin/vault agent -config=/etc/vault.d/agent.hcl
ExecReload=/bin/kill --signal HUP $MAINPID
KillMode=process
Restart=on-failure
RestartSec=5
TimeoutStartSec=30

[Install]
WantedBy=multi-user.target
```

**Шаг 4.** Включите сервис:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now vault-agent
sudo systemctl status vault-agent
journalctl -u vault-agent -f
```

**Шаг 5.** Проверьте рендеринг секретов:

```bash
cat /etc/app/config.json
# → {"db_user":"admin","db_pass":"s3cret"}

# Проверьте статус аутентификации
vault token lookup
# → token renewal window, policies, TTL
```

### Аутентификация через Vault Agent

Рекомендуется использовать [Vault Agent](./vault_agent/basics.md) для автоматизации процесса логина и обновления токенов. Агент сам выполнит `unwrap`, аутентифицируется и будет поддерживать токен в актуальном состоянии, предоставляя приложению готовый файл с секретом или токеном.

**Пример конфигурации агента (auto-auth):**
```hcl
auto_auth {
  method "approle" {
    config = {
      role_id_file_path = "/etc/vault/role-id"
      secret_id_file_path = "/etc/vault/secret-id"
      remove_secret_id_file_after_reading = true
    }
  }
}
```

## Дополнительная информация

### Безопасное разделение каналов доставки

Никогда не передавайте `RoleID` и `SecretID` через один и тот же канал связи. 
*   **RoleID:** может быть частью образа контейнера или конфигурационного файла.
*   **SecretID:** должен доставляться динамически (через оберточный токен) в момент запуска инстанса.

### Защита от перебора (User Lockout)

Начиная с Vault 1.13 в методе `approle` (а также `userpass` и `ldap`) включен механизм **User Lockout**: при нескольких неудачных попытках входа подряд Vault временно прекращает проверку учетных данных для этого `RoleID` и возвращает отказ. Это снижает риск брутфорс-атак на `SecretID`.

*   Порог срабатывания и длительность блокировки настраиваются блоком `user_lockout` в файле конфигурации сервера или через `auth tune`.
*   Поведение можно отключить глобально (`disable_user_lockout = true`) или для конкретного auth-маунта.

```hcl
# Фрагмент конфигурации Vault (server.hcl)
user_lockout {
  lockout_threshold           = 5   # число неудачных попыток до блокировки
  lockout_duration            = "15m"
  lockout_counter_reset_duration = "15m"
}
```

### Аудит входов через AppRole

Для отслеживания успешных и неуспешных попыток аутентификации используйте Audit Devices. Убедитесь, что включен хотя бы один аудит:

```bash
# Проверка включенных аудит-устройств
vault audit list
# → Path     Type    Description
# → file/    file    file audit log

# Чтение последних событий аутентификации AppRole (если audit device файловый)
sudo tail -n 50 /var/log/vault/audit.log | jq 'select(.type=="request") | select(.path=="auth/approle/login")'
```

В логах будут видны поля:
*   `auth.accessor` — accessor auth-метода
*   `auth.metadata` — метаданные роли
*   `client_token` — полученный токен (или его отсутствие при ошибке)

### Мониторинг и алерты

При развертывании AppRole в production добавьте мониторинг ключевых метрик:

| Что мониторить | Команда / Метод | Критерий алерта |
| :--- | :--- | :--- |
| Доступность Vault | `curl -sk $VAULT_ADDR/v1/sys/health` | HTTP 5xx или таймаут |
| Неудачи аутентификации | Аудит-лог или Prometheus метрики | Рост ошибок `permission denied` на `auth/approle/login` |
| Истечение `SecretID` | Время последней выдачи через `vault list` + `secret_id_ttl` | Отсутствие новых SecretID за `secret_id_ttl * 2` |
| Количество активных токенов | `vault token lookup -format=json \| jq '[.data[] | select(.policies[] | contains("payment-policy"))] | length'` | Рост без объяснения |
| Успешное продление токенов Agent | Метрика `vault.agent.auth.token.renewal.success` | Отсутствие метрики в течение `2 × token_ttl` |

### Устранение неполадок

| Ошибка / Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `permission denied` при создании роли | Недостаточно прав у токена, под которым выполняется команда. | Проверьте политику: нужны права на `auth/approle/role/*`. |
| `permission denied` при login | Роль не существует или `bind_secret_id=true`, а `SecretID` не передан / неверен. | Проверьте `vault read auth/approle/role/<role>`, убедитесь в валидности `SecretID`. |
| `invalid secret id` | `SecretID` истек, превышен `secret_id_num_uses`, или запрос с запрещенного CIDR. | Выполните `vault write auth/approle/role/<role>/secret-id/lookup` и проверьте `secret_id_accessor`. |
| `user is locked out` | Сработал User Lockout после неудачных попыток. | Подождите `lockout_duration` или отключите блокировку через `auth tune` (не рекомендуется для production). |
| `already unwrapped` | Попытка повторного развертывания оберточного токена. | Сгенерируйте новый SecretID; оберточный токен можно развернуть только один раз. |
| `connection refused` / `no such host` | Vault недоступен или DNS не разрешается. | Проверьте сетевое соединение и `VAULT_ADDR`. |
| `certificate signed by unknown authority` | Сертификат Vault не подписан доверенным CA. | Укажите `ca_cert` в конфигурации агента или переменной окружения. |
| `token lookup self failed` | Токен истек или был отозван. | Проверьте `token_ttl` и работу renew в агенте. |
| `lease is not renewable` | Аренда секрета не поддерживает продление. | Нормально для `batch` токенов; используйте `service` или `periodic`, если требуется продление. |
| `agent failed to start after auth` | Ошибка в шаблоне или недоступность секрета после аутентификации. | Запустите с `-log-level=debug`, проверьте синтаксис шаблона и права. |

### Аптечка реагирования на компрометацию

При признаках утечки `SecretID` или токена действуйте по порядку:

1.  **Отзыв выданных токенов** роли, чтобы прервать активные сессии:
    ```bash
    vault token revoke -mode=path auth/approle/login
    ```
2.  **Уничтожение** всех активных `SecretID` роли (см. раздел «Ротация и отзыв SecretID»).
3.  **Генерация нового** `SecretID` и безопасная доставка приложению через оберточный токен.
4.  **Пересмотр политик**, привязанных к роли, и `token_bound_cidrs`.

### Ограничения и крайние случаи

*   **IPv6 в `token_bound_cidrs` / `secret_id_bound_cidrs`:** CIDR в Vault поддерживают IPv6. Указывайте адреса в квадратных скобках, например `[2001:db8::]/32`.
*   **Периодическая ротация `SecretID`:** Vault не умеет автоматически ротировать `SecretID` по таймеру. Ротацию реализует внешний оркестратор (Ansible, система управления конфигурацией, Kubernetes Operator), который по cron получает новый `SecretID` и обновляет секрет в целевом хранилище.
*   **Максимальный размер `custom-secret-id`:** При использовании Push-модели (`custom-secret-id`) значение не может превышать 32 KiB.
*   **Одновременное использование `SecretID`:** Если `secret_id_num_uses > 1`, Vault уменьшает счетчик при каждом успешном логине. При исчерпании лимита все последующие попытки завершатся ошибкой, даже если `SecretID` технически еще не истек по TTL.
*   **Зависимость от доступности Vault:** При недоступности Vault приложение не сможет обновить токен. Для повышения отказоустойчивости используйте Vault Agent с персистентным кэшем (`persist "file"`), который позволяет пережить кратковременные простои без повторной аутентификации.

### См. также

*   **[Основные концепции Vault](../concepts.md)** — архитектурные основы.
*   **[Авторизация и политики](../authorization.md)** — синтаксис и принципы управления доступом.
*   **[Vault Agent — базовая конфигурация](./vault_agent/basics.md)** — автоматизация аутентификации и ротации токенов.
*   **[Подход Zero Trust](../zero_trust.md)** — AppRole в модели нулевого доверия и альтернативы (WIF).
*   **[Антипаттерны управления секретами](../common_antipatterns.md)** — почему нельзя хранить `SecretID` в Git.

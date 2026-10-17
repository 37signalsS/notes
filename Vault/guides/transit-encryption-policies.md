# Политики Transit Engine в Vault

**Актуально для:** Vault 2.x (latest 2.1.2; ветка 1.21.x поддерживается)

> **Статус:** Transit secrets engine доступен в OSS Vault. Функции BYOK (import/export), управление ключами через Managed Keys (`managed_key`), квантово-устойчивые алгоритмы (`ml-dsa`, `slh-dsa`, `hybrid`) и `aes*-cmac`/`aes*-cbc` доступны только в Vault Enterprise.

## Предварительные требования

- **Vault версии 1.15+ (рекомендуется 2.x)** — Transit secrets engine доступен в OSS.
- **Enterprise** — для импорта/экспорта ключей (BYOK), Managed Keys, `aes*-cmac`/`aes*-cbc`/`ml-dsa`/`slh-dsa`/`hybrid` типов.
- **TLS** — обязательна для production; все клиентские соединения к Transit должны использовать TLS 1.2+.
- **Audit logging включён** — Transit операции логируются с хэшированными значениями; требуется минимум один audit device (file + syslog рекомендуется для отказоустойчивости).
- **Политика доступа** — субъекту требуется минимум `update` capability на нужный путь (`transit/encrypt/<key>`, `transit/decrypt/<key>` и т.д.).
- **Key derivation** — если используется `derived=true`, каждый запрос обязан передавать `context` (base64); контекст не должен повторяться для разных сущностей с тем же ключом (иначе нарушится изоляция).
- **Конвергентное шифрование** — требует `derived=true` + `convergent_encryption=true` при создании ключа; каждая операция обязана передавать `context`.

## Определения

**Transit Engine** — это движок секретов Vault, реализующий модель «криптография как сервис» (Cryptography as a Service, CaaS). Он позволяет приложениям выполнять шифрование, расшифровку, подписание данных и генерацию хэшей без прямого доступа к криптографическим ключам.

**Политика Transit Engine** — это декларативный набор правил в формате HCL, определяющий полномочия субъекта (приложения или администратора) на выполнение конкретных криптографических операций с определенными ключами.

**Деривация ключей (Key Derivation)** — механизм создания уникальных дочерних ключей на основе мастер-ключа и предоставленного контекста. Позволяет изолировать данные разных пользователей или сущностей в рамках одного ключа Vault.

**Пакетные операции (Batch Input)** — механизм отправки нескольких криптографических запросов (шифрование, расшифровка, подпись, HMAC) в одном HTTP-запросе через массив `batch_input`. Используется для снижения количества round-trip к Vault и повышения пропускной способности.

**Ключ данных (Data Key)** — эфемерный симметричный ключ, генерируемый Vault и зашифрованный Transit-ключом. Используется в паттерне envelope encryption, где приложение работает с открытым ключом данных, а шифротекст ключа данных сохраняется вместе с зашифрованными данными.

**Конвергентное шифрование (Convergent Encryption)** — режим, при котором одинаковые входные данные и контекст всегда производят одинаковый шифротекст. Позволяет выполнять поиск по зашифрованным полям без их расшифровки.

**Минимизация версий (Trim)** — операция принудительного удаления старых версий ключа. После trim данные, зашифрованные удалёнными версиями, расшифровать невозможно.

## Основные концепции

### Принципы безопасности Transit Engine

*   **Изоляция ключей:** Ключи никогда не покидают Vault. Приложение отправляет данные (plaintext), Vault возвращает зашифрованный результат (ciphertext).
*   **Разделение обязанностей (Separation of Duties):** Четкое разграничение между администраторами, управляющими жизненным циклом ключей (создание, ротация, удаление), и потребителями (шифрование/расшифровка).
*   **Контекстная безопасность:** Использование `context` при деривации ключей гарантирует, что одинаковые данные разных пользователей будут иметь разные шифротексты.
*   **Минимизация привилегий:** Ограничение не только по путям, но и по допустимым параметрам запроса (например, принудительное использование конкретной версии ключа).
*   **Аудит без раскрытия секретов:** В логах аудита Vault криптографические операции помечаются хэшированными значениями, что позволяет отслеживать активность без раскрытия plaintext или ciphertext.

### Жизненный цикл ключа Transit

Каждый ключ Transit проходит следующие этапы:

1.  **Создание:** Политика должна разрешать `create` на `transit/keys/<name>`. Vault генерирует мастер-ключ и нулевую версию.
2.  **Настройка:** Через `transit/keys/<name>/config` задаются параметры: `min_encryption_version`, `min_decryption_version`, `deletion_allowed`, `exportable`. Изменения влияют только на последующие операции.
3.  **Ротация:** Операция `transit/keys/<name>/rotate` создает новую версию ключа. Старые версии остаются доступными для расшифровки до явного trim или до наступления `min_decryption_version`.
4.  **Эксплуатация:** Приложения вызывают `encrypt`, `decrypt`, `rewrap`, `sign`, `verify`, `hmac`, `datakey`. Каждая операция может указывать версию через параметр `version`.
5.  **Очистка (Trim):** `transit/keys/<name>/trim` удаляет старые версии ниже порога. После этого данные, зашифрованные удалёнными версиями, расшифровать невозможно.
6.  **Удаление:** Удаление ключа (`delete` на `transit/keys/<name>`) требует `deletion_allowed=true` и удаляет все версии. Для критически важных ключей `deletion_allowed` должен оставаться `false`.

### Возможности и пути API

Политики строятся вокруг эндпоинтов движка `transit` (по умолчанию монтируется в `transit/`):

| Путь | Операция | Capabilities | Описание |
| :--- | :--- | :--- | :--- |
| `transit/keys/<name>` | Управление | `create`, `read`, `update`, `delete`, `list` | Создание и настройка параметров ключа. |
| `transit/keys/<name>/config` | Настройка | `update` | Изменение `min_decryption_version`, `min_encryption_version`, `deletion_allowed`, `exportable` и др. |
| `transit/keys/<name>/rotate` | Ротация | `update` | Генерация новой версии ключа. |
| `transit/keys/<name>/trim` | Очистка | `update` | Удаление старых версий ключа (`min_available_version=<N>`); данные, зашифрованные удалёнными версиями, расшифровать невозможно. |
| `transit/keys/<name>/import` | Импорт | `update` | Импорт внешнего ключа (BYOK). Enterprise; для `hmac`-ключей доступен в OSS. |
| `transit/keys/<name>/import_version` | Добавление версии | `update` | Импорт новой версии в существующий ключ (Enterprise). |
| `transit/wrapping_key` | Wrapping key | `read` | Чтение 4096-бит RSA public key для BYOK (Enterprise). |
| `transit/export/<key_type>/<name>` | Экспорт | `read` | Экспорт ключевого материала (`key_type`: `encryption-key`, `signing-key`, `hmac-key`, `public-key`, `certificate-chain`, `cmac-key`). Требует `exportable=true`. Enterprise. |
| `transit/encrypt/<name>` | Шифрование | `update` | Преобразование plaintext в ciphertext. Поддерживает `context`, `associated_data`, `batch_input`. |
| `transit/decrypt/<name>` | Расшифровка | `update` | Преобразование ciphertext в plaintext. Поддерживает `context`, `batch_input`. |
| `transit/rewrap/<name>` | Перешифрование | `update` | Перекодировка ciphertext на текущую версию ключа без возврата plaintext. |
| `transit/datakey/plaintext/<name>` | Ключ данных (plaintext) | `update` | Генерация эфемерного ключа данных + шифротекст ключа (паттерн envelope). |
| `transit/datakey/wrapped/<name>` | Ключ данных (wrapped) | `update` | Генерация эфемерного ключа данных — только шифротекст ключа. |
| `transit/hmac/<name>[/sha2-256]` | HMAC | `update` | Вычисление HMAC входных данных. Алгоритм хэша в URL (`/sha2-256`, `/sha2-384`, `/sha2-512`). |
| `transit/random` | Генерация | `update` | Генерация криптографически безопасного случайного набора байт. |
| `transit/sign/<name>[/<hash>]` | Подписание | `update` | Создание цифровой подписи (`hash`: `sha2-256`, `sha2-384`, `sha2-512` и т.д.). |
| `transit/verify/<name>[/<hash>]` | Проверка | `update` | Валидация цифровой подписи. |

> **Пакетные операции:** Шифрование, расшифровка, rewrap, подпись и HMAC поддерживают упаковку множества элементов в один запрос через «пакетный ввод» `batch_input` — массив объектов. Ответ возвращается в `batch_results` с теми же порядком элементов. При использовании `batch_input` параметры верхнего уровня (`plaintext`, `context`, `nonce`) игнорируются. Каждый элемент может содержать:
> - `reference` — произвольная строка, возвращаемая в `batch_results` для сопоставления входа с результатом;
> - `plaintext` / `ciphertext` — данные для обработки;
> - `context` — base64 контекст для деривации;
> - `nonce` — для convergent encryption (только ключи < Vault 0.6.2);
> - `associated_data` — base64 AAD для AEAD-шифров (`aes*-gcm96`, `chacha20-poly1305`);
> - `key_version` — явная версия ключа;
> - `padding_scheme` — для RSA-CBC (`PKCS1v15`, `OAEP` и т.д.);
> - `iv` — пользовательский IV для AES-CBC.
> 
> Если отдельный элемент завершается ошибкой, но другие успешны, по умолчанию HTTP-код ответа — 400 (Bad Request). Параметр `partial_failure_response_code` позволяет вернуть иной код (например, 200) для удобства пакетной обработки: если все элементы fail — всегда возвращается 400.

> **Версионирование:** Все криптографические операции поддерживают параметр `version` для явного указания версии ключа. Если параметр опущен, используется `min_encryption_version` (для encrypt) или `min_decryption_version` (для decrypt). Это позволяет принудительно запретить использование устаревших версий для новых операций, сохраняя обратную совместимость для чтения старых данных.

> **Associated Data (AAD):** Для AEAD-шифров (`aes128-gcm96`, `aes256-gcm96`, `chacha20-poly1305`) параметр `associated_data` (base64) позволяет аутентифицировать дополнительные данные без шифрования. AAD должен передаваться при каждом вызове encrypt и decrypt — при несовпадении операция завершится ошибкой. Добавьте `"associated_data" = []` в `allowed_parameters` политики, если приложение использует AAD.

> **CLI `vault transit`:** Начиная с Vault 1.17, доступен подмнкож `vault transit` с подкомандами `import`/`import-version` (BYOK) и `envelope encrypt`/`envelope decrypt`/`envelope header` для файлового шифрования. Пример: `vault transit envelope encrypt transit/keys/my-key file.txt` — шифрует файл с использованием ключа Transit. Для операций encrypt/decrypt/sign на отдельных значениях используйте `vault write transit/encrypt/<key>`.

### Типы ключей

При создании ключа параметр `type` определяет алгоритм и допустимые операции. Для современных инсталляций Transit Engine поддерживает:

| `type` | Алгоритм | Операции | Enterprise |
| :--- | :--- | :--- | :--- |
| `aes256-gcm96` | AES-256-GCM, 96-бит nonce (по умолчанию) | Шифрование, расшифровка, деривация, конвергентное шифрование | OSS |
| `aes128-gcm96` | AES-128-GCM, 96-бит nonce | Шифрование, расшифровка, деривация, конвергентное шифрование | OSS |
| `chacha20-poly1305` | ChaCha20-Poly1305, 256-бит ключ | Шифрование, расшифровка, деривация, конвергентное шифрование | OSS |
| `ed25519` | Ed25519 (асимметричный) | Подпись, проверка подписи, деривация | OSS |
| `ecdsa-p256` / `p384` / `p521` | ECDSA на кривых NIST | Подпись, проверка подписи | OSS |
| `rsa-2048` / `rsa-3072` / `rsa-4096` | RSA | Шифрование/расшифровка (OAEP), подпись/проверка (PSS, PKCS#1 v1.5) | OSS |
| `hmac` | HMAC (SHA-256 по умолчанию) | HMAC-генерация, HMAC-проверка, поддержка import в OSS | OSS |
| `aes128-gcm96-nofallback` | AES-256-GCM без fallback | Шифрование, расшифровка | Enterprise |
| `aes128-cbc` | AES-128-CBC | Шифрование, расшифровка (с padding scheme) | Enterprise (FIPS Inside) |
| `aes256-cbc` | AES-256-CBC | Шифрование, расшифровка (с padding scheme) | Enterprise (FIPS Inside) |
| `aes128-cmac` | AES-128-CMAC | CMAC-генерация, CMAC-проверка | Enterprise |
| `aes192-cmac` | AES-192-CMAC | CMAC-генерация, CMAC-проверка | Enterprise |
| `aes256-cmac` | AES-256-CMAC | CMAC-генерация, CMAC-проверка | Enterprise |
| `managed_key` | Внешний ключ (HSM/KMS) | Зависит от backing solution | Enterprise |
| `ml-dsa` | Квантово-устойчивый (CRYSTALS-Dilithium) | Подпись, проверка подписи | Enterprise |
| `slh-dsa` | Квантово-устойчивый (SPHINCS+) | Подпись, проверка подписи | Enterprise |
| `hybrid` | Комбинированный (классический + PQC) | Подпись, проверка подписи | Enterprise |

Все типы ключей дополнительно получают отдельный случайный ключ для операций HMAC.

> **Примечание (режим FIPS 140-3):** в FIPS 140-3 режиме следующие алгоритмы не сертифицированы и не должны использоваться: `chacha20-poly1305` и `ed25519`. Используйте `aes*-gcm96` для шифрования и `ecdsa-*` / `rsa-*` для подписи.

> **Примечание (key_usages, Vault 2.2.0+):** начиная с Vault 2.2.0 каждый ключ имеет поле `key_usages`, выводимое в ответах `keys/`, `algorithm/` и `config/` endpoints. Это позволяет клиенту программно определять, какие операции поддерживает ключ:
> 
> | `key_usage` | Key Types |
> | :--- | :--- |
> | `aead-encryption` | `aes128-gcm96`, `aes256-gcm96`, `chacha20-poly1305` |
> | `symmetric-encryption` | `aes128-cbc`, `aes256-cbc` |
> | `digital-signature` | `ecdsa-p256`, `ecdsa-p384`, `ecdsa-p521`, `ed25519`, `ml-dsa`, `slh-dsa`, `hybrid`, `rsa-2048`, `rsa-3072`, `rsa-4096` |
> | `asymmetric-encryption` | `rsa-2048`, `rsa-3072`, `rsa-4096` |
> | `message-authentication` | `hmac`, `aes128-cmac`, `aes192-cmac`, `aes256-cmac` |
> 
> При ротации через `algorithm/` endpoint новый тип ключа должен иметь совместимый `key_usage`.

Все типы ключей дополнительно получают отдельный случайный HMAC-ключ при создании и ротации, что позволяет выполнять HMAC-операции для любого типа ключа. Для асимметричных ключей (`ed25519`, `ecdsa-*`, `rsa-*`) перед подписью входные данные хэшируются (кроме `ed25519`, который выполняет Ed25519ph-хэширование внутри — для него `derived=true` даёт детерминированную подпись с тем же `context`).

### Паттерн Envelope Encryption (Data Key)

Вместо того чтобы передавать plaintext в Vault для каждого вызова, приложение может запросить одноразовый **ключ данных (Data Key)**, зашифрованный Transit-ключом. Приложение работает с открытым ключом данных локально, а шифротекст ключа данных сохраняется вместе с зашифрованными данными.

Преимущества паттерна:
*   Снижение нагрузки на Vault (шифрование данных выполняется локально).
*   Ограничение размера plaintext (API Vault имеет лимиты на тело запроса).
*   Возможность офлайн-шифрования между обращениями к Vault.

Поддерживаются два режима:
*   `transit/datakey/plaintext/<name>` — возвращает и открытый ключ, и шифротекст ключа.
*   `transit/datakey/wrapped/<name>` — возвращает только шифротекст ключа (приложение никогда не видит открытый ключ).

### Конвергентное шифрование (Convergent Encryption)

Позволяет получать одинаковый шифротекст для одинаковых входных данных и контекста. Это необходимо для реализации **поиска по зашифрованным полям** в базах данных (поиск по точному совпадению без раскрытия данных).

*   Требует параметра `derived=true` **и** `convergent_encryption=true` при создании ключа.
*   Требует обязательного наличия `context` при каждой операции.
*   Для ключей, созданных до Vault 0.6.2, каждый запрос должен передавать детерминированный `nonce` (96 бит); для ключей, созданных в 0.6.2 и новее, nonce выводится автоматически.

Механизм работает путем деривации ключа и детерминированной генерации nonce: риск повторного использования nonce стремится к нулю на пространстве ключей ~2^256. Расшифровка работает в обычном режиме — одинаковый контекст и конвергенция не влияют на возможность расшифровать данные.

### Взаимодействие с движками секретов и Identity

Политики Transit не существуют изолированно. Для корректной работы необходимо:

1.  **Аутентификация:** Приложение должно получить токен через auth-метод (AppRole, Kubernetes, JWT и т.д.). Подробнее — в **[Руководстве по AppRole](./vault_auth_approle.md)**.
2.  **Привязка политики:** Политика Transit привязывается к токену напрямую или через групппу Identity Store. Это позволяет централизованно управлять доступом для групп приложений.
3.  **Аудит:** Для отслеживания операций Transit настройте audit device. Рекомендуется минимум два устройства (file + syslog) для отказоустойчивости логов.

## Практические сценарии

### Сценарий 1: Политика для приложения (Наименьшие привилегии)

Приложению требуется шифровать и расшифровывать данные пользователей, используя деривацию ключей для изоляции.

```hcl
# Разрешить шифрование с обязательным контекстом
path "transit/encrypt/user-data" {
  capabilities = ["update"]
  allowed_parameters = {
    "context" = [] # Контекст (base64) обязателен
    "plaintext" = []
    "version" = [] # Опционально: явное указание версии
  }
}

# Разрешить расшифровку
path "transit/decrypt/user-data" {
  capabilities = ["update"]
  allowed_parameters = {
    "context" = []
    "ciphertext" = []
    "version" = []
  }
}
```

Политика обеспечивает:
*   Приложение может работать только с одним ключом `user-data`.
*   Параметр `context` обязателен для деривации.
*   Нет прав на управление ключом (создание, ротация, удаление).

#### Валидация и проверка

```bash
# 1. Создать ключ с деривацией
vault write -f transit/keys/user-data type=aes256-gcm96 derived=true

# 2. Проверить, что приложение может шифровать
vault write transit/encrypt/user-data \
  plaintext=$(echo -n "test" | base64) \
  context=$(echo -n "user-123" | base64)
# → ciphertext: vault:v1:...

# 3. Проверить, что приложение НЕ может создавать ключи
vault write -f transit/keys/forbidden-type
# → Error reading: forbidden

# 4. Проверить, что приложение НЕ может экспортировать ключи
vault read transit/export/encryption-key/user-data
# → Forbidden
```

### Сценарий 2: Политика администратора безопасности (Crypto Officer)

Администратор может создавать ключи и проводить их ротацию, но не имеет прав на расшифровку данных (защита от инсайдера).

```hcl
# Управление всеми ключами (создание, просмотр параметров, список)
path "transit/keys/*" {
  capabilities = ["create", "read", "update", "list"]
}

# Разрешить ротацию ключей
path "transit/keys/*/rotate" {
  capabilities = ["update"]
}

# Явный запрет на расшифровку любых данных
path "transit/decrypt/*" {
  capabilities = ["deny"]
}

# Запретить trim без дополнительного подтверждения
path "transit/keys/*/trim" {
  capabilities = ["deny"]
}
```

> **Важно:** Политика `deny` на `transit/decrypt/*` имеет высший приоритет и перекрывает любые другие разрешения на этом пути. Это гарантирует, что Crypto Officer не может увидеть plaintext даже при наличии прав root на другие ресурсы.

### Сценарий 3: Паттерн Envelope Encryption (Data Key)

Приложение работает с большими объемами данных и хочет минимизировать обращения к Vault. Используется паттерн envelope encryption:

```hcl
# Приложение может запрашивать ключи данных
path "transit/datakey/plaintext/app-encryption" {
  capabilities = ["update"]
  allowed_parameters = {
    "context" = []
  }
}

# Приложение может расшифровывать ключи данных
path "transit/decrypt/app-encryption" {
  capabilities = ["update"]
  allowed_parameters = {
    "ciphertext" = []
  }
}
```

Алгоритм работы:
1.  Приложение запрашивает `datakey/plaintext/app-encryption` и получает `plaintext_data_key` + `wrapped_data_key`.
2.  Приложение шифрует данные локально с использованием `plaintext_data_key` (AES-GCM).
3.  В хранилище сохраняются: `ciphertext` (зашифрованные данные) + `wrapped_data_key` + метаданные.
4.  Для расшифровки приложение отправляет `wrapped_data_key` в `transit/decrypt/app-encryption` и получает `plaintext_data_key`.

#### Валидация и проверка

```bash
# 1. Проверка наличия datakey endpoint в политике
vault policy read app-transit-policy
# → должна содержать путь transit/datakey/plaintext/app-encryption

# 2. Проверка выдачи data key
vault write transit/datakey/plaintext/app-encryption \
  context=$(echo -n "app-context" | base64)
# → plaintext_data_key: ...
# → ciphertext: vault:v1:...

# 3. Проверка обратимости: расшифровать data key и сравнить
#    (plaintext_data_key используется локально, wrapped_data_key сохраняется)
DECRYPTED=$(vault write transit/decrypt/app-encryption \
  ciphertext="vault:v1:..." -format=json | jq -r .data.plaintext)
[ "$DECRYPTED" = "$ORIGINAL_PLAINTEXT_KEY" ] && echo "Match OK"
```

> **Важно:** `plaintext_data_key` никогда не должен сохраняться в хранилище. Только `wrapped_data_key` сохраняется вместе с зашифрованными данными.

### Сценарий 4: Подписание и проверка подписи (Signing/Verification)

Приложение подписывает отчёты, а проверка выполняется стороной. Ключ `report-signing` имеет тип `ed25519`.

```hcl
# Подписание отчётов
path "transit/sign/report-signing/sha2-256" {
  capabilities = ["update"]
  allowed_parameters = {
    "input" = []
    "context" = []
  }
}

# Проверка подписи
path "transit/verify/report-signing/sha2-256" {
  capabilities = ["update"]
  allowed_parameters = {
    "input" = []
    "signature" = []
    "context" = []
  }
}

# Администратор управляет ключом
path "transit/keys/report-signing" {
  capabilities = ["create", "read", "update", "list"]
}

# Явный запрет на расшифровку (для асимметричного ключа не применимо, но оставляем для безопасности)
path "transit/decrypt/report-signing" {
  capabilities = ["deny"]
}
```

> **Примечание:** Для асимметричных ключей путь подписи включает хэш-алгоритм (`/sha2-256`). При изменении алгоритма подписи потребуется обновить политику или разрешить несколько путей.

#### Валидация и проверка

```bash
# 1. Создать ключ ed25519 для подписи
vault write -f transit/keys/report-signing type=ed25519

# 2. Подписать данные
echo -n "important report content" | base64
# → aW1wb3J0YW50IHJlcG9ydCBjb250ZW50

SIGNATURE=$(vault write transit/sign/report-signing/sha2-256 \
  input=aW1wb3J0YW50IHJlcG9ydCBjb250ZW50 -format=json | \
  jq -r '.data.signature')
# → signature: vault:v1:...

# 3. Проверить подпись
vault write transit/verify/report-signing/sha2-256 \
  input=aW1wb3J0YW50IHJlcG9ydCBjb250ZW50 \
  signature="$SIGNATURE"
# → valid: true
```

### Сценарий 5: Мониторинг, аудит и диагностика

#### Мониторинг через Syslog

Настройте audit device для фиксации всех операций Transit:

```bash
# Включение audit device (file)
vault audit enable file file_path=/var/log/vault/audit.log

# Включение audit device (syslog) для отказоустойчивости
vault audit enable syslog tag="vault-transit" facility="AUTH"
```

#### Метрики Prometheus (если используется Vault с Prometheus exporter)

| Метрика | Описание |
| :--- | :--- |
| `vault.core.unsealed` | Состояние распечатанности (1 = unsealed). |
| `vault.cache.hit` / `vault.cache.miss` | Эффективность кэша запросов Transit. |
| `vault.token.count.by_policy` | Количество токенов с привязанной политикой Transit. |

#### Диагностика состояния кластера

```bash
# Проверка статуса Vault
vault status
# → Sealed: false
# → Version: 1.xx.x
# → Cluster Name: vault-cluster
# → HA Cluster: active (self)

# Проверка смонтированных движков
vault secrets list -detailed
# → transit/  transit

# Проверка ключей Transit
vault list transit/keys
# → Keys
# ---
# app-encryption
# user-data
# report-signing

# Проверка параметров конкретного ключа
vault read transit/keys/user-data
# → Key Type: aes256-gcm96
# → Versions:
#   - 5 (рабочая)
#   - 4
#   - 3
# → Min Decryption Version: 1
# → Min Encryption Version: 4
# → Deletion Allowed: false
```

### Сценарий 6: Восстановление после сбоя (Disaster Recovery)

#### Миграция ключа Transit между кластерами

Для переноса ключа между кластерами Vault без потери данных используйте `vault export` / `vault import` (Enterprise) или rewrap в промежуточном кластере (OSS).

**OSS-подход (через промежуточный кластер):**

1.  На исходном кластере расшифруйте данные с помощью старого ключа.
2.  На целевом кластере создайте новый ключ с тем же типом и настройками.
3.  Перешифруйте данные через целевой ключ.
4.  Обновите `min_encryption_version` и `min_decryption_version` в целевой политике.

```bash
# На исходном кластере: перешифровка на новую версию ключа
vault write transit/rewrap/user-data \
  ciphertext="vault:v1:..." \
  context="base64_context"

# На целевом кластере: обновление параметров
vault write transit/keys/user-data/config \
  min_decryption_version=1 \
  min_encryption_version=3
```

> **Важно:** Перешифровка (rewrap) не раскрывает plaintext, но требует доступа к операциям `decrypt` и `encrypt` исходного ключа. Для полной переносимости ключей в OSS предусмотрите резервное копирование хранилища Vault (Raft snapshot).

#### Восстановление снапшотом

```bash
# Создание снапшота (Enterprise)
vault operator raft snapshot save /backup/vault.snap

# Восстановление
vault operator raft snapshot restore /backup/vault.snap
```

Для OSS используйте резервное копирование бэкенда хранения (файлы Raft или Consul snapshot).

### Сценарий 7: Очистка и откат

#### Удаление ключа (с подтверждением)

```bash
# Проверка параметра deletion_allowed
vault read transit/keys/user-data

# Включение возможности удаления
vault write transit/keys/user-data/config deletion_allowed=true

# Удаление ключа
vault delete transit/keys/user-data

# Откат: если удаление было ошибочным, единственный способ — восстановление из снапшота
```

#### Отзыв токенов с политикой Transit

```bash
# Поиск токенов с политикой transit-app
vault list auth/token/lookup-accessor

# Отзыв конкретного токена
vault token revoke <accessor>

# Каскадный отзыв всех дочерних токенов
vault token revoke -mode=orphan <parent_accessor>
```

#### Очистка старых версий (Trim)

```bash
# Просмотр текущих версий
vault read transit/keys/user-data

# Удаление версий 1-2 (оставить 3 и выше)
vault write transit/keys/user-data/trim min_available_versions=3

# Проверка результата
vault read transit/keys/user-data
```

> **Предупреждение:** Trim необратим. Убедитесь, что все данные, зашифрованные удаляемыми версиями, либо расшифрованы и перешифрованы на актуальную версию, либо больше не требуются.

### Сценарий 8: Конфигурация в production (systemd + TLS)

Развёртывание Transit Engine в production-среде с systemd, отдельным процессом Vault и mTLS к Consul (при использовании Consul backend):

```bash
# /etc/vault.d/vault.hcl (фрагмент)
storage "consul" {
  address = "127.0.0.1:8500"
  path    = "vault/"
}

listener "tcp" {
  address       = "127.0.0.1:8200"
  tls_cert_file = "/etc/vault.d/vault.crt"
  tls_key_file  = "/etc/vault.d/vault.key"
}

seal "transit" {
  address            = "https://vault-unsealer:8200"
  token              = "<recovery-token>"
  disable_renewal    = false

  tls_ca_cert_file   = "/etc/vault.d/vault-unsealer.crt"
  tls_client_cert_file = "/etc/vault.d/vault-client.crt"
  tls_client_key_file  = "/etc/vault.d/vault-client.key"
}

# /etc/systemd/system/vault.service
[Unit]
Description="HashiCorp Vault"
After=network-online.target
Wants=network-online.target

[Service]
Type=notify
ExecStart=/usr/bin/vault server -config=/etc/vault.d/vault.hcl
Restart=on-failure
LimitNOFILE=65536
Environment=VAULT_ADDR=https://127.0.0.1:8200
Environment=VAULT_CACERT=/etc/vault.d/vault.crt

[Install]
WantedBy=multi-user.target
```

```bash
# Применение конфигурации systemd
sudo systemctl daemon-reload
sudo systemctl enable --now vault

# Проверка статуса
sudo systemctl status vault
vault status
```

## Лучшие практики

### Управление ключами

1.  **Base64 кодирование:** Все данные, передаваемые в параметры `plaintext` и `context`, должны быть закодированы в Base64.
2.  **Версионность:** Регулярно проводите ротацию ключей (`/rotate`). Vault поддерживает расшифровку старыми версиями ключей автоматически. Используйте `min_encryption_version` для принудительного перехода на новую версию.
3.  **Удаление ключей:** Всегда устанавливайте `deletion_allowed=false` для критически важных ключей, чтобы предотвратить случайное удаление данных.
4.  **Разделение ключей:** Используйте разные ключи для разных окружений (dev/staging/prod) и классов данных (PII, финансы, логи). Это ограничивает взрывной радиус компрометации.
5.  **Ротация по расписанию:** Настройте автоматическую ротацию ключей через cron или scheduler (например, ротация каждые 90 дней). Ротация не прерывает работу приложений, так как старые версии остаются доступными.
6.  **Trim с осторожностью:** Перед trim убедитесь, что все потребители обновлены до работы с актуальной версией ключа. Trim удаляет старые версии безвозвратно.
7.  **Контекстная изоляция:** Всегда передавайте уникальный `context` для каждого пользователя/сущности. Переиспользование контекста между разными сущностями сводит на нет изоляцию деривации ключей.
8.  **Конвергентное шифрование:** Используйте только для поиска по зашифрованным полям. Не используйте для шифрования данных, где безопасность важнее поиска — конвергентное шифрование ослабляет свойства случайности nonce.
9.  **Envelope encryption:** Для больших объемов данных используйте datakey endpoints — plaintext_data_key сохранять НЕ должен.
10. **Audit logging:** Всегда включайте минимум один audit device для операций Transit. Рекомендуется file + syslog для отказоустойчивости.

#### Валидация и проверка

```bash
# Проверить, что ключ создан с ожидаемыми параметрами
vault read transit/keys/my-key -format=json | jq '{
  type: .data.type,
  derived: .data.derived,
  min_encryption_version: .data.min_encryption_version,
  min_decryption_version: .data.min_decryption_version,
  deletion_allowed: .data.deletion_allowed
}'

# Проверить, что политика разрешает нужные операции
vault policy read my-app-policy
# → должна содержать пути transit/encrypt/my-key и/или transit/decrypt/my-key

# Проверить, что аудит включен
vault audit list
# → file/ и/или syslog/
```

#### Очистка и откат

```bash
# Отозвать все токены с политикой Transit (перед сменой ключа)
vault list auth/token/lookup-accessor | tail -n +3 | while read accessor; do
  info=$(vault token lookup -format=json "$accessor" 2>/dev/null)
  policy=$(echo "$info" | jq -r '.data.policies' | grep -o 'transit-app' || true)
  [ -n "$policy" ] && vault token revoke "$accessor"
done

# Удалить ключ (только если deletion_allowed=true)
vault write transit/keys/my-key/config deletion_allowed=true
vault delete transit/keys/my-key
# → Откат: восстановление только из снапшота хранилища Vault

# Остановить ротацию (если настроена автоматическая)
# → удалить cron-задачу или oplog entry, отвечающий за ротацию
```

> **Предупреждение:** Trim и удаление ключей необратимы. Перед выполнением убедитесь, что данные, зашифрованные удаляемыми версиями, перешифрованы на актуальную версию (через rewrap).

## Устранение неполадок

### Типичные ошибки и решения

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `invalid request: key not found` | Ключ не создан или название указано неверно | `vault list transit/keys` — проверить существование ключа |
| `permission denied` на `transit/encrypt/my-key` | Политика не привязана к токену или deny-правило | `vault token lookup` — проверить политики; `vault policy read <policy>` — проверить пути |
| `missing context` при encrypt | Ключ создан с `derived=true`, но `context` не передан | Добавить `context=$(echo -n "user-123" | base64)` в запрос |
| `ciphertext verification failed` при decrypt | Несовпадение `context` или повреждение ciphertext | Проверить, что `context` совпадает с тем, что использовался при encrypt |
| `key version not found` | Версия ключа trim'нута или не существует | `vault read transit/keys/my-key` — проверить доступные версии; изменить `min_decryption_version` |
| `deletion not allowed` при `vault delete ` | `deletion_allowed=false` в конфиге ключа | `vault write transit/keys/my-key/config deletion_allowed=true` — затем удалить |
| `key type does not support this operation` | Например, `hmac`-операция на `ed25519`-ключ | Проверить тип ключа в `vault read transit/keys/my-key` и выбрать подходящий endpoint |
| `export failed: key is not exportable` | `exportable=false` в конфиге ключа | Пересоздать ключ с `exportable=true` (изменить нельзя после создания) |
| `associated_data required` / `associated_data mismatch` | AAD передан при encrypt, но не при decrypt (или наоборот) | Оба вызова должны передавать одинаковый `associated_data` |

### Диагностика

#### 1. Проверка статуса и смонтированных движков

```bash
vault status
# → Sealed: false, HA enabled: true/false

vault secrets list -detailed | grep transit
# → transit/  transit  default  true  secrets/sync

vault read transit/keys/my-key
# → Key Type, Versions, Min Decryption/Encryption Version, Deletion Allowed
```

#### 2. Проверка политик

```bash
# Какие политики привязаны к токену
vault token lookup -format=json | jq '.data.policies'

# Содержимое конкретной политики
vault policy read my-transit-policy

# Онлайн-проверка: попытка выполнить операцию
vault write transit/encrypt/my-key plaintext=$(echo -n "test" | base64) -tls-server-name=vault.example.com
# → error или ciphertext
```

#### 3. Аудит операций

```bash
# Поиск операций Transit в audit log
grep '"path":"transit/' /var/log/vault/audit.log | jq '{
  time: .time, method: .request.operation, path: .request.path,
  client: .request.client_token_identity_name
}'

# Фильтр по ключу и операции
grep 'transit/encrypt/my-key' /var/log/vault/audit.log | jq .
```

### Ограничения

- **Размер plaintext:** API Vault имеет лимит на размер тела HTTP-запроса (~10 МБ по умолчанию). Для больших данных используйте паттерн envelope encryption.
- **Export один раз:** Параметр `exportable=true` нельзя отключить после установки. Пересоздайте ключ, если экспорт больше не нужен.
- **Import (OSS):** В OSS доступен только импорт `hmac`-ключей. Импорт симметричных и асимметричных ключей требует Vault Enterprise.
- **Ротация не перешифровывает:** Ротация создаёт новую версию ключа, но существующие ciphertext остаются на старой версии. Используйте rewrap для перешифровки.
- **KMS-интеграция:** `managed_key` и квантово-устойчивые типы (`ml-dsa`, `slh-dsa`, `hybrid`) требуют Vault Enterprise + HSM/KMS.**

## Дополнительная информация

### Рекомендации по эксплуатации

1.  **Разделение ключей:** Используйте разные ключи для разных окружений (dev/staging/prod) и классов данных (PII, финансы, логи). Это ограничивает взрывной радиус компрометации.
2.  **Ротация по расписанию:** Настройте автоматическую ротацию ключей через cron или scheduler (например, ротация каждые 90 дней). Ротация не прерывает работу приложений, так как старые версии остаются доступными.
3.  **Контекстная изоляция:** Всегда передавайте уникальный `context` для каждого пользователя/сущности. Переиспользование контекста между разными сущностями сводит на нет изоляцию деривации ключей.
4.  **Размер plaintext:** Учитывайте лимиты на размер запроса Vault API (по умолчанию ~10 МБ). Для больших данных применяйте паттерн envelope encryption (datakey endpoints).
5.  **Ротация HSM/KMS:** Если используется `managed_key`, настройте ротацию ключей в HSM/KMS в соответствии с политикой организации.

### См. также

*   **[Авторизация и политики](../authorization.md)** — общие правила написания HCL, включая динамические пути с `{{identity.entity.metadata.*}}`.
*   **[Основные концепции Vault](../concepts.md)** — архитектура движков секретов и токенов.
*   **[Подход Zero Trust](../zero_trust.md)** — роль Transit в защите данных при передаче и хранении.
*   **[Руководство по AppRole](./vault_auth_approle.md)** — аутентификация приложений для доступа к Transit.

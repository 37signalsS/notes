# Аутентификация в Vault через AppRole

## Определения

* **AppRole** — метод [аутентификации](../concepts.md#методы-аутентификации-и-токены) в [HashiCorp Vault](../overview.md), предназначенный для машин и приложений. Работает по принципу пары "логин/пароль" с расширенной гибкостью и контролем.

## Основные концепции

Основными компонентами AppRole являются:

* **RoleID:** Идентификатор роли. Можно считать его "логином". Обычно не является секретом.
* **SecretID:** Секретный идентификатор. Аналог "пароля". Должен безопасно доставляться приложению.

Приложение предоставляет `RoleID` и `SecretID` для аутентификации в Vault и в ответ получает токен с привязанными к роли [политиками](../concepts.md#политики-доступа-policies).

### Параметры безопасности AppRole

| Параметр | Описание | Рекомендация |
| :--- | :--- | :--- |
| `bind_secret_id` | Требовать SecretID для аутентификации | `true` (обычно) или `false` (при строгом ограничении по CIDR) |
| `secret_id_bound_cidrs` | IP-адреса, с которых можно создать SecretID | Ограничить сетью управления |
| `token_bound_cidrs` | IP-адреса, с которых можно использовать токен | **Обязательно** ограничить сетью приложения |
| `secret_id_num_uses` | Максимальное использований SecretID | Ограничить для одноразовых развёртываний |
| `secret_id_ttl` | Время жизни SecretID | Установить TTL (например, 24h) |
| `token_ttl` | Время жизни выдаваемого токена | Короткий TTL (например, 1h) |

## Повышение безопасности: Bound CIDRs и bind_secret_id: false

Для усиления защиты в средах CI/CD и микросервисов можно использовать комбинацию ограничений.

### 1. Ограничение по подсетям (Bound CIDRs)
Вы можете привязать возможность получения токена к конкретным IP-адресам или подсетям (например, IP-адреса ваших CI-раннеров).
- `secret_id_bound_cidrs`: Список CIDR, с которых разрешена операция логина с этим SecretID.
- `token_bound_cidrs`: Список CIDR, с которых разрешено использовать выданный токен.

Это гарантирует, что даже если `RoleID` и `SecretID` будут украдены, злоумышленник не сможет ими воспользоваться извне вашей инфраструктуры.

### 2. Использование без SecretID (`bind_secret_id: false`)
В некоторых сценариях (например, когда доставка SecretID затруднена, но сеть полностью доверенная) можно отключить требование SecretID.
- В этом режиме для аутентификации достаточно только `RoleID`.
- **ВНИМАНИЕ:** Этот режим крайне небезопасен без использования `token_bound_cidrs`. Его следует применять только в комбинации со строгим ограничением по IP-адресам источников запросов.

## Практические сценарии

### Включение метода аутентификации AppRole

Если метод еще не включен, его необходимо активировать.

```bash
vault auth enable approle
```

*В UI это делается на вкладке `Access` -> `Authentication Methods` -> `Enable new method`.*

### Пример: Связка Политики и Роли

Полный пример: предоставление приложению [`ansible`](../../Ansible/ansible_introduction.md) доступа на чтение секрета с токеном для [Consul](../../Consul/consul_overview.md).

#### Шаг 1. Создание секрета

```bash
# Включение K/V v2 хранилища
vault secrets enable -path=devops kv-v2

# Запись секрета
vault kv put devops/consul token="a1b2-c3d4-e5f6"
```

#### Шаг 2. Создание политики

Политика `consul-read-policy` для чтения пути `devops/data/consul` (K/V v2 требует `data` в пути):

```hcl
path "devops/data/consul" {
  capabilities = ["read", "list"]
}
```

```bash
vault policy write consul-read-policy consul-read-policy.hcl
```

#### Шаг 3. Создание роли

Создание роли `ansible` с привязкой политики `consul-read-policy`:

```bash
vault write auth/approle/role/ansible token_policies="consul-read-policy"
```

Параметры:

* `auth/approle/role/ansible` — путь создания роли `ansible`
* `token_policies` — список политик для токена

Дополнительно можно задать TTL токена, CIDR-ограничения, количество использований `SecretID`.

#### Шаг 4. Получение RoleID

```bash
vault read auth/approle/role/ansible/role-id
```

Результат:

```
Key        Value
---        -----
role_id    f4b3...
```

#### Шаг 5. Создание и получение SecretID

```bash
vault write -f auth/approle/role/ansible/secret-id
```

Результат:

```
Key                   Value
---                   -----
secret_id             b3e4...
secret_id_accessor    a1b2...
```

### Процесс аутентификации приложения

Аутентификация с использованием `RoleID` и `SecretID`:

```bash
vault write auth/approle/login \
    role_id="f4b3..." \
    secret_id="b3e4..."
```

Ответ Vault — временный токен с политиками роли:

```
Key                     Value
---                     -----
token                   s.tC...
token_policies          ["default" "consul-read-policy"]
token_duration          768h
token_renewable         true
```

Полученный токен используется для последующих запросов к Vault.

## Дополнительная информация

`SecretID` является секретом и не должен храниться в системах контроля версий или открытом доступе. Безопасная доставка: переменные окружения, облачные KMS, CI/CD-переменные или [Vault Agent](./vault_agent/basics.md).

Принципы Zero Trust в контексте AppRole описаны в разделе [Подход Zero Trust к управлению секретами](../zero_trust.md). Типичные ошибки работы с SecretID — в [Антипаттернах управления секретами](../common_antipatterns.md).

Полный список параметров и примеры использования: [официальная документация HashiCorp Vault AppRole](https://developer.hashicorp.com/vault/docs/auth/approle).

# Аутентификация в Vault через AppRole

## Определения

*   **AppRole** — это один из [методов аутентификации](../concepts.md#методы-аутентификации-auth-methods) в [HashiCorp Vault](../overview.md), предназначенный специально для машин и приложений. Он работает по аналогии с парой "логин/пароль", но предоставляет гораздо больше гибкости и контроля.

## Основные концепции

Основными компонентами AppRole являются:
*   **RoleID:** Идентификатор роли. Можно считать его "логином". Обычно не является секретом.
*   **SecretID:** Секретный идентификатор. Аналог "пароля". Должен безопасно доставляться приложению.

Приложение предоставляет `RoleID` и `SecretID` для аутентификации в Vault и в ответ получает токен с привязанными к роли [политиками](../concepts.md#политики-доступа-в-vault).

## Практические сценарии

### Включение метода аутентификации AppRole

Если метод еще не включен, его необходимо активировать.

```bash
vault auth enable approle
```
*В UI это делается на вкладке `Access` -> `Authentication Methods` -> `Enable new method`.*

### Пример: Связка Политики и Роли

Рассмотрим полный пример, где мы хотим дать приложению [`ansible`](../../Ansible/ansible_introduction.md) доступ на чтение секрета с токеном для [Consul](../../Consul/consul_overview.md).

#### Шаг 1. Создание секрета
Сначала положим сам секрет в K/V-хранилище (версии 2).

```bash
# Включаем K/V хранилище по пути 'devops', если его нет
vault secrets enable -path=devops kv-v2

# Кладем секрет
vault kv put devops/consul token="a1b2-c3d4-e5f6"
```

#### Шаг 2. Создание политики
Теперь создадим политику `consul-read-policy`, которая разрешает чтение данных по пути `devops/data/consul`. Для K/V v2 API путь к данным всегда содержит `data`.

```hcl
# consul-read-policy.hcl
path "devops/data/consul" {
  capabilities = ["read", "list"]
}
```

Загрузим политику в Vault:
```bash
vault policy write consul-read-policy consul-read-policy.hcl
```
*В UI политики создаются на вкладке `Policies` -> `Create ACL policy`.*

#### Шаг 3. Создание роли
Наконец, создадим роль `ansible` и привяжем к ней созданную политику.

```bash
# Создаем роль 'ansible' и привязываем к ней политику 'consul-read-policy'
vault write auth/approle/role/ansible token_policies="consul-read-policy"
```

*   `auth/approle/role/ansible`: Путь для создания роли с именем `ansible`.
*   `token_policies`: Список политик, которые будут привязаны к токену, полученному этой ролью.

Можно также задать другие параметры, например, TTL токена, ограничения по CIDR и количество использований `SecretID`.

#### Шаг 4. Получение RoleID

`RoleID` является публичным идентификатором роли.

```bash
vault read auth/approle/role/ansible/role-id
```

Результат будет содержать `role_id`:
```
Key        Value
---        -----
role_id    f4b3...
```

#### Шаг 5. Создание и получение SecretID

`SecretID` — это секрет, который используется для аутентификации.

```bash
# Ключ -f (force) используется, потому что операция POST, а не GET
vault write -f auth/approle/role/ansible/secret-id
```

Результат будет содержать `secret_id` и `secret_id_accessor` (идентификатор для управления `SecretID`).

```
Key                   Value
---                   -----
secret_id             b3e4...
secret_id_accessor    a1b2...
...
```

### Процесс аутентификации приложения

Приложение, имея на руках `RoleID` и `SecretID`, может выполнить вход.

```bash
vault write auth/approle/login \
    role_id="f4b3..." \
    secret_id="b3e4..."
```

В ответ Vault вернет временный токен, который приложение может использовать для запроса секретов в соответствии с привязанными к роли политиками.

```
Key                     Value
---                     -----
token                   s.tC...
accessor                nF9...
token_policies          ["default" "consul-read-policy"]
...
token_duration          768h
token_renewable         true
```
Этот токен (`s.tC...`) и используется для дальнейших запросов к Vault.

## Дополнительная информация

*   **Важно:** `SecretID` является секретом. Сохраните его и безопасно передайте вашему приложению. Никогда не храните `SecretID` в системе контроля версий или открытом доступе. Для безопасной доставки `SecretID` могут использоваться такие механизмы, как переменные окружения, облачные сервисы секретов или [Vault Agent](../guides/vault_agent_and_templates.md).
*   Для получения дополнительной информации о других параметрах AppRole (например, `bind_secret_id`, `secret_id_num_uses`, `secret_id_ttl`), обратитесь к [официальной документации HashiCorp Vault](https://developer.hashicorp.com/vault/docs/auth/approle).

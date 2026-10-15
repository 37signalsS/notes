# Zabbix — API и автоматизация (Monitoring as Code)

**Актуально для:** Zabbix 7.0 LTS / 7.4

## Определения

* **Zabbix API** — программный интерфейс управления Zabbix, встроенный в frontend и реализованный по протоколу **JSON-RPC 2.0** поверх HTTP(S). Endpoint — `<url_frontend>/api_jsonrpc.php`.
* **API-токен** — постоянный секрет для аутентификации без логина/пароля. Введён в Zabbix **5.4**; передаётся в заголовке `Authorization: Bearer <token>`.
* **`user.login`** — классический метод аутентификации, возвращающий `auth`-строку. Исторический способ; для автоматизации предпочтительнее токены.
* **`configuration.export` / `configuration.import`** — методы выгрузки и загрузки конфигурации (шаблоны, хосты, карты) в формате XML/YAML/JSON.
* **`history.push`** — метод прямой отправки исторических значений из внешних систем (добавлен в **7.0**), альтернатива `zabbix_sender` для интеграций.
* **Monitoring as Code (MaC)** — подход, при котором конфигурация мониторинга хранится в Git и применяется через API конвейером, как обычный код.

## Основные концепции

### Аутентификация

| Способ | Заголовок/поле | Примечание |
|---|---|---|
| API-токен | `Authorization: Bearer <token>` | Рекомендуемый. Создаётся в `Users → API tokens` или в профиле пользователя |
| `user.login` | поле `auth` в теле запроса | Устаревающий способ; токен живёт ограниченное время |
| Без аутентификации | — | Только `apiinfo.version` |

Токен привязан к пользователю и наследует его права (или ограничивается отдельной ролью). Скомпрометированный токен отзывается в интерфейсе.

### Структура запроса

```json
{
  "jsonrpc": "2.0",
  "method": "host.get",
  "params": { "output": ["hostid", "host"], "filter": { "status": 0 } },
  "id": 1
}
```

Аутентификация передаётся заголовком `Authorization: Bearer <token>`. Поле `auth` в теле запроса устарело (deprecated) и удалено начиная с Zabbix 7.2 — не использовать его в примерах для 7.x.

Ответ содержит `result` (данные) либо `error` (код, сообщение, данные). Для больших выборок используются `limit`/`offset`, `search`, `filter`, `sortfield`/`sortorder`, `output`.

### Ключевые группы методов

| Группа | Примеры |
|---|---|
| Хосты | `host.get`, `host.create`, `host.update`, `host.delete` |
| Элементы/триггеры | `item.create`, `itemprototype.create`, `trigger.create` |
| Шаблоны | `template.get`, `template.create`, `configuration.export/import` |
| История/события | `history.get`, `history.push`, `event.get`, `problem.get` |
| Обслуживание | `maintenance.create`, `maintenance.update`, `maintenance.delete` |
| Служебные | `apiinfo.version` (без авторизации) |

### MaC-конвейер

```
Git (шаблоны/хосты в XML/YAML) --CI--> API import --> Zabbix
```

Изменения мониторинга проходят code review, применяются автоматически после merge, откатываются через `git revert`. Это исключает дрейф конфигурации и позволяет восстановить мониторинг за минуты.

## Практические сценарии

### Шаг 1. Проверка версии (без авторизации)

```bash
curl -s -X POST http://zabbix.example.com/api_jsonrpc.php \
  -H 'Content-Type: application/json-rpc' \
  -d '{"jsonrpc":"2.0","method":"apiinfo.version","params":{},"id":1}'
# → {"jsonrpc":"2.0","result":"7.4.0","id":1}
```

### Шаг 2. Получение токена (user.login)

```bash
curl -s -X POST http://zabbix.example.com/api_jsonrpc.php \
  -H 'Content-Type: application/json-rpc' \
  -d '{
        "jsonrpc":"2.0","method":"user.login",
        "params":{"username":"Admin","password":"secret"},
        "id":1
      }'
# → {"jsonrpc":"2.0","result":"<auth-строка>","id":1}
```

Для автоматизации вместо этого создайте **API-токен** в UI и используйте его напрямую.

### Шаг 3. Чтение данных (host.get)

```bash
TOKEN="<api-token>"
curl -s -X POST http://zabbix.example.com/api_jsonrpc.php \
  -H 'Content-Type: application/json-rpc' \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
        "jsonrpc":"2.0","method":"host.get",
        "params":{"output":["hostid","host","status"],
                  "selectInterfaces":["ip"]},
        "id":1
      }'
# → {"result":[{"hostid":"10084","host":"web01","status":"0", ...}]}
```

### Шаг 4. Создание хоста (host.create)

```bash
curl -s -X POST http://zabbix.example.com/api_jsonrpc.php \
  -H 'Content-Type: application/json-rpc' \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
        "jsonrpc":"2.0","method":"host.create",
        "params":{
          "host":"db01",
          "interfaces":[{"type":1,"main":1,"useip":1,
                         "ip":"192.168.1.20","dns":"","port":"10050"}],
          "groups":[{"groupid":"2"}],
          "templates":[{"templateid":"10001"}]
        },
        "id":1
      }'
# → {"result":{"hostids":["10264"]}}
```

### Шаг 5. Экспорт и импорт конфигурации

```bash
# Экспорт шаблона в YAML (в Git)
yaml=$(curl -s -X POST http://zabbix.example.com/api_jsonrpc.php \
  -H 'Content-Type: application/json-rpc' \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"jsonrpc":"2.0","method":"configuration.export",
       "params":{"options":{"templates":["10001"]},"format":"yaml"},
       "id":1}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["result"])')
printf '%s\n' "$yaml" > templates/linux.yaml

# Импорт обратно (например, из CI после merge)
curl -s -X POST http://zabbix.example.com/api_jsonrpc.php \
  -H 'Content-Type: application/json-rpc' \
  -H "Authorization: Bearer $TOKEN" \
  -d "$(python3 - <<'PY'
import json
print(json.dumps({"jsonrpc":"2.0","method":"configuration.import",
  "params":{"format":"yaml","rules":{"templates":{"createMissing":True,
  "updateExisting":True}},"source":open("templates/linux.yaml").read()},"id":1}))
PY
)"
# → {"result":true}
```

### Шаг 6. Отправка значений из внешней системы (history.push, 7.0+)

```bash
curl -s -X POST http://zabbix.example.com/api_jsonrpc.php \
  -H 'Content-Type: application/json-rpc' \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
        "jsonrpc":"2.0","method":"history.push",
        "params":[{"host":"db01","key":"custom.metric","value":"42","clock":1728900000}],
        "id":1
      }'
# → {"result":{"response":"success","processed":1}}
```

### Шаг 7. Автоматизация через Ansible

Готовые модули коллекции `community.zabbix` используют API и покрывают хосты, группы, шаблоны, макросы, действия. Примеры — в [Ansible: модули управления мониторингом](../Ansible/Modules/ansible_monitoring_modules.md).

## Операции и команды

| Задача | Метод |
|---|---|
| Версия API | `apiinfo.version` |
| Логин | `user.login` |
| Список хостов | `host.get` |
| Создание хоста | `host.create` |
| Экспорт конфигурации | `configuration.export` |
| Импорт конфигурации | `configuration.import` |
| Список проблем | `problem.get` |
| Отправка значений | `history.push` |
| Создание окна обслуживания | `maintenance.create` |

```bash
# Разбор ответа в одну строку (jq)
curl -s ... -d '{"jsonrpc":"2.0","method":"host.get","params":{"output":["host"]},"id":1}' \
  -H "Authorization: Bearer $TOKEN" | jq -r '.result[].host'
# → web01
# → db01
```

## Устранение неисправностей

### `{"error":{"code":-32602,"message":"Invalid params"}}`

* Неверные имена полей или отсутствует обязательное (например, `groups` при создании хоста).
* Тип значения не совпадает со схемой метода — сверьтесь с документацией API для вашей версии.

### `Not authorised` / `Session terminated`

* Токен отозван или истёк; `user.login`-строка имеет ограниченное время жизни.
* Заголовок `Authorization` не передан или передан неверно.

### `-32500 Application error` при импорте

* Конфликт версий формата шаблона (шаблон новее сервера) — использовать шаблон под версию инсталляции.
* Нарушена целостность ссылок (шаблон ссылается на отсутствующую группу/элемент).

### Создание дубликатов

* Повторный `host.create` с тем же `host`-именем невозможен; используйте `host.update` или импорт с `createMissing`/`updateExisting`.

### Большие выборки падают по таймауту

* Используйте постранично `limit`/`offset`, сужайте `output` и `filter`, не выбирайте лишние `select*`.

## Лучшие практики

* **API-токены вместо `user.login`** в автоматизации; храните токены в секрет-менеджере (Vault, GitLab CI variables), не в Git.
* **Принцип наименьших прав** — отдельный пользователь/роль для автоматизации с минимальными правами.
* **Экспортируйте конфигурацию в Git** и применяйте через `configuration.import` в CI после review (MaC).
* **Идемпотентность** — используйте `get` → `create`/`update`, а не «создать всё заново».
* **Версионируйте шаблоны** вместе с базой; фиксируйте версию API/Zabbix в пайплайне, чтобы выявить несовместимость формата импорта.
* **Для потоковой передачи внешних данных** (SIEM/SOAR) предпочитайте `history.push` (7.0+) — пример в [интеграции Wazuh и Zabbix](../Security/Tools/Wazuh/zabbix-integration.md).
* **Мониторьте и сам API** — доступность endpoint, ошибки авторизации, лимиты.

## Дополнительная информация

### См. также

* [Ansible: модули управления мониторингом](../Ansible/Modules/ansible_monitoring_modules.md) — `community.zabbix`, развёртывание и регистрация хостов.
* [Интеграция Wazuh и Zabbix](../Security/Tools/Wazuh/zabbix-integration.md) — `history.push` и `zabbix_sender`.
* [Лучшие практики настройки](./zabbix_best_practices.md) — тикет-системы, Media Types, Actions.
* [Аутентификация и права](./zabbix_authentication_and_rbac.md) — токены, роли, пользователи.
* [Источники данных Grafana](../Grafana/grafana_datasources.md) — источник данных Zabbix.
* [Интеграция с Grafana](./zabbix_grafana_integration.md) — app-плагин Zabbix для Grafana и Direct DB Connection.
* [Экспорт и стриминг данных](./zabbix_data_streaming.md) — выгрузка истории/трендов в NDJSON и стриминг во внешние системы.

### Источники

* Zabbix documentation: [API](https://www.zabbix.com/documentation/current/en/manual/api), [API reference](https://www.zabbix.com/documentation/current/en/manual/api/reference), [Configuration export/import](https://www.zabbix.com/documentation/current/en/manual/xml_export_import).

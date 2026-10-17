# consul-template — рендеринг секретов в конфиги

> **Актуально для:** consul-template 0.43.x (документация ветки `main`)

## Определения

**consul-template (CT)** — демон HashiCorp, который опрашивает Consul, Vault и/или Nomad и по их данным рендерит файлы-шаблоны на диске, при необходимости запуская команду-перезагрузку (например, reload nginx).

**Шаблон (`*.ctmpl`)** — файл с функциями Go-шаблонизатора (`{{ secret "kv/data/app" }}`, `{{ key "config/max" }}`), который CT превращает в выходной файл.

**Секрет Vault с lease** — значение с привязанным lease: CT продлевает его и перерисовывает шаблон до истечения; для секретов без lease используется `default_lease_duration`.

**Режимы работы** — `once` (отрисовать один раз и выйти), de-duplication (общая пред-отрисовка шаблонов в Consul KV), `exec` (CT как супервизор приложения).

**Vault Agent Token File** — файл, из которого CT читает токен, выпущенный Vault Agent (режим `sink`/ Auto-Auth); приоритет поля `token`.

## Основные концепции

### Позиция в стеке Vault

CT **не аутентифицируется сам**: в его конфиге нет ни одного auth-метода. Токен обязан предоставить внешний контур — Vault Agent (Auto-Auth + `vault_agent_token_file`), тулчейн CI, systemd-единица с `EnvironmentFile=`, обёртка-скрипт. Это принципиальное отличие от Vault Agent, который умеет логиниться и продлевать токен самостоятельно; функция «шаблонов» самого Vault Agent построена на том же движке шаблонов.

Демон в цикле: прочитать шаблоны → получить данные (блокирующие запросы/long polling к Consul, запросы к Vault) → записать выходной файл → выполнить команду, **если содержимое изменилось** → ждать обновления lease/watch.

### Модель обновления Vault-данных

* Токен продлевается автоматически на половину его lease (`renew_token = true` по умолчанию). Исключение — токен из `vault_agent_token_file`: по умолчанию CT его **не** продлевает, для продления нужно явно `renew_token = true`.
* Секрет в шаблоне (`{{ secret }}`) перечитывается по lease: CT ждёт `lease_renewal_threshold` (по умолчанию 90% lease) и перерисовывает файл заранее до истечения.
* У секрета **нет** lease — применяется `default_lease_duration` (по умолчанию 5 минут): это интервал перепроверки значения.
* `unwrap_token = true` — токен является response-wrapped и раскрывается через cubbyhole перед использованием. **По умолчанию `unwrap_token = false`** — включайте явно, если выдаёте токены завёрнутыми.

### Приоритет источников токена и конфигурации

1. `vault_agent_token_file` — приоритетнее поля `token`; CT периодически проверяет файл (`stat`) и подхватывает новое значение.
2. Поле `token = ""` (не храните токен в конфиге; используйте переменную окружения `VAULT_TOKEN`, `VAULT_NAMESPACE` — для namespace).
3. CLI-флаги имеют приоритет над файлом конфигурации; при нескольких `-config` выигрывает правый, каталоги сливаются в лексическом порядке (симлинки не обходятся).

## Практические сценарии

### Установка и базовый запуск

```bash
# Бинарь: релизы https://releases.hashicorp.com/consul-template/ (актуальный 0.43.0)
consul-template -h   # полный список флагов

# Один шаблон и выход, в режиме one-shot (типичный CI-вариант)
consul-template -template "/tmp/template.ctmpl:/tmp/result" -once
```

В шаблоне:

```hcl
{{- with secret "kv/data/nginx/basic_auth" }}
user: {{ .Data.data.username }}
password: {{ .Data.data.password }}
{{- end }}
```

### Конфигурация демона: nginx из Vault и Consul

```hcl
# /etc/consul-template/config.hcl
log_level = "warn"

vault {
  address             = "https://vault.service.consul:8200"
  vault_agent_token_file = "/run/vault/agent/token"  # приоритет над token
  renew_token         = true        # продлевать токен из файла явно
  default_lease_duration = "5m"     # интервал перепроверки секретов без lease
  lease_renewal_threshold = 0.90    # перерисовка за 90% до конца lease
  unwrap_token        = true        # токен приходит response-wrapped
}

template {
  source             = "/etc/consul-template/nginx.ctmpl"
  destination        = "/etc/nginx/nginx.conf"
  error_on_missing_key = true       # рекомендуется для Vault: ошибка вместо <no value>
  perms              = 0600         # у нового файла; существующий наследует свои права
  exec {
    command = ["nginx", "-s", "reload"]
    timeout = "30s"                 # команда должна успеть и вернуть 0
  }
}

template {
  contents  = "{{ keyOrDefault \"service/redis/maxconns\" \"5\" }}"
  destination = "/etc/redis/maxconns.conf"
}
```

Запуск и перезагрузка без рестарта:

```bash
consul-template -config "/etc/consul-template/config.hcl"
kill -HUP "$(cat /run/consul-template.pid)"   # reload_signal = SIGHUP (по умолчанию)
```

`SIGHUP` перечитывает и конфигурацию, и шаблоны; `kill_signal` по умолчанию `SIGINT` (graceful stop).

### CLI-варианты

```bash
# Несколько шаблонов, команда запускается при каждом изменении
consul-template \
  -template "/tmp/nginx.ctmpl:/var/nginx/nginx.conf:nginx -s reload" \
  -template "/tmp/redis.ctmpl:/var/redis/redis.conf:service redis restart" \
  -template "/tmp/haproxy.ctmpl:/var/haproxy/haproxy.conf"

# Собственные адреса backends
consul-template -consul-addr "10.4.4.6:8500" -vault-addr "https://10.5.32.5:8200"

# Режим супервизора: отрисовать и мониторить дочерний процесс
consul-template -template "/tmp/in.ctmpl:/tmp/result" -exec "/sbin/my-server"
```

Синтаксис `-template`: `источник:назначение[:команда]`.

### Режимы

```hcl
once = true                        # то же, что флаг -once

deduplicate {
  enabled = true                   # общая пред-отрисовка в Consul KV
  prefix  = "consul-template/dedup/"
}

exec {
  command = ["/usr/bin/app"]       # один процесс-команда на весь CT
}
```

В exec-режиме сигналы приходят дочернему процессу напрямую, а строка `command = "exec /usr/sbin/nginx -c /etc/nginx/nginx.conf"` передаёт управление (exec) приложению.

### Docker-образ

Образ `hashicorp/consul-template`: пользователь `consul-template` имеет UID 100 и GID 1000 — учитывайте это для прав на `/consul-template/config` и `/consul-template/data`, если образ — родительский для своего.

## Справочник параметров

### Глобальные

| Параметр | По умолчанию | Назначение |
| :--- | :--- | :--- |
| `reload_signal` | `"SIGHUP"` | Сигнал перезагрузки конфига и шаблонов; пустая строка — не слушать |
| `kill_signal` | `"SIGINT"` | Сигнал graceful stop |
| `log_level` | `"warn"` | `trace`, `debug`, `info`, `warn`, `err` |
| `template_error_fatal` | `true` | Ошибка шаблона завершает процесс (переопределяется в блоке `template`) |
| `err_on_failed_lookup` | `true` | Выход с ошибкой, если значение поля не найдено (retry-логика сюда не применяется) |
| `max_stale` | `"10m"` | Допустимая «устаревшесть» данных Consul при ответе с follower |
| `block_query_wait` | `"60s"` | Длительность blocking query |
| `wait` (quiescence) | `min 5s / max 10s` | Антифлаппинг: ждать стабильности кластера перед рендером |
| `pid_file`, `syslog`, `log_file` | выключены | PID-файл; syslog; файловый лог с ротацией (`log_rotate_bytes`, `log_rotate_duration`, `log_rotate_max_files`) |

### Блок `vault`

| Параметр | По умолчанию | Назначение |
| :--- | :--- | :--- |
| `address` | — | Адрес Vault-лидера, обязателен протокол `http(s)://` |
| `namespace` | `""` | Namespace Vault Enterprise; также задаётся через `VAULT_NAMESPACE` |
| `token` | `""` | Токен Vault; лучше `VAULT_TOKEN`, не хранить в конфиге. **CT не умеет создавать токены через auth-методы** |
| `vault_agent_token_file` | выкл. | Читать токен из файла (приоритет над `token`); без `renew_token = true` продление выключено |
| `unwrap_token` | `false` | Раскрывать response-wrapped токен (cubbyhole) |
| `default_lease_duration` | `5m` | Переиспользуемый интервал перепроверки для секретов без lease |
| `lease_renewal_threshold` | `0.90` | Доля lease, после которой секрет перечитывается |
| `renew_token` | `true` | Продлевать токен (на половину lease). Секреты в шаблонах продлеваются всегда, независимо от флага |
| `retry` | — | Повторы подключения (экспоненциальная пауза; по умолчанию до 5 попыток для Vault) |
| `ssl` | — | TLS: `ca_cert`, `ca_path`, `cert`, `verify` (как в блоке Consul) |

### Блок `template`

| Параметр | По умолчанию | Назначение |
| :--- | :--- | :--- |
| `source` / `contents` | — | Путь к шаблону либо текст шаблона; взаимоисключающи |
| `destination` | — | Выходной файл |
| `create_dest_dirs` | `true` | Создавать родительские каталоги |
| `error_on_missing_key` | `false` | Ошибка вместо вывода `<no value>`; **для Vault рекомендуется `true`** |
| `error_fatal` | `true` | Завершить CT при ошибке шаблона (переопределяет глобальный `template_error_fatal`) |
| `perms` | наследуются существующего файла, иначе `0644` | Права нового файла (в примерах для секретов — `0600`) |
| `user` / `group` | текущий пользователь CT | Владелец файла (на Windows не поддерживается) |
| `backup` | `false` | Хранить одну резервную копию перед перезаписью |
| `wait { min, max }` | не задано | Минимальная/максимальная пауза перед рендером; без `max` — 4×`min` |
| `left_delimiter` / `right_delimiter` | `{{` / `}}` | Изменить разделители при конфликте с синтаксисом выходного файла |
| `function_denylist` | `[]` | Запрещённые функции шаблонизатора (ошибка при вызове) |
| `sandbox_path` | `""` | Ограничить функцию `file` указанным каталогом |
| `exec { command, timeout }` | `timeout 30s` | Команда после рендеринга; выполняется только при изменении содержимого |
| `command` / `command_timeout` | `60s` | Устаревший (back-compat) синтаксис команды |

Команда должна завершиться с кодом 0 и уложиться в таймаут — иначе CT считает рендер неудачным (при `error_fatal` процесс завершится).

## Устранение неполадок

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| Выход с ошибкой `permission denied` при старте/записи | Каталог назначения недоступен пользователю CT (в Docker — UID 100/GID 1000) | Выправить права на `destination` и родительские каталоги или задать `perms`/`user` |
| В файле `<no value>` вместо секрета | Нет ключа в ответе, `error_on_missing_key = false` (по умолчанию) | `error_on_missing_key = true` и исправить путь к секрету |
| CT завершился сразу после ошибки шаблона | `error_fatal = true` / глобальный `template_error_fatal = true` | Для «живого» демона оставить true и чинить шаблон; для постепенного внедрения — временно `false` |
| `failed to renew the Vault token` / токен протух | Токен из `vault_agent_token_file` без `renew_token = true`, либо агент не продлевает sink | Включить `renew_token = true` или настроить Auto-Auth у Vault Agent |
| Токен не подхватывается после ротации | Используется поле `token` вместо файла | Перейти на `vault_agent_token_file` — CT сам перечитывает файл |
| Постоянные повторы подключения к Vault | Недоступен адрес/некорректен TLS | Проверить `address`, блок `ssl`; retry-логика работает с экспоненциальной паузой |
| Файл перерисовывается слишком редко/часто | Секрет без lease + неверный `default_lease_duration` либо порог `lease_renewal_threshold` | Выставить `default_lease_duration` под ожидаемую волатильность, оставить порог ~0.90 |
| Изменения конфига не подхватываются | Ожидание перезапуска вместо `SIGHUP` | `kill -HUP <pid>`; пустой `reload_signal` отключает слушателя |
| Конфигурация «не видит» часть настроек | Загружено несколько `-config`, выигрывает правый файл | Упорядочить файлы или объединить в один каталог (слияние в лексическом порядке) |

## Лучшие практики

* Поставить `error_on_missing_key = true` для любых шаблонов с Vault-секретами: ошибка лучше тихо отрендеренного пустого значения в проде.
* Токены не в конфиге: `VAULT_TOKEN` из окружения или `vault_agent_token_file`; для повышенной секретности — response wrapping (`unwrap_token = true`).
* Права `0600` на файлы с секретами и `user`/`group` под сервис, который их читает; отдельно проверять права каталога.
* Ограничить шаблон единственной командой reload и задать ей `timeout`; команды вида `service x restart || true` маскируют отказы — осознанное исключение.
* Для кластера с флейпом использовать quiescence `wait { min, max }`, чтобы не перезагружать nginx на каждом watch-событии.
* Относиться к CT как к «глазам» тулчейна, а не к источнику токенов: логин и продление — зона Vault Agent/CI.
* Обновляться вместе с бэкендами: шаблоны опираются на API Consul/Vault/Nomad, поэтому версию CT держать в одном релизном окне с ними.

## Дополнительная информация

* [Vault Agent — базовые сценарии](./vault_agent/basics.md) — источник токена (Auto-Auth, token sinks) и встроенная функция шаблонов
* [Интеграция с Terraform](./terraform-integration.md) — кодирование политик и секретов
* [Интеграция с Nomad](./nomad-integration.md) — сценарий «секреты в task» через template-блоки Nomad
* [Consul-бэкенд Vault](./vault_with_consul_backend.md) — сама storage-подсистема на Consul
* GitLab CI-сценарий рендеринга: [consul-template-in-gitlab-ci-deploy](../../CI-CD/GitLab_CI/Tutorials/consul-template-in-gitlab-ci-deploy.md)

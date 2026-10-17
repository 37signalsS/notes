# Обслуживание кластера Vault

> **Актуально для:** Vault 2.x (latest 2.1.2; ветка 1.21.x поддерживается)

## Определения

**Active node (лидер)** — единственный узел кластера, обрабатывающий write-запросы и выполняющий фоновые задачи (renew, revocation). Выбирается через HA-lock в storage backend.

**Standby node** — узел, ожидающий активации; проксирует запросы на active (request forwarding) либо, в режиме performance standby (Enterprise), обслуживает часть чтений локально.

**Step-down** — управляемое принудительное сложение активности с текущего лидера (`vault operator step-down`), чтобы другой узел взял на себя роль active.

**Rolling upgrade (покатный апгрейд)** — обновление кластера узел за узлом: сначала все standby, затем active, с unseal и проверкой каждого узла.

**Autopilot** — подсистема integrated storage (Raft), управляющая членством и здоровьем узлов; включает automated upgrade (Vault 1.11+).

**Health endpoint (`/sys/health`)** — коды HTTP, по которым LB и мониторинг определяют состояние узла: 200 active, 429 standby, 472 DR secondary, 473 performance standby, 474 standby без связи с active, 501 не инициализирован, 503 sealed, 530 удалён из кластера.

## Основные концепции

### Step-down: поведение и последствия

`vault operator step-down` (API `POST /sys/step-down`) заставляет активный узел отдать лидерство:

* Вызов с неактивного узла **пересылается на active** — команду можно давать на любой узел.
* Ушедший лидер **спит 10 секунд** перед повторной попыткой взять lock; если за это время лидом не стал другой узел, тот же узел может снова стать active.
* Пока новый лидер не выбрался, **кластер остаётся без active-узла**: forwarding запросов к лидеру в этот период падает. Длительность — секунды, но на ней возможны ошибки у клиентов.
* Требуется токен с policy `root` либо capability `update` и `sudo` на пути `sys/step-down`:

```hcl
path "sys/step-down" {
  capabilities = ["update", "sudo"]
}
```

```bash
vault operator step-down
# → Success! Stepped down: http://127.0.0.1:8200
```

**Категорически нельзя** делать step-down во время покатного апгрейда — официальная процедура апгрейда прямо это запрещает (см. ниже).

### Кто обрабатывает запросы: `/sys/health`

| Код | Состояние |
| :--- | :--- |
| 200 | initialized, unsealed, active |
| 429 | unsealed standby (не обрабатывает запросы сам) |
| 472 | DR secondary |
| 473 | performance standby |
| 474 | standby, нет связи с active |
| 501 | не инициализирован |
| 503 | sealed |
| 530 | удалён из HA-кластера |

Параметры `standbyok=true`/`perfstandbyok=true` возвращают 200-level ответ для standby (удобно за LB, которые не умеют работать с 429); параметры `activecode`, `standbycode`, `sealedcode` и др. позволяют переопределить сами коды.

### Покатный апгрейд: официальная процедура (HA)

Предпосылки: Vault **не гарантирует zero-downtime апгрейд** — при правильной процедуре простоя секунды (единицы сотен мс — 1 с в зависимости от storage). **Никогда не откатывайтесь фейlover'ом со старой версии на новую** (newer → older запрещено).

Подготовка:

1. Изучить change tracker и release notes целевой версии, учесть breaking changes.
2. `sudo` на серверах Vault, admin-доступ, заранее оповестить держателей unseal-шард.
3. **Бэкап**: snapshot данных (Vault не даёт backward-гарантий по data store) и конфигурации.
4. Тест: snapshot → изолированная тестовая инстанция → апгрейд → проверка данных и критичных workflow.

Процедура по узлам:

1. **Каждый standby:** корректно остановить через `SIGINT`/`SIGTERM` → заменить бинарь (восстановить capability `mlock` через `setcap`) → запустить → unseal → `vault status`: версия верна, `HA Mode = standby` → проверить логи.
2. Когда все standby обновлены — апгрейд завершится только после того, как обновлённый standby займёт active.
3. **Active-узел:** остановить `SIGINT`/`SIGTERM` → заменить бинарь → запустить → unseal → `vault status` → логи. Внутренние upgrade-задачи выполнит новый active.

Важно:

* Останавливать только штатными сигналами: SIGKILL не отпускает HA-lock, и standby не сможет взять лидерство до истечения lock timeout (backend-зависимо, порядка 10 с и более).
* **Step-down во время апгрейда запрещён** (warning в официальной процедуре).
* Если кластер на Vault 1.11+ с integrated storage и вы не хотите включать automated upgrades — отключите автоматическую миграцию Autopilot, иначе возможна потеря кворума (Lost Quorum при апгрейде с 1.11.0).

### Autopilot automated upgrade

Для integrated storage (Vault 1.11+) автономно проще управлять апгрейдами через Autopilot: узлы обновляются автоматически по заданным правилам здоровья узлов, без ручной последовательности standby→active. Ручная процедура выше нужна для Consul-storage и старых версий, либо при opted-out из automated upgrade.

## Практические сценарии

### Плановое обслуживание (например, замена TLS-сертификата на узле)

```bash
# На узле, который обслуживаем (standby — предпочтительнее):
vault status
# → Sealed: false, HA Mode: standby
# Остановить (SIGTERM/ systemctl stop vault), заменить сертификат, запустить, unseal
vault status
# → Version верна, HA Mode: standby
```

Если обслуживается active и перезапуск нежелателен — `vault operator step-down` с разрешённого токена, дождаться нового лидера (`vault status` / `vault operator raft list-peers`), затем обслуживать узел уже как standby.

### Апгрейд кластера на Raft (3 узла)

```bash
# 0. Бэкап
vault operator raft snapshot save /var/backup/vault-$(date +%F).snap

# 1-3. Каждый standby: SIGTERM → бинарь → старт → unseal → проверка
vault status
# → Version: <новая>, HA Mode: standby

# 4. Active: SIGTERM → бинарь → старт → unseal
vault status
# → HA Mode: active (после того, как новый active поднялся)
vault operator raft list-peers
# → 3 узла, версии бинарей совпадают
```

### Проверка здоровья после вмешательства

```bash
curl -s http://vault-1:8200/v1/sys/health | jq .   # 200 = active
vault status                                        # Sealed: false
vault operator raft list-peers                      # кворум 3/3
vault audit list                                    # подключённые audit devices
```

### Откат апгрейда

Откат — только вперёд-назад через бэкап: остановить кластер, восстановить snapshot **предыдущей** версии на изолированной инстанции, проверить, затем переключать. Фейlover на старый бинарь при новой версии данных запрещён. Подробности — [восстановление из бэкапа](./backup_restore_strategies.md) и документация по rollback.

## Устранение неполадок

| Симптом | Причина | Действия |
| :--- | :--- | :--- |
| После step-down падают запросы | Кластер временно без active | Подождать избрания лидера (секунды), проверить `vault status` на всех узлах |
| После step-down снова активировался тот же узел | За 10 с никто не взял lock | Проверить остальные узлы (sealed? мертвы?), HA-lock storage |
| Standby не берёт лидерство после kill | HA-lock не отпущен (SIGKILL) | Ждать lock timeout (≈10 с и более) либо восстановить узел |
| Код 474 от standby | Нет связи с active | Сеть/active мёртв; смотреть логи и `sys/leader` |
| `permission denied` на step-down | Нет `update`+`sudo` на `sys/step-down` | Break-glass политика |
| При апгрейде Lost Quorum | Autopilot automated migration + opted-out конфиг | Отключить автоматическую миграцию Autopilot (см. официальную инструкцию) |
| `vault status` показывает новую версию, но кластер странно работает | Несовпадение версий бинарей между узлами | Довести все узлы до целевой версии по процедуре |

## Лучшие практики

* Апгрейды: снапшот → тест изолированной копией → standby → active; без step-down, без failback на старую версию.
* Остановка узла всегда `SIGINT`/`SIGTERM` — иначе пауза на lock timeout.
* Step-down — только как штатный инструмент перед обслуживанием активного узла, с готовым запасным узлом; не во время апгрейда.
* `/sys/health` настраивать под LB: либо `standbyok=true`, либо принимать 429 как healthy-standby; 474 мониторить отдельно.
* Держатели unseal-шард оповещаются заранее — без них каждый restart узла превращается в инцидент.
* Для Raft: кворум 3/5, автоподозор Autopilot включён, регулярные raft snapshot (см. [бэкап](./backup_restore_strategies.md)).

## Дополнительная информация

* [Восстановление из бэкапа](./backup_restore_strategies.md) — snapshot save/restore, откат
* [Инциденты и реагирование](./incident-response.md) — массовые отзывы, компрометация
* [Мониторинг и алертинг](./monitoring_and_alerting.md) — метрики leader/standby, health
* [Конфигурация Vault с Consul backend](./vault_with_consul_backend.md) — HA на Consul storage
* [Основные концепции](../concepts.md) — HA, unseal, audit

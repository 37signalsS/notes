# Обновление систем Proxmox

## Определения

**Proxmox Virtual Environment (PVE)** — платформа виртуализации с открытым исходным кодом на базе Debian. Актуальная ветка — **9.x** (на базе Debian 13 «Trixie»).

**Proxmox Backup Server (PBS)** — специализированное решение для инкрементального резервного копирования.

**In-place Upgrade (Обновление на месте)** — процесс мажорного обновления ОС без переустановки, путем смены репозиториев в `apt` и выполнения полной модернизации. Формального пути отката не существует — единственной защитой являются протестированные резервные копии.

**deb822 (.sources)** — многострочный формат описания apt-репозиториев, введенный в PVE 9 (Debian 13). Пришел на смену однострочному формату `deb <uri> <suite> <component>` в файлах `.list`, который использовался в PVE 8 и ранее.

**pve8to9** — встроенный в PVE 8.4+ чеклист проверки готовности к мажорному обновлению. Только читает конфигурацию и отчитывается, автоматически ничего не чинит.

**Maintenance Mode (Режим обслуживания)** — режим узла кластера PVE, при котором все HA-сервисы с него мигрируют, а новые на нем не запускаются. Используется при плановых работах, в том числе при обновлении.

## Основные концепции

### Типы репозиториев

1. **Enterprise Repository**: Платный, максимально стабильный. Требует активной подписки. Без валидной подписки `apt update` завершается ошибкой `401 Unauthorized`. В PVE 9 — файл `/etc/apt/sources.list.d/pve-enterprise.sources`.
2. **No-Subscription Repository**: Рекомендуемый для домашних/тестовых лабораторий. Содержит те же пакеты, что и Enterprise, но с меньшим циклом тестирования. Не рекомендуется для продакшена. В PVE 9 — файл `/etc/apt/sources.list.d/proxmox.sources`.
3. **Test Repository**: Самые свежие пакеты для разработчиков. Не для продакшена.

**Форматы файлов репозиториев по версиям:**
- **PVE 9 (Debian 13 «Trixie»)**: формат deb822 `.sources`. Ключ подписи — `/usr/share/keyrings/proxmox-archive-keyring.gpg`.
- **PVE 8 (Debian 12 «Bookworm»)**: классический формат `.list`, кодовое имя `bookworm`. Ключ — `/etc/apt/trusted.gpg.d/proxmox-release-bookworm.gpg`. Поддержка PVE 8.4 — до августа 2026.
- **PVE 7 (Debian 11 «Bullseye»)**: классический формат `.list`, кодовое имя `bullseye`. Ветка EOL, репозитории сохранены только для миграции.

### Плановое (точечное) обновление

В рамках одной мажорной версии достаточно штатного обновления пакетов:

```bash
apt update && apt dist-upgrade
```

Рекомендуется включить **No-Subscription** или иметь активную подписку, иначе обновление будет недоступно. Обновления внутри ветки (например, 9.1 → 9.2) выполняются тем же способом — никакой специальной процедуры не требуется.

### Безопасное обновление (Best Practices)

- **Терминальный мультиплексор**: При мажорном обновлении используйте SSH + `tmux` или `screen`. Веб-консоль GUI (включая noVNC-терминал) закроется при перезапуске `pveproxy`.
- **Внеполосный доступ**: Убедитесь, что для каждого узла доступен IPMI/iKVM/iDRAC или физическая консоль. Обновление ядра или сетевая проблема могут отключить удаленный доступ.
- **Резервные копии**: Обязательно создайте протестированные бэкапы всех VM и LXC (`vzdump` или PBS). Отката у In-place upgrade нет — бэкап это единственный способ восстановления.
- **Свободное место**: Минимум 5 ГБ на корневом разделе (`/`), рекомендуется 10+ ГБ (при сохранении старых ядер требуется больше).
- **Явная привязка имен интерфейсов**: При переходе на новое ядро имена сетевых интерфейсов могут измениться (`enp*`/`ens*`). Проверьте `vmbr0` и физические интерфейсы, при необходимости зафиксируйте их через udev-правила или systemd `.link`-файлы до обновления.
- **Последовательность в кластере**:
  1. Обновляйте строго по одному узлу за раз, сохраняя кворум.
  2. Миграция ВМ с обновляемого узла.
  3. Перевод узла в Maintenance Mode.
  4. Обновление пакетов.
  5. Перезагрузка.
  6. Проверка, что узел вернулся в кластер, и только затем переход к следующему.
- **Команды**: Всегда используйте `apt dist-upgrade` или `apt full-upgrade`. Обычный `apt upgrade` запрещен, так как он не умеет корректно обрабатывать зависимости ядра.

## Практические сценарии

### Настройка No-Subscription через CLI (PVE 9, формат deb822)

1. Отключение Enterprise (файл останется, но apt его пропустит):
   ```bash
   echo 'Enabled: false' >> /etc/apt/sources.list.d/pve-enterprise.sources
   ```

2. Создание No-Subscription репозитория:
   ```bash
   cat > /etc/apt/sources.list.d/proxmox.sources << 'EOF'
   Types: deb
   URIs: http://download.proxmox.com/debian/pve
   Suites: trixie
   Components: pve-no-subscription
   Signed-By: /usr/share/keyrings/proxmox-archive-keyring.gpg
   EOF
   ```

3. Для гиперконвергентного кластера отдельно настраивается репозиторий Ceph (`ceph.sources`):
   ```bash
   cat > /etc/apt/sources.list.d/ceph.sources << 'EOF'
   Types: deb
   URIs: http://download.proxmox.com/debian/ceph-squid
   Suites: trixie
   Components: no-subscription
   Signed-By: /usr/share/keyrings/proxmox-archive-keyring.gpg
   EOF
   ```

   > Путь `ceph-squid` соответствует версии Ceph кластера. В свежих установках PVE 9.2 по умолчанию предлагается Ceph Tentacle — тогда путь будет `ceph-tentacle`. Сверяйтесь с версией, указанной в существующем файле.

4. Обновление списков пакетов:
   ```bash
   apt update
   ```

### Настройка No-Subscription в PVE 8 (справочно)

PVE 8 и более ранние версии использовали однострочный формат `.list`:

```bash
sed -i 's/^deb/#deb/g' /etc/apt/sources.list.d/pve-enterprise.list
echo "deb http://download.proxmox.com/debian/pve bookworm pve-no-subscription" \
  > /etc/apt/sources.list.d/pve-install-repo.list
apt update
```

### Мажорное обновление PVE 8.x → 9.x (актуальная процедура)

> **Внимание**: поддержка PVE 8.x завершается в августе 2026. Обновление до 9.x необратимо, поэтому перед началом обязательны тестированные бэкапы.

1. **Обновление до последней PVE 8.4** (на каждом узле):
   ```bash
   apt update && apt dist-upgrade
   ```
   Требуется версия **8.4.1 или новее** — именно в ней появляется инструмент проверки `pve8to9`.

2. **Проверка версии и готовности** (на каждом узле кластера перед обновлением первого):
   ```bash
   pveversion
   pve8to9 --full
   # → System health check passed: OK
   ```
   `pve8to9 --full` — read-only диагностика: проверяет репозитории, хранилища, кластер, сторонние пакеты и известные аппаратные проблемы. Красные пункты (FAIL) должны быть устранены, желтые (WARN) — изучены. Прогоняйте чеклист повторно после исправлений, а затем после обновления.

3. **Ceph (только для гиперконвергентных кластеров)**: Ceph должен быть уже на версии **19.x Squid** до обновления PVE — PVE 9 не работает с Ceph 17/18. Процедура описана в разделе ниже.

4. **Подготовка терминала**:
   ```bash
   tmux new-session -s upgrade
   # или
   screen -S upgrade
   ```

5. **Миграция репозиториев с Bookworm на Trixie**:
   ```bash
   sed -i 's/bookworm/trixie/g' /etc/apt/sources.list
   sed -i 's/bookworm/trixie/g' /etc/apt/sources.list.d/pve-enterprise.list 2>/dev/null
   ```

6. **Добавление репозиториев PVE 9 в формате deb822** (замените `pve-no-subscription` на `pve-enterprise` при наличии подписки):
   ```bash
   cat > /etc/apt/sources.list.d/proxmox.sources << 'EOF'
   Types: deb
   URIs: http://download.proxmox.com/debian/pve
   Suites: trixie
   Components: pve-no-subscription
   Signed-By: /usr/share/keyrings/proxmox-archive-keyring.gpg
   EOF
   ```

7. **Удаление устаревших файлов `.list`** и проверка:
   ```bash
   rm -f /etc/apt/sources.list.d/pve-install-repo.list
   apt update
   apt policy
   ```

8. **Запуск обновления**:
   ```bash
   apt dist-upgrade
   # → Calculating upgrade... Done
   # → ... пакетов будет обновлено ...
   ```
   Внимательно отвечайте на вопросы о конфигурационных файлах: для `/etc/lvm/lvm.conf` рекомендована версия сопровождающих (maintainer), для измененных вами файлов — сверяйте diff.

9. **После обновления (UEFI-системы)**: при загрузке UEFI+LVM установите пакет `grub-efi-amd64` — известная проблема: без него следующий запуск не загрузится:
   ```bash
   apt install grub-efi-amd64
   systemctl restart pve-manager
   ```

10. **Повторный чеклист и перезагрузка**:
    ```bash
    pve8to9 --full
    # → System health check passed: OK
    reboot
    ```

11. **Проверка после обновления** (см. раздел «Диагностика и проверка»).

> **Совет**: после успешного обновления устаревшие файлы `.list` можно перевести в формат deb822 автоматически:
> ```bash
> apt modernize-sources
> ```
> Резервные копии сохраняются с суффиксом `.bak` вне каталога `/etc/apt/sources.list.d/` (файлы с расширением `.bak` внутри него вызывают ошибки в веб-интерфейсе).

### Предыдущее мажорное обновление PVE 7.4 → 8.x (справочно)

> Ветка PVE 7 достигла EOL. Процедура приведена как историческая справка для миграции устаревших инсталляций.

1. **Диагностика**:
   ```bash
   pve7to8 --full
   # → System health check passed: OK
   ```

2. **Обновление репозиториев** (Bullseye → Bookworm):
   ```bash
   sed -i 's/bullseye/bookworm/g' /etc/apt/sources.list
   sed -i 's/bullseye/bookworm/g' /etc/apt/sources.list.d/*.list
   ```

3. **Запуск обновления**:
   ```bash
   apt update && apt full-upgrade
   # → Calculating upgrade... Done
   # → ... пакетов будет обновлено ...
   ```

### Обновление кластера с Ceph (гиперконвергентный кластер)

Порядок обновления гиперконвергентного кластера строго фиксирован: **сначала Ceph, затем Proxmox**:

> Ceph 17/18 (Quincy/Reef) → **Ceph 19 Squid** → переход PVE 8 → 9 → после PVE 9.1+ → **Ceph 20 Tentacle**.

PVE 9 не может работать с Ceph 17/18 — при попытке обновления узла с устаревшим Ceph кластер останется неработоспособным до исправления с консоли.

**Обновление Ceph Reef → Squid (выполняется на PVE 8):**

1. Проверка состояния кластера (должен быть `HEALTH_OK`):
   ```bash
   ceph -s
   ceph versions
   ```

2. Смена репозитория Ceph на каждом узле:
   ```bash
   sed -i 's/reef/squid/' /etc/apt/sources.list.d/ceph.list
   ```
   Для no-subscription репозитория строка примет вид:
   ```
   deb http://download.proxmox.com/debian/ceph-squid bookworm no-subscription
   ```

3. Установка флагов (с любой ноды) для предотвращения перестроения данных (rebalance) при перезагрузках:
   ```bash
   ceph osd set noout
   ceph osd set noscrub
   ceph osd set nodeep-scrub
   ceph osd set nobackfill
   ceph osd set norecover
   # → set noout
   ```

4. Обновление пакетов Ceph на каждом узле по очереди с перезапуском демонов OSD:
   ```bash
   apt update && apt dist-upgrade
   systemctl restart ceph-osd@*.service
   ```

5. После обновления всех нод снимите флаги и проверьте состояние:
   ```bash
   ceph osd unset noout
   ceph osd unset noscrub
   ceph osd unset nodeep-scrub
   ceph osd unset nobackfill
   ceph osd unset norecover
   ceph -s
   # → health: HEALTH_OK
   ```

**Далее — обновление PVE 8 → 9 по процедуре выше, строго по одному узлу.** После PVE 9.1+ аналогичным образом выполняется переход Ceph Squid → Tentacle (смена `ceph.sources` на `ceph-tentacle`).

**Стратегия обновления многопоточного кластера:**

- Обновляйте узлы **строго по одному**: `Узел 1 → Upgrade → Reboot → Verify → Узел 2 → ...`
- Перед обновлением узла: миграция VM/LXC, перевод в Maintenance Mode.
- В смешанном кластере PVE 8/9 на время окна обновления **Live Migration не поддерживается** — только холодная миграция.
- HA-группы автоматически конвертируются в новый формат HA Rules.
- После обновления всех узлов проверьте кворум: `pvecm status`.

## Диагностика и проверка

### Проверка версий после обновления

```bash
pveversion -v
# → proxmox-ve: 9.2-1 (running kernel: 7.0-1-pve)
# → pve-manager: 9.2.2 (running version: 9.2.2/e328e3b555091993)
```

Пример вывода актуален для PVE 9.2 (Debian 13 «Trixie», ядро 7.0).

### Проверка состояния сервисов

```bash
systemctl status pve-cluster pvedaemon pveproxy
# → ● pveproxy.service - PVE API Proxy Server
# →    Active: active (running) since ...

systemctl --failed
# → 0 loaded units listed.
```

### Проверка веб-интерфейса, кластера и гостей

```bash
curl -k https://localhost:8006
pvecm status
# → Quorum: 3/3
ceph -s                              # при наличии Ceph
qm list
pct list
```

Убедитесь, что запланированные бэкапы и задачи репликации выполняются, а HA-ресурсы перешли в штатное состояние.

### Частые проблемы и их устранение

- **`401 Unauthorized` при `apt update`** — включен Enterprise-репозиторий без активной подписки. Отключите его (см. настройку No-Subscription) или обновите токен подписки:
  ```bash
  pvesubscription update --force
  ```
- **Отсутствие сети после перезагрузки** — изменились имена сетевых интерфейсов из-за нового ядра. Заранее зафиксируйте привязку имен интерфейсов (см. Best Practices).
- **Незагружаемая система после обновления (UEFI)** — не установлен `grub-efi-amd64` (шаг 9 процедуры). Восстановление — см. раздел Recover From Grub Failure официальной документации.
- **Не обновился отдельный PBS** — совмещенный Proxmox Backup Server обновляется отдельно от PVE (через `pbs3to4 --full` и смену его репозиториев на Trixie).

## Дополнительная информация

### Связанные темы

- [Proxmox VE — Обзор и базовые концепции](./proxmox_overview.md)
- [Кластеризация и High Availability в Proxmox](./proxmox_cluster.md)
- [Proxmox Backup Server (PBS)](./proxmox_backup_server.md)

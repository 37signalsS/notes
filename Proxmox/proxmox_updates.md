# Обновление систем Proxmox

## Определения

**Proxmox Virtual Environment (PVE)** — платформа виртуализации с открытым исходным кодом на базе Debian. Актуальная ветка — **9.x** (на базе Debian 13 «Trixie»).

**Proxmox Backup Server (PBS)** — специализированное решение для инкрементального резервного копирования.

**In-place Upgrade (Обновление на месте)** — процесс мажорного обновления ОС без переустановки, путем смены репозиториев в `apt` и выполнения полной модернизации. Формального пути отката не существует — единственной защитой являются протестированные резервные копии.

**deb822 (.sources)** — многострочный формат описания apt-репозиториев, введенный в PVE 9 (Debian 13). Пришел на смену однострочному формату `deb <uri> <suite> <component>` в файлах `.list`, который использовался в PVE 8 и ранее.

**pve8to9** — встроенный в PVE 8.4+ чеклист проверки готовности к мажорному обновлению. Только читает конфигурацию и отчитывается, автоматически ничего не чинит.

**Maintenance Mode (Режим обслуживания)** — режим узла кластера PVE, при котором все HA-сервисы с него мигрируют, а новые на нем не запускаются. Используется при плановых работах, в том числе при обновлении.

**Rollback (Откат)** — процесс возврата системы к предыдущему рабочему состоянию. In-place upgrade не имеет формального пути отката через `apt`; единственный механизм — восстановление из резервной копии (vzdump/PBS) или из snapshot'а хранилища (ZFS snapshot, LVM snapshot, Ceph RBD snapshot), созданного *до* начала обновления.

**EOL (End of Life)** — дата прекращения поддержки версии. После EOL репозитории закрываются, обновления безопасности не выпускаются. Важно планировать обновление до наступления EOL.

**HWE (Hardware Enablement)** — набор обновленных драйверов ядра и X.org, переносимый из более свежих версий Debian. В контексте PVE актуален при обновлении на новое железо без переустановки ОС.

**APT Pinning** — механизм управления приоритетом пакетов из разных репозиториев через `/etc/apt/preferences.d/`. Позволяет зафиксировать версию конкретного пакета или запретить установку из тестового репозитория.

## Основные концепции

### Типы репозиториев

1. **Enterprise Repository**: Платный, максимально стабильный. Требует активной подписки. Без валидной подписки `apt update` завершается ошибкой `401 Unauthorized`. В PVE 9 — файл `/etc/apt/sources.list.d/pve-enterprise.sources`.
2. **No-Subscription Repository**: Рекомендуемый для домашних/тестовых лабораторий. Содержит те же пакеты, что и Enterprise, но с меньшим циклом тестирования. Не рекомендуется для продакшена. В PVE 9 — файл `/etc/apt/sources.list.d/proxmox.sources`.
3. **Test Repository**: Самые свежие пакеты для разработчиков. Не для продакшена.

**Форматы файлов репозиториев по версиям:**
- **PVE 9 (Debian 13 «Trixie»)**: формат deb822 `.sources`. Ключ подписи — `/usr/share/keyrings/proxmox-archive-keyring.gpg`.
- **PVE 8 (Debian 12 «Bookworm»)**: классический формат `.list`, кодовое имя `bookworm`. Ключ — `/etc/apt/trusted.gpg.d/proxmox-release-bookworm.gpg`. **Поддержка завершена** (EOL).
- **PVE 7 (Debian 11 «Bullseye»)**: классический формат `.list`, кодовое имя `bullseye`. Ветка EOL, репозитории сохранены только для миграции.

### Жизненный цикл версий и даты EOL

| Версия PVE | База Debian | Дата выпуска | EOL | Kernel |
|------------|-------------|--------------|-----|--------|
| 9.x | Trixie (13) | Авг 2025 | Актуальная | 6.x / 7.x |
| 8.x | Bookworm (12) | Июн 2023 | **Завершена** | 6.x |
| 7.x | Bullseye (11) | Ноя 2021 | Завершена | 5.x |

После наступления EOL узлы перестают получать обновления безопасности. Обновление до актуальной ветки — единственный способ поддерживать соответствие требованиям безопасности (compliance).

> **Важно**: при наличии подписки Enterprise EOL продлевается на 6 месяцев. Однако даже с подпиской после окончания стандартного цикла обновление до новой ветки остается единственным долгосрочным решением.

### Плановое (точечное) обновление

В рамках одной мажорной версии достаточно штатного обновления пакетов:

```bash
apt update && apt dist-upgrade
```

Рекомендуется включить **No-Subscription** или иметь активную подписку, иначе обновление будет недоступно. Обновления внутри ветки (например, 9.1 → 9.2) выполняются тем же способом — никакой специальной процедуры не требуется.

### Безопасное обновление (Best Practices)

- **Терминальный мультиплексор**: При мажорном обновлении используйте SSH + `tmux` или `screen`. Веб-консоль GUI (включая noVNC-терминал) закроется при перезапуске `pveproxy`.
- **Внеполосной доступ**: Убедитесь, что для каждого узла доступен IPMI/iKVM/iDRAC или физическая консоль. Обновление ядра или сетевая проблема могут отключить удаленный доступ.
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
- **Тестирование ядра**: свежие сборки ядра (например, 7.0.0.3) могут содержать критические ошибки, приводящие к kernel panic и невозможности загрузки. Тестируйте обновления на выделенном узле перед применением к production. Откат на предыдущее ядро через GRUB не всегда возможен.

## Подготовка к обновлению (Pre-Upgrade Checklist)

Перед любым обновлением (особенно мажорным) выполните полную проверку состояния узла/кластера. Отсутствие подготовительных шагов — основная причина простоев.

### Проверка дискового пространства

```bash
df -h /
df -h /boot
# → Корневой раздел должен иметь минимум 5 ГБ свободно, рекомендуется 10+ ГБ
# → /boot — минимум 500 МБ (при множестве ядер может требоваться больше)
```

Для ZFS/LVM-Thin проверьте также общий пул:

```bash
zpool list
# → capacity не должен превышать 70-80%
lvs
# → lvmthinpool VG/lvthin — проверьте Data%, Meta%
```

### Создание snapshot'ов хранилища (Rollback foundation)

**ZFS** (если используется как хранилище данных):

```bash
zfs snapshot -r pool/data@pre-upgrade-$(date +%Y%m%d)
# → snapshot pool/data@pre-upgrade-20260917 created
zfs list -t snapshot | grep pre-upgrade
```

**LVM** (если используется LVM или LVM-Thin):

```bash
# Для обычного VG
lvcreate -L 5G -s -n vm-101-disk-0-snap VG/vm-101-disk-0
# Для thin pool — snapshot создается автоматически при создании VM backup
vzdump --mode snapshot --storage local-lvm 101
```

**Ceph RBD** (гиперконвергентные кластеры):

```bash
rbd snap create rbd/vm-101-disk-0@pre-upgrade-$(date +%Y%m%d)
# → Snap successfully created
```

> **Важно**: snapshot'ы хранилища не заменяют резервные копии VM. Они защищают только от проблем с обновлением самого узла, но не от повреждения файловой системы внутри гостя.

### Резервные копии виртуальных машин

Перед обновлением узла создайте свежие бэкапы всех критичных VM и LXC:

```bash
# Одиночная VM
vzdump 101 --mode snapshot --storage pbs --compress zstd

# Все запущенные VM на узле
for vmid in $(qm list | awk 'NR>1 {print $1}'); do
  vzdump $vmid --mode snapshot --storage pbs
done

# Все контейнеры
for ctid in $(pct list | awk 'NR>1 {print $1}'); do
  vzdump $ctid --mode snapshot --storage pbs
done
```

Верификация бэкапа:

```bash
vzdump --check 101 --storage pbs
# → Archive .vma.zst is valid
```

### Проверка конфигурации и зависимостей

```bash
# Проверка зафиксированных (held) пакетов
dpkg --get-selections | grep hold
# → Если есть held-пакеты — примите решение: оставить или удалить hold

# Проверка сторонних репозиториев
grep -r ^deb /etc/apt/sources.list.d/
# → Все источники, кроме официальных Proxmox/Ceph, должны быть проверены на совместимость

# Проверка locale и часового пояса (во избежание проблем с systemd-timesyncd)
timedatectl status
```

### Проверка аппаратной совместимости

```bash
# Проверка модулей ядра, загруженных при текущем запуске
lsmod | grep -E 'kvm|dm|zfs|ceph|rbd'
# → При обновлении ядра модули должны быть доступны для нового ядра

# Проверка SMART-статуса дисков (особенно для boot диска)
smartctl -a /dev/sda | grep -E 'SMART overall-health|Reallocated_Sector_Ct'
```

### Обновление чеклиста

- [ ] Созданы snapshot'ы ZFS/LVM/Ceph
- [ ] Созданы и верифицированы бэкапы всех VM/LXC
- [ ] Корневой раздел имеет ≥ 10 ГБ свободного места
- [ ] Нет held-пакетов, блокирующих обновление
- [ ] Все сторонние пакеты проверены на совместимость с целевой версией
- [ ] Сетевые интерфейсы зафиксированы через udev/systemd link
- [ ] Для кластера: настроен Maintenance Mode, HA-ресурсы мигрированы

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

> **Внимание**: PVE 8.x достиг EOL. Обновление до 9.x необратимо, поэтому перед началом обязательны тестированные бэкапы и snapshot'ы хранилища. На EOL-версиях репозитории могут быть перенесены в архив — убедитесь, что зеркала доступны.

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

### Обновление standalone-узла (не кластера)

Для одиночного узла (standalone) процедура упрощена: нет необходимости в Maintenance Mode и миграции. Однако бэкапы и snapshot'ы остаются обязательными.

1. Создание snapshot'а хранилища и бэкапов (см. раздел подготовки).
2. Обновление репозиториев на PVE 8:
   ```bash
   sed -i 's/bookworm/trixie/g' /etc/apt/sources.list
   cat > /etc/apt/sources.list.d/proxmox.sources << 'EOF'
   Types: deb
   URIs: http://download.proxmox.com/debian/pve
   Suites: trixie
   Components: pve-no-subscription
   Signed-By: /usr/share/keyrings/proxmox-archive-keyring.gpg
   EOF
   ```
3. Удаление старых `.list` файлов:
   ```bash
   rm -f /etc/apt/sources.list.d/pve-enterprise.list /etc/apt/sources.list.d/pve-install-repo.list
   ```
4. Запуск обновления:
   ```bash
   apt update && apt dist-upgrade
   ```
5. Для UEFI: установка `grub-efi-amd64` (см. шаг 9 процедуры для кластера).
6. Перезагрузка и проверка:
   ```bash
   reboot
   pveversion -v
   pve8to9 --full
   ```

### Просмотр changelog перед обновлением

Перед установкой пакетов ознакомьтесь с изменениями:

```bash
apt changelog pve-manager | head -100
# → Показывает изменения между текущей и доступной версией

# Для всех доступных обновлений
apt list --upgradable
# → proxxmox-ve/stable 9.2-1 upgradable
```

### Очистка старых ядер

После обновления удалите устаревшие ядра, чтобы освободить место в `/boot` и ускорить загрузку GRUB:

```bash
# Просмотр установленных ядер
dpkg -l 'linux-image-*' | grep ^ii
# → ii  linux-image-6.8.12-1-pve  6.8.12-1
# → ii  linux-image-7.0-1-pve     7.0-1  (актуальное)

# Удаление старого ядра (замените версию)
apt purge 'linux-image-6.8.12-1-pve'
update-grub
# → Generating grub configuration file ...

# Автоматическая очистка (без удаления текущего ядра)
apt autoremove --purge
```

> **Важно**: не удаляйте текущее загрузочное ядро. Проверьте текущее: `uname -r`.

### Восстановление после неудачного обновления (Rollback)

Если обновление прервалось или узел не загружается, используйте snapshot хранилища:

**ZFS snapshot rollback:**

```bash
# Загрузка с Live CD / Rescue режимом PVE
zfs rollback -r pool/data@pre-upgrade-20260917
# → will rollback pool/data and all datasets to pre-upgrade-20260917
```

**LVM snapshot rollback:**

```bash
# Смонтировать LV и слияние snapshot'а
lvconvert --merge VG/vm-101-disk-0-snap
# → Merging of snapshot VG/vm-101-disk-0-snap will happen on next activation.
lvchange --refresh VG/vm-101-disk-0
```

**Ceph RBD rollback:**

```bash
rbd snap rollback rbd/vm-101-disk-0@pre-upgrade-20260917
# → Rolling back to snapshot pre-upgrade-20260917
```

**Восстановление из бэкапа (последний инстанс):**

```bash
# Восстановление VM из PBS/vzdump
qmrestore /var/lib/vz/dump/vzdump-qemu-101.vma.zst 101 --storage local-lvm
```

### Автоматизация обновлений через Ansible

Для централизованного управления обновлениями в кластере используйте Ansible. Пример playbook'а:

```yaml
---
- name: Update Proxmox node
  hosts: proxmox_nodes
  become: true
  vars:
    target_version: "trixie"
    pve_subscription: "no-subscription"
  tasks:
    - name: Disable enterprise repo
      lineinfile:
        path: /etc/apt/sources.list.d/pve-enterprise.sources
        line: "Enabled: false"
        create: yes

    - name: Configure no-subscription repo
      copy:
        dest: /etc/apt/sources.list.d/proxmox.sources
        content: |
          Types: deb
          URIs: http://download.proxmox.com/debian/pve
          Suites: trixie
          Components: pve-no-subscription
          Signed-By: /usr/share/keyrings/proxmox-archive-keyring.gpg

    - name: Update apt cache
      apt:
        update_cache: yes
        cache_valid_time: 3600

    - name: Upgrade all packages
      apt:
        upgrade: dist
        autoremove: yes
        purge: yes

    - name: Install grub-efi-amd64 for UEFI
      apt:
        name: grub-efi-amd64
        state: present
      when: ansible_mounts | selectattr('mount', 'equalto', '/boot/efi') | list | length > 0

    - name: Reboot if kernel updated
      reboot:
        reboot_timeout: 600
      when: ansible_kernel != '7.0-pve'
```

Запуск rolling update по кластеру:

```bash
# На управляющей ноде
ansible-playbook -i inventory.ini proxmox-rolling-upgrade.yml --limit node1
# → Обновляет node1, ждет перезагрузки, затем переходит к следующему
```

> **Примечание**: убедитесь, что Inventory содержит все узлы в правильном порядке обновления, а `--limit` позволяет обновлять по одному узлу.

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
- **`Hash Sum mismatch` при `apt update`** — поврежденный кэш индексов. Очистите и повторите:
  ```bash
  apt clean
  rm -rf /var/lib/apt/lists/*
  apt update
  ```
- **Зависший `dpkg` на half-configured** — предыдущее обновление было прервано:
  ```bash
  dpkg --configure -a
  apt dist-upgrade
  ```
- **`pve8to9` показывает FAIL на `ceph`** — Ceph не обновлен до Squid (19.x). PVE 9 несовместим с Ceph 17/18. Сначала выполните обновление Ceph на PVE 8, затем возвращайтесь к `pve8to9`.
- **Не стартует `pveproxy` после обновления** — проверьте конфликты портов и сертификаты:
  ```bash
  systemctl status pveproxy
  journalctl -u pveproxy -n 50
  ss -tlnp | grep 8006
  ```
- **Потеря кворума после обновления узла** — несовместимость версий корневой файловой системы pmxcfs. Проверьте версии `pve-cluster` на всех узлах:
  ```bash
  pveversion -v | grep pve-cluster
  # → Все узлы должны иметь одинаковую версию
  ```
- **Заполнен `/boot`** — слишком много ядер. Очистите старые версии (см. раздел очистки старых ядер) или расширьте раздел.
- **Не обновляются сторонние пакеты** — из-за APT pinning или held-пакетов:
  ```bash
  apt-mark showhold
  # → Удалите hold для пакетов, которые должны обновляться
  apt-mark unhold <package>
  ```
- **Ceph `nearfull`/`full` во время обновления** — остановите запись, снимите флаги `noout` только после проверки ` HEALTH_OK`:
  ```bash
  ceph -s
  ceph osd unset noout
  # → Повторяйте ceph -s до получения HEALTH_OK
  ```

## Лучшие практики

- **Тестирование обновлений**: перед обновлением production выполните полный цикл обновления на стенде, повторяющем конфигурацию production.
- **Изменения по одному**: не смешивайте обновление ОС, ядра, Ceph и прикладного ПО в одно окно. Каждое изменение — отдельное окно с отдельным бэкапом.
- **Snapshot перед обновлением**: всегда создавайте snapshot хранилища до начала работ. Для ZFS/LVM это занимает секунды, но позволяет откатиться без потерь.
- **Фиксация сетевых интерфейсов**: используйте udev-правила или systemd `.link`-файлы для предсказуемых имен интерфейсов после обновления ядра.
- **Мониторинг во время обновления**: оставьте открытым `tail -f /var/log/syslog` или `journalctl -fu pveproxy` для отслеживания ошибок в реальном времени.
- **Ограничение EOL**: планируйте обновление за 3-6 месяцев до наступления EOL, чтобы избежать давления и рисков.
- **Квартальные патч-вторники**: выделите фиксированное окно для обновлений безопасности внутри мажорной ветки. В PVE 9 достаточно `apt update && apt dist-upgrade`.
- **Документирование изменений**: ведите журнал изменений (changelog) на уровне кластера с указанием версий до/после, узлов и проблем.
- **Резервный доступ**: имейте для каждого узла out-of-band управление (IPMI/iDRAC/iKVM). Веб-интерфейс может стать недоступен при обновлении `pveproxy`.
- **Аппаратный RAID**: для boot-раздела используйте RAID1 (модуль ядра `dm-raid`), чтобы избежать потери данных при отказе диска во время обновления.

## Граничные случаи (Edge Cases)

- **Нехватка места во время `dist-upgrade`**: `apt` может не завершиться с ошибкой `No space left on device` на `/boot` или `/`. Создайте временное пространство или очистите кэш `apt` (`apt clean`).
- **Обновление ядра с проприетарными модулями** (NVIDIA GPU passthrough, VMware NSX, специализированные HBA): перед обновлением проверьте доступность модулей для нового ядра:
  ```bash
  # Для модулей NVIDIA
  dkms status
  # → nvidia/535.113.01, 6.8.12-1-pve, x86_64: installed
  # После обновления ядра модуль нужно пересобрать:
  dkms autoinstall
  ```
- **Смешанный кластер PVE 8/9 с Ceph**: Live Migration между узлами разных версий **не поддерживается**. Используйте только холодную миграцию.
- **Обновление при включенном ZFS replication**: репликация может зафиксировать состояние mid-upgrade. Остановите scheduled replication на время обновления узла:
  ```bash
  zfs list -t snapshot | grep pve2-weekly
  # → Остановите задачу replication в GUI или systemctl stop pvedaemon
  ```
- **Ceph OSD failure во время обновления**: если OSD падает во время rolling upgrade, не снимайте флаги `noout/noscrub` до полного восстановления кластера. `noout` предотвращает ненужные перебалансировки.
- **Кластер с одним узлом (quorum loss)**: при обновлении последнего узла в 2-узловом кластере без witnesses кворум теряется. Используйте `qdevice` или обновляйте только при наличии witnesses.
- **Загрузка с устаревшего ядра после обновления**: проверьте GRUB configuration и порядок загрузки:
  ```bash
  grep -E 'menuentry|linux' /boot/grub/grub.cfg | head -20
  # → Убедитесь, что актуальное ядро указано первым
  ```
- **APT pinning и сторонние пакеты**: если вы используете APT pinning для фиксации версий, после обновления проверьте, что политика приоритетов не блокирует новые пакеты Proxmox:
  ```bash
  apt policy pve-manager
  # → Должен показывать целевую версию из trixie
  ```

## Дополнительная информация

### Связанные темы

- [Proxmox VE — Обзор и базовые концепции](./proxmox_overview.md)
- [Кластеризация и High Availability в Proxmox](./proxmox_cluster.md)
- [Proxmox Backup Server (PBS)](./proxmox_backup_server.md)

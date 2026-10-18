# Обновление систем Proxmox

**Актуально для:** Proxmox VE 9.2 (PVE 9.x на Debian 13 «Trixie»; PVE 8.x — EOL 31.08.2026) / Proxmox Backup Server 4.2 (ветка PBS 4.x)

## Определения

**Proxmox Virtual Environment (PVE)** — платформа виртуализации с открытым исходным кодом на базе Debian. Актуальная ветка — **9.x** (Debian 13 «Trixie»; PVE 9.2 — ядро Linux 7.0, Debian 13.5).

**Proxmox Backup Server (PBS)** — специализированное решение для инкрементального резервного копирования. Обновляется **отдельно** от PVE (см. раздел [Обновление PBS 3 → 4](#pbs-3-to-4)).

**In-place Upgrade (Обновление на месте)** — процесс мажорного обновления ОС без переустановки: смена репозиториев в `apt` и полное обновление пакетов (`apt dist-upgrade` / `apt full-upgrade`). Формального пути отката через `apt` не существует — единственной защитой являются протестированные резервные копии и snapshot'ы хранилища, созданные *до* начала работ.

**deb822 (.sources)** — многострочный формат описания apt-репозиториев, стандартный в PVE 9 (Debian 13). Пришел на смену однострочному формату `deb <uri> <suite> <component>` в файлах `.list`, который использовался в PVE 8 и ранее.

**pve8to9** — встроенный в PVE 8.4+ чеклист проверки готовности к мажорному обновлению 8 → 9. Только читает конфигурацию и отчитывается (`--full` — все проверки), автоматически ничего не чинит.

**pbs3to4** — аналогичный чеклист для обновления PBS 3.4 → 4.x, входит в состав пакетов PBS 3.4.

**Maintenance Mode (Режим обслуживания)** — режим узла кластера PVE, при котором все HA-сервисы с него мигрируют, а новые на нем не запускаются. Используется при плановых работах, в том числе при обновлении (см. [Кластеризация](./proxmox_cluster.md)).

**HA arm/disarm (PVE 9.2)** — кластерное «разоружение» HA-стека на время обслуживания: fencing и failover отключаются, состояния ресурсов сохраняются. Альтернатива или дополнение Maintenance Mode при обновлении (см. [Кластеризация](./proxmox_cluster.md)).

**Rollback (Откат)** — возврат системы к предыдущему рабочему состоянию. У in-upgrade нет формального пути отката через `apt`; единственные механизмы — восстановление из резервной копии (vzdump/PBS) или rollback snapshot'а хранилища (ZFS, LVM, Ceph RBD), созданного до обновления.

**EOL (End of Life)** — дата прекращения поддержки версии. После EOL обновления безопасности не выпускаются. Важно планировать обновление до наступления EOL.

**APT Pinning** — управление приоритетом пакетов из разных репозиториев через `/etc/apt/preferences.d/`. Позволяет зафиксировать версию пакета или запретить установку из тестового репозитория.

**apt-mark hold** — фиксация установленной версии пакета, запрещающая его обновление до снятия hold. Используется для «заморозки» узла на окно обслуживания и для защиты от нежелательных обновлений критичных компонентов.

## Основные концепции

### Типы репозиториев

1. **Enterprise Repository**: рекомендуемый для production; доступен при наличии подписки любого уровня. Без валидной подписки `apt update` завершается ошибкой `401 Unauthorized`. В PVE 9 — файл `/etc/apt/sources.list.d/pve-enterprise.sources`.
2. **No-Subscription Repository**: официально предназначен для тестирования и non-production. Содержит те же пакеты, что и Enterprise, с меньшим циклом проверки. В PVE 9 — файл `/etc/apt/sources.list.d/proxmox.sources`.
3. **Test Repository**: самые свежие пакеты, в основном для разработчиков. Не для продакшена.

> **Всегда нужны и базовые репозитории Debian** рядом с репозиторием Proxmox — без них обновление зависимостей (libc, systemd и т.д.) невозможно. В PVE 9 это `/etc/apt/sources.list` (Trixie) и/или дистрибутивные `.sources` в `/etc/apt/sources.list.d/`.

**Форматы файлов репозиториев по версиям:**

- **PVE 9 (Debian 13 «Trixie»)**: формат deb822 `.sources`. Ключ подписи — `/usr/share/keyrings/proxmox-archive-keyring.gpg`.
- **PVE 8 (Debian 12 «Bookworm»)**: классический формат `.list`, кодовое имя `bookworm`. Ключ — `/etc/apt/trusted.gpg.d/proxmox-release-bookworm.gpg`. **Поддержка завершена** (EOL).
- **PVE 7 (Debian 11 «Bullseye»)**: классический формат `.list`, кодовое имя `bullseye`. Ветка EOL, репозитории сохранены только для миграции.

### Жизненный цикл версии и даты EOL

По данным официальной FAQ (pve-docs chapter-pve-faq):

| Версия PVE | База Debian | Первый релиз | Debian EOL | Proxmox EOL | Ядро (по ветке) |
|------------|-------------|--------------|------------|-------------|-----------------|
| 9.x | Trixie (13) | 2025-08 | tba | tba | 6.14 (9.0) → 6.17 (9.1) → **7.0 (9.2)** |
| 8.x | Bookworm (12) | 2023-06 | 2026-07 | **2026-08 (31.08.2026)** | 6.x |
| 7.x | Bullseye (11) | 2021-07 | 2024-07 | 2024-07 | 5.x / 6.x |

После наступления EOL узлы перестают получать обновления безопасности. Обновление до актуальной ветки — единственный способ поддерживать соответствие требованиям безопасности (compliance). Стандартная поддержка ветки примерно равна сроку поддержки соответствующего Debian Security Team (≈3 года), с небольшим запасом у Proxmox после Debian EOL (у PVE 8 — один месяц: Debian 2026-07, Proxmox 2026-08). Отдельного «продления на 6 месяцев по подписке» нет.

> На **18.10.2026**: PVE 8.x и PBS 3.4 уже EOL; Ceph Squid (19.2) — estimated EOL 2026-09. Узлы на этих ветках не получают исправлений — обновление не стоит откладывать.

### Точечное (плановое) обновление внутри ветки

В рамках одной мажорной версии (например, 9.1 → 9.2) специальная процедура не нужна:

```bash
apt update && apt full-upgrade
# или
apt update && apt dist-upgrade
```

`apt upgrade` для ядра и снятия зависимостей не подходит: он не удаляет/не заменяет пакеты, когда это необходимо для разрешения зависимостей, и может оставить систему с устаревшим ядром и конфликтующими пакетами. Используйте `full-upgrade` (синоним `dist-upgrade` — оба корректны).

Проверить, что доступно, не применяя обновления:

```bash
apt list --upgradable
# → proxmox-ve/stable 9.2-1 upgradable [from 9.1.x]
# → pve-manager/stable 9.2.2 upgradable [from ...]
```

В GUI: Datacenter → Updates, либо Node → Updates. Обновления в веб-интерфейсе применяются тем же `apt` под капотом.

### Безопасное обновление (Best Practices)

- **Терминальный мультиплексор**: при мажорном обновлении используйте SSH + `tmux` или `screen`. Веб-консоль GUI (включая noVNC) закроется при перезапуске `pveproxy`.
- **Внеполосной доступ**: убедитесь, что для каждого узла доступен IPMI/iKVM/iDRAC или физическая консоль. Обновление ядра или сетевая проблема могут отключить удаленный доступ.
- **Резервные копии**: обязательны протестированные бэкапы всех VM и LXC (`vzdump` или PBS) и snapshot'ы хранилища. Отката у in-place upgrade нет — бэкап это единственный способ восстановления.
- **Свободное место**: минимум 5 ГБ на корневом разделе (`/`), рекомендуется 10+ ГБ; `/boot` — минимум 500 МБ свободно (при множестве ядер — больше).
- **Явная привязка имен интерфейсов**: при переходе на новое ядро имена сетевых интерфейсов могут измениться (`enp*`/`ens*`). Проверьте `vmbr0` и физические интерфейсы, при необходимости зафиксируйте их через udev-правила или systemd `.link`-файлы до обновления.
- **Последовательность в кластере**:
  1. Обновляйте строго по одному узлу за раз, сохраняя кворум.
  2. Миграция ВМ с обновляемого узла (или Maintenance Mode / HA disarm в PVE 9.2).
  3. Перевод узла в Maintenance Mode.
  4. Обновление пакетов.
  5. Перезагрузка (обязательна при обновлении ядра).
  6. Проверка, что узел вернулся в кластер, и только затем переход к следующему.
- **Не смешивайте изменения**: обновление ОС/ядра, Ceph и прикладного ПО — разные окна с разными бэкапами.
- **Тестирование ядра**: свежие сборки ядра могут содержать критические ошибки (kernel panic, отказ загрузки). Тестируйте на выделенном узле перед production. Откат на предыдущее ядро через GRUB возможен не всегда (см. [Управление ядром](./proxmox_kernel_management.md)).
- **Live patching**: для узлов, где перезагрузка откладывается, применим livepatch — см. [Управление ядром](./proxmox_kernel_management.md). Это не заменяет мажорное обновление, но закрывает критичные CVE ядра в окне до reboot.
- **Unattended-upgrades**: на гипервизорах **не включайте** полный unattended-upgrade по умолчанию — обновление ядра/QEMU требует проверки changelog, перезагрузки и контроля HA. Если автоматизация обязательна (соответствие политике), ограничьтесь безопасными пакетами, настройте `Unattended-Upgrade::Automatic-Reboot "false"` и вынесите reboot в управляемое окно.

## Подготовка к обновлению (Pre-Upgrade Checklist)

Перед любым обновлением (особенно мажорным) выполните полную проверку состояния узла/кластера. Отсутствие подготовки — основная причина простоев.

### Проверка дискового пространства

```bash
df -h /
df -h /boot
# → Корневой раздел: минимум 5 ГБ свободно, рекомендуется 10+ ГБ
# → /boot: минимум 500 МБ

du -sh /var/cache/apt/archives
# → большой кэш можно освободить: apt clean
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
# → snapshot pool/data@pre-upgrade-20261018 created
zfs list -t snapshot | grep pre-upgrade
```

**LVM** (обычный LV; для thin pool snapshot'ы — временные, в режиме бэкапа):

```bash
lvcreate -L 5G -s -n vm-101-disk-0-snap VG/vm-101-disk-0
# Для thin: vzdump в режиме snapshot создаёт временные снапшоты
# и удаляет их по завершении — долгосрочный rollback — только из бэкапа
vzdump --mode snapshot --storage local-lvm 101
```

**Ceph RBD** (гиперконвергентные кластеры):

```bash
rbd snap create rbd/vm-101-disk-0@pre-upgrade-$(date +%Y%m%d)
# → Snap successfully created
```

> **Важно**: snapshot'ы хранилища не заменяют резервные копии VM. Они защищают от проблем с обновлением самого узла (когда данные гостей не тронуты), но не от повреждения ФС внутри гостя.

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
# Held-пакеты, блокирующие обновление
dpkg --get-selections | grep hold
apt-mark showhold
# → Решение: оставить hold или apt-mark unhold <package>

# Сторонние репозитории (PVE 9 — deb822; grep ^deb не увидит .sources)
grep -rE '^(deb|URIs:)' /etc/apt/sources.list /etc/apt/sources.list.d/ 2>/dev/null
# → Все источники, кроме официальных Proxmox/Ceph/Debian, должны быть
#   проверены на совместимость с целевой версией

# Часовой пояс и синхронизация времени
timedatectl status
```

### Проверка аппаратной совместимости

```bash
# Модули ядра, загруженные при текущем запуске (после обновления
# ядра они должны быть доступны в DKMS для нового ядра)
lsmod | grep -E 'kvm|dm|zfs|ceph|rbd'

# Статус SMART boot-диска
smartctl -a /dev/sda | grep -E 'SMART overall-health|Reallocated_Sector_Ct'
```

### Чеклист подготовки

- [ ] Созданы snapshot'ы ZFS/LVM/Ceph
- [ ] Созданы и верифицированы бэкапы всех VM/LXC
- [ ] Корневой раздел ≥ 10 ГБ свободного места, `/boot` ≥ 500 МБ
- [ ] Нет held-пакетов, блокирующих обновление
- [ ] Сторонние репозитории и пакеты проверены на совместимость
- [ ] Сетевые интерфейсы зафиксированы через udev/systemd .link
- [ ] Для кластера: настроен Maintenance Mode (или HA disarm), HA-ресурсы мигрированы
- [ ] Для HCI: Ceph обновлён до поддерживаемой целевой версии **до** PVE (см. ниже)
- [ ] Для UEFI+LVM: установлен метапакет `grub-efi-amd64` (см. раздел 8→9)
- [ ] Для систем на `proxmox-boot-tool` (ZFS on root + UEFI): запланирован `proxmox-boot-tool refresh` после обновления ядра

## Настройка репозиториев

### No-Subscription в PVE 9 (формат deb822)

1. Отключение Enterprise (формально по спецификации deb822 — `Enabled: no`; apt принимает и `false`):
   ```bash
   echo 'Enabled: no' >> /etc/apt/sources.list.d/pve-enterprise.sources
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

3. Для гиперконвергентного кластера отдельно настраивается репозиторий Ceph (`/etc/apt/sources.list.d/ceph.sources`):
   ```bash
   # PVE 9.2+: Tentacle (рекомендуемый, EOL 2027-11)
   cat > /etc/apt/sources.list.d/ceph.sources << 'EOF'
   Types: deb
   URIs: http://download.proxmox.com/debian/ceph-tentacle
   Suites: trixie
   Components: no-subscription
   Signed-By: /usr/share/keyrings/proxmox-archive-keyring.gpg
   EOF
   ```

   > Путь `ceph-tentacle` соответствует Ceph 20.x; для существующих кластеров на Squid (19.2) путь — `ceph-squid` (EOL 2026-09 — переход на Tentacle не откладывайте). Сверяйтесь с версией в существующем файле репозитория. Подробнее — [Package Repositories (wiki)](https://pve.proxmox.com/wiki/Package_Repositories) и [Хранилища](./proxmox_storage.md).

4. Обновление списков:
   ```bash
   apt update
   apt policy proxmox-ve
   # → Candidate должен указывать на версию из trixie
   ```

### No-Subscription в PVE 8 (справочно, EOL)

PVE 8 и более ранние использовали однострочный формат `.list`:

```bash
sed -i 's/^deb/#deb/g' /etc/apt/sources.list.d/pve-enterprise.list
echo "deb http://download.proxmox.com/debian/pve bookworm pve-no-subscription" \
  > /etc/apt/sources.list.d/pve-install-repo.list
apt update
```

## Мажорное обновление PVE 8.x → 9.x

> **Внимание**: ветка PVE 8 достигла EOL **31.08.2026** — новые исправления безопасности не выпускаются. Обновление необратимо: обязательны протестированные бэкапы и snapshot'ы. Если Enterprise-репозиторий ещё отвечает, пакеты 8.4.x можно получить; при проблемах с доступом убедитесь, что зеркала/no-subscription доступны.

Порядок шагов (на каждом узле, если не указано иное; для кластера — см. также «Стратегию для кластера» ниже):

1. **Обновление до последней PVE 8.4**:
   ```bash
   apt update && apt dist-upgrade
   ```
   Требуется версия **8.4.1 или новее** — в ней появляется `pve8to9`.

2. **Проверка готовности** (на каждом узле кластера — до обновления первого):
   ```bash
   pveversion
   pve8to9 --full
   # → System health check passed: OK
   ```
   `pve8to9 --full` — read-only диагностика: репозитории, хранилища, кластер, загрузчик, сторонние пакеты. Красные пункты (FAIL) устраняются, желтые (WARN) изучаются. Прогоняйте чеклист повторно после исправлений и после обновления.

3. **Ceph (только HCI)**: Ceph должен быть на версии **19.x Squid** до обновления PVE — PVE 9 не работает с Ceph 17/18. Порядок: сначала Reef→Squid ещё на PVE 8, затем PVE 8→9, затем Squid→Tentacle на PVE 9.1+ (см. раздел [Обновление кластера с Ceph](#обновление-кластера-с-ceph-гиперконвергентный-кластер)).

4. **Загрузчик и ESP (критично для UEFI)**:
   ```bash
   # UEFI + root on LVM: без grub-efi-amd64 следующий boot может упасть
   [ -d /sys/firmware/efi ] && apt install grub-efi-amd64

   # Если pve8to9 предупреждает о systemd-boot meta-package (Trixy):
   # метапакет systemd-boot сам меняет загрузчик при апдейтах — для
   # штатных PVE-систем (GRUB или proxmox-boot-tool) его удаляют:
   apt purge systemd-boot
   # (systemd-boot-efi / systemd-boot-tools при необходимости pve8to9
   #  предложит оставить — их удалять не нужно)
   ```
   Дополнительно `pve8to9` проверяет случай removable-загрузчика `/boot/efi/EFI/BOOT/BOOTX64.efi`: если GRUB не настроен обновлять его, выполните:
   ```bash
   echo 'grub-efi-amd64 grub2/force_efi_extra_removable boolean true' | debconf-set-selections -v -u
   apt install --reinstall grub-efi-amd64
   ```
   Для ZFS on root + UEFI (`proxmox-boot-tool`) после обновления ядра:
   ```bash
   proxmox-boot-tool refresh
   ```

5. **Подготовка терминала**:
   ```bash
   tmux new-session -s upgrade
   # или
   screen -S upgrade
   ```

6. **Миграция репозиториев Debian Bookworm → Trixie**:
   ```bash
   sed -i 's/bookworm/trixie/g' /etc/apt/sources.list
   # Если остались .list с bookworm (включая pve-enterprise.list):
   sed -i 's/bookworm/trixie/g' /etc/apt/sources.list.d/*.list 2>/dev/null
   ```

7. **Добавление репозиториев PVE 9 в формате deb822** (замените `pve-no-subscription` на `pve-enterprise` при наличии подписки):
   ```bash
   cat > /etc/apt/sources.list.d/proxmox.sources << 'EOF'
   Types: deb
   URIs: http://download.proxmox.com/debian/pve
   Suites: trixie
   Components: pve-no-subscription
   Signed-By: /usr/share/keyrings/proxmox-archive-keyring.gpg
   EOF
   ```

8. **Удаление устаревших файлов** и проверка:
   ```bash
   rm -f /etc/apt/sources.list.d/pve-install-repo.list
   apt update
   apt policy
   ```

9. **Запуск обновления**:
   ```bash
   apt dist-upgrade
   # → Calculating upgrade... Done
   # → ... пакетов будет обновлено ...
   ```
   Внимательно отвечайте на вопросы о конфигурационных файлах: для `/etc/lvm/lvm.conf` рекомендована версия сопровождающих (maintainer), для измененных вами файлов — сверяйте diff. Прерывать dist-upgrade нельзя; при обрыве — `dpkg --configure -a` и повтор.

10. **Повторный чеклист и перезагрузка**:
    ```bash
    pve8to9 --full
    # → System health check passed: OK
    reboot
    ```
    Перезагрузка обязательна: без неё работает старое ядро, а ABI пакетов (QEMU, ZFS-модули) уже новые — такое состояние нестабильно.

11. **Проверка после обновления** — раздел [Диагностика и проверка](#диагностика-и-проверка).

> **Совет**: после успешного обновления устаревшие файлы `.list` можно перевести в формат deb822:
> ```bash
> apt modernize-sources
> ```
> Резервные копии не должны оставаться в `/etc/apt/sources.list.d/` — файлы `.bak` внутри него вызывают предупреждения в веб-интерфейсе; перенесите их вне каталога (например, в `/root/apt-sources-backup/`).

### Предыдущее мажорное обновление PVE 7.4 → 8.x (справочно)

> Ветка PVE 7 достигла EOL (2024-07). Процедура приведена как историческая справка для миграции устаревших инсталляций.

1. **Диагностика**: `pve7to8 --full` (read-only, аналогично pve8to9).
2. **Репозитории** (Bullseye → Bookworm):
   ```bash
   sed -i 's/bullseye/bookworm/g' /etc/apt/sources.list
   sed -i 's/bullseye/bookworm/g' /etc/apt/sources.list.d/*.list
   ```
3. **Обновление**: `apt update && apt full-upgrade`, затем перезагрузка и проверка.

### Обновление standalone-узла (не кластера)

Для одиночного узла процедура упрощена: нет Maintenance Mode и миграции. Бэкапы и snapshot'ы остаются обязательными. Выполните шаги 1–2, 4–11 мажорной процедуры (репозитории, загрузчик, dist-upgrade, reboot, проверка).

### Стратегия обновления кластера

- Обновляйте узлы **строго по одному**: `Узел 1 → Upgrade → Reboot → Verify → Узел 2 → ...`.
- Перед обновлением узла: миграция VM/LXC, перевод в Maintenance Mode (в PVE 9.2 можно дополнительно `ha-manager crm-command disarm-ha` — см. [Кластеризация](./proxmox_cluster.md)).
- В смешанном кластере PVE 8/9 **live migration не поддерживается** — только холодная миграция (или остановка гостей).
- **HA-группы → HA node affinity rules**: при обновлении до PVE 9 HA Manager автоматически мигрирует группы в правила. В смешанном кластере маппинг работает in-memory на узлах 9.x; персистентная миграция (с удалением `ha/groups.cfg`) выполняется только когда **все** узлы на PVE 9 с `pve-manager` ≥ 9.0. Правила не редактируйте до завершения кластерного обновления.
- После обновления всех узлов проверьте кворум и версии:
  ```bash
  pvecm status
  pveversion -v | grep pve-cluster
  # → Все узлы должны иметь одинаковую версию pve-cluster
  ```

## Обновление кластера с Ceph (гиперконвергентный кластер)

Порядок гиперконвергентного кластера строго фиксирован: **сначала Ceph, затем Proxmox**, мажорные переходы Ceph — по одному:

```
Ceph Reef (18.2) → Squid (19.2)  [ещё на PVE 8]
PVE 8 → 9                       [узел за узлом]
Ceph Squid (19.2) → Tentacle (20.2)  [на PVE 9.1+]
```

PVE 9 несовместим с Ceph 17/18: при обновлении узла с устаревшим Ceph кластер остаётся неработоспособным до исправления с консоли.

### Обновление Ceph Reef → Squid (на PVE 8)

1. Состояние кластера — `HEALTH_OK`:
   ```bash
   ceph -s
   ceph versions
   ```
2. Смена репозитория на каждом узле:
   ```bash
   sed -i 's/reef/squid/' /etc/apt/sources.list.d/ceph.list 2>/dev/null
   sed -i 's/reef/squid/' /etc/apt/sources.list.d/ceph.sources 2>/dev/null
   # no-subscription (.list):
   # deb http://download.proxmox.com/debian/ceph-squid bookworm no-subscription
   ```
3. Флаги защиты от rebalance при перезагрузках (с любой ноды):
   ```bash
   ceph osd set noout
   ceph osd set noscrub
   ceph osd set nodeep-scrub
   ceph osd set nobackfill
   ceph osd set norecover
   # → set noout
   ```
4. На каждом узле по очереди: `apt update && apt dist-upgrade`, затем перезапуск OSD:
   ```bash
   systemctl restart ceph-osd@*.service
   ```
5. После всех нод — снять флаги и проверить `HEALTH_OK`:
   ```bash
   ceph osd unset noout
   ceph osd unset noscrub
   ceph osd unset nodeep-scrub
   ceph osd unset nobackfill
   ceph osd unset norecover
   ceph -s
   # → health: HEALTH_OK
   ```

**Далее — обновление PVE 8 → 9 по процедуре выше, узел за узлом.**

### Обновление Ceph Squid → Tentacle (на PVE 9.1+)

Требования (wiki Ceph Squid to Tentacle): все узлы на PVE 9.1+, `pve-manager` ≥ **9.1.4**, Ceph-пакеты ≥ **19.2.3-pve3**, кластер `HEALTH_OK`:

```bash
pveversion --verbose | grep -E 'pve-manager|ceph'
```

1. На каждом узле сменить репозиторий:
   ```bash
   sed -i 's/squid/tentacle/' /etc/apt/sources.list.d/ceph.sources
   # или для legacy .list:
   sed -i 's/squid/tentacle/' /etc/apt/sources.list.d/ceph.list
   ```
2. Обновлять демоны по одному, начиная с mon/mgr, затем OSD — rolling upgrade с проверкой `ceph -s` после каждого узла; флаги `noout` (и при необходимости `nobackfill`/`norecover`) держать до стабилизации.
3. Массовые операции (`upgrade`, перезапуск демонов) выполняются **один раз на кластер**, не на каждом узле (кроме локального apt/рестарта).
4. После перехода всех демонов: `ceph versions` — все на 20.2.x; `ceph -s` → `HEALTH_OK`.

Глубина по Ceph (PG, EC, эксплуатация) — в [Storage/Ceph](../Kubernetes/Storage/Ceph/); специфика PVE-хранилищ — в [Хранилища](./proxmox_storage.md).

### Ceph во время rolling upgrade PVE

Если OSD падает во время обновления, **не снимайте** `noout/noscrub` до полного восстановления кластера. `nearfull`/`full` — сначала остановить запись/расширить кластер, затем продолжать (пороги и мониторинг — в [Хранилища](./proxmox_storage.md)).

## Обновление PBS 3 → 4 {#pbs-3-to-4}

Proxmox Backup Server обновляется **отдельно от PVE** (свой Debian, свои репозитории, свой чеклист). PBS 3.4 — EOL **август 2026** (ветка уже закрыта); PBS 4.x — на Debian 13 Trixie (kernel 6.14+). Источник процедур: [Upgrade from 3 to 4 (wiki)](https://pbs.proxmox.com/wiki/Upgrade_from_3_to_4); детали эксплуатации — [Proxmox Backup Server](./proxmox_backup_server.md).

### Подготовка

1. SSH/IPMI + `tmux`/`screen`; не через веб-консоль.
2. Обновить PBS до последней 3.4 (≥ 3.4.2):
   ```bash
   apt update && apt dist-upgrade
   proxmox-backup-manager versions
   # → proxmox-backup-server 3.4.2-1 running version: 3.4.2 (или новее)
   ```
3. Бэкап конфигурации и места:
   ```bash
   tar czf "pbs3-etc-backup-$(date -I).tar.gz" -C /etc proxmox-backup
   df -h /   # ≥ 10 ГБ свободно
   ```
4. Чеклист: `pbs3to4 --full` — устранить FAIL/WARN, повторить после правок.

### Выполнение

1. Смена репозиториев Bookworm → Trixie (enterprise/no-subscription по аналогии с PVE; файлы `pbs*.list` / `pbs*.sources`).
2. Загрузчик: те же правила, что и для PVE (UEFI+LVM → `grub-efi-amd64`; метапакет `systemd-boot` — удалить, если pve/pbs чеклист на это указывает).
3. `apt update && apt dist-upgrade` (конфигурационные вопросы — как при PVE).
4. Повторный `pbs3to4` → `systemctl reboot` (перезагрузка нужна даже если ядро 6.14 уже стояло — ABI новый).
5. Очистка старых `.list`/`.sources` Bookworm, `apt update && apt policy proxmox-backup-server`.
6. Проверка: GUI/CLI `proxmox-backup-manager versions`, статусы datastore, test-restore одного бэкапа.

## Просмотр changelog перед обновлением

```bash
apt changelog pve-manager | head -100
# → Изменения между текущей и доступной версией

apt list --upgradable
# → proxmox-ve/stable 9.2-1 upgradable [from ...]

# Release notes: forum/announce и pve-docs changelog
```

## Очистка старых ядер (после обновления)

После успешного обновления и reboot удалите устаревшие ядра, чтобы освободить `/boot` и ускорить загрузку GRUB:

```bash
# Текущее ядро
uname -r
# → 7.0.1-pve

# Установленные ядра Proxmox
dpkg -l 'linux-image-*-pve' 'proxmox-kernel-*' | grep ^ii

# Удаление конкретного старого ядра (замените версию!)
apt purge 'linux-image-6.17.4-1-pve'
update-grub
# → Generating grub configuration file ...

# Автоочистка (не удаляет текущее ядро)
apt autoremove --purge
```

> **Важно**: не удаляйте текущее загрузочное ядро (`uname -r`) и не очищайте `/boot` до успешной проверки системы после reboot.

## Восстановление после неудачного обновления (Rollback)

Если обновление прервалось или узел не загружается — с Live CD / rescue:

**ZFS:**

```bash
zfs rollback -r pool/data@pre-upgrade-20261018
# → will rollback pool/data and all datasets to pre-upgrade-20261018
```

**LVM snapshot:**

```bash
lvconvert --merge VG/vm-101-disk-0-snap
# → Merging ... will happen on next activation.
lvchange --refresh VG/vm-101-disk-0
```

**Ceph RBD:**

```bash
rbd snap rollback rbd/vm-101-disk-0@pre-upgrade-20261018
```

**Восстановление из бэкапа (последний инстанс):**

```bash
qmrestore /var/lib/vz/dump/vzdump-qemu-101.vma.zst 101 --storage local-lvm
# или через PBS: GUI → Restore / proxmox-backup-client
```

Восстановление узла (не гостей) при неработающем GRUB — см. [Boot failure recovery](../Linux/Diagnostics/Troubleshooting/boot_failure_recovery.md) и [GRUB](../Linux/SystemAdministration/grub.md).

## Автоматизация обновлений через Ansible

Для централизованного rolling update кластера. Шаблон playbook'а (паттерны интеграции Ansible ↔ Proxmox — в [Ansible](./proxmox_ansible.md)):

```yaml
---
- name: Update Proxmox node
  hosts: proxmox_nodes
  become: true
  serial: 1          # всегда по одному узлу
  tasks:
    - name: Disable enterprise repo
      ansible.builtin.lineinfile:
        path: /etc/apt/sources.list.d/pve-enterprise.sources
        regexp: "^#?Enabled:"
        line: "Enabled: no"
      when: ansible_distribution == "Debian"

    - name: Configure no-subscription repo
      ansible.builtin.copy:
        dest: /etc/apt/sources.list.d/proxmox.sources
        content: |
          Types: deb
          URIs: http://download.proxmox.com/debian/pve
          Suites: trixie
          Components: pve-no-subscription
          Signed-By: /usr/share/keyrings/proxmox-archive-keyring.gpg

    - name: Update apt cache
      ansible.builtin.apt:
        update_cache: true
        cache_valid_time: 3600

    - name: Upgrade all packages
      ansible.builtin.apt:
        upgrade: dist
        autoremove: true
        purge: true

    - name: Ensure grub-efi-amd64 on UEFI hosts
      ansible.builtin.apt:
        name: grub-efi-amd64
        state: present
      when: ansible_facts['firmware'] | default('') == 'efi'

    - name: Collect facts after upgrade
      ansible.builtin.setup:
        gather_subset:
          - '!all'
          - facter

    - name: Reboot if required
      ansible.builtin.reboot:
        reboot_timeout: 600
      when: ansible_reboot_required | default(false)
```

Запуск rolling update по одному узлу:

```bash
ansible-playbook -i inventory.ini proxmox-rolling-upgrade.yml --limit node1
```

> **Примечание**: перед playbook'ом убедитесь, что HA-ресурсы с узла мигрированы (или задайте drain через API — см. [Ansible](./proxmox_ansible.md)); `serial: 1` + `--limit` не отменяют проверку кворума после каждого узла.

## Диагностика и проверка

### Проверка версий после обновления

```bash
pveversion -v
# → proxmox-ve: 9.2-1 (running kernel: 7.0-1-pve)
# → pve-manager: 9.2.2 (running version: 9.2.2/...)
```

Пример вывода соответствует PVE 9.2 (Debian 13.5 «Trixie», ядро 7.0).

### Проверка состояния сервисов и кластера

```bash
systemctl status pve-cluster pvedaemon pveproxy
# → ● pveproxy.service - PVE API Proxy Server
# →    Active: active (running) since ...

systemctl --failed
# → 0 loaded units listed.

curl -k https://localhost:8006
pvecm status
# → Quorum: 3/3
ceph -s                              # при наличии Ceph
qm list
pct list
```

Убедитесь, что запланированные бэкапы и задачи репликации выполняются, а HA-ресурсы перешли в штатное состояние (в PVE 9.2 — состояние HA arm/disarm: должно быть `armed`).

### Частые проблемы и их устранение

- **`401 Unauthorized` при `apt update`** — включен Enterprise без активной подписки. Отключите его (`Enabled: no` в `pve-enterprise.sources`) или обновите токен: `pvesubscription update --force`.
- **Отсутствие сети после перезагрузки** — изменились имена сетевых интерфейсов. Зафиксируйте привязку заранее (Best Practices).
- **Незагружаемая система после обновления (UEFI+LVM)** — не установлен/не обновился `grub-efi-amd64` или не обновлён removable BOOTX64.efi (шаг 4 процедуры 8→9). Восстановление — chroot + `apt install --reinstall grub-efi-amd64` с `grub2/force_efi_extra_removable` (см. wiki Upgrade from 8 to 9 / форум).
- **`Hash Sum mismatch` при `apt update`** — поврежденный кэш индексов:
  ```bash
  apt clean
  rm -rf /var/lib/apt/lists/*
  apt update
  ```
- **Зависший `dpkg` (half-configured)** — прерванное обновление:
  ```bash
  dpkg --configure -a
  apt dist-upgrade
  ```
- **`pve8to9` показывает FAIL на `ceph`** — Ceph не обновлен до Squid (19.x). Сначала обновите Ceph на PVE 8, затем вернитесь к чеклисту.
- **`pve8to9` WARN про systemd-boot / BOOTX64.efi** — см. шаг 4 процедуры 8→9; игнорирование приводит к незагрузке после reboot.
- **Не стартует `pveproxy`** — конфликты портов и сертификаты:
  ```bash
  systemctl status pveproxy
  journalctl -u pveproxy -n 50
  ss -tlnp | grep 8006
  ```
- **Потеря кворума / разные версии pmxcfs** — несовместимость `pve-cluster` в смешанном кластере:
  ```bash
  pveversion -v | grep pve-cluster
  # → Все узлы должны иметь одинаковую версию
  ```
- **Заполнен `/boot`** — очистите старые ядра (раздел очистки) или расширьте раздел.
- **Сторонние пакеты не обновляются** — APT pinning или hold:
  ```bash
  apt-mark showhold
  apt-mark unhold <package>
  apt policy <package>
  ```
- **Ceph `nearfull`/`full`** — остановите запись/расширьте кластер; флаги `noout` снимайте только после `HEALTH_OK` (повторяйте `ceph -s`).

## Лучшие практики

- **Тестирование**: перед production — полный цикл на стенде, повторяющем конфигурацию.
- **Одно изменение за окно**: ОС/ядро, Ceph и прикладной слой — раздельные окна и бэкапы.
- **Snapshot перед обновлением**: всегда; для ZFS/LVM это секунды, откат — без потерь данных гостя.
- **Фиксация интерфейсов**: udev/systemd `.link` до обновления ядра.
- **Мониторинг во время работ**: `journalctl -fu pveproxy`, `tail -f /var/log/syslog`; для Ceph — `ceph -w` в отдельной вкладке.
- **Горизонт планирования EOL**: обновление начинать за 3–6 месяцев до EOL; на 18.10.2026 PVE 8/PBS 3 уже закрыты — приоритет на оставшиеся узлы.
- **Фиксированные окна патчинга**: квартальное окно для обновлений безопасности внутри ветки (`apt full-upgrade`).
- **Журнал изменений**: версии до/после, узлы, замечания чеклистов, инциденты — на уровень кластера.
- **Out-of-band доступ**: IPMI/iDRAC для каждого узла — веб-интерфейс может стать недоступен при обновлении `pveproxy`.
- **Аппаратный RAID1 для boot** — защита от отказа диска в окно обновления.
- **Hold на окно обслуживания**: `apt-mark hold pve-manager qemu-server` и т.п. на узлах, которые не должны уехать в фоне.

## Граничные случаи (Edge Cases)

- **Нехватка места во время dist-upgrade**: `No space left on device` на `/boot` или `/` — очистите кэш (`apt clean`), старые ядра (если текущее уже новое), освободите место; **не** прерывайте dpkg без плана доведения до конца.
- **Проприетарные модули (NVIDIA, HBA)**: проверить DKMS до обновления:
  ```bash
  dkms status
  # → nvidia/535.113.01, 6.8.12-1-pve, x86_64: installed
  dkms autoinstall   # после обновления ядра — пересборка
  ```
  Подробнее — [Управление ядром](./proxmox_kernel_management.md).
- **Смешанный кластер PVE 8/9**: live migration не поддерживается; HA-группы — только in-memory маппинг rules; не редактируйте HA-правила до полного обновления кластера.
- **ZFS replication во время обновления**: остановите scheduled replication на окно узла — снапшот может зафиксировать mid-upgrade состояние:
  ```bash
  pvesr list
  # → отключить задачу replication в GUI или pvesr disable <id>
  ```
- **Потеря кворума в 2-узловом кластере**: обновляйте только при наличии qdevice/witness; иначе после первого узла кворум упадёт.
- **Загрузка с устаревшего ядра**: проверьте порядок GRUB:
  ```bash
  grep -E 'menuentry|linux' /boot/grub/grub.cfg | head -20
  # → актуальное ядро должно быть default (grub-set-default / GRUB_DEFAULT)
  ```
- **APT pinning**: после обновления проверьте, что политика не блокирует пакеты Proxmox:
  ```bash
  apt policy pve-manager
  # → Candidate: версия из trixie, не «(none)»
  ```
- **Конфигфайлы при dist-upgrade**: системные (`/etc/lvm/lvm.conf` и др.) — в пользу maintainer; свои правки — merge вручную, diff не пропускать «на глаз».

## Дополнительная информация

### Связанные темы

- [Proxmox VE — Обзор и базовые концепции](./proxmox_overview.md)
- [Кластеризация и High Availability](./proxmox_cluster.md) — Maintenance Mode, HA arm/disarm, CRS
- [Proxmox Backup Server (PBS)](./proxmox_backup_server.md) — эксплуатация, datastore, S3
- [Управление ядром Linux в Proxmox](./proxmox_kernel_management.md) — DKMS, livepatch, initramfs
- [Хранилища Proxmox](./proxmox_storage.md) — snapshot'ы, Ceph на уровне PVE, replication
- [Автоматизация Proxmox через Ansible](./proxmox_ansible.md) — API-паттерны, снапшоты, inventory
- [Восстановление загрузки (Debian)](../Linux/Diagnostics/Troubleshooting/boot_failure_recovery.md)
- [GRUB: настройка и восстановление](../Linux/SystemAdministration/grub.md)

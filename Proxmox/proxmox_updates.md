---
Надёжность: 10 (SSoT + Проектный контекст 2026)
Свежесть: Актуально на июль 2026
---

# Обновление систем Proxmox

## Определения

**Proxmox Virtual Environment (PVE)** — платформа виртуализации с открытым исходным кодом на базе Debian.

**Proxmox Backup Server (PBS)** — специализированное решение для инкрементального резервного копирования.

**In-place Upgrade (Обновление на месте)** — процесс мажорного обновления ОС без переустановки, путем смены репозиториев в `apt` и выполнения полной модернизации.

## Основные концепции

### Типы репозиториев

1. **Enterprise Repository**: Платный, максимально стабильный. Требует активной подписки.
2. **No-Subscription Repository**: Рекомендуемый для домашних/тестовых лабораторий. Содержит те же пакеты, что и Enterprise, но с меньшим циклом тестирования.
3. **Test Repository**: Самые свежие пакеты для разработчиков. Не для продакшена.

### Безопасное обновление (Best Practices)

- **Терминальный мультиплексор**: При мажорном обновлении используйте SSH + `tmux` или `screen`. Веб-консоль GUI закроется при перезапуске `pveproxy`.
- **Свободное место**: Минимум 10 ГБ на корневом разделе (`/`).
- **Последовательность в кластере**:
  1. Миграция ВМ с обновляемого узла.
  2. Перевод узла в Maintenance Mode (для PVE 8+).
  3. Обновление пакетов.
  4. Перезагрузка.
- **Команды**: Всегда используйте `apt dist-upgrade` или `apt full-upgrade`. Обычный `apt upgrade` запрещен, так как он не умеет корректно обрабатывать зависимости ядра.

## Практические сценарии

### Настройка No-Subscription через CLI

Для использования Proxmox без подписки необходимо отключить платный репозиторий и добавить бесплатный.

1. Отключение Enterprise (закомментируйте строку):
   ```bash
   sed -i 's/^deb/#deb/g' /etc/apt/sources.list.d/pve-enterprise.list
   ```

2. Добавление No-Subscription (для PVE 8):
   ```bash
   echo "deb http://download.proxmox.com/debian/pve bookworm pve-no-subscription" > /etc/apt/sources.list.d/pve-install-repo.list
   ```

### Мажорное обновление (на примере PVE 7.4 -> 8.x)

1. **Диагностика**:
   ```bash
   pve7to8 --full
   # → System health check passed: OK
   ```

2. **Обновление репозиториев**:
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

### Специфика обновления кластера с Ceph

Перед обновлением узлов в кластере с Ceph необходимо предотвратить перестроение данных (rebalance) при перезагрузках.

1. Установка флагов (с любой ноды):
   ```bash
   ceph osd set noout
   ceph osd set noscrub
   ceph osd set nodeep-scrub
   # → set noout
   ```

2. После обновления и перезагрузки всех нод снимите флаги:
   ```bash
   ceph osd unset noout
   ceph osd unset noscrub
   ceph osd unset nodeep-scrub
   # → unset noout
   ```

## Диагностика и проверка

### Проверка версий после обновления
```bash
pveversion -v
# → proxmox-ve: 8.2.0 (running kernel: 6.8.4-2-pve)
# → pve-manager: 8.2.2 (running version: 8.2.2/e328e3b555091993)
```

### Проверка состояния сервисов
```bash
systemctl status pve-cluster pvedaemon pveproxy
# → ● pveproxy.service - PVE API Proxy Server
# →    Active: active (running) since ...
```

## Дополнительная информация

### Связанные темы

- [Proxmox VE — Обзор и базовые концепции](./proxmox_overview.md)
- [Proxmox Backup Server (PBS)](./proxmox_backup_server.md)
- [Кластеризация и High Availability в Proxmox](./proxmox_cluster.md)
